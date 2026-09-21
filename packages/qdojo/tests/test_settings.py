"""A setting is an environment variable with a manifest behind it. These
tests hold the manifest to its schema, the values to their types, and the
one rule that matters: a secret is stored as the NAME of a variable and
never as what the variable holds."""
import json
import os
import re
import sys

import pytest

from qdojo import onboard, settings, wizard
from qdojo.cli import main

HERE = os.path.dirname(os.path.abspath(__file__))
SOLVERS = os.path.abspath(os.path.join(HERE, "..", "..", "..", "examples", "solvers"))


def manifest(tmp_path, name, items, **extra):
    p = tmp_path / name
    p.write_text(json.dumps({"solver": name, "settings": items, **extra}))
    return str(p)


def solver_with_manifest(tmp_path, items):
    """A solver script plus its `<stem>.settings.json` beside it."""
    script = tmp_path / "mine.py"
    script.write_text("import json,sys; print(json.dumps({'answer': 1}))\n")
    manifest(tmp_path, "mine.settings.json", items)
    return [sys.executable, str(script)]


@pytest.fixture
def state(tmp_path):
    """A state dir with a profile pointing at a solver that declares settings."""
    d = tmp_path / "bot"
    solver = solver_with_manifest(tmp_path, [
        {"key": "MY_MODEL", "type": "string", "default": "small", "help": "which model",
         "suggestions": ["small", "large"]},
        {"key": "MY_LEVEL", "type": "enum", "choices": ["off", "low", "high"], "default": "low"},
        {"key": "MY_ROUNDS", "type": "int", "default": 3, "min": 1, "max": 10},
        {"key": "MY_RATE", "type": "float", "default": 0.5, "min": 0, "max": 1},
        {"key": "MY_LEARN", "type": "bool", "default": True},
        {"key": "MY_API_KEY", "type": "secret", "default": "MY_KEY_VAR",
         "help": "the NAME of the variable"},
    ])
    onboard.save_profile(str(d), {**wizard.PROFILE_DEFAULTS, "conf": str(d / "bot.conf"),
                                  "identity": "A" * 60, "solver": solver})
    return str(d)


# ----------------------------------------------------------------- manifest

def test_manifest_sits_beside_the_script_named_by_its_stem(tmp_path):
    solver = solver_with_manifest(tmp_path, [])
    assert settings.manifest_path(solver) == str(tmp_path / "mine.settings.json")
    assert settings.manifest_path(["python3", "/nowhere/x.py"]) is None
    assert settings.manifest_path([]) is None


def test_the_shipped_manifests_load_and_name_only_variables_their_solver_reads():
    """Every key a shipped manifest declares must be read by the script it
    sits beside, or the form would show a knob wired to nothing."""
    found = 0
    for fn in sorted(os.listdir(SOLVERS)):
        if not fn.endswith(settings.MANIFEST_SUFFIX):
            continue
        found += 1
        script = os.path.join(SOLVERS, fn[:-len(settings.MANIFEST_SUFFIX)] + ".py")
        src = open(script, encoding="utf-8").read()
        # Read directly, or named in the docstring's Env: line for a variable
        # the script reaches through qdojo (prompted.py and QDOJO_PROMPTS).
        for s in settings.load_manifest(os.path.join(SOLVERS, fn)):
            assert re.search(r"\b%s\b" % s["key"], src), \
                f"{fn} declares {s['key']} but {os.path.basename(script)} never mentions it"
    assert found >= 4                                   # evo, pi, openai_compat, prompted


def test_evo_and_pi_manifests_cover_the_documented_env_vars():
    evo = {s["key"] for s in settings.load_manifest(os.path.join(SOLVERS, "evo.settings.json"))}
    assert evo >= {"EVO_DIR", "EVO_MODEL", "EVO_THINKING", "EVO_BOARD", "EVO_TIMEOUT"}
    pi = {s["key"] for s in settings.load_manifest(os.path.join(SOLVERS, "pi.settings.json"))}
    assert pi >= {"PI_TOOLS", "PI_THINKING", "PI_TIMEOUT", "PI_MODEL", "PI_MAX_CONCURRENT", "PI_SLOT_WAIT"}
    thinking = next(s for s in settings.load_manifest(os.path.join(SOLVERS, "pi.settings.json"))
                    if s["key"] == "PI_THINKING")
    assert thinking["type"] == "enum" and thinking["choices"] == ["off", "low", "medium", "high"]


