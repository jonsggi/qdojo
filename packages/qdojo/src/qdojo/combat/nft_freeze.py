"""`qdojo combat nft ...`: freeze, verify and inspect fighter NFTs (docs/nft.md §7).

  qdojo combat nft freeze --arena ~/.qdojo/combat/arena --export DIR --out apps/web/data/nft/v1
  qdojo combat nft freeze --tokens tokens.json --out DIR
  qdojo combat nft verify DIR
  qdojo combat nft show --arena ~/.qdojo/combat/arena [FIGHTER_ID]

`freeze` renders every token's art with apps/web/avatars.js through
scripts/nft-freeze.cjs (node, no dependencies): card and sprite SVG, 16x
lossless PNG masters, metadata JSON, all content-addressed by SHA-256, and a
manifest with a root hash. `verify` checks a frozen set against the current
renderer. The arena is read, never written: its journal is replayed into a
private copy (readmodel.Replica), exactly as the read model does.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]           # the repository (packages/qdojo/src/qdojo/combat/..)
SCRIPT = ROOT / "scripts" / "nft-freeze.cjs"
AVATARS = ROOT / "apps" / "web" / "avatars.js"
SITE = "https://qdojo.jonsggi.com/combat.html"


def replay_ledger(devnet_dir: Path):
    """The arena's NFT ledger, rebuilt read-only from its journal."""
    from . import readmodel as rm
    rep = rm.Replica(rm.manifest_for(devnet_dir))
    with open(Path(devnet_dir) / rm.JOURNAL, "rb") as f:
        for line in f:
            if line.endswith(b"\n") and line.strip():
                rep.apply(json.loads(line))
    return rep.nft


def names_from_export(export_dir: Path | None) -> dict:
    if not export_dir:
        return {}
    try:
        return json.loads((Path(export_dir) / "index.json").read_text()).get("names") or {}
    except (OSError, ValueError):
        return {}


def tokens_doc(ledger, names: dict, site: str = SITE) -> dict:
    return {"collection": {"name": "QDOJO fighters", "issuer": ledger.issuer.hex() if ledger.issuer else None,
                           "asset_prefix": ledger.policy.name_prefix},
            "site": site,
            "tokens": [{"fighter_id": f.hex(), "serial": t.serial, "name": t.name, "fighter_name": names.get(f.hex()),
                        "issuer": t.issuer.hex(), "founding": t.founding, "creator": t.creator.hex()}
                       for f, t in sorted(ledger.tokens.items(), key=lambda kv: kv[1].serial)]}


def _node(*args) -> int:
    node = shutil.which("node")
    if node is None:
        raise SystemExit("qdojo: the freeze needs node (any recent version; no packages)")
    return subprocess.run([node, str(SCRIPT), *args]).returncode


def freeze(tokens: dict, out: Path, avatars: Path = AVATARS) -> int:
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(tokens, f)
    try:
        return _node("freeze", "--tokens", f.name, "--out", str(out), "--avatars", str(avatars))
    finally:
        Path(f.name).unlink(missing_ok=True)


def verify(out: Path, avatars: Path = AVATARS) -> int:
    return _node("verify", "--out", str(out), "--avatars", str(avatars))


def cmd_freeze(a):
    if a.tokens:
        doc = json.loads(Path(a.tokens).read_text())
    elif a.arena:
        doc = tokens_doc(replay_ledger(Path(a.arena)), names_from_export(a.export), a.site)
    else:
        raise SystemExit("qdojo: give --arena DIR (the arena's journal) or --tokens FILE")
    if not doc["tokens"]:
        raise SystemExit("qdojo: no tokens to freeze")
    sys.exit(freeze(doc, Path(a.out), Path(a.avatars)))


def cmd_verify(a):
    sys.exit(verify(Path(a.dir), Path(a.avatars)))


def cmd_show(a):
    led = replay_ledger(Path(a.arena))
    if a.fighter:
        fid = bytes.fromhex(a.fighter)
        doc = led.token_doc(fid)
        if doc is None:
            raise SystemExit("qdojo: no token for that fighter")
        doc = {**doc, "book": led.book_doc(fid), "history": led.history_doc(fid)}
    else:
        doc = {"stats": led.stats(), "policy": vars(led.policy),
               "tokens": [led.token_doc(f) for f in sorted(led.tokens, key=lambda f: led.tokens[f].serial)]}
    print(json.dumps(doc, indent=1, default=str))


def add_parser(s):
    p = s.add_parser("nft", help="fighter NFTs: freeze art and metadata, verify a frozen set, inspect the ledger")
    sub = p.add_subparsers(dest="nft_cmd", required=True)
    d = sub.add_parser("freeze", help="render, hash and store every token's art and metadata (AUD-009)")
    d.add_argument("--out", required=True, help="output directory (objects/ and manifest.json)")
    d.add_argument("--arena", help="an arena directory: its journal is replayed read-only for the token list")
    d.add_argument("--export", help="the arena's public export, for fighter names")
    d.add_argument("--tokens", help="or a tokens.json (see scripts/nft-freeze.cjs)")
    d.add_argument("--site", default=SITE, help="the page the metadata's external_url points at")
    d.add_argument("--avatars", default=str(AVATARS), help="the renderer (default: apps/web/avatars.js)")
    d.set_defaults(fn=cmd_freeze)
    d = sub.add_parser("verify", help="check a frozen set against the renderer and its own hashes")
    d.add_argument("dir")
    d.add_argument("--avatars", default=str(AVATARS))
    d.set_defaults(fn=cmd_verify)
    d = sub.add_parser("show", help="the arena's NFT ledger (read-only replay of its journal)")
    d.add_argument("--arena", required=True)
    d.add_argument("fighter", nargs="?")
    d.set_defaults(fn=cmd_show)
