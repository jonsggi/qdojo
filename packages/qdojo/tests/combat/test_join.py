"""Outside builders on a local arena: register, sign, fight, get disclosed (AUD-027)."""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from qdojo.cli import main
from qdojo.combat import api, codec, export, live
from qdojo.combat import evaluate as E
from qdojo.combat import join as J
from qdojo.combat import readmodel as rm
from qdojo.combat.bot import Bot, Budget, policy_chooser
from qdojo.combat.codec import Op
from qdojo.combat.rules import PUBLIC_ARENA, by_version, candidate_1
from qdojo.qubic import schnorrq
from qdojo.qubic.tx import Transaction

LIMITS = J.Limits(reads_per_second=10_000, tx_per_second=1000, tx_burst=1000, max_outside_fighters=2)
FAST = {"reads_per_second": 10_000, "tx_per_second": 1000, "tx_burst": 1000}


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


def _cli(capsys, *argv):
    code = 0
    try:
        main(list(argv))
    except SystemExit as exc:
        code = exc.code
    out = capsys.readouterr()
    return code, f"{out.out}{out.err}{code if isinstance(code, str) else ''}"


def test_test_names_are_reserved_for_the_operators_keys(tmp_path, capsys):
    """docs/beta.md §3: names starting with test- are the operator's smoke tests,
    which community.py counts apart from builders; the gateway enforces it."""
    # beta.md §5 step 2: the smoke-test key's owner, printed without contacting any arena.
    code, out = _cli(capsys, "combat", "join", "--arena", "http://127.0.0.1:9", "--name", "test-smoke1",
                     "--key", str(tmp_path / "operator.seed"), "--show-key")
    _s, operator = J.load_or_make_key(tmp_path / "operator.seed")
    assert code == 0 and f"owner {operator.hex()}" in out, out
    rig = Rig(tmp_path, J.Limits(**FAST, operator_keys=[operator.hex()]))
    try:
        for name in ("test-bot", "Test-Pilot"):
            _s, _p, body = rig.register(name, tmp_path / f"{name}.seed")
            assert err(lambda: rig.http.post("/api/v1/join/register", body)) == (403, "name_reserved"), name
        _s, _p, smoke = rig.register("test-smoke1", tmp_path / "operator.seed")
        assert rig.http.post("/api/v1/join/register", smoke)["status"] == "new"
        assert "operator_keys" not in rig.http.get("/api/v1/join")["limits"]    # the list stays private
    finally:
        rig.srv.shutdown()
    path = tmp_path / "limits.json"
    path.write_text(json.dumps({"operator_keys": [operator.hex().upper()]}))
    assert J.Limits.load(path).operator_keys == [operator.hex()]
    path.write_text(json.dumps({"operator_keys": ["test-smoke1"]}))
    with pytest.raises(SystemExit, match="operator_keys"):
        J.Limits.load(path)


def test_the_per_address_limit_counts_an_ipv6_client_per_64(tmp_path):
    rig = Rig(tmp_path, J.Limits(**FAST, max_outside_fighters=16, registrations_per_ip_day=2))
    try:
        def register(name, ip):
            _s, _p, body = rig.register(name, tmp_path / f"{name}.seed")
            status, doc = rig.svc.post(["join", "register"], body, ip)
            return doc["error"]["code"] if status >= 400 else status
        assert register("v6one", "2001:db8:1:2::1") == 202
        assert register("v6two", "2001:db8:1:2::abcd") == 202
        assert register("v6three", "2001:db8:1:2:ffff::9") == "rate_limited"     # another address, the same /64
        assert register("v6next", "2001:db8:1:3::1") == 202                        # the next /64
        assert register("v4one", "198.51.100.7") == 202
        assert register("v4two", "::ffff:198.51.100.7") == 202                     # the same IPv4 address, mapped
        assert register("v4three", "198.51.100.7") == "rate_limited"
        assert register("v4next", "198.51.100.8") == 202                           # IPv4: the exact address
        stored = {r[0] for r in rig.svc.db.execute("SELECT ip FROM registrations")}
        assert stored == {"2001:db8:1:2::/64", "2001:db8:1:3::/64", "198.51.100.7", "198.51.100.8"}
    finally:
        rig.srv.shutdown()


