"""Contract and docs sync check: the contract and the docs must never drift.

Run by `make test` (packages/qdojo/tests/test_contract_sync.py) and on its own:

    python3 docs/reference/check_sync.py

The reference is the Python contract (packages/qdojo/src/qdojo/combat/:
codec.py, contract.py, rules.py, devnet.py, nft.py, live.py). Every other copy
is compared with it:

  1. opcodes      codec.Op + codec.BODIES  vs  docs/protocol.md §3 table, the
                  C++ port (contracts/combat_contract/combat_contract.h) and
                  contracts/qubic/QDOJO.h: numbers, names, field names and
                  widths (the doc), body lengths (both C++ files), a handler
                  wired for each opcode, the admin range in protocol.md;
                  "Name (opcode N)" mentions anywhere in the active docs
  2. event types  contract.EVENT_TYPES  vs  docs/protocol.md §6 table and both
                  C++ files (numbers, names, an emit site for each)
  3. result codes codec.Code  vs  docs/protocol.md §6 table and both C++ files
  4. v1 ABI       QDOJO.h REGISTER_USER_* IDs  vs  docs/protocol.md §1 table,
                  contracts/qubic/README.md queries table, join.INPUT_TYPE
  5. rulesets     docs/combat-v1*.json and rules.KNOWN digests  vs
                  contracts/combat_core/combat_core.h tables, QDOJO.h's ruleset
                  functions (compiled natively and evaluated), apps/web/combat/
                  ruleset.js, digests named in docs/combat.md, llms.txt and
                  QDOJO.h comments (docs/reference/check_docs.py checks the
                  combat.md matrices)
  6. manifest     QDOJO.h's compiled-in manifest  vs  devnet.PROFILES["demo-c3"]
                  and the test identities, the capacities of both C++ files,
                  and the values README.md, testnet.md, protocol.md, combat.md
                  and llms.txt state
  7. NFT          docs/nft.md backends and ownership-opcode table  vs
                  nft.make_backend, live.NFT_BACKENDS, the code that sends
                  each opcode, codec.MIRROR_SOURCES and both C++ files

C++ is read with simple regexes over regions marked `// sync:begin NAME` ...
`// sync:end NAME`; Markdown tables are marked `<!-- sync:begin NAME -->` ...
`<!-- sync:end NAME -->`. Each error names the file, the table and the value.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages/qdojo/src"))
sys.path.insert(0, str(ROOT / "packages/qdojo/tests"))

PORT = "contracts/combat_contract/combat_contract.h"
QDOJO = "contracts/qubic/QDOJO.h"
CORE = "contracts/combat_core/combat_core.h"
PROTOCOL = "docs/protocol.md"
README = "contracts/qubic/README.md"
NFT_MD = "docs/nft.md"
LLMS = "apps/web/llms.txt"
RULESET_FILES = {"combat-v1-candidate-1": "docs/combat-v1.json", "combat-v1-candidate-2": "docs/combat-v1-candidate-2.json",
                 "combat-v1-candidate-3": "docs/combat-v1-candidate-3.json"}

errors: list[str] = []
notes: list[str] = []


def fail(where: str, what: str):
    errors.append(f"{where}: {what}")


def text(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def flat(s: str) -> str:
    """Whitespace collapsed (prose regexes must survive re-wrapping)."""
    return re.sub(r"\s+", " ", s)


def region(rel: str, name: str) -> str:
    """The text between the sync markers NAME of a C++ or Markdown file."""
    s = text(rel)
    m = re.search(r"sync:begin " + re.escape(name) + r"\b[^\n]*\n(.*?)\n[^\n]*sync:end " + re.escape(name) + r"\b",
                  s, re.S)
    if not m:
        fail(rel, f"no region marked 'sync:begin {name}' ... 'sync:end {name}'")
        return ""
    return m.group(1)


def table_rows(md: str) -> list[list[str]]:
    rows = []
    for line in md.splitlines():
        line = line.strip()
        if not line.startswith("|") or re.match(r"^\|[\s:|-]+\|$", line):
            continue
        rows.append([c.strip() for c in line.strip("|").split("|")])
    return rows[1:]                                     # without the header row


def numbered(where: str, pairs) -> dict[int, str]:
    out: dict[int, str] = {}
    for name, num in pairs:
        num = int(num, 0)
        if num in out:
            fail(where, f"number {num} appears twice ({out[num]}, {name})")
        out[num] = name
    return out


def compare(what: str, ref: dict[int, str], where: str, got: dict[int, str], ref_name: str):
    for num in sorted(set(ref) | set(got)):
        if num not in got:
            fail(where, f"{what} {num} {ref[num]} is missing ({ref_name} has it)")
        elif num not in ref:
            fail(where, f"{what} {num} {got[num]} is not in {ref_name}")
        elif got[num] != ref[num]:
            fail(where, f"{what} {num} is named {got[num]}, {ref_name} says {ref[num]}")


def snake(camel: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", camel).upper()


def cpp_sum(expr: str) -> int:
    return sum(int(x) for x in re.findall(r"\d+", expr))


# ---- 1. opcodes ------------------------------------------------------------------------------

def check_opcodes():
    from qdojo.combat import codec
    ref = {int(op): op.name for op in codec.Op}
    widths = {}
    for op, fields in codec.BODIES.items():
        widths[int(op)] = [(n, 32 if w == "id" else 7 if w == "plan" else w) for n, w in fields]
    ref_len = {k: sum(w for _, w in v) for k, v in widths.items()}

    # protocol.md §3: | opcode | CamelName | body |
    doc, rows = {}, table_rows(region(PROTOCOL, "opcodes"))
    for r in rows:
        if len(r) != 3 or not r[0].isdigit():
            fail(f"{PROTOCOL} opcodes table", f"unexpected row {r}")
            continue
        num = int(r[0])
        doc[num] = snake(r[1])
        fields = []
        if r[2] != "empty":
            for part in (p.strip() for p in r[2].split(",")):
                m = re.fullmatch(r"(\w+)\[(\d+)\]", part) or re.fullmatch(r"(\w+) u(8|16|32|64)", part)
                if not m:
                    fail(f"{PROTOCOL} opcodes table", f"opcode {num}: cannot read field '{part}'")
                    continue
                size = int(m.group(2)) if "[" in part else int(m.group(2)) // 8
                fields.append((m.group(1), size))
        if num in widths and fields != widths[num]:
            fail(f"{PROTOCOL} opcodes table", f"opcode {num} {r[1]} body is {fields}, codec.BODIES says {widths[num]}")
    compare("opcode", ref, f"{PROTOCOL} opcodes table", doc, "codec.Op")

    # Both C++ files: the numbers, the body lengths, a handler for each.
    for rel, prefix in ((PORT, "OP_"), (QDOJO, "QDOJO_OP_")):
        got = numbered(rel, re.findall(r"\b" + prefix + r"([A-Z_]+)\s*=\s*(\d+)", region(rel, "opcodes")))
        compare("opcode", ref, f"{rel} opcodes", got, "codec.Op")
        lens = {name: cpp_sum(expr) for name, expr in
                re.findall(r"case\s+" + prefix + r"([A-Z_]+):\s*return\s+([\d\s+]+);", region(rel, "body-lengths"))}
        src = text(rel)
        for num, name in ref.items():
            if name not in lens:
                fail(f"{rel} body-lengths", f"no body length for opcode {num} {name}")
            elif lens[name] != ref_len[num]:
                fail(f"{rel} body-lengths", f"opcode {num} {name} body is {lens[name]} bytes, codec.BODIES says "
                                            f"{ref_len[num]}")
            rest = src.replace(region(rel, "opcodes"), "").replace(region(rel, "body-lengths"), "")
            if not re.search(r"\b" + prefix + name + r"\b", rest):
                fail(rel, f"opcode {num} {name} has a body length but no handler (dispatch never names it)")

    # Frame constants.
    for rel, names in ((PORT, ("FRAME_LEN", "FRAME_HEADER", "FRAME_SENTINEL")),
                       (QDOJO, ("QDOJO_FRAME_LEN", "QDOJO_FRAME_HEADER", "QDOJO_FRAME_SENTINEL", "QDOJO_MAX_BODY"))):
        src = text(rel)
        for n in names:
            m = re.search(r"\b" + n + r"\s*=\s*(0x[0-9A-Fa-f]+|\d+)", src)
            want = getattr(codec, n.replace("QDOJO_", ""))
            if not m or int(m.group(1), 0) != want:
                fail(rel, f"{n} is {m.group(1) if m else 'missing'}, codec.{n.replace('QDOJO_', '')} is {want}")
    m = re.search(r"\| 16 \| 2 \| body length, 0\.\.(\d+) \|", text(PROTOCOL))
    if not m or int(m.group(1)) != codec.MAX_BODY:
        fail(f"{PROTOCOL} §1 frame table", f"body length bound is {m.group(1) if m else 'missing'}, "
                                          f"codec.MAX_BODY is {codec.MAX_BODY}")

    # The admin range.
    admin = sorted(n for n in ref if n >= 100)
    m = re.search(r"Opcodes (\d+)[–-](\d+) are accepted only from the manifest's admin", flat(text(PROTOCOL)))
    if not m or (int(m.group(1)), int(m.group(2))) != (admin[0], admin[-1]):
        fail(f"{PROTOCOL} §3", f"states admin opcodes {m.groups() if m else 'nowhere'}, codec has {admin[0]}–{admin[-1]}")

    # "AdminBindAsset (103)", "AdminMirrorOwner (opcode 104)", "opcode 104 AdminMirrorOwner" anywhere.
    camel = {"".join(w.capitalize() for w in name.split("_")): num for num, name in ref.items()}
    names = "|".join(sorted(camel, key=len, reverse=True))
    pat_a = re.compile(r"\b(" + names + r")\s*\((?:opcode\s*)?(\d{1,3})\)")
    pat_b = re.compile(r"\bopcode\s+(\d{1,3}),?\s*\(?`?(" + names + r")\b")
    for rel in active_docs():
        body = flat(text(rel))
        for name, num in pat_a.findall(body):
            if int(num) != camel[name]:
                fail(rel, f"says {name} ({num}); codec.Op has {name} = {camel[name]}")
        for num, name in pat_b.findall(body):
            if int(num) != camel[name]:
                fail(rel, f"says opcode {num} {name}; codec.Op has {name} = {camel[name]}")


def active_docs() -> list[str]:
    out = [p.relative_to(ROOT).as_posix() for p in sorted((ROOT / "docs").glob("*.md"))]
    out += ["README.md", LLMS, README, "contracts/combat_contract/README.md"]
    return out


# ---- 2. event types --------------------------------------------------------------------------

def check_events():
    from qdojo.combat import contract
    ref = {num: name for name, num in contract.EVENT_TYPES.items()}
    doc = {}
    for r in table_rows(region(PROTOCOL, "event-types")):
        if len(r) < 2 or not r[0].isdigit():
            fail(f"{PROTOCOL} event-types table", f"unexpected row {r}")
            continue
        doc[int(r[0])] = r[1].strip("`")
    compare("event type", ref, f"{PROTOCOL} event-types table", doc, "contract.EVENT_TYPES")
    py = text("packages/qdojo/src/qdojo/combat/contract.py")
    for rel, prefix, emit in ((PORT, "EV_", r"emit\(s,\s*EV_{}\b"), (QDOJO, "QDOJO_EV_", r"emit\(s,\s*c,\s*QDOJO_EV_{}\b")):
        got = numbered(rel, re.findall(r"\b" + prefix + r"([A-Z_]+)\s*=\s*(\d+)", region(rel, "event-types")))
        compare("event type", ref, f"{rel} event-types", got, "contract.EVENT_TYPES")
        src = text(rel)
        for num, name in ref.items():
            if name in got.values() and not re.search(emit.format(name), src):
                fail(rel, f"event type {num} {name} is defined but never emitted")
    for num, name in ref.items():
        if not re.search(r'_emit\(\s*"' + name + '"', py):
            fail("packages/qdojo/src/qdojo/combat/contract.py", f"event type {num} {name} is never emitted")


# ---- 3. result codes -------------------------------------------------------------------------

def check_codes():
    from qdojo.combat import codec
    ref = {int(c): c.name for c in codec.Code}
    doc = {}
    for r in table_rows(region(PROTOCOL, "result-codes")):
        if len(r) < 2 or not r[0].isdigit():
            fail(f"{PROTOCOL} result-codes table", f"unexpected row {r}")
            continue
        doc[int(r[0])] = r[1].strip("`")
    compare("result code", ref, f"{PROTOCOL} result-codes table", doc, "codec.Code")
    for rel, pat in ((PORT, r"\b([A-Z_]+)\s*=\s*(\d+)"), (QDOJO, r"\bQDOJO_([A-Z_]+)\s*=\s*(\d+)")):
        got = numbered(rel, re.findall(pat, region(rel, "result-codes")))
        if got.pop(255, None) != "HOST_ERROR":
            fail(f"{rel} result-codes", "HOST_ERROR = 255 (not a protocol code) is missing")
        compare("result code", ref, f"{rel} result-codes", got, "codec.Code")


# ---- 4. the v1 ABI ---------------------------------------------------------------------------

def check_abi():
    from qdojo.combat import join
    src = text(QDOJO)
    procs = {int(n): name for name, n in re.findall(r"REGISTER_USER_PROCEDURE\((\w+),\s*(\d+)\)", src)}
    funcs = {int(n): name for name, n in re.findall(r"REGISTER_USER_FUNCTION\((\w+),\s*(\d+)\)", src)}
    if not procs or not funcs:
        fail(QDOJO, "no REGISTER_USER_PROCEDURE / REGISTER_USER_FUNCTION lines found")
    doc_p, doc_f = {}, {}
    for r in table_rows(region(PROTOCOL, "abi")):
        if len(r) < 3 or not r[1].isdigit() or r[0] not in ("procedure", "function"):
            fail(f"{PROTOCOL} abi table", f"unexpected row {r}")
            continue
        (doc_p if r[0] == "procedure" else doc_f)[int(r[1])] = r[2].strip("`")
    compare("user procedure", procs, f"{PROTOCOL} abi table", doc_p, QDOJO)
    compare("user function", funcs, f"{PROTOCOL} abi table", doc_f, QDOJO)
    readme = {}
    for r in table_rows(region(README, "abi")):
        if r and r[0].isdigit():
            readme[int(r[0])] = r[1].strip("`")
    compare("query function", funcs, f"{README} queries table", readme, QDOJO)
    m = re.search(r"`Dispatch` is user procedure (\d+)", flat(text(README)))
    if not m or procs.get(int(m.group(1))) != "Dispatch":
        fail(README, f"says Dispatch is user procedure {m.group(1) if m else '(nowhere)'}; QDOJO.h registers {procs}")
    dispatch = next((n for n, name in procs.items() if name == "Dispatch"), None)
    if join.INPUT_TYPE != dispatch:
        fail("packages/qdojo/src/qdojo/combat/join.py", f"INPUT_TYPE is {join.INPUT_TYPE}, Dispatch is procedure "
                                                       f"{dispatch} in QDOJO.h")


# ---- 5. rulesets -----------------------------------------------------------------------------

FIELDS = ("hp", "stamina", "opening_damage", "power_damage", "max_opening", "submitted", "base_costs", "damage",
          "digest")


def expected_tables() -> dict[str, dict]:
    """Per version, from the JSON file (the reference artifact), padded to nine actions."""
    from qdojo.combat import rules
    out = {}
    for version, digest in rules.KNOWN.items():
        rel = RULESET_FILES.get(version)
        if rel is None:
            fail("packages/qdojo/src/qdojo/combat/rules.py", f"{version} has no ruleset file in check_sync.py")
            continue
        doc = json.loads(text(rel))
        got = rules.digest_of(doc).hex()
        if got != digest:
            fail(rel, f"hashes to {got}, rules.KNOWN says {digest}")
        if rules.by_version(version).digest.hex() != digest:
            fail("packages/qdojo/src/qdojo/combat/rules.py", f"{version} loads with another digest")
        n = len(doc["action_names"])
        pad = lambda row: list(row) + [0] * (9 - len(row))  # noqa: E731
        out[version] = {
            "doc": doc, "hp": doc["initial"]["hp"], "stamina": doc["initial"]["stamina"],
            "opening_damage": doc["opening_damage"], "power_damage": doc["power_damage"],
            "max_opening": 2 if "last_stand" in doc else 1,
            "submitted": sorted(doc["submitted_action_ids"]), "base_costs": pad(doc["base_costs"]),
            "damage": [pad(r) for r in doc["damage"]] + [[0] * 9] * (9 - n), "digest": digest,
            "stand": (doc.get("last_stand", {}).get("per_hp_behind", 0), doc.get("last_stand", {}).get("cap", 0)),
        }
        if doc["initial"]["hp"] != doc["limits"]["hp"] or doc["initial"]["stamina"] != doc["limits"]["stamina"]:
            notes.append(f"{rel}: initial and limit differ; the C++ tables assume they are equal")
    return out


def check_rulesets():
    from qdojo.combat import devnet, rules
    want = expected_tables()
    versions = list(want)

    # combat_core.h: every integer of CANDIDATE_n in declaration order.
    core = re.sub(r"//[^\n]*", "", text(CORE))
    for i, version in enumerate(versions, 1):
        m = re.search(r"static constexpr RulesetTable CANDIDATE_" + str(i) + r"\s*=\s*\{(.*?)\n\};", core, re.S)
        if not m:
            fail(CORE, f"CANDIDATE_{i} ({version}) not found")
            continue
        v = [int(x, 0) for x in re.findall(r"0x[0-9a-fA-F]+|\d+", m.group(1))]
        w, d = want[version], want[version]["doc"]
        if len(v) != 147:
            fail(CORE, f"CANDIDATE_{i}: {len(v)} values, expected 147 (the RulesetTable layout changed?)")
            continue
        expect = ([d["rounds"], d["beats_per_round"], d["initial"]["hp"], d["initial"]["stamina"], d["initial"]["opening"],
                   d["initial"]["guard_streak"], d["initial"]["power_available"], d["limits"]["hp"],
                   d["limits"]["stamina"], d["limits"]["guard_streak"], d["block_streak_cost"], d["block_strain"],
                   d["ordinary_recovery"], d["recover_unhit"], d["recover_hit"], d["exhausted_recovery"],
                   d["break_recovery"], d["opening_damage"], d["power_damage"], d["power_cost"]]
                  + w["base_costs"] + [x for row in w["damage"] for x in row]
                  + [sum(1 << a for a in w["submitted"]), w["max_opening"], int("last_stand" in d), *w["stand"]]
                  + list(bytes.fromhex(w["digest"])))
        names = (["rounds/beats/initial/limits/costs"] * 20 + ["base_costs"] * 9 + ["damage"] * 81
                 + ["submitted_mask", "max_opening", "candidate3", "stand_per_hp", "stand_cap"] + ["digest"] * 32)
        bad = sorted({names[k] for k in range(147) if v[k] != expect[k]})
        if bad:
            fail(CORE, f"CANDIDATE_{i} differs from {RULESET_FILES[version]} in: {', '.join(bad)}")

    # QDOJO.h: compile the ruleset functions natively and evaluate every table.
    got = qdojo_tables()
    if got is not None:
        for i, version in enumerate(versions, 1):
            g, w = got.get(str(i)), want[version]
            if g is None:
                fail(QDOJO, f"ruleset table {i} ({version}) missing")
                continue
            for f in FIELDS:
                if g[f] != w[f]:
                    fail(f"{QDOJO} ruleset-functions", f"table {i} ({version}): {f} is {g[f]}, "
                                                       f"{RULESET_FILES[version]} says {w[f]}")
            if g["ruleset_of"] != i:
                fail(f"{QDOJO} ruleset-functions", f"rulesetOf(digest of table {i}) is {g['ruleset_of']}")
            if i == 3 and tuple(g["stand"]) != w["stand"]:
                fail(QDOJO, f"QDOJO_STAND_PER_HP/QDOJO_STAND_CAP {g['stand']}, {RULESET_FILES[version]} says "
                            f"{w['stand']}")
        for name, key in (("QDOJO_BLOCK_STREAK_COST", "block_streak_cost"), ("QDOJO_BLOCK_STRAIN", "block_strain"),
                          ("QDOJO_ORDINARY_RECOVERY", "ordinary_recovery"), ("QDOJO_RECOVER_UNHIT", "recover_unhit"),
                          ("QDOJO_RECOVER_HIT", "recover_hit"), ("QDOJO_EXHAUSTED_RECOVERY", "exhausted_recovery"),
                          ("QDOJO_BREAK_RECOVERY", "break_recovery"), ("QDOJO_POWER_COST", "power_cost")):
            m = re.search(r"\b" + name + r"\s*=\s*(\d+)", text(QDOJO))
            vals = {want[v]["doc"][key] for v in versions}
            if not m or {int(m.group(1))} != vals:
                fail(QDOJO, f"{name} is {m.group(1) if m else 'missing'}, the ruleset files say {sorted(vals)}")

    # The compiled manifest's ruleset is the demo-c3 profile's.
    m = re.search(r"QDOJO_MANIFEST_RULESET\s*=\s*QDOJO_RS_C(\d)", text(QDOJO))
    demo = devnet.manifest("demo-c3").ruleset.semantic_version
    if not m or versions[int(m.group(1)) - 1] != demo:
        fail(QDOJO, f"QDOJO_MANIFEST_RULESET is {m.group(0) if m else 'missing'}, devnet demo-c3 runs {demo}")

    # ruleset.js (the site's embedded copies).
    if shutil.which("node"):
        js = subprocess.run(["node", "-e", "require('./apps/web/combat/ruleset.js');"
                             "process.stdout.write(JSON.stringify(globalThis.QDojoRulesets))"],
                            cwd=ROOT, capture_output=True, text=True)
        if js.returncode:
            fail("apps/web/combat/ruleset.js", f"node could not load it: {js.stderr.strip()[:200]}")
        else:
            copies = {r["semantic_version"]: r for r in json.loads(js.stdout)}
            for version in versions:
                if version not in copies:
                    fail("apps/web/combat/ruleset.js", f"{version} is not embedded")
                elif rules.digest_of(copies[version]).hex() != want[version]["digest"]:
                    fail("apps/web/combat/ruleset.js", f"the embedded {version} hashes to "
                         f"{rules.digest_of(copies[version]).hex()}, {RULESET_FILES[version]} to {want[version]['digest']}")
    else:
        notes.append("node not found: apps/web/combat/ruleset.js not checked")

    # Digests named in prose.
    known = {want[v]["digest"]: v for v in versions}
    combat = text("docs/combat.md")
    for full in set(re.findall(r"\b[0-9a-f]{64}\b", combat)):
        if full not in known:
            fail("docs/combat.md", f"names digest {full}, which is no packaged ruleset")
    s11, s12 = combat.find("## 11. Candidate 2"), combat.find("## 12. Candidate 3")
    for version, part in ((versions[1], combat[s11:s12]), (versions[2], combat[s12:])):
        if want[version]["digest"] not in part:
            fail("docs/combat.md", f"the {version} section does not name its digest {want[version]['digest']}")
    head = flat(combat[:2000])
    for version in versions:
        m = re.search(re.escape(RULESET_FILES[version].split("/")[1]) + r"\), digest `([0-9a-f]{8})…`", head)
        if not m or not want[version]["digest"].startswith(m.group(1)):
            fail("docs/combat.md status line", f"{version}: digest {m.group(1) if m else '(not stated)'}…, "
                                               f"expected {want[version]['digest'][:8]}…")
    llms = flat(text(LLMS))
    for version in versions:
        m = re.search(re.escape(version) + r", digest ([0-9a-f]{8})", llms)
        if not m or not want[version]["digest"].startswith(m.group(1)):
            fail(LLMS, f"{version}: digest {m.group(1) if m else '(not stated)'}..., expected "
                       f"{want[version]['digest'][:8]}...")
    for i, version in enumerate(versions, 1):
        m = re.search(r"//\s+" + str(i) + r" = (\S+)\s+(\S+)\s+([0-9a-f]{8})\.\.\.", text(QDOJO))
        if not m or (m.group(1), m.group(2)) != (RULESET_FILES[version], version) \
                or not want[version]["digest"].startswith(m.group(3)):
            fail(QDOJO, f"the ruleset comment for table {i} is {m.groups() if m else 'missing'}, expected "
                        f"{RULESET_FILES[version]} {version} {want[version]['digest'][:8]}...")


def qdojo_tables() -> dict | None:
    """Compile QDOJO.h's ruleset functions (its sync region) with g++ against a
    tiny stand-in for the QPI types, and print every table as JSON."""
    gxx = shutil.which("g++")
    if not gxx:
        notes.append("g++ not found: QDOJO.h ruleset functions not evaluated")
        return None
    src = text(QDOJO)
    consts = "\n".join(re.findall(r"^constexpr [^;\n]*;", src, re.M))
    body = region(QDOJO, "ruleset-functions")
    if not body:
        return None
    prog = """#include <cstdint>
