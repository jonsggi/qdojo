"""`qdojo bot init` / `qdojo bot setup` as a ceremony that VERIFIES.

Six staged steps. Each one proves something instead of printing a claim:
qubic-cli is not merely found but run; the seed conf is not merely written but
stat'ed for mode 0600; the name is not merely measured but pushed through
`payload.encode(payload.Bow(name))`; the node is not merely named but asked for
its tick; the model is not merely configured but made to solve one cheap test
riddle through `solver.run_solver` — the exact code path `bot run` uses; and the
balance is read live, where an unknown is a warning and never a zero.

NON-NEGOTIABLE: qdojo never stores an API key. Not in bot.json, not in a conf,
not in argv, not in an env file it writes. There is no flag anywhere that takes
a key value — a key on a command line lands in shell history and in `ps`. The
profile records only the NAME OF THE PLACE the key lives:
`"key_source": "pi" | "env:OPENROUTER_API_KEY" | "none"`.
"""
import contextlib
import dataclasses
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import textwrap
import time

from . import nodes, onboard, payload, prompts, qubic, term
from .chain.base import ChainError, Unknown
from .chain.native import NativeChain
from .payload import PayloadError
from .solver import SolverError, run_solver


class WizardError(RuntimeError):
    """Fatal and loud. Subclasses RuntimeError so cli.py's existing handler
    already turns it into `qdojo: <message>` without a change."""


DEFAULT_STATE = os.path.expanduser("~/.qdojo/bot")
DEFAULT_BOARD = "https://klabautermann.tailb4bd0.ts.net/qdojo/data/board.json"
DEFAULT_SEAT = 1000          # a white-belt seat, when no board says otherwise
BUILD_CLI = "./scripts/build-qubic-cli.sh"

# One frozen vector out of qubic-cli, so the signer can be proved here with
# no binary and no network. The seed is the publicly known 55 'a's -- the
# identity anyone can spend from, which is why it is safe to write down.
SIGNER_CHECK_SEED = "a" * 55
SIGNER_CHECK_IDENTITY = "BZBQFLLBNCXEMGLOBHUVFTLUPLVCPQUASSILFABOFFBCADQSSUPNWLZBQEXK"
SIGNER_CHECK_PAYLOAD = bytes.fromhex(
    "1f590d03e613bdded38b4c0820ac44615f91af12435980b3ede3c08c315a2544"
    "1f590d03e613bdded38b4c0820ac44615f91af12435980b3ede3c08c315a2544"
    "3930000000000000f0e0cf0400000000"
    "8d2fa826775df4d167899079219766339c2a7ca28ceb338911a780e45c29502e"
    "053763bd193d8b4ed9a41dbcba3ec9119b5faa422fae7c0487848f8262080600"
)
CLI_MARKERS = ("qubic", "nodeip", "showkeys", "getbalance", "usage", "sendtoaddress")

PROFILE_KEYS = ("conf", "identity", "name", "cli", "provider", "model", "solver", "solver_env",
                "key_source", "setup_at")
PROFILE_DEFAULTS = {"conf": "", "identity": "", "name": "", "cli": "qubic-cli", "provider": "",
                    "model": "", "solver": [], "solver_env": {}, "key_source": "none", "setup_at": 0}

# A name for anything that must never be written down, and a shape for a value
# that is obviously a live credential even under an innocent name.
SECRET_RE = re.compile(r"(?i)(key|token|secret|password|passwd|credential)")
SECRET_VALUE_RE = re.compile(r"^(sk-|sk_|ghp_|gho_|github_pat_|xox[baprs]-|AIza|Bearer\s)")

TEST_RIDDLE = {"round_id": 0, "title": "white belt: sum the numbers",
               "statement": "Add every number below.", "input": "17 25 -8 108",
               "answer_format": "integer"}
TEST_ANSWER = "142"