def test_the_operator_revokes_a_registration_and_frees_its_place(tmp_path, capsys):
    rig = Rig(tmp_path, J.Limits(**FAST, max_outside_fighters=2, grant_qu=1_000_000, registrations_per_ip_day=5))
    inbox = str(rig.dir / "inbox.sqlite")
    try:
        keys = {}
        for name in ("First", "Second"):
            subseed, pub, body = rig.register(name, tmp_path / f"{name}.seed")
            keys[name] = (subseed, pub)
            assert rig.http.post("/api/v1/join/register", body)["status"] == "new"
        rig.tick()
        # The arena issues by the limits the API was started with: the cap and the grant it publishes.
        assert rig.arena.w.balances[keys["First"][1]] == 1_000_000
        _s, _p, third = rig.register("Third", tmp_path / "Third.seed")
        assert err(lambda: rig.http.post("/api/v1/join/register", third)) == (403, "arena_full")
        first = rig.http.get(f"/api/v1/join/status?owner={keys['First'][1].hex()}")
        fid = bytes.fromhex(first["fighter_id"])
        client = J.RemoteClient(rig.http, rig.info, *keys["First"], fid, tmp_path / "st")
        client.refresh()
        queued = rig.http.post("/api/v1/tx", {"tx": client.sign(Op.REGISTER_FIGHTER, 0, {
            "fighter_id": fid, "registry_version": 1}).hex()})["hash"]
        code, out = _cli(capsys, "combat", "registrations", "revoke", "First", "--inbox", inbox,
                         "--reason", "impersonating name")
        assert code == 0 and "First revoked (impersonating name)" in out and "1 of 2" in out, out
        # Its place is free, in the API and in the arena; its key can no longer send.
        assert rig.http.get("/api/v1/join")["outside_fighters"] == 1
        assert rig.http.post("/api/v1/join/register", third)["status"] == "new"
        rig.tick()
        assert rig.http.get("/api/v1/join/status?name=Third")["status"] == "active"
        st = rig.http.get(f"/api/v1/join/status?owner={keys['First'][1].hex()}")
        assert (st["status"], st["detail"]) == ("revoked", "impersonating name")
        assert rig.http.get(f"/api/v1/tx/{queued}")["status"] == "dropped"
        client.refresh()
        raw = client.sign(Op.WITHDRAW, 0, {})
        assert err(lambda: rig.http.post("/api/v1/tx", {"tx": raw.hex()})) == (403, "revoked")
        # The fighter stays in the record, labelled outside, and keeps its name.
        assert [e["label"] for e in J.load_outside(rig.dir)] == ["First", "Second", "Third"]
        _s, _p, again = rig.register("first", tmp_path / "again.seed")
        assert err(lambda: rig.http.post("/api/v1/join/register", again)) == (409, "name_taken")
        code, out = _cli(capsys, "combat", "registrations", "revoke", "First", "--inbox", inbox)
        assert code != 0 and "revoked already" in out
    finally:
        rig.srv.shutdown()


