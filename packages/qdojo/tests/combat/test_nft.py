"""Fighter NFTs (docs/nft.md): the ledger's rules, determinism across replay,
snapshots and the read model, the port both backends implement, the arena's
use of it, and the frozen-art pipeline."""
import inspect
import json
import shutil
import subprocess

import pytest

from qdojo.combat import devnet, invariants, live, nft, nft_freeze, nft_qubic
from qdojo.combat import readmodel as rm
from qdojo.combat.codec import Op
from qdojo.combat.contract import development_manifest
from qdojo.combat.rules import candidate_1
from qdojo.combat.sim import World, identity

RULES = candidate_1()
ADMIN, HOUSE, DEV, SHARE = (identity(x) for x in ("n-admin", "n-house", "n-dev", "n-share"))
ISSUER, ESCROW = identity("n-issuer"), identity("n-escrow")
ALICE, BOB, CAROL, CREATOR = (identity(x) for x in ("alice", "bob", "carol", "creator"))


def _world():
    w = World(development_manifest(RULES, ADMIN, HOUSE, DEV, SHARE))
    w.mint(ADMIN, 10**12)
    for who in (ALICE, BOB, CAROL):
        w.mint(who, 10**7)
    nf = nft.SimFighterNFTs(w)
    assert nf.genesis(ISSUER, HOUSE, ESCROW)["code"] == "OK"
    return w, nf


def _mint(w, nf, label, owner=ALICE, creator=CREATOR, register=False):
    fid = nf.id_for(label)
    r = nf.poll(nf.issue(ISSUER, fid, owner, creator=creator))
    assert r["code"] == "OK", r
    if register:
        w.send(ADMIN, Op.ADMIN_REGISTER_ASSET, fighter_id=fid, registry_version=1, house_npc=0)
        assert w.send(owner, Op.REGISTER_FIGHTER, fighter_id=fid, registry_version=1).ok
    return fid


def code(nf, receipt):
    return nf.poll(receipt)["code"]


# ---- the lifecycle ----------------------------------------------------------------

def test_mint_names_shares_and_issuer_rules():
    w, nf = _world()
    fid = _mint(w, nf, "a")
    t = nf.token(fid)
    assert (t["name"], t["serial"], t["shares"], t["owner"], t["possessor"]) == ("QF00001", 1, 1, ALICE.hex(), ALICE.hex())
    assert w.owners[fid] == ALICE                                    # the contract sees the owner
    assert code(nf, nf.issue(ALICE, nf.id_for("x"), ALICE)) == "NOT_ISSUER"
    assert code(nf, nf.issue(ISSUER, fid, BOB)) == "DUPLICATE"
    assert code(nf, nf.issue(ISSUER, nf.id_for("y"), BOB, name="qf1")) == "BAD_NAME"
    assert code(nf, nf.issue(ISSUER, nf.id_for("y"), BOB, name="1ABC")) == "BAD_NAME"
    assert code(nf, nf.issue(ISSUER, nf.id_for("y"), BOB, name="TOOLONG1")) == "BAD_NAME"
    assert code(nf, nf.issue(ISSUER, nf.id_for("y"), BOB, name="QF00001")) == "DUPLICATE"
    assert nft.asset_name(36 ** 5 - 1) == "QFZZZZZ" and nft.name_u64("QF00001") == int.from_bytes(b"QF00001\0", "little")
    assert w.nft_call(ISSUER, "genesis", {"issuer": ISSUER.hex(), "house": HOUSE.hex(),
                                          "escrow": ESCROW.hex()})["code"] == "DUPLICATE"