# ---------------------------------------------------------------------------
# Model ids rot far faster than this code. The suggestions below were current
# on 2026-09-16 (the openrouter three are the ids this dojo's own fighters run
# today). When one comes back "unknown model", that is not a qdojo bug:
# choose "type any model id" and paste a current one from the provider's list.
# ---------------------------------------------------------------------------
PROVIDERS = (
    {
        "key": "none",
        "label": "none — no LLM at all, a plain script wins",
        "hint": "free, instant, and already on the podium",
        "how_to": ("Costs nothing and needs no account. Half the white-belt riddles are arithmetic, and "
                   "examples/solvers/echo.py already sums them — a plain script has stood on the podium. "
                   "This is the honest first choice. Buy a model later, out of winnings."),
        "solver": "echo", "models": (), "base_url": "", "key_env": "",
    },
    {
        "key": "openrouter",
        "label": "openrouter — one key, every model",
        "hint": "one account in front of every major model",
        "how_to": ("One account, one key, every major model behind it. Sign up at https://openrouter.ai, make a "
                   "key under Keys, then export it in your shell — never on a qdojo command line. Pay as you go: "
                   "the cheap models run about $0.10-0.30 per million tokens, a white-belt round is a few "
                   "thousand tokens, and the :free models cost nothing but queue."),
        "solver": "pi", "base_url": "https://openrouter.ai/api/v1", "key_env": "OPENROUTER_API_KEY",
        "models": (("deepseek/deepseek-v4-flash", "cheap — pennies a round, and this dojo's own fighters use it", ""),
                   ("qwen/qwen3-235b-a22b-2507", "strong — a big open model, slower and dearer", ""),
                   ("google/gemini-3.1-flash-lite", "cheapest — a :free suffix on an id costs nothing but queues", "")),
    },
    {
        "key": "direct",
        "label": "direct — a key straight from DeepSeek / Google AI Studio / Anthropic",
        "hint": "cheapest per token, one key per provider",
        "how_to": ("Cheapest per token, one account per provider. DeepSeek: https://platform.deepseek.com "
                   "(about $0.28 in / $0.42 out per million). Google AI Studio: https://aistudio.google.com/apikey "
                   "(a genuinely free daily tier). Anthropic: https://console.anthropic.com. Export the key in "
                   "your shell; qdojo stores only the name of the variable."),
        "solver": "pi", "base_url": "https://api.deepseek.com/v1", "key_env": "OPENAI_API_KEY",
        "models": (("deepseek-chat", "cheap — DeepSeek direct", "https://api.deepseek.com/v1"),
                   ("claude-sonnet-4-5", "strong — Anthropic's OpenAI-compatible endpoint",
                    "https://api.anthropic.com/v1"),
                   ("gemini-3.1-flash-lite", "free tier — Google AI Studio, daily limits",
                    "https://generativelanguage.googleapis.com/v1beta/openai")),
    },
    {
        "key": "local",
        "label": "local — Ollama or any OpenAI-compatible endpoint on this machine",
        "hint": "free for ever, private, as fast as your box",
        "how_to": ("Free for ever, private, and as fast as your hardware. Install Ollama from https://ollama.com, "
                   "`ollama pull qwen2.5-coder:7b`, and it serves http://localhost:11434/v1 with no key at all. "
                   "LM Studio and vLLM speak the same shape on their own ports."),
        "solver": "openai_compat", "base_url": "http://localhost:11434/v1", "key_env": "",
        "models": (("qwen2.5-coder:7b", "cheap — fits 8GB, good at arithmetic", ""),
                   ("deepseek-r1:14b", "strong — reasons, wants ~12GB", ""),
                   ("llama3.2:3b", "free and tiny — runs on almost anything", "")),
    },
)
PROVIDER_KEYS = tuple(p["key"] for p in PROVIDERS)

# What kind of fighter, asked first. A provider and a model are a SUB-question
# that only appears once a choice needs one -- so someone taking the free path
# is never asked for an API key at all.
SOLVERS = (
    {"key": "bare", "label": "bare bones — a plain script, no model, no key, no bill",
     "hint": "thirty lines of Python you can read; it has taken first place here",
     "file": "bare.py", "needs_model": False,
     "how_to": "Your fighter is a program, not a model. It costs nothing to run, it never times out and it "
               "never refuses. Half the white belt is arithmetic and string work. Open examples/solvers/bare.py, "
               "read all of it, and change one thing -- `qdojo train` will name every answer you should have given."},
    {"key": "prompt", "label": "prompt-driven — one model call, and the fighter is a text file",
     "hint": "everything the model is told lives in two .md files you edit",
     "file": "prompted.py", "needs_model": True,
     "how_to": "One call to a language model per riddle, and everything it is told lives in solver-system.md and "
               "solver-user.md. There is no Python to read. Change a sentence, save, and the next round uses it. "
               "You bring the key; qdojo records the NAME of the variable you keep it in and nothing else."},
    {"key": "byo", "label": "bring your own — any program, any language",
     "hint": "riddle JSON on stdin, {\"answer\": …} on the last line of stdout",
     "file": "", "needs_model": False,
     "how_to": "Point the dojo at anything: an agent, a solver you wrote, a model you trained, a lookup table. "
               "It gets the riddle on stdin and prints the answer on stdout; what happens in between is yours."},
)
SOLVER_KEYS = tuple(x["key"] for x in SOLVERS)
# An old --provider still picks a sensible kind, so nothing we published breaks.
PROVIDER_TO_SOLVER = {"none": "bare", "openrouter": "prompt", "direct": "prompt", "local": "prompt"}


# --------------------------------------------------------------------- options

