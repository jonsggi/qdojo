"""Protocol, matchmaking, money and competition scenarios on the fake chain.

Every test ends with World.check_conservation(): external balances plus the
contract balance equal what was minted, and the contract's balance equals
the sum of its liabilities.
"""
import pytest

from qdojo.combat import rating as rt
from qdojo.combat.codec import Code, Op, encode_frame
from qdojo.combat.contract import development_manifest
from qdojo.combat.rules import candidate_1
from qdojo.combat.series import Series, bracket, seed_positions
from qdojo.combat.sim import World, commit_fields, identity, reveal_fields
from qdojo.combat.types import Action, Plan

J, K, B, D, T, R = Action.JAB, Action.KICK, Action.BLOCK, Action.DUCK, Action.THROW, Action.RECOVER
ADMIN, HOUSE, DEV, SHARE = identity("admin"), identity("house"), identity("dev"), identity("share")
JABS = Plan.of([J] * 6)
RESTS = Plan.of([R] * 6)
KO_PLAN = Plan.of([K, R, K, R, K, R])


@pytest.fixture
def world():
    w = World(development_manifest(candidate_1(), ADMIN, HOUSE, DEV, SHARE))
    w.mint(ADMIN, 10**9)
    return w


class Player:
    def __init__(self, world, label, npc=False, owner=None, operator=None):
        self.w = world
        self.fid = identity("fighter:" + label)
        self.owner = owner or identity("owner:" + label)
        self.operator = operator or self.owner
        world.owners[self.fid] = self.owner
        world.mint(self.owner, 1_000_000)
        if self.operator != self.owner:
            world.mint(self.operator, 1_000_000)
        assert world.send(ADMIN, Op.ADMIN_REGISTER_ASSET, fighter_id=self.fid, registry_version=1,
                          house_npc=int(npc)).ok
        assert world.send(self.owner, Op.REGISTER_FIGHTER, fighter_id=self.fid, registry_version=1).ok
        if self.operator != self.owner:
            assert world.send(self.owner, Op.SET_OPERATOR, fighter_id=self.fid, new_operator=self.operator,
                              expected_auth_version=1).ok

    @property
    def f(self):
        return self.w.contract.fighters[self.fid]

    def enter(self, amount=1000, expires_in=240, max_gap=200, tier=1, who=None):
        c = self.w.contract
        return self.w.send(who or self.operator, Op.QUEUE_ENTER, amount, fighter_id=self.fid,
                           auth_version=self.f.auth_version, ruleset_digest=c.m.ruleset.digest,
                           timing_profile_id=1, fee_profile_id=1, tier_id=tier, max_gap=max_gap,
                           expires_tick=self.w.tick + expires_in)

    def commit(self, fight_id, plan, salt=None):
        fields, salt = commit_fields(self.w, fight_id, self.fid, self.operator, plan, salt)
        return self.w.send(self.operator, Op.COMMIT, **fields), salt

    def reveal(self, fight_id, plan, salt):
        return self.w.send(self.operator, Op.REVEAL, **reveal_fields(self.w, fight_id, self.fid, plan, salt))


def until_match(w, *players):
    for _ in range(8):
        w.end()
        c = w.contract
        live = [x for x in c.fights.values() if x.phase != "DONE"
                and all(x.slot_of(p.fid) for p in players)]
        if live:
            return live[-1].fight_id
    raise AssertionError("no match")


def play_round(w, fight_id, moves):
    """moves: {player: plan or None (no commit) or 'commit-only'}"""
    fight = w.contract.fights[fight_id]
    w.run_until(fight.start_tick + 1)
    salts = {}
    for p, plan in moves.items():
        if plan is not None:
            plan_ = plan if isinstance(plan, Plan) else plan[0]
            r, salts[p] = p.commit(fight_id, plan_)
            assert r.code == Code.OK, r
    w.run_until(fight.commit_last + 1)
    if fight.phase != "REVEAL":
        return
    for p, plan in moves.items():
        if isinstance(plan, Plan):
            assert p.reveal(fight_id, plan, salts[p]).code == Code.OK
    w.end()


