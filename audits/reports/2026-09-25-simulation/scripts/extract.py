import pickle,sys,json,collections
from qdojo.combat import codec
from qdojo.combat.engine import resolve_round
from qdojo.combat.chainsim import AssetRegistry
from qdojo.combat.sim import identity
from qdojo.combat.devnet import roles
from qdojo.hashing import sha256
S=sys.argv[1]
w=pickle.load(open(S+"/world.pkl","rb")); c=w.contract; R=c.m.ruleset
lineup=json.load(open(S+"/lineup-arena.json"))
iss=identity("qdojo-sim-issuer")
lab={}; info={}
for e in lineup:
    fid=sha256(b"qdojo/combat/sim-asset/v1\0", iss, b"QDOJOF", e["label"].encode()); lab[fid]=e["label"]; info[e["label"]]=e
who={}
for e in lineup: who[identity("demo-owner:"+e["label"])]="owner:"+e["label"]
for i in range(1,200): who[identity(f"demo-collector:{i}")]=f"collector:{i}"
for k,v in roles().items(): who[v]=k
M={0:"ranked",1:"duel",2:"cup"}
fights=[]
for fid,f in sorted(c.fights.items()):
    con=c.contests[f.contest_id]
    A=lab.get(f.context.participant_a.fighter_id,"?"); B=lab.get(f.context.participant_b.fighter_id,"?")
    rounds=[]
    for r in f.rounds:
        pa=codec.decode_plan(r["plans"]["A"]); pb=codec.decode_plan(r["plans"]["B"])
        res=resolve_round(R, r["start"], pa, pb)
        beats=[]
        for bt in res.beats:
            beats.append({s:{"i":sd.intended.name,"e":sd.effective.name,"pw":sd.power,"dmg":sd.computed_damage,"lost":sd.actual_hp_lost,"ob":sd.opening_bonus,"pb":sd.power_bonus,"st":sd.before.stamina} for s,sd in (("A",bt.a),("B",bt.b))})
        rounds.append({"ri":r["round_index"],"tick":r["tick"],"planA":[a.name for a in pa.actions],"psA":pa.power_slot,"planB":[a.name for a in pb.actions],"psB":pb.power_slot,
            "start":{"A":r["start"].a.to_json(),"B":r["start"].b.to_json()},"end":{"A":res.end.a.to_json(),"B":res.end.b.to_json()},"executed":res.executed,"beats":beats})
    first=con.start_tick
    fights.append({"fight":fid,"contest":f.contest_id,"mode":M[int(con.mode)],"fmt":int(con.fmt),"cup":con.cup_id,"A":A,"B":B,
       "created":f.rounds[0]["tick"] if False else None,"result":f.result,"rounds":rounds,
       "ratingA":f.context.participant_a.lifetime_rating,"ratingB":f.context.participant_b.lifetime_rating,"contest_start":con.start_tick})
contests=[]
for cid,con in sorted(c.contests.items()):
    contests.append({"contest":cid,"mode":M[int(con.mode)],"fmt":int(con.fmt),"stake":con.stake,"A":lab.get(con.a.fighter_id),"B":lab.get(con.b.fighter_id),
      "start":con.start_tick,"status":con.status,"result":con.result,"fights":con.fights,"cup":con.cup_id,"replay":con.replay,
      "credits":{who.get(k,k.hex()[:8]):v for k,v in (con.settlement or {}).get("credits",{}).items()},
      "ratings":(con.settlement or {}).get("ratings"),"payers":{s:who.get(p,p.hex()[:8]) for s,p in con.payers.items()}})
fighters={}
for fid,f in c.fighters.items():
    fighters[lab.get(fid,fid.hex()[:8])]={"lifetime":f.lifetime,"placement":f.placement,"record":f.record,"faults":{str(k):v for k,v in f.faults.items()},
      "season_rating":{str(k):v for k,v in f.season_rating.items()},"owner":who.get(f.owner,f.owner.hex()[:8]),"lock":f.lock,"suspended_epoch":f.suspended_epoch,
      "season_stats":{str(s):{k:(len(v) if isinstance(v,set) else v) for k,v in st.items()} for s,st in f.season_stats.items()}}
cups=[]
for k in c.cups.values():
    cups.append({"cup":k.cup_id,"status":k.status,"created":k.created_tick,"entries":[lab.get(x) for x in k.entries],"champion":lab.get(k.champion),"levels":k.levels,
      "sponsorship":k.sponsorship,"entry_fee":k.descriptor["entry_fee"],"combat_fights":k.combat_fights,"postponed":sorted(k.postponed),"expiry":k.expiry_tick,
      "pairings":[{"id":p.pairing_id,"level":p.level,"a":lab.get(p.a),"b":lab.get(p.b),"status":p.status,"winner":lab.get(p.winner),"checked":[lab.get(x) for x in p.checked],"contest":p.contest_id} for p in k.pairings.values()]})
offers=[{"id":o.offer_id,"kind":o.kind,"f":lab.get(o.fighter_id),"opp":lab.get(o.opponent_id) if o.opponent_id else None,"amount":o.amount,"status":o.status,"created":o.created_tick,"expires":o.expires_tick,"contest":getattr(o,"contest_id",None),"rating":o.rating} for o in c.offers.values()]
ledger={"credits":{who.get(k,k.hex()[:8]):v for k,v in c.ledger.credits.items()},"balance":c.ledger.balance,"paid_out":c.ledger.paid_out,
   "escrow_offers":sum(a for _,a in c.ledger.offers.values()),"escrow_contests":sum(sum(v.values()) for v in c.ledger.contests.values()),"escrow_cups":sum(sum(v.values()) for v in c.ledger.cups.values())}
balances={who.get(k,k.hex()[:8]):v for k,v in w.balances.items()}
mints=collections.Counter()
events=collections.Counter(e[2] for e in c.events)
out={"tick":w.tick,"fights":fights,"contests":contests,"fighters":fighters,"cups":cups,"offers":offers,"ledger":ledger,"balances":balances,"minted":w.minted,
     "generation":c.generation,"event_seq":c.event_seq,"pair_starts":len(c.pair_starts),"season_now":c.m.season(w.tick),"epoch_now":c.m.epoch(w.tick)}
json.dump(out,open(S+"/data.json","w"))
print("ok",len(fights),len(contests),len(offers),len(cups), "generation",c.generation)