def test_ask_bid_sale_pays_seller_fee_royalty_and_refunds_the_overbid():
    w, nf = _world()
    fid = _mint(w, nf, "a")
    b0 = dict(w.balances)
    assert code(nf, nf.ask(ALICE, fid, 10_000)) == "OK"
    assert code(nf, nf.bid(BOB, fid, 9_000)) == "OK"                # rests below the ask, escrowed
    assert w.balances[ESCROW] == 9_000 and w.balances[BOB] == b0[BOB] - 9_000
    r = nf.poll(nf.bid(CAROL, fid, 12_000))                          # crosses: trades at the ask (maker) price
    assert r["code"] == "OK" and r["sale"]["price"] == 10_000
    fee, royalty = 10_000 * 250 // 10_000, 10_000 * 250 // 10_000
    assert w.balances[ALICE] == b0[ALICE] + 10_000 - fee - royalty
    assert w.balances[HOUSE] == b0.get(HOUSE, 0) + fee and w.balances[CREATOR] == royalty
    assert w.balances[CAROL] == b0[CAROL] - 10_000                   # the 2 000 over the ask came back
    assert nf.owner(fid) == CAROL and w.owners[fid] == CAROL
    assert w.balances[ESCROW] == 9_000                               # Bob's bid still rests
    assert invariants.check(w) == [] and w.total() == w.minted
    # Carol lists; Bob's resting bid is the maker: the sale is at Bob's price.
    r = nf.poll(nf.ask(CAROL, fid, 8_000))
    assert r["sale"]["price"] == 9_000 and nf.owner(fid) == BOB
    kinds = [e["kind"] for e in nf.history(fid)]
    assert kinds == ["MINT", "ASK", "BID", "BID", "SALE", "ASK", "SALE"]
    assert [(f.hex() if f else None, t.hex()) for _, f, t in w.nft.ownership(fid)] == [
        (None, ALICE.hex()), (ALICE.hex(), CAROL.hex()), (CAROL.hex(), BOB.hex())]


def test_no_royalty_when_the_creator_sells_and_orders_need_the_holder():
    w, nf = _world()
    fid = _mint(w, nf, "a", owner=ALICE, creator=ALICE)
    assert code(nf, nf.ask(BOB, fid, 5_000)) == "NOT_OWNER"
    assert code(nf, nf.bid(ALICE, fid, 5_000)) == "SELF_TRADE"
    assert code(nf, nf.ask(ALICE, fid, 0)) == "BAD_PRICE"
    assert code(nf, nf.cancel_ask(ALICE, fid)) == "NO_ORDER"
    nf.ask(ALICE, fid, 5_000)
    r = nf.poll(nf.bid(BOB, fid, 5_000))
    assert r["sale"]["royalty"] == 0 and r["sale"]["fee"] == 125


def test_bids_escrow_replace_cancel_and_fail_without_funds():
    w, nf = _world()
    fid = _mint(w, nf, "a")
    start = w.balances[BOB]
    nf.bid(BOB, fid, 1_000)
    nf.bid(BOB, fid, 3_000)                                          # replaces: net 3 000 held
    assert w.balances[BOB] == start - 3_000 and len(nf.book(fid)["bids"]) == 1
    assert code(nf, nf.cancel_bid(BOB, fid)) == "OK" and w.balances[BOB] == start
    assert code(nf, nf.cancel_bid(BOB, fid)) == "NO_ORDER"
    assert code(nf, nf.bid(BOB, fid, 10**8)) == "INSUFFICIENT_FUNDS"  # more than Bob has
    assert w.balances[BOB] == start and w.balances.get(ESCROW, 0) == 0
    w.nft.policy = nft.NFTPolicy(max_bids=1)
    nf.bid(BOB, fid, 10)
    assert code(nf, nf.bid(CAROL, fid, 20)) == "BOOK_FULL"


def test_a_busy_fighter_cannot_change_hands_until_it_is_idle():
    """Transfers only between contests (docs/nft.md §2): a transfer is refused
    while the fighter is queued; a crossing sale waits and settles at the first
    END_TICK it is idle; the new owner re-registers; the record stays."""
    w, nf = _world()
    fid = _mint(w, nf, "a", register=True)
    f = w.contract.fighters[fid]
    r = w.send(ALICE, Op.QUEUE_ENTER, 1000, fighter_id=fid, auth_version=1, ruleset_digest=RULES.digest,
               timing_profile_id=1, fee_profile_id=1, tier_id=1, max_gap=200, expires_tick=w.tick + 45)
    assert r.ok and f.lock == "QUEUED"
    assert code(nf, nf.transfer(ALICE, fid, BOB)) == "LOCKED"
    nf.ask(ALICE, fid, 5_000)
    r = nf.poll(nf.bid(BOB, fid, 5_000))
    assert r["code"] == "OK" and r.get("deferred") and fid in w.nft.crossed and nf.owner(fid) == ALICE
    assert code(nf, nf.settle(CAROL, fid)) == "LOCKED"
    assert invariants.check(w) == []
    while f.lock != "IDLE":                                          # the queue entry expires
        w.end()
    assert nf.owner(fid) == BOB and w.nft.sales[-1]["price"] == 5_000
    assert w.nft.sales[-1]["tick"] == w.tick - 1                     # settled by END_TICK
    record = dict(f.record)
    assert w.send(BOB, Op.REGISTER_FIGHTER, fighter_id=fid, registry_version=1).ok
    assert (f.owner, f.operator, f.auth_version, f.record) == (BOB, BOB, 2, record)
    assert invariants.check(w) == []


