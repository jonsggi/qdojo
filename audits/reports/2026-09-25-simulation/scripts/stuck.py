import pickle,sys,collections
w=pickle.load(open(sys.argv[1]+"/world.pkl","rb")); c=w.contract; t=w.tick
live=[f for f in c.fights.values() if f.phase!="DONE"]
print("tick",t,"fights total",len(c.fights),"non-DONE",len(live))
past=[f for f in live if (f.phase=="COMMIT" and t>f.commit_last) or (f.phase=="REVEAL" and t>f.reveal_last)]
print("deadline passed:",len(past))
for f in sorted(live,key=lambda x:x.fight_id)[:40]:
    con=c.contests[f.contest_id]
    print(f.fight_id,f.phase,"r",f.state.round_index,"start",f.start_tick,"cl",f.commit_last,"rl",f.reveal_last,"commits",sorted(f.commits),"reveals",sorted(f.reveals),"mode",con.mode,con.status, "cup",getattr(con,'cup_id',None))
print(collections.Counter((c.contests[f.contest_id].mode, f.phase) for f in live))
print("fights_in_use",c.fights_in_use(), "max",c.m.max_fights)
print("contests active",collections.Counter(x.mode for x in c.contests.values() if x.status=="ACTIVE"))
print("cups",[(k.cup_id,k.status,k.reserved) for k in c.cups.values() if k.status in("RUNNING","REGISTRATION")])
