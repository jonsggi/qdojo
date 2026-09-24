"""Stories on the simulated chain, with every invariant checked on every tick."""
from qdojo.combat import invariants
from qdojo.combat.bot import Bot
from qdojo.combat.chainsim import SimQubicClient
from qdojo.combat.devnet import DevnetClient
from qdojo.combat.codec import Op
from qdojo.combat.sim import identity

from .test_chainsim import ADMIN, RULES, _setup


def _run(w, chain, bots, ticks, until=None):
    for _ in range(ticks):
        for b in bots:
            b.step()
        chain.advance()
        invariants.assert_ok(w)
        if until and until():
            return True
    return False


def test_nft_sold_mid_contest_pays_the_snapshotted_owner(tmp_path):
    w, chain, registry, bots, owners = _setup(tmp_path, n=2, latency=(1, 2), seed=21)
    a, b = bots
    c = w.contract
    assert _run(w, chain, bots, 200, until=lambda: c.fighters[a.fighter_id].lock == "CONTEST")
    contest = c.contests[c.fighters[a.fighter_id].lock_ref]
    buyer = identity("sc-buyer")
    w.mint(buyer, 10**6)
    registry.transfer(a.fighter_id, owners[0], buyer)        # sold while fighting
    before = dict(c.ledger.credits)
    assert _run(w, chain, bots, 800, until=lambda: contest.status == "DONE")
    side = "A" if contest.a.fighter_id == a.fighter_id else "B"
    if contest.result.get("winner") == side:
        # The purse goes to the owner snapshotted at acceptance, never the buyer.
        assert c.ledger.credits.get(owners[0], 0) > before.get(owners[0], 0)
        assert c.ledger.credits.get(buyer, 0) == 0
    # The buyer gains control at the boundary: register, then it can enter again.
    r = chain.send(buyer, Op.REGISTER_FIGHTER, fighter_id=a.fighter_id, registry_version=1)
    _run(w, chain, [b], 5)
    assert chain.poll(r).ok and c.fighters[a.fighter_id].owner == buyer


def test_cup_finalist_sold_between_pairings_is_played_by_the_new_owner(tmp_path):
    w, chain, registry, bots, owners = _setup(tmp_path, n=4, latency=(1, 2), seed=22)
    for b in bots:
        b.play_cups, b.ranked = True, False
        b.budget.max_stake = b.budget.max_total_escrow = 5000
    c = w.contract
    r = w.send(ADMIN, Op.ADMIN_CREATE_CUP, 0, ruleset_digest=RULES.digest, timing_profile_id=1, fee_profile_id=1,
               entry_fee=2000, registration_close=w.tick + 15, min_entrants=4, max_entrants=4, level_ticks=1300,
               first_level_delay=30, checkin_ticks=60, replay_delay=40)
    cup = c.cups[r.data["cup_id"]]
    assert _run(w, chain, bots, 4000, until=lambda: cup.status == "RUNNING" and cup.level == 1)
    finalist = next(p.winner for p in cup.pairings.values() if p.level == 0 and p.winner)
    i = next(k for k, b in enumerate(bots) if b.fighter_id == finalist)
    buyer = identity("sc-finalist-buyer")
    w.mint(buyer, 10**9)
    registry.transfer(finalist, owners[i], buyer)
    receipt = chain.send(buyer, Op.REGISTER_FIGHTER, fighter_id=finalist, registry_version=1)
    _run(w, chain, bots, 3, until=lambda: chain.poll(receipt) is not None)
    assert chain.poll(receipt).ok, "the TOURNAMENT lock allows the buyer to bind at a pairing boundary"
    # The new owner's bot takes over the fighter for the final.
    client = SimQubicClient(chain, buyer, DevnetClient(bots[i].client.view.net, buyer))
    new_bot = Bot(client, RULES, finalist, buyer, buyer, bots[i].choose, bots[i].budget, tmp_path / "buyer-bot",
                  clock=bots[i].clock)
    new_bot.play_cups = True
    bots[i] = new_bot
    assert _run(w, chain, bots, 6000, until=lambda: cup.status in ("COMPLETE", "ABORTED"))
    assert cup.status == "COMPLETE"
    if cup.champion == finalist:
        # Prize to the owner snapshotted at the final's check-in: the buyer.
        assert c.ledger.credits.get(buyer, 0) > 0


def test_bot_restart_mid_round_with_transactions_in_flight(tmp_path):
    w, chain, _, bots, _ = _setup(tmp_path, n=2, latency=(3, 5), drop_rate=0.1, seed=23)
    a, b = bots
    c = w.contract
    assert _run(w, chain, bots, 400, until=lambda: bool(a.inflight) and c.fighters[a.fighter_id].lock == "CONTEST")
    # The process dies: in-flight receipts are lost, the plan journal survives.
    a2 = Bot(a.client, RULES, a.fighter_id, a.operator, a.wallet, a.choose, a.budget, a.state_dir, clock=a.clock)
    fight_id = c.fighters[a.fighter_id].lock_ref
    contest = c.contests[fight_id]
    assert _run(w, chain, [a2, b], 1500, until=lambda: contest.status == "DONE")
    assert contest.result["kind"] == "COMBAT", contest.result
