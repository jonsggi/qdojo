"""Every dojo message, in English, for the tick pages on the spectator site.

A block explorer shows a spectator 166 bytes of hex. This module turns the
same bytes into one sentence: who did what, in which round, for how much.
That is the whole point -- the page explains, the explorer proves.

Two things make this harder than decoding the wire, and both are handled here:

  * 131 PUBLISH/LOBBY frames from rounds 1-69 predate the bond_bps/bond_rounds/
    sensei fields and no longer decode. There are at least five historical
    header layouts and 56 of the 69 PUBLISH frames are ambiguous by length
    alone, so a speculative legacy decoder would GUESS. We never guess bytes we
    still hold the authoritative record for: the tx is looked up in an index
    built from the round dirs, and `fields` comes from meta.json. The sentence
    is identical; only `source` says where it came from.
  * Payouts are outbound and so are absent from observed.jsonl, which only ever
    holds what arrived. They come from each settlement's payouts[].

Pure: no I/O, no House, no chain. `describe()` takes ONE already-merged record
so it is a table-driven unit test with no fixtures.
"""
from . import payload

# Context describe() needed but the page already has from history.json. Kept out
# of the shards: ~4,000 events is 1.2 KB each before this, 0.6 KB after.
_SCAFFOLD = ("foreign_only", "title", "belt", "had_lobby", "entry_fee", "identity")

BUCKET = 1000                 # ticks per exported shard; ~8 minutes of chain
KIND_PAYOUT = "PAYOUT"        # outbound, from the settlement ledger
KIND_OTHER = "OTHER"          # reached the house carrying no dojo message
KIND_UNKNOWN = "UNKNOWN"      # has our magic, does not decode, and no index hit

_VERDICT_SUFFIX = {
    "outranked": " The seat was refused -- a fighter may not sit below its own belt -- and the stake was refunded.",
    "late": " It arrived after the table had closed and was refunded.",
    "underpaid": " It was short of the seat price and was refunded.",
}
_REVEAL_SUFFIX = {
    "winner": " That was right, and first.",
    "solved": " That was right.",
    "wrong": " That was wrong.",
    "bad_reveal": " It did not match what it had committed, so it does not count.",
}
_PAYOUT_VERB = {
    "win": "paid", "refund": "refunded", "bond_release": "released", "rake_dev": "paid",
}


# ------------------------------------------------------------------ helpers

def fields_of(m) -> dict:
    """A decoded message as JSON-safe fields. `kind` is a CLASS attribute on
    every payload dataclass, so vars() omits it -- it is a top-level record key,
    never a field. cli.py's `payload decode` prints exactly this projection."""
    d = {k: (v.hex() if isinstance(v, bytes) else v) for k, v in vars(m).items()}
    if "payout_mode" in d:
        d["payout_mode_name"] = payload.MODE_NAMES.get(d["payout_mode"], str(d["payout_mode"]))
    return d


def ticks_to_human(t: int) -> str:
    """Mirror of the page's ticksToHuman: a tick is about half a second."""
    s = max(0, round((t or 0) / 2))
    if s < 90:
        return f"{s}s"
    m, r = divmod(s, 60)
    return f"{m}m{r:02d}s" if r else f"{m}m"


def qu(n) -> str:
    return "unknown" if n is None else f"{int(n):,} QU"


def short(h, n=8) -> str:
    h = h or ""
    return f"{h[:n]}…" if len(h) > n else (h or "—")


def who(ev) -> str:
    return ev.get("name") or short(ev.get("identity") or ev.get("from") or "", 6)


def mode_phrase(mode) -> str:
    name = mode if isinstance(mode, str) else payload.MODE_NAMES.get(mode, "")
    return {"split": "split evenly between everyone who solved it",
            "first": "to the first correct commit",
            "podium": "5:3:2 to the first three correct commits"}.get(name, "as the house published it")


def match_phrase(seed_cap, match_bps) -> str:
    """0 bps is a flat seed; otherwise it is a ratio against what fighters stake."""
    if not match_bps:
        return ", a fixed amount"
    a, b = int(match_bps), 10000
    while b:
        a, b = b, a % b
    g = a or 1
    return f", matching {int(match_bps) // g}:{10000 // g} of what the fighters stake"


