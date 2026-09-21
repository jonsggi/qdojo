import pytest

from qdojo import hashing, payload as P, belts as B
from qdojo.round import RoundSpec, evaluate, Observed
from conftest import ALICE, BOB, CARL, HOUSE, ident

DOJO_SALT = b"\x0d" * 16
ANSWER = "42"


def spec(**over):
    d = dict(round_id=1, publish_tick=100, entry_fee=1000, commit_window=50, reveal_window=20,
             riddle_hash=b"\x11" * 32, answer_commitment=hashing.answer_commitment(1, DOJO_SALT, ANSWER),
             answer_format="integer", house_seed=10_000, rake_bps=500, payout_mode=P.MODE_SPLIT)
    d.update(over)
    return RoundSpec(**d)


def test_windows():
    s = spec()
    assert (s.commit_start, s.commit_end, s.reveal_start, s.reveal_end) == (101, 150, 151, 170)
    assert s.state_at(100) == "commit" and s.state_at(150) == "commit"
    assert s.state_at(151) == "reveal" and s.state_at(170) == "reveal" and s.state_at(171) == "settling"


def test_two_winners_split_pot_with_rake_and_carry(txf, salt):
    s = spec()
    obs = [
        txf.commit(ALICE, 110, 1, salt, "42", amount=1000),
        txf.commit(BOB, 111, 1, salt, "42", amount=1500),
        txf.commit(CARL, 112, 1, salt, "41", amount=1000),
        txf.reveal(ALICE, 155, 1, salt, "42"),
        txf.reveal(BOB, 156, 1, salt, "42"),
        txf.reveal(CARL, 157, 1, salt, "41"),
    ]
    ev = evaluate(s, obs, HOUSE, DOJO_SALT, ANSWER)
    assert ev.winners == [ALICE, BOB]
    assert ev.pot == 10_000 + 3500
    assert ev.rake == 3500 * 500 // 10000 == 175
    share = (13_500 - 175) // 2
    assert [(p.identity, p.amount, p.kind) for p in ev.payouts] == [(ALICE, share, "win"), (BOB, share, "win")]
    assert ev.carry == 13_325 - 2 * share == 1
    verdicts = {e.identity: e.verdict for e in ev.entries}
    assert verdicts == {ALICE: "winner", BOB: "winner", CARL: "wrong"}
    assert ev.strikes == {}


def test_no_winner_carries_everything_but_rake(txf, salt):
    s = spec()
    obs = [txf.commit(ALICE, 110, 1, salt, "7", amount=1000), txf.reveal(ALICE, 160, 1, salt, "7")]
    ev = evaluate(s, obs, HOUSE, DOJO_SALT, ANSWER)
    assert ev.winners == [] and ev.payouts == []
    assert ev.rake == 50 and ev.carry == 10_000 + 1000 - 50


def test_no_reveal_forfeits_stake(txf, salt):
    s = spec()
    obs = [txf.commit(ALICE, 110, 1, salt, "42", amount=1000)]
    ev = evaluate(s, obs, HOUSE, DOJO_SALT, ANSWER)
    assert ev.entries[0].verdict == "no_reveal" and ev.payouts == [] and ev.pot == 11_000


def test_late_and_underpaid_commits_are_refunded_and_do_not_play(txf, salt):
    s = spec()
    obs = [
        txf.commit(ALICE, 151, 1, salt, "42", amount=1000),   # one tick late
        txf.commit(BOB, 120, 1, salt, "42", amount=999),      # underpaid
        txf.reveal(ALICE, 160, 1, salt, "42"),
        txf.reveal(BOB, 160, 1, salt, "42"),
    ]
    ev = evaluate(s, obs, HOUSE, DOJO_SALT, ANSWER)
    assert {e.identity: e.verdict for e in ev.entries} == {ALICE: "late", BOB: "underpaid"}
    assert sorted((p.identity, p.amount, p.kind) for p in ev.payouts) == [(ALICE, 1000, "refund"), (BOB, 999, "refund")]
    assert ev.winners == [] and ev.pot == 10_000 and ev.carry == 10_000
    assert "reveal_without_commit" in ev.strikes[ALICE] and "reveal_without_commit" in ev.strikes[BOB]


def test_first_commit_counts_duplicate_is_struck_and_refunded(txf, salt):
    s = spec()
    obs = [
        txf.commit(ALICE, 110, 1, salt, "41", amount=1000),
        txf.commit(ALICE, 111, 1, salt, "42", amount=1000),
        txf.reveal(ALICE, 160, 1, salt, "42"),  # reveals the second commit: does not match the first
    ]
    ev = evaluate(s, obs, HOUSE, DOJO_SALT, ANSWER)
    assert ev.strikes[ALICE] == ["duplicate_commit", "bad_reveal"]
    assert ev.entries[0].verdict == "bad_reveal"
    assert [(p.identity, p.amount, p.kind) for p in ev.payouts] == [(ALICE, 1000, "refund")]


def test_reveal_must_match_own_commitment_not_copy(txf, salt):
    s = spec()
    other = b"\x99" * 16
    obs = [
        txf.commit(ALICE, 110, 1, salt, "42", amount=1000),
        txf.commit(BOB, 111, 1, other, "42", amount=1000),
        txf.reveal(ALICE, 160, 1, salt, "42"),
        txf.reveal(BOB, 161, 1, salt, "42"),  # Bob reveals with Alice's salt
    ]
    ev = evaluate(s, obs, HOUSE, DOJO_SALT, ANSWER)
    assert ev.winners == [ALICE]
    assert ev.strikes[BOB] == ["bad_reveal"]


