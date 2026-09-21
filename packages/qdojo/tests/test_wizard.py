"""The ceremony. The load-bearing tests here are the two that cost money:
a key must never reach disk, and nothing may block when nobody can answer."""
import dataclasses
import json
import os
import shlex
import stat
import sys
import textwrap

import pytest

from qdojo import nodes, onboard, term, wizard


@pytest.fixture(autouse=True)
def plain(monkeypatch):
    for v in ("NO_COLOR", "FORCE_COLOR", "TERM"):
        monkeypatch.delenv(v, raising=False)
    term.set_enabled(False)          # assertions read plain text
    yield
    term.set_enabled(None)


def fake_cli(tmp_path):
    """A qubic-cli that answers the four calls the wizard makes."""
    p = tmp_path / "qubic-cli"
    p.write_text("#!" + sys.executable + "\n" + textwrap.dedent("""
        import sys
        a = sys.argv[1:]
        if '-showkeys' in a:
            conf = a[a.index('-conf') + 1]
            seed = [l for l in open(conf) if l.startswith('seed=')][0][5:].strip()
            print('Seed: ' + seed)                      # the real tool prints secrets too
            print('Identity: ' + seed[:1].upper() * 60)
        elif '-getbalance' in a:
            print('Identity: ' + a[a.index('-getbalance') + 1])
            print('Balance: 5000')
            print('Tick: 1000')
        elif '-getcurrenttick' in a:
            print('Tick: 1000'); print('Epoch: 42')
        else:
            print('Qubic CLI usage: -nodeip <IP> -getbalance ...')
    """))
    os.chmod(p, 0o755)
    return str(p)


class FakeChain:
    """Stands in for NativeChain: the wizard only reads a balance and a tick."""

    def __init__(self, ip, port=21841, **kw):
        self.ip, self.identity = ip, kw.get("identity", "")

    def current_tick(self):
        return 1000

    def balance(self, identity):
        return 5000


@pytest.fixture
def dojo(tmp_path, monkeypatch):
    """A throwaway state dir, a fake signer, and no network.

    The signer itself is no longer faked -- qdojo derives and signs in
    process, so there is nothing to stub. What is stubbed is the network:
    the prober and the chain.
    """
    monkeypatch.setattr(nodes, "native_probe", lambda timeout=6.0: (lambda ip: (1000, [])))
    monkeypatch.setattr(wizard, "NativeChain", FakeChain)
    return {"cli": fake_cli(tmp_path), "state": str(tmp_path / "state"), "tmp": tmp_path}


def py(code):
    return [sys.executable, "-c", code]


def files_under(d):
    for root, _, names in os.walk(d):
        for n in names:
            yield os.path.join(root, n)


# --------------------------------------------------- qdojo never stores a key

def test_env_flag_refuses_a_key_by_name_and_nothing_lands_on_disk(dojo):
    with pytest.raises(wizard.WizardError) as e:
        wizard.init(cli=dojo["cli"], state=dojo["state"], name="RYUBOT", provider="none",
                    env=["OPENROUTER_API_KEY=sk-live-xxx"], yes=True)
    assert "OPENROUTER_API_KEY" in str(e.value)            # it names the offending variable
    assert os.path.isdir(dojo["state"])                    # the seed step had already run
    for path in files_under(dojo["state"]):
        assert "sk-live-xxx" not in open(path, "rb").read().decode("utf-8", "replace"), path


def test_check_no_secrets_names_the_variable():
    for name in ("API_KEY", "openrouter_token", "MY_SECRET", "db_password", "PASSWD", "CREDENTIALS"):
        with pytest.raises(wizard.WizardError) as e:
            wizard.check_no_secrets({name: "x"})
        assert name in str(e.value)
    wizard.check_no_secrets({"PI_MODEL": "deepseek/deepseek-v4-flash", "OPENAI_BASE_URL": "http://x/v1"})


def test_check_no_secrets_catches_a_key_shape_under_an_innocent_name():
    with pytest.raises(wizard.WizardError) as e:
        wizard.check_no_secrets({"MODEL": "sk-live-abcdefghijklmnop"})
    assert "MODEL" in str(e.value)


def test_parse_env_wants_name_equals_value():
    assert wizard.parse_env(["A=1", "B=x=y"]) == {"A": "1", "B": "x=y"}
    with pytest.raises(wizard.WizardError):
        wizard.parse_env(["nope"])


def test_no_flag_anywhere_accepts_a_key_value():
    """The options object is the whole surface: it carries the NAME of the
    place a key lives, never a key."""
    names = {f.name for f in dataclasses.fields(wizard.Opts)}
    assert "key_env" in names
    assert not [n for n in names if wizard.SECRET_RE.search(n) and n != "key_env"]


# ------------------------------------------------------------------ profile

def test_profile_key_set_is_exactly_the_documented_one(dojo):
    prof = wizard.init(cli=dojo["cli"], state=dojo["state"], name="RYUBOT", provider="none", yes=True)
    assert set(prof) == set(wizard.PROFILE_KEYS)
    assert set(json.load(open(onboard.profile_path(dojo["state"])))) == set(wizard.PROFILE_KEYS)
    assert set(wizard.load_profile(dojo["state"])) == set(wizard.PROFILE_KEYS)