@dataclasses.dataclass
class Opts:
    """Every choice the ceremony can make, so it can be made for it.

    `init()` and `setup()` accept any object with these attribute names
    (an `argparse.Namespace` is exactly right), and/or the same names as
    keyword arguments, which win. `None` on the object means "not given".
    """
    state: str = DEFAULT_STATE          # bot state dir (seed conf, profile, node cache)
    cli: str | None = None              # path to qubic-cli; "qubic-cli" is read as "not given"
    conf: str | None = None             # seed conf path; default <state>/bot.conf
    name: str | None = None             # fighter name (<= 32 bytes as a BOW payload)
    node: str | None = None             # IP[:PORT] to use instead of discovery
    seed_from_stdin: bool = False       # import an existing seed rather than create one
    yes: bool = False                   # take every default, ask nothing
    color: bool | None = None           # force styling on/off; None = auto-detect
    provider: str | None = None         # none | openrouter | direct | local
    model: str | None = None            # model id, verbatim
    base_url: str | None = None         # OpenAI-compatible endpoint override
    key_env: str | None = None          # NAME of the env var holding the key. NEVER a key.
    solver: list[str] | None = None     # explicit solver argv
    env: list[str] | None = None        # ["NAME=VALUE", ...] extra solver env; refused if secret-shaped
    pi: str | None = None               # path to the pi binary
    board: str | None = None            # board URL; only fetched when given explicitly
    seat_fee: int | None = None         # what a first seat costs, when you already know
    no_setup: bool = False              # init: stop after the node step, skip provider/model/purse
    skip_probe: bool = False            # do not spend a token on the test riddle
    probe_timeout: float = 90.0


def _opts(args_like=None, **kw) -> Opts:
    o = Opts()
    for f in dataclasses.fields(Opts):
        v = getattr(args_like, f.name, None) if args_like is not None else None
        if isinstance(args_like, dict):
            v = args_like.get(f.name)
        if f.name in kw and kw[f.name] is not None:
            v = kw[f.name]
        if v is not None:
            setattr(o, f.name, v)
    if o.cli == "qubic-cli":            # cli.py's global default: means "not given"
        o.cli = None
    o.state = os.path.expanduser(o.state or DEFAULT_STATE)
    return o


# ----------------------------------------------------------------- no secrets

def check_no_secrets(env: dict) -> None:
    """Refuse anything that looks like a credential, naming it.

    Called on every write of `solver_env` and on every `--env NAME=VALUE`.
    qdojo records the name of the place a key lives, never the key."""
    for k, v in (env or {}).items():
        if SECRET_RE.search(str(k)):
            raise WizardError(
                f"{k}: qdojo never stores an API key, and this name says it is one. "
                f"Export {k} in your shell instead — the profile records only the name of the place.")
        if SECRET_VALUE_RE.match(str(v).strip()):
            raise WizardError(
                f"{k}: that value has the shape of a live API key. qdojo never stores one, and a key on a "
                f"command line is already in your shell history and in `ps`. Rotate it, then export it.")


def parse_env(items) -> dict:
    """`["NAME=VALUE", ...]` -> dict, refusing secrets."""
    out = {}
    for it in items or []:
        name, sep, value = str(it).partition("=")
        if not sep or not name.strip():
            raise WizardError(f"--env wants NAME=VALUE, got {it!r}")
        out[name.strip()] = value
    check_no_secrets(out)
    return out


# ------------------------------------------------------------------- finding

def find_pi(explicit: str | None = None) -> str:
    """The `pi` coding agent, the way onboard.find_cli finds qubic-cli.
    Raises WizardError when it is not installed — which is normal."""
    for cand in ([explicit] if explicit else []) + [os.environ.get("QDOJO_PI"), "pi",
                                                    os.path.expanduser("~/.local/bin/pi")]:
        if cand and (shutil.which(cand) or os.access(cand, os.X_OK)):
            return shutil.which(cand) or cand
    raise WizardError("pi not found: it is not on PATH and QDOJO_PI is unset")


def examples_dir() -> str | None:
    """Where examples/solvers/ lives, for a checkout or an installed package."""
    here = os.path.dirname(os.path.abspath(__file__))
    for cand in (os.environ.get("QDOJO_EXAMPLES"),
                 os.path.abspath(os.path.join(here, "..", "..", "..", "..", "examples", "solvers")),
                 os.path.join(os.getcwd(), "examples", "solvers"),
                 os.path.expanduser("~/.qdojo/solvers")):
        if cand and os.path.isdir(cand):
            return cand
    return None


