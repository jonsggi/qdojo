"""Chain-shaped combat commands: queue, duel, cup, fighter, withdraw, bot, doctor.

Until a reviewed deployment manifest names a real network, contract and
procedure IDs, these commands run against the local devnet (fake QU,
synthetic identities from labels). They never read a seed, sign, or send a
real transaction; `doctor` says so explicitly.
"""
from __future__ import annotations

import json
import os
import shlex
import stat
import sys
from pathlib import Path

from . import engine, evaluate as E, export, npcs, planner
from .bot import Bot, Budget, planner_chooser, policy_chooser
from .codec import Code, Op
from .devnet import Devnet, result_text, roles
from .rules import candidate_1
from .sim import identity

FORMATS = {"single": 0, "bo3": 1, "bo5": 2}


def _home() -> Path:
    return Path(os.environ.get("QDOJO_COMBAT_HOME", os.path.expanduser("~/.qdojo/combat")))


def _net(a) -> Devnet:
    return Devnet(Path(a.devnet) if a.devnet else _home() / "devnet")


def _fid(text: str) -> bytes:
    if len(text) == 64:
        try:
            return bytes.fromhex(text)
        except ValueError:
            pass
    return identity("fighter:" + text)


def _signer(a) -> bytes:
    return identity("owner:" + a.as_label) if a.as_label else None


def _out(a, obj, text):
    print(json.dumps(obj) if getattr(a, "json", False) else text)


def _send(a, net: Devnet, who: bytes, op: Op, amount=0, **fields):
    r = net.world.send(who, op, amount, **fields)
    net.save()
    _out(a, {"code": r.code.name, "refunded": r.refunded, "detail": r.detail, "data": r.data,
             "tick": net.world.tick}, f"{op.name.lower()}: {result_text(r)} {r.data or ''}".strip())
    if r.code not in (Code.OK, Code.DUPLICATE):
        sys.exit(1)
    return r


def _owner_of_label(net, label):
    fid = _fid(label)
    f = net.world.contract.fighters.get(fid)
    if f is None:
        sys.exit(f"qdojo: no fighter {label!r} on this devnet; `qdojo combat fighter register {label}`")
    return fid, f


# ---- devnet ----------------------------------------------------------------

def cmd_devnet(a):
    net = _net(a)
    if a.action == "tick":
        for _ in range(a.n):
            net.world.end()
        net.save()
    if a.action == "export":
        out = Path(a.out) if a.out else Path("apps/web/data/combat/v1")
        written = export.export_all(net.world.contract, out)
        print(f"wrote {len(written)} files under {out}")
        return
    c = net.world.contract
    _out(a, {"tick": net.world.tick, "fighters": len(c.fighters), "open_offers": sum(o.status == "OPEN" for o in c.offers.values()),
             "active_fights": sum(f.phase != "DONE" for f in c.fights.values()), "generation": c.generation,
             "event_digest": c.event_digest.hex()},
         f"devnet {net.dir}  tick {net.world.tick}  fighters {len(c.fighters)}  "
         f"open offers {sum(o.status == 'OPEN' for o in c.offers.values())}  "
         f"active fights {sum(f.phase != 'DONE' for f in c.fights.values())}\n"
         f"fake QU and synthetic identities; not a deployment")


# ---- fighters --------------------------------------------------------------

def cmd_fighter(a):
    net = _net(a)
    c = net.world.contract
    if a.action == "register":
        fid, owner = net.ensure_fighter(a.fighter)
        net.save()
        _out(a, {"fighter_id": fid.hex(), "owner": owner.hex()}, f"fighter {a.fighter}: {fid.hex()}")
        return
    fid, f = _owner_of_label(net, a.fighter)
    if a.action == "authorize":
        _send(a, net, f.owner, Op.SET_OPERATOR, fighter_id=fid, new_operator=identity("owner:" + a.operator)
              if len(a.operator) != 64 else bytes.fromhex(a.operator), expected_auth_version=f.auth_version)
        return
    doc = export.fighter(c, fid)
    if a.json:
        print(json.dumps(doc))
        return
    r = doc["record"]
    print(f"{a.fighter}  {doc['belt']}{' (provisional)' if doc['provisional'] else ''}  rating {doc['lifetime_rating']}\n"
          f"record W{r['W']} D{r['D']} L{r['L']}  forfeits won {r['FW']} lost {r['FL']}  lock {doc['lock']}\n"
          f"owner {doc['owner'][:16]}…  operator {doc['operator'][:16]}…  auth v{doc['auth_version']}")


