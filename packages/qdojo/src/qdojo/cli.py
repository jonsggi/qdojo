"""qdojo command line. Money moves only with --apply."""
import argparse
import dataclasses
import json
import os
import sys
import time

from . import __version__, payload, riddle as R, hashing, riddles
from .chain.cli import QubicCli
from .chain.native import NativeChain
from .chain.rpc import Indexer
from .chain.base import Unknown, ChainError
from .house import House, HouseError
from .bot import Bot, BotError, fetch_board
from . import nodes, onboard, spar, events, lab, wizard, term, training, prompts as P, dash, fees
from . import portable, seedconf
from . import settings, cockpit
from .shares import Shares, SharesError


def _chain(a, signing: bool):
    """The chain this run talks through.

    Native by default: qdojo signs and speaks the node protocol itself, so a
    fighter needs nothing but Python. `--chain cli` keeps the old path through
    a compiled qubic-cli, which is still what `scripts/crosscheck-signer.py`
    checks the native signer against.
    """
    idx = Indexer()
    if a.node is None:
        if signing:
            sys.exit("a node is required to sign: --node IP[:PORT]")
        return idx
    ip, _, port = a.node.partition(":")
    env_fallbacks = os.environ.get("QDOJO_FALLBACK_NODES")
    if env_fallbacks is not None:
        fallbacks = tuple(x for x in env_fallbacks.split(",") if x)
    elif getattr(a, "state", None):
        # No explicit fallback list, but a bot state dir with a node cache:
        # use it instead of asking exactly one node. The cache already holds
        # several tick-agreeing nodes from `qdojo nodes`, so an absence
        # check (e.g. "is this asset already issued?") gets a genuine second
        # opinion by default, not just in a hand-configured deployment.
        fallbacks = tuple(n["ip"] for n in nodes.load(a.state) if n["ip"] != ip)
    else:
        fallbacks = ()
    if getattr(a, "chain", "native") == "cli":
        return QubicCli(a.cli, ip, int(port or 21841), identity=a.identity or "",
                        conf=a.conf if signing else None,
                        schedule_offset=a.schedule_offset, indexer=idx, fallback_nodes=fallbacks)
    return NativeChain(ip, int(port or 21841), identity=a.identity or "",
                       conf=a.conf if signing else None,
                       schedule_offset=a.schedule_offset, indexer=idx, fallback_nodes=fallbacks)


def _hex_arg(s: str) -> bytes:
    """Hex as a human pastes it: explorers and wallets prefix it with 0x and
    break it across lines. The wire format has neither (docs/protocol.md)."""
    t = "".join(s.split())
    if t[:2] in ("0x", "0X"):
        t = t[2:]
    try:
        return bytes.fromhex(t)
    except ValueError:
        raise payload.PayloadError("not hex: expected hex digits in pairs, an optional 0x prefix")


def cmd_payload_decode(a):
    m = payload.decode(_hex_arg(a.hex))
    print(json.dumps({"kind": payload.KIND_NAMES[m.kind], **events.fields_of(m)}, indent=2))


def cmd_riddle_hash(a):
    with open(a.file, encoding="utf-8") as f:
        r = R.from_public(json.load(f))
    print(r.hash().hex())


def cmd_riddle_list(a):
    print(json.dumps({belt: riddles.kinds(belt, pack=a.pack) for belt in riddles.BELTS}, indent=2))


def cmd_riddle_sample(a):
    import random
    if a.round_id < 1:
        raise R.RiddleError("round ID must be positive")
    doc = riddles.generate_kind(a.kind, random.Random(a.rng_seed), a.round_id)
    print(json.dumps(doc if a.with_answer else R.from_public(doc).public(), indent=2))


def _house(a, signing):
    npcs = tuple(x for x in (getattr(a, "npcs", None) or "").split(",") if x)
    return House(_chain(a, signing), a.data, a.identity, rake_bps=a.rake_bps, seed_per_round=a.seed,
                 uri_base=a.uri_base, house_fighters=npcs, dev_identity=getattr(a, "dev_identity", "") or "",
                 rake_house_bps=getattr(a, "rake_house_bps", 10000), rake_dev_bps=getattr(a, "rake_dev_bps", 0),
                 rake_share_bps=getattr(a, "rake_share_bps", 0))


def cmd_house_publish(a):
    h = _house(a, True)
    mode = {v: k for k, v in payload.MODE_NAMES.items()}[a.payout_mode]
    meta = h.publish(a.riddle, a.entry_fee, a.commit_window, a.reveal_window, a.house_seed, payout_mode=mode,
                     match_bps=a.match_bps, belt=a.belt, sensei=a.sensei)
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


def _take_ephemeral(a):
    """`--ephemeral-conf PATH` names the conf AND marks it throwaway, in one
    flag, so the only conf a run can ever shred is the one this flag named.
    A conf that arrived through --conf, QDOJO_CONF or the profile is never
    touched, and naming two different files is refused rather than guessed.
    Returns the path to shred on exit, or None."""
    path = getattr(a, "ephemeral_conf", None)
    if not path:
        return None
    path = os.path.expanduser(path)
    if a.conf and os.path.realpath(os.path.expanduser(a.conf)) != os.path.realpath(path):
        sys.exit(f"qdojo: --conf {a.conf} and --ephemeral-conf {path} name different files; pass one of them")
    a.conf = path
    return path


def _fee_arg(text):
    """--entry-fee takes a whole number of QU, or 'auto' (docs/spec.md §5)."""
    if text.strip().lower() == "auto":
        return "auto"
    try:
        return int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r}: a whole number of QU, or auto")


def _add_fee_flags(d):
    """--entry-fee and the knobs of its auto mode, shared by spar and model."""
    d.add_argument("--entry-fee", type=_fee_arg, default=1000,
                   help="QU per seat, or 'auto': retargeted per belt from the house's own history (docs/spec.md §5)")
    d.add_argument("--fee-alpha", type=float, default=0.5, help="auto: fee' = fee * (occupancy / target) ** alpha")
    d.add_argument("--fee-window", type=int, default=8, help="auto: settled or void rounds at the belt that count")
    d.add_argument("--fee-headroom", type=int, default=2, help="auto: target occupancy = min_players + headroom")
    d.add_argument("--fee-clamp", type=float, default=1.5, help="auto: one retarget moves the fee by at most this factor")
    d.add_argument("--fee-floor", default="100", help="auto: the lowest fee in QU; one number, or belt=QU,belt=QU")
    d.add_argument("--fee-cap", type=int, default=0, help="auto: the highest fee in QU (0 = none); the only ceiling without a rake")
    d.add_argument("--fee-start", type=int, default=1000, help="auto: the fee at a belt with no history yet")
    return d


def _fee_policy(a):
    """The controller `--entry-fee auto` asks for, or None for a fixed fee."""
    if a.entry_fee != "auto":
        return None
    floor, floors = fees.parse_floor(a.fee_floor)
    return fees.FeePolicy(alpha=a.fee_alpha, window=a.fee_window, headroom=a.fee_headroom, clamp=a.fee_clamp,
                          floor=floor, start=a.fee_start, cap=a.fee_cap, floors=floors)


