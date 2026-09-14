"""A whole round on the fake chain: publish, two bots, settle, export."""
import json
import os
import sys

import pytest

from qdojo import hashing, payload
from qdojo.chain import FakeChain
from qdojo.chain.base import Unknown
from qdojo.house import House, HouseError
from qdojo.bot import Bot
from conftest import HOUSE, ALICE, BOB, CARL

SUM_SOLVER = [sys.executable, "-c",
              "import json,sys; r=json.load(sys.stdin); print(json.dumps({'answer': sum(int(x) for x in r['input'].split())}))"]
WRONG_SOLVER = [sys.executable, "-c", "print('{\"answer\": 1}')"]


def riddle_file(tmp_path, rid=1, answer=142):
    p = tmp_path / f"r{rid}.json"
    p.write_text(json.dumps({"round_id": rid, "title": "sum", "statement": "add", "input": "17\n25\n-8\n108",
                             "answer_format": "integer", "answer": answer}))
    return str(p)


class World:
    """One fake ledger shared by several signing views (house, bots)."""

    def __init__(self, tick=1000):
        self.core = FakeChain(identity=HOUSE, tick=tick, balances={HOUSE: 100_000, ALICE: 5_000, BOB: 5_000, CARL: 5_000})

    def view(self, identity):
        return View(self.core, identity)


class View:
    """A signing view over the shared fake ledger: same ticks, own identity."""

    def __init__(self, core, identity):
        self.core, self.identity = core, identity

    def current_tick(self):
        return self.core.current_tick()

    def balance(self, i):
        return self.core.balance(i)

    def confirm(self, tx, tick):
        return self.core.confirm(tx, tick)

    def transactions_to(self, i, a, b):
        return self.core.transactions_to(i, a, b)

    def send(self, dest, amount, payload=b"", input_type=0):
        saved = self.core.identity
        self.core.identity = self.identity
        try:
            return self.core.send(dest, amount, payload, input_type)
        finally:
            self.core.identity = saved


@pytest.fixture
def world():
    return World()


def make_house(world, tmp_path, **kw):
    return House(world.view(HOUSE), str(tmp_path / "house"), HOUSE, rake_bps=kw.pop("rake_bps", 500),
                 seed_per_round=kw.pop("seed", 10_000), **kw)


def make_bot(world, tmp_path, who, solver, name=None):
    return Bot(world.view(who), str(tmp_path / f"bot-{who[0]}"), solver, name=name)


def publish_and_open(h, world, path, fee=1000, wc=50, wr=20):
    meta = h.publish(path, fee, wc, wr)
    world.core.advance(world.core.schedule_offset)
    return h.confirm_publish(meta["round_id"])


