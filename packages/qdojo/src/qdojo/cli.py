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
    return House(_chain(a, signing), a.data, a.identity, rake_bps=a.rake_bps, seed_per_round=a.seed,
                 uri_base=a.uri_base)


def cmd_house_publish(a):
    h = _house(a, True)
    mode = {v: k for k, v in payload.MODE_NAMES.items()}[a.payout_mode]
    meta = h.publish(a.riddle, a.entry_fee, a.commit_window, a.reveal_window, a.house_seed, payout_mode=mode)
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


def cmd_house_export(a):
    h = _house(a, False)
    hist = h.export(a.out)
    print(f"exported {len(hist['rounds'])} rounds, {len(hist['fighters'])} fighters to {a.out}")


def cmd_bot_run(a):
    chain = _chain(a, True)
    bot = Bot(chain, a.state, a.solver, name=a.name, max_stake=a.max_stake, solver_timeout=a.solver_timeout)
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
    d.set_defaults(fn=cmd_house_publish)
    d = s.add_parser("confirm"); d.add_argument("round", type=int); d.set_defaults(fn=cmd_house_confirm)
    d = s.add_parser("collect"); d.set_defaults(fn=cmd_house_collect)
    d = s.add_parser("settle"); d.add_argument("round", type=int); d.add_argument("--apply", action="store_true")
    d.add_argument("--no-collect", dest="collect", action="store_false"); d.set_defaults(fn=cmd_house_settle)
    d = s.add_parser("export"); d.add_argument("--out", default="apps/web/data"); d.set_defaults(fn=cmd_house_export)

    bp = sub.add_parser("bot")
    s = bp.add_subparsers(dest="sub", required=True)
    d = s.add_parser("run"); d.add_argument("--board", required=True); d.add_argument("--solver", nargs="+", required=True)
    d.add_argument("--state", default=os.path.expanduser("~/.qdojo/bot")); d.add_argument("--name")
    d.add_argument("--max-stake", type=int); d.add_argument("--solver-timeout", type=float, default=60.0)
    d.add_argument("--interval", type=float, default=5.0); d.add_argument("--once", action="store_true")
    d.set_defaults(fn=cmd_bot_run)

    a = p.parse_args(argv)
    try:
        a.fn(a)
    except (HouseError, BotError, ChainError, R.RiddleError, payload.PayloadError) as e:
        sys.exit(f"qdojo: {e}")


if __name__ == "__main__":
    main()