def play_fight(w, fight_id, a, pa, b, pb):
    while w.contract.fights[fight_id].phase != "DONE":
        play_round(w, fight_id, {a: pa, b: pb})
        if w.contract.fights[fight_id].phase != "DONE" and w.tick > 10**6:
            raise AssertionError("runaway")
    return w.contract.fights[fight_id].result


# ---- ranked lifecycle ------------------------------------------------------

def test_ranked_fight_pays_winner_less_rake_and_rates(world):
    a, b = Player(world, "a"), Player(world, "b")
    assert a.enter().ok and b.enter().ok
    fid = until_match(world, a, b)
    fight = world.contract.fights[fid]
    kicker = a if fight.slot_of(a.fid) else b
    result = play_fight(world, fid, a, KO_PLAN, b, JABS)
    assert result["kind"] == "COMBAT"
    winner_slot = result["winner"]
    winner = a if fight.slot_of(a.fid) == winner_slot else b
    loser = b if winner is a else a
    credits = world.contract.ledger.credits
    assert credits[winner.owner] == 1900
    assert (credits[HOUSE], credits[DEV], credits[SHARE]) == (60, 10, 30)
    assert winner.f.lifetime == 1016 and loser.f.lifetime == 984
    assert winner.f.lock == loser.f.lock == "IDLE" and winner.f.placement == 1
    before = world.balances[winner.owner]
    assert world.send(winner.owner, Op.WITHDRAW).data["amount"] == 1900
    assert world.balances[winner.owner] == before + 1900
    assert world.send(winner.owner, Op.WITHDRAW).data["amount"] == 0
    del kicker
    world.check_conservation()


def test_combat_draw_refunds_without_rake(world):
    a, b = Player(world, "a"), Player(world, "b")
    a.enter(), b.enter()
    fid = until_match(world, a, b)
    result = play_fight(world, fid, a, RESTS, b, RESTS)
    assert result == {**result, "kind": "COMBAT", "winner": None}
    assert world.contract.ledger.credits[a.owner] == 1000 == world.contract.ledger.credits[b.owner]
    assert HOUSE not in world.contract.ledger.credits
    assert a.f.lifetime == 1000 and a.f.placement == 1 and a.f.record["D"] == 1
    world.check_conservation()


def test_single_commit_wins_by_forfeit_and_faults_the_other(world):
    a, b = Player(world, "a"), Player(world, "b")
    a.enter(), b.enter()
    fid = until_match(world, a, b)
    play_round(world, fid, {a: JABS, b: None})
    fight = world.contract.fights[fid]
    assert fight.result["kind"] == "FORFEIT"
    assert world.contract.ledger.credits[a.owner] == 1900
    assert b.f.faults and b.f.cooldown_until == fight.result["tick"] + 240
    assert a.f.placement == 0 and a.f.record["FW"] == 1 and a.f.lifetime > 1000
    assert b.enter().code == Code.COOLDOWN
    world.check_conservation()


def test_withheld_reveal_loses_to_the_revealer(world):
    a, b = Player(world, "a"), Player(world, "b")
    a.enter(), b.enter()
    fid = until_match(world, a, b)
    play_round(world, fid, {a: JABS, b: (RESTS, "commit-only")})
    fight = world.contract.fights[fid]
    world.run_until(fight.reveal_last + 1)
    assert fight.result["kind"] == "FORFEIT" and fight.result["stage"] == "REVEAL"
    assert world.contract.ledger.credits[a.owner] == 1900
    world.check_conservation()


def test_double_fault_refunds_and_faults_both(world):
    a, b = Player(world, "a"), Player(world, "b")
    a.enter(), b.enter()
    fid = until_match(world, a, b)
    play_round(world, fid, {a: None, b: None})
    assert world.contract.fights[fid].result["kind"] == "DOUBLE_FAULT"
    assert world.contract.ledger.credits[a.owner] == 1000 == world.contract.ledger.credits[b.owner]
    assert a.f.lifetime == b.f.lifetime == 1000 and a.f.faults and b.f.faults
    world.check_conservation()


