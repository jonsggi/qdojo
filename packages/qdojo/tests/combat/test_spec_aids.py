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
