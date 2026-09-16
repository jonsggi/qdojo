"""qdojo command line. Money moves only with --apply."""
import argparse
import json
import os
import sys
import time

from . import __version__, payload, riddle as R
from .chain.cli import QubicCli
from .chain.rpc import Indexer
from .chain.base import Unknown, ChainError
from .house import House, HouseError
from .bot import Bot, BotError, fetch_board
from . import nodes, onboard, spar
from .shares import Shares, SharesError


def _chain(a, signing: bool):
    idx = Indexer()
    if a.node is None:
        if signing:
            sys.exit("a node is required to sign: --node IP[:PORT]")
        return idx
    ip, _, port = a.node.partition(":")
    return QubicCli(a.cli, ip, int(port or 21841), identity=a.identity or "", conf=a.conf if signing else None,
                    schedule_offset=a.schedule_offset, indexer=idx)


def cmd_payload_decode(a):
    m = payload.decode(bytes.fromhex(a.hex))
    d = {k: (v.hex() if isinstance(v, bytes) else v) for k, v in vars(m).items()}
    print(json.dumps({"kind": payload.KIND_NAMES[m.kind], **d}, indent=2))


def cmd_riddle_hash(a):
    with open(a.file, encoding="utf-8") as f:
        r = R.from_public(json.load(f))
    print(r.hash().hex())


def _house(a, signing):
    npcs = tuple(x for x in (getattr(a, "npcs", None) or "").split(",") if x)
    return House(_chain(a, signing), a.data, a.identity, rake_bps=a.rake_bps, seed_per_round=a.seed,
                 uri_base=a.uri_base, house_fighters=npcs)


def cmd_house_publish(a):
    h = _house(a, True)
    mode = {v: k for k, v in payload.MODE_NAMES.items()}[a.payout_mode]
    meta = h.publish(a.riddle, a.entry_fee, a.commit_window, a.reveal_window, a.house_seed, payout_mode=mode,
                     match_bps=a.match_bps)
    print(f"round {meta['round_id']} PUBLISH {meta['publish_tx']} scheduled for tick {meta['scheduled_tick']}")
    for _ in range(90):
        try:
            meta = h.confirm_publish(meta["round_id"])
        except Unknown:
            time.sleep(1)
            continue
        print(f"round {meta['round_id']} is {meta['status']}, publish tick {meta['publish_tick']}")
        return
    print("publish not decidable yet; run `house confirm` later")


def cmd_house_confirm(a):
    print(json.dumps(_house(a, False).confirm_publish(a.round), indent=2))


def cmd_house_collect(a):
    h = _house(a, False)
    if a.rescan:
        lo, hi = (int(x) for x in a.rescan.split("-"))
        print(f"rescanned {lo}-{hi}: {h.rescan(lo, hi)} new transactions")
        return
    n = h.collect()
    print(f"stored {n} new transactions, scanned to tick {h.state()['scanned_to']}")


def cmd_house_settle(a):
    h = _house(a, a.apply)
    if a.collect:
        h.collect()
    doc = h.settle(a.round, apply=a.apply)
    print(json.dumps(doc, indent=2))
    if not a.apply:
        print("\nPLAN ONLY. Nothing was sent. Re-run with --apply to pay.", file=sys.stderr)


def cmd_house_spar(a):
    h = _house(a, True)
    sp = spar.Spar(h, a.belts.split(","), a.entry_fee, a.commit_window, a.reveal_window,
                   riddle_dir=os.path.join(a.data, "riddles"), web_out=a.out,
                   metrics_path=os.path.join(a.data, "metrics.jsonl"), seed=a.rng_seed, poll=a.poll,
                   match_bps=a.match_bps, min_players=a.min_players, lobby_window=a.lobby_window,
                   npcs=[x for x in (a.npcs or "").split(",") if x], npc_rounds=a.npc_rounds,
                   bond_bps=a.bond_bps, bond_rounds=a.bond_rounds, skip_dead=not a.dead_tables)
    sp.payout_mode = {v: k for k, v in payload.MODE_NAMES.items()}[a.payout_mode]
    sp.run(a.rounds, stop_below=a.stop_below)