def cmd_house_spar(a):
    policy = _fee_policy(a)
    npcs = [x for x in (a.npcs or "").split(",") if x]
    if policy and npcs:
        sys.exit("qdojo: --entry-fee auto and --npcs do not mix: a house fighter sits at any price, "
                 "so the fee could only rise (docs/model.md, the entry-fee section)")
    throwaway = _take_ephemeral(a)
    seedconf.warn_leftovers(exclude=a.conf)
    with seedconf.ephemeral(throwaway):
        h = _house(a, True)
        sp = spar.Spar(h, a.belts.split(","), a.fee_start if policy else a.entry_fee, a.commit_window, a.reveal_window,
                       riddle_dir=os.path.join(a.data, "riddles"), web_out=a.out,
                       metrics_path=os.path.join(a.data, "metrics.jsonl"), seed=a.rng_seed, poll=a.poll,
                       match_bps=a.match_bps, min_players=a.min_players, lobby_window=a.lobby_window,
                       npcs=npcs, npc_rounds=a.npc_rounds,
                       bond_bps=a.bond_bps, bond_rounds=a.bond_rounds, skip_dead=not a.dead_tables, sensei=a.sensei,
                       riddle_pack=a.riddle_pack, fee_policy=policy)
        sp.payout_mode = {v: k for k, v in payload.MODE_NAMES.items()}[a.payout_mode]
        sp.run(a.rounds, stop_below=a.stop_below)


def cmd_house_resume(a):
    h = _house(a, True)
    sp = spar.Spar(h, ["white"], a.entry_fee, 300, 120, riddle_dir=os.path.join(a.data, "riddles"),
                   web_out=a.out, metrics_path=os.path.join(a.data, "metrics.jsonl"), poll=a.poll)
    sp.resume(a.round)


def cmd_house_metrics(a):
    print(json.dumps(spar.summarize(os.path.join(a.data, "metrics.jsonl")), indent=2))


def cmd_house_distribute(a):
    """Pay the accrued shareholder rake pool to the house asset's holders via
    QUtil. Booking the pool as paid happens only once the send is CONFIRMED,
    never on the receipt: a `send()` returning is not a claim the
    transaction landed, and even a landed one can be a contract-level
    refund (see shares.plan_dividend). A distribution in flight is kept as
    a pending record in state so the pool is never drawn down twice and a
    crash between send and confirm is recoverable by re-running the
    command."""
    from .shares import Shares
    h = _house(a, a.apply)
    st = h.state()
    pending = st.get("pending_distribution")
    if pending:
        print(f"a distribution of {pending['amount']} QU (tx {pending['tx'][:8]}… "
              f"scheduled for tick {pending['tick']}) is still pending confirmation.")
        if not a.apply:
            print("\nPLAN ONLY. Re-run with --apply to settle it.", file=sys.stderr); return
        try:
            ok = h.chain.confirm(pending["tx"], pending["tick"])
        except Unknown:
            print("undecidable yet; re-run to settle.", file=sys.stderr); return
        if ok:
            st["shareholder_pool"] = max(0, st.get("shareholder_pool", 0)
                                         - (pending["distributed"] + pending["fee"]))
            st["shareholder_paid"] = st.get("shareholder_paid", 0) + pending["distributed"]
            print(f"confirmed: distributed {pending['distributed']} to holders of {a.asset}, "
                  f"burnt {pending['fee']} in fees; the rest ({pending['amount'] - pending['distributed'] - pending['fee']}) "
                  "returned to the house.")
        else:
            print("NOT included; the pool is unchanged.")
        del st["pending_distribution"]
        h._save_state(st)
        return

    pool = st.get("shareholder_pool", 0)
    print(f"shareholder pool: {pool} QU")
    if pool <= 0:
        print("nothing to distribute"); return
    sh = Shares(h.chain)
    plan = sh.plan_dividend(a.asset, pool)
    print(json.dumps(plan, indent=2))
    if not a.apply:
        print("\nPLAN ONLY. Re-run with --apply to distribute.", file=sys.stderr); return
    res = sh.pay_dividend(a.asset, pool)
    st["pending_distribution"] = {"tx": res.tx_id, "tick": res.scheduled_tick, "amount": pool,
                                  "distributed": plan["distributed"], "fee": plan["fee"]}
    h._save_state(st)
    print(f"distribution {res.tx_id} scheduled for tick {res.scheduled_tick}; "
          "re-run `house distribute-shareholders --apply` once it has landed to settle the pool.")


def _sweep_value(v):
    for cast in (int, float):
        try:
            return cast(v)
        except ValueError:
            pass
    return {"true": True, "false": False}.get(v.lower(), v)


def cmd_house_model(a):
    from . import model
    auto = a.entry_fee == "auto"
    p = model.Params(rounds=a.rounds, entry_fee=a.fee_start if auto else a.entry_fee, seed_cap=a.seed_cap, match_bps=a.match_bps,
                     rake_bps=a.rake_bps, payout_mode={v: k for k, v in payload.MODE_NAMES.items()}[a.payout_mode],
                     bond_bps=a.bond_bps, bond_rounds=a.bond_rounds, min_players=a.min_players,
                     ladder=not a.no_ladder, start_balance=a.start_balance, gate=a.gate, season=a.season,
                     rake_house_bps=a.rake_house_bps, rake_dev_bps=a.rake_dev_bps, rake_share_bps=a.rake_share_bps,
                     fee_mode="auto" if auto else "fixed", fee_alpha=a.fee_alpha, fee_window=a.fee_window,
                     fee_headroom=a.fee_headroom, fee_clamp=a.fee_clamp, fee_floor=fees.parse_floor(a.fee_floor)[0],
                     fee_start=a.fee_start, fee_cap=a.fee_cap, demand=a.demand, refill=a.refill,
                     target_pot=a.target_pot, target_pot_taper=a.target_pot_taper)
    cohort = None
    if a.cohort:
        cohort = json.load(open(a.cohort))
    elif a.calibrate:
        cohort = model.calibrate(json.load(open(a.calibrate)),
                                 npcs=set(x for x in (a.npcs or "").split(",") if x) if a.npcs else None)
        if a.no_house_fighters:
            cohort = [c for c in cohort if not c.get("house_funded")]
        if a.clones > 1:
            for c in cohort:
                c["count"] = a.clones
    if a.sweep:
        grid = {}
        for item in a.sweep:
            k, vs = item.split("=")
            grid[k] = [_sweep_value(v) for v in vs.split(",")]
        print(json.dumps(model.sweep(p, grid, cohort, a.replicates, a.seed), indent=2))
    else:
        print(json.dumps(model.run(p, cohort, a.replicates, a.seed), indent=2))


def cmd_house_export(a):
    h = _house(a, False)
    hist = h.export(a.out, events_out=a.events, foreign=a.foreign)
    print(f"exported {len(hist['rounds'])} rounds, {len(hist['fighters'])} fighters to {a.out}")


