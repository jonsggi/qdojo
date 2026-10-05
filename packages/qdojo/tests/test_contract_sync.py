"""The contract and the docs stay in sync (docs/reference/check_sync.py).

test_in_sync runs the whole check. The mutation tests edit one copy in memory
and require the check to name exactly that drift, so a check that silently
stops looking fails here.
"""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location("check_sync", ROOT / "docs/reference/check_sync.py")
sync = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sync)


def run(check, edits=()):
    """Run one check with (file, old, new) edits applied in memory; return its errors."""
    original = sync.text

    def text(rel):
        s = original(rel)
        for f, old, new in edits:
            if f == rel:
                assert old in s, (rel, old)
                s = s.replace(old, new, 1)
        return s
    sync.errors.clear()
    sync.text = text
    try:
        check()
    finally:
        sync.text = original
    out = list(sync.errors)
    sync.errors.clear()
    return out


def test_in_sync():
    assert sync.main() == 0, "\n".join(sync.errors)


MUTATIONS = [
    (sync.check_opcodes, (sync.PROTOCOL, "| 104 | AdminMirrorOwner |", "| 105 | AdminMirrorOwner |"),
     "opcode 104 ADMIN_MIRROR_OWNER is missing"),
    (sync.check_opcodes, (sync.PROTOCOL, "source_id u64, owner[32], mirror_seq u64 |", "source_id u64, owner[32] |"),
     "opcode 104 AdminMirrorOwner body"),
    (sync.check_opcodes, (sync.PORT, "case OP_ADMIN_MIRROR_OWNER: return 32 + 4 + 1 + 4 + 8 + 32 + 8;",
                          "case OP_ADMIN_MIRROR_OWNER: return 32 + 4 + 1 + 4 + 8 + 32;"), "body is 81 bytes"),
    (sync.check_opcodes, (sync.QDOJO, "constexpr uint16 QDOJO_OP_ADMIN_MIRROR_OWNER = 104;", ""),
     "contracts/qubic/QDOJO.h opcodes: opcode 104 ADMIN_MIRROR_OWNER is missing"),
    (sync.check_opcodes, ("docs/nft.md", "**AdminMirrorOwner (opcode 104)**", "**AdminMirrorOwner (opcode 105)**"),
     "says AdminMirrorOwner (105)"),
    (sync.check_events, (sync.QDOJO, "constexpr uint16 QDOJO_EV_OWNER_MIRRORED = 30;", ""),
     "event type 30 OWNER_MIRRORED is missing"),
    (sync.check_events, (sync.PORT, "emit(s, EV_OWNER_MIRRORED, b);", ""), "OWNER_MIRRORED is defined but never emitted"),
    (sync.check_codes, (sync.PROTOCOL, "| 23 | BAD_STATE |", "| 23 | WRONG_STATE |"), "result code 23 is named WRONG_STATE"),
    (sync.check_abi, (sync.README, "`Dispatch` is user procedure 1", "`Dispatch` is user procedure 2"),
     "says Dispatch is user procedure 2"),
    (sync.check_abi, (sync.PROTOCOL, "| function | 10 | GetLedger |", "| function | 11 | GetLedger |"),
     "user function 10 GetLedger is missing"),
    (sync.check_rulesets, (sync.QDOJO, "return rs == QDOJO_RS_C1 ? 8 : 10;", "return rs == QDOJO_RS_C1 ? 8 : 11;"),
     "table 2 (combat-v1-candidate-2): damage"),
    (sync.check_rulesets, (sync.CORE, "{6, 12, 4, 4, 9, 0, 0, 8, 2},", "{6, 12, 4, 4, 9, 0, 0, 9, 2},"),
     "CANDIDATE_3 differs from docs/combat-v1-candidate-3.json in: base_costs"),
    (sync.check_rulesets, (sync.LLMS, "digest 231607f8", "digest 231607f9"), "combat-v1-candidate-2: digest 231607f9"),
    (sync.check_manifest, (sync.QDOJO, "QDOJO_DM_TIER_2_STAKE = 20000;", "QDOJO_DM_TIER_2_STAKE = 25000;"),
     "tier 2 stake 25000, demo-c3 has 20000"),
    (sync.check_manifest, (sync.LLMS, "commit window 9 ticks", "commit window 10 ticks"), "states ('10', '8')"),
    (sync.check_manifest, (sync.PROTOCOL, "64 waiting offers", "128 waiting offers"), "docs/protocol.md §7"),
    (sync.check_nft, (sync.NFT_MD, "| AdminMirrorOwner: the QBAY NFT", "| AdminBindAsset: the QBAY NFT"),
     "AdminBindAsset 104"),
    (sync.check_nft, (sync.NFT_MD, "`nft_backend: sim | qubic | qbay-mirror`", "`nft_backend: sim | qbay-mirror`"),
     "§5 lists backends"),
    (sync.check_nft, (sync.QDOJO, "QDOJO_MIRROR_SOURCE_QBAY = 12;", "QDOJO_MIRROR_SOURCE_QBAY = 13;"),
     "QDOJO_MIRROR_SOURCE_QBAY is 13"),
]


@pytest.mark.parametrize("check,edit,expect", MUTATIONS, ids=[f"{m[0].__name__}-{i}" for i, m in enumerate(MUTATIONS)])
def test_drift_is_named(check, edit, expect):
    assert run(check) == [], f"{check.__name__} fails without any edit"
    errors = run(check, [edit])
    assert any(expect in e for e in errors), f"expected '{expect}' in {errors}"
