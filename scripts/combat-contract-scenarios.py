#!/usr/bin/env python3
"""Deterministic contract scenarios for the C++ port's parity set.

Writes packages/qdojo/tests/combat/fixtures/contract/scenarios.journal: one
scripted run of the reference contract on a fake chain (sim.World) covering
what random traffic rarely reaches:

  ranked match and rating; SetOperator at IDLE, refused after check-in and
  allowed between pairings; failed then successful withdrawal; AdminCreateCup
  rejections; a cup with byes, a drawn pairing that goes to a replay, one
  fighter per owner, an entry withdrawn (CUP_WITHDRAWN) and a finalist sold
  during the final (the snapshot owner is paid); a level postponed for
  capacity whose retry succeeds, then NO_CHAMPION; a level postponed twice
  (CAPACITY abort) with a duel accept refused FULL; a cup CANCELLED below
  minimum; a service gap voiding a duel, an open offer and a cup
  (SERVICE_VOID); ruleset retirement; strangers (NOT_OWNER, refunds that
  take the last account slots, direct paybacks, one failing) and
  account-capacity FULL for a new registrant; a candidate-1 reveal carrying
  LAST_STAND (BAD_COMMITMENT on a wrong salt, then BAD_PLAN); AdminBindAsset
  (103) binds, rejections, a sale through the bound asset, and an asset with
  no owner (BAD_STATE).

A short timing profile (commit 4, reveal 3) keeps the journal small. Salts
come from a seeded RNG, so regeneration is byte-identical. Run directly or
through scripts/combat-sample-data.py.
"""
from __future__ import annotations

import dataclasses
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages/qdojo/src"))
sys.path.insert(0, str(ROOT / "packages/qdojo/tests"))

from qdojo.combat import store  # noqa: E402
from qdojo.combat.codec import Code, Mode, Op, asset_name_u64  # noqa: E402
from qdojo.combat.contract import development_manifest  # noqa: E402
from qdojo.combat.rules import candidate_1  # noqa: E402
from qdojo.combat.sim import World, commit_fields, identity, reveal_fields  # noqa: E402
from qdojo.combat.types import Action, Plan  # noqa: E402
from combat.test_contract import ADMIN, DEV, HOUSE, KO_PLAN, RESTS, SHARE, Player  # noqa: E402

OUT = ROOT / "packages/qdojo/tests/combat/fixtures/contract/scenarios.journal"
SEED = 0x5CE7
MAX_ACCOUNTS = 48
LEVEL = dict(level_ticks=230, first_level_delay=5, checkin_ticks=6, replay_delay=3)


