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

from . import hashing, payload, riddle as R, belts as B, events
from .round import RoundSpec, Observed, evaluate, to_dict, void as void_eval
from .chain.base import Unknown, ChainError


class HouseError(Exception):
    pass


def _log_note(house, round_id, note):
    path = os.path.join(house.rdir(round_id), "notes.jsonl")
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps({"utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "note": note}) + "\n")


INDEX_MARGIN = 2     # never scan the last ticks the indexer claims, it may still be filling them
BOND_EXPIRY_ROUNDS = 20   # a bond whose holder has not fought enough rounds by then is forfeited to the pot
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


def _write_if_changed(path, obj, mode=0o644, compact=False) -> bool:
    """Write only when the bytes differ. The supervisor re-exports ~15 times a
    round; rewriting a hundred unchanged tick shards every poll is pure churn.
    Shards are compact: nothing reads them but the page."""
    body = (json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":")) if compact
            else json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False))
    try:
        with open(path, encoding="utf-8") as f:
            if f.read() == body:
                return False
    except (OSError, ValueError):
        pass
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(body)
    os.chmod(tmp, mode)
    os.replace(tmp, path)
    return True


def _obs_to_json(o: Observed) -> dict:
    d = asdict(o)
    d["payload"] = o.payload.hex()
    return d


def _obs_from_json(d: dict) -> Observed:
    return Observed(tick=d["tick"], tx_id=d["tx_id"], source=d["source"], dest=d["dest"], amount=d["amount"],
                    input_type=d["input_type"], payload=bytes.fromhex(d["payload"]))


REFUSED_VERDICTS = ("late", "underpaid", "outranked")   # never bought a seat: refused and refunded


def _seats(entries) -> int:
    """How many of these entries bought a seat (docs/spec.md §5): a refused
    ENTER (late, underpaid, outranked) never did, on a settled round or a
    void one alike. Used by both fee_rows() and export() so the fee
    controller's occupancy and the published round agree."""
    return len([e for e in entries if e["verdict"] not in REFUSED_VERDICTS])


