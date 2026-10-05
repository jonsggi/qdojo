#!/usr/bin/env python3
"""Contract parity journals for AdminMirrorOwner (opcode 104, the qbay-mirror backend).

Writes, under packages/qdojo/tests/combat/fixtures/contract/:

  mirror.journal        a scripted run of the reference contract (sim.World,
                        candidate 3) covering what docs/nft.md §5.4 and
                        docs/protocol.md §3 specify for 104:
                          - 104 binding two fighters, both owners registering;
                          - a ranked fight in which one fighter's owner is
                            mirrored to a new identity mid-fight: the snapshot
                            owner is paid;
                          - the old owner refused (NOT_OWNER), the new owner
                            registering (auth_version + 1);
                          - a repeated or lower mirror_seq (STALE);
                          - a zero owner (BAD_STATE on SetOperator and
                            QueueEnter), then the owner restored (DUPLICATE);
                          - rejections: a stranger and a slot-holding
                            non-admin (NOT_OWNER), source 1, seq 0 and npc 2
                            (BAD_BODY), an attached amount (BAD_AMOUNT), a
                            second fighter on the same NFT, a re-pointed
                            fighter, another registry_version, 100 and 103 on
                            a mirrored fighter, 104 on a 103-bound fighter
                            (BAD_STATE);
                        `owner` records for mirrored fighters are written too,
                        as a qbay-mirror world does: the contract must ignore
                        them. Each call record also carries the reference's
                        result code ("code"), which every replay checks;
  mirror-arena.journal  a real qbay-mirror arena (live.Arena, profile demo-c3,
                        bots fighting) whose bridge reads RECORDED mainnet
                        answers (tests/fixtures/qbay/mainnet.json through
                        FixtureRpc; no network): three fighters bound to BITE:
                        Ocean Rebels NFTs, a QubicBay sale of NFT 5497 mirrored
                        while the bots fight, and NFT 5499 vanishing (zero
                        owner). Converted like scripts/combat-journal-from-devnet.py.

Both end with the reference's final event digest; make contract-test and
make qubic-core-test replay them. Deterministic: salts are derived, the arena
runs deterministic=True with a fixed seed.
"""
from __future__ import annotations

import dataclasses
import json
import random
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages/qdojo/src"))
sys.path.insert(0, str(ROOT / "packages/qdojo/tests"))

from qdojo.combat import codec, devnet, store  # noqa: E402
from qdojo.combat.codec import Code, Op  # noqa: E402
from qdojo.combat.contract import development_manifest  # noqa: E402
from qdojo.combat.rules import candidate_3  # noqa: E402
from qdojo.combat.sim import World, commit_fields, identity, reveal_fields  # noqa: E402
from combat.test_contract import ADMIN, DEV, HOUSE, KO_PLAN, SHARE, Player  # noqa: E402

OUT = ROOT / "packages/qdojo/tests/combat/fixtures/contract"
QBAY_FIXTURE = ROOT / "packages/qdojo/tests/fixtures/qbay/mainnet.json"
SEED = 0x104
REBELS = [5497, 5499, 5500, 5582, 5589, 5590, 5591, 5592]      # BITE: Ocean Rebels (collection 17)