def test_full_round_two_bots_one_wins(world, tmp_path):
    h = make_house(world, tmp_path)
    meta = publish_and_open(h, world, riddle_file(tmp_path))
    assert meta["status"] == "open" and meta["publish_tick"] == 1005
    h.collect()
    board = h.export(str(tmp_path / "web"))
    board = json.load(open(tmp_path / "web" / "board.json"))
    assert [r["round_id"] for r in board["rounds"]] == [1] and board["rounds"][0]["state"] == "commit"

    alice = make_bot(world, tmp_path, ALICE, SUM_SOLVER, name="RYUBOT")
    bob = make_bot(world, tmp_path, BOB, WRONG_SOLVER, name="KEN.EXE")
    alice.house = HOUSE; alice.bow()
    acts = alice.step(board) + bob.step(board)
    assert any("committed" in a for a in acts) and len([a for a in acts if "committed" in a]) == 2
    assert alice.step(board) == [] and bob.step(board) == []  # idempotent: no second commit
    world.core.advance(world.core.schedule_offset)                 # commits land at 1010
    assert world.core.balances[HOUSE] == 100_000 + 2000

    world.core.advance(1005 + 50 - world.core.tick)                # end of commit window
    assert alice.step(board) == []                                  # commit window: nothing to reveal yet
    world.core.advance(1)                                           # reveal window opens
    acts = alice.step(board) + bob.step(board)
    assert len([a for a in acts if "revealed" in a]) == 2
    assert alice.step(board) == []
    world.core.advance(world.core.schedule_offset)                 # reveals land

    with pytest.raises(HouseError):                                 # window not over: refuse to settle
        h.collect(); h.settle(1)
    world.core.advance(1005 + 70 + 1 - world.core.tick)
    h.collect()
    plan = h.settle(1, apply=False)
    assert plan["winners"] == [ALICE] and plan["payouts"][0]["confirmed"] is False
    assert world.core.balances[ALICE] == 4000                       # plan moved nothing

    before = world.core.balances[HOUSE]
    # settle sends and waits for confirmation; the fake chain needs ticks to pass, so drive it from confirm
    orig_confirm = h.chain.confirm
    def confirm_advancing(tx, tick):
        if world.core.tick < tick:
            world.core.advance(tick - world.core.tick)
        return orig_confirm(tx, tick)
    h.chain.confirm = confirm_advancing
    doc = h.settle(1, apply=True)
    pot = 10_000 + 2000; rake = 2000 * 500 // 10000
    assert doc["pot"] == pot and doc["rake"] == rake and doc["winners"] == [ALICE]
    assert doc["payouts"][0]["confirmed"] and doc["payouts"][0]["amount"] == pot - rake
    assert world.core.balances[ALICE] == 4000 + pot - rake
    assert world.core.balances[HOUSE] == before - (pot - rake)
    assert h.meta(1)["status"] == "settled" and h.state()["carry"] == 0
    assert hashing.settlement_hash(doc).hex() == doc["hash"]
    world.core.advance(world.core.schedule_offset)                 # the SETTLE message lands
    settle_msgs = [payload.try_decode(o.payload) for o in world.core.ledger if o.source == HOUSE and o.dest == HOUSE]
    assert any(isinstance(m, payload.Settle) and m.settlement_hash.hex() == doc["hash"] for m in settle_msgs)
    # the published salt reproduces the commitment: anyone can verify
    assert hashing.answer_commitment(1, bytes.fromhex(doc["dojo_salt"]), doc["answer"]).hex() == meta["answer_commitment"]

    assert h.settle(1, apply=True) == doc                           # idempotent
    hist = h.export(str(tmp_path / "web"))
    r = hist["rounds"][0]
    assert r["state"] == "settled" and r["settlement"]["winners"] == [ALICE]
    assert hashing.settlement_hash(r["settlement"]).hex() == r["settlement"]["hash"]   # the page re-verifies this
    assert r["rake_bps"] == 500
    names = {f["identity"]: f["name"] for f in hist["fighters"]}
    assert names[ALICE] == "RYUBOT" and names[BOB] is None      # bob never bowed
    top = hist["fighters"][0]
    assert top["identity"] == ALICE and top["wins"] == 1 and top["earned"] == pot - rake
    assert json.load(open(tmp_path / "web" / "board.json"))["rounds"] == []


def test_no_winner_carries_into_next_round(world, tmp_path):
    h = make_house(world, tmp_path)
    publish_and_open(h, world, riddle_file(tmp_path))
    bob = make_bot(world, tmp_path, BOB, WRONG_SOLVER)
    h.collect(); board = h.export(str(tmp_path / "web"))
    bob.step(json.load(open(tmp_path / "web" / "board.json")))
    world.core.advance(1005 + 51 - world.core.tick)
    bob.step(json.load(open(tmp_path / "web" / "board.json")))
    world.core.advance(1005 + 71 - world.core.tick + 25)
    h.collect()
    doc = h.settle(1, apply=True)
    assert doc["winners"] == [] and doc["payouts"] == []
    assert doc["carry"] == 10_000 + 1000 - 50 and h.state()["carry"] == doc["carry"]
    meta = h.publish(riddle_file(tmp_path, rid=2), 1000, 50, 20)
    assert meta["house_seed"] == 10_000 + doc["carry"] and h.state()["carry"] == 0


