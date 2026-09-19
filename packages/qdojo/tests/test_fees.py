"""The entry-fee controller (docs/spec.md §5, docs/api.md): pure arithmetic
over history rows, so the house and a bot reading history.json agree."""
import random

import pytest

from qdojo import fees

POLICY = fees.FeePolicy(alpha=0.5, window=8, headroom=2, clamp=1.5, floor=100, start=1000)


def rows(belt, entrants, fee=1000, state="settled", start=1):
    return [{"round_id": start + i, "belt": belt, "state": state, "entrants": n, "entry_fee": fee}
            for i, n in enumerate(entrants)]


def test_three_significant_figures_half_up_and_never_below_one():
    assert fees.round_fee(1234, 1, None) == 1230
    assert fees.round_fee(1235, 1, None) == 1240          # half up, not banker's
    assert fees.round_fee(12345, 1, None) == 12300
    assert fees.round_fee(999.5, 1, None) == 1000
    assert fees.round_fee(99.4, 1, None) == 99             # below 100 an integer already has three figures
    assert fees.round_fee(0.4, 1, None) == 1


def test_rounding_stays_inside_the_bounds():
    assert fees.round_fee(1236, 100, 1236) == 1230         # nearest would cross the ceiling: round down
    assert fees.round_fee(1234, 1234, None) == 1240        # nearest would cross the floor: round up
    assert fees.round_fee(1235, 1234, 1236) == 1236        # bounds narrower than the grid: the bound itself


def test_f_star_is_the_fee_at_which_the_seed_refunds_the_rake():
    assert fees.f_star(5000, 5, 2000) == 5000
    assert fees.f_star(5000, 4, 2500) == 5000
    assert fees.f_star(5000, 5, 0) is None                 # no rake: no ceiling
    assert fees.f_star(5000, 0, 2000) is None


def test_empty_history_charges_the_start_fee_within_the_bounds():
    d = fees.next_fee([], "white", POLICY, 3, 5000, 2000)
    assert d["fee"] == 1000 and d["occ"] is None and d["rounds"] == [] and d["from_fee"] == 1000
    assert fees.next_fee([], "white", fees.FeePolicy(start=9000), 3, 5000, 2000)["fee"] == 5000   # f* caps it
    assert fees.next_fee([], "white", fees.FeePolicy(start=50, floor=200), 3, 5000, 2000)["fee"] == 200


def test_retargets_from_mean_occupancy_with_the_per_retarget_clamp():
    d = fees.next_fee(rows("white", [10] * 8), "white", POLICY, 3, 5000, 2000)
    assert d["tgt"] == 5 and d["occ"] == 10.0 and d["fee"] == 1410      # 1000 * sqrt(2) = 1414, three figures
    d = fees.next_fee(rows("white", [2] * 8), "white", POLICY, 3, 5000, 2000)
    assert d["fee"] == 667                                                # sqrt(0.4) would give 632: clamped to 1000 / 1.5
    d = fees.next_fee(rows("white", [30] * 8), "white", POLICY, 3, 50000, 2000)
    assert d["fee"] == 1500                                               # clamped to 1000 * 1.5 before any ceiling
    assert fees.next_fee(rows("white", [5] * 8), "white", POLICY, 3, 5000, 2000)["fee"] == 1000   # on target: no move


def test_only_the_window_and_only_that_belt_count():
    old = rows("white", [12] * 20)                                        # long ago the table was full
    recent = rows("white", [5] * 8, start=21)                             # lately it is on target
    d = fees.next_fee(old + recent, "white", POLICY, 3, 5000, 2000)
    assert d["fee"] == 1000 and d["rounds"] == list(range(21, 29))
    noise = rows("yellow", [0] * 8, fee=300, start=100)                   # another belt, another fee
    assert fees.next_fee(old + recent + noise, "white", POLICY, 3, 5000, 2000)["fee"] == 1000
    assert fees.next_fee(noise, "yellow", POLICY, 3, 5000, 2000)["fee"] == 200   # 300 / 1.5


def test_void_rounds_count_with_their_real_entrants_and_open_rounds_do_not():
    r = rows("white", [5] * 7) + rows("white", [1], state="void", start=8)
    d = fees.next_fee(r, "white", POLICY, 3, 5000, 2000)
    assert d["occ"] == 4.5 and d["fee"] == 949                             # 1000 * sqrt(0.9)
    r += rows("white", [20], state="commit", start=9) + rows("white", [20], state="lobby", start=10)
    assert fees.next_fee(r, "white", POLICY, 3, 5000, 2000)["fee"] == 949


def test_ceiling_floor_and_cap():
    full = rows("white", [20] * 8, fee=4000)
    d = fees.next_fee(full, "white", POLICY, 3, 5000, 2000)
    assert d["fee"] == 5000 and d["f_star"] == 5000                        # 4000 * 2 -> 6000 by the clamp -> f*
    assert fees.next_fee(full, "white", POLICY, 3, 5000, 0)["fee"] == 6000   # no rake, no ceiling
    assert fees.next_fee(full, "white", fees.FeePolicy(cap=3000), 3, 5000, 0)["fee"] == 3000
    assert fees.next_fee(full, "white", fees.FeePolicy(cap=3000), 3, 5000, 2000)["fee"] == 3000   # the lower of the two
    empty = rows("white", [0] * 8, fee=200)
    d = fees.next_fee(empty, "white", POLICY, 3, 5000, 2000)
    assert d["fee"] == 133                                                 # 200 / 1.5, above the floor of 100
    assert fees.next_fee(rows("white", [0] * 8, fee=120), "white", POLICY, 3, 5000, 2000)["fee"] == 100
    d = fees.next_fee(full, "white", fees.FeePolicy(floor=6000), 3, 5000, 2000)
    assert d["fee"] == 6000 and d["f_star"] == 5000                        # a floor above f*: the floor wins
    assert fees.next_fee(full, "white", fees.FeePolicy(floor=500, cap=200), 3, 5000, 2000)["fee"] == 500
    per_belt = fees.FeePolicy(floor=100, floors={"blue": 2500})
    assert fees.next_fee(rows("blue", [0] * 8, fee=3000), "blue", per_belt, 3, 5000, 2000)["fee"] == 2500
    assert fees.next_fee(rows("white", [0] * 8, fee=3000), "white", per_belt, 3, 5000, 2000)["fee"] == 2000


def test_the_same_public_rows_give_the_same_fee_in_any_order():
    r = rows("white", [3, 9, 4, 7, 2, 8, 6, 5, 4, 3], fee=1230) + rows("blue", [1, 2], fee=700, start=50)
    want = fees.next_fee(r, "white", POLICY, 3, 5000, 2000)
    shuffled = list(r); random.Random(7).shuffle(shuffled)
    assert fees.next_fee(shuffled, "white", POLICY, 3, 5000, 2000) == want
    assert set(want) >= {"mode", "alpha", "window", "headroom", "clamp", "floor", "start", "cap", "floors",
                         "fee", "from_fee", "occ", "tgt", "f_star", "floor_b", "rounds", "seed_cap", "rake_bps"}


def test_parse_floor():
    assert fees.parse_floor("100") == (100, {})
    assert fees.parse_floor("white=100,blue=500") == (100, {"white": 100, "blue": 500})
    assert fees.parse_floor("250, blue=500") == (250, {"blue": 500})
    assert fees.parse_floor("") == (100, {})
    with pytest.raises(ValueError):
        fees.parse_floor("lots")
