"""The rendering kit. Two things here are not cosmetic: nothing may be wider
than the terminal, and nothing may read stdin when there is no terminal."""
import builtins
import os
import shutil

import pytest

from qdojo import term


@pytest.fixture(autouse=True)
def plain_env(monkeypatch):
    """Every test starts from auto-detection with no colour hints set."""
    for v in ("NO_COLOR", "FORCE_COLOR", "TERM"):
        monkeypatch.delenv(v, raising=False)
    term.set_enabled(None)
    yield
    term.set_enabled(None)


class FakeTTY:
    def __init__(self, tty=True):
        self.tty = tty

    def isatty(self):
        return self.tty


def cols(monkeypatch, n):
    monkeypatch.setattr(shutil, "get_terminal_size", lambda fallback=(80, 24): os.terminal_size((n, 24)))


def rendered(monkeypatch=None):
    """Everything the kit can draw, as one list of lines."""
    out = [term.banner(), term.rule(), term.rule("A TITLE THAT IS RATHER LONG FOR A NARROW TERMINAL"),
           term.box(["short", "x" * 300, term.kv("label", "value")], title="A BOX TITLE THAT IS ALSO LONG"),
           term.box([]), term.kv("k", "v"), term.qu(1234567), term.qu(None), term.belt("orange")]
    return [l for chunk in out for l in str(chunk).splitlines()]


# ------------------------------------------------------------------ enabled

def test_disabled_emits_no_escape_codes(monkeypatch, capsys):
    term.set_enabled(False)
    for line in rendered():
        assert "\x1b" not in line
    term.step(1, 6, "a step")
    term.ok("ok", "d")
    term.fail("fail", "d")
    term.warn("warn", "d")
    with term.spinner("spinning"):
        pass
    out = capsys.readouterr().out
    assert "\x1b" not in out and "\r" not in out
    assert "OK" in out and "XX" in out          # the marks degrade, they do not vanish
    assert "✔" not in out and "✘" not in out


def test_enabled_emits_escape_codes():
    term.set_enabled(True)
    assert "\x1b[" in term.c("x", "bold")
    assert "✔" in term.MARKS[True]["ok"]


def test_no_color_any_value_disables(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "")           # "set to any value", including empty
    assert term.enabled(FakeTTY()) is False
    monkeypatch.setenv("NO_COLOR", "1")
    assert term.enabled(FakeTTY()) is False


def test_dumb_term_disables(monkeypatch):
    monkeypatch.setenv("TERM", "dumb")
    assert term.enabled(FakeTTY()) is False


def test_not_a_tty_disables():
    assert term.enabled(FakeTTY(tty=False)) is False
    assert term.enabled(FakeTTY(tty=True)) is True


