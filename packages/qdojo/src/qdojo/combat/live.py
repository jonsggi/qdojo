"""The live demo arena: a devnet on a simulated chain, demo bots, events, export.

What it runs, all simulated, never a real network or real funds:
- the reference contract on `SimChain`: transaction latency, drops, reordering,
  execution fees burned from a reserve the operator tops up;
- fighter NFTs from `AssetRegistry`, including founding fighters and a small
  market that occasionally sells an idle fighter to a new collector;
- demo bots: code policies and, optionally, LLM planners with daily caps;
- scheduled cups, occasional duel challenges, ranked play, rolling seasons;
- a public export for the spectator site.

State: the devnet journal, plus assets.json and chain.json next to it, so a
restart resumes. The chain's in-flight transactions are not persisted; bots
simply resend.

  qdojo combat live --lineup lineup.json --profile demo --tick-seconds 1.5 --export DIR
"""
from __future__ import annotations

import json
import os
import random
import secrets
import shlex
import signal
import sys
import time
from pathlib import Path

from . import evaluate as E
from . import export, join
from .bot import Bot, Budget, planner_chooser, policy_chooser
from .chainsim import Asset, AssetRegistry, FeeModel, SimChain, SimQubicClient
from .codec import Op
from .devnet import Devnet, DevnetClient, roles
from .rules import candidate_1
from .sim import identity
from ..hashing import sha256

# Ranked bots are rarely idle, so the duel specialists skip ranked play: they
# fight challenges and are the fighters a collector can buy between duels.
DEFAULT_LINEUP = [
    {"label": "tanuki", "policy": "reader-v1", "cups": True},
    {"label": "kappa", "policy": "search-v1", "cups": True},
    {"label": "tengu", "policy": "scout-v1", "duels": True, "ranked": False},
    {"label": "oni", "policy": "script-vs-scout-v1", "cups": True},
    {"label": "kitsune", "policy": "mixed-v1", "cups": True},
    {"label": "baku", "policy": "repeat-last-winner", "duels": True, "ranked": False},
    {"label": "raiju", "policy": "kicker-v1", "cups": True},
    {"label": "kirin", "policy": "jabber-v1", "duels": True, "ranked": False},
]

DEPLOYMENT = {"kind": "devnet", "currency": "fake QU", "identities": "synthetic", "chain": "simulated",
              "bots": "operator-run demo bots", "note": "not a Qubic deployment; nothing here is real money"}

ISSUER_LABEL = "qdojo-sim-issuer"
RESERVE_FLOOR, RESERVE_TOPUP = 20_000, 200_000


# A demo bot stops paid entry after this many faults (missed commits/reveals)
# within one epoch's worth of ticks, then resumes by itself once they age out.
# It matches the contract's own ranked suspension (faults_per_epoch = 3), so a
# bot that keeps faulting sits out instead of donating stakes and spamming
# rejected entries; one stray timeout never benches it. A lineup entry may set
# "stop_after_faults" and "fault_window_ticks" itself.
DEMO_STOP_AFTER_FAULTS = 3


def _budget(rules, entry, epoch_ticks: int = 2400) -> Budget:
    stake = int(entry.get("max_stake", 5000))
    return Budget(ruleset_digest=rules.digest.hex(), max_stake=stake, max_total_escrow=4 * stake,
                  max_fights_per_day=100_000, max_daily_committed=10**12, max_daily_net_loss=10**12,
                  stop_after_faults=int(entry.get("stop_after_faults", DEMO_STOP_AFTER_FAULTS)),
                  fault_window_ticks=int(entry.get("fault_window_ticks", epoch_ticks)),
                  min_ticks_between_fights=int(entry.get("min_ticks_between_fights", 0)))