PROVENANCE = """{marker}
This document was published by the qdojo house and its hash is on the Qubic
chain. Nothing above this line has changed since; the hash covers the body
only, which is why this block can name the tick it was published in.

  house      {house}
  published  tick {tick}
  signature  {tx}
  doc_hash   sha256("qdojo/doc/v0" + the body above) = {doc_hash}
  uri        {uri}

Check it yourself, from a clean copy of this file:

  qdojo doc verify llms.txt --node <any live node>

or by hand: cut everything from the marker line down, strip trailing blank
lines, append one newline, and sha256 it with the domain tag above. Then look
up the transaction on any Qubic explorer and read the 32 bytes after the
6-byte header: they are the same hash, signed by the house, in that tick.
"""


def cmd_house_sign_doc(a):
    """Put the house's name to a document by publishing its hash on chain."""
    h = _house(a, a.apply)
    plan = h.sign_doc(a.file, a.uri, apply=a.apply)
    if not a.apply:
        print(json.dumps(plan, indent=2))
        print("\nnothing sent. re-run with --apply to sign it on chain.")
        return
    block = PROVENANCE.format(marker=hashing.DOC_MARKER, house=plan["house"], tick=plan["tick"],
                              tx=plan["tx"], doc_hash=plan["doc_hash"], uri=plan["uri"])
    with open(a.file, encoding="utf-8") as f:
        body = hashing.doc_body(f.read()).rstrip() + "\n"
    with open(a.file, "w", encoding="utf-8") as f:
        f.write(body + "\n" + block)
    if a.out:
        # So the page can show the signature without anyone running a command.
        os.makedirs(a.out, exist_ok=True)
        docs = {}
        try:
            with open(os.path.join(a.out, "docs.json"), encoding="utf-8") as f:
                docs = json.load(f)
        except (OSError, ValueError):
            pass
        docs[os.path.basename(a.file)] = {k: plan[k] for k in ("house", "tick", "tx", "doc_hash", "uri")}
        with open(os.path.join(a.out, "docs.json"), "w", encoding="utf-8") as f:
            json.dump(docs, f, indent=2, sort_keys=True)
    print(f"signed {a.file} as {plan['house'][:8]}… in tick {plan['tick']}")
    print(f"  tx       {plan['tx']}")
    print(f"  doc_hash {plan['doc_hash']}")


def cmd_doc_verify(a):
    """Recompute a published document's hash and, with a node, check the chain."""
    import re
    with open(a.file, encoding="utf-8") as f:
        text = f.read()
    got = hashing.doc_hash(text).hex()
    claimed = dict(re.findall(r"^\s{2}(house|published|signature|doc_hash|uri)\s+(.+?)\s*$", text, re.M))
    if not claimed:
        sys.exit(f"qdojo: {a.file} carries no provenance block; it has never been signed")
    want = (claimed.get("doc_hash", "").split("= ")[-1]).strip()
    tick = int(claimed.get("published", "tick 0").split()[-1])
    tx, house = claimed.get("signature", ""), claimed.get("house", "")
    print(f"body hash  {got}")
    print(f"claimed    {want}")
    if got != want:
        sys.exit("qdojo: MISMATCH — the body has changed since it was signed")
    print("the body matches the hash in the document.")
    if not a.node:
        print("pass --node IP to also check the signature is on chain in that tick.")
        return
    ch = _chain(a, False)
    for o in ch.transactions_to(house, tick, tick):
        m = payload.try_decode(o.payload) if o.tx_id == tx else None
        if isinstance(m, payload.Doc) and m.doc_hash.hex() == got:
            print(f"on chain   tx {tx[:8]}… in tick {tick}, signed by {house[:8]}…  VERIFIED")
            return
    sys.exit(f"qdojo: no matching DOC from {house[:8]}… in tick {tick} on this node")


