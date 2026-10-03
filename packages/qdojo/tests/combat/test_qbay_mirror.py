"""The qbay-mirror backend: ownership mirrored from a mainnet QBAY collection (docs/nft.md §5.4).

Everything runs on recorded mainnet answers (tests/fixtures/qbay/mainnet.json)
through FixtureRpc, edited in place to simulate a QubicBay sale, a vanished
NFT, a changed creator or the RPC going down. No test touches the network.
"""
import json
from pathlib import Path

import pytest

from qdojo.combat import codec, invariants, live
from qdojo.combat import nft_qbay as Q
from qdojo.combat.codec import Code, Op
from qdojo.combat.devnet import Devnet, roles
from qdojo.combat.readmodel import rebuild
from qdojo.combat.sim import identity
from qdojo.qubic import qbay
from qdojo.qubic.rpc import FixtureRpc, RpcError

from .test_contract import ADMIN, KO_PLAN, play_fight, until_match, world  # noqa: F401

FIXTURE = Path(__file__).parent.parent / "fixtures" / "qbay" / "mainnet.json"
REBELS = [5497, 5499, 5500, 5582, 5589, 5590, 5591, 5592]      # BITE: Ocean Rebels (17), first eight
BUYER = identity("qubicbay-buyer")


class Chain(FixtureRpc):
    """Recorded answers plus edits: a sale, a vanished NFT, a creator change, an outage."""

    def __init__(self):
        super().__init__(json.loads(FIXTURE.read_text()))

    def _nft_key(self, nft_id):
        return (12, 7, qbay.nft_by_id_input(nft_id))

    def set_possessor(self, nft_id, who: bytes):
        raw = bytearray(self.answers[self._nft_key(nft_id)])
        raw[32:64] = who
        self.answers[self._nft_key(nft_id)] = bytes(raw)

    def set_creator(self, nft_id, who: bytes):
        raw = bytearray(self.answers[self._nft_key(nft_id)])
        raw[0:32] = who
        self.answers[self._nft_key(nft_id)] = bytes(raw)

    def vanish(self, nft_id):
        self.answers[self._nft_key(nft_id)] = bytes(248)


def config(**kw) -> Q.QbayConfig:
    doc = {"collection_id": 17, "nfts": REBELS, "collection_name": "BITE: Ocean Rebels", "poll_seconds": 10,
           "membership": "qubicbay-api+chain"}
    return Q.QbayConfig(**{**doc, **kw})


@pytest.fixture
def chain():
    return Chain()


@pytest.fixture
def reader(chain):
    return qbay.QbayReader(chain)


# ---- configuration, membership, validation ----------------------------------------------

def test_config_rules():
    with pytest.raises(Q.ConfigError):
        config(network="moon")
    with pytest.raises(Q.ConfigError):
        config(nfts=[1, 1])
    with pytest.raises(Q.ConfigError):
        config(map={"a": 5, "b": 5})
    with pytest.raises(Q.ConfigError):
        config(poll_seconds=0.5)
    with pytest.raises(Q.ConfigError):
        Q.QbayConfig.from_doc({"collection_id": 17, "nfts": [], "surprise": 1})
    c = config(map={"kappa": 5592})
    assert c.assign(["tanuki", "kappa", "tengu"]) == {"kappa": 5592, "tanuki": 5497, "tengu": 5499}
    assert c.rpc == "https://rpc.qubic.org" and c.stale_after == 30
    with pytest.raises(Q.ConfigError, match="has none"):
        config(nfts=[5497]).assign(["a", "b"])


def test_pin_collection(reader):
    g = Q.pin_collection(reader, 4, verify=False)                     # Garth's creator has one collection: chain only
    assert g["membership"] == "chain-creator" and len(g["nfts"]) == 200 and g["nfts"][0] == 1671
    with pytest.raises(Q.ConfigError, match="catalogue"):  # BITE's creator has 17 and 19: needs QubicBay's ids
        Q.pin_collection(reader, 17)
    r = Q.pin_collection(reader, 17, api_ids=REBELS)
    assert r["membership"] == "qubicbay-api+chain" and r["nfts"] == REBELS
    with pytest.raises(Q.ConfigError, match="royalty"):   # 5795 is BITE's too, but Ocean Elements (10%)
        Q.pin_collection(reader, 17, api_ids=REBELS + [5795])
    with pytest.raises(Q.ConfigError, match="does not exist"):
        Q.pin_collection(reader, 999)


