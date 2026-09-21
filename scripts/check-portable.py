#!/usr/bin/env python3
"""Fail when the fighter side of qdojo reaches for something Windows lacks.

The bot, the rite, the trainer, the local page and the example solvers run
on a stranger's machine, and many of those are Windows (issue #21). Nothing
in this repo's tests runs there, so this keeps the property by reading the
code: every POSIX-only import, call, signal and absolute path in a
fighter-side file must sit under a guard that says which OS it is for -- an
`if` on `sys.platform`, `os.name` or `portable.is_windows()`, or a `try`
whose handler catches what Windows raises (ImportError, AttributeError,
OSError). A docstring may say /tmp; that is prose.

    python scripts/check-portable.py            # the repo (what the tests run)
    python scripts/check-portable.py FILE ...   # only these files

House-side modules may be as POSIX as they like below the top level, but
`qdojo.cli` imports them, so their module-level imports are checked too: an
`import fcntl` at the top of house.py would break `qdojo train` on Windows.
Exit 1 with one line per finding, `path:line: what`, and 0 when clean.
"""
import ast
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKAGE = os.path.join(ROOT, "packages", "qdojo", "src", "qdojo")
EXAMPLES = os.path.join(ROOT, "examples")
HOUSE_ONLY = {"house.py", "spar.py", "lab.py", "model.py", "fees.py", "riddles.py", "qubic_riddles.py"}

POSIX_MODULES = {"fcntl", "termios", "tty", "pty", "pwd", "grp", "resource", "posix", "syslog", "curses",
                 "readline", "crypt"}
POSIX_OS = {"fork", "forkpty", "setsid", "getsid", "setpgid", "getpgid", "setpgrp", "killpg", "getuid", "geteuid",
            "getgid", "getegid", "setuid", "setgid", "getgroups", "mkfifo", "mknod", "chown", "lchown", "chroot",
            "nice", "openpty", "sync", "fchmod", "fchown", "statvfs", "getloadavg", "WNOHANG", "O_NONBLOCK"}
POSIX_SIGNAL = {"SIGKILL", "SIGHUP", "SIGUSR1", "SIGUSR2", "SIGALRM", "SIGCHLD", "SIGPIPE", "SIGQUIT", "SIGSTOP",
                "SIGCONT", "SIGTSTP", "SIGWINCH", "alarm", "setitimer", "pause", "sigwait", "pthread_kill",
                "pthread_sigmask", "siginterrupt"}
POSIX_PATHS = ("/tmp", "/run/", "/bin/", "/usr/", "/etc/", "/dev/", "/var/", "/proc/", "/home/", "/opt/")
SHELL_KEYWORDS = {"shell": "assumes a shell (shell=True)", "preexec_fn": "preexec_fn is POSIX-only"}

# Words in an `if` test that mark the branch as OS-specific on purpose.
GUARD_WORDS = ("sys.platform", "os.name", "is_windows", "private_modes_enforced", "win32", "posix", "WINDOWS")
# Handlers that make a `try` a guard: what Windows raises where POSIX does not.
GUARD_EXCEPTIONS = ("ImportError", "ModuleNotFoundError", "AttributeError", "OSError", "NotImplementedError")


def is_guard(node) -> bool:
    if isinstance(node, (ast.If, ast.IfExp)):
        return any(w in ast.unparse(node.test) for w in GUARD_WORDS)
    if isinstance(node, ast.Try):
        return any(h.type is None or any(e in ast.unparse(h.type) for e in GUARD_EXCEPTIONS)
                   for h in node.handlers)
    return False


def is_docstring(node) -> bool:
    return isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)


def check_node(node, path, top_level_only) -> list:
    """Findings for one node, ignoring where it sits; the walker decides that."""
    out = []
    line = getattr(node, "lineno", 0)
    if isinstance(node, ast.Import):
        for a in node.names:
            if a.name.split(".")[0] in POSIX_MODULES:
                out.append((path, line, f"import {a.name} outside a platform guard"))
    elif isinstance(node, ast.ImportFrom):
        if (node.module or "").split(".")[0] in POSIX_MODULES:
            out.append((path, line, f"from {node.module} import ... outside a platform guard"))
    if top_level_only:
        return out
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        if node.value.id == "os" and node.attr in POSIX_OS:
            out.append((path, line, f"os.{node.attr} outside a platform guard"))
        if node.value.id == "signal" and node.attr in POSIX_SIGNAL:
            out.append((path, line, f"signal.{node.attr} outside a platform guard"))
        if node.value.id == "socket" and node.attr == "AF_UNIX":
            out.append((path, line, "socket.AF_UNIX outside a platform guard"))
    if isinstance(node, ast.Call):
        for kw in node.keywords:
            if kw.arg in SHELL_KEYWORDS and not (isinstance(kw.value, ast.Constant) and kw.value.value is False):
                out.append((path, line, f"{ast.unparse(node.func)}(...) {SHELL_KEYWORDS[kw.arg]}"))
    if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.startswith(POSIX_PATHS):
        out.append((path, line, f"POSIX path {node.value!r} outside a platform guard"))
    return out


def walk(node, path, guarded, top_level_only, out):
    if is_docstring(node):
        return                                  # prose, not code
    if top_level_only and not isinstance(node, (ast.Module, ast.Import, ast.ImportFrom)):
        if isinstance(node, (ast.If, ast.Try)):
            guarded = guarded or is_guard(node)
            for child in ast.iter_child_nodes(node):
                walk(child, path, guarded, top_level_only, out)
        return
    if not guarded:
        out.extend(check_node(node, path, top_level_only))
    guarded = guarded or is_guard(node)
    for child in ast.iter_child_nodes(node):
        walk(child, path, guarded, top_level_only, out)


def check_file(path, top_level_only=False) -> list:
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=path)
    out = []
    walk(tree, path, False, top_level_only, out)
    return out


def repo_files():
    """(path, top_level_only) for every file the fighter side is made of."""
    for base in (PACKAGE, EXAMPLES):
        for root, _dirs, names in os.walk(base):
            for name in sorted(names):
                if name.endswith(".py"):
                    yield os.path.join(root, name), name in HOUSE_ONLY


def main(argv) -> int:
    files = [(p, False) for p in argv] if argv else list(repo_files())
    findings = []
    for path, top_level_only in files:
        findings.extend(check_file(path, top_level_only))
    for path, line, what in findings:
        print(f"{os.path.relpath(path, ROOT) if path.startswith(ROOT) else path}:{line}: {what}")
    n = len(files)
    if findings:
        print(f"check-portable: {len(findings)} finding(s) in {n} file(s)")
        return 1
    print(f"check-portable: {n} file(s) clean")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
