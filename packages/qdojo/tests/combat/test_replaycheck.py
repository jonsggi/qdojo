"""`qdojo combat replay` and replaycheck, the Python twin of the site's
verifier (apps/web/combat/logic.js verifyReplay and replayMismatches).

Every genuine replay verifies: the sample export and fresh exports of every
result kind. Every way of claiming a result the revealed plans do not give is
refused, and where node is installed the site's verifier must reach the same
verdict on each document. The command prints only what it verified, reports
any failure (a malformed document included) as FAILED or "verified": false,
and bounds a download in size and time. Nothing here leaves 127.0.0.1.
"""
import http.server
import json
import shutil
import subprocess
import threading
import time

import pytest

from qdojo.cli import main
from qdojo.combat import export, replaycheck
from qdojo.combat.codec import Code, Op
from qdojo.combat.contract import development_manifest
from qdojo.combat.engine import new_fight, resolve_round
from qdojo.combat.rules import PUBLIC_ARENA, by_digest, by_version
from qdojo.combat.sim import World, commit_fields, identity, reveal_fields
from qdojo.combat.training import Contestant, ReplayMismatch, run_fight, verify_replay
from qdojo.combat.types import Plan

from .conftest import ROOT

WEB = ROOT / "apps/web"
SAMPLE = WEB / "data/combat/v1/sample/fights"
PUBLIC = by_version(PUBLIC_ARENA)
ROLES = [identity(x) for x in ("admin", "house", "dev", "share")]
KO_PLAN, RESTS = Plan.of(["KICK", "RECOVER"] * 3), Plan.of(["RECOVER"] * 6)
KINDS = ("KO", "FORFEIT", "FORFEIT at reveal", "DOUBLE_FAULT", "VOID", "open")


def _fresh(kind: str) -> dict:
    """export.fight_replay of one fight on the reference contract (public
    ruleset) that ends as `kind`; slot A plays KO_PLAN, slot B rests."""
    w = World(development_manifest(PUBLIC, *ROLES))
    w.mint(ROLES[0], 10**9)
    for label in "ab":
        fid, owner = identity("fighter:" + label), identity("owner:" + label)
        w.owners[fid] = owner
        w.mint(owner, 10**6)
        assert w.send(ROLES[0], Op.ADMIN_REGISTER_ASSET, fighter_id=fid, registry_version=1, house_npc=0).ok
        assert w.send(owner, Op.REGISTER_FIGHTER, fighter_id=fid, registry_version=1).ok
        assert w.send(owner, Op.QUEUE_ENTER, 1000, fighter_id=fid, auth_version=w.contract.fighters[fid].auth_version,
                      ruleset_digest=PUBLIC.digest, timing_profile_id=1, fee_profile_id=1, tier_id=1, max_gap=200,
                      expires_tick=w.tick + 240).ok
    while not w.contract.fights:
        w.end()
    f = next(iter(w.contract.fights.values()))
    ids = {"A": f.context.participant_a.fighter_id, "B": f.context.participant_b.fighter_id}
    plans = {"A": KO_PLAN, "B": RESTS}

    def round_(commit="AB", reveal="AB"):
        w.run_until(f.start_tick + 1)
        salts = {}
        for s in commit:
            fields, salts[s] = commit_fields(w, f.fight_id, ids[s], w.owners[ids[s]], plans[s],
                                             bytes([len(f.rounds) + 1]) * 32)
            assert w.send(w.owners[ids[s]], Op.COMMIT, **fields).code == Code.OK
        w.run_until(f.commit_last + 1)
        if f.phase == "REVEAL":
            for s in reveal:
                fields = reveal_fields(w, f.fight_id, ids[s], plans[s], salts[s])
                assert w.send(w.owners[ids[s]], Op.REVEAL, **fields).code == Code.OK
            w.end()

    if kind == "KO":
        while f.phase != "DONE":
            round_()
    elif kind == "FORFEIT":                   # B misses the second round's commit
        round_()
        round_(commit="A")
    elif kind == "FORFEIT at reveal":         # B commits to the first round and never reveals
        round_(reveal="A")
        w.run_until(f.reveal_last + 1)
    elif kind == "DOUBLE_FAULT":
        round_(commit="")
    elif kind == "VOID":                      # a service gap voids the fight after one round
        round_()
        w.skip_ticks(3)
        w.end()
    else:                                     # still open after one round
        round_()
    return json.loads(json.dumps(export.fight_replay(w.contract, f.fight_id)))


