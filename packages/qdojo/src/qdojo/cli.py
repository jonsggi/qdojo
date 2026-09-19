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
from . import nodes, onboard, spar, events, lab, wizard, term, training, prompts as P, dash
from . import seedconf
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
    fallbacks = tuple(x for x in (os.environ.get("QDOJO_FALLBACK_NODES", "") or "").split(",") if x)
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


def cmd_house_spar(a):
    throwaway = _take_ephemeral(a)
    seedconf.warn_leftovers(exclude=a.conf)
    with seedconf.ephemeral(throwaway):
        h = _house(a, True)
        sp = spar.Spar(h, a.belts.split(","), a.entry_fee, a.commit_window, a.reveal_window,
                       riddle_dir=os.path.join(a.data, "riddles"), web_out=a.out,
                       metrics_path=os.path.join(a.data, "metrics.jsonl"), seed=a.rng_seed, poll=a.poll,
                       match_bps=a.match_bps, min_players=a.min_players, lobby_window=a.lobby_window,
                       npcs=[x for x in (a.npcs or "").split(",") if x], npc_rounds=a.npc_rounds,
                       bond_bps=a.bond_bps, bond_rounds=a.bond_rounds, skip_dead=not a.dead_tables, sensei=a.sensei,
                       riddle_pack=a.riddle_pack)
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
    """Pay the accrued shareholder rake pool to the house asset's holders via QUtil."""
    from .shares import Shares
    h = _house(a, a.apply)
    pool = h.state().get("shareholder_pool", 0)
    print(f"shareholder pool: {pool} QU")
    if pool <= 0:
        print("nothing to distribute"); return
    sh = Shares(h.chain)
    plan = sh.plan_dividend(a.asset, pool)
    print(json.dumps(plan, indent=2))
    if not a.apply:
        print("\nPLAN ONLY. Re-run with --apply to distribute.", file=sys.stderr); return
    res = sh.pay_dividend(a.asset, pool)
    st = h.state(); st["shareholder_pool"] = 0; st["shareholder_paid"] = st.get("shareholder_paid", 0) + pool; h._save_state(st)
    print(f"distributed {pool} to holders of {a.asset}: {res.tx_id} tick {res.scheduled_tick}")


def cmd_house_model(a):
    from . import model
    p = model.Params(rounds=a.rounds, entry_fee=a.entry_fee, seed_cap=a.seed_cap, match_bps=a.match_bps,
                     rake_bps=a.rake_bps, payout_mode={v: k for k, v in payload.MODE_NAMES.items()}[a.payout_mode],
                     bond_bps=a.bond_bps, bond_rounds=a.bond_rounds, min_players=a.min_players,
                     ladder=not a.no_ladder, start_balance=a.start_balance, gate=a.gate, season=a.season,
                     rake_house_bps=a.rake_house_bps, rake_dev_bps=a.rake_dev_bps, rake_share_bps=a.rake_share_bps)
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
    if getattr(a, "solver", None) is None:
        a.solver = prof.get("solver")
        if not a.solver:
            sys.exit("qdojo: no solver: pass --solver, or run `qdojo bot setup` to record one")
    # setdefault, never overwrite: an explicitly exported PI_MODEL=x still wins.
    for k, v in (prof.get("solver_env") or {}).items():
        os.environ.setdefault(k, str(v))


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
    return board.rsplit("/", 1)[0] + "/history.json" if "/" in board else "history.json"


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
    for k, v in ((onboard.load_profile(a.state) or {}).get("solver_env") or {}).items():
        os.environ.setdefault(k, str(v))

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
    """Your fighter's page, on 127.0.0.1 and nowhere else."""
    try:
        httpd, url = dash.serve(a.state, board=a.board or wizard.DEFAULT_BOARD,
                                port=a.port, read_only=a.read_only)
    except dash.DashError as e:
        sys.exit(f"qdojo: {e}")
    print(f"\n  your fighter page is up:\n\n    {url}\n")
    print("  it binds 127.0.0.1 only and serves nothing from your state directory.")
    print("  edit a prompt there and the next round uses it. ctrl-c to stop.\n")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("  stopped.")


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
    throwaway = _take_ephemeral(a)
    seedconf.warn_leftovers(exclude=a.conf)
    with seedconf.ephemeral(throwaway):
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


def build_parser():
    p = argparse.ArgumentParser(prog="qdojo", description="A dojo where AI bots compete for real QU.")
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("--chain", choices=("native", "cli"),
                   default=os.environ.get("QDOJO_CHAIN", "native"),
                   help="native (default: pure Python, no binary) or cli (via qubic-cli)")
    p.add_argument("--cli", default=os.environ.get("QUBIC_CLI", "qubic-cli"),
                   help="path to qubic-cli, used only by --chain cli")
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
    d.add_argument("--sensei", action="store_true", help="let a fighter sit below its belt, capped to its stake, no belt points")
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
    d.add_argument("--entry-fee", type=int, default=1000); d.add_argument("--seed-cap", type=int, default=5000)
    d.add_argument("--match-bps", type=int, default=10000); d.add_argument("--rake-bps", type=int, default=0)
    d.add_argument("--payout-mode", choices=sorted(payload.MODE_NAMES.values()), default="podium")
    d.add_argument("--bond-bps", type=int, default=5000); d.add_argument("--bond-rounds", type=int, default=3)
    d.add_argument("--min-players", type=int, default=3); d.add_argument("--no-ladder", action="store_true")
    d.add_argument("--start-balance", type=int, default=20000)
    d.add_argument("--gate", choices=["strict", "soft", "handicap", "sensei"], default="strict")
    d.add_argument("--season", type=int, default=0, help="reset the ladder every N rounds")
    d.add_argument("--cohort", help="JSON list of archetypes"); d.add_argument("--calibrate", help="a fighters.json to derive archetypes from")
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
    d.set_defaults(fn=cmd_bot_dash)
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
    a = build_parser().parse_args(argv)
    try:
        a.fn(a)
    except (HouseError, BotError, ChainError, R.RiddleError, riddles.RiddleGenError, payload.PayloadError, onboard.OnboardError, SharesError, term.TermError, RuntimeError) as e:
        sys.exit(f"qdojo: {e}")


if __name__ == "__main__":
    main()