def test_reveal_outside_window_is_ignored(txf, salt):
    s = spec()
    obs = [
        txf.commit(ALICE, 110, 1, salt, "42", amount=1000),
        txf.reveal(ALICE, 150, 1, salt, "42"),  # still in commit window
        txf.reveal(BOB, 171, 1, salt, "42"),
    ]
    ev = evaluate(s, obs, HOUSE, DOJO_SALT, ANSWER)
    assert ev.entries[0].verdict == "no_reveal"
    assert ev.strikes[ALICE] == ["reveal_outside_window"]


def test_foreign_and_other_round_traffic_is_ignored(txf, salt):
    s = spec()
    obs = [
        txf.commit(ALICE, 110, 1, salt, "42", amount=1000),
        txf.commit(BOB, 110, 2, salt, "42", amount=1000),                       # other round
        txf.tx(CARL, 110, None, amount=5, raw=b"\x00" * 100),                   # not a dojo payload
        txf.tx(CARL, 110, P.Commit(1, b"\x00" * 32), input_type=1),             # wrong input type
        txf.tx(CARL, 110, P.Commit(1, b"\x00" * 32), dest="Z" * 60),            # wrong destination
        txf.tx(CARL, 110, P.Bow("CARL"), amount=0),
        txf.reveal(ALICE, 160, 1, salt, "42"),
    ]
    ev = evaluate(s, obs, HOUSE, DOJO_SALT, ANSWER)
    assert [e.identity for e in ev.entries] == [ALICE] and ev.winners == [ALICE]


def test_amount_on_reveal_is_refunded(txf, salt):
    s = spec()
    obs = [txf.commit(ALICE, 110, 1, salt, "42", amount=1000), txf.reveal(ALICE, 160, 1, salt, "42", amount=5)]
    ev = evaluate(s, obs, HOUSE, DOJO_SALT, ANSWER)
    assert sorted(p.kind for p in ev.payouts) == ["refund", "win"]
    assert [p.amount for p in ev.payouts if p.kind == "refund"] == [5]


def test_final_requires_secret_that_matches_commitment(txf, salt):
    s = spec()
    with pytest.raises(ValueError):
        evaluate(s, [], HOUSE, None, None)
    with pytest.raises(ValueError):
        evaluate(s, [], HOUSE, DOJO_SALT, "43")


def test_mid_round_view_gives_no_money_and_no_final_verdicts(txf, salt):
    s = spec()
    obs = [txf.commit(ALICE, 110, 1, salt, "42", amount=1000), txf.reveal(ALICE, 160, 1, salt, "42")]
    ev = evaluate(s, obs, HOUSE, None, None, final=False)
    assert ev.entries[0].verdict == "pending" and ev.entries[0].answer == "42"
    assert ev.payouts == [] and ev.pot == 0


def test_too_many_transactions_is_a_strike(txf, salt):
    s = spec()
    obs = [txf.commit(ALICE, 110, 1, salt, "42", amount=1000)]
    obs += [txf.tx(ALICE, 120 + i, P.Commit(1, b"\x00" * 32)) for i in range(9)]
    ev = evaluate(s, obs, HOUSE, DOJO_SALT, ANSWER)
    assert "too_many_transactions" in ev.strikes[ALICE]
    assert ev.strikes[ALICE].count("too_many_transactions") == 1


def test_order_is_by_tick_then_txid_not_list_order(txf, salt):
    s = spec()
    a2 = txf.commit(ALICE, 112, 1, salt, "41", amount=1000)
    a1 = txf.commit(ALICE, 111, 1, salt, "42", amount=1000)
    obs = [a2, a1, txf.reveal(ALICE, 160, 1, salt, "42")]
    ev = evaluate(s, obs, HOUSE, DOJO_SALT, ANSWER)
    assert ev.entries[0].commit_tx == a1.tx_id and ev.winners == [ALICE]


def test_money_balances_in_every_case(txf, salt):
    s = spec(house_seed=1234, rake_bps=333)
    obs = [
        txf.commit(ALICE, 110, 1, salt, "42", amount=1001),
        txf.commit(BOB, 111, 1, salt, "42", amount=1002),
        txf.commit(CARL, 112, 1, salt, "1", amount=1003),
        txf.commit("D" * 60, 112, 1, salt, "1", amount=7),        # underpaid -> refund
        txf.reveal(ALICE, 160, 1, salt, "42"), txf.reveal(BOB, 160, 1, salt, "42"),
    ]
    ev = evaluate(s, obs, HOUSE, DOJO_SALT, ANSWER)
    refunds = sum(p.amount for p in ev.payouts if p.kind == "refund")
    assert ev.total_out + ev.rake + ev.carry == ev.pot + refunds


def test_first_wins_pays_the_earliest_commit_tick_only(txf, salt):
    s = spec(payout_mode=P.MODE_FIRST)
    obs = [
        txf.commit(BOB, 112, 1, salt, "42", amount=1000),
        txf.commit(ALICE, 110, 1, salt, "42", amount=1000),
        txf.commit(CARL, 110, 1, salt, "41", amount=1000),   # early but wrong
        txf.reveal(ALICE, 160, 1, salt, "42"), txf.reveal(BOB, 161, 1, salt, "42"), txf.reveal(CARL, 162, 1, salt, "41"),
    ]
    ev = evaluate(s, obs, HOUSE, DOJO_SALT, ANSWER)
    assert ev.winners == [ALICE]
    assert {e.identity: e.verdict for e in ev.entries} == {BOB: "solved", ALICE: "winner", CARL: "wrong"}
    assert ev.pot == 13_000 and ev.rake == 150
    assert [(p.identity, p.amount) for p in ev.payouts] == [(ALICE, 13_000 - 150)]