@pytest.fixture(scope="module")
def sample():
    return {int(p.parent.name): json.loads(p.read_text())
            for p in sorted(SAMPLE.glob("*/replay.json"), key=lambda p: int(p.parent.name))}


@pytest.fixture(scope="module")
def fresh():
    docs = {kind: _fresh(kind) for kind in KINDS}
    result = {k: (d["result"].get("kind"), d["outcome"], len(d["rounds"])) for k, d in docs.items()}
    assert result["KO"][:2] == ("COMBAT", {"winner": "A", "result": "KO"})
    assert result["FORFEIT"] == ("FORFEIT", {"winner": "A", "result": "FORFEIT"}, 1)
    assert result["FORFEIT at reveal"] == ("FORFEIT", {"winner": "A", "result": "FORFEIT"}, 0)
    assert result["DOUBLE_FAULT"] == ("DOUBLE_FAULT", {"winner": None, "result": "DOUBLE_FAULT"}, 0)
    assert result["VOID"] == ("VOID", {"winner": None, "result": "VOID"}, 1) and docs["VOID"]["forfeit_round"] is None
    assert result["open"] == (None, None, 1)
    return docs


def _bases(sample, fresh):
    """The documents the tampering starts from, by name."""
    forfeit = next(d for d in sample.values() if d["result"]["kind"] == "FORFEIT" and d["rounds"])
    return {"sample KO": sample[1], "sample forfeit": forfeit, "fresh KO": fresh["KO"],
            "fresh forfeit": fresh["FORFEIT"], "fresh open": fresh["open"]}


def _verdict(doc) -> bool:
    """Whether `qdojo combat replay` verifies the document: its routing and
    verifiers, without the printing."""
    try:
        if replaycheck.is_arena(doc):
            replaycheck.verify_arena_replay(doc)
        else:
            verify_replay(doc)
    except ReplayMismatch:
        return False
    return True


def _other(winner):
    return "B" if winner == "A" else "A"


def _timeout(kind):
    """The record rewritten as an export-shaped timeout (the loser wins a forfeit)."""
    def edit(d):
        winner = _other(d["outcome"]["winner"]) if kind == "FORFEIT" else None
        d["result"] = {"kind": kind, "winner": winner, "stage": "REVEAL", "tick": d["result"]["tick"]}
        d["outcome"], d["forfeit_round"] = {"winner": winner, "result": kind}, None
    return edit


def _flip_final(d):
    d["final"]["A"]["hp"] ^= 1


def _junk(d):
    d["result"]["kind"] = "COMBATX"
    d["outcome"]["result"] += " junk"


def _claim_ko(d):
    d["result"] = {"kind": "COMBAT", "winner": "A", "result": "KO", "tick": "1"}
    d["outcome"] = {"winner": "A", "result": "KO"}


FOUGHT = [
    ("a forfeit claimed after the KO", _timeout("FORFEIT")),
    ("a double fault claimed after the KO", _timeout("DOUBLE_FAULT")),
    ("a void claimed after the KO", _timeout("VOID")),
    ("a result kind FORFEIT beside the KO outcome", lambda d: d["result"].update(kind="FORFEIT")),
    ("the result record names the loser", lambda d: d["result"].update(winner=_other(d["result"]["winner"]))),
    ("an edited final state", _flip_final),
    ("in progress, although the rounds ended it", lambda d: d.update(result={}, outcome=None)),
    ("an edited unexecuted suffix", lambda d: d["rounds"][-1]["unexecuted"]["A"].append("BLOCK")),
    ("a result kind and outcome that are no results", _junk),
    ("a made-up result", lambda d: (d["result"].update(kind="TOTALLY_WON"), d["outcome"].update(result="TOTALLY_WON"))),
    ("a fought result with no outcome", lambda d: d.update(outcome=None)),
    ("context_bytes deleted", lambda d: d.pop("context_bytes")),
]
TIMED_OUT = [
    ("a moved forfeit_round", lambda d: d.update(forfeit_round=d["forfeit_round"] + 1)),
    ("an edited final state", _flip_final),
]
# The verifier before this test (b3e3f71a) passed each of these, or crashed on it.
BYPASSES = ([(b, n, e) for b in ("sample KO", "fresh KO") for n, e in FOUGHT]
            + [(b, n, e) for b in ("sample forfeit", "fresh forfeit") for n, e in TIMED_OUT]
            + [("fresh open", "an edited final state", _flip_final)])
