"""Seed confs that live in the runtime directory, and what to do about them.

`$XDG_RUNTIME_DIR/qdojo` (`/run/user/<uid>/qdojo`) is tmpfs: a conf written
there lives until reboot, not until the process that used it exits. Nothing in
qdojo writes a conf there -- `bot init` writes `~/.qdojo/bot/bot.conf` and a
run only reads the conf it is given -- but launch scripts and ad-hoc runs do,
and after a session the directory is full of keys at rest.

Two things here, kept deliberately apart:

  * `warn_leftovers` REPORTS what is in the directory and deletes nothing. It
    exists because "there are none" was once concluded from `ls | head`,
    which showed five files of twenty-six. Most of what it lists is the
    sparring cohort's keys, which the operator keeps (docs/operations.md).
  * `ephemeral` SHREDS one conf when a run exits, on every exit path, and
    only the conf it was handed. A run opts in per conf, by path, with
    `--ephemeral-conf`; a conf that arrived any other way is never touched.
"""
import contextlib
import os
import signal
import stat
import sys
import time


def runtime_dir() -> str:
    """`$XDG_RUNTIME_DIR/qdojo`, or `/run/user/<uid>/qdojo` when the variable
    is unset (a cron job, a systemd unit without a session)."""
    base = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    return os.path.join(base, "qdojo")


def leftover_confs(directory: str | None = None, exclude: str | None = None,
                   now: float | None = None) -> list[dict]:
    """Every regular `*.conf` in the runtime directory, oldest first.

    Each entry is {"name", "path", "age"} with the age in seconds since the
    file was last written. The directory is enumerated in full with scandir,
    never through a pipe that can truncate. A directory that does not exist
    is an empty list, not an error, and so is one that cannot be read: this
    runs at the start of every bot and house run, and a warning must never be
    the reason a run did not start. `exclude` is the conf the run itself was
    given, which is in use rather than left over. Nothing here deletes.
    """
    directory = directory or runtime_dir()
    skip = os.path.realpath(exclude) if exclude else None
    now = time.time() if now is None else now
    try:
        entries = list(os.scandir(directory))
    except OSError:
        return []
    out = []
    for e in entries:
        if not e.name.endswith(".conf"):
            continue
        try:
            st = e.stat(follow_symlinks=False)
        except OSError:
            continue
        if not stat.S_ISREG(st.st_mode):
            continue
        if skip and os.path.realpath(e.path) == skip:
            continue
        out.append({"name": e.name, "path": e.path, "age": max(0.0, now - st.st_mtime)})
    out.sort(key=lambda x: (-x["age"], x["name"]))
    return out


def format_age(seconds: float) -> str:
    """4d 20h, 3h 12m, 42m, 10s: enough to tell last week from just now."""
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m"
    if s < 86400:
        return f"{s // 3600}h {(s % 3600) // 60}m"
    return f"{s // 86400}d {(s % 86400) // 3600}h"


def warn_leftovers(directory: str | None = None, exclude: str | None = None, out=None) -> list[dict]:
    """The startup check: list what is in the runtime directory, on stderr,
    and delete nothing. Silent when the directory does not exist or holds no
    conf. Returns what it found so a caller can act on it if it wants to."""
    directory = directory or runtime_dir()
    found = leftover_confs(directory, exclude=exclude)
    if not found:
        return found
    out = out or sys.stderr
    n = len(found)
    print(f"warning: {n} seed conf{'s' if n != 1 else ''} in {directory} from earlier runs "
          f"(nothing is deleted; see docs/operations.md):", file=out)
    width = max(len(x["name"]) for x in found)
    for x in found:
        print(f"  {x['name']:<{width}}  {format_age(x['age'])}", file=out)
    out.flush()
    return found


def shred(path: str, passes: int = 3) -> bool:
    """Overwrite `path` with zeros `passes` times, fsync after each pass, then
    unlink it. Returns whether there was a file to shred.

    On tmpfs the overwrite is belt-and-braces: the pages go back to the kernel
    on unlink and there is no disk holding old blocks, so the UNLINK is what
    matters -- without it the file lives until reboot, which is the whole
    problem. On a real filesystem the overwrite is not a guarantee either
    (a journal, copy-on-write or SSD wear levelling can keep the old bytes),
    which is one more reason a seed conf belongs on tmpfs in the first place.
    The unlink runs even when the overwrite fails, for the same reason.

    A symlink is unlinked, not followed: the caller named the link, not
    whatever it points at.
    """
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return False
    if stat.S_ISLNK(st.st_mode):
        os.unlink(path)
        return True
    try:
        with open(path, "rb+") as f:
            for _ in range(passes):
                f.seek(0)
                f.write(b"\0" * st.st_size)
                f.flush()
                os.fsync(f.fileno())
    finally:
        os.unlink(path)
    return True


@contextlib.contextmanager
def ephemeral(path: str | None):
    """Run a block with `path` as a throwaway conf: it is shredded when the
    block exits, however it exits -- a normal return, an exception, ctrl-c, or
    SIGTERM, which is turned into SystemExit here so the finally still runs.
    SIGKILL cannot be caught; the leftover check is for that. `None` means
    there is no throwaway conf, and the block runs untouched.

    The handler is installed only for the duration of the block and the one
    that was there before is put back. A second SIGTERM arriving during the
    shred is ignored rather than allowed to interrupt it.
    """
    if path is None:
        yield None
        return

    def on_term(signum, frame):
        raise SystemExit(128 + signum)

    prev = None
    try:
        prev = signal.signal(signal.SIGTERM, on_term)
    except ValueError:
        pass    # not the main thread: no handler, but every other exit path is still covered
    try:
        yield path
    finally:
        if prev is not None:
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
        try:
            shred(path)
        finally:
            if prev is not None:
                signal.signal(signal.SIGTERM, prev)
