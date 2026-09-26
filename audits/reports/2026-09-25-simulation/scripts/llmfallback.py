import pickle,sys,json,copy,collections,hashlib
from qdojo.combat import codec, npcs, planner
from qdojo.combat.devnet import DevnetClient
from qdojo.combat.rules import candidate_1
from qdojo.combat.types import FighterState
from qdojo.combat.sim import identity
from qdojo.hashing import sha256
S=sys.argv[1]
w=pickle.load(open(S+"/world.pkl","rb")); c=w.contract; rules=candidate_1()
iss=identity("qdojo-sim-issuer")
class N: pass
n=N(); n.m=c.m; n.world=w
cl=DevnetClient(n, b"")
def fb(obs):
    me, opp = obs["self"], obs["opponent"]
    s = FighterState(me["hp"], me["stamina"], me["opening"], me["guard_streak"], int(me["power_available"]))
    o = FighterState(opp["hp"], opp["stamina"], opp["opening"], opp["guard_streak"], int(opp["power_available"]))
    seed = hashlib.sha256(json.dumps(obs, sort_keys=True).encode()).digest()
    return npcs.mixed_v1(rules, npcs.Observation(obs["round_index"], s, o), npcs.Stream(seed, 0, obs["round_index"]))
out={}
for label in sys.argv[2:]:
    fid=sha256(b"qdojo/combat/sim-asset/v1\0", iss, b"QDOJOF", label.encode())
    res=collections.Counter(); per=[]
    for f in list(c.fights.values()):
        slot=f.slot_of(fid)
        if slot is None: continue
        con=c.contests[f.contest_id]
        orig=(f.rounds,f.state,f.phase,f.start_tick,f.commit_last,f.reveal_last,f.commits,f.reveals)
        for ri,r in enumerate(orig[0]):
            start = r["start"]
            st = (orig[0][ri-1]["tick"] if ri>0 else None)
            if st is None:
                # round 0 start tick: first fight in contest starts at contest start, later ones at previous fight end
                idx=con.fights.index(f.fight_id)
                st = con.start_tick if idx==0 else c.fights[con.fights[idx-1]].result["tick"]
            revealed=codec.decode_plan(r["plans"][slot])
            hit=None
            for dt in range(1,6):
                f.rounds=orig[0][:ri]; f.state=start; f.phase="COMMIT"; f.start_tick=st; f.commit_last=st+24; f.reveal_last=st+36
                w.tick=st+dt; c.tick=st+dt
                obs=cl.fight(f.fight_id)["observation"](slot)
                if fb(obs)==revealed: hit=dt; break
            res["fallback" if hit else "model"]+=1
            per.append((f.fight_id,ri,bool(hit),r["tick"]))
        f.rounds,f.state,f.phase,f.start_tick,f.commit_last,f.reveal_last,f.commits,f.reveals=orig
    print(label, dict(res), "fallback share %.1f%%"%(100*res["fallback"]/max(1,sum(res.values()))))
    out[label]=per
json.dump(out,open(S+"/llm_rounds.json","w"))