def test_first_wins_same_tick_shares(txf, salt):
    s = spec(payout_mode=P.MODE_FIRST)
    obs = [
        txf.commit(ALICE, 110, 1, salt, "42", amount=1000), txf.commit(BOB, 110, 1, salt, "42", amount=1000),
        txf.commit(CARL, 111, 1, salt, "42", amount=1000),
        txf.reveal(ALICE, 160, 1, salt, "42"), txf.reveal(BOB, 160, 1, salt, "42"), txf.reveal(CARL, 160, 1, salt, "42"),
    ]
    ev = evaluate(s, obs, HOUSE, DOJO_SALT, ANSWER)
    assert ev.winners == [ALICE, BOB]
    share = (13_000 - 150) // 2
    assert sorted((p.identity, p.amount) for p in ev.payouts) == [(ALICE, share), (BOB, share)]
    assert ev.carry == 13_000 - 150 - 2 * share


def test_first_wins_reveal_order_does_not_matter(txf, salt):
    s = spec(payout_mode=P.MODE_FIRST)
    obs = [
        txf.commit(ALICE, 110, 1, salt, "42", amount=1000), txf.commit(BOB, 120, 1, salt, "42", amount=1000),
        txf.reveal(BOB, 151, 1, salt, "42"), txf.reveal(ALICE, 170, 1, salt, "42"),   # Bob reveals first
    ]
    ev = evaluate(s, obs, HOUSE, DOJO_SALT, ANSWER)
    assert ev.winners == [ALICE]


def test_matching_seed_follows_stakes_up_to_the_cap(txf, salt):
    s = spec(house_seed=5000, match_bps=10000, rake_bps=0, payout_mode=P.MODE_SPLIT)
    obs = [txf.commit(ALICE, 110, 1, salt, "42", amount=1000), txf.commit(BOB, 111, 1, salt, "1", amount=2000),
           txf.reveal(ALICE, 160, 1, salt, "42"), txf.reveal(BOB, 160, 1, salt, "1")]
    ev = evaluate(s, obs, HOUSE, DOJO_SALT, ANSWER)
    assert ev.seed_used == 3000 and ev.pot == 6000 and ev.payouts[0].amount == 6000
    s2 = spec(house_seed=5000, match_bps=10000, payout_mode=P.MODE_SPLIT)
    obs2 = [txf.commit(ALICE, 110, 1, salt, "42", amount=7000), txf.reveal(ALICE, 160, 1, salt, "42")]
    ev2 = evaluate(s2, obs2, HOUSE, DOJO_SALT, ANSWER)
    assert ev2.seed_used == 5000                                     # the cap binds
    s3 = spec(house_seed=5000, match_bps=5000, payout_mode=P.MODE_SPLIT)
    assert evaluate(s3, obs2, HOUSE, DOJO_SALT, ANSWER).seed_used == 3500   # half matching
    s4 = spec(house_seed=5000, match_bps=0, payout_mode=P.MODE_SPLIT)
    assert evaluate(s4, [], HOUSE, DOJO_SALT, ANSWER).seed_used == 5000     # fixed seed, even for nobody
    s5 = spec(house_seed=5000, match_bps=10000, payout_mode=P.MODE_SPLIT)
    assert evaluate(s5, [], HOUSE, DOJO_SALT, ANSWER).seed_used == 0        # matching: an empty round costs nothing


def test_carry_in_is_always_in_the_pot(txf, salt):
    s = spec(house_seed=5000, match_bps=10000, carry_in=800, payout_mode=P.MODE_SPLIT)
    ev = evaluate(s, [], HOUSE, DOJO_SALT, ANSWER)
    assert ev.seed_used == 800 and ev.pot == 800 and ev.carry == 800    # rolls on, untouched


def lobby_spec(**over):
    d = dict(lobby_tick=50, lobby_window=40, min_players=2, publish_tick=100, match_bps=10000, house_seed=5000,
             rake_bps=0, payout_mode=P.MODE_FIRST)
    d.update(over)
    return spec(**d)


def test_lobby_round_stake_rides_on_enter_not_commit(txf, salt):
    s = lobby_spec()
    obs = [
        txf.tx(ALICE, 60, P.Enter(1), amount=1000), txf.tx(BOB, 61, P.Enter(1), amount=1000),
        txf.tx(CARL, 62, P.Enter(1), amount=1000),
        txf.commit(ALICE, 110, 1, salt, "42", amount=0), txf.commit(BOB, 111, 1, salt, "42", amount=7),  # 7 refunded
        txf.reveal(ALICE, 160, 1, salt, "42"), txf.reveal(BOB, 160, 1, salt, "42"),
    ]
    ev = evaluate(s, obs, HOUSE, DOJO_SALT, ANSWER)
    assert {e.identity: e.verdict for e in ev.entries} == {ALICE: "winner", BOB: "solved", CARL: "no_commit"}
    assert ev.pot == 3000 + 3000 and ev.winners == [ALICE]        # three seats, matched 1:1
    assert sorted((p.identity, p.amount, p.kind) for p in ev.payouts) == [(ALICE, 6000, "win"), (BOB, 7, "refund")]
    assert all(e.enter_tx for e in ev.entries)


def test_lobby_commit_without_seat_is_a_strike_and_late_enter_refunded(txf, salt):
    s = lobby_spec()
    obs = [
        txf.tx(ALICE, 60, P.Enter(1), amount=1000),
        txf.tx(BOB, 95, P.Enter(1), amount=1000),                        # after the lobby window
        txf.tx(CARL, 61, P.Enter(1), amount=999),                        # underpaid
        txf.tx(ALICE, 62, P.Enter(1), amount=1000),                      # duplicate seat, refunded
        txf.commit(BOB, 110, 1, salt, "42"), txf.reveal(BOB, 160, 1, salt, "42"),
        txf.commit(ALICE, 110, 1, salt, "42"), txf.reveal(ALICE, 160, 1, salt, "42"),
    ]
    ev = evaluate(s, obs, HOUSE, DOJO_SALT, ANSWER)
    assert ev.winners == [ALICE]
    assert ev.strikes[BOB] == ["commit_without_entry", "reveal_without_commit"]
    assert ev.strikes[ALICE] == ["duplicate_enter"]
    assert sorted((p.identity, p.amount) for p in ev.payouts if p.kind == "refund") == [(ALICE, 1000), (BOB, 1000), (CARL, 999)]