def test_gift_transfer_fee_reservation_and_custody():
    w, nf = _world()
    fid = _mint(w, nf, "a")
    nf.ask(ALICE, fid, 5_000)
    assert code(nf, nf.transfer(ALICE, fid, BOB)) == "RESERVED"     # an open ask reserves the share (as QX)
    nf.cancel_ask(ALICE, fid)
    h = w.balances.get(HOUSE, 0)
    assert code(nf, nf.transfer(ALICE, fid, BOB)) == "OK" and w.balances[HOUSE] == h + 100
    # Possession without ownership: Bob hands the share to a custodian; he still
    # owns it (the contract's owner), but cannot list or move it until it returns.
    assert code(nf, nf.custody(BOB, fid, CAROL)) == "OK"
    assert (nf.owner(fid), nf.possessor(fid), w.owners[fid]) == (BOB, CAROL, BOB)
    assert code(nf, nf.ask(BOB, fid, 5_000)) == "NOT_POSSESSOR"
    assert code(nf, nf.release(BOB, fid)) == "NOT_POSSESSOR"        # only the custodian returns it
    assert code(nf, nf.release(CAROL, fid)) == "OK" and nf.possessor(fid) == BOB
    # Management to QX: QDOJO's book is closed to it, open bids are refunded.
    nf.bid(CAROL, fid, 700)
    c0 = w.balances[CAROL]
    assert code(nf, nf.manage(BOB, fid, "QX")) == "OK" and w.balances[CAROL] == c0 + 700
    assert code(nf, nf.ask(BOB, fid, 1)) == "NOT_MANAGED" and code(nf, nf.bid(CAROL, fid, 1)) == "NOT_MANAGED"
    assert code(nf, nf.qx_transfer(BOB, fid, ALICE)) == "OK" and nf.owner(fid) == ALICE
    assert code(nf, nf.manage(ALICE, fid, "QDOJO")) == "OK"
    assert invariants.check(w) == [] and w.total() == w.minted


def test_nft_operations_as_chain_transactions_are_delayed_and_can_drop():
    from qdojo.combat.chainsim import SimChain
    w, _ = _world()
    chain = SimChain(w, seed=3, latency=(2, 2))
    nf = nft.SimFighterNFTs(w, chain)
    fid = _mint(w, nft.SimFighterNFTs(w), "a")
    r = nf.ask(ALICE, fid, 900)
    assert nf.poll(r) is None and r.target_tick == w.tick + 2
    chain.advance()
    chain.advance()
    assert nf.poll(r) is None                                        # still pending at t+1
    chain.advance()
    assert nf.poll(r)["code"] == "OK"
    chain.drop_rate = 1.0
    r = nf.bid(BOB, fid, 900)
    for _ in range(3):
        chain.advance()
    assert nf.poll(r) == "dropped" and nf.owner(fid) == ALICE
    chain.drop_rate = 0.0
    r = nf.bid(BOB, fid, 10**9)                                     # more than Bob holds: the node drops it
    for _ in range(3):
        chain.advance()
    assert nf.poll(r) == "dropped"


# ---- determinism ------------------------------------------------------------------

