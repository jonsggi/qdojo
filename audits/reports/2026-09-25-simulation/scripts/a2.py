import json,collections,sys,statistics as stt
d=json.load(open(sys.argv[1]+"/data.json"))
C=collections.Counter
F=[f for f in d["fights"] if f["result"]]
comb=[f for f in F if f["result"]["kind"]=="COMBAT"]
def q(xs,p): xs=sorted(xs); return xs[min(len(xs)-1,int(p*len(xs)))]
print("== outcome shape (COMBAT fights) by mode")
for mode in ("ranked","duel","cup","all"):
    xs=[f for f in comb if mode=="all" or f["mode"]==mode]
    n=len(xs); res=C(f["result"]["result"] for f in xs)
    endr=C(len(f["rounds"]) for f in xs)
    r0ko=sum(1 for f in xs if len(f["rounds"])==1)
    reach2=sum(1 for f in xs if len(f["rounds"])==3)
    draws=sum(1 for f in xs if f["result"]["winner"] is None)
    # trailing after round 0 wins
    tr=trw=0; margins=[]; comebacks=[]
    for f in xs:
        r0=f["rounds"][0]["end"]; w=f["result"]["winner"]
        if len(f["rounds"])>1 and r0["A"]["hp"]!=r0["B"]["hp"]:
            tr+=1; lead="A" if r0["A"]["hp"]>r0["B"]["hp"] else "B"
            if w and w!=lead: trw+=1
        e=f["rounds"][-1]["end"]; margins.append(abs(e["A"]["hp"]-e["B"]["hp"]))
    beats=[sum(r["executed"] for r in f["rounds"]) for f in xs]
    print(f"{mode:6} n={n} KO {100*res['KO']/n:.1f}% dec(HP) {100*res['HP']/n:.1f}% dbl-KO {100*res['DOUBLE_KO']/n:.1f}% HP-tie {100*res['HP_TIE']/n:.1f}% | draws {100*draws/n:.1f}% | end in R1/R2/R3 {[round(100*endr[i]/n,1) for i in (1,2,3)]} | reach R3 {100*reach2/n:.1f}% | trailer-after-R1 wins {100*trw/max(tr,1):.1f}% ({trw}/{tr}) | beats med {stt.median(beats)} | final HP margin med {stt.median(margins)} ; margin<=8: {100*sum(m<=8 for m in margins)/n:.1f}%")
# KO beat
kob=C((len(f["rounds"]), f["rounds"][-1]["executed"]) for f in comb if f["result"]["result"] in("KO","DOUBLE_KO"))
print("KO at (round,beat):",sorted(kob.items()))
# decisions: HP margin distr
dec=[abs(f["rounds"][-1]["end"]["A"]["hp"]-f["rounds"][-1]["end"]["B"]["hp"]) for f in comb if f["result"]["result"]=="HP"]
print("decision margin quartiles",q(dec,.25),q(dec,.5),q(dec,.75))
# winner HP at KO
print("\n== pacing")
T=1.5
dur=[]; 
for f in F:
    # fight duration: from fight start to result
    pass
# contest durations for ranked singles
ctd=[]
for c in d["contests"]:
    if c["status"]=="DONE" and c["result"]:
        ctd.append((c["mode"],c["result"]["tick"]-c["start"],len(c["fights"])))
for mode in ("ranked","duel","cup"):
    xs=[x[1] for x in ctd if x[0]==mode]
    print(mode,"contest duration ticks: median",stt.median(xs),"p90",q(xs,.9),"=> seconds median",stt.median(xs)*T, "p90",q(xs,.9)*T, "fights/contest mean %.2f"%stt.mean([x[2] for x in ctd if x[0]==mode]))
# per round duration ticks: round tick - previous
rd=[]
for f in comb:
    prev=None
    for r in f["rounds"]:
        if prev is not None: rd.append(r["tick"]-prev)
        prev=r["tick"]
print("ticks between round resolutions median",stt.median(rd),"min",min(rd),"max",max(rd), "p90", q(rd,.9))
# ranked combat fight duration
rk=[]
for c in d["contests"]:
    if c["mode"]=="ranked" and c["result"] and c["result"]["kind"]=="COMBAT": rk.append(c["result"]["tick"]-c["start"])
print("ranked COMBAT fight ticks median",stt.median(rk),"p95",q(rk,.95),"-> s",stt.median(rk)*T,q(rk,.95)*T)
# idle gap per fighter between contests (ranked)
gaps=collections.defaultdict(list); last={}
for c in sorted(d["contests"],key=lambda c:c["start"]):
    for s in "AB":
        fi=c[s]
        if fi in last and last[fi] is not None: gaps[fi].append(c["start"]-last[fi])
    for s in "AB":
        last[c[s]]=c["result"]["tick"] if c["result"] else None
print("idle gap between a fighter's contests (ticks): median per fighter")
print({k:stt.median(v) for k,v in sorted(gaps.items()) if v})
allg=[g for v in gaps.values() for g in v]; print("all median",stt.median(allg),"p90",q(allg,.9))
# concurrency: fights alive per tick
print("fights per hour (all modes): %.1f"%(len(F)/(d['tick']*T/3600)))