def test_three_faults_suspend_ranked_for_the_epoch(world):
    a = Player(world, "a")
    others = [Player(world, f"o{i}") for i in range(3)]
    for o in others:
        world.run_until(a.f.cooldown_until)
        assert a.enter().ok and o.enter().ok
        fid = until_match(world, a, o)
        play_round(world, fid, {a: None, o: JABS})
    world.run_until(a.f.cooldown_until + 1)
    assert a.enter().code == Code.COOLDOWN and a.f.suspended_epoch == world.contract.m.epoch(world.tick)
    world.check_conservation()


def test_windows_and_duplicate_commitments(world):
    a, b = Player(world, "a"), Player(world, "b")
    a.enter(), b.enter()
    fid = until_match(world, a, b)
    fight = world.contract.fights[fid]
    # Fights are created at END_TICK, so the first tick a commit can land on is start+1.
    assert world.tick == fight.start_tick + 1
    r, salt = a.commit(fid, JABS, salt=b"\1" * 32)
    assert r.code == Code.OK
    r, _ = a.commit(fid, JABS, salt=b"\1" * 32)
    assert r.code == Code.DUPLICATE
    r, _ = a.commit(fid, RESTS)
    assert r.code == Code.ALREADY_COMMITTED
    assert a.reveal(fid, JABS, salt).code == Code.WRONG_PHASE
    r, sb = b.commit(fid, RESTS)
    world.run_until(fight.commit_last + 1)
    r, _ = a.commit(fid, JABS)
    assert r.code in (Code.WRONG_PHASE, Code.LATE)
    # An invalid reveal is rejected without replacing the commitment, then corrected.
    assert a.reveal(fid, JABS, b"\2" * 32).code == Code.BAD_COMMITMENT
    assert a.reveal(fid, RESTS, salt).code == Code.BAD_COMMITMENT
    assert a.reveal(fid, JABS, salt).code == Code.OK
    assert a.reveal(fid, JABS, salt).code == Code.DUPLICATE
    assert b.reveal(fid, RESTS, sb).code == Code.OK
    world.end()
    assert fight.state.round_index == 1 and fight.phase == "COMMIT"
    world.check_conservation()


def test_commitment_bound_to_network_contract_and_state(world):
    a, b = Player(world, "a"), Player(world, "b")
    a.enter(), b.enter()
    fid = until_match(world, a, b)
    world.end()
    fight = world.contract.fights[fid]
    fields, salt = commit_fields(world, fid, a.fid, a.operator, JABS)
    other = World(development_manifest(candidate_1(), ADMIN, HOUSE, DEV, SHARE, network_id=b"\x01" * 32))
    del other
    from qdojo.combat import codec
    wrong_net = codec.commitment(
        network_id=b"\x01" * 32, contract_id=world.manifest.contract_id, fight_id=fid, round_index=0,
        context_digest=fight.context_digest, round_state_digest=fight.round_state_digest(), fighter_id=a.fid,
        operator=a.operator, auth_version=1, salt=salt, plan=JABS)
    assert world.send(a.operator, Op.COMMIT, **{**fields, "commitment": wrong_net}).ok
    b.commit(fid, RESTS)
    world.run_until(fight.commit_last + 1)
    assert a.reveal(fid, JABS, salt).code == Code.BAD_COMMITMENT
    bad_state = dict(reveal_fields(world, fid, a.fid, JABS, salt), round_state_digest=b"\0" * 32)
    assert world.send(a.operator, Op.REVEAL, **bad_state).code == Code.BAD_STATE
    world.check_conservation()


