"""Executable specification aid, not production gameplay or proof of balance.

Run with --check for hand-derived vectors and --smoke for a small illustrative
baseline tournament. The independent production implementations still need the
full docs/model.md acceptance campaign.
"""
from __future__ import annotations
import argparse
from dataclasses import dataclass, asdict, replace
import hashlib
import json
from pathlib import Path

RULES = json.loads((Path(__file__).resolve().parents[1] / "combat-v1.json").read_text())
JAB, KICK, BLOCK, DUCK, THROW, RECOVER, EXHAUSTED = range(7)
ATTACKS = (JAB, KICK, THROW)

@dataclass(frozen=True)
class State:
    hp: int = 100
    stamina: int = 60
    opening: int = 0
    guard_streak: int = 0
    power_available: int = 1

    def validate(self):
        for name, cap in (("hp", 100), ("stamina", 60), ("opening", 1),
                          ("guard_streak", 3), ("power_available", 1)):
            value = getattr(self, name)
            if type(value) is not int or not 0 <= value <= cap:
                raise ValueError((name, value))

def beat(a, b, action_a, action_b, power_a=False, power_b=False):
    old = (a, b)
    intents = (action_a, action_b)
    powered = (power_a, power_b)
    effective, costs, remaining, powers = [], [], [], []
    for s, action, power in zip(old, intents, powered):
        s.validate()
        if s.hp == 0 or type(action) is not int or action not in range(6):
            raise ValueError("invalid beat input")
        if power and (action not in ATTACKS or not s.power_available):
            raise ValueError("invalid power")
        cost = RULES["base_costs"][action]
        if action == BLOCK:
            cost += RULES["block_streak_cost"] * s.guard_streak
        if power:
            cost += RULES["power_cost"]
        affordable = s.stamina >= cost
        effective.append(action if affordable else EXHAUSTED)
        costs.append(cost if affordable else 0)
        remaining.append(s.stamina - costs[-1])
        powers.append(0 if power else s.power_available)
    base = [RULES["damage"][effective[i]][effective[1-i]] for i in range(2)]
    damage = [
        value + (RULES["opening_damage"] if old[i].opening else 0)
        + (RULES["power_damage"] if powered[i] else 0) if value else 0
        for i, value in enumerate(base)
    ]
    result, trace = [], []
    for i, s in enumerate(old):
        action, opp, incoming = effective[i], effective[1-i], damage[1-i]
        strain = min(remaining[i], RULES["block_strain"]) if (
            action == BLOCK and opp == KICK) else 0
        st = remaining[i] - strain
        if action == RECOVER:
            recovery = RULES["recover_hit"] if incoming else RULES["recover_unhit"]
        elif action == EXHAUSTED:
            recovery = RULES["exhausted_recovery"]
        else:
            recovery = RULES["ordinary_recovery"]
        opening = int((action == DUCK and opp in (JAB, THROW)) or
                      (action == JAB and damage[i] > 0 and incoming == 0))
        nxt = State(
            max(0, s.hp - incoming), min(60, st + recovery), opening,
            min(3, s.guard_streak + 1) if action == BLOCK else 0, powers[i])
        result.append(nxt)
        trace.append(dict(
            before=asdict(s), after=asdict(nxt), intended=intents[i],
            effective=action, power=bool(powered[i]), cost_paid=costs[i],
            base_damage=base[i], computed_damage=damage[i],
            actual_hp_lost=min(s.hp, incoming), strain=strain,
            recovered=nxt.stamina-st))
    return tuple(result), trace

def validate_plan(state, plan):
    actions, power_slot = plan
    if len(actions) != 6 or any(type(x) is not int or x not in range(6) for x in actions):
        raise ValueError("six legal actions required")
    if type(power_slot) is not int or not -1 <= power_slot <= 5:
        raise ValueError("invalid power slot")
    if power_slot >= 0 and (not state.power_available or actions[power_slot] not in ATTACKS):
        raise ValueError("invalid designated attack")

def outcome(states):
    a, b = states
    if not a.hp or not b.hp:
        return "DRAW" if a.hp == b.hp else ("A" if a.hp > b.hp else "B")
    return None

def resolve_round(states, plans, index):
    if index not in range(3) or outcome(states):
        raise ValueError("invalid round start")
    for s, p in zip(states, plans):
        s.validate()
        validate_plan(s, p)
    traces = []
    for slot in range(6):
        states, trace = beat(*states, plans[0][0][slot], plans[1][0][slot],
                             plans[0][1] == slot, plans[1][1] == slot)
        traces.append(trace)
        terminal = outcome(states)
        if terminal:
            return states, traces, terminal
    if index == 2:
        return states, traces, ("DRAW" if states[0].hp == states[1].hp else
                               "A" if states[0].hp > states[1].hp else "B")
    states = tuple(replace(s, stamina=min(60, s.stamina+RULES["break_recovery"])) for s in states)
    return states, traces, None