def test_validate_failure_modes(reader):
    cfg = config()
    rep = Q.validate(reader, cfg, cfg.assign(["a", "b"]))
    assert rep["collection"].royalty == 5 and set(rep["nfts"]) == {5497, 5499}
    with pytest.raises(Q.ConfigError, match="does not exist"):            # collection not on chain
        Q.validate(reader, config(collection_id=999), {"a": 5497})
    with pytest.raises(Q.ConfigError, match="does not exist"):            # unknown NFT (past numberOfNFT)
        Q.validate(reader, cfg, {"a": 2_000_000})
    with pytest.raises(Q.ConfigError, match="creator differs"):           # an NFT of another collection
        Q.validate(reader, cfg, {"a": 1671})


# ---- the contract: AdminMirrorOwner (104) ------------------------------------------------

def mirror(w, fid, owner, seq, nft=5497, who=ADMIN, src=12, version=1, npc=0, amount=0):
    return w.send(who, Op.ADMIN_MIRROR_OWNER, amount, fighter_id=fid, registry_version=version, house_npc=npc,
                  source_contract=src, source_id=nft, owner=owner or bytes(32), mirror_seq=seq)


def test_mirror_owner_binds_sets_and_orders(world):  # noqa: F811
    fid, a, b = identity("fighter:m"), identity("holder:a"), identity("holder:b")
    world.mint(a, 10_000)
    world.mint(b, 10_000)
    assert mirror(world, fid, a, 1).ok
    c = world.contract
    assert c.assets[fid] == (1, False, (12).to_bytes(8, "little") + bytes(24), 5497)
    assert c.mirrors[fid] == (a, 1)
    _, _, kind, fields, _ = c.events[-1]
    assert kind == "OWNER_MIRRORED" and fields == (fid, 12, 5497, a, 1)
    assert world.send(b, Op.REGISTER_FIGHTER, fighter_id=fid, registry_version=1).code == Code.NOT_OWNER
    assert world.send(a, Op.REGISTER_FIGHTER, fighter_id=fid, registry_version=1).ok
    assert mirror(world, fid, b, 1).code == Code.STALE                       # seq must increase
    assert mirror(world, fid, b, 2).ok
    assert world.send(b, Op.REGISTER_FIGHTER, fighter_id=fid, registry_version=1).ok
    f = c.fighters[fid]
    assert (f.owner, f.operator, f.auth_version) == (b, b, 2)
    assert mirror(world, fid, None, 3).ok                                    # gone: ownership unavailable
    assert c.mirrors[fid] == (None, 3)
    assert world.send(b, Op.SET_OPERATOR, fighter_id=fid, new_operator=a, expected_auth_version=2).code \
        == Code.BAD_STATE
    world.check_conservation()


def test_mirror_owner_rejections(world):  # noqa: F811
    fid, other, a = identity("fighter:m1"), identity("fighter:m2"), identity("holder:a")
    assert mirror(world, fid, a, 1, who=identity("stranger")).code == Code.NOT_OWNER
    assert mirror(world, fid, a, 1, src=1).code == Code.BAD_BODY             # only QBAY (12) is a source
    assert mirror(world, fid, a, 0).code == Code.BAD_BODY
    assert mirror(world, fid, a, 1, npc=2).code == Code.BAD_BODY
    assert mirror(world, fid, a, 1, amount=3).code == Code.BAD_AMOUNT
    assert mirror(world, fid, a, 1).ok
    assert mirror(world, other, a, 1).code == Code.BAD_STATE                 # one NFT never backs two fighters
    assert mirror(world, fid, a, 2, nft=5499).code == Code.BAD_STATE         # nor is a fighter re-pointed
    # An asset-bound fighter is not mirrored, and a mirrored one is not re-bound to an asset.
    assert world.send(ADMIN, Op.ADMIN_BIND_ASSET, fighter_id=fid, registry_version=1, house_npc=0,
                      asset_issuer=identity("iss"), asset_name=codec.asset_name_u64("QF0001")).code == Code.BAD_STATE
    assert world.send(ADMIN, Op.ADMIN_REGISTER_ASSET, fighter_id=fid, registry_version=1, house_npc=0).code \
        == Code.BAD_STATE
    assert world.send(ADMIN, Op.ADMIN_BIND_ASSET, fighter_id=other, registry_version=1, house_npc=0,
                      asset_issuer=identity("iss"), asset_name=codec.asset_name_u64("QF0002")).ok
    assert mirror(world, other, a, 1, nft=5499).code == Code.BAD_STATE