def test_only_the_snapshotted_operator_acts(world):
    op = identity("bot-signer")
    a, b = Player(world, "a", operator=op), Player(world, "b")
    assert a.f.operator == op and a.f.auth_version == 2
    a.enter(), b.enter()
    fid = until_match(world, a, b)
    world.end()
    fields, _ = commit_fields(world, fid, a.fid, a.operator, JABS)
    assert world.send(a.owner, Op.COMMIT, **fields).code == Code.NOT_OPERATOR
    assert world.send(op, Op.COMMIT, **{**fields, "auth_version": 1}).code == Code.STALE_AUTH
    assert world.send(a.owner, Op.SET_OPERATOR, fighter_id=a.fid, new_operator=a.owner,
                      expected_auth_version=2).code == Code.FIGHTER_BUSY
    world.check_conservation()


# ---- nonces and framing ----------------------------------------------------

def test_identical_retry_and_nonce_conflicts(world):
    a = Player(world, "a")
    c = world.contract
    fields = dict(fighter_id=a.fid, auth_version=1, ruleset_digest=c.m.ruleset.digest, timing_profile_id=1,
                  fee_profile_id=1, tier_id=1, max_gap=200, expires_tick=world.tick + 240)
    frame = encode_frame(Op.QUEUE_ENTER, 50, fields)
    first = world.raw(a.owner, frame, 1000)
    again = world.raw(a.owner, frame, 1000)
    assert first.code == Code.OK and again.code == Code.DUPLICATE and again.refunded == 1000
    assert again.data == first.data
    assert sum(1 for o in c.offers.values() if o.fighter_id == a.fid) == 1
    changed = encode_frame(Op.QUEUE_CANCEL, 50, {"offer_id": first.data["offer_id"]})
    assert world.raw(a.owner, changed).code == Code.NONCE_CONFLICT
    older = encode_frame(Op.QUEUE_CANCEL, 49, {"offer_id": first.data["offer_id"]})
    assert world.raw(a.owner, older).code == Code.STALE
    assert c.ledger.credits[a.owner] == 1000        # the duplicate's attachment only
    world.check_conservation()


def test_malformed_frame_and_wrong_amount_refund(world):
    a = Player(world, "a")
    r = world.raw(a.owner, b"\0" * 512, 77)
    assert r.code == Code.BAD_FRAME and r.refunded == 77
    assert a.enter(amount=999).code == Code.BAD_AMOUNT
    assert a.enter(amount=1001).code == Code.BAD_AMOUNT
    assert world.send(a.owner, Op.WITHDRAW, 5).code == Code.BAD_AMOUNT
    assert world.contract.ledger.credits[a.owner] == 77 + 999 + 1001 + 5
    assert a.f.lock == "IDLE"
    world.check_conservation()


def test_unknown_invocator_is_paid_back_not_given_a_slot(world):
    stranger = identity("stranger")
    world.mint(stranger, 500)
    world.contract.m.__class__  # manifest is frozen; capacity is the default
    r = world.raw(stranger, b"\0" * 512, 500)
    assert r.refunded == 500
    world.check_conservation()


# ---- matchmaking.md §7 ----------------------------------------------------

def test_rating_window_widens_symmetrically(world):
    a, b = Player(world, "a"), Player(world, "b")
    a.f.lifetime, b.f.lifetime = 1000, 1180
    assert a.enter(max_gap=200, expires_in=1200).ok
    world.run_until(world.tick + 200)
    assert b.enter(max_gap=200, expires_in=1200).ok
    entered = world.tick
    while not world.contract.fights:
        world.end()
    matched_at = next(iter(world.contract.fights.values())).start_tick
    # A has waited long, but B's own window must also cover 180:
    # 100 + 50*floor(dt/40) >= 180 needs dt >= 80; the next matching tick after that.
    assert matched_at == next(t for t in range(entered + 80, entered + 90) if t % 4 == 0)
    world.check_conservation()


