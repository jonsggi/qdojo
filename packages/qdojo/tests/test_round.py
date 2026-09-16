import pytest

from qdojo import hashing, payload as P
from qdojo.round import RoundSpec, evaluate, Observed
from conftest import ALICE, BOB, CARL, HOUSE

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
    assert all(e.verdict == "void" for e in ev.entries)
    assert s.state_at(60) == "lobby" and s.state_at(91) == "lobby_closed"


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