def cmd_house_metrics(a):
    print(json.dumps(spar.summarize(os.path.join(a.data, "metrics.jsonl")), indent=2))


def cmd_house_model(a):
    from . import model
    p = model.Params(rounds=a.rounds, entry_fee=a.entry_fee, seed_cap=a.seed_cap, match_bps=a.match_bps,
                     rake_bps=a.rake_bps, payout_mode={v: k for k, v in payload.MODE_NAMES.items()}[a.payout_mode],
                     bond_bps=a.bond_bps, bond_rounds=a.bond_rounds, min_players=a.min_players,
                     ladder=not a.no_ladder, start_balance=a.start_balance, gate=a.gate, season=a.season)
    cohort = None
    if a.cohort:
        cohort = json.load(open(a.cohort))
    elif a.calibrate:
        cohort = model.calibrate(json.load(open(a.calibrate)),
                                 npcs=set(x for x in (a.npcs or "").split(",") if x) if a.npcs else None)
        if a.clones > 1:
            for c in cohort:
                c["count"] = a.clones
    if a.sweep:
        grid = {}
        for item in a.sweep:
            k, vs = item.split("=")
            grid[k] = [int(v) if v.lstrip("-").isdigit() else v for v in vs.split(",")]
        print(json.dumps(model.sweep(p, grid, cohort, a.replicates, a.seed), indent=2))
    else:
        print(json.dumps(model.run(p, cohort, a.replicates, a.seed), indent=2))


def cmd_house_export(a):
    h = _house(a, False)
    hist = h.export(a.out)
    print(f"exported {len(hist['rounds'])} rounds, {len(hist['fighters'])} fighters to {a.out}")


def _bot_defaults(a):
    """Fill --cli/--conf/--identity/--node from the bot profile and node cache
    when they were not given, so `qdojo bot run` works after `qdojo bot init`."""
    prof = onboard.load_profile(a.state)
    try:
        a.cli = onboard.find_cli(a.cli if a.cli != "qubic-cli" else None)
    except onboard.OnboardError as e:
        sys.exit(f"qdojo: {e}")
    a.conf = a.conf or prof.get("conf") or os.path.join(a.state, "bot.conf")
    if not os.path.exists(os.path.expanduser(a.conf)):
        sys.exit(f"qdojo: no seed conf at {a.conf}; run `qdojo bot init` first")
    derived = onboard.derive_identity(a.cli, os.path.expanduser(a.conf))
    if a.identity and a.identity != derived:
        sys.exit(f"qdojo: --identity {a.identity[:8]}… does not match the conf, which signs as {derived[:8]}…")
    a.identity = derived
    if not a.node:
        a.node = nodes.best_node(a.state, nodes.cli_probe(a.cli))
        print(f"node: {a.node} (auto-detected)", file=sys.stderr)


def cmd_bot_init(a):
    try:
        cli = onboard.find_cli(a.cli if a.cli != "qubic-cli" else None)
    except onboard.OnboardError as e:
        sys.exit(f"qdojo: {e}")
    conf = os.path.expanduser(a.conf or os.path.join(a.state, "bot.conf"))
    created = False
    if not os.path.exists(conf):
        if a.seed_from_stdin:
            seed = sys.stdin.readline().strip()
        else:
            seed = None
        onboard.create_conf(conf, seed)
        created = True
    identity = onboard.derive_identity(cli, conf)
    found = nodes.discover(nodes.cli_probe(cli)) if not a.node else [{"ip": a.node, "tick": 0, "lag": 0}]
    if not found:
        sys.exit("qdojo: no live Qubic node reachable; check your network or pass --node")
    nodes.save(a.state, found)
    onboard.save_profile(a.state, {"conf": conf, "identity": identity, "name": a.name, "cli": cli})
    print(f"identity : {identity}")
    print(f"conf     : {conf}  ({'NEW seed created, back this file up' if created else 'existing seed'})")
    print(f"node     : {found[0]['ip']}  ({len(found)} live nodes agree, cached in {nodes.cache_path(a.state)})")
    print(f"qubic-cli: {cli}")
    print("\nFund the identity above with QU to play, then:\n"
          f"  qdojo bot run --board <board url> --solver <your solver>{' --name ' + a.name if a.name else ''}")


