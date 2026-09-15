#!/usr/bin/env python3
"""Regenerate sample-history.json and sample-board.json.

The spectator page loads these when data/history.json and data/board.json are
missing, so the page is watchable with no house running. Every hash is
computed with the real qdojo.hashing module, so the page's VERIFY button
passes on the sample data exactly as it will on a live export.

The story: three rounds in the original flow (stake on COMMIT, fixed seed),
then lobby rounds (seats bought with ENTER before the riddle exists, the house
matching stakes up to a cap), one lobby that never filled (void, refunded),
one round in its reveal window and one table waiting for challengers.

    cd apps/web && uv run python data/make-sample.py
"""
import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "..", "packages", "qdojo", "src"))
from qdojo import hashing  # noqa: E402

rng = random.Random(0x444F)  # "DO" -- deterministic output
RAKE_BPS = 250
WC, WR = 600, 300
WL = 400            # lobby window, ticks
MIN_PLAYERS = 4


def ident() -> str:
    return "".join(rng.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ") for _ in range(60))


def txid() -> str:
    return "".join(rng.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(60))


def salt() -> bytes:
    return bytes(rng.getrandbits(8) for _ in range(16))


HOUSE = ident()

FIGHTERS = {
    # name -> identity, bow tick
    "RYUBOT": (ident(), 26_399_812),
    "KEN.EXE": (ident(), 26_399_901),
    "ZANG-1EF": (ident(), 26_401_450),
    "CHUN-L1": (ident(), 26_403_020),
    "BLANKA.SH": (ident(), 26_405_777),
    "DHAL5IM": (ident(), 26_409_100),
    None: (ident(), None),  # a stranger who never bowed
}
ID = {name: v[0] for name, v in FIGHTERS.items()}

# Each round: riddle, answer, publish tick, and a script of entries:
#   (name, stake, offset_into_commit or None, offset_into_reveal or None, verdict, answer)
# A commit offset of None means the fighter bought a seat and never committed.
# Ticks are relative offsets from the window start so the story stays coherent.
# Lobby rounds set `lobby`: the table opened WL+100 ticks before the publish tick
# (or, for a void/open table, at `lobby_tick`). "winner" entries that were not
# first are demoted to "solved" by build() when payout_mode is "first".
ROUNDS = [
    dict(
        title="WHITE BELT: THE SUM",
        statement="Add every integer in the input. Answer with the total.",
        input="3 14 15 92 65 35",
        answer_format="integer",
        answer="224",
        publish_tick=26_400_100,
        seed=10_000, match_bps=0, belt="white", payout_mode="first",
        entry_fee=1_000,
        entries=[
            ("RYUBOT", 1_000, 41, 12, "winner", "224"),
            ("KEN.EXE", 1_000, 88, 30, "wrong", "225"),
            (None, 1_000, 310, None, "no_reveal", None),
        ],
    ),
    dict(
        title="COUNT THE VOWELS",
        statement="How many vowels (a e i o u) are in the input? Case does not matter.",
        input="The Quick Brown Fox Jumps Over The Lazy Dog",
        answer_format="integer",
        answer="11",
        publish_tick=26_402_000,
        seed=10_000, match_bps=0, belt="white", payout_mode="first",
        entry_fee=1_000,
        entries=[
            ("RYUBOT", 1_000, 25, 9, "winner", "11"),
            ("KEN.EXE", 1_500, 33, 14, "winner", "11"),   # correct but not first: solved, no pay
            ("ZANG-1EF", 1_000, 140, 60, "wrong", "12"),
            (None, 1_000, 402, 220, "wrong", "10"),
        ],
    ),
    dict(
        title="THE PALINDROME",
        statement="Find the longest palindromic substring of the input. Answer with it, exactly.",
        input="qubicracecarxlevelqu",
        answer_format="string",
        answer="racecar",
        publish_tick=26_404_000,
        seed=10_000, match_bps=0, belt="yellow", payout_mode="first",
        entry_fee=1_000,
        entries=[
            ("RYUBOT", 1_000, 60, 20, "wrong", "level"),
            ("KEN.EXE", 1_000, 70, 22, "wrong", "level"),
            ("ZANG-1EF", 1_000, 95, None, "no_reveal", None),
            ("CHUN-L1", 1_000, 120, 45, "wrong", "cracec"),
            (None, 1_000, 500, 290, "wrong", "ece"),
        ],
    ),
    dict(
        title="HEX OF THE BEAST",
        statement="Multiply the two decimal numbers in the input and answer with the product in hexadecimal.",
        input="666 x 1001",
        answer_format="hex",
        answer="a2c1a",
        publish_tick=26_406_000,
        seed=10_000, match_bps=10_000, belt="orange", payout_mode="first", lobby=True,
        entry_fee=2_000,
        entries=[
            ("ZANG-1EF", 2_000, 30, 8, "winner", "a2c1a"),
            ("RYUBOT", 2_000, 44, 15, "wrong", "a2c1b"),
            ("KEN.EXE", 500, None, None, "underpaid", None),   # seat underpaid, refunded
            ("CHUN-L1", 2_000, 71, None, "no_reveal", None),
            ("DHAL5IM", 2_000, None, None, "no_commit", None),  # bought a seat, never fought
            ("BLANKA.SH", 2_000, None, None, "late", None),     # entered after the lobby closed, refunded
        ],
    ),
    dict(
        title="FIBONACCI GATE",
        statement="The input is an index n. Answer with the n-th Fibonacci number, F(0)=0, F(1)=1.",
        input="40",
        answer_format="integer",
        answer="102334155",
        publish_tick=26_408_000,
        seed=10_000, match_bps=5_000, belt="green", payout_mode="split", lobby=True,
        entry_fee=1_000,
        entries=[
            ("RYUBOT", 1_000, 18, 5, "winner", "102334155"),
            ("KEN.EXE", 1_000, 21, 7, "winner", "102334155"),
            ("CHUN-L1", 1_000, 39, 11, "winner", "102334155"),
            ("ZANG-1EF", 1_000, 55, 40, "wrong", "165580141"),
            ("BLANKA.SH", 1_000, 210, 90, "wrong", "63245986"),
            (None, 1_000, 580, None, "no_reveal", None),
        ],
    ),
    dict(
        title="REVERSE THE WORD",
        statement="Reverse the input string. Answer with the result, exactly.",
        input="klabautermann",
        answer_format="string",
        answer="nnamretuabalk",
        publish_tick=26_410_000,
        seed=10_000, match_bps=10_000, belt="yellow", payout_mode="first", lobby=True,
        entry_fee=1_000,
        entries=[
            ("CHUN-L1", 1_000, 12, 4, "winner", "nnamretuabalk"),
            ("KEN.EXE", 1_000, 27, 19, "bad_reveal", None),  # reveal did not match its commitment
            ("KEN.EXE", 1_000, 90, None, "duplicate", None),  # struck twice
            ("DHAL5IM", 1_000, 150, 88, "wrong", "nnamretuabalK"),
        ],
    ),
    dict(
        title="PRIME ORDINAL",
        statement="Answer with the 100th prime number.",
        input="100",
        answer_format="integer",
        answer="541",
        publish_tick=26_412_000,
        seed=10_000, match_bps=10_000, belt="blue", payout_mode="first", lobby=True,
        entry_fee=1_000,
        entries=[
            ("KEN.EXE", 1_000, 9, 3, "winner", "541"),
            ("RYUBOT", 1_000, 11, 6, "winner", "541"),      # solved, not first
            ("DHAL5IM", 1_000, 30, 25, "wrong", "547"),
            ("BLANKA.SH", 1_000, 77, None, "no_reveal", None),
        ],
    ),
    dict(
        # a table that never filled: two of four seats, void, every seat refunded
        title="BLUE BELT: AT THE TABLE",
        lobby_tick=26_413_000,
        seed=10_000, match_bps=10_000, belt="blue", payout_mode="first", lobby=True, void=True,
        entry_fee=1_000,
        entries=[
            ("RYUBOT", 1_000, None, None, "void", None),
            ("DHAL5IM", 1_000, None, None, "void", None),
        ],
    ),
    dict(
        # currently in the reveal window
        title="THE CHECKSUM",
        statement="XOR every byte of the ASCII input together. Answer with the result in hexadecimal.",
        input="DOJO",
        answer_format="hex",
        answer="4",  # kept secret; only the commitment is published
        publish_tick=26_414_000,
        seed=10_000, match_bps=10_000, belt="orange", payout_mode="first", lobby=True,
        entry_fee=1_000,
        open=True,
        entries=[
            ("RYUBOT", 1_000, 14, 6, "pending", None),
            ("KEN.EXE", 1_000, 19, None, "pending", None),
            ("ZANG-1EF", 1_000, 33, 21, "pending", None),
            ("CHUN-L1", 1_000, 61, None, "pending", None),
            ("DHAL5IM", 1_000, 240, 70, "pending", None),
            ("BLANKA.SH", 1_000, 455, None, "pending", None),
        ],
    ),
    dict(
        # the next table, open: two of four seats bought, riddle still sealed
        title="GREEN BELT: AT THE TABLE",
        lobby_tick=26_414_000 + WC + 50,
        seed=10_000, match_bps=10_000, belt="green", payout_mode="first", lobby=True,
        entry_fee=1_500,
        open=True,
        entries=[
            ("KEN.EXE", 1_500, None, None, "pending", None),
            ("ZANG-1EF", 1_500, None, None, "pending", None),
        ],
    ),
]

NOW_TICK = 26_414_000 + WC + 110  # 190 ticks left in round 9's reveal window, 340 in round 10's lobby
GENERATED_AT = "2026-09-15T21:04:11Z"

# Verdicts whose stake stays in the pot (docs/spec.md §5). "void" is refunded.
COUNTED = ("winner", "solved", "wrong", "no_reveal", "no_commit", "bad_reveal", "pending")
PLAYED = COUNTED  # what the house counts as a round played


def seed_for(spec, carry_in: int, stakes: int) -> int:
    cap, bps = spec["seed"], spec["match_bps"]
    matched = min(cap, stakes * bps // 10000) if bps else cap
    return carry_in + matched


def build():
    rounds = []
    carry = 0
    stats = {name: dict(rounds_played=0, wins=0, earned=0, strikes=0) for name in FIGHTERS}
    for i, spec in enumerate(ROUNDS, start=1):
        is_open = spec.get("open", False)
        is_void = spec.get("void", False)
        lobby = spec.get("lobby", False)
        published = not is_void and "publish_tick" in spec
        P = spec.get("publish_tick")
        L = spec.get("lobby_tick", (P - WL - 100) if (lobby and P is not None) else None)
        carry_in = carry
        carry = 0

        public = canon = dojo_salt = None
        if published:
            public = dict(round_id=i, title=spec["title"], statement=spec["statement"],
                          input=spec["input"], answer_format=spec["answer_format"])
            canon = hashing.canonical_answer(spec["answer"], spec["answer_format"])
            dojo_salt = salt()

        if is_void:
            state = "void"
        elif not published:
            state = "lobby"
        elif is_open:
            state = "reveal"
        else:
            state = "settled"

        r = dict(
            round_id=i, title=spec["title"], state=state,
            publish_tick=P if published else None, publish_tx=txid() if published else None,
            lobby_tick=L, lobby_window=WL if lobby else 0,
            min_players=MIN_PLAYERS if lobby else 0, belt=spec.get("belt", ""),
            entrants=0,
            commit_window=WC, reveal_window=WR,
            entry_fee=spec["entry_fee"], house_seed=spec["seed"], rake_bps=RAKE_BPS,
            payout_mode=spec.get("payout_mode", "first"), match_bps=spec["match_bps"], carry_in=carry_in,
            riddle_hash=hashing.riddle_hash(public).hex() if published else None,
            answer_commitment=hashing.answer_commitment(i, dojo_salt, canon).hex() if published else None,
            riddle=public, entries=[], settlement=None,
        )

        # entries: a seat (ENTER) in lobby rounds, then COMMIT / REVEAL where they happened
        enter_off = 3
        for name, stake, c_off, r_off, verdict, answer in spec["entries"]:
            enter_off += rng.randint(4, 40)
            if lobby:
                e_off = (WL + 5) if verdict == "late" else min(enter_off, WL - 1)
                enter_tick, enter_tx = L + e_off, txid()
            else:
                enter_tick = enter_tx = None
            committed = c_off is not None and P is not None
            e = dict(
                identity=ID[name], name=name,
                commit_tick=(P + c_off) if committed else None, commit_tx=txid() if committed else None,
                stake=stake,
                reveal_tick=(P + WC + r_off) if (committed and r_off is not None) else None,
                reveal_tx=txid() if (committed and r_off is not None) else None,
                verdict=verdict,
                enter_tick=enter_tick, enter_tx=enter_tx,
                answer=answer if not is_open else None,
            )
            r["entries"].append(e)
            if verdict in ("duplicate", "bad_reveal"):
                stats[name]["strikes"] += 1
            if verdict in PLAYED:
                stats[name]["rounds_played"] += 1
        r["entrants"] = len([e for e in r["entries"] if e["verdict"] not in ("late", "underpaid")])

        if is_void:
            # the lobby never filled: nothing but refunds moved; the carry rolls on
            payouts = []
            for e in r["entries"]:
                payouts.append(dict(identity=e["identity"], amount=e["stake"], kind="refund",
                                    tx=txid(), tick=L + WL + 40 + len(payouts) * 3, confirmed=True))
            settlement = dict(void=True, pot=0, rake=0, carry=carry_in, answer=None, dojo_salt=None,
                              winners=[], payouts=payouts, settle_tx=txid())
            settlement["hash"] = hashing.settlement_hash(settlement).hex()
            r["settlement"] = settlement
            carry = carry_in
        elif not is_open and published:
            # first-wins: later correct reveals are "solved", correct but unpaid
            if r["payout_mode"] == "first":
                winners = sorted((e for e in r["entries"] if e["verdict"] == "winner"),
                                 key=lambda e: (e["commit_tick"], e["commit_tx"]))
                for e in winners[1:]:
                    if e["commit_tick"] != winners[0]["commit_tick"]:
                        e["verdict"] = "solved"
            counted = [e for e in r["entries"] if e["verdict"] in COUNTED]
            stakes = sum(e["stake"] for e in counted)
            seed_used = seed_for(spec, carry_in, stakes)
            pot = seed_used + stakes
            rake = stakes * RAKE_BPS // 10000
            winners = [e for e in r["entries"] if e["verdict"] == "winner"]
            payouts = []
            if winners:
                each = (pot - rake) // len(winners)
                carry = (pot - rake) - each * len(winners)
                for e in winners:
                    payouts.append(dict(identity=e["identity"], amount=each, kind="win",
                                        tx=txid(), tick=P + WC + WR + 40 + len(payouts) * 3, confirmed=True))
                    stats[e["name"]]["wins"] += 1
                    stats[e["name"]]["earned"] += each
            else:
                carry = pot - rake
            for e in r["entries"]:
                if e["verdict"] in ("underpaid", "late"):
                    payouts.append(dict(identity=e["identity"], amount=e["stake"], kind="refund",
                                        tx=txid(), tick=P + WC + WR + 40 + len(payouts) * 3, confirmed=True))
            settlement = dict(
                pot=pot, seed_used=seed_used, rake=rake, carry=carry, answer=canon, dojo_salt=dojo_salt.hex(),
                winners=[e["identity"] for e in winners], payouts=payouts,
                settle_tx=txid(),
            )
            settlement["hash"] = hashing.settlement_hash(settlement).hex()
            r["settlement"] = settlement
        else:
            carry = carry_in  # still open: the carry is riding in this round
        rounds.append(r)

    fighters = []
    for name, (identity, bow) in FIGHTERS.items():
        fighters.append(dict(identity=identity, name=name, bow_tick=bow, **stats[name]))

    history = dict(house=HOUSE, generated_at=GENERATED_AT, generated_tick=NOW_TICK,
                   rounds=rounds, fighters=fighters)
    board = dict(house=HOUSE, generated_tick=NOW_TICK,
                 rounds=[{k: v for k, v in r.items() if k != "entries"}
                         for r in rounds if r["state"] in ("lobby", "commit", "reveal")])
    return history, board


if __name__ == "__main__":
    history, board = build()
    with open(os.path.join(HERE, "sample-history.json"), "w", encoding="utf-8") as f:
        json.dump(history, f, indent=1, ensure_ascii=False)
        f.write("\n")
    with open(os.path.join(HERE, "sample-board.json"), "w", encoding="utf-8") as f:
        json.dump(board, f, indent=1, ensure_ascii=False)
        f.write("\n")
    print(f"wrote {len(history['rounds'])} rounds, {len(history['fighters'])} fighters, "
          f"open: {[(r['round_id'], r['state']) for r in board['rounds']]}, "
          f"void: {[r['round_id'] for r in history['rounds'] if r['state'] == 'void']}")