def test_order_capacity_and_exclusions(world):
    a, b, c, d = (Player(world, x) for x in "abcd")
    shared_owner = identity("owner:shared")
    e = Player(world, "e", owner=shared_owner)
    f = Player(world, "f", owner=shared_owner)
    npc = Player(world, "npc", npc=True)
    assert npc.enter().code == Code.INCOMPATIBLE
    assert e.enter().ok and f.enter().ok         # same owner: never paired together
    assert a.enter().ok and b.enter().ok and c.enter().ok
    world.run_until(world.tick + 5)
    fights = [x for x in world.contract.fights.values()]
    pairs = [{x.context.participant_a.fighter_id, x.context.participant_b.fighter_id} for x in fights]
    assert {e.fid, f.fid} not in pairs
    # Earliest compatible: e takes a (lowest later offer), f takes b; c waits.
    assert {e.fid, a.fid} in pairs and {f.fid, b.fid} in pairs
    assert world.contract.offers[c.f.lock_ref].status == "OPEN"
    del d
    world.check_conservation()


def test_four_matches_per_pass(world):
    players = [Player(world, f"p{i}") for i in range(10)]
    for p in players:
        assert p.enter().ok
    while world.tick % 4:
        world.end()
    world.end()
    assert len(world.contract.fights) == 4
    world.run_until(world.tick + 4)
    assert len(world.contract.fights) == 5
    world.check_conservation()


def test_cancel_before_match_refunds_after_match_does_not(world):
    a, b, c = Player(world, "a"), Player(world, "b"), Player(world, "c")
    r = a.enter()
    assert world.send(a.owner, Op.QUEUE_CANCEL, offer_id=r.data["offer_id"]).ok
    assert world.contract.ledger.credits[a.owner] == 1000 and a.f.lock == "IDLE"
    rb = b.enter()
    c.enter()
    until_match(world, b, c)
    assert world.send(b.owner, Op.QUEUE_CANCEL, offer_id=rb.data["offer_id"]).code == Code.ALREADY_MATCHED
    world.check_conservation()


def test_expiry_and_match_cannot_both_happen(world):
    a, b = Player(world, "a"), Player(world, "b")
    while (world.tick + 40) % 4:
        world.end()
    a.enter(expires_in=40)
    world.run_until(world.tick + 40)
    assert world.tick % 4 == 0
    b.enter()
    world.end()                                  # the matching tick == a's expiry tick
    assert not world.contract.fights
    assert world.contract.offers[1].status == "EXPIRED"
    world.check_conservation()


def test_transfer_before_pairing_refunds_original_payer(world):
    a, b = Player(world, "a"), Player(world, "b")
    a.enter(), b.enter()
    buyer = identity("buyer")
    world.owners[a.fid] = buyer
    world.run_until(world.tick + 5)
    assert not world.contract.fights
    assert world.contract.ledger.credits[a.owner] == 1000 and a.f.lock == "IDLE"
    assert world.send(buyer, Op.REGISTER_FIGHTER, fighter_id=a.fid, registry_version=1).ok
    assert a.f.owner == buyer and a.f.auth_version == 2 and a.f.lifetime == 1000
    world.check_conservation()


def test_pair_limits_block_farming(world):
    a, b = Player(world, "a"), Player(world, "b")
    for n in range(2):
        world.run_until(max(a.f.cooldown_until, world.tick) + 130)
        a.enter(expires_in=1200), b.enter(expires_in=1200)
        fid = until_match(world, a, b)
        play_fight(world, fid, a, RESTS, b, RESTS)
    world.run_until(world.tick + 200)
    a.enter(expires_in=1200), b.enter(expires_in=1200)
    world.run_until(world.tick + 40)
    assert sum(1 for f in world.contract.fights.values()) == 2       # third start this epoch refused
    world.check_conservation()


def test_full_queue_rejects_without_taking_funds(world):
    players = [Player(world, f"q{i}", owner=identity("owner:same")) if i == 0 else Player(world, f"q{i}")
               for i in range(66)]
    same = identity("owner:q-shared")
    del same
    accepted = 0
    for p in players:
        # Make every offer incompatible so nothing matches: distinct tiers are not
        # available, so park them with a disjoint rating gap instead.
        p.f.lifetime = 1000 + 300 * (players.index(p) % 2) + 5 * players.index(p)
        r = p.enter(max_gap=100)
        accepted += r.ok
        if not r.ok:
            assert r.code == Code.FULL and world.contract.ledger.credits[p.owner] == 1000
    assert accepted == 64
    world.check_conservation()