def test_the_model_settings_suggest_the_openrouter_lineup():
    """The three ids the wizard offers for openrouter are the ones this
    dojo's fighters run; the form offers the same three."""
    want = [m[0] for p in wizard.PROVIDERS if p["key"] == "openrouter" for m in p["models"]]
    for fn, key in (("evo.settings.json", "EVO_MODEL"), ("pi.settings.json", "PI_MODEL"),
                    ("openai_compat.settings.json", "OPENAI_MODEL")):
        s = next(x for x in settings.load_manifest(os.path.join(SOLVERS, fn)) if x["key"] == key)
        assert s["suggestions"] == want, fn


def test_a_secret_shaped_key_must_be_declared_a_secret(tmp_path):
    with pytest.raises(settings.SettingsError, match="must be type \"secret\""):
        settings.load_manifest(manifest(tmp_path, "x.settings.json", [{"key": "MY_TOKEN", "type": "string"}]))
    ok = settings.load_manifest(manifest(tmp_path, "y.settings.json", [{"key": "MY_TOKEN", "type": "secret"}]))
    assert ok[0]["type"] == "secret"


def test_manifest_shape_is_checked(tmp_path):
    bad = [
        ([{"key": "lower", "type": "string"}], "not an environment variable name"),
        ([{"key": "X", "type": "list"}], "not one of"),
        ([{"key": "X", "type": "enum"}], "non-empty list"),
        ([{"key": "X", "type": "int", "default": "abc"}], "not an integer"),
        ([{"key": "X", "type": "bool", "min": 1}], "only applies"),
        ([{"key": "X"}, {"key": "X"}], "declared twice"),
        ([{"key": "X", "help": "h" * 3000}], "help text longer"),
        (["X"], "is an object"),
    ]
    for items, why in bad:
        with pytest.raises(settings.SettingsError, match=why):
            settings.load_manifest(manifest(tmp_path, "bad.settings.json", items))
    p = tmp_path / "huge.settings.json"
    p.write_text("[" + " " * (settings.MAX_MANIFEST_BYTES + 1) + "]")
    with pytest.raises(settings.SettingsError, match="larger than"):
        settings.load_manifest(str(p))
    (tmp_path / "notjson.settings.json").write_text("{")
    with pytest.raises(settings.SettingsError, match="not JSON"):
        settings.load_manifest(str(tmp_path / "notjson.settings.json"))
    assert settings.load_manifest(None) == [] and settings.load_manifest(str(tmp_path / "absent.json")) == []


def test_the_owners_manifest_overrides_and_extends_the_shipped_one(state, tmp_path):
    user = settings.user_manifest_path(state)
    json.dump({"settings": [{"key": "MY_LEVEL", "type": "enum", "choices": ["low", "max"], "default": "max",
                             "help": "mine now"},
                            {"key": "MY_EXTRA", "type": "int", "default": 7}]}, open(user, "w"))
    m = settings.merged(state, wizard.load_profile(state)["solver"])
    keys = [s["key"] for s in m]
    assert keys == ["MY_MODEL", "MY_LEVEL", "MY_ROUNDS", "MY_RATE", "MY_LEARN", "MY_API_KEY", "MY_EXTRA"]
    level = next(s for s in m if s["key"] == "MY_LEVEL")
    assert level["choices"] == ["low", "max"] and level["manifest"] == "user" and level["help"] == "mine now"
    assert next(s for s in m if s["key"] == "MY_MODEL")["manifest"] == "shipped"
    assert next(s for s in m if s["key"] == "MY_EXTRA")["manifest"] == "user"


# -------------------------------------------------------------------- values

def test_values_are_coerced_by_type():
    c = settings.coerce
    assert c({"key": "K", "type": "int", "min": 1, "max": 10}, " 7 ") == "7"
    assert c({"key": "K", "type": "float"}, "1.50") == "1.5"
    assert c({"key": "K", "type": "float"}, 120) == "120"
    assert c({"key": "K", "type": "bool"}, "YES") == "true" and c({"key": "K", "type": "bool"}, 0) == "false"
    assert c({"key": "K", "type": "bool"}, True) == "true"
    assert c({"key": "K", "type": "enum", "choices": ["a", "b"]}, "b") == "b"
    assert c({"key": "K", "type": "string"}, "any text") == "any text"
    assert c({"key": "K", "type": "secret"}, "OPENROUTER_API_KEY") == "OPENROUTER_API_KEY"
    for setting, raw, why in (
        ({"key": "K", "type": "int"}, "x", "not an integer"),
        ({"key": "K", "type": "int", "max": 10}, "11", "above the maximum"),
        ({"key": "K", "type": "int", "min": 1}, "0", "below the minimum"),
        ({"key": "K", "type": "float"}, "nan", "not a finite"),
        ({"key": "K", "type": "float"}, "abc", "not a number"),
        ({"key": "K", "type": "bool"}, "maybe", "not true/false"),
        ({"key": "K", "type": "enum", "choices": ["a"]}, "z", "not one of"),
        ({"key": "K", "type": "string", "max": 3}, "abcd", "longer than"),
        ({"key": "K", "type": "string"}, "a\x00b", "NUL"),
    ):
        with pytest.raises(settings.SettingsError, match=why):
            c(setting, raw)