# Refused before too; here so that the site is asked about them as well.
REFUSED = [("sample KO", "the outcome names the loser", lambda d: d["outcome"].update(winner="B")),
           ("sample KO", "an edited salt", lambda d: d["rounds"][0]["salts"].update(A="00" * 32)),
           ("sample forfeit", "a KO the rounds do not reach", _claim_ko),
           ("fresh open", "a KO the rounds do not reach", lambda d: d.update(outcome={"winner": "A", "result": "KO"}))]


def _tampered(bases, cases):
    out = []
    for base, name, edit in cases:
        doc = json.loads(json.dumps(bases[base]))
        edit(doc)
        out.append((f"{base}: {name}", doc))
    return out


def test_every_genuine_replay_verifies(sample, fresh):
    assert len(sample) >= 20
    for doc in [*sample.values(), *fresh.values()]:
        report = replaycheck.verify_arena_replay(doc)
        kind = doc["result"].get("kind")
        if kind in replaycheck.TIMEOUTS:
            # what the protocol decided is reported as claimed, never as re-derived
            assert report["outcome"] is None, doc["fight_id"]
            assert report["claimed"] == {"result": kind, "winner": doc["result"]["winner"]}
        elif kind:
            assert report["outcome"] == doc["outcome"] and report["claimed"] is None
        else:
            assert report["outcome"] is None and report["claimed"] is None
        assert report["rules"] == by_digest(doc["ruleset_digest"]).semantic_version
    assert replaycheck.ReplayMismatch is ReplayMismatch        # one class: the command catches both verifiers'


@pytest.mark.parametrize("base,name,edit", BYPASSES, ids=[f"{b}: {n}" for b, n, _ in BYPASSES])
def test_a_tampered_replay_is_refused(sample, fresh, base, name, edit):
    [(what, doc)] = _tampered(_bases(sample, fresh), [(base, name, edit)])
    assert not _verdict(doc), what