def solver_argv(filename: str) -> list[str]:
    """`[python3, /abs/path/to/<filename>]`, or WizardError saying where to look."""
    d = examples_dir()
    path = os.path.join(d, filename) if d else ""
    if not path or not os.path.exists(path):
        raise WizardError(f"{filename} not found: set QDOJO_EXAMPLES to your checkout's examples/solvers, "
                          f"or pass --solver explicitly")
    return [sys.executable, path]


# --------------------------------------------------------------- the test call

@contextlib.contextmanager
def _environ(overrides):
    """Apply `overrides` on top of the real environment, then put it back
    exactly as it was. Nothing here is ever written to disk."""
    old = {k: os.environ.get(k) for k in (overrides or {})}
    try:
        for k, v in (overrides or {}).items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, str(v))
        yield
    finally:
        for k, v in old.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)


def probe_model(solver_cmd, env, timeout: float = 90.0) -> tuple[bool, str, float]:
    """Make the solver actually solve one cheap riddle. -> (passed, message, seconds)

    It goes through `solver.run_solver`, the exact path `bot run` uses, so a
    pass means the solver file, the model id and the key all work together.
    `env` is applied on top of the current environment for the call only.
    On failure the message is the diagnosis, verbatim: "no credit", "unknown
    model", "pi: command not found" are the answer, not noise.
    """
    started = time.time()
    with _environ(env):
        try:
            got = run_solver(list(solver_cmd), TEST_RIDDLE, timeout=timeout)
        except SolverError as e:
            took = time.time() - started
            msg = str(e)
            if re.match(r"solver exited 2\b", msg):
                tail = msg.split(":", 1)[1].strip() if ":" in msg else ""
                return False, ("the solver refused to run without a model — that is the safety rule working, and "
                               "it means the model id never reached it" + (f" · {tail}" if tail else "")), took
            return False, msg, took
    took = time.time() - started
    if got == TEST_ANSWER:
        return True, f"answered {TEST_ANSWER} in {took:.1f}s", took
    return False, f"answered {got!r}, expected {TEST_ANSWER}", took


# ------------------------------------------------------------------- profile

def load_profile(state_dir: str) -> dict:
    """The bot profile with every documented key present. An old four-key
    profile (conf/identity/name/cli) loads and gains safe defaults."""
    p = dict(onboard.load_profile(state_dir))
    for k, d in PROFILE_DEFAULTS.items():
        p.setdefault(k, json.loads(json.dumps(d)))
    return p


def _profile(ctx) -> dict:
    prev = ctx.get("prof") or {}
    p = {"conf": ctx["conf"], "identity": ctx["identity"], "name": ctx.get("name") or "",
         "cli": ctx.get("cli") or prev.get("cli") or "qubic-cli",
         "provider": ctx.get("provider", prev.get("provider", "")),
         "model": ctx.get("model", prev.get("model", "")),
         "solver": list(ctx.get("solver") or prev.get("solver") or []),
         "solver_env": dict(ctx.get("solver_env", prev.get("solver_env") or {})),
         "key_source": ctx.get("key_source", prev.get("key_source", "none")),
         "setup_at": int(time.time())}
    check_no_secrets(p["solver_env"])
    assert set(p) == set(PROFILE_KEYS), sorted(set(p) ^ set(PROFILE_KEYS))
    return p


def run_command(profile: dict, board: str | None = None, env_prefix: bool = True) -> list[str]:
    """The ready-to-run `qdojo bot run …` as a token list.

    With `env_prefix` (the default) the leading `NAME=value` tokens are shell
    environment assignments — that is what makes the line work as printed,
    because the solver inherits them. Pass `env_prefix=False` for a clean argv
    you can hand to subprocess.
    """
    argv = []
    if env_prefix:
        argv += [f"{k}={v}" for k, v in sorted((profile.get("solver_env") or {}).items())]
    argv += ["qdojo", "bot"]
    state = os.path.dirname(profile.get("conf") or "")
    if state and os.path.abspath(state) != os.path.abspath(DEFAULT_STATE):
        argv += ["--state", state]
    solver = list(profile.get("solver") or ["python3", "examples/solvers/echo.py"])
    argv += ["run", "--board", board or DEFAULT_BOARD, "--solver", *solver]
    if profile.get("name"):
        argv += ["--name", profile["name"]]
    return argv


def run_command_text(profile: dict, board: str | None = None, wrap: bool = True, env_prefix: bool = True) -> str:
    """The same command as one shell-safe string.
    `shlex.split(run_command_text(p, b, wrap=False)) == run_command(p, b)`."""
    args = [shlex.quote(a) for a in run_command(profile, board, env_prefix)]
    if not wrap:
        return " ".join(args)
    out, line = [], []
    for a in args:
        if line and a in ("--board", "--solver", "--name"):
            out.append(" ".join(line))
            line = ["   "]
        line.append(a)
    out.append(" ".join(line))
    return " \\\n".join(out)