def cmd_nodes(a):
    cli = onboard.find_cli(a.cli if a.cli != "qubic-cli" else None)
    found = nodes.discover(nodes.cli_probe(cli))
    if not found:
        sys.exit("qdojo: no live node found")
    nodes.save(a.state, found)
    for n in found:
        print(f"{n['ip']:16} tick {n['tick']}  lag {n['lag']}")


def _shares(a, signing):
    _bot_defaults(a)
    return Shares(_chain(a, signing))


def cmd_bot_issue_shares(a):
    sh = _shares(a, a.apply)
    plan = sh.plan_issue(a.name, a.count)
    print(json.dumps(plan, indent=2))
    if not a.apply:
        print("\nPLAN ONLY. The issuance fee above goes to Qx's shareholders and is not refundable. Re-run with --apply.", file=sys.stderr)
        return
    res = sh.issue(a.name, a.count)
    print(f"issue {res.tx_id} scheduled for tick {res.scheduled_tick}; confirming…")
    for _ in range(90):
        try:
            ok = sh.cli.confirm(res.tx_id, res.scheduled_tick); break
        except Unknown:
            time.sleep(1)
    else:
        ok = None
    print("included" if ok else "NOT included; nothing was issued" if ok is False else "undecidable yet; check later")
    if ok:
        print(json.dumps(sh.owned(a.identity), indent=2))


def cmd_bot_shares(a):
    sh = _shares(a, False)
    if a.name:
        hs = sh.holders(a.issuer or a.identity, a.name)
        total = sum(h.shares for h in hs)
        for h in hs:
            print(f"{h.owner}  {h.shares:>10}  {h.shares / total:7.2%}" if total else f"{h.owner}  {h.shares}")
        print(f"holders {len(hs)}  total shares {total}")
    else:
        print(json.dumps(sh.owned(a.identity), indent=2))


def cmd_bot_dividend(a):
    sh = _shares(a, a.apply)
    plan = sh.plan_dividend(a.name, a.amount)
    print(json.dumps(plan, indent=2))
    if not a.apply:
        print("\nPLAN ONLY. Re-run with --apply to distribute.", file=sys.stderr)
        return
    res = sh.pay_dividend(a.name, a.amount)
    print(f"distribution {res.tx_id} scheduled for tick {res.scheduled_tick}")


def cmd_bot_stats(a):
    """This bot's published performance, straight from the house's API."""
    _bot_defaults(a)
    base = a.board.rsplit("/", 1)[0] if "/" in a.board else "."
    doc = fetch_board(f"{base}/fighters.json")
    me = next((f for f in doc.get("fighters", []) if f["identity"] == a.identity), None)
    if me is None:
        sys.exit(f"qdojo: {a.identity[:8]}… has not fought at this house yet")
    print(json.dumps(me, indent=2))


def cmd_bot_run(a):
    _bot_defaults(a)
    chain = _chain(a, True)
    bot = Bot(chain, a.state, a.solver, name=a.name, max_stake=a.max_stake, solver_timeout=a.solver_timeout,
              strategy_cmd=a.strategy)
    while True:
        try:
            board = fetch_board(a.board)
            if a.name:
                bot.house = board["house"]
                bot.bow()
            for line in bot.step(board):
                print(time.strftime("%H:%M:%S"), line, flush=True)
        except (Unknown, ChainError, BotError, OSError, ValueError) as e:
            print(time.strftime("%H:%M:%S"), f"warning: {e}", file=sys.stderr, flush=True)
        if a.once:
            return
        time.sleep(a.interval)


