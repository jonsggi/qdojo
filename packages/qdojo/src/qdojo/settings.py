"""What a fighter can be told without editing it: a settings manifest.

A solver declares its knobs in a JSON file beside it, `<stem>.settings.json`
(examples/solvers/evo.settings.json is the model). The owner's own additions
live in `<state dir>/settings.json` with the same shape; on a key clash the
owner's entry wins. The two are merged on every read, so adding a setting is
editing a file and nothing else.

A setting IS an environment variable. Values are written to bot.json under
"solver_env", the profile key `bot run` already feeds the solver, and a solver
reads them with `os.environ.get()` -- the same way it reads anything the owner
exported by hand. An exported variable still wins over a stored one.

Types: string, int, float, bool, enum, secret. `secret` is the one type whose
stored value is never the thing itself: it holds the NAME of an environment
variable, `bot run` reads that variable when it starts and hands the value to
the solver in-process, and nothing is written anywhere. That is wizard.py's
--key-env rule made into a type, and the reason a key named like a credential
must be declared a secret: the profile refuses to store it any other way.
"""
import json
import math
import os
import re

from . import onboard, wizard

TYPES = ("string", "int", "float", "bool", "enum", "secret")
KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")          # an environment variable name
USER_MANIFEST = "settings.json"
MANIFEST_SUFFIX = ".settings.json"

MAX_MANIFEST_BYTES = 256 * 1024
MAX_SETTINGS = 64          # per profile; a solver with more knobs than this wants a config file
MAX_VALUE = 4096           # bytes of one string value
MAX_HELP = 2000
TRUE_WORDS = ("1", "true", "yes", "on")
FALSE_WORDS = ("0", "false", "no", "off")


class SettingsError(Exception):
    pass


# ---------------------------------------------------------------- manifests

def manifest_path(solver_argv) -> str | None:
    """`<stem>.settings.json` beside the first argv token that is a file.

    An interpreter comes first in a solver argv (`python3 /x/evo.py`), and when
    the wizard wrote it, it is sys.executable -- a file. So when argv[0] and a
    later token are both files, the later one is the script."""
    files = [str(t) for t in list(solver_argv or []) if os.path.isfile(str(t))]
    if len(files) > 1 and files[0] == str(solver_argv[0]):
        files = files[1:]
    if not files:
        return None
    stem, _ = os.path.splitext(files[0])
    return stem + MANIFEST_SUFFIX


def user_manifest_path(state_dir: str) -> str:
    return os.path.join(os.path.abspath(os.path.expanduser(state_dir)), USER_MANIFEST)


def check_setting(d: dict, where: str = "") -> dict:
    """One manifest entry, normalised, or SettingsError naming what is wrong."""
    at = f"{where}: " if where else ""
    if not isinstance(d, dict):
        raise SettingsError(f"{at}a setting is an object, not {type(d).__name__}")
    key = d.get("key")
    if not isinstance(key, str) or not KEY_RE.match(key):
        raise SettingsError(f"{at}key {key!r} is not an environment variable name (A-Z, 0-9, _; 64 max)")
    kind = d.get("type", "string")
    if kind not in TYPES:
        raise SettingsError(f"{at}{key}: type {kind!r} is not one of {', '.join(TYPES)}")
    if kind != "secret" and wizard.SECRET_RE.search(key):
        raise SettingsError(f"{at}{key}: a key named like a credential must be type \"secret\"; "
                            f"qdojo never stores a key value, only the name of the variable holding one")
    out = {"key": key, "type": kind, "label": str(d.get("label") or key.lower().replace("_", " ")),
           "help": str(d.get("help") or "")}
    if len(out["help"]) > MAX_HELP:
        raise SettingsError(f"{at}{key}: help text longer than {MAX_HELP} characters")
    if kind == "enum":
        choices = d.get("choices")
        if not isinstance(choices, list) or not choices or not all(isinstance(c, str) for c in choices):
            raise SettingsError(f"{at}{key}: an enum needs a non-empty list of string choices")
        out["choices"] = list(choices)
    for bound in ("min", "max"):
        if bound in d and d[bound] is not None:
            if kind not in ("int", "float", "string"):
                raise SettingsError(f"{at}{key}: {bound} only applies to int, float and string")
            if not isinstance(d[bound], (int, float)) or isinstance(d[bound], bool):
                raise SettingsError(f"{at}{key}: {bound} must be a number")
            out[bound] = d[bound]
    if "suggestions" in d and d["suggestions"] is not None:
        s = d["suggestions"]
        if not isinstance(s, list) or not all(isinstance(x, str) for x in s):
            raise SettingsError(f"{at}{key}: suggestions must be a list of strings")
        out["suggestions"] = list(s)
    default = d.get("default")
    out["default"] = None if default is None or default == "" and kind != "string" else coerce(out, default)
    if kind == "string" and default is None:
        out["default"] = None
    return out