# --------------------------------------------------------------------- steps

def _say(text: str) -> None:
    for line in textwrap.wrap(text, max(20, term.width() - 6)):
        print("    " + term.c(line, "dim"))


def _build_hint() -> None:
    print("    " + term.c("build the reference signer, once:", "dim"))
    print("    " + term.c(BUILD_CLI, "bold"))


def _cli_answers(cli: str) -> str | None:
    """Run qubic-cli once and look for a marker. Its exit code is worthless:
    it exits 0 on failure, so the text is the only evidence."""
    for args in ([cli, "-help"], [cli]):
        try:
            p = subprocess.run(args, capture_output=True, text=True, timeout=20)
        except (OSError, subprocess.TimeoutExpired):
            continue
        out = (p.stdout or "") + "\n" + (p.stderr or "")
        if any(m in out.lower() for m in CLI_MARKERS):
            return out
    return None


def _step_cli(opts, ctx, n, total):
    """Prove the signer, rather than prove a binary is installed.

    This stage used to look for qubic-cli and refuse to go on without it,
    which made a C++ build the price of entry. qdojo signs for itself now, so
    what is worth verifying is that the signing code produces the right bytes
    -- and that can be checked here, offline, in milliseconds, against a
    vector qubic-cli itself produced.
    """
    term.step(n, total, "THE SIGNER — qdojo signs for itself, in Python")
    try:
        got = qubic.identity_from_seed(SIGNER_CHECK_SEED)
        if got != SIGNER_CHECK_IDENTITY:
            raise WizardError(f"derived {got}, expected {SIGNER_CHECK_IDENTITY}")
        subseed, _priv, public = qubic.keys_from_seed(SIGNER_CHECK_SEED)
        signed = qubic.Transaction.to_identity(public, SIGNER_CHECK_IDENTITY,
                                               12345, 80732400).sign(subseed)
        if signed.payload() != SIGNER_CHECK_PAYLOAD:
            raise WizardError("the signature does not match the reference vector")
    except WizardError:
        term.fail("the signer is not producing the reference bytes",
                  "this build is broken; do not fight with it")
        raise
    term.ok("signer verified", "a known transaction signs to the exact bytes "
                               "qubic-cli produces")
    ctx["cli"] = opts.cli or "qubic-cli"    # only --chain cli uses it


def _step_seed(opts, ctx, n, total):
    term.step(n, total, "YOUR SEED — 55 letters that are your purse")
    conf = os.path.expanduser(opts.conf or os.path.join(opts.state, "bot.conf"))
    if os.path.exists(conf):
        term.ok("existing seed, untouched", conf)
    else:
        seed = sys.stdin.readline().strip() if opts.seed_from_stdin else None
        onboard.create_conf(conf, seed)
        term.ok("new seed created", conf)
    mode = stat.S_IMODE(os.stat(conf).st_mode)
    if mode != 0o600:
        term.fail("the seed conf is not 0600", f"{conf} is {oct(mode)} — fix it before you go on")
        raise WizardError(f"{conf} is mode {oct(mode)}, must be 0600")
    term.ok("mode 0600 confirmed", "only you can read it — back this file up")
    ctx["conf"] = conf
    ctx["identity"] = onboard.derive_identity("", conf)
    term.ok("identity derived", ctx["identity"][:12] + "…" + ctx["identity"][-6:])


def _valid_name(v):
    v = str(v).strip()
    if not v:
        return v
    try:
        payload.encode(payload.Bow(v))
    except PayloadError as e:
        raise ValueError(f"{e} — the dojo carries a name in 32 bytes")
    return v


def _step_name(opts, ctx, n, total):
    term.step(n, total, "YOUR NAME — what the dojo calls you when you bow")
    default = opts.name or (ctx.get("prof") or {}).get("name") or ""
    name = term.ask("fighter name (empty = fight unnamed)", default=default, validate=_valid_name,
                    no_input=opts.yes)
    if name:
        term.ok("name accepted", f"BOW encodes in {len(payload.encode(payload.Bow(name)))} bytes")
    else:
        term.warn("no name", "an unnamed fighter is a stranger; add one later with --name")
    ctx["name"] = name


def _step_nodes(opts, ctx, n, total):
    term.step(n, total, "THE NETWORK — live nodes that agree on the tick")
    probe = nodes.native_probe()
    if opts.node:
        ip = opts.node.partition(":")[0]
        with term.spinner(f"asking {ip} for its tick"):
            tick, _ = probe(ip)
        if not tick:
            term.fail("that node did not answer", opts.node)
            raise WizardError(f"{opts.node} gave no tick; drop --node to discover one")
        found = [{"ip": ip, "tick": tick, "lag": 0}]
    else:
        with term.spinner("probing the bootstrap nodes and every peer they name"):
            found = nodes.discover(probe)
        if not found:
            term.fail("no live Qubic node reachable", "check your network, or pass --node")
            raise WizardError("no live Qubic node reachable")
    nodes.save(opts.state, found)
    best = found[0]
    term.ok(f"node {best['ip']}", f"tick {best['tick']}, lag {best['lag']} — {len(found)} nodes agree")
    ctx["node"] = best


