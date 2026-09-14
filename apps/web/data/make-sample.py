#!/usr/bin/env python3
"""Regenerate sample-history.json and sample-board.json.

The spectator page loads these when data/history.json and data/board.json are
missing, so the page is watchable with no house running. Every hash is
computed with the real qdojo.hashing module, so the page's VERIFY button
passes on the sample data exactly as it will on a live export.

    python3 apps/web/data/make-sample.py
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
#   (name, stake, offset_into_commit, offset_into_reveal or None, verdict, answer)
# Ticks are relative offsets from the window start so the story stays coherent.
ROUNDS = [
    dict(
        title="WHITE BELT: THE SUM",
        statement="Add every integer in the input. Answer with the total.",
        input="3 14 15 92 65 35",
        answer_format="integer",
        answer="224",
        publish_tick=26_400_100,
        seed=10_000,
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
        seed=10_000,
        entry_fee=1_000,
        entries=[
            ("RYUBOT", 1_000, 25, 9, "winner", "11"),
            ("KEN.EXE", 1_500, 33, 14, "winner", "11"),
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
        seed=10_000,
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
        seed=10_000,
        entry_fee=2_000,
        entries=[
            ("ZANG-1EF", 2_000, 30, 8, "winner", "a2c1a"),
            ("RYUBOT", 2_000, 44, 15, "wrong", "a2c1b"),
            ("KEN.EXE", 500, 52, 16, "underpaid", "a2c1a"),  # refunded
            ("CHUN-L1", 2_000, 71, None, "no_reveal", None),
            ("BLANKA.SH", 2_000, 640, None, "late", None),  # committed after the bell, refunded
        ],
    ),
    dict(
        title="FIBONACCI GATE",
        statement="The input is an index n. Answer with the n-th Fibonacci number, F(0)=0, F(1)=1.",
        input="40",
        answer_format="integer",
        answer="102334155",
        publish_tick=26_408_000,
        seed=10_000,
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
        seed=10_000,
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
        seed=10_000,
        entry_fee=1_000,
        entries=[
            ("KEN.EXE", 1_000, 9, 3, "winner", "541"),
            ("RYUBOT", 1_000, 11, 6, "winner", "541"),
            ("DHAL5IM", 1_000, 30, 25, "wrong", "547"),
            ("BLANKA.SH", 1_000, 77, None, "no_reveal", None),
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
        seed=10_000,
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
]

NOW_TICK = 26_414_000 + WC + 110  # 190 ticks left in round 8's reveal window
GENERATED_AT = "2026-09-14T21:04:11Z"


def build():
    rounds = []
    carry = 0
    stats = {name: dict(rounds_played=0, wins=0, earned=0, strikes=0) for name in FIGHTERS}
    for i, spec in enumerate(ROUNDS, start=1):
        public = dict(round_id=i, title=spec["title"], statement=spec["statement"],
                      input=spec["input"], answer_format=spec["answer_format"])
        canon = hashing.canonical_answer(spec["answer"], spec["answer_format"])
        dojo_salt = salt()
        house_seed = spec["seed"] + carry
        carry = 0
        P = spec["publish_tick"]
        is_open = spec.get("open", False)
        r = dict(
            round_id=i, title=spec["title"],
            state="reveal" if is_open else "settled",
            publish_tick=P, publish_tx=txid(),
            commit_window=WC, reveal_window=WR,
            entry_fee=spec["entry_fee"], house_seed=house_seed,
            riddle_hash=hashing.riddle_hash(public).hex(),
            answer_commitment=hashing.answer_commitment(i, dojo_salt, canon).hex(),
            riddle=public, entries=[], settlement=None,
        )
        played = set()
        for name, stake, c_off, r_off, verdict, answer in spec["entries"]:
            e = dict(
                identity=ID[name], name=name,
                commit_tick=P + c_off, commit_tx=txid(), stake=stake,
                reveal_tick=(P + WC + r_off) if r_off is not None else None,
                reveal_tx=txid() if r_off is not None else None,
                verdict=verdict,
                answer=answer if not is_open else None,
            )
            r["entries"].append(e)
            if verdict in ("duplicate", "bad_reveal"):
                stats[name]["strikes"] += 1
            if verdict not in ("duplicate", "late", "underpaid"):
                played.add(name)
        for name in played:
            stats[name]["rounds_played"] += 1

        if not is_open:
            counted = [e for e in r["entries"] if e["verdict"] in ("winner", "wrong", "no_reveal", "bad_reveal")]
            stakes = sum(e["stake"] for e in counted)
            pot = house_seed + stakes
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
                pot=pot, rake=rake, carry=carry, answer=canon, dojo_salt=dojo_salt.hex(),
                winners=[e["identity"] for e in winners], payouts=payouts,
                settle_tx=txid(),
            )
            settlement["hash"] = hashing.settlement_hash(settlement).hex()
            r["settlement"] = settlement
        rounds.append(r)

    fighters = []
    for name, (identity, bow) in FIGHTERS.items():
        fighters.append(dict(identity=identity, name=name, bow_tick=bow, **stats[name]))

    history = dict(house=HOUSE, generated_at=GENERATED_AT, generated_tick=NOW_TICK,
                   rounds=rounds, fighters=fighters)
    board = dict(house=HOUSE, generated_tick=NOW_TICK,
                 rounds=[{k: v for k, v in r.items() if k not in ("entries", "settlement")}
                         for r in rounds if r["state"] in ("commit", "reveal")])
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
          f"open: {[r['round_id'] for r in board['rounds']]}")