# The site's checks 1, 3 and 4 (ruleset, commitments, replay), which replaycheck
# twins, for each document on stdin; the rules are the embedded ones the
# document names, as the page picks them from the manifest.
SITE_VERDICTS = r"""
const web = process.argv[1];
const L = require(web + '/combat/logic.js');
require(web + '/combat/ruleset.js');
const all = globalThis.QDojoRulesets;
(async () => {
  const sha = L.defaultSha256();
  const digests = await Promise.all(all.map(r => L.rulesetDigest(r, sha)));
  const out = [];
  for (const rp of JSON.parse(require('fs').readFileSync(0, 'utf8'))) {
    const i = Math.max(0, digests.indexOf(rp && rp.ruleset_digest));
    try {
      const v = await L.verifyReplay(rp, { rules: all[i], manifest: { ruleset_digest: digests[i] } });
      out.push(!v.checks.some(c => ['ruleset', 'commitments', 'replay'].includes(c.id) && c.status === 'FAIL'));
    } catch (e) {
      out.push(false);
    }
  }
  process.stdout.write(JSON.stringify(out));
})();
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_the_site_reaches_the_same_verdict(sample, fresh):
    genuine = [(f"sample {i}", d) for i, d in sorted(sample.items())] + [(f"fresh {k}", d) for k, d in fresh.items()]
    tampered = _tampered(_bases(sample, fresh), BYPASSES + REFUSED)
    docs = genuine + tampered
    site = json.loads(subprocess.run(["node", "-e", SITE_VERDICTS, str(WEB)], input=json.dumps([d for _, d in docs]),
                                     capture_output=True, text=True, check=True, timeout=300).stdout)
    mine = [_verdict(d) for _, d in docs]
    assert [w for (w, _), m, s in zip(docs, mine, site) if m != s] == []
    assert all(mine[:len(genuine)]) and not any(mine[len(genuine):])


# ---- the command ------------------------------------------------------------

def _cli(capsys, *argv):
    code = 0
    try:
        main(["combat", "replay", *argv])
    except SystemExit as exc:
        code = exc.code
    out = capsys.readouterr()
    return code, out.out, out.err


def _file(tmp_path, doc, name="replay.json"):
    p = tmp_path / name
    p.write_text(json.dumps(doc))
    return str(p)


def _practice():
    return run_fight(Contestant("x", npc="random-v1"), Contestant("y", npc="kicker-v1"), bytes([11]) * 32)


def test_arena_or_practice_follows_the_mode(sample, tmp_path, capsys):
    practice = _practice()
    assert not replaycheck.is_arena(practice)
    assert replaycheck.is_arena({**practice, "context_bytes": sample[1]["context_bytes"]})
    stripped = {k: v for k, v in sample[1].items() if k != "context_bytes"}
    assert replaycheck.is_arena(stripped)
    # The forgery from the review: plans swapped, rounds re-resolved, B
    # declared the winner, and the context bytes dropped to skip the arena checks.
    forged = json.loads(json.dumps(stripped))
    rules = by_digest(forged["ruleset_digest"])
    state = new_fight(rules)
    for r in forged["rounds"]:
        r["plans"]["A"], r["plans"]["B"] = r["plans"]["B"], r["plans"]["A"]
        a, b = (Plan.of(r["plans"][s]["actions"], r["plans"][s]["power_slot"]) for s in "AB")
        res = resolve_round(rules, state, a, b)
        r.update(res.to_json())
        state = res.end
    forged["outcome"] = state.outcome.to_json()
    forged["result"] = {**forged["result"], "winner": forged["outcome"]["winner"]}
    forged["final"] = {"A": state.a.to_json(), "B": state.b.to_json()}
    assert forged["outcome"] == {"winner": "B", "result": "KO"}
    code, out, _ = _cli(capsys, _file(tmp_path, forged))
    assert code == 1 and out.startswith("replay FAILED verification: ") and "context_bytes" in out
    code, out, _ = _cli(capsys, _file(tmp_path, practice))
    assert code == 0 and out.splitlines()[-1].startswith("practice replay re-derived from its plans: ")


def test_every_failure_is_a_clean_verdict(sample, tmp_path, capsys):
    practice = _practice()
    beat = json.loads(json.dumps(practice))
    beat["rounds"][0]["beats"][0]["A"]["after"]["hp"] ^= 1
    no_plan_bytes = json.loads(json.dumps(sample[1]))
    del no_plan_bytes["rounds"][0]["plan_bytes"]
    bad_action = json.loads(json.dumps(sample[1]))
    bad_action["rounds"][0]["plans"]["A"]["actions"][0] = "FLY"
    cases = {"a practice replay with an edited beat": beat,
             "a practice replay without rounds": {k: v for k, v in practice.items() if k != "rounds"},
             "a fought result with no outcome": {**sample[1], "outcome": None},
             "a round without plan_bytes": no_plan_bytes,
             "a displayed plan with an unknown action": bad_action,
             "a JSON list": [1, 2]}
    for what, doc in cases.items():
        path = _file(tmp_path, doc)
        code, out, _ = _cli(capsys, "--json", path)
        assert code == 1 and json.loads(out)["verified"] is False, what
        code, out, _ = _cli(capsys, path)
        assert code == 1 and out.startswith("replay FAILED verification: "), what


def test_only_verified_values_are_printed(sample, fresh, tmp_path, capsys):
    doc = json.loads(json.dumps(sample[1]))
    doc["semantic_version"] = "combat-v1-candidate-3\x1b]0;pwned\x07"
    code, out, _ = _cli(capsys, _file(tmp_path, doc))
    assert code == 0 and out.splitlines()[0] == "ruleset combat-v1-candidate-1 12085c86a61ffd10"
    assert "\x1b" not in out and "pwned" not in out
    doc = json.loads(json.dumps(sample[1]))
    doc["result"] = {"kind": "FORFEIT", "winner": "A"}
    doc["outcome"] = {"result": "KO\x1b[1A\x1b[2K\r  PASS forged line", "winner": "A\x1b]52;c;cHduZWQ=\x07"}
    for flags in ([], ["--json"]):
        code, out, _ = _cli(capsys, *flags, _file(tmp_path, doc))
        assert code == 1 and "\x1b" not in out and "forged" not in out
    # A genuine forfeit verifies, and its result is reported as the export's claim.
    forfeits = [d for d in sample.values() if d["result"]["kind"] == "FORFEIT"]
    for d in (next(x for x in forfeits if x["rounds"]), next(x for x in forfeits if not x["rounds"])):
        code, out, _ = _cli(capsys, _file(tmp_path, d))
        lines = out.splitlines()
        assert code == 0 and "re-derived from its plans" not in out
        assert lines[-1] == (f"arena replay verified up to its end; the export records FORFEIT, winner "
                             f"{d['result']['winner']}: decided by the protocol, not re-derived from the plans")
        replayed = next(x for x in lines if "independent replay" in x)
        assert replayed.startswith("  PASS" if d["rounds"] else "  UNAVAILABLE"), replayed
        code, out, _ = _cli(capsys, "--json", _file(tmp_path, d))
        assert json.loads(out)["outcome"] is None
        assert json.loads(out)["claimed"] == {"result": "FORFEIT", "winner": d["result"]["winner"]}
    # Nobody wins a double fault or a void, and neither is a draw.
    for kind in ("DOUBLE_FAULT", "VOID"):
        code, out, _ = _cli(capsys, _file(tmp_path, fresh[kind]))
        assert code == 0 and "draw" not in out
        assert out.splitlines()[-1] == (f"arena replay verified up to its end; the export records {kind}, winner "
                                        f"none: decided by the protocol, not re-derived from the plans")


# ---- downloads (127.0.0.1 only) ------------------------------------------------

@pytest.fixture
def server(sample):
    stop = threading.Event()
    body = json.dumps(sample[1]).encode()

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            if self.path == "/bad-reason":
                self.send_response(404, "Not Found\x1b]0;pwned\x07")
                self.end_headers()
                return
            self.send_response(200)
            self.end_headers()
            if self.path == "/drip":                   # a byte at a time for 3 s, each well inside the socket timeout
                i, end = 0, time.monotonic() + 3
                while time.monotonic() < end and not stop.wait(0.05):
                    self.wfile.write(body[i:i + 1])
                    self.wfile.flush()
                    i += 1
                self.wfile.write(body[i:])
            else:
                self.wfile.write(body + b" " * 4096 if self.path == "/padded" else body)

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", len(body)
    stop.set()
    srv.shutdown()
    srv.server_close()


def test_a_download_is_capped(server, monkeypatch):
    url, size = server
    assert replaycheck.load(url + "/replay.json")["fight_id"] == "1"
    monkeypatch.setattr(replaycheck, "MAX_BYTES", size + 1024, raising=False)
    with pytest.raises(ValueError, match="larger than"):
        replaycheck.load(url + "/padded")


def test_a_download_is_time_bounded(server, monkeypatch):
    monkeypatch.setattr(replaycheck, "DEADLINE_S", 1.0, raising=False)
    t = time.monotonic()
    with pytest.raises(TimeoutError):                  # not after the 3 s the drip takes
        replaycheck.load(server[0] + "/drip")
    assert time.monotonic() - t < 3


def test_a_server_message_is_printed_escaped(server, capsys):
    code, _, _ = _cli(capsys, server[0] + "/bad-reason")
    assert "cannot read" in str(code) and "\x1b" not in str(code) and "\\x1b" in str(code)