class House:
    def __init__(self, chain, data_dir: str, identity: str, rake_bps: int = 0, seed_per_round: int = 0,
                 uri_base: str = "", house_fighters: tuple = (), dev_identity: str = "",
                 rake_house_bps: int = 10000, rake_dev_bps: int = 0, rake_share_bps: int = 0):
        if not hashing.is_identity(identity):
            raise HouseError("house identity must be 60 uppercase letters")
        self.chain, self.data_dir, self.identity = chain, data_dir, identity
        self.rake_bps, self.seed_per_round, self.uri_base = rake_bps, seed_per_round, uri_base.rstrip("/")
        self.house_fighters = tuple(house_fighters)
        self.dev_identity = dev_identity
        self.rake_house_bps, self.rake_dev_bps, self.rake_share_bps = rake_house_bps, rake_dev_bps, rake_share_bps
        os.makedirs(os.path.join(data_dir, "rounds"), exist_ok=True)
        os.chmod(data_dir, 0o700)

    # ------------------------------------------------------------ state files
    def _state_path(self):
        return os.path.join(self.data_dir, "state.json")

    def state(self) -> dict:
        return _read(self._state_path(), {"carry": 0, "next_round": 1, "scanned_to": 0})

    def _save_state(self, st):
        _write(self._state_path(), st)

    def _belts_path(self):
        return os.path.join(self.data_dir, "belts.json")

    def belts(self) -> dict:
        return _read(self._belts_path(), {})

    def _save_belts(self, st):
        _write(self._belts_path(), st)

    def _bonds_path(self):
        return os.path.join(self.data_dir, "bonds.json")

    def bonds(self) -> list:
        """Open bonds: [{identity, amount, round_id, need, fought, released, forfeited}]."""
        return _read(self._bonds_path(), [])

    def _save_bonds(self, bonds):
        _write(self._bonds_path(), bonds)

    def _bond_events(self, round_id: int, ev, spec) -> tuple[list, list, int]:
        """What this settlement does to the bond ledger, without touching it:
        (new bonds held, release payouts due, amount forfeited)."""
        fought = {e.identity for e in ev.entries if e.verdict in ("winner", "solved", "wrong", "no_reveal", "no_commit", "bad_reveal")}
        bonds = [dict(b) for b in self.bonds()]
        releases, forfeited = [], 0
        for b in bonds:
            if b.get("released") or b.get("forfeited"):
                continue
            if b["identity"] in fought and b["round_id"] < round_id:
                b["fought"] += 1
            if b["fought"] >= b["need"]:
                b["released"] = round_id
                releases.append({"identity": b["identity"], "amount": b["amount"], "kind": "bond_release", "bond_round": b["round_id"]})
            elif round_id - b["round_id"] >= BOND_EXPIRY_ROUNDS:
                b["forfeited"] = round_id
                forfeited += b["amount"]
        held = [{"identity": bd.identity, "amount": bd.amount, "round_id": round_id, "need": spec.bond_rounds,
                 "fought": 0, "released": None, "forfeited": None} for bd in ev.bonds]
        return bonds + held, releases, forfeited

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
                house_seed: int | None = None, payout_mode: int = payload.MODE_FIRST, match_bps: int = 10000,
                belt: str = "", bond_bps: int = 0, bond_rounds: int = 0, sensei: bool = False,
                fee_policy: dict | None = None) -> dict:
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
                              R.commitment_for(r, secret), uri, payout_mode, house_seed, match_bps, bond_bps, bond_rounds,
                              1 if sensei else 0)
        os.makedirs(self.rdir(r.round_id), mode=0o700)
        _write(self._rpath(r.round_id, "riddle.json"), r.public())
        _write(self._rpath(r.round_id, "secret.json"),
               {"answer": secret.answer, "dojo_salt": secret.dojo_salt.hex()}, mode=0o600)
        meta = {"round_id": r.round_id, "entry_fee": entry_fee, "commit_window": commit_window,
                "reveal_window": reveal_window, "house_seed": house_seed, "rake_bps": self.rake_bps,
                "payout_mode": payload.MODE_NAMES[payout_mode], "match_bps": match_bps, "carry_in": carry_in,
                "riddle_hash": r.hash().hex(), "answer_commitment": msg.answer_commitment.hex(), "uri": uri,
                "belt": belt, "bond_bps": bond_bps, "bond_rounds": bond_rounds, "sensei": bool(sensei),
                "house_fighters": list(self.house_fighters), "fee_policy": fee_policy,
                "rake_house_bps": self.rake_house_bps, "rake_dev_bps": self.rake_dev_bps, "rake_share_bps": self.rake_share_bps,
                "publish_tx": None, "scheduled_tick": None, "publish_tick": None, "status": "publishing"}
        _write(self._rpath(r.round_id, "meta.json"), meta)
        res = self.chain.send(self.identity, 0, payload.encode(msg), payload.INPUT_TYPE)
        meta.update(publish_tx=res.tx_id, scheduled_tick=res.scheduled_tick)
        _write(self._rpath(r.round_id, "meta.json"), meta)
        st["next_round"] = r.round_id + 1
        st["carry"] = 0   # the whole carry went into this round's pot as carry_in
        self._save_state(st)
        return meta

    # ---------------------------------------------------------------- lobby
    def open_lobby(self, riddle_path: str, entry_fee: int, min_players: int, lobby_window: int, commit_window: int,
                   reveal_window: int, house_seed: int | None = None, payout_mode: int = payload.MODE_FIRST,
                   match_bps: int = 10000, belt: str = "", bond_bps: int = 0, bond_rounds: int = 0,
                   sensei: bool = False, fee_policy: dict | None = None) -> dict:
        """Announce a round and open the table. The riddle is chosen now and
        kept secret; PUBLISH follows when the table is full. `fee_policy` is
        how `entry_fee` was derived when a controller chose it (fees.py); it
        is published with the round so anyone can replay it."""
        r, secret = R.load_authored(riddle_path)
        st = self.state()
        if r.round_id != st["next_round"]:
            raise HouseError(f"riddle is round {r.round_id}, next round is {st['next_round']}")
        if os.path.exists(self.rdir(r.round_id)):
            raise HouseError(f"round {r.round_id} already exists on disk")
        carry_in = st["carry"]
        if house_seed is None:
            house_seed = self.seed_per_round
        bal = self.chain.balance(self.identity)
        if bal < house_seed + carry_in:
            raise HouseError("house balance below the seed it would promise")
        uri = f"{self.uri_base}/rounds/{r.round_id}.json" if self.uri_base else ""
        msg = payload.Lobby(r.round_id, entry_fee, min_players, lobby_window, commit_window, reveal_window,
                            payout_mode, house_seed, match_bps, belt, bond_bps, bond_rounds, 1 if sensei else 0)
        os.makedirs(self.rdir(r.round_id), mode=0o700)
        _write(self._rpath(r.round_id, "riddle.json"), r.public())
        _write(self._rpath(r.round_id, "secret.json"),
               {"answer": secret.answer, "dojo_salt": secret.dojo_salt.hex()}, mode=0o600)
        meta = {"round_id": r.round_id, "entry_fee": entry_fee, "commit_window": commit_window,
                "reveal_window": reveal_window, "house_seed": house_seed, "rake_bps": self.rake_bps,
                "payout_mode": payload.MODE_NAMES[payout_mode], "match_bps": match_bps, "carry_in": carry_in,
                "riddle_hash": r.hash().hex(), "answer_commitment": R.commitment_for(r, secret).hex(), "uri": uri,
                "belt": belt, "min_players": min_players, "lobby_window": lobby_window,
                "bond_bps": bond_bps, "bond_rounds": bond_rounds, "sensei": bool(sensei),
                "house_fighters": list(self.house_fighters), "fee_policy": fee_policy,
                "rake_house_bps": self.rake_house_bps, "rake_dev_bps": self.rake_dev_bps, "rake_share_bps": self.rake_share_bps,
                "lobby_tx": None, "lobby_scheduled_tick": None, "lobby_tick": None,
                "publish_tx": None, "scheduled_tick": None, "publish_tick": None, "status": "lobby_opening"}
        _write(self._rpath(r.round_id, "meta.json"), meta)
        res = self.chain.send(self.identity, 0, payload.encode(msg), payload.INPUT_TYPE)
        meta.update(lobby_tx=res.tx_id, lobby_scheduled_tick=res.scheduled_tick)
        _write(self._rpath(r.round_id, "meta.json"), meta)
        st["next_round"] = r.round_id + 1
        st["carry"] = 0
        self._save_state(st)
        return meta

    def confirm_lobby(self, round_id: int) -> dict:
        meta = self.meta(round_id)
        if meta["status"] != "lobby_opening":
            return meta
        ok = self.chain.confirm(meta["lobby_tx"], meta["lobby_scheduled_tick"])
        meta.update(lobby_tick=meta["lobby_scheduled_tick"] if ok else None, status="lobby" if ok else "failed")
        _write(self._rpath(round_id, "meta.json"), meta)
        if not ok:
            st = self.state(); st["carry"] += meta.get("carry_in", 0); self._save_state(st)   # the round never opened: the carry rolls on
        return meta

    def lobby_entrants(self, round_id: int) -> list:
        """Identities with a counted ENTER so far (from the observed log)."""
        ev = self.plan(round_id, final=False)
        return [e.identity for e in ev.entries if e.verdict == "pending"]  # outranked/late/underpaid never count

    def publish_from_lobby(self, round_id: int) -> dict:
        """The table is full (or the window closed with enough players): publish the riddle."""
        meta = self.meta(round_id)
        if meta["status"] != "lobby":
            raise HouseError(f"round {round_id} is {meta['status']}, not in lobby")
        r = R.from_public(_read(self._rpath(round_id, "riddle.json")))
        mode = {v: k for k, v in payload.MODE_NAMES.items()}[meta["payout_mode"]]
        msg = payload.Publish(round_id, meta["entry_fee"], meta["commit_window"], meta["reveal_window"], r.hash(),
                              bytes.fromhex(meta["answer_commitment"]), meta["uri"], mode, meta["house_seed"], meta["match_bps"],
                              meta.get("bond_bps", 0), meta.get("bond_rounds", 0), 1 if meta.get("sensei") else 0)
        res = self.chain.send(self.identity, 0, payload.encode(msg), payload.INPUT_TYPE)
        meta.update(publish_tx=res.tx_id, scheduled_tick=res.scheduled_tick, status="publishing")
        _write(self._rpath(round_id, "meta.json"), meta)
        return meta

    def void(self, round_id: int, apply: bool = False) -> dict:
        """A lobby that did not fill by its deadline: refund every entrant and close the round."""
        meta = self.meta(round_id)
        if meta["status"] == "void":
            return _read(self._rpath(round_id, "settlement.json"))
        if meta["status"] != "lobby":
            raise HouseError(f"round {round_id} is {meta['status']}, cannot void")
        spec = self.spec(round_id)
        if self.state()["scanned_to"] <= spec.lobby_end:
            raise HouseError(f"lobby of round {round_id} runs until tick {spec.lobby_end}; not over yet")
        obs = [o for o in self.observed() if spec.lobby_tick <= o.tick <= spec.lobby_end + 1]
        ev = void_eval(spec, obs, self.identity, belts=self._belts_before(round_id))
        self._confirm_entries(ev)
        ledger = _read(self._ledger_path(round_id), [])
        if not ledger:
            ledger = [{"identity": p.identity, "amount": p.amount, "kind": p.kind, "tx": None, "tick": None,
                       "confirmed": False} for p in ev.payouts]
            _write(self._ledger_path(round_id), ledger)
        doc = to_dict(ev)
        doc.update(void=True, house=self.identity, lobby_tx=meta["lobby_tx"], payouts=ledger,
                   answer=None, dojo_salt=None, seed_used=0, carry=meta.get("carry_in", 0))
        if not apply:
            return doc
        self._pay_ledger(round_id, ledger)
        if all(e["confirmed"] for e in ledger):
            doc["hash"] = hashing.settlement_hash(doc).hex()
            sec = _read(self._rpath(round_id, "secret.json"))
            msg = payload.Settle(round_id, bytes.fromhex(sec["dojo_salt"]), bytes.fromhex(doc["hash"]),
                                 f"{self.uri_base}/settlements/{round_id}.json" if self.uri_base else "")
            res = self.chain.send(self.identity, 0, payload.encode(msg), payload.INPUT_TYPE)
            doc["settle_tx"], doc["settle_tick"] = res.tx_id, res.scheduled_tick
            _write(self._rpath(round_id, "settlement.json"), doc)
            meta["status"] = "void"; _write(self._rpath(round_id, "meta.json"), meta)
            st = self.state(); st["carry"] += meta["carry_in"]; self._save_state(st)   # the carry rolls on
        return doc

    def confirm_publish(self, round_id: int) -> dict:
        meta = self.meta(round_id)
        if meta["status"] == "open":
            return meta
        if meta["status"] != "publishing":
            raise HouseError(f"round {round_id} is {meta['status']}")
        ok = self.chain.confirm(meta["publish_tx"], meta["scheduled_tick"])  # raises Unknown when too early
        if ok:
            meta.update(publish_tick=meta["scheduled_tick"], status="open")
            _write(self._rpath(round_id, "meta.json"), meta)
        elif meta.get("lobby_tick") is not None:
            # publish_from_lobby()'s PUBLISH never landed: entrants already paid
            # via ENTER, so the round goes back to "lobby" to be re-published or
            # voided with refunds, instead of being burned with stakes stranded.
            meta.update(status="lobby")
            _write(self._rpath(round_id, "meta.json"), meta)
        else:
            meta.update(status="failed")  # never landed: this round id is burned, author the next one
            _write(self._rpath(round_id, "meta.json"), meta)
            st = self.state(); st["carry"] += meta.get("carry_in", 0); self._save_state(st)   # the carry rolls on
        return meta

    def meta(self, round_id: int) -> dict:
        m = _read(self._rpath(round_id, "meta.json"))
        if m is None:
            raise HouseError(f"no round {round_id}")
        return m

    def spec(self, round_id: int) -> RoundSpec:
        m = self.meta(round_id)
        if m["publish_tick"] is None and m.get("lobby_tick") is None:
            raise HouseError(f"round {round_id} has no confirmed publish tick")
        r = R.from_public(_read(self._rpath(round_id, "riddle.json")))
        return RoundSpec(round_id, m["publish_tick"], m["entry_fee"], m["commit_window"], m["reveal_window"],
                         bytes.fromhex(m["riddle_hash"]), bytes.fromhex(m["answer_commitment"]),
                         r.answer_format, m["house_seed"], m["rake_bps"],
                         {v: k for k, v in payload.MODE_NAMES.items()}[m.get("payout_mode", "split")],
                         m.get("match_bps", 0), m.get("carry_in", 0),
                         m.get("lobby_tick"), m.get("lobby_window", 0), m.get("min_players", 0),
                         B.RANKS.get(m.get("belt") or "", None), m.get("bond_bps", 0), m.get("bond_rounds", 0),
                         tuple(m.get("house_fighters", [])),
                         rake_house_bps=m.get("rake_house_bps", 10000), rake_dev_bps=m.get("rake_dev_bps", 0),
                         rake_share_bps=m.get("rake_share_bps", 0), sensei=bool(m.get("sensei", False)))

    def fee_rows(self) -> list[dict]:
        """One row per settled or void round with what the fee controller
        reads (fees.py): the same numbers history.json publishes for the
        round, so a bot replaying the export computes the same fee."""
        rows = []
        for rid in self.round_ids():
            meta = self.meta(rid)
            if meta["status"] not in ("settled", "void"):
                continue
            doc = _read(self._rpath(rid, "settlement.json")) or {}
            rows.append({"round_id": rid, "belt": meta.get("belt", ""), "state": meta["status"],
                         "entrants": _seats(doc.get("entries", [])),
                         "entry_fee": meta["entry_fee"]})
        return rows

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

    def rescan(self, start_tick: int, end_tick: int) -> int:
        """Re-read a past range into the observed log (never moves the scan pointer)."""
        end = min(end_tick, self.chain.indexed_tick() - INDEX_MARGIN)
        fresh = self.chain.transactions_to(self.identity, start_tick, end)
        known = {o.tx_id for o in self.observed()}
        new = [o for o in fresh if o.tx_id not in known and o.tx_id]
        with open(self._observed_path(), "a", encoding="utf-8") as f:
            for o in sorted(new):
                f.write(json.dumps(_obs_to_json(o), sort_keys=True) + "\n")
        return len(new)

    # ---------------------------------------------------------------- settle
    def plan(self, round_id: int, final: bool | None = None, exclude=frozenset()):
        spec = self.spec(round_id)
        st = self.state()
        if final is None:
            final = st["scanned_to"] > spec.reveal_end
        first = spec.lobby_tick if spec.lobby else spec.publish_tick
        last = spec.reveal_end + 1 if spec.publish_tick is not None else spec.lobby_end + 1
        obs = [o for o in self.observed() if first <= o.tick <= last and o.tx_id not in exclude]
        if final:
            if st["scanned_to"] <= spec.reveal_end:
                raise HouseError(f"round {round_id}: reveal window ends at tick {spec.reveal_end}, scanned only to {st['scanned_to']}")
            sec = _read(self._rpath(round_id, "secret.json"))
            return evaluate(spec, obs, self.identity, bytes.fromhex(sec["dojo_salt"]), sec["answer"], final=True,
                            belts=self._belts_before(round_id))
        return evaluate(spec, obs, self.identity, None, None, final=False, belts=self._belts_before(round_id))

    def _belts_before(self, round_id: int) -> dict:
        """The belt state that applied when this round opened: the persisted
        state minus nothing for open rounds, and for settled rounds the state
        recorded in their settlement (so a re-plan reproduces the verdicts)."""
        doc = _read(self._rpath(round_id, "settlement.json"))
        if doc and "belts_before" in doc:
            return doc["belts_before"]
        return self.belts()

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
        absent, ev = set(), None
        for _ in range(4):
            ev = self.plan(round_id, final=True, exclude=absent)
            fresh = self._confirm_entries(ev)
            if not fresh - absent:
                break
            absent |= fresh          # a node proved these never landed: re-evaluate without them
        spec = self.spec(round_id)
        bonds_after, releases, forfeited = self._bond_events(round_id, ev, spec)
        rake_payouts = []
        if self.dev_identity and ev.rake_split.get("dev", 0) > 0:
            rake_payouts.append((self.dev_identity, ev.rake_split["dev"], "rake_dev"))
        planned_payouts = ([(p.identity, p.amount, p.kind) for p in ev.payouts]
                           + [(r["identity"], r["amount"], r["kind"]) for r in releases] + rake_payouts)
        ledger = _read(self._ledger_path(round_id), [])
        if not ledger:
            ledger = [{"identity": i, "amount": a, "kind": k, "tx": None, "tick": None, "confirmed": False}
                      for i, a, k in planned_payouts]
            _write(self._ledger_path(round_id), ledger)
        else:
            planned = planned_payouts
            if [(l["identity"], l["amount"], l["kind"]) for l in ledger] != planned:
                if any(l["confirmed"] for l in ledger):
                    # Some of this round is already paid. A re-evaluation can
                    # legitimately differ (a message proved absent since), but
                    # money already sent fixes the plan: finish THIS ledger.
                    _log_note(self, round_id, "ledger kept: a fresh evaluation differs but payouts are already confirmed")
                else:
                    # Nothing has been paid, so there is no plan to protect:
                    # adopt the fresh evaluation instead of refusing for ever.
                    _log_note(self, round_id, "ledger replaced by a fresh evaluation (nothing was paid yet)")
                    ledger = [{"identity": i, "amount": a, "kind": k, "tx": None, "tick": None, "confirmed": False}
                              for i, a, k in planned_payouts]
                    _write(self._ledger_path(round_id), ledger)
        if not apply:
            d = self._settlement_doc(round_id, ev, ledger, meta)
            d["bonds_released"], d["bonds_forfeited"] = releases, forfeited
            return d

        self._pay_ledger(round_id, ledger)

        if all(e["confirmed"] for e in ledger):
            doc = self._settlement_doc(round_id, ev, ledger, meta)
            doc["bonds_released"] = releases
            doc["bonds_forfeited"] = forfeited
            doc["unconfirmed_dropped"] = sorted(absent)
            st0 = self.state()
            share = ev.rake_split.get("shareholders", 0)
            doc["rake_split"] = ev.rake_split
            doc["shareholder_pool_after"] = st0.get("shareholder_pool", 0) + share
            before = self.belts()
            doc["belts_before"] = {k: dict(v) for k, v in before.items()}
            if spec.belt_rank is not None:
                changes = B.apply_settlement(before, spec.belt_rank, ev.entries)
                doc["belt_changes"] = [vars(c) for c in changes]
            doc["hash"] = hashing.settlement_hash(doc).hex()
            uri = f"{self.uri_base}/settlements/{round_id}.json" if self.uri_base else ""
            sec = _read(self._rpath(round_id, "secret.json"))
            msg = payload.Settle(round_id, bytes.fromhex(sec["dojo_salt"]), bytes.fromhex(doc["hash"]), uri)
            res = self.chain.send(self.identity, 0, payload.encode(msg), payload.INPUT_TYPE)
            doc["settle_tx"], doc["settle_tick"] = res.tx_id, res.scheduled_tick
            _write(self._rpath(round_id, "settlement.json"), doc)
            meta["status"] = "settled"
            _write(self._rpath(round_id, "meta.json"), meta)
            if spec.belt_rank is not None:
                self._save_belts(before)   # `before` was mutated into the after-state above
            self._save_bonds(bonds_after)
            st = self.state()
            st["carry"] += ev.carry + forfeited
            st["shareholder_pool"] = st.get("shareholder_pool", 0) + ev.rake_split.get("shareholders", 0)
            st["dev_paid"] = st.get("dev_paid", 0) + ev.rake_split.get("dev", 0)
            self._save_state(st)
            return doc
        return self._settlement_doc(round_id, ev, ledger, meta)

    def _pay_ledger(self, round_id, ledger):
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

    def _confirm_entries(self, ev) -> set:
        """The indexer only discovers. Before an entry can move money, a node
        must confirm each of its transactions in its tick (docs/spec.md §8).

        Returns the tx ids a node is CERTAIN are not in their tick, so the
        caller can re-evaluate the round without them. An undecidable answer
        still aborts: we never pay on an unconfirmed message."""
        absent = set()
        for e in ev.entries:
            for tx, tick, what in ((e.enter_tx, e.enter_tick, "enter"), (e.commit_tx, e.commit_tick, "commit"),
                                   (e.reveal_tx, e.reveal_tick, "reveal")):
                if tx is None:
                    continue
                try:
                    ok = self.chain.confirm(tx, tick)
                except Unknown as x:
                    raise HouseError(f"cannot confirm {what} {tx[:8]}… of {e.identity[:8]}… at tick {tick} against a node ({x}); retry, do not settle")
                if not ok:
                    absent.add(tx)
        return absent


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

    def sign_doc(self, path: str, uri: str, apply: bool = False) -> dict:
        """Put the house's name to a document by publishing its hash on chain.

        There is no detached-signature primitive in qubic-cli, and there does not
        need to be: a transaction signed by the house identity, carrying the
        document's hash, IS the signature, and the tick it lands in IS the
        publication date. Anyone can check both with a block explorer.

        The hash covers the document's body only -- everything above the
        provenance marker -- so the block naming the tick and the transaction can
        be appended afterwards without invalidating what was signed. A settlement
        hashes itself the same way.
        """
        with open(path, encoding="utf-8") as f:
            text = f.read()
        h = hashing.doc_hash(text)
        m = payload.Doc(h, uri)
        plan = {"file": path, "uri": uri, "doc_hash": h.hex(), "house": self.identity,
                "bytes": len(payload.encode(m))}
        if not apply:
            return plan | {"applied": False}
        r = self.chain.send(self.identity, 0, payload.encode(m), payload.INPUT_TYPE)
        plan |= {"tx": r.tx_id, "scheduled_tick": r.scheduled_tick, "applied": True}
        if not self.chain.confirm(r.tx_id, r.scheduled_tick):
            raise HouseError(f"the signature tx {r.tx_id[:8]}… was not included in tick {r.scheduled_tick}; try again")
        return plan | {"tick": r.scheduled_tick}

    def tx_index(self) -> dict[str, dict]:
        """tx_id -> {round_id, kind, identity?, verdict?, payout_kind?} from the
        round dirs. This is what saves the 131 legacy PUBLISH/LOBBY frames that
        no longer decode: we still hold the authoritative record of what we sent,
        so there is nothing to guess. It also hands every fighter message its
        verdict for free, without re-evaluating anything."""
        idx = {}
        for rid in self.round_ids():
            meta = _read(self._rpath(rid, "meta.json")) or {}
            for key, kind in (("publish_tx", "PUBLISH"), ("lobby_tx", "LOBBY")):
                if meta.get(key):
                    idx[meta[key]] = {"round_id": rid, "kind": kind}
            doc = _read(self._rpath(rid, "settlement.json"))
            if not doc:
                continue
            if doc.get("settle_tx"):
                idx[doc["settle_tx"]] = {"round_id": rid, "kind": "SETTLE"}
            for e in doc.get("entries", []):
                for key, kind in (("enter_tx", "ENTER"), ("commit_tx", "COMMIT"), ("reveal_tx", "REVEAL")):
                    if e.get(key):
                        idx[e[key]] = {"round_id": rid, "kind": kind, "identity": e["identity"],
                                       "verdict": e.get("verdict")}
            for p in doc.get("payouts", []):
                if p.get("tx"):
                    idx[p["tx"]] = {"round_id": rid, "kind": events.KIND_PAYOUT,
                                    "identity": p.get("identity"), "payout_kind": p.get("kind")}
        return idx

    def payout_events(self) -> list[dict]:
        """Every payout the house made, with its round. These are outbound and so
        appear nowhere in observed.jsonl, which only holds what arrived."""
        out = []
        for rid in self.round_ids():
            doc = _read(self._rpath(rid, "settlement.json")) or {}
            for p in doc.get("payouts", []):
                out.append({**p, "round_id": rid})
        return out

    def _export_events(self, out_dir, now, foreign="count") -> int:
        """Sharded ticks/<tick // 1000>.json plus ticks/index.json, both fetched
        lazily by the page. Never part of the 10 s poll set: ~4,000 records is
        far too much to re-stringify every poll for a screen most visitors never
        open."""
        d = os.path.join(out_dir, "ticks")
        os.makedirs(d, exist_ok=True)
        names = {i: b["name"] for i, b in self.bows().items()}
        metas, riddles = {}, {}
        for rid in self.round_ids():
            metas[rid] = _read(self._rpath(rid, "meta.json")) or {}
            riddles[rid] = _read(self._rpath(rid, "riddle.json")) or {}
        recs = events.build(self.observed(), self.identity, self.tx_index(), self.payout_events(),
                            names, metas, riddles, foreign=foreign)
        shards = events.bucketize(recs)
        for b, s in shards.items():
            _write_if_changed(os.path.join(d, f"{b}.json"), s, compact=True)
        _write_if_changed(os.path.join(d, "index.json"), events.index_doc(shards, now), compact=True)
        return len(recs)

    def export(self, out_dir: str, now_tick: int | None = None, events_out: bool = True,
               foreign: str = "count") -> dict:
        """Write board.json and history.json (docs/protocol.md, apps/web)."""
        os.makedirs(out_dir, exist_ok=True)
        os.makedirs(os.path.join(out_dir, "rounds"), exist_ok=True)
        os.makedirs(os.path.join(out_dir, "settlements"), exist_ok=True)
        st = self.state()
        now = now_tick if now_tick is not None else st["scanned_to"]
        bows = self.bows()
        belts = B.public(self.belts())
        fighters: dict[str, dict] = {}

        def fighter(idn):
            return fighters.setdefault(idn, {"identity": idn, "name": bows.get(idn, {}).get("name"),
                                             "bow_tick": bows.get(idn, {}).get("bow_tick"),
                                             "belt": belts.get(idn, {}).get("belt", "white"),
                                             "rank": belts.get(idn, {}).get("rank", 0),
                                             "points": belts.get(idn, {}).get("points", 0),
                                             "rounds_played": 0, "solved": 0, "wins": 0, "earned": 0, "staked": 0,
                                             "net": 0, "strikes": 0, "solve_ticks": [], "by_belt": {},
                                             "belt_history": [], "streak": 0, "best_streak": 0, "losses": 0})

        rounds, open_rounds = [], []
        for rid in self.round_ids():
            meta = self.meta(rid)
            if meta["status"] in ("lobby_opening", "failed") or (meta["status"] == "publishing" and meta.get("lobby_tick") is None):
                continue
            spec = self.spec(rid)
            published = meta["publish_tick"] is not None
            rpub = _read(self._rpath(rid, "riddle.json")) if published else None
            if published:
                _write(os.path.join(out_dir, "rounds", f"{rid}.json"), rpub)
            settled = meta["status"] in ("settled", "void")
            state = meta["status"] if settled else ("lobby" if not published else spec.state_at(now))
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
                                "enter_tick": e.get("enter_tick"), "enter_tx": e.get("enter_tx"),
                                "sensei": bool(e.get("sensei")),
                                "answer": e["answer"] if settled else None})
                if e["verdict"] in ("winner", "solved", "wrong", "no_reveal", "no_commit", "bad_reveal", "pending"):
                    f["rounds_played"] += 1
                    f["staked"] += e["stake"] if settled else 0
                    bb = f["by_belt"].setdefault(meta.get("belt") or "open", {"rounds": 0, "solved": 0, "wins": 0, "solve_ticks": []})
                    bb["rounds"] += 1
                    if e["verdict"] in ("winner", "solved"):
                        f["solved"] += 1; bb["solved"] += 1
                        if e["commit_tick"] and meta["publish_tick"]:
                            lat = e["commit_tick"] - meta["publish_tick"]
                            f["solve_ticks"].append(lat); bb["solve_ticks"].append(lat)
                    if e["verdict"] == "winner":
                        f["wins"] += 1; bb["wins"] += 1
                        if settled:
                            f["streak"] = f["streak"] + 1 if f["streak"] >= 0 else 1
                            f["best_streak"] = max(f["best_streak"], f["streak"])
                    elif settled and e["verdict"] in ("wrong", "no_reveal", "no_commit", "bad_reveal"):
                        f["losses"] += 1
                        f["streak"] = f["streak"] - 1 if f["streak"] <= 0 else -1
                if doc:
                    for c in doc.get("belt_changes", []):
                        if c["identity"] == e["identity"]:
                            f["belt_history"].append({"round_id": rid, "from": B.belt_name(c["before"]),
                                                      "to": B.belt_name(c["after"]), "reason": c["reason"]})
            strikes = doc["strikes"] if doc else ev.strikes
            for idn, reasons in strikes.items():
                fighter(idn)["strikes"] += len(reasons)
            settlement = None
            if doc and doc.get("void"):
                settlement = dict(doc)  # exactly the hashed document, like a settled round
            elif doc:
                for p in doc["payouts"]:
                    if p["kind"] in ("win", "bond_release") and p["confirmed"]:
                        fighter(p["identity"])["earned"] += p["amount"]
                settlement = dict(doc)  # exactly the hashed document, so the page can re-verify it
            rd = {"round_id": rid, "title": rpub["title"] if rpub else f"{meta.get('belt') or 'open'} belt: at the table",
                  "state": state, "publish_tick": meta["publish_tick"],
                  "lobby_tick": meta.get("lobby_tick"), "lobby_window": meta.get("lobby_window", 0),
                  "min_players": meta.get("min_players", 0), "belt": meta.get("belt", ""),
                  "entrants": _seats(entries),
                  "publish_tx": meta["publish_tx"], "commit_window": meta["commit_window"],
                  "reveal_window": meta["reveal_window"], "entry_fee": meta["entry_fee"],
                  "fee_policy": meta.get("fee_policy"),
                  "house_seed": meta["house_seed"], "rake_bps": meta["rake_bps"],
                  "payout_mode": meta.get("payout_mode", "split"), "match_bps": meta.get("match_bps", 0),
                  "bond_bps": meta.get("bond_bps", 0), "bond_rounds": meta.get("bond_rounds", 0),
                  "sensei": bool(meta.get("sensei", False)),
                  "rake_house_bps": meta.get("rake_house_bps", 10000), "rake_dev_bps": meta.get("rake_dev_bps", 0),
                  "rake_share_bps": meta.get("rake_share_bps", 0),
                  "carry_in": meta.get("carry_in", 0), "riddle_hash": meta["riddle_hash"] if published else None,
                  "answer_commitment": meta["answer_commitment"] if published else None, "riddle": rpub,
                  "entries": entries, "settlement": settlement}
            rounds.append(rd)
            if state in ("lobby", "commit", "reveal"):
                open_rounds.append({k: v for k, v in rd.items() if k != "entries"})
        for idn in bows:
            fighter(idn)

        def avg(xs):
            return round(sum(xs) / len(xs), 1) if xs else None
        for f in fighters.values():
            f["net"] = f["earned"] - f["staked"]
            f["avg_solve_ticks"], f["best_solve_ticks"] = avg(f["solve_ticks"]), (min(f["solve_ticks"]) if f["solve_ticks"] else None)
            f["solve_rate"] = round(f["solved"] / f["rounds_played"], 2) if f["rounds_played"] else None
            f["win_rate"] = round(f["wins"] / f["rounds_played"], 2) if f["rounds_played"] else None
            f["win_loss"] = round(f["wins"] / f["losses"], 2) if f["losses"] else (float(f["wins"]) if f["wins"] else None)
            del f["solve_ticks"]
            for bb in f["by_belt"].values():
                bb["avg_solve_ticks"] = avg(bb["solve_ticks"]); del bb["solve_ticks"]
            f["belt_history"] = sorted(f["belt_history"], key=lambda c: c["round_id"])
        _write(os.path.join(out_dir, "fighters.json"), {"generated_tick": now, "fighters": sorted(
            fighters.values(), key=lambda f: (-f["net"], -f["wins"], f["identity"]))})
        _write(os.path.join(out_dir, "bonds.json"), {"generated_tick": now, "expiry_rounds": BOND_EXPIRY_ROUNDS,
                                                       "bonds": self.bonds()})
        _write(os.path.join(out_dir, "belts.json"), {"generated_tick": now, "ladder": list(B.BELTS), "rules": {
            "promote_at": B.PROMOTE_AT, "demote_at": B.DEMOTE_AT, "winner": 2, "solved": 1, "failure": -1,
            "win_above_belt": "promoted to that belt", "failure_above_belt": 0, "enter": "own belt or above"},
            "belts": belts})
        history = {"house": self.identity, "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                   "generated_tick": now, "rounds": rounds, "belts": belts,
                   "fighters": sorted(fighters.values(), key=lambda f: (-f["earned"], -f["wins"], f["identity"]))}
        board = {"house": self.identity, "generated_tick": now, "rounds": open_rounds, "belts": belts}
        _write(os.path.join(out_dir, "history.json"), history)
        _write(os.path.join(out_dir, "board.json"), board)
        if events_out:
            # A broken tick export must never take down history.json.
            try:
                self._export_events(out_dir, now, foreign)
            except (OSError, ValueError, KeyError) as e:
                print(f"qdojo: tick export skipped: {e}")
        return history
