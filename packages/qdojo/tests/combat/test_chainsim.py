"""The bot, contract and assets on a realistic simulated chain: latency, drops,
reordering, fees and a reserve that can run dry."""
import datetime as dt
from types import SimpleNamespace

from qdojo.combat import npcs
from qdojo.combat.bot import Bot, Budget, policy_chooser
from qdojo.combat.chainsim import AssetRegistry, FeeModel, SimChain, SimQubicClient
from qdojo.combat.codec import Op
from qdojo.combat.contract import development_manifest
from qdojo.combat.devnet import DevnetClient
from qdojo.combat.rules import candidate_1
from qdojo.combat.sim import World, identity

RULES = candidate_1()
ADMIN, HOUSE, DEV, SHARE = (identity(x) for x in ("cs-admin", "cs-house", "cs-dev", "cs-share"))
NOON = dt.datetime(2026, 9, 24, 12, tzinfo=dt.timezone.utc)


def _setup(tmp_path, n=4, policy=npcs.mixed_v1, **chain_kw):
    w = World(development_manifest(RULES, ADMIN, HOUSE, DEV, SHARE))
    w.mint(ADMIN, 10**12)
    chain = SimChain(w, **chain_kw)
    registry = AssetRegistry(w, identity("cs-issuer"))
    net = SimpleNamespace(world=w, m=w.manifest)
    bots, owners = [], []
    for i in range(n):
        owner = identity(f"cs-owner-{i}")
        w.mint(owner, 10**9)
        fid = registry.issue(f"fighter-{i}", owner, founding=i < 2)
        # Registration happens directly (setup), everything after goes through the chain.
        w.send(ADMIN, Op.ADMIN_REGISTER_ASSET, fighter_id=fid, registry_version=1, house_npc=0)
        w.send(owner, Op.REGISTER_FIGHTER, fighter_id=fid, registry_version=1)
        client = SimQubicClient(chain, owner, DevnetClient(net, owner))
        bots.append(Bot(client, RULES, fid, owner, owner, policy_chooser(RULES, policy, bytes([i]) * 32),
                        Budget(ruleset_digest=RULES.digest.hex(), max_fights_per_day=10**6,
                               max_daily_committed=10**12, max_daily_net_loss=10**12, stop_after_faults=10**6),
                        tmp_path / f"bot{i}", clock=lambda: NOON))
        owners.append(owner)
    return w, chain, registry, bots, owners


def _run(w, chain, bots, ticks):
    for _ in range(ticks):
        for b in bots:
            b.step()
        chain.advance()
        w.check_conservation()


def test_bots_finish_fights_despite_latency_drops_and_reordering(tmp_path):
    w, chain, _, bots, _ = _setup(tmp_path, latency=(1, 4), drop_rate=0.15, seed=3)
    _run(w, chain, bots, 1500)
    c = w.contract
    done = [x for x in c.contests.values() if x.status == "DONE"]
    assert len(done) >= 10
    dropped = sum(1 for t in chain.txs.values() if t.status == "dropped")
    assert dropped > 0
    # Drops and latency must not turn into faults: the bots resend in time.
    kinds = [x.result["kind"] for x in done]
    assert kinds.count("COMBAT") >= 0.9 * len(kinds), kinds


def test_a_dry_reserve_halts_the_contract_and_voids_unfinished_fights(tmp_path):
    fees = FeeModel(per_call=5, per_tick=1, per_resolved_round=10)
    w, chain, _, bots, owners = _setup(tmp_path, fees=fees, reserve=1500, seed=5)
    _run(w, chain, bots, 1200)
    assert chain.halted_ticks > 0 and chain.burned > 0
    c = w.contract
    assert c.generation > 1                              # the heartbeat saw the missed END_TICKs
    # Voided contests refund; conservation is checked every tick in _run.
    chain.fund_reserve(10**6)
    before = len([x for x in c.contests.values() if x.status == "DONE"])
    _run(w, chain, bots, 600)
    assert len([x for x in c.contests.values() if x.status == "DONE"]) > before


def test_nft_transfer_mid_queue_refunds_and_new_owner_takes_over(tmp_path):
    w, chain, registry, bots, owners = _setup(tmp_path, n=3, latency=(1, 1), seed=7)
    a, b = bots[0], bots[1]
    for _ in range(3):
        a.step()
        chain.advance()
    f = w.contract.fighters[a.fighter_id]
    assert f.lock == "QUEUED"
    buyer = identity("cs-buyer")
    w.mint(buyer, 10**6)
    registry.transfer(a.fighter_id, owners[0], buyer)
    # A second offer makes the next matching pass run; it revalidates ownership
    # and invalidates the transferred fighter's offer (matchmaking.md §4).
    for _ in range(8):
        b.step()
        chain.advance()
    assert f.lock == "IDLE" and w.contract.ledger.credits.get(owners[0], 0) >= 1000
    receipt = chain.send(buyer, Op.REGISTER_FIGHTER, fighter_id=a.fighter_id, registry_version=1)
    for _ in range(3):
        chain.advance()
    assert chain.poll(receipt).ok and f.owner == buyer
    hist = registry.public(a.fighter_id)["history"]
    assert [h["to"] for h in hist] == [owners[0].hex(), buyer.hex()]
    assert registry.public(a.fighter_id)["founding"] is True
    w.check_conservation()


def test_poll_semantics(tmp_path):
    w, chain, _, _, owners = _setup(tmp_path, n=1, latency=(2, 2), seed=1)
    r = chain.send(owners[0], Op.WITHDRAW)
    assert r.target_tick == w.tick + 2
    chain.advance()                       # tick t
    chain.advance()                       # tick t+1
    assert chain.poll(r) is None
    chain.advance()                       # tick t+2: included
    assert chain.poll(r).ok
    chain.drop_rate = 1.0
    r2 = chain.send(owners[0], Op.WITHDRAW)
    for _ in range(3):
        chain.advance()
    assert chain.poll(r2) == "dropped"