class Mirror:
    def __init__(self):
        self.rng = random.Random(SEED)
        m = development_manifest(candidate_3(), ADMIN, HOUSE, DEV, SHARE)
        self.w = World(dataclasses.replace(m, timing={1: (4, 3)}))
        self.w.mint(ADMIN, 10**9)
        self.c = self.w.contract
        # Every call record carries the reference's result code ("code"): result
        # codes are not in the event digest, so the replays (store.replay,
        # test_contract.cpp, test_qdojo_core.cpp) check them call by call.
        send_raw = self.w.raw

        def raw(who, frame, amount=0):
            r = send_raw(who, frame, amount)
            self.w.journal[-1]["code"] = int(r.code)
            return r
        self.w.raw = raw

    def ok(self, r, code=Code.OK):
        assert r.code == code, (r, code)
        return r

    def mirror(self, fid, owner, seq, nft=5497, who=ADMIN, src=12, version=1, npc=0, amount=0, code=Code.OK):
        r = self.w.send(who, Op.ADMIN_MIRROR_OWNER, amount, fighter_id=fid, registry_version=version,
                        house_npc=npc, source_contract=src, source_id=nft, owner=owner or bytes(32),
                        mirror_seq=seq)
        self.ok(r, code)
        if code == Code.OK:
            self.w.owners[fid] = owner             # the world's owner table follows, as a qbay-mirror ledger's does
        return r

    def enter(self, fid, who, auth_version, code=Code.OK):
        return self.ok(self.w.send(who, Op.QUEUE_ENTER, 1000, fighter_id=fid, auth_version=auth_version,
                                   ruleset_digest=self.c.m.ruleset.digest, timing_profile_id=1, fee_profile_id=1,
                                   tier_id=1, max_gap=200, expires_tick=self.w.tick + 240), code)

    def play(self, fight_id, a, a_plan):
        """a commits and reveals a_plan every round; the other side never commits (a forfeit)."""
        w, fight = self.w, self.c.fights[fight_id]
        while fight.phase != "DONE":
            w.run_until(fight.start_tick + 1)
            salt = bytes(self.rng.getrandbits(8) for _ in range(32))
            fields, salt = commit_fields(w, fight_id, a[0], a[1], a_plan, salt=salt)
            self.ok(w.send(a[1], Op.COMMIT, **fields))
            w.run_until(fight.commit_last + 1)
            if fight.phase == "REVEAL":
                self.ok(w.send(a[1], Op.REVEAL, **reveal_fields(w, fight_id, a[0], a_plan, salt)))
                w.end()
        return fight.result

    def build(self):
        w, c = self.w, self.c
        fa, fb, other = identity("fighter:mr-a"), identity("fighter:mr-b"), identity("fighter:mr-other")
        a_old, a_new, holder_b = identity("holder:mr-a-old"), identity("holder:mr-a-new"), identity("holder:mr-b")
        for who in (a_old, a_new, holder_b):
            w.mint(who, 1_000_000)
        plain = Player(w, "mr-plain")                       # a slot holder who is not the admin
        stranger = identity("mr-stranger")
        w.mint(stranger, 10_000)

        # Rejections before any binding.
        self.mirror(fa, a_old, 1, who=stranger, code=Code.NOT_OWNER)
        self.mirror(fa, a_old, 1, who=plain.owner, code=Code.NOT_OWNER)
        self.mirror(fa, a_old, 1, src=1, code=Code.BAD_BODY)          # only QBAY (12) is a source
        self.mirror(fa, a_old, 0, code=Code.BAD_BODY)
        self.mirror(fa, a_old, 1, npc=2, code=Code.BAD_BODY)
        self.mirror(fa, a_old, 1, amount=3, code=Code.BAD_AMOUNT)

        # 104 binds two fighters; their owners register.
        self.mirror(fa, a_old, 1, nft=5497)
        self.mirror(fb, holder_b, 1, nft=5499)
        self.ok(w.send(a_new, Op.REGISTER_FIGHTER, fighter_id=fa, registry_version=1), Code.NOT_OWNER)
        self.ok(w.send(a_old, Op.REGISTER_FIGHTER, fighter_id=fa, registry_version=1))
        self.ok(w.send(holder_b, Op.REGISTER_FIGHTER, fighter_id=fb, registry_version=1))

        # One NFT never backs two fighters; a fighter is never re-pointed or re-versioned;
        # 100 and 103 refuse a mirrored fighter; 104 refuses a 103-bound one.
        self.mirror(other, a_old, 1, nft=5497, code=Code.BAD_STATE)
        self.mirror(fa, a_old, 2, nft=5499, code=Code.BAD_STATE)
        self.mirror(fa, a_old, 2, nft=5497, version=2, code=Code.BAD_STATE)
        self.mirror(fa, a_old, 2, nft=5497, npc=1, code=Code.BAD_STATE)
        self.ok(w.send(ADMIN, Op.ADMIN_REGISTER_ASSET, fighter_id=fa, registry_version=1, house_npc=0),
                Code.BAD_STATE)
        self.ok(w.send(ADMIN, Op.ADMIN_BIND_ASSET, fighter_id=fa, registry_version=1, house_npc=0,
                       asset_issuer=identity("mr-issuer"), asset_name=codec.asset_name_u64("QF0001")),
                Code.BAD_STATE)
        self.ok(w.send(ADMIN, Op.ADMIN_BIND_ASSET, fighter_id=other, registry_version=1, house_npc=0,
                       asset_issuer=identity("mr-issuer"), asset_name=codec.asset_name_u64("QF0002")))
        self.mirror(other, a_old, 1, nft=5500, code=Code.BAD_STATE)

        # A ranked fight; fa's NFT is sold on QubicBay mid-fight. fb never commits: fa wins
        # by forfeit, and the owner who entered (a_old) is paid.
        self.enter(fa, a_old, 1)
        self.enter(fb, holder_b, 1)
        fight_id = None
        for _ in range(12):
            w.end()
            live = [x for x in c.fights.values() if x.phase != "DONE" and x.slot_of(fa) and x.slot_of(fb)]
            if live:
                fight_id = live[-1].fight_id
                break
        assert fight_id, "no match"
        before = c.ledger.credits.get(a_old, 0)
        self.mirror(fa, a_new, 2, nft=5497)
        result = self.play(fight_id, (fa, a_old), KO_PLAN)
        assert result["kind"] == "FORFEIT" and result["winner"] == c.fights[fight_id].slot_of(fa), result
        assert c.ledger.credits.get(a_old, 0) > before and c.ledger.credits.get(a_new, 0) == 0

        # The old owner can no longer act; the new one registers (auth_version 2).
        self.enter(fa, a_old, 1, Code.NOT_OWNER)
        self.ok(w.send(a_new, Op.REGISTER_FIGHTER, fighter_id=fa, registry_version=1))
        assert c.fighters[fa].auth_version == 2 and c.fighters[fa].owner == a_new
        # mirror_seq must increase.
        self.mirror(fa, a_old, 2, nft=5497, code=Code.STALE)
        self.mirror(fa, a_old, 1, nft=5497, code=Code.STALE)

        # A zero owner: the NFT is gone, ownership unavailable.
        w.run_until(w.tick + 300)                           # past every cooldown
        self.mirror(fb, None, 2, nft=5499)
        self.ok(w.send(holder_b, Op.SET_OPERATOR, fighter_id=fb, new_operator=identity("mr-op"),
                       expected_auth_version=1), Code.BAD_STATE)
        self.enter(fb, holder_b, 1, Code.BAD_STATE)
        # The owner comes back (seq 3): the same owner is already registered.
        self.mirror(fb, holder_b, 3, nft=5499)
        self.ok(w.send(holder_b, Op.REGISTER_FIGHTER, fighter_id=fb, registry_version=1), Code.DUPLICATE)
        self.enter(fb, holder_b, 1)
        self.ok(w.send(holder_b, Op.QUEUE_CANCEL, offer_id=max(c.offers)))
        w.run_until(w.tick + 20)
        w.check_conservation()
        return self


