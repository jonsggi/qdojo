"""Run the devnet live: real-time ticks, a lineup of demo bots, periodic export.

This is the spectator showcase until a Qubic deployment exists. It is a
devnet: fake QU, synthetic identities, bots run by the operator and labelled
as demo bots. Its state is the devnet journal, so a restart resumes exactly.

  qdojo combat live --lineup lineup.json --tick-seconds 1.5 --export apps/web/data/combat/v1

Lineup JSON: [{"label": "tanuki", "policy": "reader-v1"} | {"label": ..., "planner": "cmd"}, ...]
"""
from __future__ import annotations

import json
import os
import secrets
import shlex
import signal
import time
from pathlib import Path

from . import evaluate as E
from . import export
from .bot import Bot, Budget, planner_chooser, policy_chooser
from .devnet import Devnet
from .sim import identity
from .rules import candidate_1

DEFAULT_LINEUP = [
    {"label": "tanuki", "policy": "reader-v1"},
    {"label": "kappa", "policy": "search-v1"},
    {"label": "tengu", "policy": "scout-v1"},
    {"label": "oni", "policy": "script-vs-scout-v1"},
    {"label": "kitsune", "policy": "mixed-v1"},
    {"label": "baku", "policy": "repeat-last-winner"},
    {"label": "raiju", "policy": "kicker-v1"},
    {"label": "kirin", "policy": "jabber-v1"},
]

DEPLOYMENT = {"kind": "devnet", "currency": "fake QU", "identities": "synthetic",
              "bots": "operator-run demo bots", "note": "not a Qubic deployment; nothing here is real money"}


def _deployment(tick_seconds: float, names: dict) -> dict:
    return {**DEPLOYMENT, "tick_seconds": tick_seconds, "names": names,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}


def _budget(rules) -> Budget:
    # Demo bots play continuously on fake QU; limits stay finite so a bug cannot loop forever silently.
    return Budget(ruleset_digest=rules.digest.hex(), max_fights_per_day=100_000, max_daily_committed=10**12,
                  max_daily_net_loss=10**12, max_total_escrow=10_000, stop_after_faults=10**6)


def build_bots(net: Devnet, lineup: list[dict], state_root: Path) -> list[Bot]:
    rules = candidate_1()
    bots = []
    for entry in lineup:
        fid, owner = net.ensure_fighter(entry["label"], funds=10**12)
        if "planner" in entry:
            choose = planner_chooser(shlex.split(entry["planner"]), entry.get("budget_ms", 1500))
        else:
            choose = policy_chooser(rules, E.policy_by_name(entry["policy"]), secrets.token_bytes(32))
        bots.append(Bot(net.client(owner), rules, fid, owner, owner, choose, _budget(rules),
                        state_root / entry["label"]))
    return bots


def run(devnet_dir: Path, lineup: list[dict], export_dir: Path, tick_seconds: float = 1.5,
        export_every: int = 10, keep: int = 200, ticks: int | None = None, log=print):
    net = Devnet(devnet_dir)
    bots = build_bots(net, lineup, Path(devnet_dir) / "bots")
    names = {identity("fighter:" + e["label"]).hex(): e["label"] for e in lineup}
    net.save()
    stop = {"now": False}

    def _stop(*_):
        stop["now"] = True
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    done = 0
    next_at = time.monotonic()
    while not stop["now"] and (ticks is None or done < ticks):
        for b in bots:
            try:
                b.step()
            except Exception as exc:               # one bot's failure must not stop the arena
                log(f"tick {net.world.tick}: bot {b.fighter_id.hex()[:8]} error: {exc}")
        net.world.end()
        done += 1
        if done % export_every == 0:
            net.save()
            export.export_all(net.world.contract, export_dir, keep=keep,
                              deployment=_deployment(tick_seconds, names))
        next_at += tick_seconds
        delay = next_at - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        else:
            next_at = time.monotonic()
    net.save()
    export.export_all(net.world.contract, export_dir, keep=keep, deployment=_deployment(tick_seconds, names))
    log(f"stopped at tick {net.world.tick}; journal saved")


def cmd_live(a):
    lineup = json.loads(Path(a.lineup).read_text()) if a.lineup else DEFAULT_LINEUP
    devnet_dir = Path(a.devnet) if a.devnet else Path(os.environ.get(
        "QDOJO_COMBAT_HOME", os.path.expanduser("~/.qdojo/combat"))) / "live-devnet"
    run(devnet_dir, lineup, Path(a.export), a.tick_seconds, a.export_every, a.keep, a.ticks,
        log=lambda m: print(time.strftime("%H:%M:%S"), m, flush=True))


def add_parser(s):
    d = s.add_parser("live", help="run the devnet live with a demo lineup and export for spectators")
    d.add_argument("--devnet", help="devnet directory (default ~/.qdojo/combat/live-devnet)")
    d.add_argument("--lineup", help="lineup JSON (default: eight demo bots)")
    d.add_argument("--export", default="apps/web/data/combat/v1")
    d.add_argument("--tick-seconds", type=float, default=1.5)
    d.add_argument("--export-every", type=int, default=10, help="ticks between exports")
    d.add_argument("--keep", type=int, default=200, help="fights kept in the export")
    d.add_argument("--ticks", type=int, help="stop after this many ticks (default: run until stopped)")
    d.set_defaults(fn=cmd_live)