def test_a_key_value_is_refused_everywhere():
    """The shape of a live key is refused as a string value, and as a secret
    value, where only a variable NAME may go."""
    with pytest.raises(settings.SettingsError, match="shape of a live API key"):
        settings.coerce({"key": "K", "type": "string"}, "sk-abcdef0123456789")
    with pytest.raises(settings.SettingsError, match="never the key itself"):
        settings.coerce({"key": "K", "type": "secret"}, "sk-abcdef0123456789")
    with pytest.raises(settings.SettingsError, match="never the key itself"):
        settings.coerce({"key": "K", "type": "secret"}, "lower_case")


def test_set_and_unset_write_the_profile_and_only_the_two_env_maps(state):
    before = wizard.load_profile(state)
    row = settings.set_value(state, "MY_ROUNDS", "5")
    assert row["value"] == "5" and row["source"] == "profile"
    settings.set_value(state, "MY_LEARN", "no")
    settings.set_value(state, "MY_API_KEY", "MY_OTHER_VAR")
    after = wizard.load_profile(state)
    assert after["solver_env"] == {"MY_ROUNDS": "5", "MY_LEARN": "false"}
    assert after["secret_env"] == {"MY_API_KEY": "MY_OTHER_VAR"}
    assert {k: v for k, v in after.items() if k not in ("solver_env", "secret_env")} == \
           {k: v for k, v in before.items() if k not in ("solver_env", "secret_env")}
    assert oct(os.stat(onboard.profile_path(state)).st_mode & 0o777) == "0o600"
    settings.unset_value(state, "MY_ROUNDS")
    assert wizard.load_profile(state)["solver_env"] == {"MY_LEARN": "false"}
    with pytest.raises(settings.SettingsError, match="is not set"):
        settings.unset_value(state, "MY_ROUNDS")


def test_an_unknown_key_is_refused_and_told_where_to_declare_it(state):
    with pytest.raises(settings.SettingsError) as e:
        settings.set_value(state, "MY_NEW_THING", "1")
    assert "no such setting" in str(e.value) and settings.user_manifest_path(state) in str(e.value)
    assert wizard.load_profile(state)["solver_env"] == {}


def test_a_wrongly_typed_value_never_reaches_the_profile(state):
    with pytest.raises(settings.SettingsError):
        settings.set_value(state, "MY_ROUNDS", "eleven")
    assert wizard.load_profile(state)["solver_env"] == {}


def test_rows_say_where_each_value_comes_from(state, monkeypatch):
    settings.set_value(state, "MY_MODEL", "large")
    monkeypatch.setenv("MY_LEVEL", "high")
    monkeypatch.setenv("MY_KEY_VAR", "sk-live-value-that-must-not-show")
    by = {r["key"]: r for r in settings.rows(state)}
    assert by["MY_MODEL"]["source"] == "profile" and by["MY_MODEL"]["effective"] == "large"
    assert by["MY_LEVEL"]["source"] == "shell" and by["MY_LEVEL"]["effective"] == "high"
    assert by["MY_ROUNDS"]["source"] == "default" and by["MY_ROUNDS"]["effective"] == "3"
    sec = by["MY_API_KEY"]
    assert sec["env_name"] == "MY_KEY_VAR" and sec["set_in_env"] is True and sec["source"] == "default"
    assert "sk-live" not in json.dumps(settings.rows(state))


def test_a_stored_key_the_manifest_forgot_is_still_listed(state):
    p = wizard.load_profile(state)
    p["solver_env"]["QDOJO_PROMPTS"] = "/x/prompts"
    onboard.save_profile(state, p)
    row = next(r for r in settings.rows(state) if r["key"] == "QDOJO_PROMPTS")
    assert row["unknown"] is True and row["value"] == "/x/prompts"
    settings.unset_value(state, "QDOJO_PROMPTS")          # removing is always allowed
    assert "QDOJO_PROMPTS" not in wizard.load_profile(state)["solver_env"]