class Arena:
    def __init__(self, directory: Path, lineup: list[dict], profile: str = "demo", seed: int | None = None,
                 latency=(1, 3), drop_rate: float = 0.02, fees: FeeModel | None = FeeModel(),
                 cup_every: int = 1800, duel_every: int = 300, market_every: int = 2400, log=print,
                 deterministic: bool = False, join_inbox: Path | None = None):
        self.dir = Path(directory)
        # Samples and tests only: derive policy seeds and salts from the seed.
        # A live arena keeps secrets-based salts, as a real bot must.
        self.deterministic = deterministic
        self.log = log
        self.net = Devnet(self.dir, profile)
        self.w = self.net.world
        self.rules = candidate_1()
        state = self._load("chain.json", {"reserve": 0, "burned": 0, "funded": 0, "seed": seed or secrets.randbits(32),
                                          "collectors": 0})
        self.state = state
        self.chain = SimChain(self.w, seed=state["seed"] ^ self.w.tick, latency=latency, drop_rate=drop_rate,
                              fees=fees, reserve=state["reserve"] if fees else None)
        self.chain.burned = state["burned"]
        self.rng = random.Random(state["seed"] ^ (self.w.tick * 7919))
        self.registry = AssetRegistry(self.w, identity(ISSUER_LABEL))
        for fid_hex, a in self._load("assets.json", {}).items():
            self.registry.assets[bytes.fromhex(fid_hex)] = Asset(
                bytes.fromhex(fid_hex), bytes.fromhex(a["issuer"]), a["name"], a["founding"],
                [(t, bytes.fromhex(f) if f else None, bytes.fromhex(to)) for t, f, to in a["history"]])
        self.labels: dict[bytes, dict] = {}
        self.bots: dict[bytes, Bot] = {}
        self.cup_every, self.duel_every, self.market_every = cup_every, duel_every, market_every
        admin = roles()["admin"]
        for entry in lineup:
            fid = self._fighter_for(entry, admin)
            self.labels[fid] = entry
            self._make_bot(fid)
        # Outside builders' fighters (join.py): labelled and disclosed, never run by a house bot.
        for entry in join.load_outside(self.dir):
            self.labels[bytes.fromhex(entry["fighter_id"])] = entry
        self.inbox = join.ArenaInbox(join_inbox) if join_inbox else None
        self.save()

    # -- persistence --------------------------------------------------------

    def _load(self, name, default):
        p = self.dir / name
        try:
            return json.loads(p.read_text())
        except (OSError, ValueError):
            return default

    def _dump(self, name, doc):
        p = self.dir / name
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(doc))
        os.replace(tmp, p)

    def save(self):
        self.net.save()
        self.state.update(reserve=self.chain.reserve or 0, burned=self.chain.burned)
        self._dump("chain.json", self.state)
        self._dump("assets.json", {fid.hex(): {"issuer": a.issuer.hex(), "name": a.name, "founding": a.founding,
                                               "history": [[t, f.hex() if f else None, to.hex()]
                                                           for t, f, to in a.history]}
                                   for fid, a in self.registry.assets.items()})

    # -- fighters and bots --------------------------------------------------

    def _fighter_for(self, entry, admin) -> bytes:
        fid = self.registry.id_for(entry["label"])
        if fid not in self.registry.assets:
            owner = identity("demo-owner:" + entry["label"])
            self.registry.issue(entry["label"], owner, founding=bool(entry.get("founding")))
        owner = self.registry.assets[fid].owner
        if self.w.balances.get(owner, 0) < 10**9:
            self.w.mint(owner, 10**12)
        c = self.w.contract
        if fid not in c.fighters:
            self.w.send(admin, Op.ADMIN_REGISTER_ASSET, fighter_id=fid, registry_version=1, house_npc=0)
            self.w.send(owner, Op.REGISTER_FIGHTER, fighter_id=fid, registry_version=1)
        return fid

    def _chooser(self, entry):
        if "llm" in entry:
            llm = entry["llm"]
            cmd = [sys.executable, "-m", "qdojo.combat.llm_planner", "--model", llm["model"],
                   "--state", str(self.dir / "llm" / entry["label"]), "--daily-usd", str(llm.get("daily_usd", 1.0))]
            for key in ("prompt", "reasoning", "max_tokens", "timeout"):
                if key in llm:
                    cmd += ["--" + key.replace("_", "-"), str(llm[key])]
            return planner_chooser(cmd, int(llm.get("budget_ms", 25000)), log=self._bot_log(entry["label"]))
        if "planner" in entry:
            return planner_chooser(shlex.split(entry["planner"]), int(entry.get("budget_ms", 1500)),
                                   log=self._bot_log(entry["label"]))
        seed = (sha256(b"qdojo/arena-policy/v1\0", str(self.state["seed"]).encode(), entry["label"].encode())
                if self.deterministic else secrets.token_bytes(32))
        return policy_chooser(self.rules, E.policy_by_name(entry["policy"]), seed)

    def _bot_log(self, label: str):
        return lambda m: self.log(f"tick {self.w.tick}: bot {label}: {m}")

    def _make_bot(self, fid: bytes):
        entry = self.labels[fid]
        owner = self.registry.assets[fid].owner
        client = SimQubicClient(self.chain, owner, DevnetClient(self.net, owner))
        label = entry["label"]
        bot = Bot(client, self.rules, fid, owner, owner, self._chooser(entry),
                  _budget(self.rules, entry, self.net.m.ticks_per_epoch),
                  self.dir / "bots" / label / owner.hex()[:12],
                  log=self._bot_log(label))
        bot.play_cups = bool(entry.get("cups"))
        bot.accept_duels = bool(entry.get("duels"))
        bot.ranked = entry.get("ranked", True)
        if self.deterministic:
            counter = {"n": 0}

            def salt(k, label=entry["label"], owner=owner):
                counter["n"] += 1
                return sha256(b"qdojo/sample-salt/v1\0", label.encode(), owner, counter["n"].to_bytes(8, "little"))[:k]
            bot.salt_source = salt
        self.bots[fid] = bot

    # -- events -------------------------------------------------------------

    def _maybe_cup(self):
        c = self.w.contract
        if any(k.status in ("REGISTRATION", "RUNNING") for k in c.cups.values()):
            return
        last = max([k.created_tick for k in c.cups.values()] + [getattr(self, "last_cup_attempt", -10**9)])
        if self.w.tick - last < self.cup_every:
            return
        admin = roles()["admin"]
        r = self.w.send(admin, Op.ADMIN_CREATE_CUP, 5000, ruleset_digest=self.rules.digest, timing_profile_id=1,
                        fee_profile_id=1, entry_fee=2000, registration_close=self.w.tick + 120, min_entrants=4,
                        max_entrants=8, level_ticks=1300, first_level_delay=40, checkin_ticks=60, replay_delay=40)
        self.last_cup_attempt = self.w.tick
        self.log(f"tick {self.w.tick}: cup {r.data.get('cup_id')} created ({r.code.name})")

    def _maybe_duel(self):
        if self.w.tick % self.duel_every:
            return
        c = self.w.contract
        idle = [f for f, b in self.bots.items() if b.accept_duels and c.fighters[f].lock == "IDLE"]
        if len(idle) < 2:
            return
        a, b = self.rng.sample(idle, 2)
        owner = self.registry.assets[a].owner
        stake = self.rng.choice([1000, 2000, 3000])
        receipt = self.chain.send(owner, Op.DUEL_OFFER, stake, fighter_id=a, auth_version=c.fighters[a].auth_version,
                                  opponent_id=b, ruleset_digest=self.rules.digest, timing_profile_id=1,
                                  fee_profile_id=1, stake=stake, format=self.rng.choice([0, 1, 1, 2]),
                                  expires_tick=self.w.tick + 200)
        del receipt
        self.log(f"tick {self.w.tick}: duel challenge {self.labels[a]['label']} -> {self.labels[b]['label']} ({stake} QU)")

    def _maybe_market(self):
        """Now and then a collector buys an idle, non-founding fighter. The bot
        keeps operating it for the new owner after they register it."""
        if self.market_every <= 0 or self.w.tick % self.market_every:
            return
        c = self.w.contract
        for_sale = [f for f in self.bots if c.fighters[f].lock == "IDLE" and not self.registry.assets[f].founding]
        if not for_sale:
            return
        fid = self.rng.choice(for_sale)
        seller = self.registry.assets[fid].owner
        self.state["collectors"] += 1
        buyer = identity(f"demo-collector:{self.state['collectors']}")
        self.w.mint(buyer, 10**12)
        self.registry.transfer(fid, seller, buyer)
        self.w.send(buyer, Op.REGISTER_FIGHTER, fighter_id=fid, registry_version=1)
        self._make_bot(fid)
        self.log(f"tick {self.w.tick}: {self.labels[fid]['label']} sold to collector #{self.state['collectors']}")

    def _reserve(self):
        if self.chain.fees is not None and (self.chain.reserve or 0) < RESERVE_FLOOR:
            self.chain.fund_reserve(RESERVE_TOPUP)
            self.state["funded"] += RESERVE_TOPUP

    # -- running ------------------------------------------------------------

    def step(self):
        for fid, b in list(self.bots.items()):
            # "reliability" < 1 models a flaky operator (slow machine, dropped
            # connection): it acts only on that share of ticks and sometimes
            # misses a deadline, which the contract turns into a forfeit.
            if self.rng.random() >= self.labels[fid].get("reliability", 1.0):
                continue
            try:
                b.step()
            except Exception as exc:               # one bot's failure must not stop the arena
                self.log(f"tick {self.w.tick}: bot {self.labels[fid]['label']} error: {exc}")
        self._maybe_cup()
        self._maybe_duel()
        self._maybe_market()
        self._reserve()
        if self.inbox:
            self.inbox.drain(self)
        self.chain.advance()
        if self.inbox:
            self.inbox.settle(self)
            self.net.save()           # remote bots read the journal-following API: keep it one tick fresh

    def deployment(self, tick_seconds: float) -> dict:
        fighters = {}
        for fid, entry in self.labels.items():
            driver = entry.get("driver") or (f"llm:{entry['llm']['model']}" if "llm" in entry else
                                             "planner" if "planner" in entry else entry.get("policy"))
            # origin: "house" (operator-run) or "outside" (registered and run by an outside builder)
            fighters[fid.hex()] = {"name": entry["label"], "driver": driver, "origin": entry.get("origin", "house"),
                                   "asset": self.registry.public(fid)}
        return {**DEPLOYMENT, "profile": self.net.profile, "tick_seconds": tick_seconds,
                "names": {f: v["name"] for f, v in fighters.items()}, "fighters": fighters,
                "chain": {"latency_ticks": list(self.chain.latency), "drop_rate": self.chain.drop_rate,
                          "execution_reserve": self.chain.reserve, "fees_burned": self.chain.burned,
                          "operator_funding": self.state["funded"], "halted_ticks": self.chain.halted_ticks},
                **({} if self.deterministic else
                   {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})}


