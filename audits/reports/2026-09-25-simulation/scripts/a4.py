import json,collections,sys,statistics as stt
d=json.load(open(sys.argv[1]+"/data.json"))
C=collections.Counter
print("== cups")
print(C(k["status"] for k in d["cups"]))
print("champions",C(k["champion"] for k in d["cups"]))
print("entrants per cup",C(len(k["entries"]) for k in d["cups"]))
print("entries by fighter",C(e for k in d["cups"] for e in k["entries"]))
print("pairing statuses",C(p["status"] for k in d["cups"] for p in k["pairings"]))
print("postponed",[k["cup"] for k in d["cups"] if k["postponed"]])
for k in d["cups"][-3:]: print(" cup",k["cup"],k["status"],"created",k["created"],"entries",k["entries"],"champ",k["champion"],"levels",k["levels"],"combat fights",k["combat_fights"])
# cup timing
cupend={}
for c in d["contests"]:
    if c["mode"]=="cup" and c["result"]: cupend[c["cup"]]=max(cupend.get(c["cup"],0),c["result"]["tick"])
dur=[cupend[k["cup"]]-k["created"] for k in d["cups"] if k["status"]=="COMPLETE" and k["cup"] in cupend]
print("cup created->last fight ticks median",stt.median(dur) if dur else None, "=> min",stt.median(dur)*1.5/60 if dur else None)
print("\n== duels")
du=[o for o in d["offers"] if o["kind"]=="DUEL"]
print("duel offers",len(du),C(o["status"] for o in du))
dc=[c for c in d["contests"] if c["mode"]=="duel"]
print("duel contests",len(dc),"formats",C(c["fmt"] for c in dc),"stakes",C(c["stake"] for c in dc))
print("duel results",C((c["result"] or {}).get("kind") for c in dc), "series draws", sum(1 for c in dc if c["result"] and c["result"]["kind"]=="COMBAT" and c["result"]["winner"] is None))
w=C(); l=C()
for c in dc:
    if not c["result"]: continue
    win=c["result"].get("winner")
    if win: w[c[win]]+=1; l[c["B" if win=="A" else "A"]]+=1
print("duel series wins",dict(w),"losses",dict(l))
print("\n== ranked matchmaking")
rk=[o for o in d["offers"] if o["kind"]=="RANKED"]
print("ranked offers",len(rk),C(o["status"] for o in rk))
# wait time created->matched: use contest start of matched offers
cs={c["contest"]:c for c in d["contests"]}
waits=[cs[o["contest"]]["start"]-o["created"] for o in rk if o["status"]=="MATCHED" and o.get("contest") in cs]
if waits: print("queue wait ticks median",stt.median(waits),"p90",sorted(waits)[int(.9*len(waits))], "max",max(waits))
pairs=C(tuple(sorted((c["A"],c["B"]))) for c in d["contests"] if c["mode"]=="ranked")
print("distinct ranked pairs",len(pairs),"top",pairs.most_common(8))
gap=[abs(f["ratingA"]-f["ratingB"]) for f in d["fights"] if f["mode"]=="ranked"]
print("rating gap at match median",stt.median(gap),"p90",sorted(gap)[int(.9*len(gap))],"max",max(gap))
