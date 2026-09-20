"""A fighter on Windows (issue #21).

There is no Windows machine in this test run, so every branch that asks
which OS this is gets driven here with `sys.platform` faked to "win32",
which is what `portable.is_windows()` reads on each call. The parts a fake
cannot prove -- that the launcher runs on a real Windows, that msvcrt really
locks, that the console really switches into VT mode -- README.md names as
unverified. The slot lock's POSIX half is tested for real, across processes,
through the actual solver script; its Windows half is exercised with a fake
msvcrt so the call is at least the right one.
"""
import ast
import io
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
import types

import pytest

from qdojo import bot, cli, dash, onboard, portable, prompts, seedconf, solver, term, wizard
from qdojo.chain import FakeChain
from qdojo.chain.cli import SeedConfError, check_seed_conf

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
CHECK = os.path.join(ROOT, "scripts", "check-portable.py")
PWSH = os.environ.get("QDOJO_PWSH") or shutil.which("pwsh")
SEED = "w" * 55
RIDDLE = {"round_id": 1, "title": "white belt: sum the numbers", "statement": "Add every number below.",
          "input": "1 2", "answer_format": "integer"}


@pytest.fixture
def win(monkeypatch):
    """This process, pretending. `_vt` is the cached console answer."""
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(portable, "_vt", None)


@pytest.fixture
def plain():
    term.set_enabled(False)
    yield
    term.set_enabled(None)


def conf(path, mode=0o600):
    path = str(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="\n") as f:
        f.write(f"seed={SEED}\n")
    os.chmod(path, mode)
    return path


# ------------------------------------------------------------------ the answer

def test_the_os_is_asked_on_every_call_never_at_import(monkeypatch):
    assert not portable.is_windows()
    assert portable.python_name() == "python3" and portable.shell_name() == "sh"
    assert portable.env_ref("K") == "$K" and portable.export_hint("K") == "export K=..."
    assert portable.private_modes_enforced()
    monkeypatch.setattr(sys, "platform", "win32")
    assert portable.is_windows()
    assert portable.python_name() == "python" and portable.shell_name() == "powershell"
    assert portable.env_ref("K") == "$env:K" and portable.export_hint("K") == "$env:K = '...'"
    assert not portable.private_modes_enforced()


# --------------------------------------------------------------- the interpreter

def test_a_python_this_machine_lacks_becomes_the_one_qdojo_runs_on(monkeypatch):
    monkeypatch.setattr(portable.shutil, "which", lambda cmd, **kw: None)
    assert portable.resolve_command(["python3", "s.py", "--x"]) == [sys.executable, "s.py", "--x"]
    assert portable.resolve_command(["python", "s.py"]) == [sys.executable, "s.py"]
    assert portable.resolve_command(["python3.12", "s.py"])[0] == sys.executable
    assert portable.resolve_command(["/gone/.venv/bin/python", "s.py"]) == [sys.executable, "s.py"]
    assert portable.resolve_command(["node", "s.js"]) == ["node", "s.js"]      # not a python: not our business
    assert portable.resolve_command([]) == []


def test_a_python_that_is_there_is_left_alone(monkeypatch):
    monkeypatch.setattr(portable.shutil, "which", lambda cmd, **kw: "/usr/bin/" + cmd)
    assert portable.resolve_command(["python3", "s.py"]) == ["python3", "s.py"]
    assert portable.resolve_command([sys.executable, "s.py"]) == [sys.executable, "s.py"]


def test_the_store_alias_does_not_count_as_a_python(win, monkeypatch):
    stub = r"C:\Users\me\AppData\Local\Microsoft\WindowsApps\python.exe"
    monkeypatch.setattr(portable.shutil, "which", lambda cmd, **kw: stub)
    assert portable.resolve_command(["python", "s.py"]) == [sys.executable, "s.py"]
    monkeypatch.setattr(portable.shutil, "which", lambda cmd, **kw: r"C:\Python312\python.exe")
    assert portable.resolve_command(["python", "s.py"]) == ["python", "s.py"]