def test_a_mid_fight_qubicbay_sale_pays_the_owner_who_entered(world):  # noqa: F811
    """Winnings go to the payout recipient each admission snapshots (the owner at
    entry), so a QubicBay sale mirrored mid-fight cannot redirect them."""
    from .test_contract import Player
    a_old, a_new = identity("holder:a-old"), identity("holder:a-new")
    fa = identity("fighter:qa")
    world.mint(a_old, 1_000_000)
    world.mint(a_new, 1_000_000)
    assert mirror(world, fa, a_old, 1).ok
    assert world.send(a_old, Op.REGISTER_FIGHTER, fighter_id=fa, registry_version=1).ok
    b = Player(world, "qb")
    pa = Player.__new__(Player)
    pa.w, pa.fid, pa.owner, pa.operator = world, fa, a_old, a_old
    assert pa.enter().ok and b.enter().ok
    fight_id = until_match(world, pa, b)
    assert mirror(world, fa, a_new, 2).ok                                    # sold on QubicBay mid-fight
    result = play_fight(world, fight_id, pa, KO_PLAN, b, None)              # b never commits: a wins
    fight = world.contract.fights[fight_id]
    assert result["kind"] == "FORFEIT" and result["winner"] == fight.slot_of(fa)
    credits = world.contract.ledger.credits
    assert credits.get(a_old) == 1900 and credits.get(a_new, 0) == 0
    # After the fight the old owner can no longer act; the new one registers and takes over.
    assert pa.enter().code == Code.NOT_OWNER
    assert world.send(a_new, Op.REGISTER_FIGHTER, fighter_id=fa, registry_version=1).ok
    world.check_conservation()


# ---- the arena -------------------------------------------------------------------------

LINEUP = [{"label": "tanuki", "policy": "reader-v1"}, {"label": "kappa", "policy": "kicker-v1"},
          {"label": "tengu", "policy": "mixed-v1"}]


def arena(tmp_path, chain, cfg=None, poll=10, **kw):
    tmp_path.mkdir(parents=True, exist_ok=True)
    p = tmp_path / "qbay.json"
    p.write_text(json.dumps((cfg or config()).doc()))
    return live.Arena(tmp_path / "net", LINEUP, deterministic=True, seed=7, nft_backend="qbay-mirror",
                      qbay_config=p, qbay_reader=qbay.QbayReader(chain), qbay_poll_ticks=poll, log=lambda m: None,
                      **kw)


def steps(a, n):
    for _ in range(n):
        a.step()
        bad = invariants.check(a.w)
        assert not bad, bad


def test_arena_binds_fighters_to_their_nfts(tmp_path, chain):
    a = arena(tmp_path, chain)
    led, c = a.w.nft, a.w.contract
    assert led.backend == "qbay-mirror" and led.source["collection_id"] == 17 and led.source["royalty_percent"] == 5
    toks = sorted(led.tokens.values(), key=lambda t: t.serial)
    assert [t.mirror["nft_id"] for t in toks] == [5497, 5499, 5500]
    owners = {t.mirror["nft_id"]: qbay.identity(t.owner)[:10] for t in toks}
    assert owners == {5497: "ZMFCIJUMHN", 5499: "MURATPTBJD", 5500: "MURATPTBJD"}
    t0 = toks[0]
    assert t0.manager == "QBAY" and t0.metadata["qbay"]["cid"].startswith("bafkrei")
    assert t0.metadata["qbay"]["url"] == "https://qubicbay.io/nft/5497"
    for t in toks:                                     # the contract got AdminMirrorOwner and the owner registered
        assert c.mirrors[t.fighter_id] == (t.owner, 1) and c.fighters[t.fighter_id].owner == t.owner
    assert not invariants.check(a.w)
    a.close()


