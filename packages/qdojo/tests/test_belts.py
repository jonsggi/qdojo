from qdojo import belts as B


def ent(identity, verdict):
    return {"identity": identity, "verdict": verdict}


A, C = "A" * 60, "C" * 60


def test_everyone_starts_white_and_may_enter_anything():
    st = {}
    assert B.rank_of(st, A) == 0 and B.may_enter(st, A, 0) and B.may_enter(st, A, 4)


def test_three_wins_at_own_belt_promote_and_lock_out_the_easy_table():
    st = {}
    B.apply_settlement(st, 0, [ent(A, "winner")])
    assert st[A] == {"rank": 0, "points": 2}
    ch = B.apply_settlement(st, 0, [ent(A, "winner")])
    assert st[A] == {"rank": 1, "points": 0} and ch[0].reason == "promoted"
    assert not B.may_enter(st, A, 0) and B.may_enter(st, A, 1)


def test_failures_at_own_belt_demote_but_never_below_white():
    st = {A: {"rank": 1, "points": 0}}
    for _ in range(3):
        B.apply_settlement(st, 1, [ent(A, "wrong")])
    assert st[A] == {"rank": 0, "points": 0}
    for _ in range(5):
        B.apply_settlement(st, 0, [ent(A, "no_reveal")])
    assert st[A]["rank"] == 0 and st[A]["points"] == B.DEMOTE_AT


def test_winning_above_your_belt_jumps_you_there_and_failing_above_is_free():
    st = {}
    ch = B.apply_settlement(st, 3, [ent(A, "wrong"), ent(C, "winner")])
    assert st[A] == {"rank": 0, "points": 0}
    assert st[C] == {"rank": 3, "points": 0} and ch[0].reason == "won above belt"
    B.apply_settlement(st, 4, [ent(A, "solved")])
    assert st[A]["points"] == 1


def test_top_belt_holds():
    st = {A: {"rank": 4, "points": 2}}
    assert B.apply_settlement(st, 4, [ent(A, "winner")]) == []
    assert st[A] == {"rank": 4, "points": 3}


def test_non_fights_do_not_move_points():
    st = {}
    B.apply_settlement(st, 0, [ent(A, "late"), ent(A, "outranked"), ent(A, "void")])
    assert st.get(A, {"rank": 0, "points": 0})["points"] == 0


def test_public_view():
    assert B.public({A: {"rank": 2, "points": -1}}) == {A: {"rank": 2, "belt": "orange", "points": -1}}