def test_void_refunds_every_seat(txf):
    from qdojo.round import void
    s = lobby_spec(publish_tick=None)
    obs = [txf.tx(ALICE, 60, P.Enter(1), amount=1000), txf.tx(BOB, 95, P.Enter(1), amount=1000)]
    ev = void(s, obs, HOUSE)
    assert sorted((p.identity, p.amount, p.kind) for p in ev.payouts) == [(ALICE, 1000, "refund"), (BOB, 1000, "refund")]
    # ALICE bought a seat (was "pending"): void() turns that into "void". BOB's
    # ENTER at tick 95 is after the lobby window (ends at 90): it was already
    # refused as "late" and kept that verdict -- it never bought a seat, so it
    # is refunded but does not count as an occupied one (MONEY #3).
    assert {e.identity: e.verdict for e in ev.entries} == {ALICE: "void", BOB: "late"}
    assert s.state_at(60) == "lobby" and s.state_at(91) == "lobby_closed"


def test_void_keeps_an_outranked_refusal_instead_of_folding_it_into_void(txf):
    """Regression (MONEY #3): a void round used to overwrite every verdict,
    including a refused ENTER, with 'void', so the seats a bot published for
    a voided strict table counted refused fighters as occupancy the quorum
    never saw. void() now takes the belts the lobby quorum saw and keeps
    'outranked' as such."""
    from qdojo.round import void
    s = lobby_spec(publish_tick=None, belt_rank=B.RANKS["white"])
    obs = [txf.tx(ALICE, 60, P.Enter(1), amount=1000),
           txf.tx(BOB, 61, P.Enter(1), amount=1000)]
    belts = {BOB: {"belt": "blue", "rank": B.RANKS["blue"], "points": 0}}
    ev = void(s, obs, HOUSE, belts=belts)
    assert {e.identity: e.verdict for e in ev.entries} == {ALICE: "void", BOB: "outranked"}
    assert sorted((p.identity, p.amount) for p in ev.payouts) == [(ALICE, 1000), (BOB, 1000)]   # still refunded


