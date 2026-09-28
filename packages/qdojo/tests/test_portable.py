"""A fighter on Windows (issue #21).

There is no Windows machine in this test run, so every branch that asks
which OS this is gets driven here with `sys.platform` faked to "win32",
which is what `portable.is_windows()` reads on each call. A planner command
is resolved through `portable.resolve_command` (combat/planner.py), and
scripts/check-portable.py keeps the package free of unguarded POSIX-only code.
"""
import io
import os
import subprocess
import sys
import textwrap
import types

import pytest

from qdojo import portable

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
CHECK = os.path.join(ROOT, "scripts", "check-portable.py")


@pytest.fixture
def win(monkeypatch):
    """This process, pretending."""
    monkeypatch.setattr(sys, "platform", "win32")


# ------------------------------------------------------------------ the answer

def test_the_os_is_asked_on_every_call_never_at_import(monkeypatch):
    assert not portable.is_windows()
    assert portable.private_modes_enforced()
    monkeypatch.setattr(sys, "platform", "win32")
    assert portable.is_windows()
    assert not portable.private_modes_enforced()


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
    monkeypatch.setattr(portable, "_alias_probed", {})
    monkeypatch.setattr(portable.shutil, "which", lambda cmd, **kw: stub)
    monkeypatch.setattr(portable.subprocess, "run",
                        lambda *a, **kw: types.SimpleNamespace(returncode=9009))    # App Installer stub
    assert portable.resolve_command(["python", "s.py"]) == [sys.executable, "s.py"]
    monkeypatch.setattr(portable.shutil, "which", lambda cmd, **kw: r"C:\Python312\python.exe")
    assert portable.resolve_command(["python", "s.py"]) == ["python", "s.py"]


def test_a_real_store_python_at_the_same_alias_path_is_left_alone(win, monkeypatch):
    """A Python installed FROM the Store is reached through the identical
    WindowsApps alias path as the App Installer stub; only running it tells
    them apart (issue: the path-only check swapped this out for good)."""
    real = r"C:\Users\me\AppData\Local\Microsoft\WindowsApps\python.exe"
    probed = []
    monkeypatch.setattr(portable, "_alias_probed", {})
    monkeypatch.setattr(portable.shutil, "which", lambda cmd, **kw: real)

    def fake_run(argv, **kw):
        probed.append(argv)
        return types.SimpleNamespace(returncode=0)                             # a real Store Python

    monkeypatch.setattr(portable.subprocess, "run", fake_run)
    assert portable.resolve_command(["python", "s.py"]) == ["python", "s.py"]
    assert probed == [[real, "-c", "pass"]]
    # cached: a second resolution does not probe again
    assert portable.resolve_command(["python", "s.py"]) == ["python", "s.py"]
    assert probed == [[real, "-c", "pass"]]


def test_a_bare_script_gets_an_interpreter_on_windows_only(monkeypatch):
    assert portable.resolve_command(["examples/combat/planner_minimal.py"]) == ["examples/combat/planner_minimal.py"]
    monkeypatch.setattr(sys, "platform", "win32")
    assert portable.resolve_command([r"examples\combat\planner_minimal.py"]) == [sys.executable, r"examples\combat\planner_minimal.py"]


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
