import json,collections,sys,statistics as stt
d=json.load(open(sys.argv[1]+"/data.json"))
C=collections.Counter
L=d["ledger"]
print("ledger balance",L["balance"],"paid_out",L["paid_out"],"escrow offers/contests/cups",L["escrow_offers"],L["escrow_contests"],L["escrow_cups"])
cr=L["credits"]
rake={k:cr.get(k,0) for k in ("house","dev","share")}
print("rake credits",rake,"total",sum(rake.values()))
# per fighter money flow from contests: stake paid by payer, credit received
net=collections.defaultdict(lambda: C())
for c in d["contests"]:
    if c["mode"]=="cup": continue
    for s in "AB":
        p=c["payers"].get(s)
        net[c[s]][c["mode"]+"_staked"]+=c["stake"]
        net[c[s]][c["mode"]+"_n"]+=1
    for who,v in c["credits"].items():
        # map owner/collector back to the fighter in this contest
        for s in "AB":
            if c["payers"].get(s)==who: net[c[s]][c["mode"]+"_returned"]+=v
# cups: entries and prizes
for k in d["cups"]:
    for e in k["entries"]:
        net[e]["cup_fees"]+=k["entry_fee"]
    if k["champion"]:
        gross=k["entry_fee"]*len(k["entries"])+k["sponsorship"]
        rakev=k["entry_fee"]*len(k["entries"])*500//10000
        net[k["champion"]]["cup_prize"]+=gross-rakev
print(f"\n{'fighter':9} {'rk_n':>5} {'rk_net':>9} {'rk/fight':>8} {'du_n':>5} {'du_net':>8} {'cup_fee':>8} {'cup_prize':>9} {'total':>9}")
tot=C(); rows=[]
for k,v in net.items():
    rk=v["ranked_returned"]-v["ranked_staked"]; du=v["duel_returned"]-v["duel_staked"]; cp=v["cup_prize"]-v["cup_fees"]
    rows.append((k,v["ranked_n"],rk,v["duel_n"],du,v["cup_fees"],v["cup_prize"],rk+du+cp))
for r in sorted(rows,key=lambda r:-r[-1]):
    print(f"{r[0]:9} {r[1]:5} {r[2]:9} {r[2]/max(r[1],1):8.1f} {r[3]:5} {r[4]:8} {r[5]:8} {r[6]:9} {r[7]:9}")
print("sum of player nets",sum(r[-1] for r in rows),"(minus escrow in flight)")
# sponsorship
print("cup sponsorship total",sum(k["sponsorship"] for k in d["cups"]), "per cup",C(k["sponsorship"] for k in d["cups"]))
# rake per ranked fight
rkc=[c for c in d["contests"] if c["mode"]=="ranked" and c["status"]=="DONE"]
print("ranked contests",len(rkc), C(c["result"]["kind"] for c in rkc))
print("minted",d["minted"])
ch=json.load(open(sys.argv[1]+"/arena/chain.json")); print("chain",ch)
hours=d["tick"]*1.5/3600
print(f"hours {hours:.1f}; exec fees burned/h {ch['burned']/hours:.0f}; rake/h {sum(rake.values())/hours:.0f}; house share/h {rake['house']/hours:.0f}")