# ---- queue -----------------------------------------------------------------

def cmd_queue(a):
    net = _net(a)
    c = net.world.contract
    if a.action == "list":
        doc = export.book(c)
        if a.json:
            print(json.dumps(doc))
            return
        for o in doc["offers"]:
            print(f"offer {o['offer_id']:>4} {o['kind']:<6} rating {o['rating']:>4} stake {o['stake']:>6} "
                  f"window {o['window']} expires {o['expires_tick']}")
        print(f"next matching tick {doc['next_matching_tick']}; fights in use "
              f"{doc['capacity']['fights_in_use']}/{doc['capacity']['fights']}")
        return
    if a.action == "cancel":
        o = c.offers.get(a.offer)
        who = o.owner if o else roles()["admin"]
        _send(a, net, who, Op.QUEUE_CANCEL, offer_id=a.offer)
        return
    fid, f = _owner_of_label(net, a.fighter)
    tier = net.m.tiers.get(a.tier)
    if tier is None:
        sys.exit(f"qdojo: unknown tier {a.tier}")
    _send(a, net, f.owner, Op.QUEUE_ENTER, tier, fighter_id=fid, auth_version=f.auth_version,
          ruleset_digest=net.m.ruleset.digest, timing_profile_id=1, fee_profile_id=1, tier_id=a.tier,
          max_gap=a.max_gap, expires_tick=net.world.tick + a.lifetime)


# ---- duels -----------------------------------------------------------------

def cmd_duel(a):
    net = _net(a)
    c = net.world.contract
    if a.action == "offer":
        fid, f = _owner_of_label(net, a.fighter)
        opp, _ = _owner_of_label(net, a.opponent)
        _send(a, net, f.owner, Op.DUEL_OFFER, a.stake, fighter_id=fid, auth_version=f.auth_version, opponent_id=opp,
              ruleset_digest=net.m.ruleset.digest, timing_profile_id=1, fee_profile_id=1, stake=a.stake,
              format=FORMATS[a.format], expires_tick=net.world.tick + a.lifetime)
    elif a.action == "accept":
        fid, f = _owner_of_label(net, a.fighter)
        o = c.offers.get(a.offer)
        _send(a, net, f.owner, Op.DUEL_ACCEPT, o.amount if o else 0, offer_id=a.offer, fighter_id=fid,
              auth_version=f.auth_version)
    else:
        o = c.offers.get(a.offer)
        _send(a, net, o.owner if o else roles()["admin"], Op.DUEL_CANCEL, offer_id=a.offer)


# ---- cups ------------------------------------------------------------------

def cmd_cup(a):
    net = _net(a)
    c = net.world.contract
    if a.action == "list":
        rows = [{"cup_id": x.cup_id, "status": x.status, "entries": len(x.entries), "entry_fee": x.descriptor["entry_fee"],
                 "sponsorship": x.sponsorship, "registration_close": x.descriptor["registration_close"],
                 "level": x.level, "level_start": x.level_start,
                 "champion": x.champion.hex() if x.champion else None} for x in c.cups.values()]
        _out(a, rows, "\n".join(f"cup {r['cup_id']} {r['status']} entries {r['entries']} fee {r['entry_fee']} "
                                 f"closes {r['registration_close']}" for r in rows) or "no cups")
        return
    if a.action == "create":
        _send(a, net, roles()["admin"], Op.ADMIN_CREATE_CUP, a.sponsorship, ruleset_digest=net.m.ruleset.digest,
              timing_profile_id=1, fee_profile_id=1, entry_fee=a.entry_fee,
              registration_close=net.world.tick + a.close_in, min_entrants=a.min_entrants,
              max_entrants=a.max_entrants, level_ticks=3000, first_level_delay=120, checkin_ticks=120,
              replay_delay=120)
        return
    fid, f = _owner_of_label(net, a.fighter)
    if a.action == "register":
        cup = c.cups.get(a.cup)
        _send(a, net, f.owner, Op.CUP_REGISTER, cup.descriptor["entry_fee"] if cup else 0, cup_id=a.cup,
              fighter_id=fid, auth_version=f.auth_version)
    else:
        _send(a, net, f.operator, Op.CUP_CHECK_IN, cup_id=a.cup, pairing_id=a.pairing, fighter_id=fid,
              auth_version=f.auth_version)


# ---- money -----------------------------------------------------------------

