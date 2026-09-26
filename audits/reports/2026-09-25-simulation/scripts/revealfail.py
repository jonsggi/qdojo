import pickle,sys,json,glob,collections
from qdojo.combat import codec
from qdojo.combat.engine import validate_plan
from qdojo.combat.types import PlanError
from qdojo.combat.chainsim import AssetRegistry
from qdojo.combat.sim import identity
from qdojo.hashing import sha256
S=sys.argv[1]
w=pickle.load(open(S+"/world.pkl","rb")); c=w.contract; R=c.m.ruleset
iss=identity("qdojo-sim-issuer")
for label in sys.argv[2:]:
    fid=sha256(b"qdojo/combat/sim-asset/v1\0", iss, b"QDOJOF", label.encode())
    recs={}
    for p in glob.glob(f"{S}/arena/bots/{label}/*/secret-plans.jsonl"):
        for l in open(p):
            try: r=json.loads(l)
            except: continue
            recs[(r["fight_id"],r["round"])]=r
    why=collections.Counter(); ex=[]
    for f in c.fights.values():
        if not f.result or f.result["kind"] not in ("FORFEIT","DOUBLE_FAULT"): continue
        slot=f.slot_of(fid)
        if slot is None or f.result.get("winner")==slot: continue
        ri=f.state.round_index; r=recs.get((f.fight_id,ri))
        if r is None: why[f"no plan journalled ({f.result['stage']})"]+=1; continue
        plan=codec.decode_plan(bytes.fromhex(r["plan"]))
        st=f.state.a if slot=="A" else f.state.b
        try:
            validate_plan(R,st,plan); why[f"valid plan, stage {f.result['stage']}, status {r['status']}"]+=1
        except PlanError as e:
            why[f"INVALID: {str(e)[:60]}"]+=1; ex.append((f.fight_id,ri,[a.name for a in plan.actions],plan.power_slot,st.power_available))
    print(label, dict(why)); print("  e.g.",ex[:3])