def _pot_sentences(f) -> str:
    """The fee/pot/bond/sensei prose shared by LOBBY and an orphan PUBLISH."""
    out = ""
    if f.get("entry_fee") is not None:
        out += f" A seat costs {qu(f['entry_fee'])}."
    if f.get("seed_cap"):
        out += (f" The house adds at most {qu(f['seed_cap'])} to this round's pot"
                f"{match_phrase(f.get('seed_cap'), f.get('match_bps'))}.")
    if f.get("payout_mode") is not None:
        out += f" Winnings go {mode_phrase(f.get('payout_mode_name', f.get('payout_mode')))}."
    if f.get("bond_bps"):
        out += (f" {int(f['bond_bps']) / 100:g}% of any win is held back as the winner's bond and released"
                f" once it has fought {f.get('bond_rounds', 0)} more rounds.")
    if f.get("sensei"):
        out += (" Fighters ranked above this belt may sit here as senseis: they win back at most their own"
                " stake and earn no belt points.")
    return out


# ----------------------------------------------------------------- describe

def describe(ev: dict) -> str:
    """One English sentence for one event. Pure: everything it needs is already
    merged into `ev` by build() -- name, belt, verdict, title, entry_fee."""
    k, f, rid = ev.get("kind"), ev.get("fields") or {}, ev.get("round_id")
    w, r = who(ev), f"round {rid}" if rid is not None else "a round"

    if k == "BOW":
        n = f.get("name") or ev.get("name")
        return (f"{n} bowed in. From now on the board shows this identity as {n}."
                if n else "A fighter bowed in and took a name.")

    if k == "LOBBY":
        belt = f.get("belt") or ev.get("belt") or ""
        head = f"The house opened the table for {r}" + (f" at the {belt} belt." if belt else ".")
        if f.get("min_players"):
            head += (f" The table needs {f['min_players']} fighters and stays open for"
                     f" {f.get('lobby_window', 0)} ticks (about {ticks_to_human(f.get('lobby_window', 0))}).")
        return head + _pot_sentences(f)

    if k == "PUBLISH":
        title = ev.get("title")
        head = (f"The house published {r}: “{title}”." if title
                else f"The house published the riddle for {r}.")
        if not ev.get("had_lobby"):
            head += _pot_sentences(f)
        if f.get("commit_window"):
            head += (f" Commits are accepted for {f['commit_window']} ticks"
                     f" (about {ticks_to_human(f['commit_window'])}) and reveals for"
                     f" {f.get('reveal_window', 0)} ticks after that.")
        if f.get("riddle_hash"):
            head += (f" The riddle hashes to {short(f['riddle_hash'])} and the house's own answer is sealed"
                     f" under {short(f.get('answer_commitment'))} -- it cannot change either one now.")
        return head

    if k == "ENTER":
        s = f"{w} bought a seat at {r} for {qu(ev.get('amount'))}."
        return s + _VERDICT_SUFFIX.get(ev.get("verdict"), "")

    if k == "COMMIT":
        stake = f" and staked {qu(ev['amount'])}" if ev.get("amount") else ""
        return (f"{w} committed an answer to {r}{stake}. The answer itself stays sealed as"
                f" {short(f.get('commitment'))} until the reveal window opens.")

    if k == "REVEAL":
        a = f.get("answer")
        a = (a[:120] + "…") if isinstance(a, str) and len(a) > 120 else a
        s = (f"{w} revealed “{a}” for {r}." if a is not None else f"{w} revealed its answer for {r}.")
        return s + _REVEAL_SUFFIX.get(ev.get("verdict"), "")

    if k == "SETTLE":
        s = (f"The house settled {r} and published the proof: the dojo salt {short(f.get('dojo_salt'))}"
             f" opens its sealed answer, and the whole settlement hashes to"
             f" {short(f.get('settlement_hash'))}.")
        return s + (f" Anyone can recompute it from {f['uri']}." if f.get("uri") else
                    " Anyone can recompute it from the published settlement.")

    if k == KIND_PAYOUT:
        pk, amt = f.get("payout_kind"), qu(ev.get("amount"))
        if pk == "win":
            return f"The house paid {amt} to {w} for winning {r}."
        if pk == "refund":
            return f"The house refunded {amt} to {w} for {r}."
        if pk == "bond_release":
            return f"The house released {w}'s bond of {amt} from {r}: it has fought the rounds it promised."
        if pk == "rake_dev":
            return f"The house paid the developer's share of the rake, {amt}, for {r}."
        return f"The house {_PAYOUT_VERB.get(pk, 'sent')} {amt} to {w} for {r}."

    if k == KIND_OTHER:
        return f"{qu(ev.get('amount'))} arrived from {w} carrying no dojo message. It is not part of any round."

    return "A dojo message the house can no longer read (an older wire format)."


