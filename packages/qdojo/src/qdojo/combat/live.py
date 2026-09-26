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
from . import export, invariants, store
from .bot import Bot, Budget, planner_chooser, policy_chooser
from .chainsim import Asset, AssetRegistry, FeeModel, SimChain, SimQubicClient
from .codec import Mode, Op
from .devnet import Devnet, DevnetClient, roles
from .rules import candidate_1
from .sim import identity
from .types import ATTACKS, Plan
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
EXPORT_CHECK_EVERY = 10          # exports between checks of the export against the contract
# Hot-state bounds (AUD-024): finished fights, contests and offers leave the
# contract's memory every COMPACT_EVERY ticks (store.compact); a verifiable
# state snapshot every SNAPSHOT_EVERY ticks bounds a restart to replaying the
# journal written since.
COMPACT_EVERY = 600
SNAPSHOT_EVERY = 1200




def compact(contract):
    return store.compact(contract)


RESERVE_FLOOR, RESERVE_TOPUP = 20_000, 200_000

# Event economics (AUD-018, AUD-019), in multiples of the manifest's tier-1
# stake, so an arena created with older manifest values stays consistent.
# The reasoning and measurements are in docs/economics-report.md.
EVENTS = {
    # Duel stake per fighter by series format (SINGLE, BO3, BO5): a series
    # plays more fights, and its one rake must pay for their execution.
    "duel_stake": {0: 1, 1: 2, 2: 3},
    "cup_entry": 2,                  # cup entry fee
    "cup_fee_profile": 2,            # fee profile for cup entries, when the manifest has it (else 1)
    "cup_sponsorship": 0.1,          # house sponsorship per cup...
    # ...paid only while no fighter won more than sponsor_max_wins of the last
    # sponsor_window sponsored cups: one bot cannot capture the house's money.
    "sponsor_window": 6, "sponsor_max_wins": 2,
}


# A demo bot stops paid entry after this many faults (missed commits/reveals)
# within one epoch's worth of ticks, then resumes by itself once they age out.
# It matches the contract's own ranked suspension (faults_per_epoch = 3), so a
# bot that keeps faulting sits out instead of donating stakes and spamming
# rejected entries; one stray timeout never benches it. A lineup entry may set
# "stop_after_faults" and "fault_window_ticks" itself.
DEMO_STOP_AFTER_FAULTS = 3


def stub_chooser(rules, name: str, seed: bytes):
    """In-process stand-ins for LLM planners, for soaks and tests (a lineup
    entry's "stub"). "power-reuse" plays mixed-v1 but claims the power strike
    on its first attack every round, even after it was spent: the planner bug
    behind the 2026-09-25 forfeits. The bot's plan check must strip it.
    Any other name is a policy name."""
    if name == "power-reuse":
        base = policy_chooser(rules, E.policy_by_name("mixed-v1"), seed)

        def choose(obs):
            plan = base(obs)
            slot = next((i for i, a in enumerate(plan.actions) if a in ATTACKS), None)
            return plan if slot is None else Plan(plan.actions, slot)
        return choose
    return policy_chooser(rules, E.policy_by_name(name), seed)


# Demo bots' duel accept filters (AUD-019): decline a challenger rated more
# than DUEL_MAX_RATING_GAP above them, and one they have lost to in most of
# their last series (history-aware: at least DUEL_H2H_SERIES series, series
# score below DUEL_H2H_MIN_SCORE). Lineup entries may override each.
DUEL_MAX_RATING_GAP, DUEL_H2H_SERIES, DUEL_H2H_MIN_SCORE = 200, 3, 0.34


