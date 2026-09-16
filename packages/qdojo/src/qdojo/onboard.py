"""First-run setup for a bot: a seed conf that exists nowhere else, the identity
it derives to, and the node it will talk to."""
import json
import os
import secrets
import shutil
import string
import subprocess

from .chain.cli import check_seed_conf

SEED_ALPHABET = string.ascii_lowercase
SEED_LEN = 55


class OnboardError(Exception):
    pass


def find_cli(explicit: str | None = None) -> str:
    for cand in ([explicit] if explicit else []) + [os.environ.get("QUBIC_CLI"), "qubic-cli",
                                                    os.path.expanduser("~/.qdojo/qubic-cli")]:
        if cand and (shutil.which(cand) or os.access(cand, os.X_OK)):
            return shutil.which(cand) or cand
    raise OnboardError("qubic-cli not found: build it with scripts/build-qubic-cli.sh or pass --cli")


def new_seed(rng=secrets) -> str:
    return "".join(rng.choice(SEED_ALPHABET) for _ in range(SEED_LEN))


def create_conf(path: str, seed: str | None = None) -> str:
    """Write a 0600 conf with one seed= line. Refuses to overwrite: a seed that
    exists must never be silently replaced."""
    path = os.path.expanduser(path)
    if os.path.exists(path):
        raise OnboardError(f"{path} already exists; not overwriting a seed")
    os.makedirs(os.path.dirname(path) or ".", mode=0o700, exist_ok=True)
    seed = seed or new_seed()
    if len(seed) != SEED_LEN or not seed.isalpha() or not seed.islower():
        raise OnboardError("a seed is exactly 55 lowercase letters a-z")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(f"seed={seed}\n")
    check_seed_conf(path)
    return path


def derive_identity(cli: str, conf: str, timeout: float = 20.0) -> str:
    """The identity a conf signs as, from qubic-cli -showkeys. Only the
    Identity line is read; the private key it also prints is discarded."""
    check_seed_conf(conf)
    try:
        out = subprocess.run([cli, "-conf", conf, "-showkeys"], capture_output=True, text=True, timeout=timeout).stdout
    except (subprocess.TimeoutExpired, OSError) as e:
        raise OnboardError(f"qubic-cli -showkeys failed: {e}")
    for line in out.splitlines():
        if line.startswith("Identity: "):
            idn = line.split(": ", 1)[1].strip()
            if len(idn) == 60 and idn.isupper():
                return idn
    raise OnboardError("could not derive an identity from the conf")


def profile_path(state_dir: str) -> str:
    return os.path.join(state_dir, "bot.json")


def save_profile(state_dir: str, profile: dict) -> None:
    """0600 like the seed conf beside it. No secret is in here -- qdojo never
    stores a key -- but it carries the identity, the provider and the model, and
    there is no reason for the rest of the box to read them."""
    os.makedirs(state_dir, mode=0o700, exist_ok=True)
    path = profile_path(state_dir)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(profile, f, indent=2)
    os.chmod(path, 0o600)


def load_profile(state_dir: str) -> dict:
    try:
        with open(profile_path(state_dir), encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return {}