# ----------------------------------------------------------------- run time

def test_runtime_env_copies_a_secret_from_the_named_variable_and_writes_nothing(state, monkeypatch):
    settings.set_value(state, "MY_API_KEY", "MY_KEY_VAR")
    monkeypatch.setenv("MY_KEY_VAR", "sk-the-live-key")
    env = settings.runtime_env(wizard.load_profile(state))
    assert env["MY_API_KEY"] == "sk-the-live-key"
    assert "sk-the-live-key" not in open(onboard.profile_path(state)).read()
    monkeypatch.delenv("MY_KEY_VAR")
    assert "MY_API_KEY" not in settings.runtime_env(wizard.load_profile(state))


def test_apply_env_sets_defaults_but_never_overwrites_an_export(state):
    settings.set_value(state, "MY_MODEL", "large")
    settings.set_value(state, "MY_ROUNDS", "5")
    env = {"MY_MODEL": "exported"}
    applied = settings.apply_env(wizard.load_profile(state), {}, env)
    assert env == {"MY_MODEL": "exported", "MY_ROUNDS": "5"} and applied == {"MY_ROUNDS": "5"}
    # a re-read after the owner changes a setting replaces OUR value and leaves theirs
    settings.set_value(state, "MY_ROUNDS", "6")
    settings.unset_value(state, "MY_MODEL")
    applied = settings.apply_env(wizard.load_profile(state), applied, env)
    assert env == {"MY_MODEL": "exported", "MY_ROUNDS": "6"} and applied == {"MY_ROUNDS": "6"}
    # and an unset setting is withdrawn from the environment, if it was ours
    settings.unset_value(state, "MY_ROUNDS")
    applied = settings.apply_env(wizard.load_profile(state), applied, env)
    assert env == {"MY_MODEL": "exported"} and applied == {}


# ---------------------------------------------------------------------- CLI

def test_cli_round_trip_on_a_temp_state_dir(state, capsys, monkeypatch):
    main(["bot", "--state", state, "settings", "set", "MY_LEVEL", "high"])
    assert "MY_LEVEL" in capsys.readouterr().out
    assert wizard.load_profile(state)["solver_env"] == {"MY_LEVEL": "high"}
    main(["bot", "--state", state, "settings"])
    out = capsys.readouterr().out
    assert "MY_LEVEL" in out and "high" in out and "profile" in out and "default" in out
    main(["bot", "--state", state, "settings", "--json"])
    rows = json.loads(capsys.readouterr().out)
    assert next(r for r in rows if r["key"] == "MY_LEVEL")["value"] == "high"
    main(["bot", "--state", state, "settings", "describe"])
    doc = json.loads(capsys.readouterr().out)
    assert doc["shipped"].endswith("mine.settings.json") and doc["user"] == settings.user_manifest_path(state)
    assert [s["key"] for s in doc["settings"]][:2] == ["MY_MODEL", "MY_LEVEL"]
    main(["bot", "--state", state, "settings", "unset", "MY_LEVEL"])
    assert wizard.load_profile(state)["solver_env"] == {}
    with pytest.raises(SystemExit) as e:
        main(["bot", "--state", state, "settings", "set", "MY_ROUNDS", "99"])
    assert "above the maximum" in str(e.value)


def test_cli_secret_shows_the_name_and_whether_it_is_set_never_the_value(state, capsys, monkeypatch):
    monkeypatch.setenv("MY_KEY_VAR", "sk-live-secret-value")
    main(["bot", "--state", state, "settings", "set", "MY_API_KEY", "MY_KEY_VAR"])
    main(["bot", "--state", state, "settings"])
    out = capsys.readouterr().out
    assert "$MY_KEY_VAR" in out and "set" in out and "sk-live" not in out
    with pytest.raises(SystemExit) as e:
        main(["bot", "--state", state, "settings", "set", "MY_API_KEY", "sk-live-secret-value"])
    assert "never the key itself" in str(e.value)
    assert "sk-live" not in open(onboard.profile_path(state)).read()


def test_bot_run_and_train_apply_the_profile_through_the_same_door():
    """cli.py used to loop over solver_env by hand in two places; both now go
    through settings.apply_env, which is the only way a secret is copied."""
    src = open(os.path.join(HERE, "..", "src", "qdojo", "cli.py"), encoding="utf-8").read()
    assert src.count("settings.apply_env(") >= 2
    assert 'prof.get("solver_env") or {}).items()' not in src
