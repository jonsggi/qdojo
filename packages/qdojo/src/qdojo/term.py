"""The dojo's terminal: colour, boxes, steps, prompts and a spinner.

Hand-rolled on purpose. The package has no third-party dependencies and must
not grow one: a fighter bot has to run on a stranger's machine with nothing
pulled in. Everything here degrades to plain ASCII with zero escape codes.

Two rules this module exists to enforce:

- **Nothing rendered is wider than `width()`** (the terminal, capped at 100).
  A card that wraps is a card nobody reads.
- **`ask` and `menu` never call `input()` when stdin is not a TTY**, or when
  `no_input` is set. They return the default instead, and raise `TermError`
  when there is no default. A wizard that blocks in CI blocks forever.
"""
import contextlib
import os
import re
import shutil
import sys
import threading

from . import portable

MAX_WIDTH = 100
MIN_WIDTH = 24

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

CODES = {
    "reset": "0", "bold": "1", "dim": "2", "italic": "3", "under": "4", "invert": "7",
    "black": "30", "red": "31", "green": "32", "yellow": "33", "blue": "34",
    "magenta": "35", "cyan": "36", "white": "37", "grey": "90", "gray": "90",
    "bred": "91", "bgreen": "92", "byellow": "93", "bblue": "94", "bmagenta": "95", "bcyan": "96",
    # the belt vocabulary (belts.BELTS): white, yellow, orange, green, blue
    "orange": "38;5;208",
}
BELT_STYLE = {"white": ("white", "bold"), "yellow": ("byellow",), "orange": ("orange",),
              "green": ("bgreen",), "blue": ("bblue",)}

SPIN = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
MARKS = {True: {"ok": "✔", "fail": "✘", "warn": "▲", "step": "▸", "dot": "·"},
         False: {"ok": "OK", "fail": "XX", "warn": "!!", "step": ">", "dot": "-"}}
BOX = {True: "┌┐└┘─│├┤", False: "++++-|++"}

_forced: bool | None = None


class TermError(Exception):
    pass


# ---------------------------------------------------------------- capability

def set_enabled(v: bool | None) -> None:
    """Force styling on (True) or off (False); None restores auto-detection."""
    global _forced
    _forced = v


def enabled(stream=None) -> bool:
    """True when it is safe to emit escape codes.

    Off when NO_COLOR is set to any value, when TERM is "dumb", or when the
    stream is not a TTY. FORCE_COLOR=1 overrides all three. `stream` defaults
    to the *current* sys.stdout (not the one bound at import) so that a test
    harness capturing stdout is honoured. On Windows the console must also
    agree to interpret escapes (portable.console_escapes_ok); a legacy
    cmd.exe window that will not is treated like NO_COLOR.
    """
    if _forced is not None:
        return _forced
    if os.environ.get("FORCE_COLOR") == "1":
        return True
    if os.environ.get("NO_COLOR") is not None:
        return False
    if os.environ.get("TERM") == "dumb":
        return False
    stream = sys.stdout if stream is None else stream
    try:
        if not stream.isatty():
            return False
    except Exception:
        return False
    return portable.console_escapes_ok()


def stdin_is_tty() -> bool:
    """Whether a human could actually answer a prompt. Monkeypatch me in tests."""
    try:
        return bool(sys.stdin.isatty())
    except Exception:
        return False


def width() -> int:
    """The usable width: the terminal's columns, capped at 100."""
    try:
        cols = shutil.get_terminal_size((80, 24)).columns
    except Exception:
        cols = 80
    return max(MIN_WIDTH, min(int(cols), MAX_WIDTH))


def mark(name: str) -> str:
    return MARKS[enabled()][name]


# ------------------------------------------------------------------ styling

def c(text, *styles) -> str:
    """`text` wrapped in `styles`, or returned untouched when styling is off.

    Styles are names from CODES, or a belt name (white/yellow/orange/green/blue)
    which expands to that belt's look.
    """
    text = str(text)
    if not styles or not enabled():
        return text
    parts = [CODES[s] for s in styles if s in CODES]
    if not parts:
        return text
    return "\x1b[" + ";".join(parts) + "m" + text + "\x1b[0m"


def belt(name: str) -> str:
    """A belt name in its own colour."""
    return c(name, *BELT_STYLE.get(name, ("white",)))


def vis(s: str) -> int:
    """Visible length: escape codes take no columns."""
    return len(ANSI_RE.sub("", str(s)))