def _busy_world():
    w, nf = _world()
    ids = [_mint(w, nf, lbl, register=True) for lbl in "abc"]
    nf.ask(ALICE, ids[0], 4_000)
    nf.bid(BOB, ids[0], 4_500)
    nf.bid(CAROL, ids[1], 100)
    nf.transfer(ALICE, ids[2], CAROL)
    w.send(ALICE, Op.QUEUE_ENTER, 1000, fighter_id=ids[1], auth_version=1, ruleset_digest=RULES.digest,
           timing_profile_id=1, fee_profile_id=1, tier_id=1, max_gap=200, expires_tick=w.tick + 41)
    nf.ask(ALICE, ids[1], 90)                                        # crosses while queued: settles later
    for _ in range(60):
        w.end()
    return w, ids


def _state(led):
    return (led.events, led.sales, {f: vars(t) for f, t in led.tokens.items()}, led.totals,
            {f: [vars(o) for o in v] for f, v in led.bids.items()}, {f: vars(o) for f, o in led.asks.items()})


def test_replaying_the_journal_rebuilds_the_identical_ledger_and_owners():
    w, ids = _busy_world()
    assert w.nft.sales and len(w.nft.sales) == 2                     # one at once, one deferred
    again = World.replay(w.manifest, w.journal)
    assert _state(again.nft) == _state(w.nft) and dict(again.owners) == dict(w.owners)
    assert again.balances == w.balances
    rep = rm.Replica(w.manifest)
    for rec in json.loads(json.dumps(w.journal)):                    # through JSON, as on disk
        rep.apply(rec)
    assert _state(rep.nft) == _state(w.nft) and rep.owners == dict(w.owners)
    # A journal whose result disagrees is caught.
    bad = json.loads(json.dumps(w.journal))
    next(r for r in bad if r["k"] == "nft" and r["op"] == "transfer")["code"] = "LOCKED"
    with pytest.raises(ValueError, match="diverged"):
        World.replay(w.manifest, bad)


def test_arena_nfts_survive_snapshot_and_full_replay_restarts(tmp_path):
    lineup = [{"label": "a", "policy": "scout-v1", "founding": True}, {"label": "b", "policy": "kicker-v1"},
              {"label": "c", "policy": "mixed-v1", "duels": True, "ranked": False},
              {"label": "d", "policy": "jabber-v1", "duels": True, "ranked": False}]
    kw = dict(seed=5, deterministic=True, cup_every=10**9, duel_every=150, market_every=100, log=lambda m: None,
              snapshot_every=250)
    arena = live.Arena(tmp_path / "arena", lineup, **kw)
    for _ in range(900):
        arena.step()
    arena.save()
    led = arena.w.nft
    assert led.sales, "the simulated market sold something"
    assert invariants.check(arena.w) == []
    want = _state(led)
    snap = live.Arena(tmp_path / "arena", lineup, **kw)              # from the snapshot
    assert snap.net.restart["mode"].startswith("snapshot") and _state(snap.w.nft) == want
    for name in (devnet.SNAPSHOT, devnet.SNAPSHOT_PREV):
        (tmp_path / "arena" / name).unlink(missing_ok=True)
    full = live.Arena(tmp_path / "arena", lineup, **kw)              # from the journal alone
    assert full.net.restart["mode"] == "full replay" and _state(full.w.nft) == want
    # Every sold house fighter runs for its new owner, who registered it.
    for fid, bot in full.bots.items():
        assert bot.wallet == full.nfts.owner(fid) == full.w.contract.fighters[fid].owner
    # The founding fighter is never listed by the demo market.
    founding = [f for f, t in led.tokens.items() if t.founding]
    assert founding and not any(s["fighter_id"] == founding[0].hex() for s in led.sales)
    # The read-only CLI replay agrees.
    assert _state(nft_freeze.replay_ledger(tmp_path / "arena")) == want


def test_legacy_assets_json_is_imported_once(tmp_path):
    arena = live.Arena(tmp_path / "arena", [{"label": "a", "policy": "scout-v1"}], seed=1, deterministic=True,
                       market_every=0, log=lambda m: None)
    arena.save()
    fid = next(iter(arena.w.nft.tokens))
    # Pretend an older arena: a second, legacy-only asset in assets.json.
    old = live.identity("someone")
    legacy_id = arena.nfts.id_for("legacy")
    (tmp_path / "arena" / "assets.json").write_text(json.dumps({legacy_id.hex(): {
        "issuer": arena.nfts.issuer.hex(), "name": "QDOJOF", "founding": False,
        "history": [[1, None, identity("x").hex()], [7, identity("x").hex(), old.hex()]]}}))
    again = live.Arena(tmp_path / "arena", [{"label": "a", "policy": "scout-v1"}], seed=1, deterministic=True,
                       market_every=0, log=lambda m: None)
    assert again.nfts.owner(legacy_id) == old and again.nfts.owner(fid) is not None
    assert again.nfts.history(legacy_id)[0]["legacy_history"]
    n = len(again.w.nft.events)
    again.save()
    third = live.Arena(tmp_path / "arena", [{"label": "a", "policy": "scout-v1"}], seed=1, deterministic=True,
                       market_every=0, log=lambda m: None)
    assert len(third.w.nft.events) == n                               # not imported twice