def run(devnet_dir: Path, lineup: list[dict], export_dir: Path, tick_seconds: float = 1.5,
        export_every: int = 10, keep: int = 200, ticks: int | None = None, log=print, profile: str = "demo",
        **arena_kw):
    arena = Arena(devnet_dir, lineup, profile=profile, log=log, **arena_kw)
    stop = {"now": False}

    def _stop(*_):
        stop["now"] = True
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    done = 0
    next_at = time.monotonic()
    while not stop["now"] and (ticks is None or done < ticks):
        arena.step()
        done += 1
        if done % export_every == 0:
            arena.save()
            export.export_all(arena.w.contract, export_dir, keep=keep, deployment=arena.deployment(tick_seconds))
        next_at += tick_seconds
        delay = next_at - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        else:
            next_at = time.monotonic()
    arena.save()
    export.export_all(arena.w.contract, export_dir, keep=keep, deployment=arena.deployment(tick_seconds))
    log(f"stopped at tick {arena.w.tick}; journal saved")
    return arena


def cmd_live(a):
    lineup = json.loads(Path(a.lineup).read_text()) if a.lineup else DEFAULT_LINEUP
    devnet_dir = Path(a.devnet) if a.devnet else Path(os.environ.get(
        "QDOJO_COMBAT_HOME", os.path.expanduser("~/.qdojo/combat"))) / "arena"
    run(devnet_dir, lineup, Path(a.export), a.tick_seconds, a.export_every, a.keep, a.ticks,
        log=lambda m: print(time.strftime("%H:%M:%S"), m, flush=True), profile=a.profile,
        join_inbox=Path(a.join_inbox) if a.join_inbox else None)


def add_parser(s):
    d = s.add_parser("live", help="run the demo arena on a simulated chain and export for spectators")
    d.add_argument("--devnet", help="arena directory (default ~/.qdojo/combat/arena)")
    d.add_argument("--lineup", help="lineup JSON (default: eight demo bots)")
    d.add_argument("--profile", default="demo", choices=("demo", "dev"))
    d.add_argument("--export", default="apps/web/data/combat/v1")
    d.add_argument("--tick-seconds", type=float, default=1.5)
    d.add_argument("--export-every", type=int, default=10, help="ticks between exports")
    d.add_argument("--keep", type=int, default=200, help="fights kept in the export")
    d.add_argument("--ticks", type=int, help="stop after this many ticks (default: run until stopped)")
    d.add_argument("--join-inbox", help="ENABLE outside builders: the inbox the API's join endpoints fill "
                                        "(off by default; docs/build-a-bot.md §8)")
    d.set_defaults(fn=cmd_live)