def summarise(tick_events: list[dict]) -> str:
    """One line for a whole tick. Mechanical on purpose -- the sentences carry
    the detail, this only has to help someone scanning a list of ticks."""
    by = {}
    for e in tick_events:
        by.setdefault(e["kind"], []).append(e)
    for kind, tmpl in (("PUBLISH", "Round {} opened."), ("SETTLE", "Round {} settled."),
                       ("LOBBY", "The table for round {} opened.")):
        if by.get(kind):
            return tmpl.format(by[kind][0].get("round_id"))
    bits = []
    for kind, word in (("ENTER", "seat"), ("COMMIT", "commit"), ("REVEAL", "reveal"),
                       (KIND_PAYOUT, "payout"), ("BOW", "fighter bowing in"), (KIND_OTHER, "foreign transfer")):
        n = len(by.get(kind, []))
        if n:
            bits.append(f"{n} {word}{'s' if n != 1 else ''}")
    return (", ".join(bits) + ".").capitalize() if bits else "Nothing of ours happened here."


# -------------------------------------------------------------------- build

def _merge(ev, names, metas, riddles, idx_hit):
    """Fold the context describe() needs into the record: who the identity is,
    what the round was called, and what the round decided about this message."""
    idn = ev.get("identity") or ev.get("from")
    ev["name"] = names.get(idn)
    rid = ev.get("round_id")
    if rid is not None:
        meta, rp = metas.get(rid) or {}, riddles.get(rid) or {}
        ev["title"] = rp.get("title")
        ev["belt"] = meta.get("belt") or ""
        ev["had_lobby"] = meta.get("lobby_tick") is not None
        ev.setdefault("entry_fee", meta.get("entry_fee"))
    if idx_hit:
        for k in ("verdict", "payout_kind"):
            if idx_hit.get(k) and not ev.get(k):
                ev[k] = idx_hit[k]
    return ev


def _fields_from_meta(meta: dict) -> dict:
    """Everything a legacy PUBLISH/LOBBY frame would have carried, from the
    authoritative record the house kept when it sent it."""
    return {k: meta[k] for k in ("round_id", "entry_fee", "commit_window", "reveal_window", "payout_mode",
                                 "match_bps", "bond_bps", "bond_rounds", "sensei", "belt", "min_players",
                                 "lobby_window", "riddle_hash", "answer_commitment", "uri", "seed_cap")
            if meta.get(k) is not None} | ({"seed_cap": meta["house_seed"]} if meta.get("house_seed") else {})


