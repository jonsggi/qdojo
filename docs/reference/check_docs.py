"""Check active documentation links and candidate artifact shape."""
from pathlib import Path
import json,re
ROOT=Path(__file__).resolve().parents[2]
paths=[ROOT/"README.md",ROOT/"apps/web/AVATARS.md",ROOT/"examples/README.md",
       ROOT/"apps/web/data/README.md",ROOT/"audits/README.md",ROOT/"prompts/README.md"]
paths += sorted((ROOT/"docs").glob("*.md"))
paths += sorted((ROOT/"docs/archive").glob("*.md"))
paths += [ROOT/"docs/archive/riddle-v0/INDEX.md"]
errors=[]
for p in paths:
    text=p.read_text()
    for target in re.findall(r"\]\(([^)]+)\)",text):
        if "://" in target or target.startswith("mailto:") or target.startswith("#"):
            continue
        target=target.split("#",1)[0].split(" ",1)[0]
        if target and not (p.parent/target).resolve().exists():
            errors.append(str(p.relative_to(ROOT))+": "+target)
def matrix_rows(text, names):
    rows=[]
    for line in text.splitlines():
        cells=[part.strip() for part in line.split("|")[1:-1]]
        if len(cells)==8 and cells[0] in names and all(x.isdigit() for x in cells[1:]):
            rows.append([int(x) for x in cells[1:]])
    return rows
# Every packaged ruleset: artifact shape, and its Markdown matrix in combat.md
# (candidate 1 in sections 1-10, candidate 2 in its own section 11).
combat=(ROOT/"docs/combat.md").read_text()
split=combat.index("## 11. Candidate 2")
for name,text in (("combat-v1.json",combat[:split]),("combat-v1-candidate-2.json",combat[split:])):
    rules=json.loads((ROOT/"docs"/name).read_text())
    assert rules["rounds"]==3 and rules["beats_per_round"]==6
    assert rules["submitted_action_ids"]==list(range(6))
    assert len(rules["damage"])==7 and all(len(row)==7 for row in rules["damage"])
    assert all(type(n) is int and n>=0 for row in rules["damage"] for n in row)
    # Cross-check the normative Markdown matrix against the machine artifact.
    assert matrix_rows(text,rules["action_names"])==rules["damage"],"Markdown/artifact damage matrix mismatch: "+name
assert not errors,"Broken active links:\n"+"\n".join(errors)
print("Active document links passed:",len(paths),"files; candidate 1 and 2 matrices passed.")