class Scenario:
    def __init__(self):
        self.rng = random.Random(SEED)
        m = development_manifest(candidate_1(), ADMIN, HOUSE, DEV, SHARE, max_fights=4,
                                 max_accounts=MAX_ACCOUNTS, max_cup_entrants=8, event_ring=64)
        self.w = World(dataclasses.replace(m, timing={1: (4, 3)}))
        self.w.mint(ADMIN, 10**9)
        self.c = self.w.contract
        self.players: dict[bytes, Player] = {}
        self.pending = {}
        self.checkin: dict[int, set] = {}      # cup_id -> fighter ids that never check in
        self.drawn_cup = 0                    # cup whose level-0 pairing is played to a draw
        self.hook = None

    # -- helpers ----------------------------------------------------------------
    def player(self, label, **kw) -> Player:
        p = Player(self.w, "sc-" + label, **kw)
        self.players[p.fid] = p
        return p

    def ok(self, r, code=Code.OK):
        assert r.code == code, (r, code)
        return r

    def create_cup(self, close_in=10, sponsor=500, **over):
        f = dict(ruleset_digest=self.c.m.ruleset.digest, timing_profile_id=1, fee_profile_id=1, entry_fee=1000,
                 registration_close=self.w.tick + close_in, min_entrants=4, max_entrants=8, **LEVEL)
        f.update(over)
        return self.w.send(ADMIN, Op.ADMIN_CREATE_CUP, sponsor, **f)

    def register(self, cup_id, p, code=Code.OK):
        return self.ok(self.w.send(p.owner, Op.CUP_REGISTER, 1000, cup_id=cup_id, fighter_id=p.fid,
                                   auth_version=p.f.auth_version), code)

    def duel(self, a, b, accept_code=Code.OK):
        r = self.ok(self.w.send(a.owner, Op.DUEL_OFFER, 1000, fighter_id=a.fid, auth_version=a.f.auth_version,
                                opponent_id=b.fid, ruleset_digest=self.c.m.ruleset.digest, timing_profile_id=1,
                                fee_profile_id=1, stake=1000, format=0, expires_tick=self.w.tick + 40))
        return self.ok(self.w.send(b.owner, Op.DUEL_ACCEPT, 1000, offer_id=r.data["offer_id"], fighter_id=b.fid,
                                   auth_version=b.f.auth_version), accept_code)

    def plan_for(self, ct, fid):
        if ct.mode == Mode.DUEL:
            return None                                  # capacity fillers: never played
        slot_a = fid == ct.a.fighter_id
        if ct.mode == Mode.CUP:
            cup = self.c.cups[ct.cup_id]
            if cup.cup_id == self.drawn_cup and cup.pairings[ct.pairing_id].level == 0 and not ct.replay:
                return RESTS                             # a drawn series -> replay
        return KO_PLAN if slot_a else RESTS

    def step(self):
        w, c, t = self.w, self.c, self.w.tick
        if self.hook:
            self.hook(t)
        for cup_id, no_show in self.checkin.items():
            cup = c.cups[cup_id]
            if cup.status != "RUNNING" or not cup.level_start <= t < cup.level_start + cup.descriptor["checkin_ticks"]:
                continue
            for pr in cup.pairings.values():
                if pr.level != cup.level or pr.status != "SCHEDULED":
                    continue
                for fid in (pr.a, pr.b):
                    if fid and fid not in pr.checked and fid not in no_show:
                        p = self.players[fid]
                        self.ok(w.send(p.operator, Op.CUP_CHECK_IN, cup_id=cup_id, pairing_id=pr.pairing_id,
                                       fighter_id=fid, auth_version=p.f.auth_version))
        for fight in list(c.fights.values()):
            ct = c.contests[fight.contest_id]
            if fight.phase == "COMMIT" and fight.start_tick < t <= fight.commit_last:
                for side in (fight.context.participant_a, fight.context.participant_b):
                    if fight.slot_of(side.fighter_id) in fight.commits:
                        continue
                    plan = self.plan_for(ct, side.fighter_id)
                    if plan is None:
                        continue
                    salt = bytes(self.rng.getrandbits(8) for _ in range(32))
                    fields, salt = commit_fields(w, fight.fight_id, side.fighter_id, side.operator, plan, salt=salt)
                    self.ok(w.send(side.operator, Op.COMMIT, **fields))
                    self.pending[(fight.fight_id, fight.state.round_index, side.fighter_id)] = (plan, salt, side)
            elif fight.phase == "REVEAL":
                for side in (fight.context.participant_a, fight.context.participant_b):
                    k = (fight.fight_id, fight.state.round_index, side.fighter_id)
                    if k in self.pending and fight.slot_of(side.fighter_id) not in fight.reveals:
                        plan, salt, s = self.pending.pop(k)
                        self.ok(w.send(s.operator, Op.REVEAL,
                                       **reveal_fields(w, fight.fight_id, s.fighter_id, plan, salt)))
        w.end()

    def run_until(self, tick):
        while self.w.tick < tick:
            self.step()

    def run_while(self, cond, limit=5000):
        for _ in range(limit):
            if not cond():
                return
            self.step()
        raise AssertionError("scenario did not settle")

    # -- scenarios ---------------------------------------------------------------
    def build(self):
        w, c = self.w, self.c
        A = [self.player(f"a{i}") for i in range(5)]
        twin = self.player("a-twin", owner=A[0].owner)               # same owner as A[0]
        leaver = self.player("a-leaver")
        N = [self.player(f"n{i}") for i in range(4)]
        D = [self.player(f"d{i}") for i in range(4)]
        U = [self.player(f"u{i}") for i in range(6)]

        # Ranked: a match, a KO, ratings; then a failed and a retried withdrawal.
        self.ok(U[0].enter())
        self.ok(U[1].enter())
        self.run_while(lambda: U[0].f.lock != "IDLE" or U[1].f.lock != "IDLE")
        winner = max(U[:2], key=lambda p: c.ledger.credits.get(p.owner, 0))
        w.transfer_fails.add(winner.owner)
        self.ok(w.send(winner.owner, Op.WITHDRAW), Code.TRANSFER_FAILED)
        w.transfer_fails.discard(winner.owner)
        self.ok(w.send(winner.owner, Op.WITHDRAW))
        # SetOperator at IDLE; Advance must use nonce 0.
        self.ok(w.send(U[2].owner, Op.SET_OPERATOR, fighter_id=U[2].fid, new_operator=identity("sc-op-u2"),
                       expected_auth_version=U[2].f.auth_version))
        U[2].operator = identity("sc-op-u2")
        self.ok(w.send(U[3].owner, Op.ADVANCE, nonce=3, target_kind=1, target_id=1), Code.BAD_BODY)

        # AdminCreateCup rejections: unexaminable boundaries, a window too short, a non-admin.
        for bad in (dict(checkin_ticks=0), dict(first_level_delay=1), dict(replay_delay=0)):
            self.ok(self.create_cup(**bad), Code.BAD_BODY)
        self.ok(self.create_cup(level_ticks=100), Code.INCOMPATIBLE)
        self.ok(w.send(U[3].owner, Op.ADMIN_CREATE_CUP, 0, ruleset_digest=c.m.ruleset.digest, timing_profile_id=1,
                       fee_profile_id=1, entry_fee=1000, registration_close=w.tick + 10, min_entrants=4,
                       max_entrants=8, **LEVEL), Code.NOT_OWNER)

        # Cup 1: five entrants (three byes), a drawn level-0 pairing replayed,
        # one fighter per owner, a withdrawn entry, SetOperator refused after
        # check-in and allowed between pairings, a finalist sold mid-final.
        cup1 = self.ok(self.create_cup()).data["cup_id"]
        self.drawn_cup = cup1
        self.checkin[cup1] = set()
        for p in A:
            self.register(cup1, p)
        self.register(cup1, twin, Code.INCOMPATIBLE)
        self.register(cup1, leaver)
        self.ok(w.send(leaver.owner, Op.CUP_WITHDRAW, cup_id=cup1, fighter_id=leaver.fid))
        k1 = c.cups[cup1]
        done = {}

        def hook1(t):
            if k1.status != "RUNNING":
                return
            for pr in k1.pairings.values():
                if pr.level == 1 and pr.status == "SCHEDULED" and pr.checked and "busy" not in done:
                    p = self.players[min(pr.checked)]
                    self.ok(w.send(p.owner, Op.SET_OPERATOR, fighter_id=p.fid, new_operator=identity("sc-late-op"),
                                   expected_auth_version=p.f.auth_version), Code.FIGHTER_BUSY)
                    done["busy"] = True
            final = [pr for pr in k1.pairings.values() if pr.level == k1.levels - 1]
            if final and final[0].status == "SCHEDULED" and not final[0].checked and "between" not in done:
                p = self.players[final[0].a]
                op = identity("sc-final-op")
                self.ok(w.send(p.owner, Op.SET_OPERATOR, fighter_id=p.fid, new_operator=op,
                               expected_auth_version=p.f.auth_version))
                p.operator = op
                done["between"] = True
            if final and final[0].status == "PLAYING" and "sold" not in done:
                fid = c.contests[final[0].contest_id].a.fighter_id
                buyer = identity("sc-final-buyer")
                w.owners[fid] = buyer
                self.ok(w.send(buyer, Op.REGISTER_FIGHTER, fighter_id=fid, registry_version=1))
                done["sold"] = True

        self.hook = hook1
        self.run_while(lambda: k1.status in ("REGISTRATION", "RUNNING"))
        self.hook = None
        assert k1.status == "COMPLETE" and len(done) == 3, (k1.status, done)
        assert any(ct.replay for ct in c.contests.values() if ct.cup_id == cup1)

        # Cup 2: duels hold three of four fight slots when the roster locks, so
        # level 0 is postponed; the retry succeeds; nobody checks in: NO_CHAMPION.
        cup2 = self.ok(self.create_cup()).data["cup_id"]
        k2 = c.cups[cup2]
        self.checkin[cup2] = {p.fid for p in N}
        for p in N:
            self.register(cup2, p)
        self.run_until(k2.descriptor["registration_close"])
        for a, b in ((U[0], U[1]), (U[2], U[3]), (U[4], U[5])):
            self.duel(a, b)
        self.step()
        assert k2.pending_reservation
        self.run_while(lambda: k2.status in ("REGISTRATION", "RUNNING"))
        assert k2.status == "ABORTED", k2.status

        # Cup 3: postponed at lock and again at the retry: CAPACITY. A fourth
        # duel accept is refused FULL while the slots are held.
        cup3 = self.ok(self.create_cup()).data["cup_id"]
        k3 = c.cups[cup3]
        for p in D:
            self.register(cup3, p)
        self.run_until(k3.descriptor["registration_close"])
        for a, b in ((N[0], N[1]), (N[2], N[3]), (A[1], A[2]), (A[3], A[4])):
            self.duel(a, b)
        self.duel(U[0], U[1], accept_code=Code.FULL)
        self.step()
        assert k3.pending_reservation
        self.run_until(k3.level_start - 1)
        for a, b in ((U[0], U[1]), (U[2], U[3]), (U[4], U[5])):
            self.duel(a, b)
        self.step()
        assert k3.status == "ABORTED", k3.status

        # Cup 4: below minimum: CANCELLED.
        cup4 = self.ok(self.create_cup()).data["cup_id"]
        k4 = c.cups[cup4]
        for p in D[:3]:
            self.register(cup4, p)
        self.run_while(lambda: k4.status == "REGISTRATION")
        assert k4.status == "CANCELLED"

        # Service gap: voids a live duel, invalidates an open offer, aborts a cup.
        self.run_until(w.tick + 250)                         # every duel fault cooldown has passed
        cup5 = self.ok(self.create_cup(close_in=30)).data["cup_id"]
        self.register(cup5, D[3])
        self.duel(U[4], U[5])
        self.ok(U[0].enter())
        w.skip_ticks(2)
        self.step()
        assert c.cups[cup5].status == "ABORTED"

        # A candidate-1 reveal carrying a candidate-3 action (LAST_STAND) decodes,
        # is checked against its commitment first (a wrong salt: BAD_COMMITMENT)
        # and is then refused by the ruleset (BAD_PLAN); that fighter forfeits.
        E = [self.player(f"e{i}") for i in range(2)]
        self.duel(E[0], E[1])
        fight = next(x for x in c.fights.values() if x.phase != "DONE" and x.slot_of(E[0].fid))
        self.step()
        stand = Plan.of([Action.LAST_STAND, Action.JAB, Action.JAB, Action.JAB, Action.JAB, Action.JAB])
        salts = {}
        for p, plan in ((E[0], stand), (E[1], RESTS)):
            salt = bytes(self.rng.getrandbits(8) for _ in range(32))
            fields, salts[p.fid] = commit_fields(w, fight.fight_id, p.fid, p.operator, plan, salt=salt)
            self.ok(w.send(p.operator, Op.COMMIT, **fields))
        self.run_while(lambda: fight.phase == "COMMIT")
        self.ok(w.send(E[0].operator, Op.REVEAL, **reveal_fields(w, fight.fight_id, E[0].fid, stand, bytes(32))),
                Code.BAD_COMMITMENT)
        self.ok(w.send(E[0].operator, Op.REVEAL, **reveal_fields(w, fight.fight_id, E[0].fid, stand,
                                                                 salts[E[0].fid])), Code.BAD_PLAN)
        self.ok(w.send(E[1].operator, Op.REVEAL, **reveal_fields(w, fight.fight_id, E[1].fid, RESTS,
                                                                 salts[E[1].fid])))
        self.run_while(lambda: fight.phase != "DONE")
        assert c.contests[fight.contest_id].result["kind"] == "FORFEIT"

        # AdminBindAsset (103): the registry names a real asset (issuer, name).
        # Rejections; a sale and re-registration read through the bound asset;
        # an asset with no owner ("unavailable") refuses registration BAD_STATE.
        issuer = identity("sc-nft-issuer")
        B = []
        for j in range(3):
            fid, owner = identity(f"fighter:sc-nft-{j}"), identity(f"owner:sc-nft-{j}")
            w.owners[fid] = owner
            w.mint(owner, 10_000)
            B.append((fid, owner))

        def bind(fid, name, who=ADMIN, iss=issuer, code=Code.OK):
            value = asset_name_u64(name) if isinstance(name, str) else name
            return self.ok(w.send(who, Op.ADMIN_BIND_ASSET, fighter_id=fid, registry_version=1, house_npc=0,
                                  asset_issuer=iss, asset_name=value), code)

        bind(B[0][0], "QF0001", who=U[3].owner, code=Code.NOT_OWNER)
        bind(B[0][0], "QF0001", iss=bytes(32), code=Code.BAD_BODY)
        bind(B[0][0], int.from_bytes(b"qf1", "little"), code=Code.BAD_BODY)
        for j, (fid, owner) in enumerate(B):
            bind(fid, f"QF000{j + 1}")
            self.ok(w.send(owner, Op.REGISTER_FIGHTER, fighter_id=fid, registry_version=1))
        bind(B[2][0], "QF0001", code=Code.BAD_STATE)           # bound to B[0]
        buyer = identity("sc-nft-buyer")
        w.owners[B[0][0]] = buyer
        self.ok(w.send(B[0][1], Op.REGISTER_FIGHTER, fighter_id=B[0][0], registry_version=1), Code.NOT_OWNER)
        self.ok(w.send(buyer, Op.REGISTER_FIGHTER, fighter_id=B[0][0], registry_version=1))
        w.owners[B[1][0]] = None                               # on chain: the one share burned
        self.ok(w.send(buyer, Op.REGISTER_FIGHTER, fighter_id=B[1][0], registry_version=1), Code.BAD_STATE)

        # Ruleset retirement: admission refused, attachment refunded.
        self.ok(w.send(ADMIN, Op.ADMIN_RETIRE_RULESET, ruleset_digest=bytes(32)))
        self.ok(w.send(ADMIN, Op.ADMIN_RETIRE_RULESET, ruleset_digest=c.m.ruleset.digest))
        self.ok(U[1].enter(), Code.RULESET_RETIRED)

        # Strangers never get a slot: a zero-QU request is refused, and an
        # attachment is paid straight back. Legitimate registrants fill the
        # table; then a new registrant gets FULL, and a stranger whose payback
        # fails is still owed the amount as credit.
        s0 = identity("sc-stranger")
        w.mint(s0, 10_000)
        self.ok(w.send(s0, Op.WITHDRAW), Code.NOT_OWNER)
        self.ok(w.send(s0, Op.QUEUE_CANCEL, offer_id=1), Code.NOT_OWNER)
        before = len(c.accounts)
        self.ok(w.raw(s0, bytes(512), 7), Code.BAD_FRAME)
        assert len(c.accounts) == before, "a stranger's refund must not take a slot"
        i = 0
        while len(c.accounts) < MAX_ACCOUNTS:
            fid, owner = identity(f"fighter:sc-fill-{i}"), identity(f"owner:sc-fill-{i}")
            w.owners[fid] = owner
            self.ok(w.send(ADMIN, Op.ADMIN_REGISTER_ASSET, fighter_id=fid, registry_version=1, house_npc=0))
            self.ok(w.send(owner, Op.REGISTER_FIGHTER, fighter_id=fid, registry_version=1))
            i += 1
        late_fid, late_owner = identity("fighter:sc-late"), identity("owner:sc-late")
        w.owners[late_fid] = late_owner
        self.ok(w.send(ADMIN, Op.ADMIN_REGISTER_ASSET, fighter_id=late_fid, registry_version=1, house_npc=0))
        self.ok(w.send(late_owner, Op.REGISTER_FIGHTER, fighter_id=late_fid, registry_version=1), Code.FULL)
        for j, fails in enumerate((False, True)):
            who = identity(f"sc-late-stranger-{j}")
            w.mint(who, 100)
            if fails:
                w.transfer_fails.add(who)
            self.ok(w.raw(who, bytes(512), 9), Code.BAD_FRAME)
            w.transfer_fails.discard(who)
        self.run_until(w.tick + 20)
        w.check_conservation()
        return self


def main(out: Path = OUT):
    sc = Scenario().build()
    c = sc.c
    out.parent.mkdir(parents=True, exist_ok=True)
    store.write(out, sc.w.manifest, sc.w.journal, c.event_digest)
    size = out.stat().st_size
    kinds = sorted({e[2] for e in c.events})
    print(f"scenarios: {len(sc.w.journal)} records, {c.event_seq} events, {size} bytes; "
          f"cups {[k.status for k in c.cups.values()]}")
    print(f"event digest {c.event_digest.hex()}")
    assert size < 1_000_000, size
    return kinds


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else OUT)
