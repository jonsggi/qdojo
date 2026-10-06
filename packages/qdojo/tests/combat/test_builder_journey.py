"""The published builder journey, end to end, under the public arena's ruleset (AUD-041).

One local arena (profile demo-c3: the public arena's ruleset, fake QU, no
network beyond 127.0.0.1, no LLM) with outside entry open and house bots that
play LAST_STAND and FEINT. The builder follows the published path: doctor
--arena, train and replay with the starter (both the repository copy and the
site download), evaluate, `qdojo combat join` to register, a ranked fight
fought by the starter, then the arena's replay fetched over HTTP and verified.
Every ruleset digest on the way must be the public arena's, and no starter
round may fall back or be adjusted. A second arena with entry closed checks
the closed-entry messages.
"""
import json
import re
import sys
import threading
import time

import pytest

from qdojo.cli import main
from qdojo.combat import api, export, live, replaycheck
from qdojo.combat import join as J
from qdojo.combat import readmodel as rm
from qdojo.combat.bot import Bot, Budget, planner_chooser
from qdojo.combat.rules import PUBLIC_ARENA, by_version

from .conftest import ROOT

STARTERS = {"repository": ROOT / "examples/combat/planner_minimal.py",
            "download": ROOT / "apps/web/combat/planner_minimal.py"}
PUBLIC = by_version(PUBLIC_ARENA)
LINEUP = [{"label": "house-stander", "policy": "stander"}, {"label": "house-feinter", "policy": "feinter"}]
SLOW_HOST_MS = 20_000          # a loaded two-CPU host can take a second to start Python


class Arena:
    """A demo-c3 arena behind the real read API, optionally with outside entry."""

    def __init__(self, tmp, open_entry=True):
        self.dir = tmp / "arena"
        self.dir.mkdir()
        inbox = self.dir / "inbox.sqlite" if open_entry else None
        self.arena = live.Arena(self.dir, LINEUP, profile="demo-c3", seed=7, deterministic=True,
                                join_inbox=inbox, log=lambda m: None)
        self.out = tmp / "web" / "combat" / "v1"
        self.export()
        self.fl = rm.Follower(self.dir, tmp / "rm.sqlite", self.out, log=lambda m: None)
        svc = None
        if open_entry:
            svc = J.JoinService(inbox, J.Limits(reads_per_second=10_000, tx_per_second=1000, tx_burst=1000,
                                                max_outside_fighters=2))
            svc.attach(self.fl)
        self.fl.step()
        self.srv = api.Server(("127.0.0.1", 0), tmp / "rm.sqlite", self.out, join=svc, follower=self.fl)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"
        self.lock = threading.Lock()

    def export(self):
        export.export_all(self.arena.w.contract, self.out, keep=50, deployment=self.arena.deployment(1.5))

    def tick(self, n=1):
        with self.lock:
            for _ in range(n):
                self.arena.step()
            self.fl.step()

    def ticking(self, period=0.05):
        """Tick in the background (for CLI commands that poll with real sleeps); returns a stop function."""
        stop = threading.Event()

        def run():
            while not stop.is_set():
                self.tick()
                time.sleep(period)
        t = threading.Thread(target=run, daemon=True)
        t.start()
        return lambda: (stop.set(), t.join())


def _cli(capsys, *argv):
    code = 0
    try:
        main(list(argv))
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else exc.code)
    out = capsys.readouterr()
    return code, out.out, out.err


def _starter(which):
    return f"{sys.executable} {STARTERS[which]}"


@pytest.fixture
def arena(tmp_path):
    a = Arena(tmp_path)
    yield a
    a.srv.shutdown()


def test_the_published_commands_select_the_public_arena_ruleset():
    """The quickstart in llms.txt and on the site's BUILD A BOT page trains under
    the CLI default, and that default is the public arena's ruleset."""
    brief = (ROOT / "apps/web/llms.txt").read_text()
    quick = re.search(r"## Commands.*?```sh\n(.*?)```", brief, re.S).group(1)
    site = re.search(r"const COMMANDS = \[(.*?)\];", (ROOT / "apps/web/combat/app.js").read_text(), re.S).group(1)
    for where, text in (("llms.txt", quick), ("app.js COMMANDS", site)):
        assert "--ruleset" not in text, f"{where}: the quickstart must use the default ruleset"
    for cmd in ("train", "evaluate", "doctor"):
        assert re.search(rf'"{cmd}".*?default=PUBLIC_ARENA|{cmd}.*?--ruleset", default=PUBLIC_ARENA',
                         (ROOT / "packages/qdojo/src/qdojo/combat/cli.py").read_text()
                         + (ROOT / "packages/qdojo/src/qdojo/combat/chain_cli.py").read_text(), re.S)


@pytest.mark.parametrize("which", sorted(STARTERS))
def test_train_and_replay_with_each_starter_distribution(which, tmp_path, capsys):
    out = tmp_path / "fight.json"
    code, text, err = _cli(capsys, "combat", "train", "--npc", "jabber-v1", "--planner", _starter(which),
                           "--budget-ms", str(SLOW_HOST_MS), "--out", str(out))
    assert code == 0, err
    assert text.splitlines()[0].startswith(f"ruleset {PUBLIC_ARENA} "), "the ruleset comes first"
    assert "fallback" not in (text + err).lower()
    assert json.loads(out.read_text())["ruleset_digest"] == PUBLIC.digest.hex()
    code, text, err = _cli(capsys, "combat", "replay", str(out))
    assert code == 0, err + text


