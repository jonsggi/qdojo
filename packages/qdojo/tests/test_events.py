import json
import os

import pytest

from qdojo import events, payload
from qdojo.round import Observed

from conftest import ALICE, BOB, HOUSE

# A real 151-byte PUBLISH from round 2, before bond_bps/bond_rounds/sensei
# existed. payload.try_decode() returns None for it and always will.
LEGACY_PUBLISH = bytes.fromhex(
    "444f4a4f000202000000e8030000000000002c01780001263bd33209ded232d50a204b8864b2ac"
    "7fe222dec7dee325409df854b9137ec312e025717a83802cb3e6023c0b3212b73371905ee358fe"
    "42e00eb649ddc62b033f68747470733a2f2f6b6c616261757465726d616e6e2e7461696c623462"
    "64302e74732e6e65742f71646f6a6f2f646174612f726f756e64732f322e6a736f6e")

META_2 = {"round_id": 2, "entry_fee": 1000, "commit_window": 300, "reveal_window": 120,
          "payout_mode": "first", "house_seed": 5000, "riddle_hash": "ab" * 32,
          "answer_commitment": "cd" * 32, "publish_tick": 100, "publish_tx": "legacytx",
          "uri": "https://example/2.json"}


def ev(**kw):
    base = {"tick": 1, "tx": "t", "dir": "in", "from": ALICE, "to": HOUSE, "identity": ALICE,
            "amount": 0, "kind": "BOW", "round_id": None, "fields": {}, "decoded": True, "source": "payload"}
    return base | kw


# ------------------------------------------------------------------ describe

ALL_KINDS = [
    ev(kind="BOW", fields={"name": "RYUBOT"}),
    ev(kind="LOBBY", round_id=7, fields={"round_id": 7, "entry_fee": 1000, "min_players": 3, "lobby_window": 240,
                                         "payout_mode": 2, "payout_mode_name": "podium", "seed_cap": 5000,
                                         "match_bps": 10000, "bond_bps": 5000, "bond_rounds": 3, "sensei": 1,
                                         "belt": "orange"}),
    ev(kind="PUBLISH", round_id=7, title="Orange belt: the sum",
       fields={"round_id": 7, "commit_window": 300, "reveal_window": 120,
               "riddle_hash": "ab" * 32, "answer_commitment": "cd" * 32}),
    ev(kind="ENTER", round_id=7, amount=1000, fields={"round_id": 7}),
    ev(kind="COMMIT", round_id=7, fields={"round_id": 7, "commitment": "ef" * 32}),
    ev(kind="REVEAL", round_id=7, verdict="winner", fields={"round_id": 7, "answer": "142"}),
    ev(kind="SETTLE", round_id=7, fields={"round_id": 7, "dojo_salt": "11" * 16,
                                          "settlement_hash": "22" * 32, "uri": "https://example/7.json"}),
    ev(kind=events.KIND_PAYOUT, round_id=7, amount=3700, dir="out", fields={"payout_kind": "win"}),
    ev(kind=events.KIND_PAYOUT, round_id=7, amount=1000, dir="out", fields={"payout_kind": "refund"}),
    ev(kind=events.KIND_PAYOUT, round_id=4, amount=500, dir="out", fields={"payout_kind": "bond_release"}),
    ev(kind=events.KIND_PAYOUT, round_id=7, amount=140, dir="out", fields={"payout_kind": "rake_dev"}),
    ev(kind=events.KIND_OTHER, amount=99),
    ev(kind=events.KIND_UNKNOWN),
]


@pytest.mark.parametrize("e", ALL_KINDS, ids=lambda e: f"{e['kind']}-{e['fields'].get('payout_kind', '')}")
def test_describe_covers_every_kind(e):
    t = events.describe(e)
    assert t and t.endswith(".")
    assert "{" not in t and "}" not in t   # an unformatted template is the likeliest bug here


@pytest.mark.parametrize("bps,want", [(10000, "matching 1:1"), (5000, "matching 1:2"), (0, "a fixed amount")])
def test_lobby_match_wording(bps, want):
    e = ev(kind="LOBBY", round_id=1, fields={"entry_fee": 1000, "seed_cap": 5000, "match_bps": bps})
    assert want in events.describe(e)