# ---- the port: both backends ---------------------------------------------------------

BACKENDS = ["sim", "qubic"]


@pytest.mark.parametrize("backend", BACKENDS)
def test_both_backends_implement_the_whole_port(backend):
    cls = nft.SimFighterNFTs if backend == "sim" else nft_qubic.QubicFighterNFTs
    assert not inspect.isabstract(cls) and issubclass(cls, nft.FighterNFTs) and cls.backend == backend
    for name in ("issue", "transfer", "ask", "cancel_ask", "bid", "cancel_bid", "settle", "poll", "token",
                 "collection", "book", "history", "sales", "owner", "possessor", "tokens_of"):
        assert callable(getattr(cls, name))


@pytest.mark.parametrize("backend", BACKENDS)
def test_adapter_contract_list_bid_sell(backend):
    """The same scenario against each backend. The qubic stub runs dry: each
    write must plan the exact QX call and refuse to send it."""
    if backend == "sim":
        w, nf = _world()
        fid = _mint(w, nf, "a")
        assert code(nf, nf.ask(ALICE, fid, 5_000)) == "OK"
        assert nf.book(fid)["asks"][0]["price"] == "5000"
        assert code(nf, nf.bid(BOB, fid, 5_000)) == "OK"
        assert nf.owner(fid) == BOB and nf.sales(fid)[0]["price"] == 5_000
        assert [t["fighter_id"] for t in nf.tokens_of(BOB)] == [fid.hex()]
        return
    fid = identity("q-fighter")
    nf = nft.make_backend("qubic", issuer=ISSUER, token_names={fid: "QF00001"})
    plans = {}
    for op, call in (("ask", lambda: nf.ask(ALICE, fid, 5_000)), ("bid", lambda: nf.bid(BOB, fid, 5_000)),
                     ("transfer", lambda: nf.transfer(ALICE, fid, BOB)),
                     ("issue", lambda: nf.issue(ISSUER, fid, ALICE, name="QF00001")),
                     ("manage", lambda: nf.manage(ALICE, fid, 1))):
        with pytest.raises(nft_qubic.NetworkDisabled) as e:
            call()
        plans[op] = e.value.plan
    assert (plans["ask"].contract_index, plans["ask"].input_type, plans["ask"].amount, len(plans["ask"].payload)) == (1, 5, 0, 56)
    assert (plans["bid"].input_type, plans["bid"].amount) == (6, 5_000)            # the bid attaches its escrow
    assert (plans["transfer"].input_type, plans["transfer"].amount, len(plans["transfer"].payload)) == (2, 100, 80)
    assert (plans["issue"].input_type, plans["issue"].amount, len(plans["issue"].payload)) == (1, 10**9, 32)
    assert (plans["manage"].input_type, len(plans["manage"].payload)) == (9, 56)
    assert plans["ask"].payload[:32] == ISSUER and plans["ask"].payload[32:40] == b"QF00001\0"
    assert plans["ask"].destination_public_key() == (1).to_bytes(8, "little") + bytes(24)
    for read in (lambda: nf.token(fid), nf.collection, lambda: nf.book(fid), lambda: nf.poll(None)):
        with pytest.raises(nft_qubic.NotConnected):
            read()


def test_qubic_payloads_match_the_existing_qubic_tooling():
    from qdojo.qubic import contracts
    assert nft_qubic.qx_issue_input("QF00001") == contracts.issue_asset_input("QF00001", 1)
    assert nft_qubic.QX_INDEX == contracts.QX_CONTRACT_INDEX
    assert contracts.contract_public_key(1) == nft_qubic.TxPlan(1, 0, 0, b"", "").destination_public_key()