# ---- step 5: the mind

def _pick_provider(opts, skip_none=False):
    if opts.provider:
        key = str(opts.provider).strip().lower()
        for p in PROVIDERS:
            if p["key"] == key:
                return p
        raise WizardError(f"unknown provider {opts.provider!r}; one of {', '.join(PROVIDER_KEYS)}")
    i = term.menu("who thinks for this fighter?", [(p["label"], p["hint"]) for p in PROVIDERS],
                  default=0, no_input=opts.yes)
    return PROVIDERS[i]


def _pick_model(opts, prov):
    if not prov["models"]:
        return "", ""
    if opts.model:
        return opts.model, opts.base_url or prov["base_url"]
    options = [(m[0], m[1]) for m in prov["models"]] + [("type any model id", "paste one from the provider's list")]
    i = term.menu("which model?", options, default=0, no_input=opts.yes)
    if i < len(prov["models"]):
        mid, _, base = prov["models"][i]
        return mid, opts.base_url or (base or prov["base_url"])
    mid = term.ask("model id", default=prov["models"][0][0], no_input=opts.yes)
    return mid, opts.base_url or prov["base_url"]


def _pick_solver_kind(opts) -> dict:
    """What thinks for this fighter. Asked before any provider question."""
    want = getattr(opts, "solver_kind", None)
    if not want and opts.solver:
        want = "byo"
    if not want and opts.provider:
        want = PROVIDER_TO_SOLVER.get(opts.provider, "prompt")
    if want:
        for sv in SOLVERS:
            if sv["key"] == want:
                return sv
        raise WizardError(f"unknown solver kind {want!r}; one of {', '.join(SOLVER_KEYS)}")
    i = term.menu("what thinks for your fighter?", [(sv["label"], sv["hint"]) for sv in SOLVERS],
                  default=0, no_input=opts.yes)
    return SOLVERS[i]


def _pick_solver(opts, sv) -> list[str]:
    """The argv. For `byo` we ask, and then the probe proves their program
    satisfies the contract before a single seat is ever bought."""
    if opts.solver:
        return list(opts.solver)
    if sv["key"] != "byo":
        return solver_argv(sv["file"])
    _say("the whole contract: the riddle arrives on stdin as JSON, and the LAST line you print "
         "must be {\"answer\": ...}. Exit non-zero and the dojo records that you did not answer.")
    cmd = term.ask("the command that runs your fighter", default="python3 ./my_solver.py",
                   no_input=opts.yes)
    argv = shlex.split(cmd)
    if not argv:
        raise WizardError("no solver command given")
    return argv


def _pi_is_missing(opts, prov, why):
    term.warn("pi is not installed", f"{why}. pi.py drives it; three ways on from here.")
    options = [("use openai_compat.py", "stdlib urllib, no pi, works with this provider today"),
               ("choose none and fight the white belt today", "a plain script; buy a model out of winnings"),
               ("install pi, then re-run", "stops here so you can install it")]
    i = term.menu("how do you want to go on?", options, default=0, no_input=opts.yes)
    if i == 0:
        return solver_argv("openai_compat.py"), "openai_compat"
    if i == 1:
        return solver_argv("echo.py"), "echo"
    print()
    _say("install pi, then run `qdojo bot setup` again:")
    print("    " + term.c("# TODO: pi's own install command — qdojo will not invent an install URL for you.", "dim"))
    print("    " + term.c("#        see pi's README; then: qdojo bot setup", "dim"))
    raise WizardError("pi is not installed; install it and re-run `qdojo bot setup`")