def test_an_old_four_key_profile_still_loads(tmp_path):
    state = str(tmp_path / "old")
    onboard.save_profile(state, {"conf": "/x/bot.conf", "identity": "Q" * 60, "name": "OLD", "cli": "qubic-cli"})
    p = wizard.load_profile(state)
    assert set(p) == set(wizard.PROFILE_KEYS)
    assert p["name"] == "OLD" and p["provider"] == "" and p["solver"] == [] and p["solver_env"] == {}
    assert wizard.run_command(p, "http://b")[:3] == ["qdojo", "bot", "--state"]     # still usable


# ---------------------------------------------------------------- the rite

def test_provider_none_succeeds_even_when_pi_is_missing(dojo, monkeypatch, capsys):
    monkeypatch.setattr(wizard, "find_pi", lambda explicit=None: (_ for _ in ()).throw(
        wizard.WizardError("pi not found")))
    prof = wizard.init(cli=dojo["cli"], state=dojo["state"], name="RYUBOT", provider="none")
    out = capsys.readouterr().out
    assert prof["provider"] == "none" and prof["key_source"] == "none"
    assert prof["solver_env"] == {} and prof["model"] == ""
    assert any(x in " ".join(prof["solver"]) for x in ("bare.py", "echo.py"))
    assert "the test riddle is solved" in out                  # it really solved 142
    assert prof["identity"] in out and len(prof["identity"]) == 60


def test_the_seed_conf_is_0600(dojo):
    prof = wizard.init(cli=dojo["cli"], state=dojo["state"], provider="none", yes=True)
    assert stat.S_IMODE(os.stat(prof["conf"]).st_mode) == 0o600


def test_a_second_init_reports_the_existing_seed_and_leaves_it_byte_identical(dojo, capsys):
    prof = wizard.init(cli=dojo["cli"], state=dojo["state"], name="RYUBOT", provider="none", yes=True)
    before = open(prof["conf"], "rb").read()
    capsys.readouterr()
    again = wizard.init(cli=dojo["cli"], state=dojo["state"], name="RYUBOT", provider="none", yes=True)
    assert "existing seed, untouched" in capsys.readouterr().out
    assert open(prof["conf"], "rb").read() == before
    assert again["identity"] == prof["identity"]


def test_openrouter_path_writes_the_model_and_never_a_key(dojo, monkeypatch):
    """A provider now picks the PROMPT-DRIVEN solver, not pi.py.

    pi is almost never installed on a stranger's machine -- _pi_is_missing
    existed only to apologise for that -- and the prompt-driven solver is
    stdlib urllib, so the default path works on a bare checkout.
    """
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-live-should-never-be-written")
    prof = wizard.init(cli=dojo["cli"], state=dojo["state"], name="RYUBOT", provider="openrouter",
                       model="deepseek/deepseek-v4-flash", yes=True, skip_probe=True)
    assert prof["solver_env"]["OPENAI_MODEL"] == "deepseek/deepseek-v4-flash"
    assert "prompted.py" in " ".join(prof["solver"])
    assert prof["solver_env"]["QDOJO_PROMPTS"].endswith("prompts")
    # The key stays in the user's shell; the profile records the NAME of the
    # place and nothing else -- which is more honest than "pi", because it names
    # the exact variable.
    assert prof["key_source"] == "env:OPENROUTER_API_KEY"
    for path in files_under(dojo["state"]):
        assert "sk-live" not in open(path, "rb").read().decode("utf-8", "replace"), path


def test_local_path_writes_base_url_and_model(dojo, monkeypatch):
    prof = wizard.init(cli=dojo["cli"], state=dojo["state"], provider="local", model="llama3.2:3b",
                       yes=True, skip_probe=True)
    env = prof["solver_env"]
    assert env["OPENAI_MODEL"] == "llama3.2:3b"
    assert env["OPENAI_BASE_URL"] == "http://localhost:11434/v1"
    assert env["QDOJO_PROMPTS"].endswith("prompts")     # a local model is prompt-driven too
    assert prof["key_source"] == "none" and "prompted.py" in " ".join(prof["solver"])


def test_unknown_provider_is_refused(dojo):
    with pytest.raises(wizard.WizardError) as e:
        wizard.init(cli=dojo["cli"], state=dojo["state"], provider="chatgpt", yes=True)
    assert "chatgpt" in str(e.value)


def test_none_is_listed_first(capsys):
    assert wizard.PROVIDERS[0]["key"] == "none"
    assert wizard.PROVIDER_KEYS == ("none", "openrouter", "direct", "local")


def test_a_name_that_is_too_long_is_refused_by_the_encoder(dojo):
    with pytest.raises(term.TermError) as e:
        wizard.init(cli=dojo["cli"], state=dojo["state"], name="R" * 40, provider="none", yes=True)
    assert "32 bytes" in str(e.value)


