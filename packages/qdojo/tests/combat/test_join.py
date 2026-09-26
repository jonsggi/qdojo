"""Outside builders on a local arena: register, sign, fight, get disclosed (AUD-027)."""
import json
import threading

import pytest

from qdojo.combat import api, codec, export, live
from qdojo.combat import evaluate as E
from qdojo.combat import join as J
from qdojo.combat import readmodel as rm
from qdojo.combat.bot import Bot, Budget, policy_chooser
from qdojo.combat.codec import Op
from qdojo.combat.rules import candidate_1
from qdojo.qubic import schnorrq
from qdojo.qubic.tx import Transaction

LIMITS = J.Limits(reads_per_second=10_000, tx_per_second=1000, tx_burst=1000, max_outside_fighters=2)


class Rig:
    def __init__(self, tmp, limits=LIMITS):
        self.dir = tmp / "arena"
        self.dir.mkdir()
        inbox = self.dir / "inbox.sqlite"
        lineup = [{"label": "house-a", "policy": "scout-v1"}, {"label": "house-b", "policy": "kicker-v1"}]
        self.arena = live.Arena(self.dir, lineup, seed=1, deterministic=True, join_inbox=inbox, log=lambda m: None)
        self.out = tmp / "web" / "combat" / "v1"
        self.export()
        self.fl = rm.Follower(self.dir, tmp / "rm.sqlite", self.out, log=lambda m: None)
        self.svc = J.JoinService(inbox, limits)
        self.svc.attach(self.fl)
        self.fl.step()
        self.srv = api.Server(("127.0.0.1", 0), tmp / "rm.sqlite", self.out, join=self.svc, follower=self.fl)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.http = J.Http(f"http://127.0.0.1:{self.srv.server_address[1]}")
        self.info = self.http.get("/api/v1/join")

    def export(self):
        export.export_all(self.arena.w.contract, self.out, keep=20, deployment=self.arena.deployment(1.5))

    def tick(self, n=1):
        for _ in range(n):
            self.arena.step()
        self.fl.step()

    def register(self, name, key_path):
        subseed, pub = J.load_or_make_key(key_path)
        t = self.fl.replica.tick
        digest = J.register_digest(self.arena.w.manifest.network_id, self.arena.w.manifest.contract_id, pub, name, t)
        body = {"name": name, "public_key": pub.hex(), "tick": t, "signature": schnorrq.sign(subseed, pub, digest).hex()}
        return subseed, pub, body


@pytest.fixture
def rig(tmp_path):
    r = Rig(tmp_path)
    yield r
    r.srv.shutdown()


def err(fn):
    with pytest.raises(J.HttpError) as e:
        fn()
    return e.value.status, e.value.code


def test_an_outside_bot_registers_signs_fights_and_is_disclosed(rig, tmp_path):
    subseed, pub, body = rig.register("Outsider", tmp_path / "me.seed")
    assert (tmp_path / "me.seed").stat().st_mode & 0o777 == 0o600
    assert rig.http.post("/api/v1/join/register", body)["status"] == "new"
    rig.tick()
    st = rig.http.get(f"/api/v1/join/status?owner={pub.hex()}")
    assert st["status"] == "active"
    fid = bytes.fromhex(st["fighter_id"])
    assert rig.arena.w.balances[pub] == LIMITS.grant_qu
    client = J.RemoteClient(rig.http, rig.info, subseed, pub, fid, tmp_path / "state")
    client.refresh()
    assert client.state["fighter"] is None                 # issued, not yet registered on chain
    receipt = client.send(Op.REGISTER_FIGHTER, fighter_id=fid, registry_version=1)
    result = None
    for _ in range(6):
        rig.tick()
        client.refresh()
        result = client.poll(receipt)
        if result is not None:
            break
    assert result is not None and result.code.name == "OK"
    rules = candidate_1()
    bot = Bot(client, rules, fid, pub, pub, policy_chooser(rules, E.policy_by_name("mixed-v1"), b"\1" * 32),
              Budget(ruleset_digest=rules.digest.hex(), max_stake=5000, max_total_escrow=20000), tmp_path / "state")
    c = rig.arena.w.contract
    for _ in range(400):
        client.refresh()
        bot.step()
        rig.tick()
        if any(f.phase == "DONE" and fid in (f.context.participant_a.fighter_id, f.context.participant_b.fighter_id)
               for f in c.fights.values()):
            break
    mine = [f for f in c.fights.values() if fid in (f.context.participant_a.fighter_id, f.context.participant_b.fighter_id)]
    assert any(f.phase == "DONE" and f.result["kind"] == "COMBAT" for f in mine), "a fought result, not a forfeit"
    assert all(len(f.rounds) for f in mine if f.phase == "DONE")
    # Disclosed as outside in the export and the API; the house stays house.
    rig.export()
    rig.fl.step()
    doc = json.loads((rig.out / "fighters" / f"{fid.hex()}.json").read_text())
    assert doc["origin"] == "outside" and doc["driver"] == "builder" and doc["name"] == "Outsider"
    board = {f["name"]: f for f in rig.http.get("/api/v1/leaderboard")["fighters"]}
    assert board["Outsider"]["origin"] == "outside" and board["house-a"]["origin"] == "house"
    # A restart keeps the outside fighter labelled, with or without joining enabled.
    again = live.Arena(rig.dir, [{"label": "house-a", "policy": "scout-v1"}, {"label": "house-b", "policy": "kicker-v1"}],
                       seed=1, deterministic=True, log=lambda m: None)
    assert again.deployment(1.5)["fighters"][fid.hex()]["origin"] == "outside"


