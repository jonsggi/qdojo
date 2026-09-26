import json,collections,sys,statistics as stt
d=json.load(open(sys.argv[1]+"/data.json"))
C=collections.Counter
lineup={e["label"]:e for e in json.load(open(sys.argv[1]+"/lineup-arena.json"))}
drv=lambda l: ("llm:"+lineup[l]["llm"]["model"].split("/")[1]) if "llm" in lineup[l] else lineup[l]["policy"]
comb=[f for f in d["fights"] if f["result"] and f["result"]["kind"]=="COMBAT"]
ACTS=["JAB","KICK","BLOCK","DUCK","THROW","RECOVER"]
# executed effective action frequency overall and by round
eff=C(); effr=collections.defaultdict(C); intended=C()
exh=0; tot=0
for f in comb:
    for r in f["rounds"]:
        for b in r["beats"]:
            for s in "AB":
                eff[b[s]["e"]]+=1; effr[r["ri"]][b[s]["e"]]+=1; tot+=1
                if b[s]["e"]=="EXHAUSTED": exh+=1
print("== effective action share, all COMBAT fights (executed beats)")
print({a:round(100*eff[a]/tot,1) for a in ACTS+["EXHAUSTED"]})
for ri in (0,1,2):
    t=sum(effr[ri].values()); print(" round",ri+1,{a:round(100*effr[ri][a]/t,1) for a in ACTS+["EXHAUSTED"]})
# damage dealt per action (executed) and "value": mean dmg dealt minus mean dmg taken when playing it
dd=collections.defaultdict(list); dt=collections.defaultdict(list)
for f in comb:
    for r in f["rounds"]:
        for b in r["beats"]:
            for s,o in (("A","B"),("B","A")):
                a=b[s]["e"]; dd[a].append(b[s]["dmg"]); dt[a].append(b[o]["dmg"])
print("\n== per executed action: mean dmg dealt, mean dmg taken, net")
for a in ACTS+["EXHAUSTED"]:
    print(f" {a:9} dealt {stt.mean(dd[a]):5.2f} taken {stt.mean(dt[a]):5.2f} net {stt.mean(dd[a])-stt.mean(dt[a]):+5.2f}  n={len(dd[a])}")
# pair matrix frequency
pm=C()
for f in comb:
    for r in f["rounds"]:
        for b in r["beats"]:
            pm[tuple(sorted((b["A"]["e"],b["B"]["e"])))]+=1
print("\ntop beat pairings:",[(k,round(100*v/sum(pm.values()),1)) for k,v in pm.most_common(12)])
# power usage
pw_used=pw_wasted=pw_none=0; pwdmg=0; pw_round=C()
op_earned=op_used=0; opdmg=0
for f in comb:
    for s in "AB":
        used=False
        for r in f["rounds"]:
            ps=r["psA"] if s=="A" else r["psB"]
            if ps>=0:
                used=True; pw_round[r["ri"]]+=1
                if ps < r["executed"]:
                    b=r["beats"][ps][s]
                    if b["pb"]>0: pw_used+=1; pwdmg+=b["pb"]
                    else: pw_wasted+=1
                else: pw_wasted+=1
            for b in r["beats"]:
                if b[s]["ob"]>0: op_used+=1; opdmg+=b[s]["ob"]
        if not used: pw_none+=1
n=2*len(comb)
print(f"\n== power: fighter-fights {n}; power landed {100*pw_used/n:.1f}%, wasted/blocked/unexecuted {100*pw_wasted/n:.1f}%, never used {100*pw_none/n:.1f}%; power by round {dict(pw_round)}")
print(f"opening bonus hits per fighter-fight {op_used/n:.2f}; bonus dmg per fight-side: opening {opdmg/n:.2f}, power {pwdmg/n:.2f}")
print(f"exhausted beats {100*exh/tot:.2f}%")
# per driver action mix & win rates in ranked
print("\n== per fighter: action mix (executed) and combat score (all modes)")
mix=collections.defaultdict(C); score=collections.defaultdict(list)
for f in comb:
    w=f["result"]["winner"]
    for s in "AB":
        for r in f["rounds"]:
            for b in r["beats"]: mix[f[s]][b[s]["e"]]+=1
        score[f[s]].append(1 if w==s else .5 if w is None else 0)
for k in sorted(mix,key=lambda k:-stt.mean(score[k])):
    t=sum(mix[k].values())
    print(f" {k:9} {drv(k):22} score {stt.mean(score[k]):.3f} n={len(score[k]):4} "+" ".join(f"{a[:2]}{100*mix[k][a]/t:4.0f}" for a in ACTS+["EXHAUSTED"]))
# win rate by action mix: per fighter-fight share of each action vs outcome (logistic-free: bucket)
print("\n== score by share of an action in own executed beats (fighter-fight level)")
rows=[]
for f in comb:
    w=f["result"]["winner"]
    for s in "AB":
        m=C(); 
        for r in f["rounds"]:
            for b in r["beats"]: m[b[s]["e"]]+=1
        t=sum(m.values()); sc=1 if w==s else .5 if w is None else 0
        rows.append(({a:m[a]/t for a in ACTS+["EXHAUSTED"]},sc))
for a in ACTS:
    bk=collections.defaultdict(list)
    for sh,sc in rows:
        b=min(4,int(sh[a]*10)); bk[b].append(sc)
    print(f" {a:8}", " ".join(f"[{b*10}-{b*10+10}%]:{stt.mean(v):.2f}(n{len(v)})" for b,v in sorted(bk.items())))
