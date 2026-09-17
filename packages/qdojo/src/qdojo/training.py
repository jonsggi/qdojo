"""Fight a round without fighting: the dojo, graded, for nothing.

A newcomer should be able to find out whether their fighter is any good before
they own a seed, hold a single QU, or sign anything. Everything needed is
already published: 118 settled rounds, each with its riddle, the answer the
house revealed, and the tick every rival's answer landed on. So a training
fight runs the player's solver against a real round and reports what would have
happened -- right or wrong, how fast, where that would have placed, and what
the purse would have been.

THE SAFETY GUARANTEE IS STRUCTURAL, NOT A FLAG.

`Bot.step()` sends money from four separate call sites. Threading an
`if training:` through it would put a money-safety property behind a boolean
that every future edit has to remember. This module instead is never given a
chain, a conf, an identity or a seed. It takes a document and a command. There
is nothing here to send *with*, the way a program holding no file handle cannot
write to one. `test_training.py` asserts that shape with `ast`, so it stays
true rather than merely being true today.

It follows that a training fight needs no seed, no QU, no node and no
qubic-cli. Say that loudly wherever this is offered: it is the only claim we
can make that costs the reader nothing.
"""
import dataclasses
import time

from . import belts as B, payload, riddle as R
from .round import Entry, Evaluation, RoundSpec, settle
from .solver import SolverError, run_solver

TICKS_PER_SECOND = 2          # a tick is about half a second (docs/api.md)
SCHEDULE_OFFSET = 20          # ticks ahead a transaction is scheduled (cli.py's default)
SOLVED = ("winner", "solved")
COUNTED = ("winner", "solved", "wrong", "no_reveal", "no_commit", "bad_reveal")
ME = "T" * 60                 # a stand-in identity; nothing is signed with it


@dataclasses.dataclass
class Attempt:
    """One round, fought in the imagination."""
    round_id: int
    belt: str
    title: str
    answer_format: str
    seconds: float                      # wall time the solver took
    answer: str | None = None
    error: str | None = None
    truth: str | None = None
    correct: bool | None = None
    commit_tick: int | None = None      # when the answer would have landed
    solve_ticks: int | None = None      # ...measured from the publish tick
    in_window: bool = True
    rank: int | None = None             # place among correct commits
    rivals: int = 0                     # how many others got it right
    unsolved: bool = False              # nobody solved this round at all
    stake: int = 0
    payout_mode: str = ""
    would_pay: int | None = None        # None = not claimable, never a made-up 0
    net: int | None = None
    why_unpriced: str = ""


# ------------------------------------------------------------------ rebuilding

def spec_from_round(rd: dict) -> RoundSpec:
    """A RoundSpec from a published history round, so the real evaluator can
    re-settle it. Missing fields take their defaults: the export only ever
    grows, and a round published before a rule existed simply lacks it."""
    return RoundSpec(
        round_id=rd["round_id"], publish_tick=rd.get("publish_tick"), entry_fee=rd["entry_fee"],
        commit_window=rd["commit_window"], reveal_window=rd["reveal_window"],
        riddle_hash=b"\x00" * 32, answer_commitment=b"\x00" * 32,
        answer_format=(rd.get("riddle") or {}).get("answer_format", "string"),
        house_seed=rd.get("house_seed", 0), rake_bps=rd.get("rake_bps", 0),
        payout_mode={v: k for k, v in payload.MODE_NAMES.items()}[rd.get("payout_mode", "split")],
        match_bps=rd.get("match_bps", 0), carry_in=rd.get("carry_in", 0),
        lobby_tick=rd.get("lobby_tick"), lobby_window=rd.get("lobby_window", 0),
        min_players=rd.get("min_players", 0),
        belt_rank=B.RANKS.get(rd.get("belt") or "", None),
        bond_bps=rd.get("bond_bps", 0), bond_rounds=rd.get("bond_rounds", 0),
        rake_house_bps=rd.get("rake_house_bps", 10000), rake_dev_bps=rd.get("rake_dev_bps", 0),
        rake_share_bps=rd.get("rake_share_bps", 0), sensei=bool(rd.get("sensei")))


def entries_from_round(rd: dict) -> list[Entry]:
    """Fresh Entry objects every call: settle() rewrites verdicts in place
    (first and podium demote the also-rans to "solved"), so a shared list would
    give a different answer the second time it was graded."""
    return [Entry(identity=e["identity"], commit_tick=e.get("commit_tick"), commit_tx=e.get("commit_tx"),
                  stake=e.get("stake") or 0, enter_tick=e.get("enter_tick"), enter_tx=e.get("enter_tx"),
                  sensei=bool(e.get("sensei")), reveal_tick=e.get("reveal_tick"),
                  reveal_tx=e.get("reveal_tx"), answer=e.get("answer"), verdict=e.get("verdict", "pending"))
            for e in rd.get("entries", [])]


def _settled(spec: RoundSpec, entries: list[Entry]) -> Evaluation:
    ev = Evaluation(round_id=spec.round_id, entries=entries)
    return settle(spec, ev)


def reproduces(rd: dict) -> bool:
    """Does re-settling this round from what was published reproduce the
    payouts the house actually made?

    It is not always yes, and that matters. `house_fighters` -- the identities
    the house funds, whose stakes join the pot but are not matched by the seed
    -- is not in the export, so on an NPC round the matched seed comes out too
    high. When we cannot reproduce the round we did not understand it, and we
    decline to put a number on the purse rather than inventing one. An unknown
    is not a zero.
    """
    doc = rd.get("settlement") or {}
    want = sorted((p["identity"], p["amount"]) for p in doc.get("payouts", []) if p["kind"] == "win")
    if not want:
        return False
    got = sorted((p.identity, p.amount) for p in _settled(spec_from_round(rd), entries_from_round(rd)).payouts
                 if p.kind == "win")
    return got == want