def test_setup_does_not_block_with_piped_stdin_and_no_yes(dojo, capsys):
    """pytest's stdin is not a TTY: every prompt must fall through to a default."""
    wizard.init(cli=dojo["cli"], state=dojo["state"], name="RYUBOT", provider="none", yes=True)
    capsys.readouterr()
    prof = wizard.setup(state=dojo["state"], cli=dojo["cli"])       # no yes=True, no provider, no model
    out = capsys.readouterr().out
    assert prof["provider"] == "none"                               # the menu default, listed first
    assert "YOUR FIGHTER" in out and "5,000 QU" in out              # the purse was read live


def test_setup_without_an_init_says_so(tmp_path):
    with pytest.raises(wizard.WizardError) as e:
        wizard.setup(state=str(tmp_path / "nothing"))
    assert "bot init" in str(e.value)


def test_no_setup_stops_after_the_network_step(dojo, capsys):
    prof = wizard.init(cli=dojo["cli"], state=dojo["state"], name="RYUBOT", no_setup=True, yes=True)
    out = capsys.readouterr().out
    assert "[4/4]" in out and "[5/" not in out
    assert prof["provider"] == "" and prof["solver"] == []


# ------------------------------------------------------------- the test call

def test_probe_model_passes_for_a_solver_that_answers_142():
    ok, msg, took = wizard.probe_model(py("import json,sys; sys.stdin.read(); print('{\"answer\":142}')"), {})
    assert ok is True and "142" in msg and took >= 0


def test_probe_model_fails_for_a_wrong_answer():
    ok, msg, _ = wizard.probe_model(py("import sys; sys.stdin.read(); print('{\"answer\":141}')"), {})
    assert ok is False and "141" in msg and "142" in msg


def test_probe_model_names_the_safety_rule_on_exit_2():
    ok, msg, _ = wizard.probe_model(
        py("import sys; sys.stdin.read(); print('pi.py: set PI_MODEL', file=sys.stderr); sys.exit(2)"), {})
    assert ok is False
    assert "refused to run without a model" in msg and "PI_MODEL" in msg     # the stderr tail is the diagnosis


def test_probe_model_shows_the_stderr_tail_verbatim():
    ok, msg, _ = wizard.probe_model(
        py("import sys; sys.stdin.read(); print('402 no credit remaining', file=sys.stderr); sys.exit(1)"), {})
    assert ok is False and "no credit remaining" in msg


def test_probe_model_restores_the_environment(monkeypatch):
    monkeypatch.setenv("PI_MODEL", "before")
    wizard.probe_model(py("import sys; sys.stdin.read(); print('{\"answer\":142}')"), {"PI_MODEL": "during"})
    assert os.environ["PI_MODEL"] == "before"
    assert "QDOJO_ONLY_HERE" not in os.environ
    wizard.probe_model(py("import sys; sys.stdin.read(); print('{\"answer\":142}')"), {"QDOJO_ONLY_HERE": "x"})
    assert "QDOJO_ONLY_HERE" not in os.environ


def test_the_shipped_solvers_refuse_without_a_model():
    """pi.py, evo.py and openai_compat.py all exit 2 rather than guess."""
    for name in ("pi.py", "evo.py", "openai_compat.py"):
        ok, msg, _ = wizard.probe_model(wizard.solver_argv(name), {"PI_MODEL": None, "EVO_MODEL": None,
                                                                   "OPENAI_MODEL": None}, timeout=30)
        assert ok is False and "refused to run without a model" in msg, name


def test_echo_solver_solves_the_test_riddle():
    ok, msg, _ = wizard.probe_model(wizard.solver_argv("echo.py"), {})
    assert ok is True, msg


# ------------------------------------------------------------- run command

def test_run_command_text_round_trips_through_shlex():
    prof = {"conf": "/tmp/state/bot.conf", "name": "RYU BOT", "solver": ["python3", "/a b/pi.py"],
            "solver_env": {"PI_MODEL": "deepseek/deepseek-v4-flash"}}
    assert shlex.split(wizard.run_command_text(prof, "http://b", wrap=False)) == wizard.run_command(prof, "http://b")
    wrapped = wizard.run_command_text(prof, "http://b", wrap=True)
    assert wrapped.count(" \\\n") == 3                                     # one line per flag group
    assert shlex.split(wrapped.replace(" \\\n", " ")) == wizard.run_command(prof, "http://b")


def test_run_command_carries_the_model_env_but_never_a_key():
    prof = {"conf": os.path.join(wizard.DEFAULT_STATE, "bot.conf"), "name": "RYU",
            "solver": ["python3", "pi.py"], "solver_env": {"PI_MODEL": "m"}}
    argv = wizard.run_command(prof, "http://b")
    assert argv[0] == "PI_MODEL=m" and argv[1:3] == ["qdojo", "bot"]
    assert "--state" not in argv                          # the default state dir is not repeated
    assert wizard.run_command(prof, "http://b", env_prefix=False)[0] == "qdojo"
    assert not [a for a in argv if wizard.SECRET_RE.search(a)]