def test_service_gap_voids_active_fight_and_reverses_start(world):
    a, b = Player(world, "a"), Player(world, "b")
    a.enter(), b.enter()
    fid = until_match(world, a, b)
    epoch = world.contract.m.epoch(world.tick)
    key = (min(a.fid, b.fid), max(a.fid, b.fid), epoch)
    assert world.contract.pair_starts[key] == 1
    world.skip_ticks(3)                           # END_TICK never ran for those ticks
    world.end()
    fight = world.contract.fights[fid]
    assert fight.result["kind"] == "VOID"
    assert world.contract.ledger.credits[a.owner] == 1000 == world.contract.ledger.credits[b.owner]
    assert not a.f.faults and a.f.lifetime == 1000 and world.contract.pair_starts[key] == 0
    assert a.f.lock == "IDLE"
    world.check_conservation()


def test_failed_withdrawal_restores_credit(world):
    a, b = Player(world, "a"), Player(world, "b")
    r = a.enter()
    world.send(a.owner, Op.QUEUE_CANCEL, offer_id=r.data["offer_id"])
    world.transfer_fails.add(a.owner)
    assert world.send(a.owner, Op.WITHDRAW).code == Code.TRANSFER_FAILED
    assert world.contract.ledger.credits[a.owner] == 1000
    world.transfer_fails.clear()
    assert world.send(a.owner, Op.WITHDRAW).data["amount"] == 1000
    assert world.send(a.owner, Op.WITHDRAW).data["amount"] == 0
    del b
    world.check_conservation()


# ---- duels -----------------------------------------------------------------

def _duel(world, a, b, stake=5000, fmt=1):
    c = world.contract
    r = world.send(a.owner, Op.DUEL_OFFER, stake, fighter_id=a.fid, auth_version=a.f.auth_version,
                   opponent_id=b.fid, ruleset_digest=c.m.ruleset.digest, timing_profile_id=1,
                   fee_profile_id=1, stake=stake, format=fmt, expires_tick=world.tick + 240)
    assert r.ok, r
    acc = world.send(b.owner, Op.DUEL_ACCEPT, stake, offer_id=r.data["offer_id"], fighter_id=b.fid,
                     auth_version=b.f.auth_version)
    assert acc.ok, acc
    return c.contests[acc.data["contest_id"]]


def test_bo3_duel_one_rake_no_rating(world):
    a, b = Player(world, "a"), Player(world, "b")
    contest = _duel(world, a, b)
    while contest.status == "ACTIVE":
        fid = contest.fights[-1]
        play_fight(world, fid, a, KO_PLAN, b, JABS)
    assert contest.series.fights >= 2
    winner = contest.result["winner"]
    w_owner = (contest.a if winner == "A" else contest.b).payout_recipient
    assert world.contract.ledger.credits[w_owner] == 10_000 - 500
    assert world.contract.ledger.credits[HOUSE] == 300
    assert a.f.lifetime == b.f.lifetime == 1000 and a.f.lock == b.f.lock == "IDLE"
    world.check_conservation()


def test_duel_series_draw_at_cap_refunds(world):
    a, b = Player(world, "a"), Player(world, "b")
    contest = _duel(world, a, b, fmt=1)
    while contest.status == "ACTIVE":
        play_fight(world, contest.fights[-1], a, RESTS, b, RESTS)
    assert contest.series.fights == 5 and contest.result["winner"] is None
    assert world.contract.ledger.credits[a.owner] == 5000 == world.contract.ledger.credits[b.owner]
    world.check_conservation()


def test_duel_forfeit_ends_series(world):
    a, b = Player(world, "a"), Player(world, "b")
    contest = _duel(world, a, b, fmt=2)
    play_fight(world, contest.fights[-1], a, KO_PLAN, b, JABS)
    play_round(world, contest.fights[-1], {a: None, b: JABS})
    assert contest.status == "DONE" and contest.result["kind"] == "FORFEIT"
    w_owner = (contest.a if contest.result["winner"] == "A" else contest.b).payout_recipient
    assert w_owner == b.owner
    world.check_conservation()


