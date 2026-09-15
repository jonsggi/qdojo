"""The house: publish rounds, collect what landed, settle, export for the page.

State lives in a data directory of JSON files. Secrets (answer, dojo salt)
sit in a 0600 file per round and reach the chain only in SETTLE. Every send
is recorded before it is made and confirmed by tick inclusion before it is
believed; settlement is idempotent because of that ledger.
"""
import json
import os
import time
from dataclasses import asdict

from . import hashing, payload, riddle as R
from .round import RoundSpec, Observed, evaluate, to_dict
from .chain.base import Unknown, ChainError


class HouseError(Exception):
    pass


INDEX_MARGIN = 2     # never scan the last ticks the indexer claims, it may still be filling them
RESCAN = 300         # re-read this many ticks behind the scan pointer every time; tx_id dedup makes it free


def _read(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def _write(path, obj, mode=0o644):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, sort_keys=True, ensure_ascii=False)
    os.chmod(tmp, mode)
    os.replace(tmp, path)


def _obs_to_json(o: Observed) -> dict:
    d = asdict(o)
    d["payload"] = o.payload.hex()
    return d


def _obs_from_json(d: dict) -> Observed:
    return Observed(tick=d["tick"], tx_id=d["tx_id"], source=d["source"], dest=d["dest"], amount=d["amount"],
                    input_type=d["input_type"], payload=bytes.fromhex(d["payload"]))