def load_manifest(path: str | None) -> list[dict]:
    """Every setting a manifest file declares, validated. No file, no settings."""
    if not path or not os.path.isfile(path):
        return []
    if os.path.getsize(path) > MAX_MANIFEST_BYTES:
        raise SettingsError(f"{path} is larger than {MAX_MANIFEST_BYTES} bytes; that is not a settings manifest")
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
    except ValueError as e:
        raise SettingsError(f"{path}: not JSON ({e})")
    if isinstance(doc, dict):
        items = doc.get("settings")
    else:
        items = doc
    if not isinstance(items, list):
        raise SettingsError(f"{path}: expected {{\"settings\": [...]}}")
    out, seen = [], set()
    for i, d in enumerate(items):
        s = check_setting(d, f"{os.path.basename(path)}[{i}]")
        if s["key"] in seen:
            raise SettingsError(f"{path}: {s['key']} is declared twice")
        seen.add(s["key"])
        out.append(s)
    if len(out) > MAX_SETTINGS:
        raise SettingsError(f"{path}: more than {MAX_SETTINGS} settings")
    return out


def merged(state_dir: str, solver_argv=None) -> list[dict]:
    """The shipped manifest with the owner's on top: same key replaces in
    place, a new key is appended. Each entry says which file it came from."""
    shipped = manifest_path(solver_argv)
    out = []
    for s in load_manifest(shipped):
        out.append({**s, "manifest": "shipped"})
    for s in load_manifest(user_manifest_path(state_dir)):
        s = {**s, "manifest": "user"}
        for i, prev in enumerate(out):
            if prev["key"] == s["key"]:
                out[i] = s
                break
        else:
            out.append(s)
    return out


def describe(state_dir: str, profile: dict | None = None) -> dict:
    """The merged manifest as one document: where each half lives and every
    setting with its current value. What `bot settings describe` prints."""
    prof = profile if profile is not None else wizard.load_profile(state_dir)
    solver = list(prof.get("solver") or [])
    return {"shipped": manifest_path(solver), "user": user_manifest_path(state_dir),
            "solver": [os.path.basename(str(x)) for x in solver],
            "settings": rows(state_dir, prof)}


# ------------------------------------------------------------------- values

def _bounds(setting, v):
    lo, hi = setting.get("min"), setting.get("max")
    if lo is not None and v < lo:
        raise SettingsError(f"{setting['key']}: {v} is below the minimum {lo}")
    if hi is not None and v > hi:
        raise SettingsError(f"{setting['key']}: {v} is above the maximum {hi}")