def main(argv=None):
    p = argparse.ArgumentParser(prog="qdojo", description="A dojo where AI bots compete for real QU.")
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("--cli", default=os.environ.get("QUBIC_CLI", "qubic-cli"), help="path to qubic-cli")
    p.add_argument("--node", default=os.environ.get("QDOJO_NODE"), help="node IP[:PORT] for reads and signing")
    p.add_argument("--conf", default=os.environ.get("QDOJO_CONF"), help="0600 conf with one seed= line")
    p.add_argument("--identity", default=os.environ.get("QDOJO_IDENTITY"), help="identity the conf signs as")
    p.add_argument("--schedule-offset", type=int, default=20)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("payload").add_subparsers(dest="sub", required=True)
    d = s.add_parser("decode"); d.add_argument("hex"); d.set_defaults(fn=cmd_payload_decode)

    s = sub.add_parser("riddle").add_subparsers(dest="sub", required=True)
    d = s.add_parser("hash"); d.add_argument("file"); d.set_defaults(fn=cmd_riddle_hash)

    hp = sub.add_parser("house")
    hp.add_argument("--data", default=os.environ.get("QDOJO_DATA", "private/house"))
    hp.add_argument("--rake-bps", type=int, default=int(os.environ.get("QDOJO_RAKE_BPS", "0")))
    hp.add_argument("--seed", type=int, default=int(os.environ.get("QDOJO_SEED_PER_ROUND", "0")))
    hp.add_argument("--uri-base", default=os.environ.get("QDOJO_URI_BASE", ""))
    s = hp.add_subparsers(dest="sub", required=True)
    d = s.add_parser("publish"); d.add_argument("riddle"); d.add_argument("--entry-fee", type=int, required=True)
    d.add_argument("--commit-window", type=int, default=600); d.add_argument("--reveal-window", type=int, default=300)
    d.add_argument("--house-seed", type=int, default=None)
    d.add_argument("--payout-mode", choices=sorted(payload.MODE_NAMES.values()), default="first")
    d.add_argument("--match-bps", type=int, default=10000, help="house seed = min(cap, stakes*bps/10000); 0 = fixed seed")
    d.set_defaults(fn=cmd_house_publish)
    d = s.add_parser("confirm"); d.add_argument("round", type=int); d.set_defaults(fn=cmd_house_confirm)
    d = s.add_parser("collect"); d.add_argument("--rescan", help="TICK-TICK: re-read a past range"); d.set_defaults(fn=cmd_house_collect)
    d = s.add_parser("settle"); d.add_argument("round", type=int); d.add_argument("--apply", action="store_true")
    d.add_argument("--no-collect", dest="collect", action="store_false"); d.set_defaults(fn=cmd_house_settle)
    d = s.add_parser("export"); d.add_argument("--out", default="apps/web/data"); d.set_defaults(fn=cmd_house_export)
    d = s.add_parser("spar", help="generated riddles, rounds back to back, metrics per round")
    d.add_argument("--rounds", type=int, default=10); d.add_argument("--belts", default="white,yellow,orange,green,blue")
    d.add_argument("--entry-fee", type=int, default=1000); d.add_argument("--commit-window", type=int, default=300)
    d.add_argument("--reveal-window", type=int, default=120); d.add_argument("--out", default="apps/web/data")
    d.add_argument("--rng-seed", type=int, default=None); d.add_argument("--poll", type=int, default=15)
    d.add_argument("--stop-below", type=int, default=0); d.add_argument("--match-bps", type=int, default=10000)
    d.add_argument("--min-players", type=int, default=0, help="open a lobby and publish only with this many seats bought")
    d.add_argument("--lobby-window", type=int, default=240, help="ticks the table stays open")
    d.add_argument("--npcs", help="comma-separated house-fighter identities to top up before each round")
    d.add_argument("--npc-rounds", type=int, default=3, help="top NPCs up to this many stakes")
    d.add_argument("--payout-mode", choices=sorted(payload.MODE_NAMES.values()), default="first")
    d.add_argument("--bond-bps", type=int, default=0, help="share of each win held as a bond")
    d.add_argument("--bond-rounds", type=int, default=0, help="rounds the winner must fight before release")
    d.add_argument("--dead-tables", action="store_true", help="publish belts even when no outsider may sit there")
    d.set_defaults(fn=cmd_house_spar)
    d = s.add_parser("metrics"); d.set_defaults(fn=cmd_house_metrics)
    d = s.add_parser("model", help="offline model of the mechanics through the real evaluator and ladder (house-side)")
    d.add_argument("--rounds", type=int, default=200); d.add_argument("--replicates", type=int, default=10); d.add_argument("--seed", type=int, default=1)
    d.add_argument("--entry-fee", type=int, default=1000); d.add_argument("--seed-cap", type=int, default=5000)
    d.add_argument("--match-bps", type=int, default=10000); d.add_argument("--rake-bps", type=int, default=0)
    d.add_argument("--payout-mode", choices=sorted(payload.MODE_NAMES.values()), default="podium")
    d.add_argument("--bond-bps", type=int, default=5000); d.add_argument("--bond-rounds", type=int, default=3)
    d.add_argument("--min-players", type=int, default=3); d.add_argument("--no-ladder", action="store_true")
    d.add_argument("--start-balance", type=int, default=20000)
    d.add_argument("--gate", choices=["strict", "soft", "handicap"], default="strict")
    d.add_argument("--season", type=int, default=0, help="reset the ladder every N rounds")
    d.add_argument("--cohort", help="JSON list of archetypes"); d.add_argument("--calibrate", help="a fighters.json to derive archetypes from")
    d.add_argument("--clones", type=int, default=1, help="with --calibrate: copies of each measured fighter")
    d.add_argument("--npcs", help="with --calibrate: comma-separated house-funded identities (names are untrusted)")
    d.add_argument("--sweep", nargs="+", help="param=v1,v2,... (e.g. match_bps=0,5000,10000 bond_bps=0,5000)")
    d.set_defaults(fn=cmd_house_model)

    bp = sub.add_parser("bot")
    bp.add_argument("--state", default=os.path.expanduser("~/.qdojo/bot"), help="bot state dir (seed conf, profile, node cache)")
    s = bp.add_subparsers(dest="sub", required=True)
    d = s.add_parser("init", help="create a seed if there is none, derive the identity, find live nodes")
    d.add_argument("--name"); d.add_argument("--seed-from-stdin", action="store_true", help="import an existing seed instead of creating one")
    d.set_defaults(fn=cmd_bot_init)
    d = s.add_parser("nodes", help="discover live nodes and refresh the cache"); d.set_defaults(fn=cmd_nodes)
    d = s.add_parser("stats", help="this bot's performance as the house publishes it"); d.add_argument("--board", required=True)
    d.set_defaults(fn=cmd_bot_stats)
    d = s.add_parser("issue-shares", help="issue this bot's shares on Qx (the issuance fee is yours)")
    d.add_argument("name"); d.add_argument("count", type=int); d.add_argument("--apply", action="store_true")
    d.set_defaults(fn=cmd_bot_issue_shares)
    d = s.add_parser("shares", help="list holders of an asset, or every asset this identity owns")
    d.add_argument("--name"); d.add_argument("--issuer"); d.set_defaults(fn=cmd_bot_shares)
    d = s.add_parser("dividend", help="distribute QU to this bot's shareholders pro rata via QUtil")
    d.add_argument("name"); d.add_argument("amount", type=int); d.add_argument("--apply", action="store_true")
    d.set_defaults(fn=cmd_bot_dividend)
    d = s.add_parser("run"); d.add_argument("--board", required=True); d.add_argument("--solver", nargs="+", required=True)
    d.add_argument("--name")
    d.add_argument("--max-stake", type=int); d.add_argument("--solver-timeout", type=float, default=60.0)
    d.add_argument("--interval", type=float, default=5.0); d.add_argument("--once", action="store_true")
    d.add_argument("--strategy", nargs="+", help="program deciding whether to enter a round (docs/api.md)")
    d.set_defaults(fn=cmd_bot_run)

    a = p.parse_args(argv)
    try:
        a.fn(a)
    except (HouseError, BotError, ChainError, R.RiddleError, payload.PayloadError, onboard.OnboardError, SharesError, RuntimeError) as e:
        sys.exit(f"qdojo: {e}")


if __name__ == "__main__":
    main()
