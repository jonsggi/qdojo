#!/usr/bin/env python3
"""Instruments for the builder beta and the human validation study
(docs/validation-protocol.md; logic in packages/qdojo/src/qdojo/study.py).

  # Readability (model.md §3): review sheets and an answer key from finished replays
  uv run python scripts/beta-study.py sample --export ~/.qdojo/combat/public/combat/v1 --reviewers 5 --seed 1 --out DIR
  uv run python scripts/beta-study.py score --dir DIR --answers answers.csv        # columns: reviewer,item,causes

  # The cohort log (docs/fixtures/beta-cohort-template.csv): aggregate, drop-offs included
  uv run python scripts/beta-study.py cohort cohort.csv

  # Adaptation: a builder fighter against a house bot that changed style at a known tick
  uv run python scripts/beta-study.py adaptation --db ~/.qdojo/combat/readmodel.sqlite \
      --fighter HEX --opponent HEX --switch-tick N

Every report prints aggregates only. Keep the cohort log and the answer files
off the public site and out of git: they hold pseudonyms, but they are study data.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "qdojo" / "src"))
from qdojo import study  # noqa: E402


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    s = p.add_subparsers(dest="cmd", required=True)
    a = s.add_parser("sample", help="review sheets and answer key from an export's replays")
    a.add_argument("--export", required=True, type=Path)
    a.add_argument("--reviewers", type=int, default=5)
    a.add_argument("--seed", type=int, default=0)
    a.add_argument("--out", required=True, type=Path)
    a = s.add_parser("score", help="score reviewers' answers against the key")
    a.add_argument("--dir", required=True, type=Path, help="the directory `sample` wrote")
    a.add_argument("--answers", required=True, type=Path)
    a = s.add_parser("cohort", help="aggregate the cohort log")
    a.add_argument("log", type=Path)
    a = s.add_parser("adaptation", help="score before and after an opponent's style switch")
    a.add_argument("--db", required=True, type=Path)
    a.add_argument("--fighter", required=True)
    a.add_argument("--opponent", required=True)
    a.add_argument("--switch-tick", required=True, type=int)
    a.add_argument("--window", type=int, default=5)
    a = p.parse_args(argv)

    if a.cmd == "sample":
        doc = study.sample_sheets(study.load_replays(a.export), a.reviewers, a.seed)
        a.out.mkdir(parents=True, exist_ok=True)
        (a.out / "sheets.json").write_text(json.dumps({"causes": doc["causes"], "sheets": doc["sheets"]}, indent=1))
        (a.out / "key.json").write_text(json.dumps(doc["key"], indent=1))
        lines = ["# Replay readability review", "", "Open each link on the site, find the exchange, and name its cause.",
                 "Items marked REDUCED MOTION: switch MOTION: OFF in the footer first.", "", "Causes:", ""]
        lines += [f"- `{k}`: {v}" for k, v in doc["causes"].items()]
        for rv in sorted({x["reviewer"] for x in doc["sheets"]}):
            lines += ["", f"## {rv}", ""]
            lines += [f"{x['item']}. fight {x['fight_id']} ({x['link']}), {x['where']}"
                      + (" — REDUCED MOTION" if x["reduced_motion"] else "") for x in doc["sheets"] if x["reviewer"] == rv]
        (a.out / "sheets.md").write_text("\n".join(lines) + "\n")
        print(json.dumps({k: doc[k] for k in ("pool", "pool_by_cause", "missing_required")}, indent=1))
        return 0
    if a.cmd == "score":
        sheets = json.loads((a.dir / "sheets.json").read_text())["sheets"]
        key = json.loads((a.dir / "key.json").read_text())
        print(json.dumps(study.score_answers(key, sheets, study.read_csv(a.answers)), indent=1))
        return 0
    if a.cmd == "cohort":
        print(json.dumps(study.cohort_report(study.read_csv(a.log)), indent=1))
        return 0
    if a.cmd == "adaptation":
        res = study.results_from_readmodel(a.db, a.fighter, a.opponent)
        print(json.dumps(study.adaptation(res, a.switch_tick, a.window), indent=1))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
