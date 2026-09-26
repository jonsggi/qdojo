import json,csv,sys,collections
S=sys.argv[1]; O=sys.argv[2]
d=json.load(open(S+"/data.json"))
lineup={e["label"]:e for e in json.load(open(S+"/lineup-arena.json"))}
with open(O+"/fights.csv","w",newline="") as fh:
    w=csv.writer(fh); w.writerow(["fight_id","contest_id","mode","A","B","rating_A","rating_B","kind","winner","result","stage","end_tick","rounds","beats","hp_A","hp_B"])
    for f in d["fights"]:
        r=f["result"] or {}
        e=f["rounds"][-1]["end"] if f["rounds"] else {"A":{"hp":""},"B":{"hp":""}}
        w.writerow([f["fight"],f["contest"],f["mode"],f["A"],f["B"],f["ratingA"],f["ratingB"],r.get("kind",""),r.get("winner") or "",r.get("result") or "",r.get("stage",""),r.get("tick",""),len(f["rounds"]),sum(x["executed"] for x in f["rounds"]),e["A"]["hp"],e["B"]["hp"]])
st=collections.defaultdict(collections.Counter)
for f in d["fights"]:
    r=f["result"]
    if not r: continue
    for s in "AB":
        me=st[f[s]]; me["fights"]+=1; me[f["mode"]]+=1
        k=r["kind"]
        if k=="COMBAT": me["W" if r["winner"]==s else "D" if r["winner"] is None else "L"]+=1
        elif k=="FORFEIT": me["forfeit_win" if r["winner"]==s else "forfeit_loss"]+=1
        elif k=="DOUBLE_FAULT": me["double_fault"]+=1
with open(O+"/fighters.csv","w",newline="") as fh:
    w=csv.writer(fh); w.writerow(["fighter","driver","founding","cups","duels","ranked","lifetime_rating","placement","fights","ranked_fights","duel_fights","cup_fights","W","D","L","combat_score","forfeit_wins","forfeit_losses","double_faults","forfeit_loss_pct","owner_now"])
    for k,v in sorted(st.items(),key=lambda x:-d["fighters"][x[0]]["lifetime"]):
        e=lineup[k]; drv=("llm:"+e["llm"]["model"]) if "llm" in e else e["policy"]
        cm=v["W"]+v["D"]+v["L"]
        w.writerow([k,drv,e.get("founding",False),e.get("cups",False),e.get("duels",False),e.get("ranked",True),d["fighters"][k]["lifetime"],d["fighters"][k]["placement"],v["fights"],v["ranked"],v["duel"],v["cup"],v["W"],v["D"],v["L"],round((v["W"]+.5*v["D"])/cm,3) if cm else "",v["forfeit_win"],v["forfeit_loss"],v["double_fault"],round(100*v["forfeit_loss"]/v["fights"],1),d["fighters"][k]["owner"]])
print("ok")
