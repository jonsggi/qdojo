"""Every qdojo command line we publish must actually parse.

Two commands shipped broken because nothing checked this: `qdojo bot init
--full` (no such flag) appeared in the README twice, in docs/api.md and three
times in llms.txt -- which is signed on chain, so the signed briefing told a
coding agent to run a command that fails. And `qdojo doc verify FILE --node IP`
put a top-level flag after a subcommand, which argparse will not take.

Documentation that does not parse is a bug. This test is the fence, and it
feeds the lines to the REAL parser rather than modelling argparse in a regex:
a regex model would itself drift, and it could never catch the second bug,
which is about a flag's position rather than its name.
"""
import os
import re
import shlex

import pytest

from qdojo.cli import build_parser

ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "..")
# The prose surfaces, where a command sits in a fenced block and means exactly
# what it says. apps/web/app.js is NOT here on purpose: its commands live
# inside escaped JS template literals, and regexing those back out produces
# artefacts ("\\`)", "</span>,"). The page is covered by
# apps/web/tests/setup.test.cjs, which evaluates the literal in a vm instead --
# the same trick help.test.cjs uses for HELP. Python reads markdown; node reads
# JavaScript; neither guesses at the other's escaping.
# Archived examples still document the supported legacy implementation.
# Active combat commands are explicitly planned until their parser exists.
SURFACES = ["README.md", "docs/api.md", "docs/protocol.md", "docs/riddle-pack.md", "apps/web/llms.txt"]
SURFACES += ["docs/archive/riddle-v0/" + path for path in SURFACES]

# A published line is written for a human and carries placeholders. Each one is
# spelled out here on purpose: an unrecognised placeholder FAILS rather than
# being quietly dropped, so nobody can sneak a new bit of hand-waving past.
# Angle-bracket and ellipsis forms: unambiguous, replaced as substrings because
# they appear inside larger tokens ("<origin>/data/board.json").
ANGLE = {
    "<board url>": "https://x/data/board.json", "<your solver>": "./s.py",
    "<origin>": "https://x", "<any live node>": "1.2.3.4", "<ip>": "1.2.3.4",
    "<house>": "https://x", "<the repository>": "https://x/r.git", "<repo>": "https://x/r.git",
    "<id>": "1", "<url>": "https://x", "<n>": "1", "<name>": "N", "<path>": "./p",
    "<data>": "./d", "<tmp>": "./d", "<board>": "https://x/data/board.json",
    "...": "", "…": "",
}
# Bare uppercase synopsis names: replaced only as a WHOLE token.
BARE = {
    "ID": "1", "N": "1", "S": "1", "URL": "https://x", "FILE": "./f.md", "PATH": "./p",
    "NAME": "N", "CMD": "./c", "IP": "1.2.3.4", "ASSET": "A", "COUNT": "1", "AMOUNT": "1",
    "DIR": "./d", "B": "white", "TICK-TICK": "1-2", "NAME=VALUE": "A=B", "KEY": "K",
    "NAME=IDENTITY": "A=B", "NAME=MODEL": "A=B", "VALUE": "v", "flags": "",
}
PLACEHOLDER_RE = re.compile(r"<[^>\s][^>]*>")

# The top-level subcommands. Requiring one of these immediately after `qdojo`
# is what separates an invocation from a domain tag ("qdojo/answer/v0") or a
# path ("qdojo/data/"), which are all over the protocol docs.
VERBS = ("payload", "doc", "riddle", "house", "bot")
FENCE = re.compile(r"^\s*```")