def _budget(rules, entry, epoch_ticks: int = 2400, tier_stake: int = 1000) -> Budget:
    stake = int(entry.get("max_stake", max(5000, 3 * tier_stake)))
    return Budget(ruleset_digest=rules.digest.hex(), max_stake=stake, max_total_escrow=4 * stake,
                  max_fights_per_day=100_000, max_daily_committed=10**12, max_daily_net_loss=10**12,
                  stop_after_faults=int(entry.get("stop_after_faults", DEMO_STOP_AFTER_FAULTS)),
                  fault_window_ticks=int(entry.get("fault_window_ticks", epoch_ticks)),
                  min_ticks_between_fights=int(entry.get("min_ticks_between_fights", 0)),
                  duel_max_stake=int(entry.get("duel_max_stake", stake)),
                  duel_max_rating_gap=int(entry.get("duel_max_rating_gap", DUEL_MAX_RATING_GAP)),
                  duel_h2h_series=int(entry.get("duel_h2h_series", DUEL_H2H_SERIES)),
                  duel_h2h_min_score=float(entry.get("duel_h2h_min_score", DUEL_H2H_MIN_SCORE)))


class Market:
    """A simulated secondary market for fighter NFTs (AUD-023), priced.

    Every `every` ticks: owners of non-founding fighters may list them with an
    ask above the fighter's value; unsold asks come down a little; a collector
    arrives with a bid around the value of the listing that looks cheapest,
    and buys when the bid meets the ask. The transfer completes the first tick
    the fighter is idle (not queued or fighting). The buyer pays the ask, the
    seller receives it less a market fee (FEE_BPS), which goes to the house.
    Payments move external fake QU and are journalled ("xfer"), so balances
    replay. The value model is deliberately simple and public: rating, record
    and experience. It shows what a market would show (asks, sales, prices),
    not real demand."""

    FEE_BPS = 250
    LIST_P, BUYERS = 0.25, 2

    def __init__(self, arena, doc: dict | None):
        self.a = arena
        doc = doc or {}
        self.listings: dict[str, dict] = doc.get("listings", {})
        self.sales: list[dict] = doc.get("sales", [])

    def value(self, fid: bytes) -> int:
        """Rating doubles the value every 250 points; a winning record and
        experience add to it. In fake QU, scaled to the tier-1 stake."""
        f = self.a.w.contract.fighters[fid]
        r = f.record
        fights = r["W"] + r["D"] + r["L"] + r["FW"] + r["FL"]
        score = (r["W"] + r["FW"] + r["D"] / 2 + 5) / (fights + 10)
        experience = 0.8 + 0.4 * min(1.0, fights / 50)
        return int(20 * self.a.tier_stake * 2 ** ((f.lifetime - 1000) / 250) * (0.5 + score) * experience)

    def step(self):
        a, rng = self.a, self.a.rng
        sellable = {f.hex(): f for f in a.bots if not a.registry.assets[f].founding}
        for hx in list(self.listings):
            if hx not in sellable or self.listings[hx]["seller"] != a.registry.assets[sellable[hx]].owner.hex():
                del self.listings[hx]                   # changed hands: withdrawn
                continue
            lst = self.listings[hx]
            if "buyer_bid" not in lst:
                lst["ask"] = max(int(0.85 * self.value(sellable[hx])), int(lst["ask"] * 0.95))
        for hx, fid in sellable.items():
            if hx not in self.listings and rng.random() < self.LIST_P:
                self.listings[hx] = {"ask": int(self.value(fid) * rng.uniform(1.05, 1.5)), "since": a.w.tick,
                                     "seller": a.registry.assets[fid].owner.hex()}
        for _ in range(self.BUYERS):
            open_ = [h for h in self.listings if "buyer_bid" not in self.listings[h]]
            if not open_:
                break
            hx = min(open_, key=lambda h: self.listings[h]["ask"] / max(1, self.value(sellable[h])))
            bid = int(self.value(sellable[hx]) * rng.uniform(0.8, 1.15))
            if bid >= self.listings[hx]["ask"]:
                self.listings[hx]["buyer_bid"] = bid    # agreed: settles when the fighter is next idle
        self.settle()

    def settle(self):
        """Complete agreed sales whose fighter is idle (a transfer needs an idle fighter)."""
        a, c = self.a, self.a.w.contract
        for hx in [h for h, x in self.listings.items() if "buyer_bid" in x]:
            fid = bytes.fromhex(hx)
            if c.fighters[fid].lock == "IDLE":
                lst = self.listings.pop(hx)
                self._sell(fid, lst["ask"], lst["buyer_bid"])

    def _sell(self, fid: bytes, price: int, bid: int):
        a = self.a
        seller = a.registry.assets[fid].owner
        a.state["collectors"] += 1
        buyer = identity(f"demo-collector:{a.state['collectors']}")
        a.w.mint(buyer, 10**12)
        fee = price * self.FEE_BPS // 10_000
        a.net.transfer_external(buyer, seller, price - fee)
        a.net.transfer_external(buyer, roles()["house"], fee)
        a.registry.transfer(fid, seller, buyer)
        a.w.send(buyer, Op.REGISTER_FIGHTER, fighter_id=fid, registry_version=1)
        a._make_bot(fid)
        f = a.w.contract.fighters[fid]
        self.sales.append({"tick": a.w.tick, "fighter_id": fid.hex(), "seller": seller.hex(), "buyer": buyer.hex(),
                           "price": price, "fee": fee, "bid": bid, "rating": f.lifetime, "record": dict(f.record)})
        a.log(f"tick {a.w.tick}: {a.labels[fid]['label']} sold to collector #{a.state['collectors']} for {price} QU")

    def fees_collected(self) -> int:
        return sum(x["fee"] for x in self.sales)

    def summary(self) -> dict:
        prices = [x["price"] for x in self.sales]
        return {"sales": len(prices), "volume": sum(prices), "fees": self.fees_collected(),
                "median_price": sorted(prices)[len(prices) // 2] if prices else None,
                "min_price": min(prices) if prices else None, "max_price": max(prices) if prices else None,
                "listings": len(self.listings)}

    def doc(self) -> dict:
        names = {f.hex(): e["label"] for f, e in self.a.labels.items()}
        c = self.a.w.contract
        listings = [{"fighter_id": hx, "name": names.get(hx), "ask": str(x["ask"]), "since_tick": str(x["since"]),
                     "seller": x["seller"], "value": str(self.value(bytes.fromhex(hx))), "sold": "buyer_bid" in x,
                     "rating": c.fighters[bytes.fromhex(hx)].lifetime}
                    for hx, x in sorted(self.listings.items(), key=lambda kv: int(kv[1]["ask"]))]
        sales = [{**x, "name": names.get(x["fighter_id"]), "tick": str(x["tick"]), "price": str(x["price"]),
                  "fee": str(x["fee"]), "bid": str(x["bid"])} for x in self.sales[-50:]][::-1]
        return {"fee_bps": self.FEE_BPS, "currency": "fake QU", "listings": listings, "sales": sales,
                "stats": {k: (str(v) if isinstance(v, int) else v) for k, v in self.summary().items()},
                "model": "simulated collectors; value from rating, record and experience; not real demand"}

    def state(self) -> dict:
        return {"listings": self.listings, "sales": self.sales}


class Arena:
    def __init__(self, directory: Path, lineup: list[dict], profile: str = "demo", seed: int | None = None,
                 latency=(1, 3), drop_rate: float = 0.02, fees: FeeModel | None = FeeModel(),
                 cup_every: int = 1800, duel_every: int = 300, market_every: int = 2400, log=print,
                 deterministic: bool = False, params: dict | None = None, snapshot_every: int = SNAPSHOT_EVERY):
        self.dir = Path(directory)
        # Samples and tests only: derive policy seeds and salts from the seed.
        # A live arena keeps secrets-based salts, as a real bot must.
        self.deterministic = deterministic
        self.log = log
        self.net = Devnet(self.dir, profile, params=params, compact=compact, compact_every=COMPACT_EVERY)
        if self.net.restart["mode"] != "new":
            r = self.net.restart
            log(f"restored at tick {self.net.world.tick} by {r['mode']} in {r['seconds']} s"
                + (f" (skipped: {'; '.join(r['tried'])})" if r["tried"] else ""))
        self.snapshot_every = snapshot_every
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
        self.tier_stake = self.net.m.tiers[min(self.net.m.tiers)]
        self.market = Market(self, self._load("market.json", None))
        admin = roles()["admin"]
        for entry in lineup:
            fid = self._fighter_for(entry, admin)
            self.labels[fid] = entry
            self._make_bot(fid)
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
        self.net.save(trim=True)
        last = self.net.snapshot_tick
        if self.snapshot_every and (last is None or self.w.tick - last >= self.snapshot_every):
            self.net.snapshot()
        self.state.update(reserve=self.chain.reserve or 0, burned=self.chain.burned)
        self._dump("chain.json", self.state)
        self._dump("assets.json", {fid.hex(): {"issuer": a.issuer.hex(), "name": a.name, "founding": a.founding,
                                               "history": [[t, f.hex() if f else None, to.hex()]
                                                           for t, f, to in a.history]}
                                   for fid, a in self.registry.assets.items()})
        self._dump("market.json", self.market.state())

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
        if "stub" in entry:
            return stub_chooser(self.rules, entry["stub"], seed)
        return policy_chooser(self.rules, E.policy_by_name(entry["policy"]), seed)

    def _bot_log(self, label: str):
        return lambda m: self.log(f"tick {self.w.tick}: bot {label}: {m}")

    def _make_bot(self, fid: bytes):
        entry = self.labels[fid]
        owner = self.registry.assets[fid].owner
        client = SimQubicClient(self.chain, owner, DevnetClient(self.net, owner))
        label = entry["label"]
        bot = Bot(client, self.rules, fid, owner, owner, self._chooser(entry),
                  _budget(self.rules, entry, self.net.m.ticks_per_epoch, self.tier_stake),
                  self.dir / "bots" / label / owner.hex()[:12],
                  log=self._bot_log(label))
        # Every ranked bot enters cups unless its entry says "cups": false, so
        # the strongest ranked fighters meet the cup field too (AUD-019).
        bot.play_cups = bool(entry.get("cups", entry.get("ranked", True)))
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

    def _stake(self, multiple: float) -> int:
        return int(round(multiple * self.tier_stake))

    def sponsorship(self) -> int:
        """The house's sponsorship for the next cup: nothing while one fighter
        won more than sponsor_max_wins of the last sponsor_window sponsored cups."""
        c = self.w.contract
        h = getattr(c, "history", None)
        done = [(k.cup_id, k.champion, k.sponsorship) for k in c.cups.values() if k.status == "COMPLETE"]
        done += [(kid, v[1], v[2]) for kid, v in (h.cups.items() if h is not None else ()) if v[0] == "COMPLETE"]
        sponsored = [champ for _, champ, amount in sorted(done, key=lambda x: x[0]) if amount][-EVENTS["sponsor_window"]:]
        if sponsored and max(sponsored.count(x) for x in set(sponsored)) > EVENTS["sponsor_max_wins"]:
            return 0
        return self._stake(EVENTS["cup_sponsorship"])

    def _cup_level_ticks(self, timing_id=1, checkin=60, replay_delay=40) -> int:
        """A cup level's window: the worst case the contract requires, with a margin."""
        commit, reveal = self.net.m.timing[timing_id]
        worst = checkin + 7 * 3 * (commit + reveal) + replay_delay + 3 * 3 * (commit + reveal) + 2
        return worst + worst // 10

    def _maybe_cup(self):
        c = self.w.contract
        if any(k.status in ("REGISTRATION", "RUNNING") for k in c.cups.values()):
            return
        last = max([k.created_tick for k in c.cups.values()] + [getattr(self, "last_cup_attempt", -10**9)])
        if self.w.tick - last < self.cup_every:
            return
        admin = roles()["admin"]
        fee_id = EVENTS["cup_fee_profile"] if EVENTS["cup_fee_profile"] in self.net.m.fees else 1
        sponsorship = self.sponsorship()
        r = self.w.send(admin, Op.ADMIN_CREATE_CUP, sponsorship, ruleset_digest=self.rules.digest, timing_profile_id=1,
                        fee_profile_id=fee_id, entry_fee=self._stake(EVENTS["cup_entry"]),
                        registration_close=self.w.tick + 120, min_entrants=4, max_entrants=8,
                        level_ticks=self._cup_level_ticks(), first_level_delay=40, checkin_ticks=60, replay_delay=40)
        self.last_cup_attempt = self.w.tick
        self.log(f"tick {self.w.tick}: cup {r.data.get('cup_id')} created ({r.code.name}), sponsorship {sponsorship}")

    def _maybe_duel(self):
        """Now and then an idle duel bot challenges another. The challenger's
        bot decides, under its own budget and duel filters (AUD-019)."""
        if self.w.tick % self.duel_every:
            return
        c = self.w.contract
        idle = [f for f, b in self.bots.items() if b.accept_duels and c.fighters[f].lock == "IDLE"]
        pairs = [(a, b) for a in idle for b in idle if a != b]
        self.rng.shuffle(pairs)
        fmt = self.rng.choice([0, 1, 1, 2])
        stake = self._stake(EVENTS["duel_stake"][fmt])
        for a, b in pairs[:6]:
            why = self.bots[a].challenge(b, c.fighters[b].lifetime, stake, fmt, self.w.tick + 200)
            if why is None:
                self.log(f"tick {self.w.tick}: duel challenge {self.labels[a]['label']} -> "
                         f"{self.labels[b]['label']} ({stake} QU)")
                return

    def _maybe_market(self):
        """Now and then owners list fighters and collectors bid (Market); an
        agreed sale completes on the first tick its fighter is idle."""
        if self.market_every <= 0:
            return
        if self.w.tick % self.market_every == 0:
            self.market.step()
        elif self.market.listings:
            self.market.settle()

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
        self.chain.advance()
        if self.w.tick % COMPACT_EVERY == 0:
            compact(self.w.contract)

    @property
    def qualification(self):
        from .devnet import QUALIFICATION
        return QUALIFICATION.get(self.net.profile)

    def season_standings(self, season: int, t: int) -> dict:
        return self.w.contract.season_standings(season, t, self.qualification)

    def economics(self) -> dict:
        """economics.json (AUD-018, AUD-019): per tier, the player's expected
        value by score and the break-even score; event prices; what recent
        ranked contests paid by rating band; the house's running P&L."""
        m, c = self.net.m, self.w.contract
        fee = m.fees[1]
        rake = fee.rake_bps / 10_000
        tiers = {}
        for tid, stake in sorted(m.tiers.items()):
            house = 2 * stake * fee.rake_bps // 10_000 * fee.house_bps // 10_000
            tiers[str(tid)] = {
                "stake": str(stake), "rake_bps": fee.rake_bps, "house_rake_per_fight": str(house),
                "break_even_win_share": round(1 / (2 * (1 - rake)), 4),
                # Net QU per fight for a bot that wins this share and draws none (a draw refunds the stake).
                "ev_by_win_share": {f"{p:.2f}": str(round(stake * (2 * p * (1 - rake) - 1)))
                                    for p in (0.40, 0.45, 0.50, 0.55, 0.60, 0.65)}}
        bands: dict[str, list[int]] = {}
        for ct in c.contests.values():
            if ct.mode != Mode.RANKED or ct.status != "DONE" or not ct.settlement or ct.result["kind"] == "VOID":
                continue
            for p in (ct.a, ct.b):
                r = p.lifetime_rating
                band = "<900" if r < 900 else "900-1099" if r < 1100 else "1100-1299" if r < 1300 else "1300+"
                bands.setdefault(band, []).append(ct.settlement["credits"].get(p.payout_recipient, 0) - ct.stake)
        credits = c.ledger.credits
        fights = c.next_id["fight"] - 1
        sponsored = sum(k.sponsorship for k in c.cups.values() if k.status == "COMPLETE")
        h = getattr(c, "history", None)
        sponsored += sum(v[2] for v in (h.cups.values() if h is not None else ()) if v[0] == "COMPLETE")
        pnl = credits.get(fee.house, 0) + self.market.fees_collected() - self.chain.burned - sponsored
        return {
            "currency": "fake QU", "note": "simulated execution fees; not a Qubic cost measurement",
            "tiers": tiers,
            "events": {"duel_stake_by_format": {k: str(self._stake(v)) for k, v in
                                                zip(("SINGLE", "BO3", "BO5"), EVENTS["duel_stake"].values())},
                       "cup_entry_fee": str(self._stake(EVENTS["cup_entry"])),
                       "cup_rake_bps": m.fees[EVENTS["cup_fee_profile"] if EVENTS["cup_fee_profile"] in m.fees else 1].rake_bps,
                       "next_cup_sponsorship": str(self.sponsorship()), "market_fee_bps": Market.FEE_BPS},
            "measured_ranked_net_by_rating": {b: {"fights": len(v), "net_per_fight": round(sum(v) / len(v), 1)}
                                              for b, v in sorted(bands.items())},
            "house": {"rake_income": str(credits.get(fee.house, 0)), "market_fees": str(self.market.fees_collected()),
                      "execution_fees": str(self.chain.burned), "sponsorship_paid": str(sponsored),
                      "pnl": str(pnl), "fights": str(fights),
                      "pnl_per_fight": round(pnl / fights, 1) if fights else None},
        }

    def extras(self) -> dict:
        return {"market": self.market.doc(), "economics": self.economics()}

    def deployment(self, tick_seconds: float) -> dict:
        fighters = {}
        for fid, entry in self.labels.items():
            driver = (f"llm:{entry['llm']['model']}" if "llm" in entry else
                      "planner" if "planner" in entry else f"stub:{entry['stub']}" if "stub" in entry
                      else entry.get("policy"))
            fighters[fid.hex()] = {"name": entry["label"], "driver": driver, "asset": self.registry.public(fid)}
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
    done = exports = 0
    next_at = time.monotonic()
    while not stop["now"] and (ticks is None or done < ticks):
        arena.step()
        done += 1
        if done % export_every == 0:
            arena.save()
            export.export_all(arena.w.contract, export_dir, keep=keep, deployment=arena.deployment(tick_seconds),
                              qualification=arena.qualification, extras=arena.extras())
            exports += 1
            if exports % EXPORT_CHECK_EVERY == 0:
                # The public files against the contract (AUD-025): a live fight
                # published past its deadline or a finished one not published final.
                for problem in invariants.check_export(arena.w.contract, export_dir, slack=export_every + 1)[:5]:
                    log(f"tick {arena.w.tick}: export invariant: {problem}")
        next_at += tick_seconds
        delay = next_at - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        else:
            next_at = time.monotonic()
    arena.save()
    export.export_all(arena.w.contract, export_dir, keep=keep, deployment=arena.deployment(tick_seconds),
                      qualification=arena.qualification, extras=arena.extras())
    log(f"stopped at tick {arena.w.tick}; journal saved")
    return arena


def cmd_live(a):
    lineup = json.loads(Path(a.lineup).read_text()) if a.lineup else DEFAULT_LINEUP
    devnet_dir = Path(a.devnet) if a.devnet else Path(os.environ.get(
        "QDOJO_COMBAT_HOME", os.path.expanduser("~/.qdojo/combat"))) / "arena"
    params = None
    if a.timing:
        commit, reveal = (int(x) for x in a.timing.split(","))
        params = {"timing": {1: (commit, reveal)}}
    run(devnet_dir, lineup, Path(a.export), a.tick_seconds, a.export_every, a.keep, a.ticks,
        log=lambda m: print(time.strftime("%H:%M:%S"), m, flush=True), profile=a.profile, params=params)


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
    d.add_argument("--timing", metavar="COMMIT,REVEAL",
                   help="commit and reveal windows in ticks for a NEW arena (default devnet.DEMO_TIMING); "
                        "an existing arena keeps the values it was created with")
    d.set_defaults(fn=cmd_live)