def cmd_withdraw(a):
    net = _net(a)
    who = _signer(a)
    if who is None:
        sys.exit("qdojo: --as LABEL names the devnet owner withdrawing to itself")
    _send(a, net, who, Op.WITHDRAW)


# ---- bot -------------------------------------------------------------------

def cmd_bot_run(a):
    """Run your fighter's bot on the devnet for N ticks. With --spar, a disclosed
    house-labelled sparring bot enters too, so a lone owner still gets fights."""
    net = _net(a)
    rules = candidate_1()
    fid, owner = net.ensure_fighter(a.fighter)
    if a.planner:
        choose = planner_chooser(shlex.split(a.planner), a.budget_ms)
    else:
        choose = policy_chooser(rules, E.policy_by_name(a.npc or "mixed-v1"), os.urandom(32))
    budget = Budget(ruleset_digest=rules.digest.hex())
    if a.budget:
        budget = Budget(**{**budget.__dict__, **json.loads(Path(a.budget).read_text())})
    state = Path(a.state) if a.state else _home() / "bots" / a.fighter
    bots = [Bot(net.client(owner), rules, fid, owner, owner, choose, budget, state)]
    if a.spar:
        sfid, sowner = net.ensure_fighter("sparring-" + a.spar)
        bots.append(Bot(net.client(sowner), rules, sfid, sowner, sowner,
                        policy_chooser(rules, E.policy_by_name(a.spar), os.urandom(32)),
                        Budget(ruleset_digest=rules.digest.hex(), max_fights_per_day=10**6,
                               max_daily_committed=10**12, max_daily_net_loss=10**12, stop_after_faults=10**6),
                        _home() / "bots" / ("sparring-" + a.spar)))
    last = None
    for _ in range(a.ticks):
        msg = bots[0].step()
        for b in bots[1:]:
            b.step()
        if msg != last and not a.quiet:
            print(f"tick {net.world.tick}: {msg}")
            last = msg
        net.world.end()
    net.save()
    f = net.world.contract.fighters[fid]
    print(f"{a.fighter}: rating {f.lifetime}, record {f.record}, credit {net.world.contract.ledger.credits.get(owner, 0)}")


# ---- doctor ----------------------------------------------------------------

def cmd_doctor(a):
    """Non-spending readiness check. Every line is PASS, WARN or FAIL."""
    checks = []

    def check(name, ok, detail, warn=False):
        checks.append({"check": name, "status": "PASS" if ok else ("WARN" if warn else "FAIL"), "detail": detail})
    rules = candidate_1()
    check("ruleset digest", True, f"{rules.semantic_version} {rules.digest.hex()}")
    try:
        s = engine.new_fight(rules)
        from .types import Action, Plan
        r = engine.resolve_round(rules, s, Plan.of([Action.JAB] * 6), Plan.of([Action.JAB] * 6))
        check("engine self-test", r.end.a.hp == 52 and r.end.a.stamina == 46, "six JABs each: 52 HP, 46 stamina")
    except Exception as exc:
        check("engine self-test", False, str(exc))
    manifest = os.environ.get("QDOJO_COMBAT_MANIFEST")
    check("deployment manifest", bool(manifest), manifest or "none: no network, contract or procedure IDs; "
          "paid admission stays disabled and only the devnet is available", warn=True)
    if a.planner:
        obs = json.loads(json.dumps(_sample_observation(rules)))
        try:
            ran = planner.run(shlex.split(a.planner), obs, a.budget_ms)
            check("planner health", True, f"{ran.elapsed_ms} ms, plan {ran.plan.to_json()}")
        except planner.PlannerError as exc:
            check("planner health", False, f"{exc.code}: {exc}")
    state = Path(a.state) if a.state else _home() / "bots"
    if state.exists():
        bad = [p for p in state.rglob("secret-plans.jsonl") if stat.S_IMODE(p.stat().st_mode) & 0o077]
        check("secret plan journals private", not bad, ", ".join(map(str, bad)) or "all 0600")
    else:
        check("secret plan journals private", True, "no journals yet", warn=True)
    check("npc roster", len(npcs.ROSTER) == 6, ", ".join(npcs.ROSTER))
    if a.json:
        print(json.dumps(checks, indent=1))
    else:
        for c in checks:
            print(f"{c['status']:<4}  {c['check']}: {c['detail']}")
    if any(c["status"] == "FAIL" for c in checks):
        sys.exit(1)