def coerce(setting: dict, raw) -> str:
    """A value as typed on a command line or posted by the page, checked
    against its type and stored as the string the environment will carry."""
    key, kind = setting["key"], setting["type"]
    if isinstance(raw, bool):
        raw = "true" if raw else "false"
    text = str(raw).strip() if raw is not None else ""
    if "\x00" in text:
        raise SettingsError(f"{key}: a value cannot contain NUL")
    if kind == "int":
        try:
            v = int(text)
        except ValueError:
            raise SettingsError(f"{key}: {text!r} is not an integer")
        _bounds(setting, v)
        return str(v)
    if kind == "float":
        try:
            v = float(text)
        except ValueError:
            raise SettingsError(f"{key}: {text!r} is not a number")
        if not math.isfinite(v):
            raise SettingsError(f"{key}: {text!r} is not a finite number")
        _bounds(setting, v)
        s = repr(v)
        return s[:-2] if s.endswith(".0") else s
    if kind == "bool":
        if text.lower() in TRUE_WORDS:
            return "true"
        if text.lower() in FALSE_WORDS:
            return "false"
        raise SettingsError(f"{key}: {text!r} is not true/false")
    if kind == "enum":
        if text not in setting["choices"]:
            raise SettingsError(f"{key}: {text!r} is not one of {', '.join(setting['choices'])}")
        return text
    if kind == "secret":
        if not KEY_RE.match(text):
            raise SettingsError(f"{key}: a secret setting takes the NAME of the environment variable holding "
                                f"the key (letters, digits, _), never the key itself. Export the key in your "
                                f"shell, then name the variable here.")
        if wizard.SECRET_VALUE_RE.match(text):
            raise SettingsError(f"{key}: that is a key, not a variable name. qdojo never stores one.")
        return text
    limit = int(setting.get("max") or MAX_VALUE)
    if len(text.encode("utf-8")) > limit:
        raise SettingsError(f"{key}: longer than {limit} bytes")
    if setting.get("min") is not None and len(text) < setting["min"]:
        raise SettingsError(f"{key}: shorter than {setting['min']} characters")
    if wizard.SECRET_VALUE_RE.match(text):
        raise SettingsError(f"{key}: that value has the shape of a live API key. qdojo never stores one; "
                            f"declare the setting as type \"secret\" and name the variable instead.")
    return text


def _stores(profile: dict) -> tuple[dict, dict]:
    return dict(profile.get("solver_env") or {}), dict(profile.get("secret_env") or {})


def rows(state_dir: str, profile: dict | None = None, environ: dict | None = None) -> list[dict]:
    """Every setting with what it is worth right now and where that comes from.

    `source` is where the value the solver would see comes from: "shell" when
    the variable is exported in this process (an export wins, as in `bot run`),
    "profile" when bot.json holds it, "default" otherwise. A secret row carries
    the NAME of the variable and whether that variable is set -- never what it
    holds. A stored key the manifest does not know is listed too, flagged, so
    nothing in the profile is invisible."""
    env = os.environ if environ is None else environ
    prof = profile if profile is not None else wizard.load_profile(state_dir)
    solver_env, secret_env = _stores(prof)
    out, known = [], set()
    for s in merged(state_dir, prof.get("solver")):
        known.add(s["key"])
        row = {k: s.get(k) for k in ("key", "label", "type", "help", "default", "choices", "min", "max",
                                    "suggestions", "manifest") if s.get(k) is not None}
        if s["type"] == "secret":
            name = secret_env.get(s["key"])
            row.update(value=name, source="profile" if name else ("default" if s.get("default") else "unset"))
            name = name or s.get("default")
            row["env_name"] = name
            row["set_in_env"] = bool(env.get(name)) if name else False
        else:
            stored = solver_env.get(s["key"])
            if s["key"] in env:
                row.update(value=stored, effective=env[s["key"]], source="shell")
            elif stored is not None:
                row.update(value=stored, effective=stored, source="profile")
            else:
                row.update(value=None, effective=s.get("default"), source="default")
        out.append(row)
    for k, v in sorted(solver_env.items()):
        if k not in known:
            out.append({"key": k, "label": k.lower().replace("_", " "), "type": "string", "help": "",
                        "value": v, "effective": env.get(k, v), "source": "shell" if k in env else "profile",
                        "unknown": True})
    for k, v in sorted(secret_env.items()):
        if k not in known:
            out.append({"key": k, "label": k.lower().replace("_", " "), "type": "secret", "help": "",
                        "value": v, "env_name": v, "set_in_env": bool(env.get(v)), "source": "profile",
                        "unknown": True})
    return out