def cmd_house_lab(a):
    """What the self-evolving fighters actually did. Summaries and statistics
    only -- no tool source is ever published (docs/api.md)."""
    def kv(pairs):
        return dict(x.split("=", 1) for x in (pairs or []) if "=" in x)
    root = a.evo_dir or os.environ.get("QDOJO_EVO_DIR")
    if not lab.find_evo_dirs(root):
        print(f"no evo directories found at {root or lab.DEFAULT_EVO_DIR}; nothing to publish")
        return
    doc = lab.build(root, identities=kv(a.map), models=kv(a.model))
    if a.print_only:
        print(json.dumps(doc, indent=2, sort_keys=True))
        return
    os.makedirs(a.out, exist_ok=True)
    path = os.path.join(a.out, "lab.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, sort_keys=True, ensure_ascii=False)
    t = doc["totals"]
    print(f"lab: {t['bots']} bots, {t['kinds']} kinds, {t['tools']} tools, "
          f"{t['solves']} solves -> {path}")


def cmd_house_events(a):
    """Every dojo message in a tick or a round, in English. The same describe()
    the page uses, so this is both a debugging tool and a demo of the feature."""
    h = _house(a, False)
    names = {i: b["name"] for i, b in h.bows().items()}
    metas, riddles = {}, {}
    for rid in h.round_ids():
        metas[rid] = json.load(open(h._rpath(rid, "meta.json"), encoding="utf-8"))
        try:
            riddles[rid] = json.load(open(h._rpath(rid, "riddle.json"), encoding="utf-8"))
        except FileNotFoundError:
            riddles[rid] = {}
    recs = events.build(h.observed(), h.identity, h.tx_index(), h.payout_events(), names, metas, riddles,
                        foreign=a.foreign)
    recs = [r for r in recs if not r.get("foreign_only")
            and (a.tick is None or r["tick"] == a.tick)
            and (a.round is None or r.get("round_id") == a.round)]
    if a.text:
        for r in recs:
            print(f"{r['tick']}  {r['text']}")
    else:
        print(json.dumps(recs, indent=2))


def _cli_chain(a) -> bool:
    """True under `--chain cli`: the only case in which a bot command may go
    looking for qubic-cli. The default chain signs and probes in Python."""
    return getattr(a, "chain", "native") == "cli"


def _bot_defaults(a):
    """Fill --conf/--identity/--node (and --cli, under --chain cli) from the
    bot profile and node cache when they were not given, so `qdojo bot run`
    works after `qdojo bot init`."""
    prof = onboard.load_profile(a.state)
    if _cli_chain(a):
        try:
            a.cli = onboard.find_cli(a.cli if a.cli != "qubic-cli" else (prof.get("cli") or None))
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
        probe = nodes.cli_probe(a.cli) if _cli_chain(a) else nodes.native_probe()
        a.node = nodes.best_node(a.state, probe)
        print(f"node: {a.node} (auto-detected)", file=sys.stderr)
    if getattr(a, "solver", None) is None:
        a.solver = prof.get("solver")
        if not a.solver:
            sys.exit("qdojo: no solver: pass --solver, or run `qdojo bot setup` to record one")
    # setdefault, never overwrite: an explicitly exported PI_MODEL=x still wins.
    # A secret setting is copied from the variable it names, here, in-process.
    a._applied_env = settings.apply_env(prof, {})


def cmd_bot_init(a):
    """The bowing-in rite: signer, seed, name, node, mind, purse. Every stage
    verifies rather than printing, and every prompt has a flag, so a
    professional runs the whole thing on one non-interactive line."""
    seedconf.warn_leftovers(exclude=a.conf)
    wizard.init(a)


def cmd_bot_setup(a):
    """Provider and model only, for a fighter that already has a seed."""
    wizard.setup(a)


def _history_url(board: str) -> str:
    """history.json sits beside board.json. The same derivation evo.py makes."""
    if board.endswith("history.json"):
        return board
    return portable.sibling(board, "history.json")


def cmd_train(a):
    """Fight past rounds without fighting: no seed, no QU, no node, no signer.

    This is the first thing a newcomer should run. Everything it needs is
    already published, so it costs nothing and risks nothing.
    """
    src = _history_url(a.board or wizard.DEFAULT_BOARD)
    try:
        history = fetch_board(src)
    except (OSError, ValueError) as e:
        sys.exit(f"qdojo: could not read {src}: {e}")
    solver = a.solver or (onboard.load_profile(a.state) or {}).get("solver")
    if not solver:
        sys.exit("qdojo: no solver: pass --solver, or run `qdojo bot init` to choose one")
    settings.apply_env(onboard.load_profile(a.state) or {}, {})

    pool = training.settled_rounds(history)
    if not pool:
        sys.exit(f"qdojo: {src} has no settled rounds to train against yet")
    term.set_enabled(a.color)
    if not a.json:
        print(term.banner())
        print(term.rule("TRAINING FIGHT"))
        term.info("nothing is sent", "no seat is bought, no answer is committed, the chain never hears from you")
        term.info("the solver", " ".join(os.path.basename(x) for x in solver))

    out = []

    def show(at):
        out.append(at)
        if a.json:
            print(json.dumps(dataclasses.asdict(at)), flush=True)
            return
        mark = term.ok if at.correct else term.fail
        speed = f"+{at.solve_ticks}T" if at.solve_ticks is not None else "--"
        if at.error:
            term.fail(f"R{at.round_id} {at.belt}", at.error)
        elif at.correct and at.would_pay:
            place = f"{at.rank} of {at.rivals + 1}" if at.rivals else "uncontested"
            mark(f"R{at.round_id} {at.belt}", f"{speed}  {place}  would have taken {term.qu(at.would_pay)}"
                 + ("  — NOBODY SOLVED THIS ONE" if at.unsolved else ""))
        elif at.correct:
            why = at.why_unpriced or (f"{at.rank} of {at.rivals + 1}, off the money" if at.rank else "")
            mark(f"R{at.round_id} {at.belt}", f"{speed}  right  {why}")
        else:
            mark(f"R{at.round_id} {at.belt}", f"{speed}  wrong: said {at.answer!r}, the answer was {at.truth!r}")

    training.replay(history, list(solver), rounds=a.rounds, belt=a.belt or "",
                    round_ids=a.round or (), timeout=a.solver_timeout, on_attempt=show)

    card = training.scorecard(out)
    _save_training(a.state, card, out)
    if a.json:
        print(json.dumps({"scorecard": card}), flush=True)
        return
    rows = [term.kv("fought", str(card["fought"])),
            term.kv("solved", f"{card['solved']} of {card['fought']}")]
    if card["median_solve_ticks"] is not None:
        rows.append(term.kv("solve time", f"median {card['median_solve_ticks']} ticks, best {card['best_solve_ticks']}"))
    if card["missed_window"]:
        rows.append(term.kv("too slow", f"{card['missed_window']} right but after the window closed"))
    rows.append(term.kv("placed", f"{card['would_have_placed']} of {card['fought']} rounds"))
    rows.append(term.kv("purse", term.qu(card["would_have_earned"]) + "  (hypothetical)"))
    if card["unpriced"]:
        rows.append(term.kv("unpriced", f"{card['unpriced']} right, but the house's seed rules for those"))
        rows.append(term.kv("", "rounds are not fully published, so no purse is claimed"))
    print()
    print(term.box(rows, title="HOW YOU WOULD HAVE DONE"))
    if card["unsolved_taken"]:
        print()
        term.ok("unclaimed", f"you answered {len(card['unsolved_taken'])} round(s) NOBODY solved: "
                             + ", ".join(f"R{r}" for r in card["unsolved_taken"]))
    print()
    term.info("none of that was real", "no QU moved. when you want a seat: qdojo bot init")


def _save_training(state_dir, card, attempts):
    """So the local page can show a newcomer something before they have a
    single round on chain."""
    try:
        os.makedirs(state_dir, mode=0o700, exist_ok=True)
        path = os.path.join(state_dir, "training.json")
        doc = {"at": int(time.time()), "scorecard": card,
               "attempts": [dataclasses.asdict(x) for x in attempts]}
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(doc, f, indent=2, sort_keys=True)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except OSError:
        pass          # a scorecard we could not file is not worth failing over


def cmd_bot_dash(a):
    """Your cockpit, on 127.0.0.1 and nowhere else."""
    try:
        httpd, url = dash.serve(a.state, board=a.board or wizard.DEFAULT_BOARD,
                                port=a.port, read_only=a.read_only)
    except dash.DashError as e:
        sys.exit(f"qdojo: {e}")
    print(f"\n  your cockpit is up:\n\n    {url}\n")
    print("  it binds 127.0.0.1 only and serves nothing from your state directory.")
    print("  status, metrics, settings, training, prompts: a setting saved there is live on")
    print("  the bot's next poll, a prompt on the next round. ctrl-c to stop.\n")
    if getattr(a, "open", False):
        # Opt-in, because a browser opening on its own is a surprise. The
        # stdlib asks the OS for its default browser (os.startfile on
        # Windows), and a machine without one is not an error: the URL is
        # printed above either way.
        import webbrowser
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("  stopped.")


def cmd_bot_settings(a):
    """Your fighter's knobs, as its manifest declares them (docs/api.md,
    'Settings'). Reads and writes bot.json only; needs no seed, no node."""
    try:
        if a.action == "set":
            row = settings.set_value(a.state, a.key, a.value)
            shown = f"${row['env_name']}" if row["type"] == "secret" else row["value"]
            print(f"{a.key} = {shown}  (a running bot picks it up on its next poll)")
            return
        if a.action == "unset":
            settings.unset_value(a.state, a.key)
            print(f"{a.key} unset")
            return
        if a.action == "describe":
            print(json.dumps(settings.describe(a.state), indent=2))
            return
        rows = settings.rows(a.state)
    except settings.SettingsError as e:
        sys.exit(f"qdojo: {e}")
    if a.json:
        print(json.dumps(rows, indent=2))
        return
    if not rows:
        doc = settings.describe(a.state)
        print(f"no settings: {doc['shipped'] or 'the solver has no manifest'} and {doc['user']} declare none.")
        print("declare one in the second file (docs/api.md, 'Settings').")
        return

    def shown(r):
        if r["type"] == "secret":
            name = r.get("env_name")
            return f"${name} ({'set' if r.get('set_in_env') else 'NOT set'})" if name else "—"
        return "—" if r.get("value") is None else str(r["value"])

    def default(r):
        d = r.get("default")
        if r["type"] == "secret":
            return f"${d}" if d else "—"
        return "—" if d is None else str(d)

    table = [(r["key"], shown(r), default(r), r["source"],
              (r.get("help") or "") + (" (not in the manifest)" if r.get("unknown") else "")) for r in rows]
    widths = [max(len(t[i]) for t in [("KEY", "VALUE", "DEFAULT", "SOURCE", "")] + table) for i in range(4)]
    room = term.width() - sum(widths) - 8
    # Help beside the row when it fits, under it when the terminal is narrow:
    # a help text cut to thirty characters explains nothing.
    beside = room >= 48
    print("  ".join(h.ljust(w) for h, w in zip(("KEY", "VALUE", "DEFAULT", "SOURCE"), widths)) + ("  HELP" if beside else ""))
    for row in table:
        line = "  ".join(v.ljust(w) for v, w in zip(row[:4], widths))
        if beside:
            print(line + "  " + term.fit(row[4], room))
        else:
            print(line)
            if row[4]:
                print("    " + term.fit(row[4], term.width() - 4))
    print(f"\nchange one: qdojo bot settings set KEY VALUE   (a running bot picks it up on its next poll)")
    doc = settings.describe(a.state)
    print(f"declared in: {doc['shipped'] or '(no shipped manifest)'}\n         and {doc['user']}")


def cmd_prompts(a):
    """Where your fighter's prompts are, and how to get an editable copy.

    A prompt-driven fighter IS these files. The dojo runs a solver as a fresh
    process every riddle, so a save is live on the very next round.
    """
    if a.sub == "install":
        done = P.install(a.state, force=a.force)
        if done:
            for path in done:
                print(f"copied {path}")
            print("\nedit any of those; the next round uses them.")
        else:
            print(f"already there: {os.path.join(a.state, 'prompts')}  (--force to overwrite)")
        return
    if a.sub == "show":
        text, path = P.load(a.name, state_dir=a.state)
        print(f"# {path}\n")
        print(text)
        return
    rows = P.listing(a.state)
    if not rows:
        sys.exit("qdojo: no prompts found; run `qdojo prompts install`")
    for r in rows:
        where = "yours" if os.path.abspath(a.state) in r["path"] else "shipped"
        print(f"{r['name']:22} {where:8} {r['path']}")
    print("\nedit one and the next round uses it. `qdojo prompts install` puts an editable copy")
    print("under your state dir, so a git pull never fights your edits.")


def cmd_nodes(a):
    if _cli_chain(a):
        probe = nodes.cli_probe(onboard.find_cli(a.cli if a.cli != "qubic-cli" else None))
    else:
        probe = nodes.native_probe()
    found = nodes.discover(probe)
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
        print(f"\nabsence of {a.name} confirmed by {plan['checked_nodes']} node(s).", file=sys.stderr)
        print("PLAN ONLY. The issuance fee above goes to Qx's shareholders and is not refundable. Re-run with --apply.", file=sys.stderr)
        return
    res = sh.issue(a.name, a.count)
    print(f"issue {res.tx_id} scheduled for tick {res.scheduled_tick}; confirming…")
    for _ in range(90):
        try:
            ok = sh.chain.confirm(res.tx_id, res.scheduled_tick); break
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
    doc = fetch_board(portable.sibling(a.board, "fighters.json"))
    me = next((f for f in doc.get("fighters", []) if f["identity"] == a.identity), None)
    if me is None:
        sys.exit(f"qdojo: {a.identity[:8]}… has not fought at this house yet")
    print(json.dumps(me, indent=2))


def cmd_bot_run(a):
    throwaway = _take_ephemeral(a)
    seedconf.warn_leftovers(exclude=a.conf)
    with seedconf.ephemeral(throwaway):
        _bot_defaults(a)
        chain = _chain(a, True)
        recorder = cockpit.Recorder(a.state)
        bot = Bot(chain, a.state, a.solver, name=a.name, max_stake=a.max_stake, solver_timeout=a.solver_timeout,
                  strategy_cmd=a.strategy, recorder=recorder)
        log = cockpit.open_log(a.state)
        beat = cockpit.Heartbeat(a.state, a.interval, board=a.board, solver=a.solver)
        applied = getattr(a, "_applied_env", {})
        looked = 0.0

        def say(line, err=False):
            print(time.strftime("%H:%M:%S"), line, file=sys.stderr if err else sys.stdout, flush=True)
            log.info(line)

        try:
            while True:
                try:
                    # A setting saved from the cockpit or `bot settings set` is live
                    # on this poll: the solver is a fresh process and inherits it.
                    applied = settings.apply_env(wizard.load_profile(a.state), applied)
                    board = fetch_board(a.board)
                    if a.name:
                        bot.house = board["house"]
                        bot.bow()
                    acts = bot.step(board)
                    for line in acts:
                        say(line)
                    beat.beat(board=board, actions=acts)
                    if recorder.pending() and time.time() - looked > cockpit.HISTORY_EVERY:
                        looked = time.time()
                        for row in recorder.settle_from_history(fetch_board(_history_url(a.board)), a.identity):
                            say(f"round {row['round_id']}: settled {row['verdict']}, earned {row['earned']}, net {row['net']}")
                except (Unknown, ChainError, BotError, OSError, ValueError) as e:
                    say(f"warning: {e}", err=True)
                    beat.beat(error=e)
                if a.once:
                    return
                time.sleep(a.interval)
        finally:
            beat.close()


def _age(seconds) -> str:
    if seconds is None:
        return "—"
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m{s % 60:02d}s"
    return f"{s // 3600}h{(s % 3600) // 60:02d}m"


def cmd_bot_status(a):
    """Is a bot running for this state dir, and what is it doing. Reads the
    heartbeat, rounds.json and the metrics; needs no seed and no node."""
    st = cockpit.status(a.state)
    if a.json:
        print(json.dumps(st, indent=2))
        return
    term.set_enabled(a.color)
    if st["state"] == "running":
        head = term.c("RUNNING", "bgreen", "bold") + f"   pid {st['pid']} · heartbeat {_age(st['age'])} ago · "                f"polls every {st['interval']:g}s · up {_age(time.time() - (st['started_at'] or time.time()))}"
    elif st["state"] == "stale":
        head = term.c("STALE", "bred", "bold") + f"   pid {st['pid']} last beat {_age(st['age'])} ago: it died "                f"without cleaning up, or the machine slept"
    else:
        head = term.c("IDLE", "byellow", "bold") + f"   no bot is running for {a.state}"
    rows = [term.kv("bot", head)]
    if st["board"]:
        rows.append(term.kv("board", st["board"]))
    if st["solver"]:
        rows.append(term.kv("solver", " ".join(st["solver"])))
    if st["tick"] is not None:
        rows.append(term.kv("tick", str(st["tick"])))
    for r in st["rounds"]:
        what = " · ".join(x for x in (r.get("belt"), r.get("kind") or r.get("title"), r.get("state")) if x)
        rows.append(term.kv(f"R{r['round_id']}", what or "on the board"))
        rows.append(term.kv("  did", r["did"]))
    if not st["rounds"]:
        rows.append(term.kv("rounds", "none seen yet"))
    for act in st["last_actions"][-3:]:
        rows.append(term.kv("last", time.strftime("%H:%M:%S", time.localtime(act["at"])) + " " + act["text"]))
    if st["last_error"]:
        rows.append(term.kv("warning", time.strftime("%H:%M:%S", time.localtime(st["last_error"]["at"])) + " "
                            + st["last_error"]["text"]))
    print(term.box(rows, title="YOUR BOT"))


def cmd_bot_metrics(a):
    """What this machine recorded about every round its bot saw."""
    m = cockpit.summary(a.state, last=a.last)
    if a.json:
        print(json.dumps(m, indent=2))
        return
    term.set_enabled(a.color)
    if not m["rounds_seen"]:
        print(f"no rounds recorded in {os.path.join(a.state, cockpit.METRICS)} yet; `qdojo bot run` writes it.")
        return
    pc = lambda x: "—" if x is None else f"{round(x * 100)}%"
    rows = [term.kv("rounds", f"{m['rounds_seen']} seen · {m['entered']} entered · {m['skipped']} sat out · "
                              f"{m['pending']} awaiting settlement"),
            term.kv("solved", f"{m['solved']} of {m['settled']} settled ({pc(m['solve_rate'])}) · "
                              f"{m['wins']} paid ({pc(m['win_rate'])})"),
            term.kv("solve time", "—" if m["avg_solve_seconds"] is None else
                    f"avg {m['avg_solve_seconds']}s · best {m['best_solve_seconds']}s"),
            term.kv("purse", f"staked {term.qu(m['staked'])} · earned {term.qu(m['earned'])} · "
                             f"net {term.qu(m['net'])}" + (f" · bond held {term.qu(m['bond_held'])}" if m["bond_held"] else "")),
            term.kv("streak", f"{m['streak']:+d} (best {m['best_streak']})"),
            term.kv("solver", f"failed on {m['solver_failed']} round(s)")]
    print(term.box(rows, title="THIS MACHINE"))
    if m["by_kind"]:
        print()
        print("KIND" + " " * 38 + "SEEN  ENTERED  SETTLED  SOLVED  RATE")
        for k, b in sorted(m["by_kind"].items(), key=lambda kv: -kv[1]["seen"]):
            print(f"{term.fit(k, 40):40}  {b['seen']:4}  {b['entered']:7}  {b['settled']:7}  {b['solved']:6}  {pc(b['solve_rate'])}")
    if m["last"]:
        print()
        print("ROUND  BELT    KIND                          VERDICT     ANSWER        SOLVE   STAKE   NET")
        for r in m["last"]:
            state = r.get("verdict") or ("sat out" if r.get("skipped") else ("pending" if r.get("entered") else "seen"))
            ans = "—" if r.get("answer") is None else str(r["answer"])[:12]
            took = "—" if r.get("solver_seconds") is None else f"{r['solver_seconds']}s"
            net = "—" if r.get("net") is None else f"{r['net']:+,}"
            print(f"R{r['round_id']:<5} {str(r.get('belt') or '—'):7} {term.fit(r.get('kind') or '—', 29):29} "
                  f"{state:11} {ans:13} {took:7} {str(r.get('stake') or 0):7} {net}")


def cmd_bot_log(a):
    """The tail of bot run's own log."""
    lines = cockpit.log_tail(a.state, a.n)
    if not lines:
        print(f"no log at {os.path.join(a.state, cockpit.LOG)} yet; `qdojo bot run` writes it.")
        return
    for line in lines:
        print(line)


def build_parser():
    p = argparse.ArgumentParser(prog="qdojo", description="A dojo where AI bots compete for real QU.")
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("--chain", choices=("native", "cli"),
                   default=os.environ.get("QDOJO_CHAIN", "native"),
                   help="native (default: pure Python, no binary) or cli (via qubic-cli)")
    p.add_argument("--cli", default=os.environ.get("QUBIC_CLI", "qubic-cli"),
                   help="path to qubic-cli, read only under --chain cli; a bot never needs the binary")
    p.add_argument("--node", default=os.environ.get("QDOJO_NODE"), help="node IP[:PORT] for reads and signing")
    p.add_argument("--conf", default=os.environ.get("QDOJO_CONF"), help="0600 conf with one seed= line")
    p.add_argument("--identity", default=os.environ.get("QDOJO_IDENTITY"), help="identity the conf signs as")
    p.add_argument("--schedule-offset", type=int, default=20)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("payload").add_subparsers(dest="sub", required=True)
    d = s.add_parser("decode"); d.add_argument("hex"); d.set_defaults(fn=cmd_payload_decode)

    s = sub.add_parser("doc").add_subparsers(dest="sub", required=True)
    d = s.add_parser("verify", help="recheck a published document against its on-chain signature")
    d.add_argument("file")
    # Also accepted here, not only before the subcommand: argparse will not take
    # a parent option after a subcommand, and `doc verify FILE --node IP` is the
    # form we published. dest collides with the global on purpose -- last wins,
    # and either position means the same thing.
    # SUPPRESS, so that when it is absent it does NOT overwrite the value the
    # global --node already put in the namespace.
    d.add_argument("--node", default=argparse.SUPPRESS,
                   help="a live node, to check the signature is really on chain")
    d.set_defaults(fn=cmd_doc_verify)

    s = sub.add_parser("riddle").add_subparsers(dest="sub", required=True)
    d = s.add_parser("hash"); d.add_argument("file"); d.set_defaults(fn=cmd_riddle_hash)
    d = s.add_parser("list", help="list available challenge families by belt")
    d.add_argument("--pack", choices=riddles.PACKS, default="classic"); d.set_defaults(fn=cmd_riddle_list)
    d = s.add_parser("sample", help="generate an offline practice riddle; public fields by default")
    d.add_argument("kind"); d.add_argument("--rng-seed", type=int, default=None)
    d.add_argument("--round-id", type=int, default=1)
    d.add_argument("--with-answer", action="store_true", help="include the answer for a local authored fixture")
    d.set_defaults(fn=cmd_riddle_sample)

    hp = sub.add_parser("house")
    hp.add_argument("--data", default=os.environ.get("QDOJO_DATA", "private/house"))
    hp.add_argument("--rake-bps", type=int, default=int(os.environ.get("QDOJO_RAKE_BPS", "0")))
    hp.add_argument("--seed", type=int, default=int(os.environ.get("QDOJO_SEED_PER_ROUND", "0")))
    hp.add_argument("--uri-base", default=os.environ.get("QDOJO_URI_BASE", ""))
    hp.add_argument("--dev-identity", default=os.environ.get("QDOJO_DEV_IDENTITY", ""), help="who receives the dev/team rake share")
    hp.add_argument("--rake-house-bps", type=int, default=int(os.environ.get("QDOJO_RAKE_HOUSE_BPS", "10000")))
    hp.add_argument("--rake-dev-bps", type=int, default=int(os.environ.get("QDOJO_RAKE_DEV_BPS", "0")))
    hp.add_argument("--rake-share-bps", type=int, default=int(os.environ.get("QDOJO_RAKE_SHARE_BPS", "0")))
    s = hp.add_subparsers(dest="sub", required=True)
    d = s.add_parser("publish"); d.add_argument("riddle"); d.add_argument("--entry-fee", type=int, required=True)
    d.add_argument("--commit-window", type=int, default=600); d.add_argument("--reveal-window", type=int, default=300)
    d.add_argument("--house-seed", type=int, default=None)
    d.add_argument("--payout-mode", choices=sorted(payload.MODE_NAMES.values()), default="first")
    d.add_argument("--match-bps", type=int, default=10000, help="house seed = min(cap, stakes*bps/10000); 0 = fixed seed")
    d.add_argument("--belt", default="", help="the riddle's belt (white..blue); empty = no belt gate")
    d.add_argument("--sensei", action="store_true", help="allow sensei seats from above the belt")
    d.set_defaults(fn=cmd_house_publish)
    d = s.add_parser("confirm"); d.add_argument("round", type=int); d.set_defaults(fn=cmd_house_confirm)
    d = s.add_parser("collect"); d.add_argument("--rescan", help="TICK-TICK: re-read a past range"); d.set_defaults(fn=cmd_house_collect)
    d = s.add_parser("settle"); d.add_argument("round", type=int); d.add_argument("--apply", action="store_true")
    d.add_argument("--no-collect", dest="collect", action="store_false"); d.set_defaults(fn=cmd_house_settle)
    d = s.add_parser("export"); d.add_argument("--out", default="apps/web/data")
    d.add_argument("--no-events", dest="events", action="store_false", help="skip the per-tick event shards")
    d.add_argument("--foreign", choices=["count", "list", "drop"], default="count",
                   help="transfers to the house carrying no dojo message")
    d.set_defaults(fn=cmd_house_export)
    d = s.add_parser("sign-doc", help="publish a document's hash on chain: the house's signature and its date")
    d.add_argument("file"); d.add_argument("--uri", required=True, help="where the document is published")
    d.add_argument("--apply", action="store_true"); d.add_argument("--out", default="apps/web/data")
    d.set_defaults(fn=cmd_house_sign_doc)
    d = s.add_parser("lab", help="what the self-evolving fighters learned (summaries only, never tool source)")
    d.add_argument("--evo-dir"); d.add_argument("--out", default="apps/web/data")
    d.add_argument("--map", action="append", metavar="NAME=IDENTITY", help="tie a bot directory to its chain identity")
    d.add_argument("--model", action="append", metavar="NAME=MODEL")
    d.add_argument("--print", dest="print_only", action="store_true")
    d.set_defaults(fn=cmd_house_lab)
    d = s.add_parser("events", help="every dojo message in a tick or a round, decoded to English")
    d.add_argument("--tick", type=int); d.add_argument("--round", type=int)
    d.add_argument("--text", action="store_true", help="just the sentences")
    d.add_argument("--foreign", choices=["count", "list", "drop"], default="count")
    d.set_defaults(fn=cmd_house_events)
    d = s.add_parser("distribute-shareholders", help="pay the accrued shareholder rake pool via QUtil")
    d.add_argument("asset"); d.add_argument("--apply", action="store_true"); d.set_defaults(fn=cmd_house_distribute)
    d = s.add_parser("spar", help="generated riddles, rounds back to back, metrics per round")
    d.add_argument("--riddle-pack", choices=riddles.PACKS, default="classic",
                   help="opt-in challenge pool; qubic supports orange,green,blue only")
    d.add_argument("--rounds", type=int, default=10); d.add_argument("--belts", default="white,yellow,orange,green,blue")
    _add_fee_flags(d); d.add_argument("--commit-window", type=int, default=300)
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
    d.add_argument("--sensei", action="store_true", help="let a fighter sit below its belt: it plays for the sensei pot, no belt points")
    d.add_argument("--ephemeral-conf", metavar="PATH",
                   help="a throwaway seed conf: sign with it, shred it when this run exits (never a conf you keep)")
    d.set_defaults(fn=cmd_house_spar)
    d = s.add_parser("resume", help="drive a round left open by a dead supervisor to settlement")
    d.add_argument("round", type=int); d.add_argument("--entry-fee", type=int, default=1000)
    d.add_argument("--out", default="apps/web/data"); d.add_argument("--poll", type=int, default=15)
    d.set_defaults(fn=cmd_house_resume)
    d = s.add_parser("metrics"); d.set_defaults(fn=cmd_house_metrics)
    d = s.add_parser("model", help="offline model of the mechanics through the real evaluator and ladder (house-side)")
    d.add_argument("--rounds", type=int, default=200); d.add_argument("--replicates", type=int, default=10); d.add_argument("--seed", type=int, default=1)
    _add_fee_flags(d); d.add_argument("--seed-cap", type=int, default=5000)
    d.add_argument("--match-bps", type=int, default=10000); d.add_argument("--rake-bps", type=int, default=0)
    d.add_argument("--payout-mode", choices=sorted(payload.MODE_NAMES.values()), default="podium")
    d.add_argument("--bond-bps", type=int, default=5000); d.add_argument("--bond-rounds", type=int, default=3)
    d.add_argument("--min-players", type=int, default=3); d.add_argument("--no-ladder", action="store_true")
    d.add_argument("--start-balance", type=int, default=20000)
    d.add_argument("--gate", choices=["strict", "soft", "handicap", "sensei"], default="strict")
    d.add_argument("--season", type=int, default=0, help="reset the ladder every N rounds")
    d.add_argument("--demand", choices=["none", "ev"], default="none",
                   help="none: every eligible fighter sits at any price; ev: only when its own expected value is >= 0 (what makes --entry-fee auto mean anything)")
    d.add_argument("--refill", action="store_true", help="owners top a broke fighter back up to --start-balance (their money, not the house's)")
    d.add_argument("--target-pot", type=int, default=0, help="the corollary: seed_cap = max(0, target_pot - target * fee); 0 = fixed --seed-cap")
    d.add_argument("--target-pot-taper", type=int, default=0, help="rounds over which --target-pot declines linearly to 0")
    d.add_argument("--cohort", help="JSON list of archetypes"); d.add_argument("--calibrate", help="a fighters.json to derive archetypes from")
    d.add_argument("--no-house-fighters", action="store_true", help="with --calibrate: leave the house-funded fighters out")
    d.add_argument("--clones", type=int, default=1, help="with --calibrate: copies of each measured fighter")
    d.add_argument("--npcs", help="with --calibrate: comma-separated house-funded identities (names are untrusted)")
    d.add_argument("--sweep", nargs="+", help="param=v1,v2,... (e.g. match_bps=0,5000,10000 bond_bps=0,5000)")
    d.set_defaults(fn=cmd_house_model)

    pp = sub.add_parser("prompts", help="your fighter's prompt files: what they are and where")
    pp.add_argument("--state", default=os.path.expanduser("~/.qdojo/bot"))
    ps = pp.add_subparsers(dest="sub")
    ps.add_parser("list")
    d = ps.add_parser("install", help="copy the shipped prompts somewhere you can edit them")
    d.add_argument("--force", action="store_true", help="overwrite your edits with the originals")
    d = ps.add_parser("show"); d.add_argument("name")
    pp.set_defaults(fn=cmd_prompts, sub="list", force=False, name="")

    tp = sub.add_parser("train", help="fight past rounds for nothing: no seed, no QU, no node")
    tp.add_argument("--board", help="the house to train against (default: the published one)")
    tp.add_argument("--state", default=os.path.expanduser("~/.qdojo/bot"))
    tp.add_argument("--solver", nargs="+", help="your solver; defaults to the one in your profile")
    tp.add_argument("--rounds", type=int, default=10, help="how many recent rounds to fight")
    tp.add_argument("--belt", help="only rounds at this belt")
    tp.add_argument("--round", action="append", type=int, help="a specific round, repeatable")
    tp.add_argument("--solver-timeout", type=float, default=60.0)
    tp.add_argument("--json", action="store_true", help="one JSON record per attempt")
    tp.add_argument("--no-color", dest="color", action="store_false", default=None)
    tp.set_defaults(fn=cmd_train)

    bp = sub.add_parser("bot")
    bp.add_argument("--state", default=os.path.expanduser("~/.qdojo/bot"), help="bot state dir (seed conf, profile, node cache)")
    s = bp.add_subparsers(dest="sub", required=True)

    def _setup_flags(d, init=False):
        """Every prompt in the rite has a flag, so the whole thing is one line.
        There is deliberately NO flag that takes an API key: a key on argv lands
        in the shell history and in `ps`. --key-env names the variable instead."""
        d.add_argument("--solver-kind", choices=wizard.SOLVER_KEYS,
                       help="what thinks for your fighter: a plain script, a prompt, or your own program")
        d.add_argument("--provider", choices=wizard.PROVIDER_KEYS)
        d.add_argument("--model", help="a model id -- never a key")
        d.add_argument("--base-url", help="an OpenAI-compatible endpoint, e.g. a local Ollama")
        d.add_argument("--key-env", metavar="NAME", help="the NAME of the env var holding your key")
        d.add_argument("--solver", nargs="+")
        d.add_argument("--env", action="append", metavar="NAME=VALUE", help="refused if NAME looks secret")
        d.add_argument("--pi")
        d.add_argument("--board"); d.add_argument("--seat-fee", type=int)
        d.add_argument("--skip-probe", action="store_true", help="do not make the test call")
        d.add_argument("--probe-timeout", type=float, default=90.0)
        d.add_argument("--yes", "-y", action="store_true", help="accept every default, never prompt")
        d.add_argument("--no-color", dest="color", action="store_false", default=None)
        if init:
            # --full and --no-setup are one another's negation on the same dest.
            # --full is what README, docs/api.md and the on-chain-signed llms.txt
            # already tell people to run, so it has to mean something: it means
            # the default, the whole rite. Deleting it from the docs would have
            # meant re-signing llms.txt to fix a flag we could simply honour.
            d.add_argument("--full", dest="no_setup", action="store_false", default=False,
                           help="run the whole rite (the default)")
            d.add_argument("--no-setup", dest="no_setup", action="store_true",
                           help="seed and node only, skip provider and model")
        return d
    d = s.add_parser("init", help="the bowing-in rite: seed, identity, live nodes, provider, model, purse")
    d.add_argument("--name"); d.add_argument("--seed-from-stdin", action="store_true", help="import an existing seed instead of creating one")
    _setup_flags(d, init=True).set_defaults(fn=cmd_bot_init)
    d = s.add_parser("setup", help="choose a provider and a model for a fighter that already has a seed")
    d.add_argument("--name")
    _setup_flags(d).set_defaults(fn=cmd_bot_setup)
    d = s.add_parser("dash", help="your fighter's stats and prompts, on 127.0.0.1 only")
    d.add_argument("--port", type=int, default=7777)
    d.add_argument("--board", help="the house to read your published record from")
    d.add_argument("--read-only", action="store_true", help="show everything, save nothing")
    d.add_argument("--open", action="store_true", help="also open the page in your default browser")
    d.set_defaults(fn=cmd_bot_dash)
    d = s.add_parser("settings", help="your fighter's knobs: list, set KEY VALUE, unset KEY, describe")
    d.add_argument("--json", action="store_true", help="the rows as JSON")
    ss = d.add_subparsers(dest="action")
    x = ss.add_parser("set", help="validate against the manifest and write bot.json")
    x.add_argument("key"); x.add_argument("value")
    x = ss.add_parser("unset", help="forget a stored value; the default applies again")
    x.add_argument("key")
    ss.add_parser("describe", help="the merged manifest as JSON, with current values")
    d.set_defaults(fn=cmd_bot_settings, action="", key="", value="")
    d = s.add_parser("status", help="is a bot running for this state dir, and what is it doing")
    d.add_argument("--json", action="store_true"); d.add_argument("--no-color", dest="color", action="store_false", default=None)
    d.set_defaults(fn=cmd_bot_status)
    d = s.add_parser("metrics", help="what this machine recorded about every round its bot saw")
    d.add_argument("--json", action="store_true"); d.add_argument("--last", type=int, default=20, help="rows to show")
    d.add_argument("--no-color", dest="color", action="store_false", default=None)
    d.set_defaults(fn=cmd_bot_metrics)
    d = s.add_parser("log", help="the tail of bot run's log")
    d.add_argument("-n", type=int, default=50, help="lines")
    d.set_defaults(fn=cmd_bot_log)
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
    d = s.add_parser("run"); d.add_argument("--board", required=True); d.add_argument("--solver", nargs="+")
    d.add_argument("--name")
    d.add_argument("--max-stake", type=int); d.add_argument("--solver-timeout", type=float, default=60.0)
    d.add_argument("--interval", type=float, default=5.0); d.add_argument("--once", action="store_true")
    d.add_argument("--strategy", nargs="+", help="program deciding whether to enter a round (docs/api.md)")
    d.add_argument("--ephemeral-conf", metavar="PATH",
                   help="a throwaway seed conf: sign with it, shred it when this run exits (never a conf you keep)")
    d.set_defaults(fn=cmd_bot_run)

    return p


def main(argv=None):
    portable.tolerant_stdio()      # a redirected Windows stdout must not die on a tick mark
    a = build_parser().parse_args(argv)
    try:
        a.fn(a)
    except (HouseError, BotError, ChainError, R.RiddleError, riddles.RiddleGenError, payload.PayloadError, onboard.OnboardError, SharesError, term.TermError, RuntimeError) as e:
        sys.exit(f"qdojo: {e}")


if __name__ == "__main__":
    main()
