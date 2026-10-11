"""The contract and the docs stay in sync (docs/reference/check_sync.py).

test_in_sync runs the whole check. The mutation tests edit one copy in memory
and require the check to name exactly that drift, so a check that silently
stops looking fails here. Every comparison has a row for each copy it reads;
the parse guards ("unexpected row", "not found") have none, and ruleset.js,
which node loads from disk, is compared with the JSON files by
apps/web/tests/combat-app.test.cjs.
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


PORT_README, CONTRACT_PY = "contracts/combat_contract/README.md", "packages/qdojo/src/qdojo/combat/contract.py"
MUTATIONS = [
    # 1. opcodes
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
    (sync.check_opcodes, (sync.PROTOCOL, "| 4 | QueueCancel |",
                          "| 4 | QueueCancelOld | offer_id u64 |\n| 4 | QueueCancel |"),
     "opcodes table: number 4 appears twice (QUEUE_CANCEL_OLD, QUEUE_CANCEL)"),
    (sync.check_opcodes, (sync.PORT, "OP_ADMIN_MIRROR_OWNER = 104", "OP_ADMIN_MIRROR_OWNER = 105"),
     "combat_contract.h opcodes: opcode 104 ADMIN_MIRROR_OWNER is missing"),
    (sync.check_opcodes, (sync.QDOJO, "case QDOJO_OP_ADMIN_MIRROR_OWNER: return 32 + 4 + 1 + 4 + 8 + 32 + 8;",
                          "case QDOJO_OP_ADMIN_MIRROR_OWNER: return 32 + 4 + 1 + 4 + 8 + 32;"),
     "QDOJO.h body-lengths: opcode 104 ADMIN_MIRROR_OWNER body is 81 bytes"),
    (sync.check_opcodes, (sync.PORT, "        case OP_WITHDRAW: return 0;\n", ""),
     "combat_contract.h body-lengths: no body length for opcode 10 WITHDRAW"),
    (sync.check_opcodes, (sync.QDOJO, "        case QDOJO_OP_WITHDRAW: return 0;\n", ""),
     "QDOJO.h body-lengths: no body length for opcode 10 WITHDRAW"),
    (sync.check_opcodes, (sync.PORT, "        case OP_REVEAL: return op_reveal(s, inv, r, amount, t);\n", ""),
     "combat_contract.h dispatch: opcode 8 REVEAL has no handler"),
    (sync.check_opcodes, (sync.QDOJO, "        case QDOJO_OP_REVEAL:\n"
                                      "            opReveal(s, c, inv, fr, amount, t, r);\n            break;\n", ""),
     "QDOJO.h dispatch: opcode 8 REVEAL has no handler"),
    (sync.check_opcodes, (sync.QDOJO, "if (c.fr_op == QDOJO_OP_WITHDRAW)", "if (c.fr_op == QDOJO_OP_CUP_WITHDRAW)"),
     "QDOJO.h dispatch: opcode 10 WITHDRAW has no handler"),
    (sync.check_opcodes, (sync.PORT, "FRAME_HEADER = 24;", "FRAME_HEADER = 25;"),
     "combat_contract.h: FRAME_HEADER is 25"),
    (sync.check_opcodes, (sync.QDOJO, "QDOJO_MAX_BODY = 487;", "QDOJO_MAX_BODY = 486;"),
     "QDOJO.h: QDOJO_MAX_BODY is 486"),
    (sync.check_opcodes, (sync.PROTOCOL, "body length, 0..487", "body length, 0..486"), "body length bound is 486"),
    (sync.check_opcodes, (sync.PROTOCOL, "Opcodes 100–104 are accepted", "Opcodes 100–103 are accepted"),
     "states admin opcodes ('100', '103')"),
    (sync.check_opcodes, (PORT_README, "admin opcodes 100–104", "admin opcodes 100–102"),
     "combat_contract/README.md: says admin opcodes 100–102"),
    (sync.check_opcodes, ("docs/nft.md", "**AdminMirrorOwner (opcode 104)**", "**opcode 105 AdminMirrorOwner**"),
     "says opcode 105 AdminMirrorOwner"),
    # 2. event types
    (sync.check_events, (sync.QDOJO, "constexpr uint16 QDOJO_EV_OWNER_MIRRORED = 30;", ""),
     "event type 30 OWNER_MIRRORED is missing"),
    (sync.check_events, (sync.PORT, "emit(s, EV_OWNER_MIRRORED, b);", ""), "OWNER_MIRRORED is defined but never emitted"),
    (sync.check_events, (sync.PROTOCOL, "| 30 | OWNER_MIRRORED |", "| 31 | OWNER_MIRRORED |"),
     "event-types table: event type 30 OWNER_MIRRORED is missing"),
    (sync.check_events, (sync.PROTOCOL, "| 14 | RATING |", "| 14 | RATED |\n| 14 | RATING |"),
     "event-types table: number 14 appears twice (RATED, RATING)"),
    (sync.check_events, (sync.PORT, "EV_OWNER_MIRRORED = 30", "EV_OWNER_MIRRORED = 31"),
     "combat_contract.h event-types: event type 30 OWNER_MIRRORED is missing"),
    (sync.check_events, (sync.QDOJO, "emit(s, c, QDOJO_EV_OWNER_MIRRORED);", ""),
     "QDOJO.h: event type 30 OWNER_MIRRORED is defined but never emitted"),
    (sync.check_events, (CONTRACT_PY, '_emit("OWNER_MIRRORED"', '_emit("OWNER_MIRROR"'),
     "contract.py: event type 30 OWNER_MIRRORED is never emitted"),
    # 3. result codes
    (sync.check_codes, (sync.PROTOCOL, "| 23 | BAD_STATE |", "| 23 | WRONG_STATE |"), "result code 23 is named WRONG_STATE"),
    (sync.check_codes, (sync.PROTOCOL, "| 23 | BAD_STATE |", "| 23 | WRONG_STATE |\n| 23 | BAD_STATE |"),
     "result-codes table: number 23 appears twice (WRONG_STATE, BAD_STATE)"),
    (sync.check_codes, (sync.PORT, "TRANSFER_FAILED = 29", "TRANSFER_FAILED = 30"),
     "combat_contract.h result-codes: result code 29 TRANSFER_FAILED is missing"),
    (sync.check_codes, (sync.QDOJO, "QDOJO_TRANSFER_FAILED = 29", "QDOJO_TRANSFER_FAILED = 30"),
     "QDOJO.h result-codes: result code 29 TRANSFER_FAILED is missing"),
    (sync.check_codes, (sync.PORT, "HOST_ERROR = 255", "HOST_ERROR = 254"),
     "combat_contract.h result-codes: HOST_ERROR = 255 (not a protocol code) is missing"),
    (sync.check_codes, (sync.QDOJO, "QDOJO_HOST_ERROR = 255", "QDOJO_HOST_ERROR = 254"),
     "QDOJO.h result-codes: HOST_ERROR = 255 (not a protocol code) is missing"),
    # 4. the v1 ABI
    (sync.check_abi, (sync.README, "`Dispatch` is user procedure 1", "`Dispatch` is user procedure 2"),
     "says Dispatch is user procedure 2"),
    (sync.check_abi, (sync.PROTOCOL, "| function | 10 | GetLedger |", "| function | 11 | GetLedger |"),
     "user function 10 GetLedger is missing"),
    (sync.check_abi, (sync.PROTOCOL, "| procedure | 1 | Dispatch |", "| procedure | 2 | Dispatch |"),
     "abi table: user procedure 1 Dispatch is missing"),
    (sync.check_abi, (sync.PROTOCOL, "| function | 3 | GetEvents |",
                      "| function | 3 | GetEventsOld | x |\n| function | 3 | GetEvents |"),
     "abi table: number 3 appears twice (GetEventsOld, GetEvents)"),
    (sync.check_abi, (sync.README, "| 10 | `GetLedger` |", "| 11 | `GetLedger` |"),
     "queries table: query function 10 GetLedger is missing"),
    (sync.check_abi, (sync.README, "| 3 | `GetEvents` |", "| 3 | `GetEventsOld` | |\n  | 3 | `GetEvents` |"),
     "queries table: number 3 appears twice (GetEventsOld, GetEvents)"),
    (sync.check_abi, (sync.QDOJO, "REGISTER_USER_FUNCTION(GetEvents, 3);",
                      "REGISTER_USER_FUNCTION(GetEventsOld, 3);\n        REGISTER_USER_FUNCTION(GetEvents, 3);"),
     "REGISTER_USER_FUNCTION: number 3 appears twice (GetEventsOld, GetEvents)"),
    (sync.check_abi, (sync.QDOJO, "REGISTER_USER_PROCEDURE(Dispatch, 1);", "REGISTER_USER_PROCEDURE(Dispatch, 2);"),
     "INPUT_TYPE is 1, Dispatch is procedure 2"),
    # 5. rulesets
    (sync.check_rulesets, (sync.QDOJO, "return rs == QDOJO_RS_C1 ? 8 : 10;", "return rs == QDOJO_RS_C1 ? 8 : 11;"),
     "table 2 (combat-v1-candidate-2): damage"),
    (sync.check_rulesets, (sync.CORE, "{6, 12, 4, 4, 9, 0, 0, 8, 2},", "{6, 12, 4, 4, 9, 0, 0, 9, 2},"),
     "CANDIDATE_3 differs from docs/combat-v1-candidate-3.json in: base_costs"),
    (sync.check_rulesets, (sync.LLMS, "digest 231607f8", "digest 231607f9"), "combat-v1-candidate-2: digest 231607f9"),
    (sync.check_rulesets, ("docs/combat-v1-candidate-2.json", '"power_cost": 4,', '"power_cost": 5,'),
     "docs/combat-v1-candidate-2.json: hashes to"),
    (sync.check_rulesets, (sync.QDOJO, "return QDOJO_RS_C2;", "return QDOJO_RS_C1;"),
     "rulesetOf(digest of table 2) is 1"),
    (sync.check_rulesets, (sync.QDOJO, "QDOJO_STAND_CAP = 16;", "QDOJO_STAND_CAP = 17;"),
     "QDOJO_STAND_PER_HP/QDOJO_STAND_CAP [1, 17]"),
    (sync.check_rulesets, (sync.QDOJO, "QDOJO_POWER_COST = 4;", "QDOJO_POWER_COST = 5;"), "QDOJO_POWER_COST is 5"),
    (sync.check_rulesets, (sync.QDOJO, "QDOJO_MANIFEST_RULESET = QDOJO_RS_C3;",
                           "QDOJO_MANIFEST_RULESET = QDOJO_RS_C2;"),
     "QDOJO_RS_C2, devnet demo-c3 runs combat-v1-candidate-3"),
    (sync.check_rulesets, (sync.QDOJO, "combat-v1-candidate-3  cf19b7cf...", "combat-v1-candidate-3  cf19b7ce..."),
     "the ruleset comment for table 3"),
    (sync.check_rulesets, ("docs/combat.md", "231607f823153747f4c922fd5976c1ac06622542cd5a39eab088874d886b8b74",
                           "231607f823153747f4c922fd5976c1ac06622542cd5a39eab088874d886b8b75"),
     "which is no packaged ruleset"),
    (sync.check_rulesets, ("docs/combat.md", "231607f823153747f4c922fd5976c1ac06622542cd5a39eab088874d886b8b74",
                           "231607f8…"), "the combat-v1-candidate-2 section does not name its digest"),
    (sync.check_rulesets, ("docs/combat.md", "digest `cf19b7cf…`", "digest `cf19b7ce…`"),
     "docs/combat.md status line: combat-v1-candidate-3: digest cf19b7ce…"),
    # 6. the compiled-in manifest
    (sync.check_manifest, (sync.QDOJO, "QDOJO_DM_TIER_2_STAKE = 20000;", "QDOJO_DM_TIER_2_STAKE = 25000;"),
     "tier 2 stake 25000, demo-c3 has 20000"),
    (sync.check_manifest, (sync.LLMS, "commit window 9 ticks", "commit window 10 ticks"), "states ('10', '8')"),
    (sync.check_manifest, (sync.PROTOCOL, "64 waiting offers", "128 waiting offers"), "docs/protocol.md §7"),
    (sync.check_manifest, (sync.QDOJO, "QDOJO_DM_COMMIT_TICKS = 9;", "QDOJO_DM_COMMIT_TICKS = 10;"), "timing 1: 10/8"),
    (sync.check_manifest, (sync.QDOJO, "QDOJO_DM_FEES = 2;", "QDOJO_DM_FEES = 3;"), "3 fee profiles and tiers"),
    (sync.check_manifest, (sync.QDOJO, "QDOJO_DM_FEE_2_RAKE_BPS = 1000;", "QDOJO_DM_FEE_2_RAKE_BPS = 900;"),
     "fee profile 2 (rake, house, dev, share bps) (900,"),
    (sync.check_manifest, (sync.QDOJO, "QDOJO_DM_COOLDOWN_TICKS = 240;", "QDOJO_DM_COOLDOWN_TICKS = 241;"),
     "QDOJO_DM_COOLDOWN_TICKS is 241, devnet demo-c3 has 240"),
    (sync.check_manifest, (sync.QDOJO, "QDOJO_DM_ADMIN_0 = 0x012fe519b42f69e5ULL;",
                           "QDOJO_DM_ADMIN_0 = 0x012fe519b42f69e6ULL;"), "ADMIN identity"),
    (sync.check_manifest, (sync.PORT, "CAP_FIGHTERS = 1024;", "CAP_FIGHTERS = 2048;"),
     "combat_contract.h: CAP_FIGHTERS is 2048"),
    (sync.check_manifest, (sync.QDOJO, "QDOJO_CAP_FIGHTERS = 1024;", "QDOJO_CAP_FIGHTERS = 2048;"),
     "QDOJO.h: QDOJO_CAP_FIGHTERS is 2048"),
    (sync.check_manifest, (sync.README, "timing 9/8, tiers", "timing 9/7, tiers"), "qubic/README.md: states ('9', '7'"),
    (sync.check_manifest, ("docs/testnet.md", "(timing 9/8, tiers", "(timing 9/7, tiers"),
     "testnet.md: states ('9', '7'"),
    (sync.check_manifest, ("docs/combat.md", "(commit 9, reveal 8 ticks)", "(commit 9, reveal 7 ticks)"),
     "combat.md: states ('9', '7')"),
    # 7. NFT backends and ownership opcodes
    (sync.check_nft, (sync.NFT_MD, "| AdminMirrorOwner: the QBAY NFT", "| AdminBindAsset: the QBAY NFT"),
     "AdminBindAsset 104"),
    (sync.check_nft, (sync.NFT_MD, "`nft_backend: sim | qubic | qbay-mirror`", "`nft_backend: sim | qbay-mirror`"),
     "§5 lists backends"),
    (sync.check_nft, (sync.QDOJO, "QDOJO_MIRROR_SOURCE_QBAY = 12;", "QDOJO_MIRROR_SOURCE_QBAY = 13;"),
     "QDOJO_MIRROR_SOURCE_QBAY is 13"),
    (sync.check_nft, ("packages/qdojo/src/qdojo/combat/nft.py", 'if name == "qubic":', 'if name == "qubic-v2":'),
     "nft.make_backend builds"),
    (sync.check_nft, (sync.NFT_MD, "| `sim`, `qubic` |", "| `sim`, `qubik` |"),
     "backend qubik is not in live.NFT_BACKENDS"),
    (sync.check_nft, (sync.NFT_MD, "| `sim`, `qubic` |", "| `sim` |"), "covers backends ['qbay-mirror', 'sim']"),
    (sync.check_nft, (sync.NFT_MD, "| 103 | `combat/live.py` |", "| 103 | `combat/lives.py` |"),
     "sender lives.py is not a file"),
    (sync.check_nft, (sync.NFT_MD, "| 100 | `combat/devnet.py` |", "| 100 | `combat/nft.py` |"),
     "nft.py never sends Op.ADMIN_REGISTER_ASSET"),
    (sync.check_nft, (sync.NFT_MD, "| — (simulated devnets, practice, old journals) | AdminRegisterAsset: the interim "
                                   "asset (issuer = fighter id, name `QDOJOF`) | 100 | `combat/devnet.py` |\n", ""),
     "does not list the ownership opcodes [100]"),
    (sync.check_nft, (sync.PORT, "MIRROR_SOURCE_QBAY = 12;", "MIRROR_SOURCE_QBAY = 13;"),
     "combat_contract.h: MIRROR_SOURCE_QBAY is 13"),
    (sync.check_nft, (sync.PROTOCOL, "the only accepted source is 12 (QBAY)", "the only accepted source is 13 (QBAY)"),
     "states mirror source 13"),
]


@pytest.mark.parametrize("check,edit,expect", MUTATIONS, ids=[f"{m[0].__name__}-{i}" for i, m in enumerate(MUTATIONS)])
def test_drift_is_named(check, edit, expect):
    assert run(check) == [], f"{check.__name__} fails without any edit"
    errors = run(check, [edit])
    assert any(expect in e for e in errors), f"expected '{expect}' in {errors}"