def test_duel_offer_expires_and_refunds(world):
    a, b = Player(world, "a"), Player(world, "b")
    c = world.contract
    r = world.send(a.owner, Op.DUEL_OFFER, 3000, fighter_id=a.fid, auth_version=1, opponent_id=b.fid,
                   ruleset_digest=c.m.ruleset.digest, timing_profile_id=1, fee_profile_id=1, stake=3000,
                   format=0, expires_tick=world.tick + 40)
    world.run_until(world.tick + 41)
    assert c.offers[r.data["offer_id"]].status == "EXPIRED" and c.ledger.credits[a.owner] == 3000
    world.check_conservation()


# ---- cups ------------------------------------------------------------------

def _cup(world, sponsorship=1000, close_in=50, min_entrants=4):
    c = world.contract
    r = world.send(ADMIN, Op.ADMIN_CREATE_CUP, sponsorship, ruleset_digest=c.m.ruleset.digest,
                   timing_profile_id=1, fee_profile_id=1, entry_fee=2000,
                   registration_close=world.tick + close_in, min_entrants=min_entrants, max_entrants=16,
                   level_ticks=3000, first_level_delay=120, checkin_ticks=120, replay_delay=120)
    assert r.ok, r
    return c.cups[r.data["cup_id"]]


def _run_cup(world, cup, players, plan_for, no_show=()):
    by_fid = {p.fid: p for p in players}
    guard = 0
    while cup.status == "RUNNING" and guard < 200_000:
        guard += 1
        t = world.tick
        if cup.level_start <= t < cup.level_start + 120:
            for p in cup.pairings.values():
                if p.level == cup.level and p.status == "SCHEDULED":
                    for fid in (p.a, p.b):
                        if fid and fid not in p.checked and fid not in no_show:
                            pl = by_fid[fid]
                            world.send(pl.operator, Op.CUP_CHECK_IN, cup_id=cup.cup_id, pairing_id=p.pairing_id,
                                       fighter_id=fid, auth_version=pl.f.auth_version)
        active = [x for x in world.contract.fights.values() if x.phase == "COMMIT" and x.start_tick < t <= x.commit_last
                  and world.contract.contests[x.contest_id].cup_id == cup.cup_id]
        for fight in active:
            for fid in (fight.context.participant_a.fighter_id, fight.context.participant_b.fighter_id):
                slot = fight.slot_of(fid)
                if slot not in fight.commits:
                    pl = by_fid[fid]
                    plan = plan_for(pl)
                    r, salt = pl.commit(fight.fight_id, plan)
                    pl.pending = (fight.fight_id, fight.state.round_index, plan, salt)
        for fight in [x for x in world.contract.fights.values() if x.phase == "REVEAL"]:
            for pl in players:
                pend = getattr(pl, "pending", None)
                if pend and pend[0] == fight.fight_id and pend[1] == fight.state.round_index:
                    slot = fight.slot_of(pl.fid)
                    if slot not in fight.reveals:
                        pl.reveal(fight.fight_id, pend[2], pend[3])
        world.end()


def test_cup_bracket_with_byes_pays_champion(world):
    cup = _cup(world)
    players = [Player(world, f"c{i}") for i in range(5)]
    for i, p in enumerate(players):
        p.f.lifetime = 1000 + 10 * i
        assert world.send(p.owner, Op.CUP_REGISTER, 2000, cup_id=cup.cup_id, fighter_id=p.fid, auth_version=1).ok
    world.run_until(cup.descriptor["registration_close"] + 1)
    assert cup.status == "RUNNING" and len(cup.slots) == 8 and cup.slots.count(None) == 3
    strong = players[-1]
    _run_cup(world, cup, players, lambda p: KO_PLAN if p is strong else RESTS)
    assert cup.status == "COMPLETE", cup.status
    champ = world.contract.fighters[cup.champion]
    prize = 1000 + 5 * 2000 - 5 * 2000 * 500 // 10_000
    assert world.contract.ledger.credits.get(champ.owner, 0) == prize
    assert all(p.f.lock == "IDLE" for p in players)
    assert all(p.f.lifetime == 1000 + 10 * i for i, p in enumerate(players))    # cups never rate
    world.check_conservation()