def test_settle_survives_a_lost_send_without_double_paying(world, tmp_path):
    h = make_house(world, tmp_path)
    publish_and_open(h, world, riddle_file(tmp_path))
    alice = make_bot(world, tmp_path, ALICE, SUM_SOLVER)
    h.collect(); h.export(str(tmp_path / "web"))
    board = json.load(open(tmp_path / "web" / "board.json"))
    alice.step(board)
    world.core.advance(1005 + 51 - world.core.tick); alice.step(board)
    world.core.advance(1005 + 71 - world.core.tick + 25); h.collect()
    orig_confirm = h.chain.confirm
    def confirm_advancing(tx, tick):
        if world.core.tick < tick:
            world.core.advance(tick - world.core.tick)
        return orig_confirm(tx, tick)
    h.chain.confirm = confirm_advancing
    world.core.drop_next_send = True                                # the payout never lands
    with pytest.raises(HouseError):
        h.settle(1, apply=True)
    ledger = json.load(open(h._ledger_path(1)))
    assert ledger[0]["tx"].startswith("lost") and not ledger[0]["confirmed"]
    doc = h.settle(1, apply=True)                                   # resend, exactly once
    assert doc["payouts"][0]["confirmed"]
    wins = [o for o in world.core.ledger if o.source == HOUSE and o.dest == ALICE]
    assert len(wins) == 1 and world.core.balances[ALICE] == 4000 + (10_000 + 1000) - 50


def test_unknown_reads_abort_never_zero(world, tmp_path):
    h = make_house(world, tmp_path)
    world.core.fail_reads = True
    with pytest.raises(Unknown):
        h.publish(riddle_file(tmp_path), 1000, 50, 20)
    world.core.fail_reads = False
    publish_and_open(h, world, riddle_file(tmp_path))
    world.core.fail_reads = True
    with pytest.raises(Unknown):
        h.collect()
    assert h.state()["scanned_to"] == 0                              # a failed scan advances nothing


def test_publish_refuses_wrong_round_and_unfunded_seed(world, tmp_path):
    h = make_house(world, tmp_path)
    with pytest.raises(HouseError):
        h.publish(riddle_file(tmp_path, rid=2), 1000, 50, 20)
    with pytest.raises(HouseError):
        h.publish(riddle_file(tmp_path), 1000, 50, 20, house_seed=10**9)


def test_secret_is_0600_and_riddle_public_has_no_answer(world, tmp_path):
    h = make_house(world, tmp_path)
    h.publish(riddle_file(tmp_path), 1000, 50, 20)
    sec = h._rpath(1, "secret.json")
    assert oct(os.stat(sec).st_mode & 0o777) == "0o600"
    assert "answer" not in json.load(open(h._rpath(1, "riddle.json")))


def test_bot_does_not_reveal_if_its_commit_never_landed(world, tmp_path):
    h = make_house(world, tmp_path)
    publish_and_open(h, world, riddle_file(tmp_path))
    h.collect(); h.export(str(tmp_path / "web"))
    board = json.load(open(tmp_path / "web" / "board.json"))
    alice = make_bot(world, tmp_path, ALICE, SUM_SOLVER)
    world.core.drop_next_send = True
    alice.step(board)
    world.core.advance(1005 + 51 - world.core.tick)
    acts = alice.step(board)
    assert acts == ["round 1: commit never landed, sitting this one out"]
    assert not any(o.source == ALICE for o in world.core.ledger)


def test_bot_ignores_a_tampered_riddle(world, tmp_path):
    h = make_house(world, tmp_path)
    publish_and_open(h, world, riddle_file(tmp_path))
    h.collect(); h.export(str(tmp_path / "web"))
    board = json.load(open(tmp_path / "web" / "board.json"))
    board["rounds"][0]["riddle"]["input"] = "1\n1"
    alice = make_bot(world, tmp_path, ALICE, SUM_SOLVER)
    assert alice.step(board) == ["round 1: riddle hash mismatch, ignoring"]