def test_market_writes_are_refused(tmp_path, chain):
    a = arena(tmp_path, chain)
    fid = next(iter(a.w.nft.tokens))
    owner = a.nfts.owner(fid)
    for receipt in (a.nfts.ask(owner, fid, 10), a.nfts.bid(BUYER, fid, 10), a.nfts.transfer(owner, fid, BUYER)):
        r = a.nfts.poll(receipt)
        assert r["code"] == "TRADE_ON_QUBICBAY" and "qubicbay.io/nft/5497" in r["detail"]
    # The ledger itself refuses too (a transaction that reached it some other way).
    r = a.w.nft_call(owner, "ask", {"fighter_id": fid.hex(), "price": 10})
    assert r["code"] == "TRADE_ON_QUBICBAY"
    r = a.w.nft_call(a.nfts.issuer, "issue", {"fighter_id": identity("x").hex(), "to": owner.hex()})
    assert r["code"] == "TRADE_ON_QUBICBAY"
    assert a.nfts.book(fid) == {"asks": [], "bids": []} and a.nfts.sales() == []
    a.close()


def test_sale_outage_vanish_and_replay(tmp_path, chain):
    a = arena(tmp_path, chain)
    fid = a.nfts.fighter_of(5497)
    old = a.nfts.owner(fid)
    steps(a, 25)
    assert a.mirror.status()["status"] == "live" and a.mirror.state["polls"] >= 2
    # A QubicBay sale: the possessor of NFT 5497 changes on mainnet.
    chain.set_possessor(5497, BUYER)
    steps(a, 15)
    tok = a.w.nft.tokens[fid]
    assert tok.owner == BUYER and tok.mirror["seq"] == 2 and a.w.contract.mirrors[fid] == (BUYER, 2)
    for _ in range(400):                               # the new holder registers once the fighter is idle
        if a.w.contract.fighters[fid].owner == BUYER:
            break
        steps(a, 1)
    steps(a, 1)
    assert a.w.contract.fighters[fid].owner == BUYER and a.bots[fid].wallet == BUYER   # registered, new bot
    hist = a.nfts.history(fid)
    assert [e["kind"] for e in hist] == ["MIRROR_BIND", "MIRROR"] and hist[1]["from"] == old.hex()
    assert a.w.nft.ownership(fid)[-1][1:] == (old, BUYER)
    # The RPC goes down: last known owners stay, the data turns stale.
    clock = {"t": a.mirror.clock()}
    a.mirror.clock = lambda: clock["t"]
    chain.down = True
    chain.set_possessor(5497, identity("not-seen"))
    clock["t"] += 100
    steps(a, 20)
    st = a.mirror.status()
    assert st["status"] == "stale" and st["stale"] and st["consecutive_failures"] >= 1 and "down" in st["last_error"]
    assert a.w.nft.tokens[fid].owner == BUYER
    # Back up; NFT 5499 vanishes (a zero row): marked missing only after two polls.
    chain.down = False
    chain.set_possessor(5497, BUYER)
    chain.vanish(5499)
    gone = a.nfts.fighter_of(5499)
    steps(a, 10)
    assert a.nfts.owner(gone) is not None
    steps(a, 10)
    assert a.nfts.owner(gone) is None and a.w.nft.tokens[gone].mirror["missing"]
    assert a.w.contract.mirrors[gone][0] is None and a.w.owners.get(gone) is None
    assert a.mirror.status()["status"] == "live"
    # Replay: a restart reads the journal alone. A reader that raises proves no network is touched.
    a.save()
    led, c = a.w.nft, a.w.contract
    digest, owners = c.event_digest, {f: (t.owner, dict(t.mirror)) for f, t in led.tokens.items()}
    a.close()

    class NoNetwork:
        def __getattr__(self, name):
            raise AssertionError("replay touched the network")
    (tmp_path / "net" / "snapshot.pickle").unlink(missing_ok=True)
    net = Devnet(tmp_path / "net")
    assert net.restart["mode"] == "replay" or net.restart["mode"].startswith("full")
    assert net.world.contract.event_digest == digest
    assert {f: (t.owner, dict(t.mirror)) for f, t in net.world.nft.tokens.items()} == owners
    assert not invariants.check(net.world)
    b = live.Arena(tmp_path / "net", LINEUP, deterministic=True, nft_backend="qbay-mirror",
                   qbay_reader=NoNetwork(), qbay_poll_ticks=10**9, log=lambda m: None)
    assert b.w.contract.event_digest == digest and b.nfts.owner(fid) == BUYER
    b.close()


def test_restart_needs_no_network_and_flags_stale(tmp_path, chain):
    a = arena(tmp_path, chain)
    steps(a, 12)
    a.save()
    a.close()
    chain.down = True
    b = live.Arena(tmp_path / "net", LINEUP, deterministic=True, nft_backend="qbay-mirror",
                   qbay_reader=qbay.QbayReader(chain), qbay_poll_ticks=5, log=lambda m: None)
    steps(b, 6)
    st = b.mirror.status()
    assert st["status"] == "stale" and st["last_ok_at"] is None
    assert all(b.nfts.owner(f) is not None for f in b.w.nft.tokens)
    b.close()