def test_podium_splits_5_3_2_by_commit_order(txf, salt):
    s = spec(payout_mode=P.MODE_PODIUM, rake_bps=0, house_seed=7000)
    obs = []
    for who, tick in ((ALICE, 110), (BOB, 111), (CARL, 112), ("D" * 60, 113)):
        obs.append(txf.commit(who, tick, 1, salt, "42", amount=1000))
        obs.append(txf.reveal(who, 160, 1, salt, "42"))
    ev = evaluate(s, obs, HOUSE, DOJO_SALT, ANSWER)
    assert ev.winners == [ALICE, BOB, CARL] and ev.pot == 11_000
    assert [(p.identity[0], p.amount) for p in ev.payouts] == [("A", 5500), ("B", 3300), ("C", 2200)]
    assert {e.identity[0]: e.verdict for e in ev.entries}["D"] == "solved" and ev.carry == 0
    two = evaluate(s, obs[:4], HOUSE, DOJO_SALT, ANSWER)          # only two solvers: 5:3
    assert [p.amount for p in two.payouts] == [9000 * 5 // 8, 9000 * 3 // 8] and two.carry == 9000 - 5625 - 3375


def test_bond_is_held_from_every_win_and_money_still_balances(txf, salt):
    s = spec(payout_mode=P.MODE_FIRST, rake_bps=0, house_seed=9000, bond_bps=5000, bond_rounds=3)
    obs = [txf.commit(ALICE, 110, 1, salt, "42", amount=1000), txf.reveal(ALICE, 160, 1, salt, "42"),
           txf.commit(BOB, 120, 1, salt, "41", amount=7), txf.reveal(BOB, 160, 1, salt, "41")]
    ev = evaluate(s, obs, HOUSE, DOJO_SALT, ANSWER)
    assert ev.pot == 10_000 and ev.payouts[0].amount == 5000 and ev.bonds[0].amount == 5000   # Bob's 7 is underpaid: refunded, not in the pot
    assert [p for p in ev.payouts if p.kind == "refund"][0].amount == 7
    assert ev.payouts[0].amount + ev.bonds[0].amount + ev.carry == ev.pot


def test_house_fighter_stakes_join_the_pot_but_are_not_matched(txf, salt):
    s = spec(house_seed=5000, match_bps=10000, rake_bps=0, payout_mode=P.MODE_SPLIT, house_fighters=(BOB, CARL))
    obs = [txf.commit(ALICE, 110, 1, salt, "42", amount=1000), txf.commit(BOB, 111, 1, salt, "1", amount=1000),
           txf.commit(CARL, 112, 1, salt, "1", amount=1000), txf.reveal(ALICE, 160, 1, salt, "42")]
    ev = evaluate(s, obs, HOUSE, DOJO_SALT, ANSWER)
    assert ev.seed_used == 1000 and ev.pot == 4000                     # matched Alice only; all three stakes in the pot
    only_npcs = [txf.commit(BOB, 111, 1, salt, "1", amount=1000), txf.commit(CARL, 112, 1, salt, "1", amount=1000)]
    ev2 = evaluate(s, only_npcs, HOUSE, DOJO_SALT, ANSWER)
    assert ev2.seed_used == 0 and ev2.pot == 2000 and ev2.carry == 2000  # an NPC-only table costs the house nothing new


def test_rake_splits_three_ways(txf, salt):
    s = spec(rake_bps=1000, rake_house_bps=6000, rake_dev_bps=1000, rake_share_bps=3000, house_seed=0, payout_mode=P.MODE_SPLIT)
    obs = [txf.commit(ALICE, 110, 1, salt, "42", amount=10000), txf.reveal(ALICE, 160, 1, salt, "42")]
    ev = evaluate(s, obs, HOUSE, DOJO_SALT, ANSWER)
    assert ev.rake == 1000 and ev.rake_split == {"house": 600, "dev": 100, "shareholders": 300}
    assert ev.payouts[0].amount == 10000 - 1000                       # winner still gets pot minus the whole rake


def test_sensei_may_sit_below_its_belt_but_wins_back_only_its_stake(txf, salt):
    """A blue belt teaching at a white table: it pays, it can win, but it
    cannot take more than it put in, and the surplus goes to the real winner."""
    belts = {ALICE: {"rank": 4, "points": 0}}                     # Alice is blue, the table is white
    s = spec(belt_rank=0, sensei=True, rake_bps=0, house_seed=9000, match_bps=0, payout_mode=P.MODE_SPLIT)
    obs = [txf.commit(ALICE, 110, 1, salt, "42", amount=1000), txf.commit(BOB, 111, 1, salt, "42", amount=1000),
           txf.reveal(ALICE, 160, 1, salt, "42"), txf.reveal(BOB, 160, 1, salt, "42")]
    ev = evaluate(s, obs, HOUSE, DOJO_SALT, ANSWER, belts=belts)
    a = next(e for e in ev.entries if e.identity == ALICE)
    assert a.sensei and a.verdict == "winner" and not next(e for e in ev.entries if e.identity == BOB).sensei
    pay = {p.identity: p.amount for p in ev.payouts}
    assert pay[ALICE] == 1000                                      # capped at its own stake
    assert pay[BOB] == 11_000 - 1000                               # the whole surplus went to the white belt
    assert ev.pot == 11_000 and ev.carry == 0


def test_sensei_surplus_carries_when_no_one_else_wins(txf, salt):
    belts = {ALICE: {"rank": 4, "points": 0}}
    s = spec(belt_rank=0, sensei=True, rake_bps=0, house_seed=9000, match_bps=0, payout_mode=P.MODE_SPLIT)
    obs = [txf.commit(ALICE, 110, 1, salt, "42", amount=1000), txf.commit(BOB, 111, 1, salt, "1", amount=1000),
           txf.reveal(ALICE, 160, 1, salt, "42"), txf.reveal(BOB, 160, 1, salt, "1")]
    ev = evaluate(s, obs, HOUSE, DOJO_SALT, ANSWER, belts=belts)
    assert [(p.identity, p.amount) for p in ev.payouts] == [(ALICE, 1000)]
    assert ev.carry == 11_000 - 1000                               # the rest stays for the next white table


def test_without_sensei_the_same_fighter_is_refused(txf, salt):
    belts = {ALICE: {"rank": 4, "points": 0}}
    s = spec(belt_rank=0, sensei=False, rake_bps=0, payout_mode=P.MODE_SPLIT)
    obs = [txf.commit(ALICE, 110, 1, salt, "42", amount=1000), txf.reveal(ALICE, 160, 1, salt, "42")]
    ev = evaluate(s, obs, HOUSE, DOJO_SALT, ANSWER, belts=belts)
    assert ev.entries[0].verdict == "outranked" and ev.payouts[0].kind == "refund"


# ------------------------------------------------------------------ two pots
# The belt pot (seed + carry + at-belt stakes) pays at-belt solvers; the sensei
# pot (sensei stakes only) pays sensei solvers. docs/spec.md §5-6, issue #10.

BLUE = {"rank": 4, "points": 0}
GREEN = {"rank": 3, "points": 0}
ORANGE = {"rank": 2, "points": 0}
WHITE = {"rank": 0, "points": 0}


def _table(txf, salt, seats):
    """seats: (identity, commit_tick, answer). Every seat stakes 1000 and reveals."""
    obs = []
    for who, tick, ans in seats:
        obs.append(txf.commit(who, tick, 1, salt, ans, amount=1000))
        obs.append(txf.reveal(who, 160, 1, salt, ans))
    return obs


def _round89(**over):
    """Round 89's terms: an orange table, podium, 20% rake split 60/10/30,
    5,000 cap matched 1:1, 13,200 carried in, 50% bond for 3 fights."""
    d = dict(belt_rank=2, sensei=True, payout_mode=P.MODE_PODIUM, rake_bps=2000, rake_house_bps=6000,
             rake_dev_bps=1000, rake_share_bps=3000, house_seed=5000, match_bps=10000, carry_in=13_200,
             bond_bps=5000, bond_rounds=3)
    d.update(over)
    return spec(**d)


def test_round_89_the_seniors_settle_among_themselves_and_the_beginners_money_waits(txf, salt):
    """Issue #10's worked example: ten senseis (eight blue, two green) and four
    at-belt fighters at an orange table. Sensei pot 10,000 - rake 2,000 ->
    4,000 / 2,400 / 1,600 (was 1,000 each under the cap); the belt pot
    13,200 + 4,000 + 4,000 has no at-belt solver, so it carries."""
    senseis = [(c + "ABCDEFGHIJ"[i]).ljust(60, c) for i, c in enumerate("SCOWFQYXZL")]   # 60 letters, all distinct
    at_belt = [ident("M"), ident("K"), ident("Q"), ident("A")]
    belts = {s: (BLUE if i < 8 else GREEN) for i, s in enumerate(senseis)}
    belts |= {at_belt[0]: ORANGE, at_belt[1]: ORANGE, at_belt[2]: WHITE, at_belt[3]: WHITE}
    seats = [(senseis[0], 131, "42"), (senseis[1], 133, "42"), (senseis[2], 135, "42")]        # the sensei podium
    seats += [(s, 140 + i, "42") for i, s in enumerate(senseis[3:])]                          # seven more, correct but later
    seats += [(a, 136 + i, "1") for i, a in enumerate(at_belt)]                               # nobody at the belt solves
    ev = evaluate(_round89(), _table(txf, salt, seats), HOUSE, DOJO_SALT, ANSWER, belts=belts)
    # The real round had pot 32,200: the cap matched 5,000 because it matched the
    # senseis' stakes too. Now the house matches the 4,000 at the belt and no more.
    assert ev.pot == 31_200 and ev.seed_used == 13_200 + 4000 and ev.rake == 2800
    assert ev.pots["sensei"] == {"carry_in": 0, "matched": 0, "stakes": 10_000, "pot": 10_000, "rake": 2000,
                                 "distributable": 8000, "paid": 8000, "carry": 0, "winners": senseis[:3],
                                 "payouts": [{"identity": senseis[0], "amount": 4000}, {"identity": senseis[1], "amount": 2400},
                                             {"identity": senseis[2], "amount": 1600}]}
    assert ev.pots["belt"] == {"carry_in": 13_200, "matched": 4000, "stakes": 4000, "pot": 21_200, "rake": 800,
                               "distributable": 20_400, "paid": 0, "carry": 20_400, "winners": [], "payouts": []}
    assert ev.winners == senseis[:3] and ev.carry == 20_400
    wins = {p.identity: p.amount for p in ev.payouts if p.kind == "win"}
    assert wins == {senseis[0]: 2000, senseis[1]: 1200, senseis[2]: 800}                  # half of each win is the bond
    assert [(b.identity, b.amount) for b in ev.bonds] == [(senseis[0], 2000), (senseis[1], 1200), (senseis[2], 800)]
    assert {e.identity: e.verdict for e in ev.entries}[senseis[3]] == "solved"
    assert all(e.sensei for e in ev.entries if e.identity in senseis) and not any(e.sensei for e in ev.entries if e.identity in at_belt)


def test_round_89_with_the_at_belt_solvers_it_actually_had(txf, salt):
    """The real round 89 had two orange fighters solve it behind the senseis.
    Under the cap they were 'solved' and unpaid; under two pots the belt pot
    is theirs, 5:3, and nothing carries."""
    senseis = [(c + "ABCDEFGHIJ"[i]).ljust(60, c) for i, c in enumerate("SCOWFQYXZL")]
    k, m, q, a = ident("K"), ident("M"), ident("Q"), ident("A")
    belts = {s: BLUE for s in senseis} | {k: ORANGE, m: ORANGE, q: WHITE, a: WHITE}
    seats = [(senseis[0], 131, "42"), (senseis[1], 133, "42"), (senseis[2], 135, "42")]
    seats += [(s, 140 + i, "42") for i, s in enumerate(senseis[3:])]
    seats += [(k, 135, "42"), (m, 141, "42"), (q, 133, "1"), (a, 137, "1")]
    ev = evaluate(_round89(), _table(txf, salt, seats), HOUSE, DOJO_SALT, ANSWER, belts=belts)
    assert ev.pots["belt"]["winners"] == [k, m] and ev.pots["belt"]["payouts"] == [
        {"identity": k, "amount": 20_400 * 5 // 8}, {"identity": m, "amount": 20_400 * 3 // 8}]
    assert ev.pots["sensei"]["payouts"][0] == {"identity": senseis[0], "amount": 4000}
    assert ev.winners == [k, m] + senseis[:3]
    assert ev.carry == 20_400 - 12_750 - 7650 == ev.pots["belt"]["carry"] + ev.pots["sensei"]["carry"]


def test_all_sensei_table_the_carry_stands_and_the_ratchet_never_starts(txf, salt):
    """Rounds 112-118's shape: seven blue senseis alone at a white table with
    7,600 carried in. The house matches nothing (no at-belt stake), the carry
    waits untouched for a white belt, and the seniors play for their 7,000."""
    senseis = [ident(c) for c in "ABCDEFG"]
    belts = {s: BLUE for s in senseis}
    s = _round89(belt_rank=0, carry_in=7600)
    seats = [(senseis[0], 110, "42"), (senseis[1], 111, "42"), (senseis[2], 112, "42"), (senseis[3], 113, "42"),
             (senseis[4], 114, "1"), (senseis[5], 115, "1"), (senseis[6], 116, "1")]
    ev = evaluate(s, _table(txf, salt, seats), HOUSE, DOJO_SALT, ANSWER, belts=belts)
    assert ev.seed_used == 7600 and ev.pots["belt"]["matched"] == 0             # not one QU of new seed
    assert ev.pot == 7600 + 7000 and ev.rake == 1400
    assert ev.pots["belt"]["carry"] == 7600 and ev.pots["belt"]["winners"] == []
    assert [(p["identity"], p["amount"]) for p in ev.pots["sensei"]["payouts"]] == [
        (senseis[0], 2800), (senseis[1], 1680), (senseis[2], 1120)]              # 5:3:2 of 5,600
    assert ev.carry == 7600                                                       # was 7,600 + 5,600 - 3,000 under the cap
    # Round 113 opens with the same carry, so the pot stops growing on sensei-only tables.
    nxt = evaluate(_round89(belt_rank=1, carry_in=ev.carry), _table(txf, salt, seats), HOUSE, DOJO_SALT, ANSWER, belts=belts)
    assert nxt.carry == 7600 and nxt.seed_used == 7600


def test_a_lone_sensei_wins_back_at_most_its_stake_less_the_rake(txf, salt):
    """The old cap as a special case: alone in its pot a sensei can only win its own money."""
    belts = {ALICE: BLUE}
    s = _round89(belt_rank=0, carry_in=0, bond_bps=0)
    ev = evaluate(s, _table(txf, salt, [(ALICE, 110, "42"), (BOB, 111, "1"), (CARL, 112, "1")]),
                  HOUSE, DOJO_SALT, ANSWER, belts=belts)
    assert [(p.identity, p.amount) for p in ev.payouts] == [(ALICE, 800)]         # 1,000 less the 20% rake
    assert ev.pots["belt"] == {"carry_in": 0, "matched": 2000, "stakes": 2000, "pot": 4000, "rake": 400,
                               "distributable": 3600, "paid": 0, "carry": 3600, "winners": [], "payouts": []}
    assert ev.seed_used == 2000                                                   # Bob and Carl matched, Alice not


def test_a_sensei_pot_nobody_wins_carries_down_to_the_belt(txf, salt):
    belts = {ALICE: BLUE}
    s = _round89(belt_rank=0, carry_in=0, bond_bps=0)
    ev = evaluate(s, _table(txf, salt, [(ALICE, 110, "1"), (BOB, 111, "42")]), HOUSE, DOJO_SALT, ANSWER, belts=belts)
    assert ev.pots["sensei"]["carry"] == 800 and ev.pots["belt"]["paid"] == 1000 + 1000 - 200
    assert ev.carry == 800                                                        # next round's carry_in, belt money from then on


def test_first_mode_runs_once_per_pot(txf, salt):
    """Under `first` each pot goes to its own earliest tick: a sensei that
    commits first does not take the belt pot, and the belt's first solver
    does not have to beat the seniors."""
    belts = {ALICE: BLUE, BOB: WHITE, CARL: WHITE}
    s = _round89(belt_rank=0, carry_in=0, bond_bps=0, payout_mode=P.MODE_FIRST, rake_bps=0)
    ev = evaluate(s, _table(txf, salt, [(ALICE, 110, "42"), (BOB, 120, "42"), (CARL, 121, "42")]),
                  HOUSE, DOJO_SALT, ANSWER, belts=belts)
    assert ev.pots["belt"]["winners"] == [BOB] and ev.pots["sensei"]["winners"] == [ALICE]
    assert {p.identity: p.amount for p in ev.payouts} == {BOB: 2000 + 2000, ALICE: 1000}
    assert {e.identity: e.verdict for e in ev.entries}[CARL] == "solved"


def test_without_senseis_the_two_pots_are_the_old_single_pot(txf, salt):
    """No sensei at the table: every number the old settlement produced,
    unchanged, and the sensei pot is an explicit zero."""
    s = spec(payout_mode=P.MODE_PODIUM, rake_bps=2000, house_seed=5000, match_bps=10000, carry_in=3333,
             bond_bps=5000, bond_rounds=3)
    seats = [(ALICE, 110, "42"), (BOB, 111, "42"), (CARL, 111, "1"), (ident("D"), 112, "42"), (ident("E"), 113, "42")]
    ev = evaluate(s, _table(txf, salt, seats), HOUSE, DOJO_SALT, ANSWER)
    stakes, seed = 5000, 3333 + 5000
    rake = stakes * 2000 // 10000
    dist = seed + stakes - rake
    gross = [dist * 5 // 10, dist * 3 // 10, dist * 2 // 10]
    assert (ev.pot, ev.seed_used, ev.rake, ev.carry) == (seed + stakes, seed, rake, dist - sum(gross))
    assert ev.winners == [ALICE, BOB, ident("D")]
    assert [(p.identity, p.amount) for p in ev.payouts] == [(ALICE, gross[0] - gross[0] // 2), (BOB, gross[1] - gross[1] // 2),
                                                            (ident("D"), gross[2] - gross[2] // 2)]
    assert [b.amount for b in ev.bonds] == [g // 2 for g in gross]
    assert ev.pots["sensei"] == {"carry_in": 0, "matched": 0, "stakes": 0, "pot": 0, "rake": 0, "distributable": 0,
                                 "paid": 0, "carry": 0, "winners": [], "payouts": []}
    b = ev.pots["belt"]
    assert (b["pot"], b["rake"], b["carry"], b["winners"]) == (ev.pot, ev.rake, ev.carry, ev.winners)
    assert b["carry_in"] + b["matched"] == ev.seed_used


def test_the_pots_add_up_to_the_settlement_and_are_published(txf, salt):
    from qdojo.round import to_dict, void
    belts = {ALICE: BLUE, BOB: BLUE}
    s = _round89(belt_rank=0)
    ev = evaluate(s, _table(txf, salt, [(ALICE, 110, "42"), (BOB, 110, "1"), (CARL, 111, "42")]),
                  HOUSE, DOJO_SALT, ANSWER, belts=belts)
    b, se = ev.pots["belt"], ev.pots["sensei"]
    assert b["pot"] + se["pot"] == ev.pot and b["rake"] + se["rake"] == ev.rake and b["carry"] + se["carry"] == ev.carry
    assert b["carry_in"] + b["matched"] == ev.seed_used and b["winners"] + se["winners"] == ev.winners
    assert b["paid"] + se["paid"] == sum(p.amount for p in ev.payouts if p.kind == "win") + sum(x.amount for x in ev.bonds)
    d = to_dict(ev)
    assert d["pots"] == ev.pots and d["pot"] == ev.pot                          # additive: the old fields stay
    lobby = spec(lobby_tick=50, lobby_window=40, min_players=5)
    assert "pots" not in to_dict(void(lobby, [], HOUSE))                        # a void table has no pots


# ----------------------------------------------------------------- dead heats
# Same-tick correct commits share a placing and split the placings' weights
# (docs/spec.md §5 "Ties", docs/product-decisions.md "Regular-round ties").

D_, E_, F_ = ident("D"), ident("E"), ident("F")


def _podium(txf, salt, seats, **over):
    s = spec(payout_mode=P.MODE_PODIUM, rake_bps=0, house_seed=7000, **over)   # 10,000 to share: one part is 1,000
    return evaluate(s, _table(txf, salt, seats), HOUSE, DOJO_SALT, ANSWER, belts=over.get("belts"))


def test_two_tied_for_first_take_four_parts_each_and_third_takes_two(txf, salt):
    ev = _podium(txf, salt, [(ALICE, 110, "42"), (BOB, 110, "42"), (CARL, 111, "42"), (D_, 112, "42")])
    assert ev.pot == 11_000
    assert {p.identity: p.amount for p in ev.payouts} == {ALICE: 4400, BOB: 4400, CARL: 2200}
    assert ev.winners == [ALICE, BOB, CARL] and ev.carry == 0
    assert {e.identity: e.verdict for e in ev.entries}[D_] == "solved"


def test_two_tied_for_second_split_second_and_third(txf, salt):
    ev = _podium(txf, salt, [(ALICE, 110, "42"), (BOB, 111, "42"), (CARL, 111, "42"), (D_, 112, "42")])
    assert {p.identity: p.amount for p in ev.payouts} == {ALICE: 5500, BOB: 2750, CARL: 2750}
    assert {e.identity: e.verdict for e in ev.entries}[D_] == "solved"      # the podium is full at three


def test_four_tied_for_third_all_stand_on_the_podium(txf, salt):
    ev = _podium(txf, salt, [(ALICE, 110, "42"), (BOB, 111, "42"), (CARL, 112, "42"), (D_, 112, "42"),
                             (E_, 112, "42"), (F_, 112, "42"), (ident("G"), 113, "42")])
    dist = 7000 + 7000
    assert {p.identity: p.amount for p in ev.payouts} == {ALICE: dist * 5 // 10, BOB: dist * 3 // 10,
                                                          CARL: 700, D_: 700, E_: 700, F_: 700}
    assert len(ev.winners) == 6 and ev.carry == 0
    assert {e.identity: e.verdict for e in ev.entries}[ident("G")] == "solved"


def test_three_or_more_tied_for_first_split_everything_evenly(txf, salt):
    ev = _podium(txf, salt, [(ALICE, 110, "42"), (BOB, 110, "42"), (CARL, 110, "42"), (D_, 111, "42")])
    assert {p.identity: p.amount for p in ev.payouts} == {ALICE: 11_000 // 3, BOB: 11_000 // 3, CARL: 11_000 // 3}
    assert ev.carry == 11_000 - 3 * (11_000 // 3)
    assert {e.identity: e.verdict for e in ev.entries}[D_] == "solved"     # a tie for first can fill the podium
    five = _podium(txf, salt, [(who, 110, "42") for who in (ALICE, BOB, CARL, D_, E_)])
    assert [p.amount for p in five.payouts] == [12_000 // 5] * 5 and five.winners == [ALICE, BOB, CARL, D_, E_]


def test_a_tie_is_a_dead_heat_not_a_transaction_id_lottery(txf, salt):
    """The same tick in either transaction order pays the same money to each."""
    a = _podium(txf, salt, [(ALICE, 110, "42"), (BOB, 110, "42"), (CARL, 111, "42")])
    b = _podium(txf, salt, [(BOB, 110, "42"), (ALICE, 110, "42"), (CARL, 111, "42")])
    assert {p.identity: p.amount for p in a.payouts} == {p.identity: p.amount for p in b.payouts}
    assert a.payouts[0].amount == a.payouts[1].amount


def test_first_mode_still_splits_the_earliest_tick_equally(txf, salt):
    s = spec(payout_mode=P.MODE_FIRST, rake_bps=0, house_seed=7000)
    ev = evaluate(s, _table(txf, salt, [(ALICE, 110, "42"), (BOB, 110, "42"), (CARL, 111, "42")]), HOUSE, DOJO_SALT, ANSWER)
    assert {p.identity: p.amount for p in ev.payouts} == {ALICE: 5000, BOB: 5000}


def test_dead_heats_are_settled_per_pot_on_a_sensei_table(txf, salt):
    """Two senseis tied for first in their pot; two beginners tied for first
    in theirs. Each pot runs its own dead heat, the tick shared across pots
    means nothing."""
    belts = {ALICE: BLUE, BOB: BLUE}
    s = _round89(belt_rank=0, carry_in=2000, bond_bps=0, rake_bps=0)
    seats = [(ALICE, 110, "42"), (BOB, 110, "42"), (CARL, 110, "42"), (D_, 110, "42"), (E_, 111, "42"), (F_, 112, "1")]
    ev = evaluate(s, _table(txf, salt, seats), HOUSE, DOJO_SALT, ANSWER, belts=belts)
    assert ev.pots["sensei"]["payouts"] == [{"identity": ALICE, "amount": 1000}, {"identity": BOB, "amount": 1000}]
    belt_dist = 2000 + 4000 + 4000                                          # carry, four beginners matched, their stakes
    assert ev.pots["belt"]["payouts"] == [{"identity": CARL, "amount": belt_dist * 8 // 10 // 2},
                                          {"identity": D_, "amount": belt_dist * 8 // 10 // 2},
                                          {"identity": E_, "amount": belt_dist * 2 // 10}]
    assert ev.winners == [CARL, D_, E_, ALICE, BOB]