def build(observed, house_identity, tx_index=None, payouts=(), names=None, metas=None, riddles=None,
          foreign="count") -> list[dict]:
    """Event records for every dojo message that reached the house, plus every
    payout it made. `foreign` is one of count|list|drop: what to do with the
    transfers that reach the house carrying no dojo message."""
    tx_index, names = tx_index or {}, names or {}
    metas, riddles = metas or {}, riddles or {}
    out = []
    for o in observed:
        if o.dest != house_identity:
            continue
        hit = tx_index.get(o.tx_id) or {}
        base = {"tick": o.tick, "tx": o.tx_id, "dir": "in", "from": o.source, "to": o.dest,
                "amount": o.amount, "identity": o.source, "payload": o.payload.hex() or None}
        if o.input_type != payload.INPUT_TYPE or not payload.is_dojo(o.payload):
            if foreign == "drop":
                continue
            if foreign == "list":
                out.append(_merge({**base, "kind": KIND_OTHER, "round_id": None, "fields": {},
                                   "decoded": False, "source": "chain"}, names, metas, riddles, hit))
            else:
                out.append({**base, "kind": KIND_OTHER, "foreign_only": True})
            continue
        m = payload.try_decode(o.payload)
        if m is not None:
            f = fields_of(m)
            ev = {**base, "kind": payload.KIND_NAMES[m.kind], "round_id": f.get("round_id"),
                  "fields": f, "decoded": True, "source": "payload"}
        elif hit:
            # Authoritative, not archaeology: the round dir still holds every field.
            ev = {**base, "kind": hit["kind"], "round_id": hit["round_id"],
                  "fields": _fields_from_meta(metas.get(hit["round_id"]) or {}),
                  "decoded": False, "source": "index"}
        else:
            ev = {**base, "kind": KIND_UNKNOWN, "round_id": None, "fields": {},
                  "decoded": False, "source": "chain"}
        out.append(_merge(ev, names, metas, riddles, hit))

    for p in payouts:
        ev = {"tick": p.get("tick"), "tx": p.get("tx"), "dir": "out", "from": house_identity,
              "to": p.get("identity"), "identity": p.get("identity"), "amount": p.get("amount"),
              "kind": KIND_PAYOUT, "round_id": p.get("round_id"), "payload": None, "decoded": True,
              "source": "ledger",
              "fields": {"payout_kind": p.get("kind"), "confirmed": bool(p.get("confirmed"))}}
        if ev["tick"] is not None:
            out.append(_merge(ev, names, metas, riddles, {}))

    for ev in out:
        if not ev.get("foreign_only"):
            ev["text"] = describe(ev)
    return sorted(out, key=lambda e: (e["tick"], e.get("kind") or "", e.get("tx") or ""))


def bucketize(records, bucket=BUCKET) -> dict:
    """Shard by tick // bucket. The page computes the filename arithmetically,
    so it never needs the index just to fetch one tick."""
    shards: dict[int, dict] = {}
    for ev in records:
        b = ev["tick"] // bucket
        s = shards.setdefault(b, {"bucket": b, "bucket_size": bucket, "ticks": {}})
        t = s["ticks"].setdefault(ev["tick"], {"tick": ev["tick"], "events": [],
                                               "foreign": {"count": 0, "amount": 0}})
        if ev.get("foreign_only"):
            t["foreign"]["count"] += 1
            t["foreign"]["amount"] += ev.get("amount") or 0
        else:
            t["events"].append({k: v for k, v in ev.items() if k not in _SCAFFOLD})
    for s in shards.values():
        ticks = []
        for t in sorted(s["ticks"].values(), key=lambda x: x["tick"]):
            t["summary"] = summarise(t["events"])
            ticks.append(t)
        s["ticks"] = ticks
        s["first_tick"], s["last_tick"] = ticks[0]["tick"], ticks[-1]["tick"]
    return shards


def index_doc(shards, generated_tick, bucket=BUCKET) -> dict:
    """Which shards exist, which ticks carry events, and how many of each kind.
    The tick array is what lets the page step to the previous or next event; if
    it ever passes ~50k ticks, move it into the shard files."""
    counts, ticks, buckets = {}, [], []
    for b in sorted(shards):
        s = shards[b]
        rounds = sorted({e["round_id"] for t in s["ticks"] for e in t["events"] if e.get("round_id") is not None})
        buckets.append({"bucket": b, "first_tick": s["first_tick"], "last_tick": s["last_tick"],
                        "count": sum(len(t["events"]) for t in s["ticks"]), "rounds": rounds})
        for t in s["ticks"]:
            ticks.append(t["tick"])
            for e in t["events"]:
                counts[e["kind"]] = counts.get(e["kind"], 0) + 1
    return {"generated_tick": generated_tick, "bucket_size": bucket, "buckets": buckets,
            "ticks": ticks, "counts": counts, "unresolved": counts.get(KIND_UNKNOWN, 0)}