def test_cup_below_minimum_refunds_everyone(world):
    cup = _cup(world, sponsorship=700)
    players = [Player(world, f"m{i}") for i in range(3)]
    for p in players:
        world.send(p.owner, Op.CUP_REGISTER, 2000, cup_id=cup.cup_id, fighter_id=p.fid, auth_version=1)
    world.run_until(cup.descriptor["registration_close"] + 1)
    assert cup.status == "CANCELLED"
    assert all(world.contract.ledger.credits[p.owner] == 2000 for p in players)
    assert world.contract.ledger.credits[ADMIN] == 700
    world.check_conservation()


def test_cup_with_no_combat_aborts_with_full_refunds(world):
    cup = _cup(world)
    players = [Player(world, f"n{i}") for i in range(4)]
    for p in players:
        world.send(p.owner, Op.CUP_REGISTER, 2000, cup_id=cup.cup_id, fighter_id=p.fid, auth_version=1)
    world.run_until(cup.descriptor["registration_close"] + 1)
    _run_cup(world, cup, players, lambda p: RESTS, no_show={p.fid for p in players})
    assert cup.status == "ABORTED"
    assert all(world.contract.ledger.credits[p.owner] == 2000 for p in players)
    assert HOUSE not in world.contract.ledger.credits
    world.check_conservation()


def test_cup_one_fighter_per_owner_and_withdraw_before_close(world):
    cup = _cup(world)
    shared = identity("owner:cupshared")
    a, b = Player(world, "x1", owner=shared), Player(world, "x2", owner=shared)
    assert world.send(shared, Op.CUP_REGISTER, 2000, cup_id=cup.cup_id, fighter_id=a.fid, auth_version=1).ok
    assert world.send(shared, Op.CUP_REGISTER, 2000, cup_id=cup.cup_id, fighter_id=b.fid,
                      auth_version=1).code == Code.INCOMPATIBLE
    assert world.send(shared, Op.CUP_WITHDRAW, cup_id=cup.cup_id, fighter_id=a.fid).ok
    assert world.contract.ledger.credits[shared] == 4000 and a.f.lock == "IDLE"
    world.check_conservation()


# ---- pure pieces -----------------------------------------------------------

def test_rating_examples():
    assert rt.update(1000, 1000, rt.WIN) == (1016, 984)
    assert rt.delta(1200, 1000, rt.WIN) == 9
    assert rt.delta(1200, 1000, rt.LOSS) == -22
    assert rt.delta(1200, 1000, rt.DRAW) == -6
    assert rt.update(3000, 0, rt.WIN) == (3000, 0)
    assert rt.update(5, 3000, rt.WIN) == (5 + 32 * (2000 - 100) // 2000, 3000 - 32 * (2000 - 100) // 2000)
    for ra in range(0, 3001, 97):
        for rb in range(0, 3001, 131):
            for s in (rt.WIN, rt.DRAW, rt.LOSS):
                x, y = rt.update(ra, rb, s)
                assert x + y == ra + rb and 0 <= x <= 3000 and 0 <= y <= 3000
                assert rt.update(rb, ra, 2000 - s) == (y, x)
    assert rt.belt(1100, True) == "orange" and rt.belt(2500, False) == "white"


def test_bracket_positions_and_series():
    assert seed_positions(8) == [1, 8, 4, 5, 2, 7, 3, 6]
    ids = [bytes([i]) * 32 for i in range(5)]
    slots = bracket([(1000 + i, ids[i]) for i in range(5)])
    assert slots[0] == ids[4] and slots.count(None) == 3
    s = Series.of(1)
    for w in ("A", None, "B", None, None):
        s.record(w)
    assert s.done and s.winner is None
    s = Series.of(1)
    s.record("A"), s.record("A")
    assert s.done and s.winner == "A"
