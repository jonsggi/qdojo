"""Check active documentation links and candidate artifact shape."""
from pathlib import Path
import json,re
ROOT=Path(__file__).resolve().parents[2]
paths=[ROOT/"README.md",ROOT/"apps/web/AVATARS.md",ROOT/"examples/README.md",
       ROOT/"apps/web/data/README.md",ROOT/"audits/README.md",ROOT/"prompts/README.md"]
paths += sorted((ROOT/"docs").glob("*.md"))
paths += sorted((ROOT/"docs/archive").glob("*.md"))
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
        if len(cells)==len(names)+1 and cells[0] in names and all(x.isdigit() for x in cells[1:]):
            rows.append([int(x) for x in cells[1:]])
    return rows
# Every packaged ruleset: artifact shape, and its Markdown matrix in combat.md
# (candidate 1 in sections 1-10, candidate 2 in section 11, candidate 3 in 12).
combat=(ROOT/"docs/combat.md").read_text()
s2=combat.index("## 11. Candidate 2")
s3=combat.index("## 12. Candidate 3")
for name,text in (("combat-v1.json",combat[:s2]),("combat-v1-candidate-2.json",combat[s2:s3]),
                  ("combat-v1-candidate-3.json",combat[s3:])):
    rules=json.loads((ROOT/"docs"/name).read_text())
    n=len(rules["action_names"])
    assert rules["rounds"]==3 and rules["beats_per_round"]==6
    assert rules["submitted_action_ids"]==[i for i in range(n) if rules["action_names"][i]!="EXHAUSTED"]
    assert len(rules["damage"])==n and all(len(row)==n for row in rules["damage"])
    assert all(type(v) is int and v>=0 for row in rules["damage"] for v in row)
    # Cross-check the normative Markdown matrix against the machine artifact.
    assert matrix_rows(text,rules["action_names"])==rules["damage"],"Markdown/artifact damage matrix mismatch: "+name
# Candidate 1's §2 state table and §4 action table against the artifact
# (the costs and initial values the prose tables state).
c1=json.loads((ROOT/"docs/combat-v1.json").read_text())
for field in ("hp","stamina","opening","guard_streak","power_available"):
    m=re.search(r"^\| "+field+r" \| (\d+) \|",combat[:s2],re.M)
    assert m and int(m.group(1))==c1["initial"][field],"combat.md §2 initial "+field+" differs from combat-v1.json"
for i,name in enumerate(c1["action_names"]):
    m=re.search(r"^\| (?:internal )?"+str(i)+r" \| "+name+r" \| (\d+)",combat[:s2],re.M)
    assert m and int(m.group(1))==c1["base_costs"][i],"combat.md §4 cost of "+name+" differs from combat-v1.json"
m=re.search(r"\| 2 \| BLOCK \| (\d+) \+ (\d+)\*guard_streak",combat[:s2])
assert m and (int(m.group(1)),int(m.group(2)))==(c1["base_costs"][2],c1["block_streak_cost"]),"combat.md §4 BLOCK cost"
assert not errors,"Broken active links:\n"+"\n".join(errors)
print("Active document links passed:",len(paths),"files; candidate 1, 2 and 3 matrices and the candidate-1 state and cost tables passed.")