def test_a_bare_script_gets_an_interpreter_on_windows_only(monkeypatch):
    assert portable.resolve_command(["examples/solvers/bare.py"]) == ["examples/solvers/bare.py"]
    monkeypatch.setattr(sys, "platform", "win32")
    assert portable.resolve_command([r"examples\solvers\bare.py"]) == [sys.executable, r"examples\solvers\bare.py"]


def test_run_solver_and_the_strategy_resolve_the_interpreter(monkeypatch, tmp_path):
    """python3 is not on this PATH, says the fake which, and both still run."""
    monkeypatch.setattr(portable.shutil, "which", lambda cmd, **kw: None)
    prog = "import sys; sys.stdin.read(); print('{\"answer\": 3}')"
    assert solver.run_solver(["python3", "-c", prog], RIDDLE) == "3"
    me = "A" * 60
    b = bot.Bot(FakeChain(identity=me, balances={me: 5000}), str(tmp_path / "s"), ["true"],
                strategy_cmd=["python", "-c", "import sys; sys.stdin.read(); print('{\"enter\": false, \"why\": \"w\"}')"])
    actions = []
    assert b._strategy_says_enter({"round_id": 1, "entry_fee": 10}, {}, 100, actions, "1") is False
    assert actions == ["round 1: strategy says skip (w)"]


# -------------------------------------------------------------- the command line

def test_split_command_keeps_backslashes_on_windows(win):
    assert portable.split_command(r'python "C:\Users\me\my solver\s.py" --x') == \
        ["python", r"C:\Users\me\my solver\s.py", "--x"]


def test_split_command_is_posix_elsewhere():
    assert portable.split_command("python3 'a b.py' --x") == ["python3", "a b.py", "--x"]


def test_ps_quote_wraps_what_powershell_would_eat():
    for plain_arg in ("--board", "https://x/y.json", r"C:\a\b.py", "deepseek/deepseek-v4-flash", "RYU"):
        assert portable.ps_quote(plain_arg) == plain_arg
    assert portable.ps_quote("RYU BOT") == "'RYU BOT'"
    assert portable.ps_quote("a,b") == "'a,b'"
    assert portable.ps_quote("it's") == "'it''s'"
    assert portable.ps_quote("$env:X") == "'$env:X'"
    assert portable.ps_quote("") == "''"
    assert portable.ps_string("m/x") == "'m/x'"                     # an assignment's right-hand side: always a string
    assert portable.quote("a b", "sh") == "'a b'" and portable.quote("a b", "powershell") == "'a b'"


def test_the_run_command_is_written_for_powershell_on_windows(win):
    prof = {"conf": "/x/state/bot.conf", "name": "RYU BOT", "solver": ["python", r"C:\a b\pi.py"],
            "solver_env": {"PI_MODEL": "m/x"}}
    text = wizard.run_command_text(prof, "http://b")
    lines = text.splitlines()
    assert lines[0] == "$env:PI_MODEL = 'm/x'"
    assert lines[1].startswith("qdojo bot") and lines[1].endswith(" `")
    assert "'RYU BOT'" in text and "'C:\\a b\\pi.py'" in text and "\\\n" not in text and "PI_MODEL=m/x" not in text
    one = wizard.run_command_text(prof, "http://b", wrap=False)
    assert one.startswith("$env:PI_MODEL = 'm/x'; qdojo bot ") and "\n" not in one
    assert wizard.run_command_text(prof, "http://b", shell="sh", wrap=False).startswith("PI_MODEL=m/x qdojo bot ")
    assert wizard.run_command(prof, "http://b") == wizard.run_command(prof, "http://b")     # the argv is the same


def test_the_default_solver_line_names_the_python_of_the_os(win):
    assert wizard.run_command({"conf": "", "solver": []}, "http://b")[-2:] == ["python", "examples/solvers/echo.py"]


# ------------------------------------------------------------- the runtime dir

