import json,collections,sys
d=json.load(open(sys.argv[1]+"/data.json"))
F=[f for f in d["fights"] if f["result"]]
print("tick",d["tick"],"fights done",len(F),"of",len(d["fights"]))
C=collections.Counter
print("by mode",C(f["mode"] for f in F))
print("kind by mode",sorted(C((f["mode"],f["result"]["kind"],f["result"].get("result"),f["result"].get("stage")) for f in F).items()))
# per fighter
st=collections.defaultdict(lambda: C())
for f in F:
    r=f["result"]; k=r["kind"]
    for s,o in (("A","B"),("B","A")):
        me=f[s]; m=f["mode"]
        st[me]["fights"]+=1; st[me][m]+=1
        if k=="COMBAT":
            st[me]["W" if r["winner"]==s else "D" if r["winner"] is None else "L"]+=1
        elif k=="FORFEIT":
            st[me]["FW" if r["winner"]==s else "FL"]+=1
            if r["winner"]!=s: st[me]["FL_"+r["stage"]]+=1
        elif k=="DOUBLE_FAULT": st[me]["DF"]+=1
        else: st[me][k]+=1
print(f"{'fighter':10} {'fights':>6} {'rank':>5} {'duel':>5} {'cup':>5} {'W':>5} {'D':>4} {'L':>5} {'win%':>6} {'FW':>4} {'FL':>4} {'FL%':>6} {'DF':>3}")
for k,v in sorted(st.items(), key=lambda x:-x[1]["fights"]):
    cm=v["W"]+v["D"]+v["L"]
    print(f"{k:10} {v['fights']:6} {v['ranked']:5} {v['duel']:5} {v['cup']:5} {v['W']:5} {v['D']:4} {v['L']:5} {100*(v['W']+.5*v['D'])/max(cm,1):6.1f} {v['FW']:4} {v['FL']:4} {100*v['FL']/v['fights']:6.1f} {v['DF']:3}  {dict((a,b) for a,b in v.items() if a.startswith('FL_'))}")
print()
for k,v in sorted(d["fighters"].items(), key=lambda x:-x[1]["lifetime"]):
    print(k, v["lifetime"], v["record"], "faults",sum(v["faults"].values()), "owner",v["owner"], "placement", v["placement"], "seasonR", v["season_rating"])
