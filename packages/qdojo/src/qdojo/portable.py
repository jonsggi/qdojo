"""Where the fighter side differs between Windows and everything else.

A fighter runs on a stranger's machine, and a lot of those machines are
Windows (issue #21). The house stays on the operator's Linux box and may be
as POSIX as it likes; a bot may not. Everything in the package that has to
ask "which OS is this" asks here, so the answer is in one place and every
branch can be driven from a test with `sys.platform` faked.

What differs, each with its own function below:

  * the word for Python. Linux has `python3` and often no `python`; Windows
    has `python` and never `python3`. A profile records its solver as a
    command line, so the interpreter at the front of it is the one token
    that stops a profile written on one OS from working on the other.
    `resolve_command` maps a leading python that this machine cannot run to
    the one qdojo itself runs on.
  * quoting and splitting. A backslash is an escape to a POSIX shell and a
    path separator to Windows, and an environment variable rides in front
    of a command in sh but has to be set on its own line in PowerShell.
  * file modes. `os.chmod(path, 0o600)` on Windows toggles the read-only
    attribute and nothing else, and `os.open(..., 0o600)` cannot keep other
    users out. What keeps a seed conf private there is the ACL on the user
    profile, which is why the docs say one Windows user per fighter.
  * the runtime directory. There is no tmpfs `/run/user/<uid>`; seedconf
    uses `%LOCALAPPDATA%\\qdojo\\run` instead, and says so.
  * the console. A legacy cmd.exe window prints escape sequences as text
    until it is switched into VT mode, and a redirected stdout uses the
    locale's code page, in which a tick mark cannot be encoded.

`sys.platform` is read on every call, never at import, so a test can flip it.
"""
import ntpath
import os
import re
import shlex
import shutil
import subprocess
import sys


def is_windows() -> bool:
    return sys.platform == "win32"


def python_name() -> str:
    """The word a person types to run Python on this OS. This is for text
    shown to a human; code that has to RUN something uses `sys.executable`."""
    return "python" if is_windows() else "python3"


def shell_name() -> str:
    """The shell a printed command is written for: sh, or PowerShell."""
    return "powershell" if is_windows() else "sh"


def env_ref(name: str) -> str:
    """How that shell spells a reference to an environment variable."""
    return f"$env:{name}" if is_windows() else f"${name}"


def export_hint(name: str) -> str:
    """How that shell sets one, for a message that tells the user to."""
    return f"$env:{name} = '...'" if is_windows() else f"export {name}=..."


def private_modes_enforced() -> bool:
    """Whether 0600 and 0700 mean anything on this OS. On Windows they do
    not, and a check that insists on them can only ever fail."""
    return not is_windows()


def local_app_data() -> str:
    """`%LOCALAPPDATA%`, the per-user, per-machine directory Windows gives a
    program for things that are not documents."""
    return os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local")


# ------------------------------------------------------------ the interpreter

_PYTHON_RE = re.compile(r"^python(3(\.\d+)?)?$")


def looks_like_python(token: str) -> bool:
    """`python`, `python3`, `python3.12`, with or without a directory in
    front and `.exe` behind: the tokens a solver line starts with."""
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
    """The argv a solver or strategy is run as, made to start on this machine.

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
    """Say once, on stderr, that a solver/strategy line's leading interpreter
    was mapped to the one qdojo itself runs on -- so the swap is never
    silent, and a fighter whose recorded interpreter has moved or vanished
    has something to go on besides an unrelated import error."""
    if head in _noted_swaps:
        return
    _noted_swaps.add(head)
    print(f"qdojo: {head} is not runnable here; running under {to}", file=sys.stderr)


# ------------------------------------------------------- the command line

def split_command(text: str) -> list[str]:
    """A command line typed by a human, as argv.

    POSIX rules everywhere but Windows. There a backslash is a path separator
    and not an escape, so `python C:\\Users\\me\\solver.py` must come out with
    its backslashes intact; the non-POSIX split keeps them and keeps the
    quotes too, so the quotes that group a path with spaces are stripped
    off each token afterwards.
    """
    if not is_windows():
        return shlex.split(text)
    out = []
    for tok in shlex.split(text, posix=False):
        if len(tok) >= 2 and tok[0] == tok[-1] and tok[0] in "\"'":
            tok = tok[1:-1]
        out.append(tok)
    return out


# Characters PowerShell passes to a native command as they are. Everything
# outside this set (a space, a quote, `$`, a backtick, `;`, `,`, `@`, `(`,
# `{`, `#`) is wrapped in single quotes, inside which only a doubled quote
# is special.
_PS_SAFE = re.compile(r"^[A-Za-z0-9_./:\\=+-]+$")


def ps_quote(arg) -> str:
    """One argument, safe to paste into PowerShell."""
    arg = str(arg)
    if arg and _PS_SAFE.match(arg):
        return arg
    return "'" + arg.replace("'", "''") + "'"


def ps_string(text) -> str:
    """One PowerShell string literal, always quoted: the right-hand side of
    an assignment is an expression, so a bare word there is a command."""
    return "'" + str(text).replace("'", "''") + "'"


def quote(arg, shell: str | None = None) -> str:
    """One argument, quoted for `shell` ("sh" or "powershell"; None picks
    this OS's)."""
    shell = shell or shell_name()
    return ps_quote(arg) if shell == "powershell" else shlex.quote(str(arg))


def sibling(source: str, name: str) -> str:
    """`name` next to `source`: `fighters.json` beside a board URL, or
    beside a board file. A URL always splits on `/`; a local path splits the
    way this OS does, which on Windows is on either slash."""
    if source.startswith(("http://", "https://")):
        return source.rsplit("/", 1)[0] + "/" + name
    pathmod = ntpath if is_windows() else os.path
    d = pathmod.dirname(source)
    return pathmod.join(d, name) if d else name


# ----------------------------------------------------------------- the console

def tolerant_stdio() -> None:
    """Never let an unencodable character end a run.

    A Windows console proper takes any character (Python writes it as
    UTF-16), but stdout redirected to a file or a pipe uses the locale code
    page, and cp1252 has no tick mark. `print` would then raise
    UnicodeEncodeError -- a ValueError, which `bot run` catches as a
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


_vt: bool | None = None


def console_escapes_ok() -> bool:
    """Whether the console will interpret escape sequences rather than print
    them. Always on POSIX. A Windows console has to be switched into that
    mode; Windows Terminal and PowerShell do it themselves, a bare cmd.exe
    window may not, so this asks kernel32 once and remembers the answer.
    When the switch fails, term falls back to plain ASCII -- the same thing
    NO_COLOR does."""
    global _vt
    if not is_windows():
        return True
    if _vt is None:
        _vt = _switch_console_to_vt()
    return _vt


def _switch_console_to_vt() -> bool:
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
    except (ImportError, AttributeError):
        return False
    try:
        handle = k32.GetStdHandle(-11)                          # STD_OUTPUT_HANDLE
        mode = ctypes.c_uint32()
        if not k32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False                                        # not a console at all
        if mode.value & 0x0004:                                 # ENABLE_VIRTUAL_TERMINAL_PROCESSING
            return True
        return bool(k32.SetConsoleMode(handle, mode.value | 0x0004))
    except (OSError, ValueError):
        return False
