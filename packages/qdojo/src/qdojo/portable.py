"""Where the fighter side differs between Windows and everything else.

A fighter's planner runs on a stranger's machine, and a lot of those machines
are Windows (issue #21). Everything in the package that has to ask "which OS
is this" asks here, so the answer is in one place and every branch can be
driven from a test with `sys.platform` faked.

What differs, each with its own function below:

  * the word for Python. Linux has `python3` and often no `python`; Windows
    has `python` and never `python3`. A planner is recorded as a command
    line, so the interpreter at the front of it is the one token that stops
    a command written on one OS from working on the other. `resolve_command`
    maps a leading python that this machine cannot run to the one qdojo
    itself runs on.
  * file modes. `os.chmod(path, 0o600)` on Windows toggles the read-only
    attribute and nothing else, so a check that insists on private modes
    can only fail there (`private_modes_enforced`).
  * the console. A redirected stdout uses the locale's code page, in which a
    tick mark cannot be encoded (`tolerant_stdio`).

`sys.platform` is read on every call, never at import, so a test can flip it.
"""
import os
import re
import shutil
import subprocess
import sys


def is_windows() -> bool:
    return sys.platform == "win32"


def private_modes_enforced() -> bool:
    """Whether 0600 and 0700 mean anything on this OS. On Windows they do
    not, and a check that insists on them can only ever fail."""
    return not is_windows()


# ------------------------------------------------------------ the interpreter

_PYTHON_RE = re.compile(r"^python(3(\.\d+)?)?$")


def looks_like_python(token: str) -> bool:
    """`python`, `python3`, `python3.12`, with or without a directory in
    front and `.exe` behind: the tokens a planner line starts with."""
    base = os.path.basename(str(token)).lower()
    if base.endswith(".exe"):
        base = base[:-4]
    return bool(_PYTHON_RE.match(base))


_alias_probed: dict[str, bool] = {}


def _windows_apps_alias_runs(found: str) -> bool:
    """Whether a `python.exe` found under `%LOCALAPPDATA%\\Microsoft\\
    WindowsApps` is a real Python rather than the App Installer stub.

    A Python installed FROM the Store is reached through exactly that same
    alias directory (Windows' own docs: typing `python` there "will be
    available from any Command Prompt"), so the directory alone cannot tell
    the two apart. The stub, run with an argument, prints "Python was not
    found" and exits non-zero instead of opening the Store window; a real
    one runs the argument like any other Python. Probed once and cached per
    resolved path, since `resolve_command` re-checks this every round."""
    if found not in _alias_probed:
        try:
            p = subprocess.run([found, "-c", "pass"], capture_output=True, timeout=15)
            _alias_probed[found] = p.returncode == 0
        except (OSError, subprocess.SubprocessError):
            _alias_probed[found] = False
    return _alias_probed[found]


def runnable(token: str) -> bool:
    """Whether `token` names a program this machine can start.

    A token with a directory in it must exist there; a bare one must be on
    PATH. On Windows the Store plants a `python.exe` under
    `%LOCALAPPDATA%\\Microsoft\\WindowsApps`; that alias is a real Store
    Python for some users and the App Installer's shop-window stub for
    others, at the same path, so it is settled by running it once (see
    `_windows_apps_alias_runs`) rather than guessed from the path.
    """
    token = str(token)
    if os.path.dirname(token):
        return os.path.isfile(token)
    found = shutil.which(token)
    if not found:
        return False
    if is_windows() and "\\microsoft\\windowsapps\\" in found.lower().replace("/", "\\"):
        return _windows_apps_alias_runs(found)
    return True


def resolve_command(argv) -> list[str]:
    """The argv a planner is run as, made to start on this machine.

    When the leading token is a python this machine cannot run -- a bare
    `python3` on Windows, a bare `python` on a Linux without one, or the
    absolute path of a venv that is not here -- it becomes the interpreter
    qdojo itself runs on, which is a Python that exists. A python that IS
    runnable is left alone: someone who put a `python3` on PATH meant it.
    On Windows a leading `.py` file also gets that interpreter put in front,
    because CreateProcess cannot run a script by itself the way a shebang
    does. Anything else is returned untouched.
    """
    argv = [str(a) for a in (argv or [])]
    if not argv:
        return argv
    head = argv[0]
    if looks_like_python(head) and not runnable(head):
        _note_swap(head, sys.executable)
        return [sys.executable] + argv[1:]
    if is_windows() and head.lower().endswith(".py"):
        return [sys.executable] + argv
    return argv


_noted_swaps: set[str] = set()


def _note_swap(head: str, to: str) -> None:
    """Say once, on stderr, that a planner line's leading interpreter
    was mapped to the one qdojo itself runs on -- so the swap is never
    silent, and a fighter whose recorded interpreter has moved or vanished
    has something to go on besides an unrelated import error."""
    if head in _noted_swaps:
        return
    _noted_swaps.add(head)
    print(f"qdojo: {head} is not runnable here; running under {to}", file=sys.stderr)


# ----------------------------------------------------------------- the console

def tolerant_stdio() -> None:
    """Never let an unencodable character end a run.

    A Windows console proper takes any character (Python writes it as
    UTF-16), but stdout redirected to a file or a pipe uses the locale code
    page, and cp1252 has no tick mark. `print` would then raise
    UnicodeEncodeError -- a ValueError, which a long run can catch as a
    warning, losing the line that said what it had just sent. Replacing the
    character with `?` keeps the line. A UTF-8 stream is left exactly as it
    is; so is anything that cannot be reconfigured.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            if (getattr(stream, "encoding", "") or "").lower().replace("-", "") != "utf8":
                stream.reconfigure(errors="replace")
        except (AttributeError, ValueError, OSError):
            pass