def _step_model(opts, ctx, n, total):
    term.step(n, total, "YOUR MIND — who thinks for this fighter, and does it work")
    sv = _pick_solver_kind(opts)
    term.ok(sv["label"].split(" — ")[0])
    _say(sv["how_to"])
    solver = _pick_solver(opts, sv)
    kind = {"bare": "echo", "byo": "byo"}.get(sv["key"], "openai_compat")
    if sv["key"] == "byo":
        kind = ("pi" if any("pi.py" in a for a in solver) else
                "echo" if any(x in a for a in solver for x in ("echo.py", "bare.py")) else
                "openai_compat" if any("openai_compat" in a or "prompted" in a for a in solver) else "byo")

    if sv["needs_model"] or (kind in ("pi", "openai_compat")):
        prov = _pick_provider(opts, skip_none=True)
        term.ok(prov["label"])
        _say(prov["how_to"])
        model, base = _pick_model(opts, prov)
    else:
        prov, model, base = PROVIDERS[0], "", ""

    env, key_env = {}, (opts.key_env or prov["key_env"])
    if kind == "pi":
        env["PI_MODEL"] = model
        key_source = "pi"                            # pi holds its own credentials; qdojo never sees them
    elif kind == "openai_compat":
        env["OPENAI_MODEL"] = model
        env["OPENAI_BASE_URL"] = base
        key_source = f"env:{key_env}" if key_env else "none"
        if sv["key"] == "prompt":
            # Not a secret, so it rides in solver_env: check_no_secrets is happy
            # with the name, _bot_defaults merges it, and run_command_text then
            # prints the prompts path right there in the ready-to-run line.
            installed = prompts.install(opts.state)
            env["QDOJO_PROMPTS"] = os.path.join(os.path.abspath(os.path.expanduser(opts.state)), "prompts")
            if installed:
                term.ok("your prompts", f"{len(installed)} file(s) copied to {env['QDOJO_PROMPTS']} — edit them, "
                                        f"the next round uses them")
            else:
                term.ok("your prompts", env["QDOJO_PROMPTS"])
    else:
        key_source, key_env = "none", ""
    env.update(parse_env(opts.env))
    check_no_secrets(env)

    if model:
        term.ok("model", model + (f"  via {base}" if base and kind == "openai_compat" else ""))
    else:
        term.ok("model", "none — a plain script, and it wins the arithmetic belts")
    term.ok("solver", " ".join(os.path.basename(a) for a in solver))
    if key_env:
        if os.environ.get(key_env):
            term.ok(f"key in ${key_env}", "present in this shell — qdojo reads it, never writes it")
        else:
            term.warn(f"${key_env} is not set", "export it in your shell before you run; the probe below will say so")
    term.info("qdojo stores", f"key_source = {key_source}  (the name of the place, never the key)")

    ctx.update(provider=prov["key"], model=model, solver=solver, solver_env=env, key_source=key_source,
               solver_kind=kind, base_url=base)

    if opts.skip_probe:
        term.warn("test riddle skipped", "--skip-probe: nothing below has been proven to work")
        ctx["probe_ok"] = None
        return
    probe_env = dict(env)
    # In-process only, never written: point openai_compat at whichever variable
    # actually holds this user's key.
    if kind == "openai_compat" and key_env and key_env not in ("OPENAI_API_KEY", "OPENROUTER_API_KEY"):
        if os.environ.get(key_env):
            probe_env["OPENAI_API_KEY"] = os.environ[key_env]
    with term.spinner(f"one test riddle through the real code path: {TEST_RIDDLE['title']}"):
        passed, msg, _took = probe_model(solver, probe_env, timeout=opts.probe_timeout)
    ctx["probe_ok"], ctx["probe_msg"] = passed, msg
    if passed:
        term.ok("the test riddle is solved", msg)
    else:
        term.fail("the test riddle was NOT solved", msg)
        _say("That message is the diagnosis, verbatim from the solver. Fix it and run `qdojo bot setup` again — "
             "the seed and identity below are already safe either way.")


# ---- step 6: the purse

def _seat_fee(opts) -> int:
    if opts.seat_fee:
        return int(opts.seat_fee)
    if opts.board:
        try:
            from .bot import fetch_board
            fees = [int(r["entry_fee"]) for r in fetch_board(opts.board).get("rounds", []) if r.get("entry_fee")]
            if fees:
                return min(fees)
        except Exception:       # a nicety, never a decision: fall back to the default
            pass
    return DEFAULT_SEAT


def _ensure_chain(opts, ctx):
    if ctx.get("node"):
        return
    if opts.node:
        ip = opts.node.partition(":")[0]
        tick, _ = nodes.native_probe()(ip)
        ctx["node"] = {"ip": ip, "tick": tick or 0, "lag": 0}
        return
    cached = nodes.load(opts.state)
    if cached:
        ctx["node"] = cached[0]
        return
    with term.spinner("probing the bootstrap nodes and every peer they name"):
        found = nodes.discover(nodes.native_probe())
    if not found:
        raise WizardError("no live Qubic node reachable")
    nodes.save(opts.state, found)
    ctx["node"] = found[0]