def test_the_builder_journey_on_an_open_arena(arena, tmp_path, capsys):
    starter = _starter("download")             # the copy the site hands out
    # 1. doctor --arena: same ruleset as the arena, entry open, the starter fights a full fight cleanly.
    code, text, err = _cli(capsys, "combat", "doctor", "--planner", starter, "--budget-ms", str(SLOW_HOST_MS),
                           "--arena", arena.url, "--state", str(tmp_path / "bots"))
    assert code == 0, text + err
    lines = {ln.split(":", 1)[0].split(None, 1)[1]: ln for ln in text.splitlines() if ":" in ln}
    assert lines["arena ruleset"].startswith("PASS") and PUBLIC.digest.hex() in lines["arena ruleset"]
    assert lines["arena entry"].startswith("PASS  arena entry: open")
    assert lines["planner fight"].startswith("PASS") and "no fallback" in lines["planner fight"]
    # 2. evaluate: a short benchmark against both new-move users, nothing falls back.
    code, text, err = _cli(capsys, "combat", "evaluate", "--planner", starter, "--budget-ms", str(SLOW_HOST_MS),
                           "--opponent", "stander", "--opponent", "feinter", "--seeds", "1", "--json")
    doc = json.loads(text)
    assert code == 0 and doc["ruleset_digest"] == PUBLIC.digest.hex()
    assert doc["planners"][0]["planner"]["fallback_rounds"] == 0
    # 3. join: the published command registers a fighter (register only; it polls with real sleeps).
    key, state = tmp_path / "me.seed", tmp_path / "join-state"
    stop = arena.ticking()
    try:
        code, text, err = _cli(capsys, "combat", "join", "--arena", arena.url, "--name", "Builder", "--key", str(key),
                               "--state", str(state), "--planner", starter, "--register-only")
    finally:
        stop()
    assert code == 0, text + err
    assert f"arena ruleset {PUBLIC_ARENA} {PUBLIC.digest.hex()}" in text and "registered on chain" in text
    info = J.Http(arena.url).get("/api/v1/join")
    assert info["ruleset_digest"] == PUBLIC.digest.hex()
    # 4. the fight: the same client and bot `combat join` runs, the starter planning,
    #    ticks held while it decides (the CLI races a real clock instead).
    subseed, pub = J.load_or_make_key(key)
    fid = bytes.fromhex(J.Http(arena.url).get(f"/api/v1/join/status?owner={pub.hex()}")["fighter_id"])
    client = J.RemoteClient(J.Http(arena.url), info, subseed, pub, fid, state)
    notes, botlog = [], []
    bot = Bot(client, PUBLIC, fid, pub, pub, planner_chooser(starter.split(), SLOW_HOST_MS, log=notes.append),
              Budget(ruleset_digest=PUBLIC.digest.hex(), max_stake=5000, max_total_escrow=20000), state,
              log=botlog.append)
    c = arena.arena.w.contract

    def mine(f):
        return fid in (f.context.participant_a.fighter_id, f.context.participant_b.fighter_id)
    done = None
    for _ in range(1500):
        client.refresh()
        bot.step()
        while bot.planning():
            time.sleep(0.02)
        arena.tick()
        done = next((f for f in c.fights.values() if mine(f) and f.phase == "DONE"), None)
        if done is not None:
            break
    assert done is not None, "the outside fighter finished a fight"
    assert done.result["kind"] == "COMBAT", f"a fought result, not {done.result}"
    assert not notes, f"the starter fell back or was adjusted: {notes}"
    # the bot reports a failed chooser or an adjusted (illegal) plan as "fight N round M: ..."
    assert not [m for m in botlog if re.match(r"fight \d+ round \d+: ", m)], botlog
    # 5. the arena's replay over HTTP: verified, under the public ruleset, and by the published command.
    arena.export()
    arena.fl.step()
    url = f"{arena.url}/data/combat/v1/fights/{done.fight_id}/replay.json"
    replay = J.Http(arena.url).get(f"/data/combat/v1/fights/{done.fight_id}/replay.json")
    manifest = J.Http(arena.url).get("/data/combat/v1/manifest.json")
    assert replay["ruleset_digest"] == manifest["ruleset_digest"] == PUBLIC.digest.hex()
    report = replaycheck.verify_arena_replay(replay)
    assert report["rules"] == PUBLIC_ARENA and report["outcome"] is not None
    code, text, err = _cli(capsys, "combat", "replay", url)
    assert code == 0, text + err
    # a tampered copy is refused by the same command
    replay["rounds"][0]["salts"]["A"] = "00" * 32
    bad = tmp_path / "tampered.json"
    bad.write_text(json.dumps(replay))
    code, text, err = _cli(capsys, "combat", "replay", str(bad))
    assert code != 0


def test_closed_entry_says_so_and_creates_nothing(tmp_path, capsys):
    a = Arena(tmp_path, open_entry=False)
    try:
        code, text, err = _cli(capsys, "combat", "doctor", "--arena", a.url, "--state", str(tmp_path / "bots"))
        assert code == 0, text + err                       # closed entry is a warning, not a failure
        entry = next(ln for ln in text.splitlines() if "arena entry" in ln)
        assert entry.startswith("WARN") and "closed" in entry and "practise and benchmark locally" in entry
        key = tmp_path / "me.seed"
        code, text, err = _cli(capsys, "combat", "join", "--arena", a.url, "--name", "Builder", "--key", str(key),
                               "--register-only")
        assert code != 0 and "entry is closed" in str(code) + text + err and "nothing was created" in str(code) + text + err
        assert not key.exists()
    finally:
        a.srv.shutdown()