def test_the_arena_refuses_to_run_on_the_qubic_stub(tmp_path):
    with pytest.raises(SystemExit, match="stub"):
        live.Arena(tmp_path / "a", [{"label": "a", "policy": "scout-v1"}], seed=1, deterministic=True,
                   market_every=0, log=lambda m: None, nft_backend="qubic")
    with pytest.raises(ValueError):
        nft.make_backend("mainnet")


# ---- export, read model and API --------------------------------------------------------

def test_export_and_read_model_and_api_serve_the_collection(tmp_path):
    from qdojo.combat import api, export
    lineup = [{"label": "a", "policy": "scout-v1"}, {"label": "b", "policy": "kicker-v1"},
              {"label": "c", "policy": "mixed-v1"}]
    out = tmp_path / "web" / "combat" / "v1"
    arena = live.run(tmp_path / "net", lineup, out, tick_seconds=0, export_every=50, ticks=700, log=lambda m: None,
                     seed=9, deterministic=True, market_every=60)
    coll = json.loads((out / "nfts.json").read_text())
    assert coll["schema"] == "qdojo.combat.nfts.v1" and len(coll["tokens"]) == 3
    one = coll["tokens"][0]["fighter_id"]
    tokdoc = json.loads((out / "nfts" / f"{one}.json").read_text())
    assert tokdoc["history"][0]["kind"] == "MINT" and "book" in tokdoc
    db = tmp_path / "rm.sqlite"
    rm.rebuild(tmp_path / "net", db, out, log=lambda m: None)
    reader = api.Reader(rm.connect(db, readonly=True))
    doc = reader.nfts({})
    assert doc["total"] == 3 and [x["serial"] for x in doc["items"]] == [1, 2, 3]
    assert reader.nft(one)["history"][0]["kind"] == "MINT"
    assert int(reader.nfts({})["stats"]["sales"]) == len(arena.w.nft.sales)
    sold = [s for s in arena.w.nft.sales]
    if sold:
        buyer = sold[-1]["buyer"]
        assert any(x["owner"] == buyer for x in reader.nfts({"owner": [buyer]})["items"])
    with pytest.raises(api.ApiError):
        reader.nft("00" * 32)
    del export


# ---- frozen art ----------------------------------------------------------------------

@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_freeze_is_deterministic_and_verify_catches_tampering(tmp_path):
    ids = [identity(f"freeze-{i}").hex() for i in range(3)]
    tokens = {"collection": {"name": "t"}, "site": "https://example.invalid/combat.html",
              "tokens": [{"fighter_id": f, "serial": i, "name": nft.asset_name(i)} for i, f in enumerate(ids, 1)]}
    a, b = tmp_path / "a", tmp_path / "b"
    assert nft_freeze.freeze(tokens, a) == 0 and nft_freeze.freeze(tokens, b) == 0
    ma, mb = (json.loads((d / "manifest.json").read_text()) for d in (a, b))
    assert ma == mb and ma["count"] == 3 and len(ma["root"]) == 64
    t0 = ma["tokens"][0]
    assert t0["card_png"]["width"] == 1024 and t0["sprite_png"]["width"] == 768
    assert (a / t0["card_png"]["path"]).read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    meta = json.loads((a / t0["metadata"]["path"]).read_text())
    assert {"name", "description", "image", "attributes", "external_url"} <= set(meta)
    assert meta["image_sha256"] == t0["card_png"]["sha256"] and meta["attributes"][0]["trait_type"] == "Kit"
    assert nft_freeze.verify(a) == 0
    p = a / t0["sprite_svg"]["path"]
    p.write_text(p.read_text().replace("#", "#0", 1)[:-1])            # tamper with one stored object
    assert nft_freeze.verify(a) == 1
    r = subprocess.run(["node", str(nft_freeze.SCRIPT), "verify", "--out", str(b), "--avatars",
                        str(tmp_path / "missing.js")], capture_output=True)
    assert r.returncode != 0


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_the_committed_sample_freeze_verifies():
    assert nft_freeze.verify(nft_freeze.ROOT / "apps/web/data/nft/v1/sample") == 0