def test_the_runtime_dir_on_windows_is_localappdata(win, monkeypatch):
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\me\AppData\Local")
    assert seedconf.runtime_dir() == os.path.join(r"C:\Users\me\AppData\Local", "qdojo", "run")
    monkeypatch.delenv("LOCALAPPDATA")
    assert seedconf.runtime_dir() == os.path.join(os.path.expanduser("~"), "AppData", "Local", "qdojo", "run")
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/x")                     # explicit still wins, on any OS
    assert seedconf.runtime_dir() == os.path.join("/x", "qdojo")


def test_the_startup_check_reads_the_windows_runtime_dir(win, monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    left = conf(tmp_path / "qdojo" / "run" / "qdojo_old.conf")
    assert [x["path"] for x in seedconf.warn_leftovers()] == [left]
    assert "warning: 1 seed conf in" in capsys.readouterr().err and os.path.exists(left)


# ----------------------------------------------------------------- file modes

def test_check_seed_conf_ignores_the_mode_where_the_os_has_none(tmp_path, monkeypatch):
    p = conf(tmp_path / "c.conf", 0o644)
    with pytest.raises(SeedConfError):
        check_seed_conf(p)
    monkeypatch.setattr(sys, "platform", "win32")
    check_seed_conf(p)                                              # the mode is not the OS's to promise
    with pytest.raises(SeedConfError):
        check_seed_conf(str(tmp_path / "missing.conf"))             # existence still is
    bad = tmp_path / "bad.conf"
    bad.write_text("seed=nope\n")
    with pytest.raises(SeedConfError):
        check_seed_conf(str(bad))                                   # and so is the seed


def test_the_rite_says_what_keeps_the_seed_private_on_windows(tmp_path, monkeypatch, capsys, plain):
    p = conf(tmp_path / "bot.conf", 0o644)
    opts = wizard._opts(state=str(tmp_path), conf=p)
    with pytest.raises(wizard.WizardError):
        wizard._step_seed(opts, {}, 2, 6)                           # here 0644 is refused
    assert "not 0600" in capsys.readouterr().out
    monkeypatch.setattr(sys, "platform", "win32")
    ctx = {}
    wizard._step_seed(opts, ctx, 2, 6)
    out = capsys.readouterr().out
    assert "one Windows user per fighter" in out and "0600" not in out and "back this file up" in out
    assert ctx["conf"] == p and len(ctx["identity"]) == 60


def test_the_whole_rite_runs_on_windows(win, tmp_path, monkeypatch, capsys, plain):
    """bot init end to end with the OS faked: a conf is written, the card is
    printed in PowerShell, and nothing insists on a mode."""
    from qdojo import nodes
    monkeypatch.setattr(nodes, "native_probe", lambda timeout=6.0: (lambda ip: (1000, [])))

    class Chain:
        def __init__(self, ip, port=21841, **kw):
            pass

        def balance(self, identity):
            return 5000
    monkeypatch.setattr(wizard, "NativeChain", Chain)
    prof = wizard.init(state=str(tmp_path / "state"), name="RYUBOT", provider="none", yes=True)
    out = capsys.readouterr().out
    assert prof["identity"] in out and os.path.exists(prof["conf"])
    assert "private to your Windows user" in out and "yours alone" in out and "0600" not in out
    assert "the test riddle is solved" in out                       # bare.py ran under sys.executable
    assert " `\n" in out and " \\\n" not in out                     # the card's command is PowerShell


def test_a_new_conf_is_lf_only_on_every_os(tmp_path):
    p = onboard.create_conf(str(tmp_path / "bot.conf"))
    data = open(p, "rb").read()
    assert data.endswith(b"\n") and b"\r" not in data and len(data) == 61


def test_shred_clears_read_only_first_on_windows(tmp_path, monkeypatch):
    """os.chmod(0o400) is how a file goes read-only there, and a read-only
    file can neither be overwritten nor unlinked. Compare
    test_seedconf.test_shred_unlinks_even_when_the_overwrite_fails."""
    p = conf(tmp_path / "ro.conf", 0o400)
    monkeypatch.setattr(sys, "platform", "win32")
    assert seedconf.shred(p) is True
    assert not os.path.exists(p)


# ------------------------------------------------------------------ signals

def test_ephemeral_also_catches_ctrl_break_where_the_os_has_it(tmp_path, monkeypatch):
    """SIGBREAK exists only on Windows; SIGUSR1 stands in for it here, and the
    conf must go when it arrives, with both handlers put back afterwards."""
    assert seedconf.exit_signals() == [signal.SIGTERM]
    monkeypatch.setattr(signal, "SIGBREAK", signal.SIGUSR1, raising=False)
    assert seedconf.exit_signals() == [signal.SIGTERM, signal.SIGUSR1]
    p = conf(tmp_path / "t.conf")
    before = signal.getsignal(signal.SIGUSR1), signal.getsignal(signal.SIGTERM)
    with pytest.raises(SystemExit) as e:
        with seedconf.ephemeral(p):
            assert signal.getsignal(signal.SIGUSR1) is signal.getsignal(signal.SIGTERM)
            os.kill(os.getpid(), signal.SIGUSR1)
            time.sleep(5)
    assert e.value.code == 128 + signal.SIGUSR1
    assert not os.path.exists(p)
    assert (signal.getsignal(signal.SIGUSR1), signal.getsignal(signal.SIGTERM)) == before


# ----------------------------------------------------------------- the console

def test_a_redirected_stdout_replaces_what_its_code_page_cannot_encode(monkeypatch):
    buf = io.BytesIO()
    fake = io.TextIOWrapper(buf, encoding="cp1252", errors="strict")
    monkeypatch.setattr(sys, "stdout", fake)
    with pytest.raises(UnicodeEncodeError):
        print("\u2714")
    portable.tolerant_stdio()
    print("\u2714 ok \u2026")
    fake.flush()
    assert buf.getvalue() == b"? ok \x85\n"                         # cp1252 has the ellipsis, not the tick
    utf = io.TextIOWrapper(io.BytesIO(), encoding="utf-8", errors="strict")
    monkeypatch.setattr(sys, "stdout", utf)
    portable.tolerant_stdio()
    assert utf.errors == "strict"                                   # a UTF-8 stream is left alone


def test_styling_falls_back_when_the_console_cannot_take_escapes(win, monkeypatch):
    class Tty(io.StringIO):
        def isatty(self):
            return True
    for v in ("NO_COLOR", "FORCE_COLOR"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setenv("TERM", "xterm")
    term.set_enabled(None)
    assert term.enabled(Tty()) is False                             # no kernel32 here: the switch cannot be made
    assert portable._vt is False                                    # asked once, remembered
    monkeypatch.setattr(sys, "platform", "linux")
    assert term.enabled(Tty()) is True
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(portable, "_vt", True)                      # a console that agreed
    assert term.enabled(Tty()) is True


# -------------------------------------------------------------- paths and names

def test_a_prompt_name_with_either_slash_is_refused(tmp_path):
    for bad in ("../x.md", "..\\x.md", "a/b.md", "a\\b.md", ".hidden.md"):
        with pytest.raises(prompts.PromptError):
            prompts.find(bad, str(tmp_path))


def test_sibling_files_beside_a_board(monkeypatch):
    assert portable.sibling("https://h/qdojo/data/board.json", "history.json") == "https://h/qdojo/data/history.json"
    assert portable.sibling("data/board.json", "fighters.json") == os.path.join("data", "fighters.json")
    assert portable.sibling("board.json", "fighters.json") == "fighters.json"
    assert cli._history_url("https://h/d/history.json") == "https://h/d/history.json"
    monkeypatch.setattr(sys, "platform", "win32")
    assert portable.sibling(r"C:\d\board.json", "fighters.json") == r"C:\d\fighters.json"
    assert portable.sibling("C:/d/board.json", "fighters.json") == "C:/d\\fighters.json"
    assert cli._history_url(r"C:\d\board.json") == r"C:\d\history.json"


def test_bot_dash_open_asks_the_default_browser(monkeypatch, capsys):
    import webbrowser
    opened = []

    class Httpd:
        def serve_forever(self):
            raise KeyboardInterrupt
    monkeypatch.setattr(dash, "serve", lambda state, board="", port=7777, read_only=False: (Httpd(), "http://127.0.0.1:7/?t=x"))
    monkeypatch.setattr(webbrowser, "open", lambda url, **kw: opened.append(url) or True)
    cli.main(["bot", "--state", "s", "dash", "--open"])
    assert opened == ["http://127.0.0.1:7/?t=x"]
    cli.main(["bot", "--state", "s", "dash"])
    assert opened == ["http://127.0.0.1:7/?t=x"]                   # not without the flag
    assert "http://127.0.0.1:7/?t=x" in capsys.readouterr().out    # and the URL is printed either way


# ------------------------------------------------------------ the launchers

def _read(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return f.read()


def test_the_windows_launchers_mirror_dojo():
    sh, ps, cmd = _read("dojo"), _read("dojo.ps1"), _read("dojo.cmd")
    # the same usage block, in the Windows spelling
    usage = [l.replace("./dojo", ".\\dojo.cmd").replace("~/.qdojo", "%USERPROFILE%\\.qdojo") for l in sh.splitlines()[3:11]]
    assert ps.splitlines()[2:10] == usage
    # the same subcommands to the same qdojo commands
    for name, target in (("train", "train"), ("rite", "bot init"), ("fight", "bot run"), ("dash", "bot dash"),
                         ("prompts", "prompts")):
        assert f"{name})" in sh and f"run {target} " in sh
        assert f"'{name}'" in ps and f"Run {target} @Rest" in ps
    # uv: PATH, the two install dirs, three hints, sync, the offline fallback
    for want in (".local\\bin\\uv.exe", ".cargo\\bin\\uv.exe", "winget install --id=astral-sh.uv -e", "pipx install uv",
                 "irm https://astral.sh/uv/install.ps1 | iex", "sync --quiet", ".venv\\Scripts\\qdojo.exe",
                 "could not sync (offline?)"):
        assert want in ps, want
    # the first run: a free training fight with bare.py, gated on the profile
    assert "train --solver python examples/solvers/bare.py" in ps and ".qdojo\\bot\\bot.json" in ps
    assert "train --solver python3 examples/solvers/bare.py" in sh
    # no URL is piped into a shell by either
    assert "| iex" not in ps.replace("irm https://astral.sh/uv/install.ps1 | iex", "")
    assert "| sh" not in sh.replace("curl -LsSf https://astral.sh/uv/install.sh | sh", "")
    # the shim only starts the script
    assert "-ExecutionPolicy Bypass" in cmd and "dojo.ps1" in cmd and "%*" in cmd and cmd.count("\n") <= 12


def _pwsh(*args, env=None, timeout=120):
    return subprocess.run([PWSH, "-NoProfile", *args], capture_output=True, text=True, timeout=timeout, env=env)


@pytest.mark.skipif(not PWSH, reason="no pwsh on this box: dojo.ps1 is not parsed here")
def test_dojo_ps1_parses(tmp_path):
    parser = tmp_path / "parse.ps1"
    parser.write_text(textwrap.dedent("""
        param([string]$Path)
        $tokens = $null; $errors = $null
        [System.Management.Automation.Language.Parser]::ParseFile($Path, [ref]$tokens, [ref]$errors) | Out-Null
        if ($errors.Count) { $errors | ForEach-Object { $_.ToString() }; exit 1 }
        'parsed'
    """))
    r = _pwsh("-File", str(parser), os.path.join(ROOT, "dojo.ps1"))
    assert r.returncode == 0 and "parsed" in r.stdout, r.stdout + r.stderr


@pytest.mark.skipif(not PWSH, reason="no pwsh on this box: dojo.ps1 is not dry-run here")
def test_dojo_ps1_dry_runs_with_a_fake_uv(tmp_path):
    """The script's own logic, on Linux under pwsh: help, the three hints
    when there is no uv, the sync failure, and which qdojo command each
    subcommand reaches. A real Windows has not run this."""
    ps1 = os.path.join(ROOT, "dojo.ps1")
    home = tmp_path / "home"
    home.mkdir()
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    log = tmp_path / "uv.log"
    uv = bin_ / "uv"
    uv.write_text("#!/bin/sh\n"
                  "printf '%s\\n' \"$*\" >> \"$UV_LOG\"\n"
                  "[ \"$1\" = --version ] && echo 'uv 0.0.0'\n"
                  "[ \"$1\" = sync ] && [ -n \"$UV_SYNC_FAILS\" ] && { echo boom >&2; exit 1; }\n"
                  "exit 0\n")
    os.chmod(uv, 0o755)
    env = {**os.environ, "USERPROFILE": str(home), "UV_LOG": str(log)}

    r = _pwsh("-File", ps1, "help")
    assert r.returncode == 0 and "fight past rounds again" in r.stdout and "It writes nothing" in r.stdout

    r = _pwsh("-File", ps1, "train", env={**env, "PATH": str(tmp_path / "nowhere")})
    assert r.returncode == 1
    for hint in ("winget install --id=astral-sh.uv -e", "pipx install uv", "install.ps1 | iex"):
        assert hint in r.stderr, r.stderr
    assert not log.exists()

    env["PATH"] = str(bin_) + os.pathsep + os.environ.get("PATH", "")
    r = _pwsh("-File", ps1, "train", env={**env, "UV_SYNC_FAILS": "1"})
    assert r.returncode == 1 and "uv sync failed" in r.stderr and "  boom" in r.stderr
    assert log.read_text().splitlines() == ["--version", "sync --quiet"]

    def reaches(*args, **extra):
        log.write_text("")
        r = _pwsh("-File", ps1, *args, env={**env, **extra})
        return r, [l for l in log.read_text().splitlines() if l.startswith("run ")]

    r, ran = reaches("rite", "--yes", "--name", "RYU BOT")
    assert r.returncode == 0 and ran == ["run qdojo bot init --yes --name RYU BOT"] and "ready" in r.stdout
    r, ran = reaches("fight", "--board", "http://b")
    assert ran == ["run qdojo bot run --board http://b"]
    assert reaches("dash")[1] == ["run qdojo bot dash"] and reaches("prompts", "list")[1] == ["run qdojo prompts list"]
    r, ran = reaches("nonsense")
    assert r.returncode == 1 and "no such thing as 'nonsense'" in r.stderr and ran == []
    # nothing set up: the free training fight with bare.py, and a leading flag is not a subcommand
    r, ran = reaches("--rounds", "3")
    assert r.returncode == 0 and ran == ["run qdojo train --solver python examples/solvers/bare.py --rounds 3"]
    assert "costs nothing" in r.stdout and ".\\dojo.cmd rite" in r.stdout
    # set up: plain training
    os.makedirs(home / ".qdojo" / "bot")
    (home / ".qdojo" / "bot" / "bot.json").write_text("{}")
    r, ran = reaches("--rounds", "3")
    assert ran == ["run qdojo train --rounds 3"], ran


# ------------------------------------------------------------- the slot lock

def _lock_block(src: str) -> str:
    """The lock as written in a solver: the try/except import, SLOTS, _slot."""
    tree = ast.parse(src)
    keep = [n for n in tree.body
            if (isinstance(n, ast.Try) and any(isinstance(s, ast.Import) for s in n.body))
            or (isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "SLOTS")
            or (isinstance(n, ast.FunctionDef) and n.name == "_slot")]
    assert len(keep) == 3, [type(n).__name__ for n in keep]
    return "\n".join(ast.unparse(n) for n in keep)


def _solver(name):
    with open(os.path.join(ROOT, "examples", "solvers", name), encoding="utf-8") as f:
        return f.read()


def test_both_llm_solvers_carry_the_same_portable_lock():
    block = _lock_block(_solver("pi.py"))
    assert block == _lock_block(_solver("evo.py"))
    assert "fcntl" in block and "msvcrt" in block and "tempfile.gettempdir()" in block and "/tmp" not in block


def test_the_windows_half_of_the_lock_calls_msvcrt(tmp_path, monkeypatch):
    """No msvcrt here, so a fake one records the call the real one would get:
    LK_NBLCK on one byte at offset 0 of a slot file under the temp dir."""
    calls = []
    fake = types.SimpleNamespace(LK_NBLCK=2, locking=lambda fd, mode, n: calls.append((fd, mode, n)))
    monkeypatch.setitem(sys.modules, "fcntl", None)                 # `import fcntl` now raises ImportError
    monkeypatch.setitem(sys.modules, "msvcrt", fake)
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    monkeypatch.setattr(tempfile, "tempdir", None)
    ns = {"os": os, "sys": sys, "time": time, "tempfile": tempfile}
    exec(_lock_block(_solver("pi.py")), ns)
    f = ns["_slot"](max_slots=1, wait=0)
    assert calls == [(f.fileno(), 2, 1)] and f.tell() == 0
    assert os.path.dirname(f.name) == os.path.join(str(tmp_path), "qdojo-pi-slots")
    f.close()


def test_the_slot_lock_is_exclusive_across_processes(tmp_path):
    """The POSIX half, for real: two pi.py processes and one slot. The second
    must give up with exit 3 while the first still holds its model."""
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    pi = bin_ / "pi"
    pi.write_text(f"#!{sys.executable}\nimport time\ntime.sleep(3)\nprint('{{\"answer\": 1}}')\n")
    os.chmod(pi, 0o755)
    env = {**os.environ, "PATH": str(bin_) + os.pathsep + os.environ.get("PATH", ""), "PI_MODEL": "m",
           "PI_MAX_CONCURRENT": "1", "PI_SLOT_WAIT": "1", "TMPDIR": str(tmp_path)}
    script = os.path.join(ROOT, "examples", "solvers", "pi.py")
    riddle = json.dumps(RIDDLE)
    (tmp_path / "riddle.json").write_text(riddle)
    with open(tmp_path / "riddle.json") as stdin:
        first = subprocess.Popen([sys.executable, script], stdin=stdin, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, env=env, text=True)
    time.sleep(1.0)
    second = subprocess.run([sys.executable, script], input=riddle, capture_output=True, env=env, text=True,
                            timeout=30)
    assert second.returncode == 3 and "no model slot free" in second.stderr, second.stderr
    out, err = first.communicate(timeout=30)
    assert first.returncode == 0 and '"answer": 1' in out, err
    assert sorted(os.listdir(tmp_path / "qdojo-pi-slots")) == ["0"]          # under the temp dir, not /tmp


# ------------------------------------------------------------- the checker

def _check(*paths):
    return subprocess.run([sys.executable, CHECK, *paths], capture_output=True, text=True, timeout=120)


def test_the_fighter_side_passes_the_portability_check():
    r = _check()
    assert r.returncode == 0, r.stdout + r.stderr
    assert "clean" in r.stdout


def test_the_check_flags_what_is_unguarded_and_accepts_what_is_guarded(tmp_path):
    bad = tmp_path / "bad.py"
    bad.write_text(textwrap.dedent('''
        """A docstring may say /tmp and import fcntl; that is prose."""
        import fcntl
        import os, signal, subprocess
        uid = os.getuid()
        p = "/tmp/x"
        subprocess.run(["ls"], shell=True)
        signal.signal(signal.SIGUSR1, None)
    '''))
    r = _check(str(bad))
    assert r.returncode == 1
    for what in ("import fcntl", "os.getuid", "'/tmp/x'", "shell=True", "signal.SIGUSR1"):
        assert what in r.stdout, r.stdout
    assert f"{bad}:3:" in r.stdout and "5 finding(s)" in r.stdout
    good = tmp_path / "good.py"
    good.write_text(textwrap.dedent('''
        import os, sys
        try:
            import fcntl
        except ImportError:
            fcntl = None
        if sys.platform == "win32":
            base = os.environ.get("LOCALAPPDATA")
        else:
            base = f"/run/user/{os.getuid()}"

        def f():
            if portable.is_windows():
                return 1
            else:
                return os.getuid()
    '''))
    r = _check(str(good))
    assert r.returncode == 0, r.stdout