def test_force_color_overrides_every_disable(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setenv("TERM", "dumb")
    monkeypatch.setenv("FORCE_COLOR", "1")
    assert term.enabled(FakeTTY(tty=False)) is True


def test_set_enabled_overrides_and_none_restores(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    term.set_enabled(True)
    assert term.enabled(FakeTTY(tty=False)) is True
    term.set_enabled(None)
    assert term.enabled(FakeTTY()) is False


# -------------------------------------------------------------------- width

@pytest.mark.parametrize("n", [40, 200])
@pytest.mark.parametrize("styled", [True, False])
def test_nothing_rendered_exceeds_the_width(monkeypatch, n, styled):
    cols(monkeypatch, n)
    term.set_enabled(styled)
    w = term.width()
    assert w == min(n, term.MAX_WIDTH)
    for line in rendered():
        assert term.vis(line) <= w, repr(line)


def test_width_is_capped_at_100(monkeypatch):
    cols(monkeypatch, 1000)
    assert term.width() == 100


def test_narrow_banner_at_60_columns(monkeypatch):
    term.set_enabled(True)
    cols(monkeypatch, 60)
    narrow = term.banner()
    assert "█" not in narrow and "Q D O J O" in narrow      # the compact boxed form
    assert term.TAGLINE in narrow
    cols(monkeypatch, 72)
    wide = term.banner()
    assert "█" in wide and term.TAGLINE in wide             # the block art earns its width
    assert max(term.vis(l) for l in wide.splitlines()) <= 72


def test_plain_banner_when_disabled(monkeypatch):
    term.set_enabled(False)
    cols(monkeypatch, 100)
    b = term.banner()
    assert "\x1b" not in b and "█" not in b and term.TAGLINE in b


def test_box_borders_degrade_to_ascii():
    term.set_enabled(False)
    b = term.box(["x"], title="T")
    assert "┌" not in b and b.startswith("+")
    term.set_enabled(True)
    assert term.box(["x"], title="T").startswith("┌")


def test_fit_and_pad_count_visible_columns():
    term.set_enabled(True)
    coloured = term.c("abcdef", "bold")
    assert term.vis(coloured) == 6
    assert term.vis(term.pad(coloured, 10)) == 10
    assert term.vis(term.fit(coloured, 4)) == 4


# --------------------------------------------------------------------- ask

def no_stdin(monkeypatch):
    """No terminal, and reading one is a test failure rather than a hang."""
    monkeypatch.setattr(term, "stdin_is_tty", lambda: False)

    def boom(*a, **k):
        raise AssertionError("input() was called without a TTY — this is the CI hang")
    monkeypatch.setattr(term, "_input", boom)
    monkeypatch.setattr(builtins, "input", boom)


def test_ask_returns_the_default_without_a_tty_and_never_reads_stdin(monkeypatch):
    no_stdin(monkeypatch)
    assert term.ask("name", default="RYUBOT") == "RYUBOT"
    assert term.ask("name", default="") == ""                 # an empty default is still an answer


def test_ask_without_a_default_and_no_input_raises(monkeypatch):
    no_stdin(monkeypatch)
    with pytest.raises(term.TermError):
        term.ask("name")
    monkeypatch.setattr(term, "stdin_is_tty", lambda: True)   # a TTY exists, but no_input forbids asking
    with pytest.raises(term.TermError):
        term.ask("name", no_input=True)


def test_ask_no_input_flag_beats_a_live_tty(monkeypatch):
    monkeypatch.setattr(term, "stdin_is_tty", lambda: True)
    monkeypatch.setattr(term, "_input", lambda p: (_ for _ in ()).throw(AssertionError("asked anyway")))
    assert term.ask("name", default="D", no_input=True) == "D"


def test_ask_validates_and_re_asks(monkeypatch, capsys):
    monkeypatch.setattr(term, "stdin_is_tty", lambda: True)
    answers = iter(["", "toolong", "ok"])

    def fake(prompt):
        return next(answers)
    monkeypatch.setattr(term, "_input", fake)

    def validate(v):
        if len(v) > 4:
            raise ValueError("at most 4 characters")
        return v
    assert term.ask("name", validate=validate) == "ok"
    assert "at most 4 characters" in capsys.readouterr().out


def test_ask_rejects_an_invalid_default_without_a_tty(monkeypatch):
    no_stdin(monkeypatch)
    with pytest.raises(term.TermError):
        term.ask("name", default="much too long", validate=lambda v: (_ for _ in ()).throw(ValueError("no")))


# -------------------------------------------------------------------- menu

OPTIONS = [("none — no LLM at all", "free"), ("openrouter — one key", "paid"), ("local — Ollama", "free")]


def test_menu_returns_the_default_without_a_tty(monkeypatch):
    no_stdin(monkeypatch)
    assert term.menu("provider", OPTIONS, default=0) == 0
    assert term.menu("provider", OPTIONS, default=2) == 2
    with pytest.raises(term.TermError):
        term.menu("provider", OPTIONS, default=None)


def test_menu_accepts_a_number_and_a_key_prefix(monkeypatch):
    monkeypatch.setattr(term, "stdin_is_tty", lambda: True)
    for answer, want in [("2", 1), ("3", 2), ("local", 2), ("open", 1), ("NONE", 0), ("l", 2)]:
        monkeypatch.setattr(term, "_input", lambda p, a=answer: a)
        assert term.menu("provider", OPTIONS, default=0) == want, answer


def test_menu_re_asks_on_nonsense_then_takes_the_answer(monkeypatch, capsys):
    monkeypatch.setattr(term, "stdin_is_tty", lambda: True)
    answers = iter(["9", "zebra", "2"])
    monkeypatch.setattr(term, "_input", lambda p: next(answers))
    assert term.menu("provider", OPTIONS, default=0) == 1
    assert "not one of the 3 options" in capsys.readouterr().out


def test_menu_empty_answer_takes_the_default(monkeypatch):
    monkeypatch.setattr(term, "stdin_is_tty", lambda: True)
    monkeypatch.setattr(term, "_input", lambda p: "")
    assert term.menu("provider", OPTIONS, default=1) == 1


def test_parse_choice_is_pure():
    assert term.parse_choice("1", OPTIONS) == 0
    assert term.parse_choice("0", OPTIONS) is None
    assert term.parse_choice("4", OPTIONS) is None
    assert term.parse_choice("", OPTIONS) is None
    assert term.parse_choice("  local ", OPTIONS) == 2


# ----------------------------------------------------------------- spinner

def test_spinner_prints_one_static_line_when_disabled(capsys):
    term.set_enabled(False)
    with term.spinner("probing"):
        pass
    out = capsys.readouterr().out
    assert out.count("\n") == 1 and "probing" in out and "\x1b" not in out


def test_qu_groups_and_never_invents_a_zero():
    term.set_enabled(False)
    assert term.qu(10000) == "10,000 QU"
    assert term.qu(None) == "unknown"