def test_a_registration_keeps_its_client_address_one_day(tmp_path, capsys):
    """The address serves only the per-address limit, which looks back 24 hours (docs/beta.md §8)."""
    rig = Rig(tmp_path, J.Limits(**FAST, max_outside_fighters=4))
    db = rig.svc.db

    def addresses():
        return [r[0] for r in db.execute("SELECT ip FROM registrations ORDER BY id")]

    def age(name):                                      # received a day and a second ago
        db.execute("UPDATE registrations SET received = received - ? WHERE name = ?", (24 * 3600 + 1, name))

    def register(name, ip):
        _s, _p, body = rig.register(name, tmp_path / f"{name}.seed")
        assert rig.svc.post(["join", "register"], body, ip)[0] == 202
    try:
        register("Alice", "203.0.113.7")
        rig.tick()
        assert addresses() == ["203.0.113.7"]
        age("Alice")
        register("Bob", "203.0.113.8")                  # a registration forgets addresses older than a day ...
        assert addresses() == [None, "203.0.113.8"]
        age("Bob")
        rig.tick()                                      # ... and so does every arena tick
        assert addresses() == [None, None]
        register("Carol", "2001:db8:5:6::7")
        assert addresses() == [None, None, "2001:db8:5:6::/64"]
        code, out = _cli(capsys, "combat", "registrations", "forget-addresses", "--inbox", str(rig.dir / "inbox.sqlite"))
        assert code == 0 and "cleared 1" in out          # when entry closes: all at once
        assert addresses() == [None, None, None]
    finally:
        rig.srv.shutdown()


# ---- the builder's client against an arena it does not control ------------------------------

ESC = "\x1b]0;pwned\x07\x1b[2K\r"
PUBLIC = by_version(PUBLIC_ARENA)


@pytest.fixture
def stub(tmp_path, monkeypatch):
    """A fake arena on 127.0.0.1 answering what a test puts in `routes`:
    (method, path) -> (status, JSON document, raw bytes, or a function of the handler)."""
    monkeypatch.setenv("QDOJO_COMBAT_HOME", str(tmp_path / "home"))
    routes = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_a):
            pass

        def do_GET(self):
            status, body = routes.get((self.command, self.path.split("?")[0]), (404, {"error": {"code": "not_found"}}))
            if callable(body):
                return body(self)
            raw = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            try:
                self.wfile.write(raw)
            except OSError:                                 # the client stopped reading (a refused large body)
                pass

        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            self.do_GET()

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    routes.update({("GET", "/data/combat/v1/manifest.json"): (200, {"semantic_version": PUBLIC.semantic_version,
                                                                   "ruleset_digest": PUBLIC.digest.hex()}),
                   ("GET", "/api/v1/chain/state"): (200, {"tick": 50})})
    yield f"http://127.0.0.1:{srv.server_address[1]}", routes
    srv.shutdown()


def _join_doc(n, cap):
    return {"schema": "qdojo.combat.api.join.v1", "enabled": True, "network_id": "00" * 32,
            "contract_id": "11" * 32, "ruleset_digest": PUBLIC.digest.hex(), "tiers": {"1": 5000},
            "outside_fighters": n, "limits": {"max_outside_fighters": cap, "grant_qu": 1_000_000}}


def _refusal(status, code, message="refused"):
    return status, {"schema": "qdojo.combat.api.error.v1", "error": {"status": status, "code": code, "message": message}}