def _sample_observation(rules):
    from .training import observation, practice_context, practice_fighter_id
    ids = tuple(sorted((practice_fighter_id("you"), practice_fighter_id("them"))))
    ctx = practice_context(rules, 1, ids)
    return observation(rules, ctx, engine.new_fight(rules), "A", ids, [], planner.DEFAULT_BUDGET_MS)


def add_parsers(s):
    """Registered under `qdojo combat`."""
    def net_opts(p):
        p.add_argument("--devnet", help="devnet directory (default ~/.qdojo/combat/devnet)")
        p.add_argument("--json", action="store_true")

    d = s.add_parser("devnet", help="the local devnet: fake QU, synthetic identities")
    d.add_argument("action", choices=("status", "tick", "export"))
    d.add_argument("n", nargs="?", type=int, default=1)
    d.add_argument("--out", help="export directory ending in combat/v1")
    net_opts(d)
    d.set_defaults(fn=cmd_devnet)

    d = s.add_parser("fighter", help="register, show or authorize a fighter")
    d.add_argument("action", choices=("register", "show", "authorize"))
    d.add_argument("fighter", help="devnet label or 64-hex fighter ID")
    d.add_argument("operator", nargs="?", help="authorize: the new operator (label or hex)")
    net_opts(d)
    d.set_defaults(fn=cmd_fighter)

    d = s.add_parser("queue", help="ranked queue: enter, cancel, list")
    d.add_argument("action", choices=("enter", "cancel", "list"))
    d.add_argument("offer", nargs="?", type=int, help="cancel: the offer ID")
    d.add_argument("--fighter")
    d.add_argument("--tier", type=int, default=1)
    d.add_argument("--max-gap", type=int, default=200)
    d.add_argument("--lifetime", type=int, default=240)
    net_opts(d)
    d.set_defaults(fn=cmd_queue)

    d = s.add_parser("duel", help="named series: offer, accept, cancel")
    d.add_argument("action", choices=("offer", "accept", "cancel"))
    d.add_argument("offer", nargs="?", type=int, help="accept/cancel: the offer ID")
    d.add_argument("--fighter")
    d.add_argument("--opponent")
    d.add_argument("--stake", type=int, default=1000)
    d.add_argument("--format", choices=tuple(FORMATS), default="bo3")
    d.add_argument("--lifetime", type=int, default=240)
    net_opts(d)
    d.set_defaults(fn=cmd_duel)

    d = s.add_parser("cup", help="cups: list, create (devnet admin), register, check-in")
    d.add_argument("action", choices=("list", "create", "register", "check-in"))
    d.add_argument("cup", nargs="?", type=int)
    d.add_argument("pairing", nargs="?", type=int)
    d.add_argument("--fighter")
    d.add_argument("--entry-fee", type=int, default=2000)
    d.add_argument("--sponsorship", type=int, default=0)
    d.add_argument("--close-in", type=int, default=240)
    d.add_argument("--min-entrants", type=int, default=4)
    d.add_argument("--max-entrants", type=int, default=16)
    net_opts(d)
    d.set_defaults(fn=cmd_cup)

    d = s.add_parser("withdraw", help="withdraw your whole credit to yourself")
    d.add_argument("--as", dest="as_label", help="devnet owner label")
    net_opts(d)
    d.set_defaults(fn=cmd_withdraw)

    bp = s.add_parser("bot", help="your autonomous combat bot")
    bs = bp.add_subparsers(dest="bot_action", required=True)
    d = bs.add_parser("run", help="queue, commit and reveal within your budget")
    d.add_argument("--fighter", required=True)
    d.add_argument("--npc", help="an in-process policy instead of a planner")
    d.add_argument("--planner", help="your planner command")
    d.add_argument("--budget", help="JSON file of Budget fields")
    d.add_argument("--budget-ms", type=int, default=planner.DEFAULT_BUDGET_MS)
    d.add_argument("--state", help="bot state directory (secret plan journal)")
    d.add_argument("--ticks", type=int, default=300)
    d.add_argument("--spar", help="also run a disclosed sparring bot with this policy on the devnet")
    d.add_argument("--quiet", action="store_true")
    net_opts(d)
    d.set_defaults(fn=cmd_bot_run)

    d = s.add_parser("doctor", help="non-spending readiness and configuration check")
    d.add_argument("--planner")
    d.add_argument("--budget-ms", type=int, default=planner.DEFAULT_BUDGET_MS)
    d.add_argument("--state")
    d.add_argument("--json", action="store_true")
    d.set_defaults(fn=cmd_doctor)