# ---------------------------------------------------------------- the grading

def grade(rd: dict, answer: str | None, seconds: float, error: str = "") -> Attempt:
    """Score one solved (or unsolved) riddle against a settled round."""
    doc = rd.get("settlement") or {}
    rp = rd.get("riddle") or {}
    a = Attempt(round_id=rd["round_id"], belt=rd.get("belt") or "open", title=rd.get("title") or "",
                answer_format=rp.get("answer_format", ""), seconds=round(seconds, 2),
                answer=answer, error=error or None, truth=doc.get("answer"),
                stake=rd.get("entry_fee", 0), payout_mode=rd.get("payout_mode", ""))

    rivals = sorted(e["commit_tick"] for e in rd.get("entries", [])
                    if e.get("verdict") in SOLVED and e.get("commit_tick") and rd.get("publish_tick"))
    a.rivals = len(rivals)
    a.unsolved = not rivals
    if answer is None or a.truth is None:
        a.correct = None if a.truth is None else False
        a.why_unpriced = error or "no answer"
        return a

    a.correct = answer == a.truth
    if rd.get("publish_tick") is not None:
        a.solve_ticks = SCHEDULE_OFFSET + max(1, round(seconds * TICKS_PER_SECOND))
        a.commit_tick = rd["publish_tick"] + a.solve_ticks
        a.in_window = a.solve_ticks <= rd["commit_window"]
    if not a.correct:
        a.would_pay, a.net = 0, -a.stake
        return a
    if not a.in_window:
        a.would_pay, a.net = 0, -a.stake
        a.why_unpriced = "answered after the commit window closed"
        return a
    a.rank = sum(1 for r in rivals if r < a.commit_tick) + 1

    if not reproduces(rd):
        a.why_unpriced = ("the house's seed rules for this round are not fully published, "
                          "so the purse cannot be recomputed")
        return a
    spec = spec_from_round(rd)
    mine = Entry(identity=ME, commit_tick=a.commit_tick, commit_tx="t" * 60, stake=spec.entry_fee,
                 reveal_tick=a.commit_tick + 1, reveal_tx="r" * 60, answer=answer, verdict="winner")
    ev = _settled(spec, entries_from_round(rd) + [mine])
    a.would_pay = sum(p.amount for p in ev.payouts if p.identity == ME and p.kind == "win")
    a.would_pay += sum(b.amount for b in ev.bonds if b.identity == ME)   # the bond is won, just held
    a.net = a.would_pay - a.stake
    return a


# ----------------------------------------------------------------- the fights

def settled_rounds(history: dict) -> list[dict]:
    """Rounds a training fight can be graded against: settled, not void, with
    both the riddle and the answer published."""
    return [r for r in history.get("rounds", [])
            if r.get("riddle") and (r.get("settlement") or {}).get("answer")
            and not (r.get("settlement") or {}).get("void")]


def replay(history: dict, solver_cmd: list[str], *, rounds: int = 10, belt: str = "",
           round_ids=(), timeout: float = 60.0, on_attempt=None):
    """Fight past rounds. No seed, no node, no QU, no qubic-cli.

    Newest first, because a newcomer wants to know how they would do *now*.
    """
    pool = settled_rounds(history)
    if belt:
        pool = [r for r in pool if (r.get("belt") or "open") == belt]
    if round_ids:
        want = set(int(x) for x in round_ids)
        pool = [r for r in pool if r["round_id"] in want]
    else:
        pool = pool[-rounds:] if rounds else pool
    out = []
    for rd in reversed(pool):
        t0 = time.monotonic()
        try:
            answer, err = run_solver(solver_cmd, R.from_public(rd["riddle"]).public(), timeout), ""
        except SolverError as e:
            answer, err = None, str(e)
        a = grade(rd, answer, time.monotonic() - t0, err)
        out.append(a)
        if on_attempt:
            on_attempt(a)
    return out


def scorecard(attempts: list[Attempt]) -> dict:
    """What the whole session says. Every money figure is hypothetical and the
    caller must label it so."""
    done = [a for a in attempts if a.correct is not None]
    right = [a for a in done if a.correct]
    priced = [a for a in right if a.would_pay is not None]
    paid = [a for a in priced if a.would_pay > 0]
    ticks = sorted(a.solve_ticks for a in right if a.solve_ticks is not None)
    by_belt = {}
    for a in done:
        b = by_belt.setdefault(a.belt, {"fought": 0, "solved": 0})
        b["fought"] += 1
        b["solved"] += 1 if a.correct else 0
    return {
        "fought": len(done), "solved": len(right),
        "missed_window": sum(1 for a in right if not a.in_window),
        "median_solve_ticks": ticks[len(ticks) // 2] if ticks else None,
        "best_solve_ticks": ticks[0] if ticks else None,
        "would_have_placed": len(paid),
        "would_have_earned": sum(a.would_pay for a in paid) if paid else 0,
        "would_have_staked": sum(a.stake for a in done),
        "unpriced": len(right) - len(priced),
        "unsolved_taken": sorted(a.round_id for a in right if a.unsolved),
        "by_belt": by_belt,
        "failures": [a.error for a in done if a.error][:5],
    }