#include <cstdio>
typedef uint8_t uint8; typedef uint16_t uint16; typedef uint32_t uint32; typedef uint64_t uint64;
typedef int8_t sint8; typedef int16_t sint16; typedef int32_t sint32; typedef int64_t sint64; typedef bool bit;
struct id {
    uint64 w[4];
    id(uint64 a, uint64 b, uint64 c, uint64 d) { w[0] = a; w[1] = b; w[2] = c; w[3] = d; }
    bool operator==(const id& o) const { return w[0] == o.w[0] && w[1] == o.w[1] && w[2] == o.w[2] && w[3] == o.w[3]; }
};
%s
struct Q {
    struct EFighter { uint16 hp; uint16 stamina; uint8 opening; uint8 guardStreak; uint8 powerAvailable; };
    struct EState { EFighter a; EFighter b; uint8 roundIndex; uint8 outcome; uint8 winner; };
%s
};
int main() {
    printf("{");
    for (uint8 rs = 1; rs <= 3; ++rs) {
        id d = Q::rulesetDigestOf(rs);
        printf("%%s\\"%%u\\": {\\"digest\\": \\"", rs == 1 ? "" : ", ", rs);
        for (int i = 0; i < 32; ++i) printf("%%02x", (unsigned)((d.w[i / 8] >> (8 * (i %% 8))) & 0xff));
        printf("\\", \\"ruleset_of\\": %%u, \\"hp\\": %%u, \\"stamina\\": %%u, \\"opening_damage\\": %%u, "
               "\\"power_damage\\": %%u, \\"max_opening\\": %%u, \\"stand\\": [%%u, %%u], \\"submitted\\": [",
               Q::rulesetOf(d), Q::hpOf(rs), Q::staminaOf(rs), Q::openingDamage(rs), Q::powerDamage(rs),
               Q::maxOpening(rs), (unsigned)QDOJO_STAND_PER_HP, (unsigned)QDOJO_STAND_CAP);
        const char* sep = "";
        for (uint8 a = 0; a < QDOJO_ACTION_COUNT; ++a)
            if (Q::isSubmitted(rs, a)) { printf("%%s%%u", sep, a); sep = ", "; }
        printf("], \\"base_costs\\": [");
        for (uint8 a = 0; a < QDOJO_ACTION_COUNT; ++a) printf("%%s%%u", a ? ", " : "", Q::baseCost(rs, a));
        printf("], \\"damage\\": [");
        for (uint8 a = 0; a < QDOJO_ACTION_COUNT; ++a) {
            printf("%%s[", a ? ", " : "");
            for (uint8 b = 0; b < QDOJO_ACTION_COUNT; ++b) printf("%%s%%u", b ? ", " : "", Q::damage(rs, a, b));
            printf("]");
        }
        printf("]}");
    }
    printf("}\\n");
    return 0;
}
""" % (consts, body)
    with tempfile.TemporaryDirectory(prefix="qdojo-sync-") as tmp:
        cpp, exe = Path(tmp) / "t.cpp", Path(tmp) / "t"
        cpp.write_text(prog)
        r = subprocess.run([gxx, "-std=c++17", "-O0", "-w", "-o", str(exe), str(cpp)], capture_output=True, text=True)
        if r.returncode:
            fail(f"{QDOJO} ruleset-functions", "does not compile stand-alone: " + r.stderr.strip()[:400])
            return None
        out = subprocess.run([str(exe)], capture_output=True, text=True)
        return json.loads(out.stdout)


# ---- 6. the compiled-in manifest -------------------------------------------------------------

def check_manifest():
    from qdojo.combat import devnet
    from qdojo.combat.contract import development_manifest
    from qdojo.combat.rules import candidate_1
    from combat.test_contract import ADMIN, DEV, HOUSE, SHARE

    dm = {k: int(v, 0) for k, v in
          re.findall(r"constexpr \w+ QDOJO_DM_(\w+) = (0x[0-9a-fA-F]+|\d+)(?:ULL)?;", region(QDOJO, "compiled-manifest"))}

    def ident(prefix):
        try:
            return b"".join(dm[f"{prefix}_{i}"].to_bytes(8, "little") for i in range(4))
        except KeyError:
            fail(f"{QDOJO} compiled-manifest", f"identity {prefix} is incomplete")
            return b""

    m = devnet.manifest("demo-c3")
    where = f"{QDOJO} compiled-manifest"
    if list(m.timing) != [dm.get("TIMING_ID")] or m.timing[dm.get("TIMING_ID")] != (dm.get("COMMIT_TICKS"),
                                                                                  dm.get("REVEAL_TICKS")):
        fail(where, f"timing {dm.get('TIMING_ID')}: {dm.get('COMMIT_TICKS')}/{dm.get('REVEAL_TICKS')}, demo-c3 has "
                    f"{m.timing}")
    if sorted(m.fees) != list(range(1, dm.get("FEES", 0) + 1)) or sorted(m.tiers) != sorted(m.fees):
        fail(where, f"{dm.get('FEES')} fee profiles and tiers, demo-c3 has fees {sorted(m.fees)} tiers {sorted(m.tiers)}")
    for i in sorted(m.fees):
        f = m.fees[i]
        got = (dm.get(f"FEE_{i}_RAKE_BPS"), dm.get("HOUSE_BPS"), dm.get("DEV_BPS"), dm.get("SHARE_BPS"))
        if got != (f.rake_bps, f.house_bps, f.dev_bps, f.share_bps):
            fail(where, f"fee profile {i} (rake, house, dev, share bps) {got}, demo-c3 has "
                        f"{(f.rake_bps, f.house_bps, f.dev_bps, f.share_bps)}")
    for i, stake in sorted(m.tiers.items()):
        if dm.get(f"TIER_{i}_STAKE") != stake:
            fail(where, f"tier {i} stake {dm.get(f'TIER_{i}_STAKE')}, demo-c3 has {stake}")
    scalar = {"GENESIS_EPOCH": m.genesis_epoch, "TICKS_PER_EPOCH": m.ticks_per_epoch,
              "SEASON_START_EPOCH": m.season_start_epoch, "SEASON_EPOCHS": m.season_epochs,
              "SEASON_CLOSEOUT_TICKS": m.season_closeout_ticks, "MAX_FIGHTERS": m.max_fighters,
              "MAX_ACCOUNTS": m.max_accounts, "MAX_OFFERS": m.max_offers, "MAX_FIGHTS": m.max_fights,
              "MAX_CUPS": m.max_cups, "MAX_CUP_ENTRANTS": m.max_cup_entrants, "EVENT_RING": m.event_ring,
              "MATCH_INTERVAL": m.match_interval, "OFFER_LIFETIME_LO": m.offer_lifetime[0],
              "OFFER_LIFETIME_HI": m.offer_lifetime[1], "COOLDOWN_TICKS": m.cooldown_ticks,
              "FAULTS_PER_EPOCH": m.faults_per_epoch, "PAIR_STARTS_PER_EPOCH": m.pair_starts_per_epoch,
              "PAIR_REMATCH_TICKS": m.pair_rematch_ticks}
    for k, v in scalar.items():
        if dm.get(k) != v:
            fail(where, f"QDOJO_DM_{k} is {dm.get(k)}, devnet demo-c3 has {v}")
    test = development_manifest(candidate_1(), ADMIN, HOUSE, DEV, SHARE)
    for prefix, want in (("NETWORK", test.network_id), ("ADMIN", ADMIN), ("HOUSE", HOUSE), ("DEV", DEV),
                         ("SHARE", SHARE)):
        if ident(prefix) != want:
            fail(where, f"{prefix} identity {ident(prefix).hex()} is not the journals' test identity {want.hex()}")

    # Capacities: the compiled manifest within both C++ files' tables, as protocol.md §7 states them.
    caps = {"FIGHTERS": "MAX_FIGHTERS", "ACCOUNTS": "MAX_ACCOUNTS", "OPEN_OFFERS": "MAX_OFFERS",
            "FIGHTS": "MAX_FIGHTS", "CUPS": "MAX_CUPS", "CUP_ENTRANTS": "MAX_CUP_ENTRANTS", "EVENTS": "EVENT_RING"}
    for rel, prefix in ((PORT, "CAP_"), (QDOJO, "QDOJO_CAP_")):
        src = text(rel)
        for cap, key in caps.items():
            mm = re.search(r"\b" + prefix + cap + r"\s*=\s*(\d+)", src)
            if not mm or int(mm.group(1)) != dm.get(key):
                fail(rel, f"{prefix}{cap} is {mm.group(1) if mm else 'missing'}, the compiled manifest's {key} is "
                          f"{dm.get(key)}")
    p = flat(text(PROTOCOL))
    mm = re.search(r"Candidate fixed capacities: (\d+) fighters, (\d+) admitted signer/credit accounts, (\d+) waiting "
                   r"offers, (\d+) active fights, (\d+) cups of at most (\d+) entrants, event ring (\d+) records", p)
    want = tuple(dm.get(k) for k in ("MAX_FIGHTERS", "MAX_ACCOUNTS", "MAX_OFFERS", "MAX_FIGHTS", "MAX_CUPS",
                                     "MAX_CUP_ENTRANTS", "EVENT_RING"))
    if not mm or tuple(int(x) for x in mm.groups()) != want:
        fail(f"{PROTOCOL} §7", f"capacities {mm.groups() if mm else '(sentence not found)'}, the contract has {want}")

    # What the docs say the compiled manifest (or the live demo-c3 arena) is.
    t1, t2 = m.tiers[1], m.tiers[2]
    commit, reveal = m.timing[1]
    r1, r2 = m.fees[1].rake_bps // 100, m.fees[2].rake_bps // 100
    n = lambda x: f"{x:,}"  # noqa: E731
    stated = [
        (README, r"timing (\d+)/(\d+), tiers ([\d,]+) and ([\d,]+) QU, fee profiles 1 \((\d+)% rake\) and 2 \((\d+)%\), "
                 r"([\d,]+)-tick epochs",
         (str(commit), str(reveal), n(t1), n(t2), str(r1), str(r2), n(m.ticks_per_epoch))),
        ("docs/testnet.md", r"economics \(timing (\d+)/(\d+), tiers ([\d,]+) and ([\d,]+) QU, fee profiles 1 and 2, "
                            r"([\d,]+)-tick epochs\)",
         (str(commit), str(reveal), n(t1), n(t2), n(m.ticks_per_epoch))),
        (LLMS, r"commit window (\d+) ticks, reveal window (\d+) ticks", (str(commit), str(reveal))),
        ("docs/combat.md", r"timing \(commit (\d+), reveal (\d+) ticks\)", (str(commit), str(reveal))),
    ]
    for rel, pat, want in stated:
        mm = re.search(pat, flat(text(rel)))
        if not mm:
            fail(rel, f"the statement of the demo-c3 economics was not found (pattern: {pat})")
        elif mm.groups() != want:
            fail(rel, f"states {mm.groups()}, devnet demo-c3 / QDOJO.h have {want}")


# ---- 7. NFT backends and ownership opcodes ---------------------------------------------------

def check_nft():
    from qdojo.combat import codec, live
    nft_src = text("packages/qdojo/src/qdojo/combat/nft.py")
    made = set(re.findall(r'if name == "([\w-]+)"', nft_src))
    if set(live.NFT_BACKENDS) != made:
        fail("packages/qdojo/src/qdojo/combat/live.py", f"NFT_BACKENDS {sorted(live.NFT_BACKENDS)}, nft.make_backend "
                                                        f"builds {sorted(made)}")
    md = text(NFT_MD)
    mm = re.search(r"`nft_backend: ([\w| -]+)`", md)
    doc = {x.strip() for x in mm.group(1).split("|")} if mm else set()
    if doc != set(live.NFT_BACKENDS):
        fail(NFT_MD, f"§5 lists backends {sorted(doc)}, the code has {sorted(live.NFT_BACKENDS)}")
    ops = {int(op): op.name for op in codec.Op}
    src_files = [p for p in (ROOT / "packages/qdojo/src/qdojo").rglob("*.py") if p.name != "codec.py"]
    sources = {p: p.read_text(encoding="utf-8") for p in src_files}
    rows = table_rows(region(NFT_MD, "ownership-opcodes"))
    seen = set()
    for r in rows:
        if len(r) < 4:
            fail(f"{NFT_MD} ownership-opcodes table", f"unexpected row {r}")
            continue
        backends = set(re.findall(r"`([\w-]+)`", r[0]))          # a row without one: no backend (legacy)
        name, num, sender = r[1].split(":")[0].strip("` "), r[2], r[3].strip("`").removeprefix("combat/")
        if not num.isdigit() or ops.get(int(num)) != snake(name):
            fail(f"{NFT_MD} ownership-opcodes table", f"{name} {num}: codec.Op has "
                 f"{ {v: k for k, v in ops.items()}.get(snake(name), 'no such opcode') }")
            continue
        for b in backends:
            if b not in live.NFT_BACKENDS:
                fail(f"{NFT_MD} ownership-opcodes table", f"backend {b} is not in live.NFT_BACKENDS")
            seen.add(b)
        path = ROOT / "packages/qdojo/src/qdojo/combat" / sender
        if path not in sources:
            fail(f"{NFT_MD} ownership-opcodes table", f"{name}: sender {sender} is not a file under packages/qdojo/src/qdojo/combat")
        elif f"Op.{snake(name)}" not in sources[path]:
            fail(f"{NFT_MD} ownership-opcodes table", f"{name}: {sender} never sends Op.{snake(name)}")
    if seen != set(live.NFT_BACKENDS):
        fail(f"{NFT_MD} ownership-opcodes table", f"covers backends {sorted(seen)}, the code has "
                                                  f"{sorted(live.NFT_BACKENDS)}")
    asset_ops = {n for n, name in ops.items() if "ASSET" in name or "OWNER" in name and n >= 100}
    listed = {int(r[2]) for r in rows if len(r) >= 3 and r[2].isdigit()}
    if asset_ops - listed:
        fail(f"{NFT_MD} ownership-opcodes table", f"does not list the ownership opcodes {sorted(asset_ops - listed)}")

    # The mirror source contract.
    srcs = set(codec.MIRROR_SOURCES)
    for rel, name in ((PORT, "MIRROR_SOURCE_QBAY"), (QDOJO, "QDOJO_MIRROR_SOURCE_QBAY")):
        mm = re.search(r"\b" + name + r"\s*=\s*(\d+)", text(rel))
        if not mm or {int(mm.group(1))} != srcs:
            fail(rel, f"{name} is {mm.group(1) if mm else 'missing'}, codec.MIRROR_SOURCES is {sorted(srcs)}")
    mm = re.search(r"the only accepted source is (\d+) \(QBAY\)", flat(text(PROTOCOL)))
    if not mm or {int(mm.group(1))} != srcs:
        fail(f"{PROTOCOL} §3", f"states mirror source {mm.group(1) if mm else '(not found)'}, codec.MIRROR_SOURCES is "
                               f"{sorted(srcs)}")


def main() -> int:
    for check in (check_opcodes, check_events, check_codes, check_abi, check_rulesets, check_manifest, check_nft):
        try:
            check()
        except Exception as exc:                          # a broken check is a failure, never a pass
            fail(check.__name__, f"{type(exc).__name__}: {exc}")
    for note in notes:
        print("note:", note)
    if errors:
        print(f"contract/docs sync: {len(errors)} difference(s):")
        for e in errors:
            print("  -", e)
        return 1
    print("contract/docs sync passed: opcodes, event types, result codes, v1 ABI, rulesets, compiled manifest, NFT "
          "backends and ownership opcodes agree across the reference, the C++ port, QDOJO.h and the docs.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