def mirror_journal(out: Path):
    sc = Mirror().build()
    c = sc.c
    store.write(out, sc.w.manifest, sc.w.journal, c.event_digest)
    n = sum(1 for e in c.events if e[2] == "OWNER_MIRRORED")
    print(f"mirror: {len(sc.w.journal)} records, {c.event_seq} events ({n} OWNER_MIRRORED), "
          f"{out.stat().st_size} bytes")
    print(f"    event digest {c.event_digest.hex()}")
    assert out.stat().st_size < 1_000_000


def mirror_arena(out: Path, ticks: int = 400):
    from qdojo.combat import live
    from qdojo.qubic import qbay
    from qdojo.qubic.rpc import FixtureRpc

    chain = FixtureRpc(json.loads(QBAY_FIXTURE.read_text()))

    def edit(nft_id, possessor: bytes | None):
        k = (12, 7, qbay.nft_by_id_input(nft_id))
        raw = bytearray(chain.answers[k])
        if possessor is None:
            raw = bytearray(len(raw))                      # a zero row: the NFT vanished
        else:
            raw[32:64] = possessor
        chain.answers[k] = bytes(raw)

    tmp = Path(tempfile.mkdtemp(prefix="qdojo-mirror-"))
    try:
        cfg = {"collection_id": 17, "nfts": REBELS, "collection_name": "BITE: Ocean Rebels", "poll_seconds": 10,
               "membership": "qubicbay-api+chain"}
        (tmp / "qbay.json").write_text(json.dumps(cfg))
        lineup = [{"label": "tanuki", "policy": "reader-v1"}, {"label": "kappa", "policy": "kicker-v1"},
                  {"label": "tengu", "policy": "mixed-v1"}]
        a = live.Arena(tmp / "net", lineup, profile="demo-c3", deterministic=True, seed=7,
                       nft_backend="qbay-mirror", qbay_config=tmp / "qbay.json",
                       qbay_reader=qbay.QbayReader(chain), qbay_poll_ticks=10, log=lambda m: None)
        for i in range(ticks):
            if i == 120:
                edit(5497, identity("qubicbay-buyer"))     # a QubicBay sale on mainnet
            if i == 260:
                edit(5499, None)
            a.step()
        a.net.snapshot()                                # a digest checkpoint at the last tick
        world = a.w
        assert any(x == "OWNER_MIRRORED" for _, _, x, _, _ in world.contract.events) or world.contract.mirrors
        seqs = {f.hex()[:8]: ((o.hex()[:8] if o else None), q) for f, (o, q) in world.contract.mirrors.items()}
        a.close()
        net_dir = tmp / "net"
        meta = json.loads((net_dir / "devnet.json").read_text())
        _, _, m = devnet.recorded(meta)
        lines = [x for x in (net_dir / devnet.JOURNAL).read_text(encoding="utf-8").split("\n") if x]
        last = max(i for i, x in enumerate(lines) if json.loads(x)["k"] == "digest") + 1
        with open(out, "w", encoding="utf-8") as f:
            f.write(json.dumps(store.header(m)) + "\n")
            for line in lines[:last]:
                f.write(line + "\n")
        tail = json.loads(lines[last - 1])
        calls = [json.loads(x) for x in lines[:last] if '"k": "call"' in x or '"k":"call"' in x]
        n104 = sum(1 for r in calls if int.from_bytes(bytes.fromhex(r["frame"])[4:6], "little") == 104)
        print(f"mirror-arena: {last} records up to tick {tail['t']}, {n104} AdminMirrorOwner calls, "
              f"event_seq {tail['event_seq']}, {out.stat().st_size} bytes; mirrors {seqs}")
        print(f"    event digest {tail['event_digest']}")
        assert n104 >= 5, n104
        assert out.stat().st_size < 3_000_000
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    mirror_journal(OUT / "mirror.journal")
    mirror_arena(OUT / "mirror-arena.journal")


if __name__ == "__main__":
    main()