class House:
    def __init__(self, chain, data_dir: str, identity: str, rake_bps: int = 0, seed_per_round: int = 0,
                 uri_base: str = ""):
        if not hashing.is_identity(identity):
            raise HouseError("house identity must be 60 uppercase letters")
        self.chain, self.data_dir, self.identity = chain, data_dir, identity
        self.rake_bps, self.seed_per_round, self.uri_base = rake_bps, seed_per_round, uri_base.rstrip("/")
        os.makedirs(os.path.join(data_dir, "rounds"), exist_ok=True)
        os.chmod(data_dir, 0o700)

    # ------------------------------------------------------------ state files
    def _state_path(self):
        return os.path.join(self.data_dir, "state.json")

    def state(self) -> dict:
        return _read(self._state_path(), {"carry": 0, "next_round": 1, "scanned_to": 0})

    def _save_state(self, st):
        _write(self._state_path(), st)

    def rdir(self, round_id: int) -> str:
        return os.path.join(self.data_dir, "rounds", f"{round_id:06d}")

    def _rpath(self, round_id, name):
        return os.path.join(self.rdir(round_id), name)

    def round_ids(self) -> list[int]:
        base = os.path.join(self.data_dir, "rounds")
        return sorted(int(d) for d in os.listdir(base) if d.isdigit())

    def _observed_path(self):
        return os.path.join(self.data_dir, "observed.jsonl")

    def observed(self) -> list[Observed]:
        out = []
        try:
            with open(self._observed_path(), encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        out.append(_obs_from_json(json.loads(line)))
        except FileNotFoundError:
            pass
        return sorted(set(out))

    # --------------------------------------------------------------- publish
    def publish(self, riddle_path: str, entry_fee: int, commit_window: int, reveal_window: int,
                house_seed: int | None = None, payout_mode: int = payload.MODE_FIRST, match_bps: int = 10000) -> dict:
        r, secret = R.load_authored(riddle_path)
        st = self.state()
        if r.round_id != st["next_round"]:
            raise HouseError(f"riddle is round {r.round_id}, next round is {st['next_round']}")
        if os.path.exists(self.rdir(r.round_id)):
            raise HouseError(f"round {r.round_id} already exists on disk")
        carry_in = st["carry"]
        if house_seed is None:
            house_seed = self.seed_per_round
        # The house must actually hold what it promises: the cap plus the carry is money.
        bal = self.chain.balance(self.identity)  # raises Unknown: an unknown is not a zero
        if bal < house_seed + carry_in:
            raise HouseError(f"house balance below the seed it would promise")
        uri = f"{self.uri_base}/rounds/{r.round_id}.json" if self.uri_base else ""
        msg = payload.Publish(r.round_id, entry_fee, commit_window, reveal_window, r.hash(),
                              R.commitment_for(r, secret), uri, payout_mode, house_seed, match_bps)
        os.makedirs(self.rdir(r.round_id), mode=0o700)
        _write(self._rpath(r.round_id, "riddle.json"), r.public())
        _write(self._rpath(r.round_id, "secret.json"),
               {"answer": secret.answer, "dojo_salt": secret.dojo_salt.hex()}, mode=0o600)
        meta = {"round_id": r.round_id, "entry_fee": entry_fee, "commit_window": commit_window,
                "reveal_window": reveal_window, "house_seed": house_seed, "rake_bps": self.rake_bps,
                "payout_mode": payload.MODE_NAMES[payout_mode], "match_bps": match_bps, "carry_in": carry_in,
                "riddle_hash": r.hash().hex(), "answer_commitment": msg.answer_commitment.hex(), "uri": uri,
                "publish_tx": None, "scheduled_tick": None, "publish_tick": None, "status": "publishing"}
        _write(self._rpath(r.round_id, "meta.json"), meta)
        res = self.chain.send(self.identity, 0, payload.encode(msg), payload.INPUT_TYPE)
        meta.update(publish_tx=res.tx_id, scheduled_tick=res.scheduled_tick)
        _write(self._rpath(r.round_id, "meta.json"), meta)
        st["next_round"] = r.round_id + 1
        st["carry"] = 0   # the whole carry went into this round's pot as carry_in
        self._save_state(st)
        return meta

    def confirm_publish(self, round_id: int) -> dict:
        meta = self.meta(round_id)
        if meta["status"] == "open":
            return meta
        if meta["status"] != "publishing":
            raise HouseError(f"round {round_id} is {meta['status']}")
        ok = self.chain.confirm(meta["publish_tx"], meta["scheduled_tick"])  # raises Unknown when too early
        if ok:
            meta.update(publish_tick=meta["scheduled_tick"], status="open")
        else:
            meta.update(status="failed")  # never landed: this round id is burned, author the next one
        _write(self._rpath(round_id, "meta.json"), meta)
        return meta

    def meta(self, round_id: int) -> dict:
        m = _read(self._rpath(round_id, "meta.json"))
        if m is None:
            raise HouseError(f"no round {round_id}")
        return m

    def spec(self, round_id: int) -> RoundSpec:
        m = self.meta(round_id)
        if m["publish_tick"] is None:
            raise HouseError(f"round {round_id} has no confirmed publish tick")
        r = R.from_public(_read(self._rpath(round_id, "riddle.json")))
        return RoundSpec(round_id, m["publish_tick"], m["entry_fee"], m["commit_window"], m["reveal_window"],
                         bytes.fromhex(m["riddle_hash"]), bytes.fromhex(m["answer_commitment"]),
                         r.answer_format, m["house_seed"], m["rake_bps"],
                         {v: k for k, v in payload.MODE_NAMES.items()}[m.get("payout_mode", "split")],
                         m.get("match_bps", 0), m.get("carry_in", 0))

    # --------------------------------------------------------------- collect
    def collect(self, up_to_tick: int | None = None) -> int:
        """Pull every transaction to the house since the last scan into the
        append-only observed log. Returns how many new ones were stored."""
        st = self.state()
        node = up_to_tick if up_to_tick is not None else self.chain.current_tick()
        indexed = self.chain.indexed_tick() - INDEX_MARGIN   # raises Unknown: an unindexed tick is not an empty tick
        end = min(node, indexed)
        start = max(1, st["scanned_to"] + 1 - RESCAN)
        if end <= st["scanned_to"]:
            return 0
        fresh = self.chain.transactions_to(self.identity, start, end)  # raises Unknown, never returns "nothing" on failure
        known = {o.tx_id for o in self.observed()}
        new = [o for o in fresh if o.tx_id not in known and o.tx_id]
        with open(self._observed_path(), "a", encoding="utf-8") as f:
            for o in sorted(new):
                f.write(json.dumps(_obs_to_json(o), sort_keys=True) + "\n")
        st["scanned_to"] = end
        self._save_state(st)
        return len(new)

    # ---------------------------------------------------------------- settle
    def plan(self, round_id: int, final: bool | None = None):
        spec = self.spec(round_id)
        st = self.state()
        if final is None:
            final = st["scanned_to"] > spec.reveal_end
        obs = [o for o in self.observed() if spec.publish_tick <= o.tick <= spec.reveal_end + 1]
        if final:
            if st["scanned_to"] <= spec.reveal_end:
                raise HouseError(f"round {round_id}: reveal window ends at tick {spec.reveal_end}, scanned only to {st['scanned_to']}")
            sec = _read(self._rpath(round_id, "secret.json"))
            return evaluate(spec, obs, self.identity, bytes.fromhex(sec["dojo_salt"]), sec["answer"], final=True)
        return evaluate(spec, obs, self.identity, None, None, final=False)

    def _ledger_path(self, round_id):
        return self._rpath(round_id, "payouts.json")

    def settle(self, round_id: int, apply: bool = False) -> dict:
        """Plan (always) and pay (only with apply). Re-runnable until every
        payout is confirmed. The house balance is re-read before and after."""
        meta = self.meta(round_id)
        if meta["status"] == "settled":
            return _read(self._rpath(round_id, "settlement.json"))
        if meta["status"] != "open":
            raise HouseError(f"round {round_id} is {meta['status']}, not open")
        ev = self.plan(round_id, final=True)
        self._confirm_entries(ev)
        ledger = _read(self._ledger_path(round_id), [])
        if not ledger:
            ledger = [{"identity": p.identity, "amount": p.amount, "kind": p.kind, "tx": None, "tick": None,
                       "confirmed": False} for p in ev.payouts]
            _write(self._ledger_path(round_id), ledger)
        else:
            planned = [(p.identity, p.amount, p.kind) for p in ev.payouts]
            if [(l["identity"], l["amount"], l["kind"]) for l in ledger] != planned:
                raise HouseError("existing payout ledger disagrees with a fresh evaluation; refusing to touch money")
        if not apply:
            return self._settlement_doc(round_id, ev, ledger, meta)

        for entry in ledger:
            if entry["confirmed"]:
                continue
            if entry["tx"] is not None:
                # sent earlier, not yet confirmed: ask the chain before sending again
                try:
                    if self.chain.confirm(entry["tx"], entry["tick"]):
                        entry["confirmed"] = True
                        _write(self._ledger_path(round_id), ledger)
                        continue
                except Unknown:
                    raise HouseError(f"payout to {entry['identity'][:8]}… sent as {entry['tx'][:8]}… is not yet decidable; retry later, do not resend")
                # definitely not in its tick: safe to send again
            before = self.chain.balance(self.identity)
            if before < entry["amount"]:
                raise HouseError("house balance below the next payout; refusing")
            res = self.chain.send(entry["identity"], entry["amount"])
            entry.update(tx=res.tx_id, tick=res.scheduled_tick)
            _write(self._ledger_path(round_id), ledger)  # recorded before it is believed
            self._wait_confirm(entry, ledger, round_id, before)

        if all(e["confirmed"] for e in ledger):
            doc = self._settlement_doc(round_id, ev, ledger, meta)
            doc["hash"] = hashing.settlement_hash(doc).hex()
            uri = f"{self.uri_base}/settlements/{round_id}.json" if self.uri_base else ""
            sec = _read(self._rpath(round_id, "secret.json"))
            msg = payload.Settle(round_id, bytes.fromhex(sec["dojo_salt"]), bytes.fromhex(doc["hash"]), uri)
            res = self.chain.send(self.identity, 0, payload.encode(msg), payload.INPUT_TYPE)
            doc["settle_tx"], doc["settle_tick"] = res.tx_id, res.scheduled_tick
            _write(self._rpath(round_id, "settlement.json"), doc)
            meta["status"] = "settled"
            _write(self._rpath(round_id, "meta.json"), meta)
            st = self.state()
            st["carry"] += ev.carry
            self._save_state(st)
            return doc
        return self._settlement_doc(round_id, ev, ledger, meta)

    def _confirm_entries(self, ev):
        """The indexer only discovers. Before an entry can move money, a node
        must confirm each of its transactions in its tick (docs/spec.md §8)."""
        for e in ev.entries:
            for tx, tick, what in ((e.commit_tx, e.commit_tick, "commit"), (e.reveal_tx, e.reveal_tick, "reveal")):
                if tx is None:
                    continue
                try:
                    ok = self.chain.confirm(tx, tick)
                except Unknown as x:
                    raise HouseError(f"cannot confirm {what} {tx[:8]}… of {e.identity[:8]}… at tick {tick} against a node ({x}); retry, do not settle")
                if not ok:
                    raise HouseError(f"{what} {tx[:8]}… of {e.identity[:8]}… is NOT in tick {tick} on the node; indexer and node disagree, refusing to settle")

    def _wait_confirm(self, entry, ledger, round_id, before, tries=60, sleep=1.0):
        for _ in range(tries):
            try:
                ok = self.chain.confirm(entry["tx"], entry["tick"])
            except Unknown:
                time.sleep(sleep)
                continue
            if ok:
                after = self.chain.balance(self.identity)
                if after != before - entry["amount"]:
                    # Money moved, but not by exactly this amount: other traffic hit the house in between
                    # (a stake arriving is normal). Inclusion is the proof; the delta is logged, not enforced.
                    entry["balance_note"] = f"before={before} after={after}"
                entry["confirmed"] = True
                _write(self._ledger_path(round_id), ledger)
                return
            raise HouseError(f"payout {entry['tx'][:8]}… was NOT included in tick {entry['tick']}; rerun settle to resend")
        raise HouseError(f"payout {entry['tx'][:8]}… still undecidable after {tries} tries; rerun settle later")

    def _settlement_doc(self, round_id, ev, ledger, meta) -> dict:
        sec = _read(self._rpath(round_id, "secret.json"))
        d = to_dict(ev, bytes.fromhex(sec["dojo_salt"]), sec["answer"])
        d["payouts"] = ledger
        d["house"] = self.identity
        d["publish_tx"] = meta["publish_tx"]
        return d

    # ---------------------------------------------------------------- export
    def bows(self) -> dict[str, dict]:
        out = {}
        for o in self.observed():
            if o.dest != self.identity or o.input_type != payload.INPUT_TYPE:
                continue
            m = payload.try_decode(o.payload)
            if isinstance(m, payload.Bow) and o.source not in out:
                out[o.source] = {"name": m.name, "bow_tick": o.tick}
        return out

    def export(self, out_dir: str, now_tick: int | None = None) -> dict:
        """Write board.json and history.json (docs/protocol.md, apps/web)."""
        os.makedirs(out_dir, exist_ok=True)
        os.makedirs(os.path.join(out_dir, "rounds"), exist_ok=True)
        os.makedirs(os.path.join(out_dir, "settlements"), exist_ok=True)
        st = self.state()
        now = now_tick if now_tick is not None else st["scanned_to"]
        bows = self.bows()
        fighters: dict[str, dict] = {}

        def fighter(idn):
            return fighters.setdefault(idn, {"identity": idn, "name": bows.get(idn, {}).get("name"),
                                             "bow_tick": bows.get(idn, {}).get("bow_tick"),
                                             "rounds_played": 0, "wins": 0, "earned": 0, "strikes": 0})

        rounds, open_rounds = [], []
        for rid in self.round_ids():
            meta = self.meta(rid)
            if meta["status"] in ("publishing", "failed"):
                continue
            rpub = _read(self._rpath(rid, "riddle.json"))
            _write(os.path.join(out_dir, "rounds", f"{rid}.json"), rpub)
            spec = self.spec(rid)
            settled = meta["status"] == "settled"
            state = "settled" if settled else spec.state_at(now)
            ev = self.plan(rid, final=False) if not settled else None
            doc = _read(self._rpath(rid, "settlement.json")) if settled else None
            if doc:
                _write(os.path.join(out_dir, "settlements", f"{rid}.json"), doc)
            entries_src = doc["entries"] if doc else [vars(e) for e in ev.entries]
            entries = []
            for e in entries_src:
                f = fighter(e["identity"])
                entries.append({"identity": e["identity"], "name": f["name"], "commit_tick": e["commit_tick"],
                                "commit_tx": e["commit_tx"], "stake": e["stake"], "reveal_tick": e["reveal_tick"],
                                "reveal_tx": e["reveal_tx"], "verdict": e["verdict"],
                                "answer": e["answer"] if settled else None})
                if e["verdict"] in ("winner", "solved", "wrong", "no_reveal", "bad_reveal", "pending"):
                    f["rounds_played"] += 1
                if e["verdict"] == "winner":
                    f["wins"] += 1
            strikes = doc["strikes"] if doc else ev.strikes
            for idn, reasons in strikes.items():
                fighter(idn)["strikes"] += len(reasons)
            settlement = None
            if doc:
                for p in doc["payouts"]:
                    if p["kind"] == "win" and p["confirmed"]:
                        fighter(p["identity"])["earned"] += p["amount"]
                settlement = dict(doc)  # exactly the hashed document, so the page can re-verify it
            rd = {"round_id": rid, "title": rpub["title"], "state": state, "publish_tick": meta["publish_tick"],
                  "publish_tx": meta["publish_tx"], "commit_window": meta["commit_window"],
                  "reveal_window": meta["reveal_window"], "entry_fee": meta["entry_fee"],
                  "house_seed": meta["house_seed"], "rake_bps": meta["rake_bps"],
                  "payout_mode": meta.get("payout_mode", "split"), "match_bps": meta.get("match_bps", 0),
                  "carry_in": meta.get("carry_in", 0), "riddle_hash": meta["riddle_hash"],
                  "answer_commitment": meta["answer_commitment"], "riddle": rpub,
                  "entries": entries, "settlement": settlement}
            rounds.append(rd)
            if state in ("commit", "reveal"):
                open_rounds.append({k: v for k, v in rd.items() if k != "entries"})
        for idn in bows:
            fighter(idn)
        history = {"house": self.identity, "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                   "generated_tick": now, "rounds": rounds,
                   "fighters": sorted(fighters.values(), key=lambda f: (-f["earned"], -f["wins"], f["identity"]))}
        board = {"house": self.identity, "generated_tick": now, "rounds": open_rounds}
        _write(os.path.join(out_dir, "history.json"), history)
        _write(os.path.join(out_dir, "board.json"), board)
        return history