def fit(s, n: int) -> str:
    """`s` cut to at most n visible columns. Styling is dropped when cutting,
    because half an escape sequence is worse than no colour."""
    s = str(s)
    if vis(s) <= n:
        return s
    plain = ANSI_RE.sub("", s)
    if n <= 1:
        return plain[:max(0, n)]
    return plain[: n - 1] + ("…" if enabled() else ".")


def pad(s, n: int) -> str:
    """`s` padded with spaces to exactly n visible columns (cut if too long)."""
    s = fit(s, n)
    return s + " " * (n - vis(s))


# ------------------------------------------------------------------ drawing

def rule(title: str = "") -> str:
    """A full-width horizontal rule, optionally with a title set into it."""
    w = width()
    h = BOX[enabled()][4]
    if not title:
        return c(h * w, "dim")
    t = fit(title, max(0, w - 8))
    tail = h * max(0, w - (2 + 1 + vis(t) + 1))
    return c(h * 2, "dim") + " " + c(t, "bold") + " " + c(tail, "dim")


def box(lines, title: str = "") -> str:
    """A bordered box. Never wider than `width()`; content longer than the box
    is cut, not wrapped — put anything that must survive intact outside it
    (a 60-character identity, for one)."""
    tl, tr, bl, br, h, v, *_ = BOX[enabled()]
    lines = [str(x) for x in (lines if not isinstance(lines, str) else lines.splitlines())]
    w = width()
    inner = max([vis(x) for x in lines] + [vis(title) + 2, 8])
    inner = min(inner, w - 4)
    top = tl + h + (c(" " + fit(title, inner - 2) + " ", "bold") if title else h * 2)
    top += h * max(0, (inner + 2) - vis(top) + 1) + tr
    out = [top]
    for line in lines:
        out.append(v + " " + pad(line, inner) + " " + v)
    out.append(bl + h * (inner + 2) + br)
    return "\n".join(out)


TAGLINE = "THE DOJO IS OPEN. BOW IN."

_ART = [
    " █████  ██████   █████  ██  ██  █████ ",
    "██   ██ ██   ██ ██   ██     ██ ██   ██",
    "██ █ ██ ██   ██ ██   ██     ██ ██   ██",
    "██  ███ ██   ██ ██   ██ ██  ██ ██   ██",
    " ██████ ██████   █████   ████   █████ ",
]


def banner() -> str:
    """The attract screen. Wide block art at >=72 columns, a compact box below
    that, and a plain ASCII form when styling is off."""
    w = width()
    if not enabled():
        bar = "=" * min(w, 40)
        n = min(w, 40)
        return "\n".join([bar, "Q D O J O".center(n).rstrip(), TAGLINE.center(n).rstrip(), bar])
    if w >= 72:
        art = "\n".join(c(line.center(w).rstrip(), "bcyan") for line in _ART)
        return art + "\n" + c(TAGLINE.center(w).rstrip(), "byellow", "bold")
    return box([c("Q D O J O", "bcyan", "bold"), c(TAGLINE, "byellow")])


# ------------------------------------------------------------------ printing

def step(n: int, total: int, text: str) -> None:
    """A stage header. Printing this is not the work; verifying is."""
    tag = f"[{n}/{total}]"
    print()
    print(c(tag, "bcyan", "bold") + " " + c(mark("step"), "dim") + " " + c(fit(text, width() - len(tag) - 4), "bold"))


def _line(sym: str, style: str, label: str, detail: str) -> None:
    head = "  " + c(sym, style) + " "
    body = c(label, "bold") if label else ""
    if detail:
        body = (body + "  " if body else "") + c(detail, "dim")
    print(head + fit(body, max(4, width() - vis(head))))


def ok(label: str = "", detail: str = "") -> None:
    _line(mark("ok"), "bgreen", label, detail)


def fail(label: str, detail: str = "") -> None:
    _line(mark("fail"), "bred", label, detail)


def warn(label: str, detail: str = "") -> None:
    _line(mark("warn"), "byellow", label, detail)


def info(label: str = "", detail: str = "") -> None:
    _line(mark("dot"), "dim", label, detail)


def kv(label: str, value, w: int = 10) -> str:
    """One `label   value` row for a card. Returns the string; does not print."""
    return c(pad(label, w), "dim") + " " + str(value)


def qu(n) -> str:
    """An amount in QU, grouped. An unknown is an unknown, never a zero."""
    if n is None:
        return c("unknown", "byellow") if enabled() else "unknown"
    return f"{int(n):,} QU"


# ------------------------------------------------------------------- asking

def _input(prompt: str) -> str:
    """The only place this module reads a human. Monkeypatch me in tests."""
    return input(prompt)


