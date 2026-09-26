import json,collections,sys,statistics as stt
S=sys.argv[1]
d=json.load(open(S+"/data.json"))
lineup={e["label"]:e for e in json.load(open(S+"/lineup-arena.json"))}
eff={"reader-v1":"mixed-v1*","repeat-last-winner":"mixed-v1*","search-v1":"search-blind*"}
def drv(l):
    e=lineup[l]
    if "llm" in e: return "LLM"
    return eff.get(e["policy"],e["policy"])
comb=[f for f in d["fights"] if f["result"] and f["result"]["kind"]=="COMBAT"]
# driver-vs-driver score matrix (all modes)
M=collections.defaultdict(list)
for f in comb:
    w=f["result"]["winner"]
    for s,o in (("A","B"),("B","A")):
        M[(drv(f[s]),drv(f[o]))].append(1 if w==s else .5 if w is None else 0)
ds=sorted({k[0] for k in M})
print("row score vs column (n)")
print(f"{'':20}"+"".join(f"{c[:11]:>13}" for c in ds))
for r in ds:
    print(f"{r:20}"+"".join(f"{stt.mean(M[(r,c)]):7.2f}({len(M[(r,c)]):4})" if M[(r,c)] else f"{'-':>13}" for c in ds))
# per-round HP differential by driver
print("\nmean HP differential (dealt-taken) per round, by fighter")
H=collections.defaultdict(lambda: collections.defaultdict(list))
for f in comb:
    for r in f["rounds"]:
        for s,o in (("A","B"),("B","A")):
            dealt=sum(b[s]["dmg"] for b in r["beats"]); taken=sum(b[o]["dmg"] for b in r["beats"])
            H[f[s]][r["ri"]].append(dealt-taken)
for k in sorted(H, key=lambda k: drv(k)):
    print(f" {k:9} {drv(k):20} "+" ".join(f"R{i+1} {stt.mean(H[k][i]):+6.2f}(n{len(H[k][i])})" for i in range(3) if H[k][i]))