def test_lobby_bond_and_sensei_are_optional():
    plain = events.describe(ev(kind="LOBBY", round_id=1, fields={"entry_fee": 1000}))
    assert "bond" not in plain and "sensei" not in plain
    rich = events.describe(ev(kind="LOBBY", round_id=1,
                              fields={"entry_fee": 1000, "bond_bps": 5000, "bond_rounds": 3, "sensei": 1}))
    assert "50% of any win is held back" in rich and "senseis" in rich


def test_publish_title_fallback():
    f = {"round_id": 7, "commit_window": 300, "reveal_window": 120}
    assert "“Orange belt: the sum”" in events.describe(
        ev(kind="PUBLISH", round_id=7, title="Orange belt: the sum", fields=f))
    assert "published the riddle for round 7" in events.describe(ev(kind="PUBLISH", round_id=7, fields=f))


def test_publish_repeats_the_terms_only_when_there_was_no_lobby():
    f = {"round_id": 7, "entry_fee": 1000, "commit_window": 300}
    assert "A seat costs" in events.describe(ev(kind="PUBLISH", round_id=7, fields=f, had_lobby=False))
    assert "A seat costs" not in events.describe(ev(kind="PUBLISH", round_id=7, fields=f, had_lobby=True))


@pytest.mark.parametrize("verdict,want", [("outranked", "may not sit below its own belt"),
                                          ("late", "after the table had closed"),
                                          ("underpaid", "short of the seat price"),
                                          ("pending", None)])
def test_enter_verdict_suffixes(verdict, want):
    t = events.describe(ev(kind="ENTER", round_id=7, amount=1000, verdict=verdict, fields={}))
    assert (want in t) if want else t.endswith("for 1,000 QU.")


def test_commit_stake_phrase_only_when_the_stake_rode_on_the_commit():
    f = {"commitment": "ef" * 32}
    assert "staked" not in events.describe(ev(kind="COMMIT", round_id=7, amount=0, fields=f))
    assert "staked 1,000 QU" in events.describe(ev(kind="COMMIT", round_id=7, amount=1000, fields=f))


def test_reveal_truncates_a_long_answer():
    t = events.describe(ev(kind="REVEAL", round_id=7, fields={"answer": "x" * 512}))
    assert len(t) < 200 and "…" in t


def test_who_falls_back_to_a_short_identity():
    assert events.describe(ev(kind="ENTER", round_id=1, amount=10, fields={}))[:6] == ALICE[:6]
    assert events.describe(ev(kind="ENTER", round_id=1, amount=10, name="RYUBOT", fields={})).startswith("RYUBOT")


# -------------------------------------------------------------------- fields

def test_fields_are_json_safe():
    m = payload.Publish(1, 1000, 300, 120, b"\x01" * 32, b"\x02" * 32, "u", payload.MODE_PODIUM, 5000, 10000)
    f = events.fields_of(m)
    assert f["riddle_hash"] == "01" * 32 and f["payout_mode_name"] == "podium"
    assert "kind" not in f                 # kind is a class attribute, never a field
    json.dumps(f)


# --------------------------------------------------------------------- build

def obs(tick, tx, raw, source=ALICE, amount=0, it=payload.INPUT_TYPE):
    return Observed(tick=tick, tx_id=tx, source=source, dest=HOUSE, amount=amount, input_type=it, payload=raw)


def test_legacy_frame_gets_a_round_and_a_sentence():
    idx = {"legacytx": {"round_id": 2, "kind": "PUBLISH"}}
    recs = events.build([obs(100, "legacytx", LEGACY_PUBLISH)], HOUSE, idx, metas={2: META_2},
                        riddles={2: {"title": "White belt: the sum"}})
    assert payload.try_decode(LEGACY_PUBLISH) is None    # the premise of this test
    (r,) = recs
    assert r["decoded"] is False and r["source"] == "index" and r["round_id"] == 2
    assert "round 2" in r["text"] and "White belt: the sum" in r["text"]
    assert r["payload"] == LEGACY_PUBLISH.hex()          # the raw bytes are still published


def test_legacy_frame_with_no_index_hit_is_unresolved_but_still_readable():
    (r,) = events.build([obs(100, "legacytx", LEGACY_PUBLISH)], HOUSE)
    assert r["kind"] == events.KIND_UNKNOWN and r["text"] and r["round_id"] is None