def find(state_dir: str, key: str, profile: dict) -> dict:
    for s in merged(state_dir, profile.get("solver")):
        if s["key"] == key:
            return s
    known = ", ".join(s["key"] for s in merged(state_dir, profile.get("solver"))) or "none yet"
    raise SettingsError(f"{key}: no such setting. Known: {known}. To add one, declare it in "
                        f"{user_manifest_path(state_dir)} (docs/api.md, 'Settings').")


def set_value(state_dir: str, key: str, raw, profile: dict | None = None) -> dict:
    """Validate against the manifest and write bot.json. Returns the row."""
    prof = profile if profile is not None else wizard.load_profile(state_dir)
    if not os.path.isfile(onboard.profile_path(state_dir)):
        raise SettingsError(f"no bot profile in {state_dir}; run `qdojo bot init` first")
    s = find(state_dir, str(key or ""), prof)
    value = coerce(s, raw)
    solver_env, secret_env = _stores(prof)
    if s["type"] == "secret":
        secret_env[key] = value
        solver_env.pop(key, None)
    else:
        solver_env[key] = value
        secret_env.pop(key, None)
    if len(solver_env) + len(secret_env) > MAX_SETTINGS:
        raise SettingsError(f"more than {MAX_SETTINGS} settings stored; unset something first")
    try:
        wizard.check_no_secrets(solver_env)
    except wizard.WizardError as e:
        raise SettingsError(str(e))
    prof["solver_env"], prof["secret_env"] = solver_env, secret_env
    onboard.save_profile(state_dir, prof)
    return next(r for r in rows(state_dir, prof) if r["key"] == key)


def unset_value(state_dir: str, key: str, profile: dict | None = None) -> None:
    """Forget a stored value; the default (or nothing) applies again. Any
    stored key may be removed, manifest or not: removing cannot leak."""
    prof = profile if profile is not None else wizard.load_profile(state_dir)
    solver_env, secret_env = _stores(prof)
    if key not in solver_env and key not in secret_env:
        raise SettingsError(f"{key} is not set")
    solver_env.pop(key, None)
    secret_env.pop(key, None)
    prof["solver_env"], prof["secret_env"] = solver_env, secret_env
    onboard.save_profile(state_dir, prof)


# ---------------------------------------------------------------- run time

def runtime_env(profile: dict, environ: dict | None = None) -> dict:
    """What the solver should see: every stored setting, plus for each secret
    the value of the named variable, read now and never written.

    The mapping is solver variable -> owner's variable. When they are the
    same name the solver inherits it anyway; when they differ (the solver
    reads OPENAI_API_KEY, the owner keeps OPENROUTER_API_KEY) this is the copy
    the wizard's probe already makes in-process."""
    env = os.environ if environ is None else environ
    out = {k: str(v) for k, v in (profile.get("solver_env") or {}).items()}
    for k, name in (profile.get("secret_env") or {}).items():
        if name and name != k and env.get(name):
            out[k] = env[name]
    return out


def apply_env(profile: dict, applied: dict, environ=None) -> dict:
    """Put the profile's settings into the environment the solver inherits.

    setdefault, never overwrite: an explicitly exported PI_MODEL=x still wins.
    `applied` is what a previous call put there, so a re-read of the profile
    while the bot runs can replace or remove ITS OWN values -- a setting saved
    from the cockpit is then live on the next poll -- without ever touching a
    variable the owner exported. Returns the new `applied`."""
    env = os.environ if environ is None else environ
    want = runtime_env(profile, env)
    now = {}
    for k, v in want.items():
        if k not in env or (k in applied and env.get(k) == applied[k]):
            env[k] = v
            now[k] = v
        elif k in env:
            pass                                    # the owner's export wins
    for k, v in applied.items():
        if k not in want and env.get(k) == v:
            env.pop(k, None)
    return now
