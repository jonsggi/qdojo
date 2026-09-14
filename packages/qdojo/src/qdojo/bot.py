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
            r = R.from_public(rd["riddle"])
            if r.hash().hex() != rd["riddle_hash"]:
                actions.append(f"round {rid}: riddle hash mismatch, ignoring")
                continue
            commit_end = rd["publish_tick"] + rd["commit_window"]
            reveal_end = commit_end + rd["reveal_window"]
            st = self.rounds.get(rid)
            if st is None:
                if now > commit_end:
                    continue  # too late to enter
                if self.max_stake is not None and rd["entry_fee"] > self.max_stake:
                    actions.append(f"round {rid}: entry fee {rd['entry_fee']} above max stake, skipping")
                    self.rounds[rid] = {"skipped": True}
                    self._save()
                    continue
                try:
                    canon = run_solver(self.solver_cmd, r.public(), self.solver_timeout)
                except SolverError as e:
                    actions.append(f"round {rid}: solver failed: {e}")
                    continue
                salt = secrets.token_bytes(hashing.SALT_LEN)
                c = hashing.player_commitment(r.round_id, self.chain.identity, salt, canon)
                # record BEFORE sending so a crash mid-send cannot lead to a second commit
                self.rounds[rid] = {"answer": canon, "salt": salt.hex(), "commit_tx": None, "reveal_tx": None,
                                    "commit_end": commit_end, "reveal_end": reveal_end}
                self._save()
                res = self.chain.send(self.house, rd["entry_fee"], payload.encode(payload.Commit(r.round_id, c)),
                                      payload.INPUT_TYPE)
                self.rounds[rid].update(commit_tx=res.tx_id, commit_tick=res.scheduled_tick)
                self._save()
                actions.append(f"round {rid}: committed {res.tx_id[:8]}… for tick {res.scheduled_tick}")
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
        return actions