def _step_purse(opts, ctx, n, total):
    term.step(n, total, "YOUR PURSE — what you can actually pay a seat with")
    _ensure_chain(opts, ctx)
    seat = _seat_fee(opts)
    ctx["seat"] = seat
    ip, _, port = str(ctx["node"]["ip"]).partition(":")
    bal = None
    try:
        chain = NativeChain(ip, int(port or nodes.PORT), identity=ctx["identity"])
        with term.spinner(f"reading the balance of {ctx['identity'][:8]}… from {ip}"):
            bal = chain.balance(ctx["identity"])
    except (Unknown, ChainError, ValueError, OSError) as e:
        term.warn("balance unknown", f"{e}")
        _say("An unknown is not a zero. Read it again before you fund anything, and never treat this as empty.")
    ctx["balance"] = bal
    if bal is None:
        pass
    elif bal >= seat:
        term.ok("purse", f"{term.qu(bal)} — {bal // seat} seats at {term.qu(seat)}")
    elif bal > 0:
        term.warn("purse", f"{term.qu(bal)} — a first seat costs {term.qu(seat)}; top it up below")
    else:
        term.warn("purse", f"empty — fund the identity below with at least {term.qu(seat)}")


# ----------------------------------------------------------------- the card

def _how_reached(ctx) -> str:
    kind = ctx.get("solver_kind") or ""
    if kind == "pi":
        return "pi, with pi's own credentials"
    if kind == "openai_compat":
        return f"{ctx.get('base_url') or 'an OpenAI-compatible endpoint'} via openai_compat.py"
    return "no network at all"


def _card(opts, ctx, prof) -> None:
    node = ctx.get("node") or {}
    probe = ctx.get("probe_ok")
    model = prof.get("model") or "none — a plain script"
    if probe is False:
        model += "   " + term.c("UNPROVEN", "bred", "bold")
    rows = [
        term.kv("fighter", prof.get("name") or term.c("unnamed — you have not bowed", "dim")),
        term.kv("belt", term.belt("white") + term.c("   everyone starts here", "dim")),
        term.kv("purse", term.qu(ctx.get("balance")) + term.c(f"   seat {term.qu(ctx.get('seat', DEFAULT_SEAT))}",
                                                             "dim")),
        term.kv("seed", prof.get("conf", "")),
        term.kv("", term.c("0600 — back this up. Lose it and the purse is gone.", "byellow")),
        term.kv("node", f"{node.get('ip', '?')}" + term.c(f"   lag {node.get('lag', '?')}", "dim")),
        term.kv("model", model),
        term.kv("reached", _how_reached(ctx)),
        term.kv("key", prof.get("key_source", "none") + term.c("   qdojo never stores it", "dim")),
        term.kv("solver", " ".join(os.path.basename(a) for a in (prof.get("solver") or [])) or "—"),
    ]
    print()
    print(term.box(rows, title="YOUR FIGHTER"))
    print()
    print(term.c("  identity — fund this, it is 60 characters and copy-pasteable:", "dim"))
    print("  " + term.c(prof.get("identity", ""), "bcyan", "bold"))
    print()
    print(term.c("  when it is funded, fight:", "dim"))
    for line in run_command_text(prof, opts.board or DEFAULT_BOARD).splitlines():
        print("  " + line)
    print()
    print(term.rule("BOW IN"))


# ------------------------------------------------------------ entry points

def _open(opts):
    if opts.color is not None:
        term.set_enabled(bool(opts.color))
    print(term.banner())


def init(args_like=None, **kw) -> dict:
    """The full rite: signer, seed, name, network, mind, purse. Returns the
    saved profile (exactly PROFILE_KEYS). Every choice can be supplied, so it
    runs non-interactively; with `no_setup=True` it stops after the network
    step and keeps whatever provider the profile already had."""
    opts = _opts(args_like, **kw)
    _open(opts)
    ctx = {"prof": load_profile(opts.state)}
    steps = [_step_cli, _step_seed, _step_name, _step_nodes]
    if not opts.no_setup:
        steps += [_step_model, _step_purse]
    for i, fn in enumerate(steps, 1):
        fn(opts, ctx, i, len(steps))
    prof = _profile(ctx)
    onboard.save_profile(opts.state, prof)
    _card(opts, ctx, prof)
    return prof


def setup(args_like=None, **kw) -> dict:
    """The provider/model rite on its own, against an identity that already
    exists. Returns the saved profile (exactly PROFILE_KEYS)."""
    opts = _opts(args_like, **kw)
    prof = load_profile(opts.state)
    if not prof.get("identity") or not prof.get("conf"):
        raise WizardError(f"no bot profile in {opts.state}; run `qdojo bot init` first")
    _open(opts)
    ctx = {"prof": prof, "conf": prof["conf"], "identity": prof["identity"],
           "name": opts.name or prof.get("name") or ""}
    steps = [_step_model, _step_purse]
    for i, fn in enumerate(steps, 1):
        fn(opts, ctx, i, len(steps))
    out = _profile(ctx)
    onboard.save_profile(opts.state, out)
    _card(opts, ctx, out)
    return out