def _lines(text, fenced_only):
    """Every `qdojo <verb> …` invocation, continuations joined.

    `fenced_only` restricts markdown to fenced code blocks: a command named
    inside a sentence is illustrative prose, and reading it as an invocation is
    how the extractor starts failing on its own documentation.
    """
    out, buf, inside = [], "", not fenced_only
    for raw in text.splitlines():
        if fenced_only and FENCE.match(raw):
            inside = not inside
            continue
        if not inside:
            continue
        line = raw.strip().strip("`'\"")
        if buf:
            buf += " " + line.rstrip("\\").strip()
            if not line.endswith("\\"):
                out.append(buf); buf = ""
            continue
        m = re.search(r"\b((?:uv run )?qdojo\s+(?:%s)\b.*)$" % "|".join(VERBS), line)
        if not m:
            continue
        cmd = m.group(1).strip()
        cmd = re.split(r"\s{2,}", cmd)[0]      # a synopsis table's description column
        cmd = cmd.rstrip("`\"';.")
        if cmd.endswith("\\"):
            buf = cmd.rstrip("\\").strip()
        else:
            out.append(cmd)
    return out


def _tokens(cmd):
    """Tokenise FIRST, then substitute.

    Substituting into the raw string is a trap: a bare one-letter placeholder
    like B matched inside `bot` and turned it into `whiteot`. Angle-bracket
    forms are unambiguous and are replaced as substrings; bare uppercase names
    only ever replace a WHOLE token.
    """
    cmd = re.sub(r"\s+#.*$", "", cmd)                  # a trailing shell comment
    cmd = cmd.replace("[", "").replace("]", "")       # a synopsis' optional markers
    cmd = re.sub(r"\s+\|\s+", " ", cmd)               # "--tick N | --round N"
    cmd = re.sub(r"^\s*(?:uv run\s+)?qdojo\s*", "", cmd)
    cmd = re.sub(r"\$\{?[A-Za-z_][A-Za-z0-9_]*\}?", "V", cmd)   # $VAR / ${VAR}
    unknown = [x for x in PLACEHOLDER_RE.findall(cmd) if x.lower() not in ANGLE]
    assert not unknown, f"unknown placeholder {unknown} in: {cmd}\nadd it to ANGLE"
    for k, v in sorted(ANGLE.items(), key=lambda kv: -len(kv[0])):
        cmd = re.sub(re.escape(k), v, cmd, flags=re.I)
    out = []
    for tok in shlex.split(cmd):
        tok = BARE.get(tok, tok)
        if tok:                       # a placeholder that maps to nothing, e.g. "flags"
            out.append(tok)
    return out


def published():
    for rel in SURFACES:
        path = os.path.join(ROOT, rel)
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            for cmd in _lines(f.read(), fenced_only=rel.endswith(".md") or rel.endswith(".txt")):
                yield rel, cmd


ALL = sorted(set(published()))


def test_we_actually_found_the_published_commands():
    """A silent extraction failure would make every other test here vacuous."""
    assert len(ALL) >= 15, f"only found {len(ALL)}; the extractor is broken"
    assert {rel for rel, _ in ALL} >= {"README.md", "apps/web/llms.txt"}


@pytest.mark.parametrize("rel,cmd", ALL, ids=lambda x: x if isinstance(x, str) else None)
def test_every_published_command_parses(rel, cmd):
    tokens = _tokens(cmd)
    if not tokens:
        return
    try:
        build_parser().parse_args(tokens)
    except SystemExit as exc:
        # argparse deliberately exits successfully when displaying requested help.
        if exc.code == 0 and any(token in ("--help", "-h") for token in tokens):
            return
        pytest.fail(f"{rel} publishes a command the CLI rejects:\n    qdojo {' '.join(tokens)}\n"
                    f"  as written: {cmd}")


def test_full_is_accepted_because_we_published_it():
    """Named for the bug. `--full` was in five places including the on-chain
    signed llms.txt; honouring it was cheaper than re-signing to remove it."""
    a = build_parser().parse_args(["bot", "init", "--full"])
    assert a.no_setup is False
    assert build_parser().parse_args(["bot", "init", "--no-setup"]).no_setup is True


def test_doc_verify_takes_node_after_the_subcommand():
    """Named for the bug. argparse will not take a parent option after a
    subcommand, and `doc verify FILE --node IP` is the form we published."""
    assert build_parser().parse_args(["doc", "verify", "f.md", "--node", "1.2.3.4"]).node == "1.2.3.4"
    assert build_parser().parse_args(["--node", "1.2.3.4", "doc", "verify", "f.md"]).node == "1.2.3.4"
