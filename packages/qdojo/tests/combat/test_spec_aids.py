"""The docs' own executable checks run in the suite, so drift fails `make test`."""
import filecmp
import runpy

import pytest

from qdojo.combat import rules as rules_mod

from .conftest import ROOT


def test_packaged_ruleset_is_the_documented_artifact():
    assert filecmp.cmp(ROOT / "docs/combat-v1.json",
                       rules_mod.RULESET_DIR / f"{rules_mod.CANDIDATE_1}.json", shallow=False)


def test_candidate_digest(rules):
    assert rules.digest.hex() == rules_mod.CANDIDATE_1_DIGEST


def test_docs_links_and_matrix():
    runpy.run_path(str(ROOT / "docs/reference/check_docs.py"))


def test_reference_hand_vectors(reference):
    reference.check()


def test_ruleset_rejects_drift():
    import json
    doc = json.loads((ROOT / "docs/combat-v1.json").read_text())
    for mutate in (lambda d: d.pop("power_cost"), lambda d: d.update(extra=1),
                   lambda d: d.update(power_cost=-1), lambda d: d.update(power_cost=1.5),
                   lambda d: d["damage"].pop(), lambda d: d.update(rounds=5)):
        bad = json.loads(json.dumps(doc))
        mutate(bad)
        with pytest.raises(rules_mod.RulesetError):
            rules_mod.parse(bad)
    changed = json.loads(json.dumps(doc))
    changed["power_cost"] = 5
    assert rules_mod.parse(changed).digest != rules_mod.parse(doc).digest


def test_frozen_fight_fixtures_match_engine():
    """The parity set for the C++ and browser engines must still be what this engine produces."""
    import importlib.util
    import json
    spec = importlib.util.spec_from_file_location("combat_fixtures", ROOT / "scripts/combat-fixtures.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    frozen = json.loads(next((ROOT / "packages/qdojo/tests/combat/fixtures").glob("fights-*.json")).read_text())
    _, fights, traced = mod.generate(len(frozen["fights"]), frozen["seed"])
    assert fights == frozen["fights"] and traced == frozen["traced"]


def manifest_from_header(head):
    from qdojo.combat.contract import Manifest
    from qdojo.combat.ledger import FeeProfile
    from qdojo.combat.rules import candidate_1
    return Manifest(
        bytes.fromhex(head["network_id"]), bytes.fromhex(head["contract_id"]), bytes.fromhex(head["admin"]),
        candidate_1(), {int(k): tuple(v) for k, v in head["timing"].items()},
        {int(k): FeeProfile(int(k), f["rake_bps"], f["house_bps"], f["dev_bps"], f["share_bps"],
                            bytes.fromhex(f["house"]), bytes.fromhex(f["dev"]), bytes.fromhex(f["share"]))
         for k, f in head["fees"].items()},
        {int(k): v for k, v in head["tiers"].items()},
        offer_lifetime=tuple(head["offer_lifetime"]),
        **{k: head[k] for k in ("genesis_tick", "genesis_epoch", "ticks_per_epoch", "season_start_epoch",
                                "season_epochs", "season_closeout_ticks", "max_fighters", "max_accounts",
                                "max_offers", "max_fights", "max_cups", "max_cup_entrants", "event_ring",
                                "match_interval", "cooldown_ticks", "faults_per_epoch")})


def test_contract_parity_journals_replay_to_their_digest():
    """The journals the C++ contract port replays must still match this reference."""
    from qdojo.combat import store
    paths = sorted((ROOT / "packages/qdojo/tests/combat/fixtures/contract").glob("*.journal"))
    assert len(paths) >= 3
    for path in paths:
        head, records = store.load(path)
        assert records[-1]["k"] == "digest"
        store.replay(manifest_from_header(head), head, records)     # raises on digest mismatch
