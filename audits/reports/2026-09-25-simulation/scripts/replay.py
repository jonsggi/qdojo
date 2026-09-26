import json, pickle, sys, time
sys.setrecursionlimit(100000)
from pathlib import Path
from qdojo.combat.devnet import manifest
from qdojo.combat.sim import World
S=Path(sys.argv[1])
t0=time.time()
recs=[json.loads(x) for x in (S/"arena/devnet.journal").read_text().splitlines() if x.strip()]
w=World.replay(manifest("demo"), recs)
print("replayed", len(recs), "tick", w.tick, "in", time.time()-t0)
w.check_conservation()
w.journal=[]
own=dict(w.owners); w.owners=own; w.contract.owner_of=own.get; w.transfer_fails=set(); w.contract.transfer=None
with open(S/"world.pkl","wb") as f: pickle.dump(w, f)
print("pickled")