def test_unmapped_nft_and_creator_mismatch(tmp_path, chain):
    a = arena(tmp_path, chain)
    seen = []
    n = Q.apply_observations(a.w, a.nfts.issuer, roles()["admin"], [Q.Observation(1671, BUYER, 1)], log=seen.append)
    assert n == 0 and "not mapped" in seen[0]
    assert a.nfts.fighter_of(1671) is None and a.nfts.nft_of(identity("nobody")) is None
    # The chain no longer matches the configured collection: nothing is applied, the status says so.
    fid = a.nfts.fighter_of(5500)
    chain.set_creator(5500, identity("someone-else"))
    chain.set_possessor(5500, BUYER)
    steps(a, 12)
    st = a.mirror.status()
    assert st["status"] == "mismatch" and "5500" in st["mismatch"]
    assert a.nfts.owner(fid) != BUYER
    a.close()


def test_arena_refuses_a_collection_that_does_not_match(tmp_path, chain):
    with pytest.raises(SystemExit, match="creator differs"):
        arena(tmp_path, chain, cfg=config(nfts=[1671, 1672, 1673]))
    with pytest.raises(SystemExit, match="does not exist"):
        arena(tmp_path / "x", chain, cfg=config(collection_id=999))
    chain.down = True
    with pytest.raises(SystemExit, match="down"):
        arena(tmp_path / "y", chain)
    with pytest.raises(SystemExit, match="qbay-config"):
        live.Arena(tmp_path / "z", LINEUP, nft_backend="qbay-mirror", log=lambda m: None)


def test_export_read_model_and_api(tmp_path, chain):
    out = tmp_path / "web" / "combat" / "v1"
    p = tmp_path / "qbay.json"
    p.write_text(json.dumps(config().doc()))
    a = live.run(tmp_path / "net", LINEUP, out, tick_seconds=0, export_every=20, ticks=60, log=lambda m: None,
                 deterministic=True, seed=3, nft_backend="qbay-mirror", qbay_config=p,
                 qbay_reader=qbay.QbayReader(chain), qbay_poll_ticks=10)
    index = json.loads((out / "index.json").read_text())
    dep = index["deployment"]
    assert dep["nft_backend"] == "qbay-mirror" and dep["mirror"]["collection_id"] == 17
    assert dep["mirror"]["status"] == "live" and dep["mirror"]["network"] == "mainnet"
    fid = a.nfts.fighter_of(5497)
    asset = dep["fighters"][fid.hex()]["asset"]
    assert asset["mirror"]["nft_id"] == 5497 and asset["qbay"]["url"] == "https://qubicbay.io/nft/5497"
    coll = json.loads((out / "nfts.json").read_text())
    assert coll["collection"]["mirror"]["collection_url"] == "https://qubicbay.io/collections/17"
    tok = json.loads((out / "nfts" / f"{fid.hex()}.json").read_text())
    assert tok["manager"] == "QBAY" and tok["mirror"]["nft_id"] == 5497 and tok["mirror_status"]["status"] == "live"
    assert tok["metadata"]["qbay"]["cid"] == "bafkreicsxnpmddpz4ed6mcupmvkvywranzq7jkokhzddob76o35xwxzcam"
    # The read model rebuilds the same tokens from the journal, and the API serves them.
    db = tmp_path / "rm.sqlite"
    rebuild(tmp_path / "net", db, out, log=lambda m: None)
    from qdojo.combat import api, readmodel as rm
    r = api.Reader(rm.connect(db, readonly=True))
    doc = r.nft(fid.hex())
    assert doc["mirror"]["nft_id"] == 5497 and doc["manager"] == "QBAY" and doc["mirror_status"]["source"] == "QBAY"
    assert [e["kind"] for e in doc["history"]] == ["MIRROR_BIND"] and doc["book"] == {"asks": [], "bids": []}
    page = r.nfts({})
    assert page["total"] == 3 and page["mirror_status"]["collection_id"] == 17
    own = r.c.execute("SELECT to_owner FROM ownership WHERE fighter_id = ?", (fid.hex(),)).fetchall()
    assert [tuple(x) for x in own] == [(a.nfts.owner(fid).hex(),)]