def ask(prompt: str, default=None, validate=None, no_input: bool = False) -> str:
    """Ask, or return `default` when nobody can answer.

    `validate(value)` returns the cleaned value and raises ValueError (or
    TermError) with a human message to reject it. With no TTY or `no_input`
    the default is returned — after validation — and TermError is raised when
    there is no default.
    """
    def check(v):
        if validate is None:
            return v
        return validate(v)

    if no_input or not stdin_is_tty():
        if default is None:
            raise TermError(f"{prompt}: no answer possible without a terminal; pass it explicitly")
        try:
            return str(check(str(default)))
        except (ValueError, TermError) as e:
            raise TermError(f"{prompt}: default {default!r} is not valid: {e}")
    hint = f" [{default}]" if default not in (None, "") else ""
    while True:
        try:
            raw = _input(c("  " + prompt + hint + ": ", "bcyan")).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            if default is None:
                raise TermError(f"{prompt}: cancelled")
            raw = ""
        if not raw and default is not None:
            raw = str(default)
        if not raw:
            fail("an answer is required")
            continue
        try:
            return str(check(raw))
        except (ValueError, TermError) as e:
            fail(str(e))


def _options(options) -> list[tuple[str, str]]:
    out = []
    for o in options:
        if isinstance(o, (tuple, list)):
            out.append((str(o[0]), str(o[1]) if len(o) > 1 else ""))
        elif isinstance(o, dict):
            out.append((str(o.get("label", "")), str(o.get("hint", ""))))
        else:
            out.append((str(o), ""))
    return out


def parse_choice(entry: str, options) -> int | None:
    """A menu answer as an index: a 1-based number, or a case-insensitive
    prefix of an option's label (or of its first word). None if no match."""
    opts = _options(options)
    entry = (entry or "").strip()
    if not entry:
        return None
    if entry.isdigit():
        i = int(entry) - 1
        return i if 0 <= i < len(opts) else None
    low = entry.lower()
    for i, (label, _) in enumerate(opts):
        if label.lower().startswith(low) or label.lower().split(" ")[0].startswith(low):
            return i
    return None


def menu(title: str, options, default: int = 0, no_input: bool = False) -> int:
    """Print a numbered menu and return the chosen index.

    Never reads stdin without a TTY (or with `no_input`): the default index is
    returned instead, and TermError is raised when `default` is None.
    """
    opts = _options(options)
    if not opts:
        raise TermError("a menu needs at least one option")
    if no_input or not stdin_is_tty():
        if default is None:
            raise TermError(f"{title}: no choice possible without a terminal; pass it explicitly")
        if not 0 <= default < len(opts):
            raise TermError(f"{title}: default {default} is not one of {len(opts)} options")
        return default
    print("  " + c(title, "bold"))
    for i, (label, hint) in enumerate(opts):
        head = f"    {i + 1}) "
        star = c(" (default)", "dim") if i == default else ""
        print(head + c(fit(label, max(8, width() - len(head) - 10)), "bcyan") + star)
        if hint:
            print("       " + c(fit(hint, max(8, width() - 8)), "dim"))
    while True:
        try:
            raw = _input(c(f"  choose 1-{len(opts)}" + (f" [{default + 1}]" if default is not None else "") + ": ",
                           "bcyan")).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            if default is None:
                raise TermError(f"{title}: cancelled")
            return default
        if not raw and default is not None:
            return default
        i = parse_choice(raw, opts)
        if i is not None:
            return i
        fail(f"not one of the {len(opts)} options", raw[:40])


# ------------------------------------------------------------------ spinner

@contextlib.contextmanager
def spinner(text: str):
    """A spinner while something slow happens. One static line when styling is
    off or stdout is not a TTY — no escape codes, no carriage returns."""
    if not enabled() or not (hasattr(sys.stdout, "isatty") and sys.stdout.isatty()):
        print("  " + mark("dot") + " " + fit(text, width() - 4), flush=True)
        yield
        return
    stop = threading.Event()
    w = width()

    def spin():
        i = 0
        while not stop.is_set():
            sys.stdout.write("\r  " + c(SPIN[i % len(SPIN)], "bcyan") + " " + fit(text, w - 5))
            sys.stdout.flush()
            i += 1
            stop.wait(0.09)

    t = threading.Thread(target=spin, daemon=True)
    t.start()
    try:
        yield
    finally:
        stop.set()
        t.join(timeout=1.0)
        sys.stdout.write("\r" + " " * w + "\r")
        sys.stdout.flush()