def test_what_the_server_refuses(rig, tmp_path):
    subseed, pub, body = rig.register("Tester", tmp_path / "k.seed")
    # A tampered registration does not verify.
    assert err(lambda: rig.http.post("/api/v1/join/register", {**body, "name": "Other"})) == (401, "bad_signature")
    assert err(lambda: rig.http.post("/api/v1/join/register", {**body, "name": "no spaces"}))[1] == "bad_name"
    assert err(lambda: rig.http.post("/api/v1/join/register", {**body, "tick": body["tick"] + 10_000}))[1] == "stale"
    # A house name is taken.
    _s, _p, dup = rig.register("house-a", tmp_path / "k2.seed")
    assert err(lambda: rig.http.post("/api/v1/join/register", dup)) == (409, "name_taken")
    assert rig.http.post("/api/v1/join/register", body)["status"] == "new"
    # Transactions before the fighter is issued are refused.
    client = J.RemoteClient(rig.http, rig.info, subseed, pub, J.fighter_id_for("Tester"), tmp_path / "st")
    client.refresh()
    raw = client.sign(Op.REGISTER_FIGHTER, 0, {"fighter_id": J.fighter_id_for("Tester"), "registry_version": 1})
    assert err(lambda: rig.http.post("/api/v1/tx", {"tx": raw.hex()})) == (403, "not_registered")
    rig.tick()
    client.refresh()
    # Admin opcodes, oversized attachments, forged signatures, stale ticks, wrong contract.
    admin = client.sign(Op.ADMIN_RETIRE_RULESET, 0, {"ruleset_digest": bytes(32)})
    assert err(lambda: rig.http.post("/api/v1/tx", {"tx": admin.hex()})) == (403, "op_not_allowed")
    big = client.sign(Op.WITHDRAW, 10**7, {})
    assert err(lambda: rig.http.post("/api/v1/tx", {"tx": big.hex()})) == (400, "amount_cap")
    ok = bytearray(client.sign(Op.WITHDRAW, 0, {}))
    ok[-1] ^= 1
    assert err(lambda: rig.http.post("/api/v1/tx", {"tx": ok.hex()})) == (401, "bad_signature")
    frame = codec.encode_frame(Op.WITHDRAW, 99, {})
    old = Transaction(pub, rig.arena.w.manifest.contract_id, 0, 1 + 10**6, J.INPUT_TYPE, frame).sign(subseed).payload()
    assert err(lambda: rig.http.post("/api/v1/tx", {"tx": old.hex()})) == (400, "stale")
    wrong = Transaction(pub, bytes(32), 0, rig.fl.replica.tick, J.INPUT_TYPE, frame).sign(subseed).payload()
    assert err(lambda: rig.http.post("/api/v1/tx", {"tx": wrong.hex()})) == (400, "wrong_contract")
    assert err(lambda: rig.http.post("/api/v1/tx", {"tx": "zz"}))[1] == "bad_tx"
    # One fighter per key; the arena's cap on outside fighters.
    _s, _p, second = rig.register("Tester2", tmp_path / "k.seed")
    assert err(lambda: rig.http.post("/api/v1/join/register", second)) == (409, "one_per_key")
    _s, _p, third = rig.register("Third", tmp_path / "k3.seed")
    assert rig.http.post("/api/v1/join/register", third)["status"] == "new"
    _s, _p, fourth = rig.register("Fourth", tmp_path / "k4.seed")
    assert err(lambda: rig.http.post("/api/v1/join/register", fourth)) == (403, "arena_full")


def test_rate_limits_per_key(tmp_path):
    rig = Rig(tmp_path, J.Limits(reads_per_second=10_000, tx_burst=3, tx_per_second=0.001))
    try:
        subseed, pub, body = rig.register("Burst", tmp_path / "b.seed")
        rig.http.post("/api/v1/join/register", body)
        rig.tick()
        client = J.RemoteClient(rig.http, rig.info, subseed, pub, J.fighter_id_for("Burst"), tmp_path / "s")
        client.refresh()
        for _ in range(3):
            rig.http.post("/api/v1/tx", {"tx": client.sign(Op.WITHDRAW, 0, {}).hex()})
        assert err(lambda: rig.http.post("/api/v1/tx", {"tx": client.sign(Op.WITHDRAW, 0, {}).hex()})) == \
            (429, "rate_limited")
    finally:
        rig.srv.shutdown()


def test_join_is_off_unless_enabled(tmp_path):
    arena = live.Arena(tmp_path / "arena", [{"label": "a", "policy": "scout-v1"}], seed=1, deterministic=True,
                       log=lambda m: None)
    assert arena.inbox is None and not (tmp_path / "arena" / "inbox.sqlite").exists()
    out = tmp_path / "web" / "combat" / "v1"
    export.export_all(arena.w.contract, out, deployment=arena.deployment(1.5))
    rm.rebuild(arena.dir, tmp_path / "rm.sqlite", out, log=lambda m: None)
    srv = api.Server(("127.0.0.1", 0), tmp_path / "rm.sqlite", out)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        http = J.Http(f"http://127.0.0.1:{srv.server_address[1]}")
        assert err(lambda: http.get("/api/v1/join")) == (404, "join_disabled")
        assert err(lambda: http.post("/api/v1/tx", {"tx": ""}))[0] == 405
    finally:
        srv.shutdown()