def compact(s):
    return (s.hp, s.stamina, s.opening, s.guard_streak)

def check():
    cases = [
        (JAB,BLOCK,(100,56,0,0),(100,58,0,1)),
        (JAB,KICK,(86,56,0,0),(92,50,0,0)),
        (DUCK,JAB,(100,58,1,0),(100,56,0,0)),
        (KICK,DUCK,(100,50,0,0),(82,58,0,0)),
        (THROW,BLOCK,(100,53,0,0),(86,58,0,1)),
        (BLOCK,KICK,(100,52,0,1),(100,50,0,0)),
        (RECOVER,JAB,(88,60,0,0),(100,56,1,0)),
        (THROW,THROW,(100,53,0,0),(100,53,0,0))]
    for x,y,ea,eb in cases:
        got,_ = beat(State(), State(), x,y)
        assert (compact(got[0]),compact(got[1])) == (ea,eb)
        swapped,_ = beat(State(),State(),y,x)
        assert swapped == tuple(reversed(got))
    got,_=beat(State(),State(),DUCK,JAB)
    got,_=beat(*got,KICK,JAB)
    assert tuple(map(compact,got)) == ((92,48,0,0),(82,52,0,0))
    got,_=beat(State(stamina=11),State(),KICK,JAB)
    assert tuple(map(compact,got)) == ((88,17,0,0),(100,56,1,0))
    got,_=beat(State(stamina=12),State(),KICK,RECOVER)
    assert got[0].stamina == 2
    got,_=beat(State(opening=1),State(),KICK,DUCK,True)
    assert got[0].stamina == 46 and got[0].power_available == 0 and got[1].hp == 74
    got,_=beat(State(),State(),JAB,BLOCK,True)
    assert got[0].stamina == 52 and got[0].power_available == 0 and got[1].hp == 100
    got,_=beat(State(stamina=9),State(),JAB,JAB,True)
    assert got[0].hp == 88 and got[0].stamina == 15 and got[0].power_available == 0
    states=(State(),State())
    for expected in (58,53,45,34):
        states,_=beat(*states,BLOCK,RECOVER)
        assert states[0].stamina == expected
    states,_=beat(State(stamina=4),State(),BLOCK,KICK)
    assert states[0] == State(stamina=2,guard_streak=1)
    states,_=beat(State(hp=14),State(hp=8),JAB,KICK)
    assert outcome(states) == "DRAW"
    plan=([JAB]*6,-1)
    states,traces,result=resolve_round((State(),State()),(plan,plan),0)
    assert states[0] == State(hp=52,stamina=46) and result is None
    states,traces,result=resolve_round(states,(plan,plan),1)
    assert states[0] == State(hp=4,stamina=32) and result is None
    states,traces,result=resolve_round(states,(plan,plan),2)
    assert result == "DRAW" and len(traces) == 1
    rest=([RECOVER]*6,-1)
    states=(State(),State())
    for index in range(3):
        states,_,result=resolve_round(states,(rest,rest),index)
    assert states == (State(),State()) and result == "DRAW"
    # Full side symmetry for all submitted pairs and affordable/unaffordable states.
    count=0
    for sa in (0,3,4,5,6,9,10,11,12,16,60):
        for sb in (0,4,6,12,60):
            for x in range(6):
                for y in range(6):
                    a,b=State(stamina=sa,opening=1,guard_streak=3),State(stamina=sb)
                    got,tr=beat(a,b,x,y)
                    rev,rr=beat(b,a,y,x)
                    assert got == tuple(reversed(rev)) and tr == list(reversed(rr))
                    count += 1
    digest=hashlib.sha256(b"qdojo/combat/rules/v1\0"+
        json.dumps(RULES,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
    print("Hand vectors passed; paired boundary checks:",count)
    print("Candidate ruleset digest:",digest)
    fixture=Path(__file__).resolve().parents[1]/"fixtures/commitment-v1.json"
    assert commitment_vector()==json.loads(fixture.read_text()), "Frozen commitment fixture drift"
    print("Frozen commitment fixture passed.")

class Stream:
    def __init__(self,seed,fight,index):
        self.prefix=b"qdojo/npc/v1\0"+seed+fight.to_bytes(8,"little")+bytes([index])
        self.counter=0
        self.data=iter(())
    def uniform(self,n):
        limit=256-(256%n)
        while True:
            v=next(self.data,None)
            if v is None:
                self.data=iter(hashlib.sha256(self.prefix+self.counter.to_bytes(4,"little")).digest())
                self.counter+=1
                continue
            if v<limit:
                return v%n

PATTERNS={
    "jabber": [JAB,JAB,JAB,RECOVER,JAB,JAB],
    "turtle": [BLOCK,BLOCK,RECOVER,BLOCK,DUCK,RECOVER],
    "kicker": [KICK,RECOVER,KICK,RECOVER,KICK,RECOVER],
}
def policy(name,state,index,seed,fight):
    rng=Stream(seed,fight,index)
    if name=="random":
        actions=[rng.uniform(6) for _ in range(6)]
        eligible=[-1]+[i for i,a in enumerate(actions) if a in ATTACKS]
        power=eligible[rng.uniform(len(eligible))] if state.power_available else -1
    else:
        actions=PATTERNS[name][:]
        power=next((i for i,a in enumerate(actions) if a in ATTACKS),-1) if (
            state.power_available and index==2) else -1
    return actions,power

def smoke():
    names=["random",*PATTERNS]
    print("Illustrative smoke only: 200 paired seeds/matchup; score counts draws as half.")
    for i,a in enumerate(names):
        for b in names[i+1:]:
            wins=draws=losses=third=0
            for n in range(200):
                seeds=[hashlib.sha256(("smoke/%d/%s"%(n,x)).encode()).digest() for x in (a,b)]
                for swap in (False,True):
                    labels=(b,a) if swap else (a,b)
                    inputs=list(reversed(seeds)) if swap else seeds
                    states=(State(),State())
                    for r in range(3):
                        if r==2: third+=1
                        plans=tuple(policy(name,states[k],r,inputs[k],n) for k,name in enumerate(labels))
                        states,_,result=resolve_round(states,plans,r)
                        if result is not None: break
                    if result=="DRAW": draws+=1
                    elif (result=="A") != swap: wins+=1
                    else: losses+=1
            print("%s vs %s: W/D/L %d/%d/%d, score %.3f, third-round %.3f"%
                  (a,b,wins,draws,losses,(wins+draws/2)/400,third/400))


def commitment_vector():
    """Public synthetic identities/salt, NEVER keys or a live commitment."""
    u=lambda n,width: n.to_bytes(width,"little")
    ident=lambda n: bytes([n])*32
    h=lambda tag,data: hashlib.sha256(tag+b"\0"+data).digest()
    rules=h(b"qdojo/combat/rules/v1",json.dumps(
        RULES,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode())
    def participant(fid,owner,operator):
        return ident(fid)+ident(owner)+ident(operator)+u(1,4)+ident(owner)+u(1000,2)+u(1000,2)
    context=(ident(1)+ident(2)+u(9,8)+u(42,8)+u(0,1)+u(0,1)+u(0,8)+u(1,4)+u(1000,8)
             +rules+u(24,2)+u(12,2)+u(1,4)+u(1000,8)+u(500,2)
             +u(6000,2)+u(1000,2)+u(3000,2)+ident(9)+ident(10)+ident(11)
             +participant(3,5,6)+participant(4,7,8))
    context_hash=h(b"qdojo/combat/context/v1",context)
    state_bytes=u(100,2)+u(60,2)+bytes([0,0,1,0])
    round_state=context_hash+b"\0"+state_bytes+state_bytes
    state_hash=h(b"qdojo/combat/state/v1",round_state)
    plan=bytes([0,3,1,5,2,4,2])
    salt=ident(12)
    preimage=(b"qdojo/combat/commit/v1\0"+ident(1)+ident(2)+u(42,8)+b"\0"+
              context_hash+state_hash+ident(3)+ident(6)+u(1,4)+salt+plan)
    return dict(
        schema="qdojo.combat.commitment-vector.v1",
        note="Synthetic public fixture, no keys; never reuse fixture salt in live play.",
        ruleset_digest=rules.hex(),context_bytes=context.hex(),
        context_digest=context_hash.hex(),round_state_bytes=round_state.hex(),
        round_state_digest=state_hash.hex(),plan_bytes=plan.hex(),
        salt=salt.hex(),commitment_preimage=preimage.hex(),
        commitment=hashlib.sha256(preimage).hexdigest())

if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check",action="store_true")
    parser.add_argument("--smoke",action="store_true")
    parser.add_argument("--vector",action="store_true")
    args=parser.parse_args()
    if args.check: check()
    if args.smoke: smoke()
    if args.vector: print(json.dumps(commitment_vector(),indent=2))
    if not args.check and not args.smoke and not args.vector: parser.print_help()
