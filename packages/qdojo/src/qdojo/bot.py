"""A player's bot: read the board, solve, commit, reveal. State on disk so a
restart never double-commits."""
import json
import os
import secrets
import urllib.request

from . import hashing, payload, riddle as R
from .solver import run_solver, SolverError
from .chain.base import Unknown, ChainError


class BotError(Exception):
    pass


MAX_SOLVER_ATTEMPTS = 2   # a solver that fails twice on a riddle is not asked again this round
MAX_COMMIT_SENDS = 3      # a commit that did not land is resent while the window is open


def fetch_board(source: str) -> dict:
    if source.startswith("http://") or source.startswith("https://"):
        req = urllib.request.Request(source, headers={"User-Agent": "qdojo-bot/0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode("utf-8"))
    with open(source, encoding="utf-8") as f:
        return json.load(f)


class Bot:
    def __init__(self, chain, state_dir: str, solver_cmd: list[str], name: str | None = None,
                 max_stake: int | None = None, solver_timeout: float = 60.0):
        self.chain, self.state_dir, self.solver_cmd = chain, state_dir, solver_cmd
        self.name, self.max_stake, self.solver_timeout = name, max_stake, solver_timeout
        os.makedirs(state_dir, mode=0o700, exist_ok=True)
        self.path = os.path.join(state_dir, "rounds.json")
        self.rounds = self._load()

    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return {}

    def _save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.rounds, f, indent=2, sort_keys=True)
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.path)

    def _can_pay(self, stake: int, actions: list, rid: str) -> bool:
        """A transaction from an identity that cannot cover it is dropped by the
        node, and an identity at zero cannot send at all. Say so instead."""
        try:
            bal = self.chain.balance(self.chain.identity)
        except Unknown as e:
            actions.append(f"round {rid}: balance unknown ({e}), not sending"); return False
        if bal < stake or bal == 0:
            actions.append(f"round {rid}: broke: balance {bal} < stake {stake}, sitting out"); return False
        return True

    def chain_offset(self) -> int:
        return getattr(self.chain, "schedule_offset", 20)

    def _send_commit(self, rid: str, round_id: int, fee: int, commitment: bytes) -> str:
        res = self.chain.send(self.house, fee, payload.encode(payload.Commit(round_id, commitment)), payload.INPUT_TYPE)
        st = self.rounds[rid]
        st.update(commit_tx=res.tx_id, commit_tick=res.scheduled_tick, commit_sends=st.get("commit_sends", 0) + 1)
        self._save()
        return f"round {rid}: committed {res.tx_id[:8]}… for tick {res.scheduled_tick}"

    def bow(self) -> str:
        if not self.name:
            raise BotError("no name to bow with")
        marker = os.path.join(self.state_dir, "bowed")
        if os.path.exists(marker):
            return open(marker).read().strip()
        res = self.chain.send(self.house, 0, payload.encode(payload.Bow(self.name)), payload.INPUT_TYPE)
        with open(marker, "w") as f:
            f.write(res.tx_id)
        return res.tx_id

    def step(self, board: dict, now_tick: int | None = None) -> list[str]:
        """One pass over the board. Returns human-readable actions taken."""
        self.house = board["house"]
        if not hashing.is_identity(self.house):
            raise BotError("board has no valid house identity")
        now = now_tick if now_tick is not None else self.chain.current_tick()
        actions = []
        for rd in board.get("rounds", []):
            rid = str(rd["round_id"])
            st = self.rounds.get(rid)
            lobby = rd.get("lobby_tick") is not None
            if lobby and rd.get("publish_tick") is None:
                # The table is open: buy the seat now, the riddle comes later.
                if st is not None and (st.get("entered") or st.get("skipped")):
                    continue
                if now > rd["lobby_tick"] + rd["lobby_window"]:
                    continue
                if self.max_stake is not None and rd["entry_fee"] > self.max_stake:
                    self.rounds[rid] = {"skipped": True}; self._save()
                    actions.append(f"round {rid}: entry fee {rd['entry_fee']} above max stake, not entering")
                    continue
                if not self._can_pay(rd["entry_fee"], actions, rid):
                    continue
                self.rounds[rid] = {"entered": True, "enter_tx": None}
                self._save()
                res = self.chain.send(self.house, rd["entry_fee"], payload.encode(payload.Enter(rd["round_id"])),
                                      payload.INPUT_TYPE)
                self.rounds[rid].update(enter_tx=res.tx_id, enter_tick=res.scheduled_tick, stake=rd["entry_fee"])
                self._save()
                actions.append(f"round {rid}: entered the lobby {res.tx_id[:8]}… for tick {res.scheduled_tick}, stake {rd['entry_fee']}")
                continue
            if rd.get("riddle") is None:
                continue
            r = R.from_public(rd["riddle"])
            if r.hash().hex() != rd["riddle_hash"]:
                actions.append(f"round {rid}: riddle hash mismatch, ignoring")
                continue
            commit_end = rd["publish_tick"] + rd["commit_window"]
            reveal_end = commit_end + rd["reveal_window"]
            if lobby:
                if st is None or not st.get("entered"):
                    continue  # we never bought a seat; a commit now would only be a strike
                if "answer" not in st and not st.get("solver_failures"):
                    st = None  # fall into the solve-and-commit path below, keeping the lobby record
            stake = 0 if lobby else rd["entry_fee"]
            if st is None or ("answer" not in st and not st.get("skipped") and st.get("commit_tx") is None and not st.get("dead")):
                if now > commit_end:
                    continue  # too late to enter
                if self.max_stake is not None and rd["entry_fee"] > self.max_stake:
                    actions.append(f"round {rid}: entry fee {rd['entry_fee']} above max stake, skipping")
                    self.rounds[rid] = {"skipped": True}
                    self._save()
                    continue
                failures = (st or {}).get("solver_failures", 0)
                if failures >= MAX_SOLVER_ATTEMPTS:
                    continue
                if not self._can_pay(stake, actions, rid):
                    continue
                keep = {k: v for k, v in (self.rounds.get(rid) or {}).items() if k in ("entered", "enter_tx", "enter_tick", "stake")}
                try:
                    canon = run_solver(self.solver_cmd, r.public(), self.solver_timeout)
                except SolverError as e:
                    self.rounds[rid] = {**keep, "solver_failures": failures + 1}
                    self._save()
                    actions.append(f"round {rid}: solver failed ({failures + 1}/{MAX_SOLVER_ATTEMPTS}): {e}")
                    continue
                salt = secrets.token_bytes(hashing.SALT_LEN)
                c = hashing.player_commitment(r.round_id, self.chain.identity, salt, canon)
                # record BEFORE sending so a crash mid-send cannot lead to a second commit
                self.rounds[rid] = {**keep, "answer": canon, "salt": salt.hex(), "commit_tx": None, "reveal_tx": None,
                                    "commit_end": commit_end, "reveal_end": reveal_end, "commit_sends": 0}
                self._save()
                actions.append(self._send_commit(rid, r.round_id, stake, c))
            elif st.get("skipped"):
                continue
            elif st.get("commit_tx") is None:
                actions.append(f"round {rid}: a commit was started but never recorded as sent; not retrying automatically")
            elif st.get("reveal_tx") is None and commit_end < now <= reveal_end:
                # Only reveal if our commit is actually on chain; otherwise the reveal is a strike.
                try:
                    landed = self.chain.confirm(st["commit_tx"], st["commit_tick"])
                except Unknown:
                    actions.append(f"round {rid}: commit not yet decidable")
                    continue
                if not landed:
                    self.rounds[rid]["dead"] = True
                    self._save()
                    actions.append(f"round {rid}: commit never landed, sitting this one out")
                    continue
                msg = payload.Reveal(r.round_id, bytes.fromhex(st["salt"]), st["answer"])
                res = self.chain.send(self.house, 0, payload.encode(msg), payload.INPUT_TYPE)
                self.rounds[rid].update(reveal_tx=res.tx_id, reveal_tick=res.scheduled_tick)
                self._save()
                actions.append(f"round {rid}: revealed {res.tx_id[:8]}… for tick {res.scheduled_tick}")
            elif st.get("reveal_tx") is None and now <= commit_end and not st.get("dead"):
                # Commit window still open: make sure the commit actually landed, resend if it did not.
                if now < st["commit_tick"] + 2:
                    continue
                try:
                    landed = self.chain.confirm(st["commit_tx"], st["commit_tick"])
                except Unknown:
                    continue
                if landed or st.get("commit_sends", 1) >= MAX_COMMIT_SENDS:
                    if not landed:
                        self.rounds[rid]["dead"] = True; self._save()
                        actions.append(f"round {rid}: commit lost {MAX_COMMIT_SENDS} times, sitting this one out")
                    continue
                if now + self.chain_offset() + 2 > commit_end:
                    continue
                c = hashing.player_commitment(r.round_id, self.chain.identity, bytes.fromhex(st["salt"]), st["answer"])
                actions.append(f"round {rid}: commit {st['commit_tx'][:8]}… not in tick {st['commit_tick']}, resending")
                actions.append(self._send_commit(rid, r.round_id, stake, c))
        return actions