def test_payouts_become_outbound_events():
    recs = events.build([], HOUSE, payouts=[{"tick": 9, "tx": "p1", "identity": BOB, "amount": 3700,
                                             "kind": "win", "confirmed": True, "round_id": 7}],
                        names={BOB: "RYUBOT"})
    (r,) = recs
    assert r["dir"] == "out" and r["from"] == HOUSE and r["to"] == BOB
    assert r["text"] == "The house paid 3,700 QU to RYUBOT for winning round 7."


def test_a_payout_with_no_tick_is_dropped():
    assert events.build([], HOUSE, payouts=[{"tick": None, "tx": "p", "identity": BOB, "amount": 1,
                                             "kind": "win", "round_id": 7}]) == []


@pytest.mark.parametrize("mode,n_records,n_foreign", [("count", 0, 1), ("list", 1, 0), ("drop", 0, 0)])
def test_foreign_traffic(mode, n_records, n_foreign):
    recs = events.build([obs(5, "f1", b"junk", amount=77, it=0)], HOUSE, foreign=mode)
    shards = events.bucketize(recs)
    tick = shards[0]["ticks"][0] if shards else {"events": [], "foreign": {"count": 0, "amount": 0}}
    assert len(tick["events"]) == n_records
    assert tick["foreign"]["count"] == n_foreign
    assert tick["foreign"]["amount"] == (77 if n_foreign else 0)


def test_events_to_another_identity_are_not_ours():
    o = Observed(tick=1, tx_id="x", source=ALICE, dest=BOB, amount=1, input_type=0, payload=b"")
    assert events.build([o], HOUSE) == []


# ---------------------------------------------------------- shards and index

def test_bucketize_and_index():
    raw = payload.encode(payload.Bow("RYUBOT"))
    recs = events.build([obs(999, "a", raw), obs(1000, "b", raw), obs(1000, "c", raw)], HOUSE)
    shards = events.bucketize(recs)
    assert sorted(shards) == [0, 1]
    assert shards[1]["ticks"][0]["tick"] == 1000 and len(shards[1]["ticks"][0]["events"]) == 2
    assert shards[0]["first_tick"] == shards[0]["last_tick"] == 999
    ix = events.index_doc(shards, 2000)
    assert ix["ticks"] == [999, 1000] and ix["counts"]["BOW"] == 3 and ix["unresolved"] == 0
    assert [b["bucket"] for b in ix["buckets"]] == [0, 1]


def test_every_tick_gets_a_summary():
    raw = payload.encode(payload.Commit(7, b"\x00" * 32))
    shards = events.bucketize(events.build([obs(1, "a", raw), obs(1, "b", raw)], HOUSE))
    assert shards[0]["ticks"][0]["summary"] == "2 commits."


# ------------------------------------------------------ against the real log

REAL = os.path.join(os.path.dirname(__file__), "..", "..", "..", "private", "house")


@pytest.mark.skipif(not os.path.exists(os.path.join(REAL, "observed.jsonl")), reason="no live house data here")
def test_real_log_every_event_gets_text_and_a_round():
    """The regression that matters: 131 frames on the live chain no longer
    decode, and every one of them must still reach a reader as a sentence."""
    from qdojo.house import House
    import glob
    doc = json.load(open(sorted(glob.glob(os.path.join(REAL, "rounds", "*", "settlement.json")))[-1]))
    h = House(object(), REAL, doc["house"])
    metas = {r: json.load(open(h._rpath(r, "meta.json"))) for r in h.round_ids()}
    riddles = {}
    for r in h.round_ids():
        try:
            riddles[r] = json.load(open(h._rpath(r, "riddle.json")))
        except FileNotFoundError:
            riddles[r] = {}
    recs = events.build(h.observed(), h.identity, h.tx_index(), h.payout_events(),
                        {i: b["name"] for i, b in h.bows().items()}, metas, riddles)
    real = [r for r in recs if not r.get("foreign_only")]
    assert len(real) > 3000
    assert all(r["text"] for r in real)
    assert all("{" not in r["text"] for r in real)
    # BOW, a signed document and foreign traffic belong to no round; everything
    # else must name one.
    roundless = ("BOW", "DOC", events.KIND_OTHER, events.KIND_UNKNOWN)
    assert not [r for r in real if r["kind"] not in roundless and r["round_id"] is None]
    assert [r for r in real if r["source"] == "index"], "the legacy path is not being exercised"
    assert events.index_doc(events.bucketize(recs), 0)["unresolved"] == 0