def test_entry_is_read_as_the_site_reads_it(stub, tmp_path, capsys):
    """OPEN, FULL, CLOSED (join_disabled or join_closed only) or UNKNOWN, as the
    site's entryStatus; doctor and join agree, and join creates nothing it cannot use."""
    url, routes = stub
    cases = {
        "open": ((200, _join_doc(3, 16)), "PASS  arena entry: open: 3 of 16"),
        "full": ((200, _join_doc(16, 16)), "WARN  arena entry: full: 16 of 16"),
        "closed": (_refusal(404, "join_disabled"), "WARN  arena entry: closed (join_disabled)"),
        "api down": (_refusal(503, "api_down"), "WARN  arena entry: unknown (api_down)"),
        "proxy error": ((502, b"<html>Bad Gateway</html>"), "WARN  arena entry: unknown (HTTP 502)"),
    }
    for case, (answer, line) in cases.items():
        routes[("GET", "/api/v1/join")] = answer
        code, out = _cli(capsys, "combat", "doctor", "--arena", url, "--state", str(tmp_path / "bots"))
        assert code == 0 and line in out, (case, out)
    key = tmp_path / "me.seed"
    for answer, says in (((200, _join_doc(16, 16)), "every outside-fighter place"),
                         (_refusal(404, "join_disabled"), "entry is closed"),
                         (_refusal(503, "api_down"), "did not say whether entry is open")):
        routes[("GET", "/api/v1/join")] = answer
        code, out = _cli(capsys, "combat", "join", "--arena", url, "--name", "Builder", "--key", str(key),
                         "--register-only")
        assert code != 0 and says in out and "nothing was created" in out and not key.exists(), out
    # Entry reads as open, but the registration is refused: a clean message, never a traceback.
    routes[("GET", "/api/v1/join")] = (200, _join_doc(3, 16))
    routes[("POST", "/api/v1/join/register")] = _refusal(403, "join_closed")       # the public proxy refuses writes
    code, out = _cli(capsys, "combat", "join", "--arena", url, "--name", "Builder", "--key", str(key), "--register-only")
    assert code != 0 and "join_closed" in out and "nothing was created" in out and not key.exists(), out
    for refusal, says in ((_refusal(409, "name_taken"), "choose another --name"),
                          (_refusal(403, "arena_full"), "every outside-fighter place is taken"),
                          (_refusal(403, "name_reserved"), "names starting with 'test-' are the operator's"),
                          (_refusal(429, "rate_limited"), "try again tomorrow")):
        routes[("POST", "/api/v1/join/register")] = refusal
        code, out = _cli(capsys, "combat", "join", "--arena", url, "--name", "Builder", "--key", str(key),
                         "--register-only")
        assert code != 0 and refusal[1]["error"]["code"] in out and says in out, out
        assert "Traceback" not in out and key.exists()               # the key stays for the next attempt
    # No answer from the API behind the proxy: the registration may or may not have arrived.
    routes[("POST", "/api/v1/join/register")] = _refusal(503, "api_down")
    code, out = _cli(capsys, "combat", "join", "--arena", url, "--name", "Builder", "--key", str(key), "--register-only")
    assert code != 0 and "did not complete (api_down" in out and "run the same command again" in out and key.exists()


def test_text_from_the_arena_is_printed_escaped(stub, tmp_path, capsys):
    url, routes = stub
    routes[("GET", "/data/combat/v1/manifest.json")] = (200, {"semantic_version": PUBLIC.semantic_version + ESC,
                                                             "ruleset_digest": PUBLIC.digest.hex() + ESC})
    routes[("GET", "/api/v1/join")] = (200, {**_join_doc(3, 16), "outside_fighters": "3" + ESC})
    routes[("POST", "/api/v1/join/register")] = _refusal(429, "rate_limited" + ESC, "slow down" + ESC)
    _code, doctor = _cli(capsys, "combat", "doctor", "--arena", url, "--state", str(tmp_path / "bots"))
    _code, join = _cli(capsys, "combat", "join", "--arena", url, "--name", "Builder", "--key", str(tmp_path / "k.seed"),
                       "--register-only")
    for out in (doctor, join):
        assert "\x1b" not in out and "\x07" not in out and "\r" not in out, out
    assert "\\x1b]0;pwned\\x07" in doctor and "rate_limited\\x1b" in join


def test_a_response_is_bounded_in_size_and_time(stub):
    url, routes = stub
    routes[("GET", "/big")] = (200, b'{"pad": "' + b"x" * (3 * 1024 * 1024) + b'"}')
    with pytest.raises(OSError, match="larger than"):
        J.Http(url).get("/big")

    def drip(handler):                                  # headers at once, then a byte every 50 ms
        handler.send_response(200)
        handler.end_headers()
        try:
            for _ in range(400):
                handler.wfile.write(b" ")
                handler.wfile.flush()
                time.sleep(0.05)
        except OSError:
            pass
    routes[("GET", "/drip")] = (200, drip)
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        J.Http(url, timeout=5, deadline=1.0).get("/drip")
    assert time.monotonic() - started < 3
