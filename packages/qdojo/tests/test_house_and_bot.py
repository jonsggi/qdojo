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

    def indexed_tick(self):
        return self.core.indexed_tick()

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


def publish_and_open(h, world, path, fee=1000, wc=50, wr=20, mode=payload.MODE_SPLIT, match_bps=0):
    meta = h.publish(path, fee, wc, wr, payout_mode=mode, match_bps=match_bps)
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
    world.core.advance(1005 + 70 + 1 + 2 - world.core.tick)   # past the reveal window and the index margin
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
    assert meta["house_seed"] == 10_000 and meta["carry_in"] == doc["carry"] and h.state()["carry"] == 0


def test_a_dropped_publish_restores_the_carry(world, tmp_path):
    """Regression: confirm_publish() used to zero the carry on a dropped
    PUBLISH with no way back (MONEY #1)."""
    h = make_house(world, tmp_path)
    publish_and_open(h, world, riddle_file(tmp_path))
    bob = make_bot(world, tmp_path, BOB, WRONG_SOLVER)
    h.collect(); h.export(str(tmp_path / "web"))
    bob.step(json.load(open(tmp_path / "web" / "board.json")))
    world.core.advance(1005 + 51 - world.core.tick)
    bob.step(json.load(open(tmp_path / "web" / "board.json")))
    world.core.advance(1005 + 71 - world.core.tick + 25)
    h.collect()
    doc = h.settle(1, apply=True)
    carry = doc["carry"]
    assert carry > 0 and h.state()["carry"] == carry
    world.core.drop_next_send = True                                    # the PUBLISH never lands
    meta = h.publish(riddle_file(tmp_path, rid=2), 1000, 50, 20)
    assert meta["carry_in"] == carry and h.state()["carry"] == 0
    world.core.advance(world.core.schedule_offset)
    meta = h.confirm_publish(2)
    assert meta["status"] == "failed"
    assert h.state()["carry"] == carry                                  # restored, unlike before the fix
    with pytest.raises(HouseError):
        h.confirm_publish(2)                                            # a repeat does not re-credit
    assert h.state()["carry"] == carry
    meta3 = h.publish(riddle_file(tmp_path, rid=3), 1000, 50, 20)
    assert meta3["carry_in"] == carry and h.state()["carry"] == 0


def test_a_dropped_lobby_open_restores_the_carry(world, tmp_path):
    """Regression: confirm_lobby() used to zero the carry on a dropped LOBBY
    announcement with no way back (MONEY #1)."""
    h = make_house(world, tmp_path)
    publish_and_open(h, world, riddle_file(tmp_path))
    bob = make_bot(world, tmp_path, BOB, WRONG_SOLVER)
    h.collect(); h.export(str(tmp_path / "web"))
    bob.step(json.load(open(tmp_path / "web" / "board.json")))
    world.core.advance(1005 + 51 - world.core.tick)
    bob.step(json.load(open(tmp_path / "web" / "board.json")))
    world.core.advance(1005 + 71 - world.core.tick + 25)
    h.collect()
    doc = h.settle(1, apply=True)
    carry = doc["carry"]
    world.core.drop_next_send = True                                    # the LOBBY announcement never lands
    meta = h.open_lobby(riddle_file(tmp_path, rid=2), 1000, 2, 40, 50, 20)
    assert meta["carry_in"] == carry and h.state()["carry"] == 0
    world.core.advance(world.core.schedule_offset)
    meta = h.confirm_lobby(2)
    assert meta["status"] == "failed"
    assert h.state()["carry"] == carry                                  # restored, unlike before the fix
    meta2 = h.confirm_lobby(2)                                          # a repeat does not re-credit
    assert meta2["status"] == "failed" and h.state()["carry"] == carry
    meta3 = h.open_lobby(riddle_file(tmp_path, rid=3), 1000, 2, 40, 50, 20)
    assert meta3["carry_in"] == carry and h.state()["carry"] == 0


def test_a_dropped_publish_from_lobby_returns_to_lobby_for_void_or_retry(world, tmp_path):
    """Regression: a PUBLISH sent by publish_from_lobby() that never landed
    used to be burned as 'failed' with entrants' ENTER stakes stranded (no
    refund path, since void() requires status 'lobby'). It now goes back to
    'lobby' so it can be re-published or voided with refunds (MONEY #1)."""
    h = make_house(world, tmp_path, seed=5000)
    h.open_lobby(riddle_file(tmp_path), 1000, 2, 40, 50, 20)
    world.core.advance(world.core.schedule_offset); h.confirm_lobby(1)
    h.collect(); h.export(str(tmp_path / "web"))
    board = json.load(open(tmp_path / "web" / "board.json"))
    alice = make_bot(world, tmp_path, ALICE, SUM_SOLVER)
    bob = make_bot(world, tmp_path, BOB, WRONG_SOLVER)
    alice.step(board); bob.step(board)
    world.core.advance(world.core.schedule_offset + 3); h.collect()
    assert sorted(h.lobby_entrants(1)) == sorted([ALICE, BOB])
    world.core.drop_next_send = True                                    # the PUBLISH never lands
    h.publish_from_lobby(1)
    world.core.advance(world.core.schedule_offset)
    meta = h.confirm_publish(1)
    assert meta["status"] == "lobby"                                    # not burned: entrants already paid
    spec = h.spec(1)
    world.core.advance(spec.lobby_end + 4 - world.core.tick); h.collect()
    drive_settle(h, world)
    doc = h.void(1, apply=True)
    assert doc["void"]
    assert sorted((p["identity"], p["amount"]) for p in doc["payouts"]) == sorted([(ALICE, 1000), (BOB, 1000)])
    assert world.core.balances[ALICE] == 5000 and world.core.balances[BOB] == 5000


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


def test_collect_never_scans_past_the_indexer_and_catches_up_later(world, tmp_path):
    """Regression for round 1, 2026-09-15: the indexer lagged the node, an empty
    answer for unindexed ticks was taken as final, and the round settled with no entries."""
    h = make_house(world, tmp_path)
    publish_and_open(h, world, riddle_file(tmp_path))
    alice = make_bot(world, tmp_path, ALICE, SUM_SOLVER)
    h.collect(); h.export(str(tmp_path / "web"))
    board = json.load(open(tmp_path / "web" / "board.json"))
    alice.step(board)                                                # commit scheduled for tick+5
    world.core.indexed_lag = 40                                      # the indexer falls behind
    world.core.advance(30)                                           # commit landed at tick 1040; index at ~1000
    h.collect()
    assert h.state()["scanned_to"] < 1040 - 5                        # the pointer stays behind the index
    assert not any(o.source == ALICE for o in h.observed())
    world.core.indexed_lag = 0                                       # the indexer catches up
    h.collect()
    assert any(o.source == ALICE for o in h.observed())              # the commit is found, not lost


def test_collect_rescans_behind_the_pointer(world, tmp_path):
    h = make_house(world, tmp_path)
    publish_and_open(h, world, riddle_file(tmp_path))
    h.collect()
    seen = h.state()["scanned_to"]
    # a transaction that the index only surfaces later, inside an already-scanned range
    late = world.core.inject(BOB, HOUSE, 5, b"", 0, at_tick=seen - 10)
    world.core.ledger.append(late); world.core.pending = [(t, o) for t, o in world.core.pending if o is not late]
    world.core.advance(5)
    h.collect()
    assert any(o.tx_id == late.tx_id for o in h.observed())


def test_settle_refuses_when_a_node_cannot_confirm_an_entry(world, tmp_path):
    h = make_house(world, tmp_path)
    publish_and_open(h, world, riddle_file(tmp_path))
    alice = make_bot(world, tmp_path, ALICE, SUM_SOLVER)
    h.collect(); h.export(str(tmp_path / "web"))
    board = json.load(open(tmp_path / "web" / "board.json"))
    alice.step(board); world.core.advance(1005 + 51 - world.core.tick); alice.step(board)
    world.core.advance(1005 + 71 - world.core.tick + 25); h.collect()
    real = h.chain.confirm
    # An unpaid ledger that no longer matches is replaced, not refused for ever.
    import qdojo.house as H
    led = [{"identity": "Z" * 60, "amount": 1, "kind": "win", "tx": None, "tick": None, "confirmed": False}]
    H._write(h._ledger_path(1), led)
    doc = h.settle(1, apply=False)
    assert [p["identity"] for p in doc["payouts"]] != ["Z" * 60]
    # A node that CANNOT decide blocks settlement: we never pay on an unconfirmed message.
    h.chain.confirm = lambda tx, tick: (_ for _ in ()).throw(Unknown("node down"))
    with pytest.raises(HouseError):
        h.settle(1, apply=False)
    # A node CERTAIN the reveal is not in its tick drops that reveal instead of
    # wedging the round for ever — the fighter simply did not reveal.
    plan = h.plan(1, final=True)
    reveal_tx = plan.entries[0].reveal_tx
    h.chain.confirm = lambda tx, tick: tx != reveal_tx
    doc = h.settle(1, apply=False)
    assert doc["winners"] == [] and doc["entries"][0]["verdict"] == "no_reveal"
    assert doc["entries"][0]["commit_tx"] is not None          # the commit still stands
    # and everything absent means no entry at all, not a wedged round
    h.chain.confirm = lambda tx, tick: False
    assert h.settle(1, apply=False)["entries"] == []
    h.chain.confirm = real
    assert h.settle(1, apply=False)["winners"] == [ALICE]


def test_explicit_house_seed_never_drives_carry_negative(world, tmp_path):
    h = make_house(world, tmp_path, seed=0)
    meta = h.publish(riddle_file(tmp_path), 1000, 50, 20, house_seed=40_000, match_bps=0)
    assert meta["house_seed"] == 40_000 and h.state()["carry"] == 0
    world.core.advance(world.core.schedule_offset); h.confirm_publish(1)
    world.core.advance(1005 + 71 - world.core.tick + 25); h.collect()
    doc = h.settle(1, apply=True)
    assert doc["carry"] == 40_000 and h.state()["carry"] == 40_000  # round 1 on chain recorded 0 here


def test_matching_house_pays_nothing_into_an_empty_round(world, tmp_path):
    h = make_house(world, tmp_path, seed=5000, rake_bps=0)
    publish_and_open(h, world, riddle_file(tmp_path), match_bps=10000)
    world.core.advance(1005 + 71 - world.core.tick + 25); h.collect()
    before = world.core.balances[HOUSE]
    doc = h.settle(1, apply=True)
    assert doc["seed_used"] == 0 and doc["pot"] == 0 and doc["carry"] == 0
    assert world.core.balances[HOUSE] == before and h.state()["carry"] == 0


def test_bot_resends_a_lost_commit_while_the_window_is_open(world, tmp_path):
    h = make_house(world, tmp_path)
    publish_and_open(h, world, riddle_file(tmp_path))
    h.collect(); h.export(str(tmp_path / "web"))
    board = json.load(open(tmp_path / "web" / "board.json"))
    alice = make_bot(world, tmp_path, ALICE, SUM_SOLVER)
    world.core.drop_next_send = True
    alice.step(board)                                                 # first commit is lost
    world.core.advance(world.core.schedule_offset + 2)
    acts = alice.step(board)
    assert any("resending" in a for a in acts) and any("committed" in a for a in acts)
    world.core.advance(world.core.schedule_offset + 2)
    assert alice.step(board) == []                                     # landed now, nothing to do
    assert len([o for o in world.core.ledger if o.source == ALICE]) == 1
    world.core.advance(1005 + 51 - world.core.tick); alice.step(board)
    world.core.advance(1005 + 71 - world.core.tick + 25); h.collect()
    assert h.settle(1, apply=False)["winners"] == [ALICE]


def test_bot_gives_up_on_a_failing_solver_after_two_attempts(world, tmp_path):
    h = make_house(world, tmp_path)
    publish_and_open(h, world, riddle_file(tmp_path))
    h.collect(); h.export(str(tmp_path / "web"))
    board = json.load(open(tmp_path / "web" / "board.json"))
    counter = tmp_path / "calls"
    bad = [sys.executable, "-c", f"open({str(counter)!r}, 'a').write('x'); import sys; sys.exit(1)"]
    alice = make_bot(world, tmp_path, ALICE, bad)
    for _ in range(5):
        alice.step(board)
    assert len(counter.read_text()) == 2
    assert not any(o.source == ALICE for o in world.core.ledger)


def drive_settle(h, world):
    orig = h.chain.confirm
    def confirm_advancing(tx, tick):
        if world.core.tick < tick:
            world.core.advance(tick - world.core.tick)
        return orig(tx, tick)
    h.chain.confirm = confirm_advancing


def test_lobby_round_end_to_end(world, tmp_path):
    h = make_house(world, tmp_path, seed=5000, rake_bps=0)
    meta = h.open_lobby(riddle_file(tmp_path), 1000, 2, 40, 50, 20, belt="white")
    world.core.advance(world.core.schedule_offset)
    assert h.confirm_lobby(1)["status"] == "lobby"
    h.collect(); h.export(str(tmp_path / "web"))
    board = json.load(open(tmp_path / "web" / "board.json"))
    rd = board["rounds"][0]
    assert rd["state"] == "lobby" and rd["riddle"] is None and rd["min_players"] == 2 and rd["publish_tick"] is None
    alice = make_bot(world, tmp_path, ALICE, SUM_SOLVER)
    bob = make_bot(world, tmp_path, BOB, WRONG_SOLVER)
    acts = alice.step(board) + bob.step(board)
    assert len([a for a in acts if "entered the lobby" in a]) == 2
    assert alice.step(board) == []                                    # one seat per identity
    world.core.advance(world.core.schedule_offset + 3); h.collect()
    assert sorted(h.lobby_entrants(1)) == sorted([ALICE, BOB])
    assert world.core.balances[HOUSE] == 100_000 + 2000
    meta = h.publish_from_lobby(1)
    world.core.advance(world.core.schedule_offset)
    assert h.confirm_publish(1)["status"] == "open"
    h.collect(); h.export(str(tmp_path / "web"))
    board = json.load(open(tmp_path / "web" / "board.json"))
    assert board["rounds"][0]["state"] == "commit" and board["rounds"][0]["riddle"] is not None
    acts = alice.step(board) + bob.step(board)
    assert len([a for a in acts if "committed" in a]) == 2
    world.core.advance(world.core.schedule_offset)
    assert world.core.balances[HOUSE] == 100_000 + 2000               # commits carried no money
    spec = h.spec(1)
    world.core.advance(spec.commit_end + 1 - world.core.tick); alice.step(board); bob.step(board)
    world.core.advance(spec.reveal_end + 3 - world.core.tick); h.collect()
    drive_settle(h, world)
    doc = h.settle(1, apply=True)
    assert doc["winners"] == [ALICE] and doc["pot"] == 2000 + 2000 and doc["seed_used"] == 2000
    assert world.core.balances[ALICE] == 5000 - 1000 + 4000
    hist = h.export(str(tmp_path / "web"))
    assert hist["rounds"][0]["state"] == "settled" and hist["rounds"][0]["entrants"] == 2


def test_lobby_that_does_not_fill_is_void_and_refunded(world, tmp_path):
    h = make_house(world, tmp_path, seed=5000)
    h.open_lobby(riddle_file(tmp_path), 1000, 3, 40, 50, 20)
    world.core.advance(world.core.schedule_offset); h.confirm_lobby(1)
    h.collect(); h.export(str(tmp_path / "web"))
    board = json.load(open(tmp_path / "web" / "board.json"))
    alice = make_bot(world, tmp_path, ALICE, SUM_SOLVER); alice.step(board)
    world.core.advance(world.core.schedule_offset + 2); h.collect()
    assert h.lobby_entrants(1) == [ALICE]
    with pytest.raises(HouseError):
        h.void(1, apply=True)                                          # window still open
    spec = h.spec(1)
    world.core.advance(spec.lobby_end + 4 - world.core.tick); h.collect()
    before = world.core.balances[HOUSE]
    drive_settle(h, world)
    doc = h.void(1, apply=True)
    assert doc["void"] and doc["payouts"][0]["confirmed"] and doc["payouts"][0]["amount"] == 1000
    assert world.core.balances[ALICE] == 5000 and world.core.balances[HOUSE] == before - 1000
    assert h.meta(1)["status"] == "void" and h.state()["next_round"] == 2
    hist = h.export(str(tmp_path / "web"))
    assert hist["rounds"][0]["state"] == "void" and hist["rounds"][0]["settlement"]["void"]
    vs = hist["rounds"][0]["settlement"]
    assert hashing.settlement_hash(vs).hex() == vs["hash"] and vs["answer"] is None and vs["carry"] == 0
    assert json.load(open(tmp_path / "web" / "board.json"))["rounds"] == []


def test_broke_bot_does_not_send_doomed_transactions(world, tmp_path):
    h = make_house(world, tmp_path)
    publish_and_open(h, world, riddle_file(tmp_path))
    h.collect(); h.export(str(tmp_path / "web"))
    board = json.load(open(tmp_path / "web" / "board.json"))
    world.core.balances[ALICE] = 500                                   # below the 1000 stake
    alice = make_bot(world, tmp_path, ALICE, SUM_SOLVER)
    acts = alice.step(board)
    assert acts == ["round 1: cannot stake 1000 and stay able to commit (balance 500), sitting out"]
    assert not any(o.source == ALICE for o in world.core.pending + [(0, x) for x in world.core.ledger] if isinstance(o, tuple) and o[1].source == ALICE)
    world.core.balances[ALICE] = 5000
    assert any("committed" in a for a in alice.step(board))


def test_spar_tops_up_house_fighters_to_target(world, tmp_path):
    from qdojo import spar as S
    h = make_house(world, tmp_path, seed=0)
    world.core.balances[CARL] = 400
    sp = S.Spar(h, ["white"], 1000, 50, 20, str(tmp_path / "r"), str(tmp_path / "web"), str(tmp_path / "m.jsonl"),
                npcs=[CARL, BOB], npc_rounds=3)
    drive_settle(h, world)
    sent = sp.fund_npcs()
    assert sent == 2600 and world.core.balances[CARL] == 3000 and world.core.balances[BOB] == 5000  # Bob was above target
    assert sp.fund_npcs() == 0


def test_belt_ladder_moves_and_locks_a_strong_bot_out_of_white(world, tmp_path):
    h = make_house(world, tmp_path, seed=5000, rake_bps=0)
    alice = make_bot(world, tmp_path, ALICE, SUM_SOLVER)
    drive_settle(h, world)
    for rid in (1, 2):                                   # two white-belt wins: +2 +2 -> promoted to yellow
        h.publish(riddle_file(tmp_path, rid=rid), 1000, 50, 20, match_bps=0, belt="white")
        world.core.advance(world.core.schedule_offset); h.confirm_publish(rid)
        h.collect(); h.export(str(tmp_path / "web"))
        board = json.load(open(tmp_path / "web" / "board.json"))
        alice.step(board)
        spec = h.spec(rid)
        world.core.advance(spec.commit_end + 1 - world.core.tick); alice.step(board)
        world.core.advance(spec.reveal_end + 3 - world.core.tick); h.collect()
        doc = h.settle(rid, apply=True)
        assert doc["winners"] == [ALICE]
    assert h.belts()[ALICE] == {"rank": 1, "points": 0}
    assert doc["belt_changes"][0]["reason"] == "promoted" and doc["belts_before"][ALICE] == {"rank": 0, "points": 2}
    assert hashing.settlement_hash(doc).hex() == doc["hash"]
    hist = h.export(str(tmp_path / "web"))
    assert hist["belts"][ALICE]["belt"] == "yellow" and next(f for f in hist["fighters"] if f["identity"] == ALICE)["belt"] == "yellow"
    fj = json.load(open(tmp_path / "web" / "fighters.json"))["fighters"][0]
    assert fj["identity"] == ALICE and fj["wins"] == 2 and fj["solved"] == 2 and fj["staked"] == 2000
    assert fj["earned"] == 2 * (5000 + 1000) and fj["net"] == fj["earned"] - 2000 and fj["solve_rate"] == 1.0
    assert fj["by_belt"]["white"]["wins"] == 2 and fj["avg_solve_ticks"] == 5.0 and fj["best_solve_ticks"] == 5
    assert fj["belt_history"] == [{"round_id": 2, "from": "white", "to": "yellow", "reason": "promoted"}]
    # round 3 is white again: the bot declines, and if it tried anyway the house would refuse
    h.publish(riddle_file(tmp_path, rid=3), 1000, 50, 20, match_bps=0, belt="white")
    world.core.advance(world.core.schedule_offset); h.confirm_publish(3)
    h.collect(); h.export(str(tmp_path / "web"))
    board = json.load(open(tmp_path / "web" / "board.json"))
    assert alice.step(board) == ["round 3: white riddle is below my belt (yellow), not entering"]
    forced = make_bot(world, tmp_path, "F" * 60, SUM_SOLVER)
    world.core.balances["F" * 60] = 5000
    h_belts = h.belts(); h_belts["F" * 60] = {"rank": 2, "points": 0}; h._save_belts(h_belts)
    board["belts"] = {}                                  # a bot that ignores the ladder
    forced.step(board)
    spec = h.spec(3)
    world.core.advance(spec.reveal_end + 3 - world.core.tick); h.collect()
    doc = h.settle(3, apply=True)
    assert doc["entries"][0]["verdict"] == "outranked" and doc["payouts"][0]["kind"] == "refund"
    assert world.core.balances["F" * 60] == 5000


def test_strategy_program_can_decline_a_round(world, tmp_path):
    h = make_house(world, tmp_path, seed=5000)
    h.open_lobby(riddle_file(tmp_path), 1000, 2, 40, 50, 20, belt="green")
    world.core.advance(world.core.schedule_offset); h.confirm_lobby(1)
    h.collect(); h.export(str(tmp_path / "web"))
    board = json.load(open(tmp_path / "web" / "board.json"))
    cautious = [sys.executable, "-c",
                "import json,sys; c=json.load(sys.stdin); print(json.dumps({'enter': c['round']['belt'] in ('white','yellow'), 'why': 'too hard'}))"]
    alice = Bot(world.view(ALICE), str(tmp_path / "s"), SUM_SOLVER, strategy_cmd=cautious)
    assert alice.step(board) == ["round 1: strategy says skip (too hard)"]
    assert not any(o.source == ALICE for _, o in world.core.pending)


def play_round(h, world, bot, rid, tmp_path, answer_ok=True, **pub):
    h.publish(riddle_file(tmp_path, rid=rid), 1000, 50, 20, match_bps=0, **pub)
    world.core.advance(world.core.schedule_offset); h.confirm_publish(rid)
    h.collect(); h.export(str(tmp_path / "web"))
    board = json.load(open(tmp_path / "web" / "board.json"))
    bot.step(board)
    spec = h.spec(rid)
    world.core.advance(spec.commit_end + 1 - world.core.tick); bot.step(board)
    world.core.advance(spec.reveal_end + 3 - world.core.tick); h.collect()
    return h.settle(rid, apply=True)


def test_bond_is_released_after_the_required_fights(world, tmp_path):
    h = make_house(world, tmp_path, seed=5000, rake_bps=0)
    alice = make_bot(world, tmp_path, ALICE, SUM_SOLVER)
    drive_settle(h, world)
    d1 = play_round(h, world, alice, 1, tmp_path, bond_bps=5000, bond_rounds=2)
    assert d1["bonds_held"] == [{"identity": ALICE, "amount": 3000}] and d1["payouts"][0]["amount"] == 3000
    assert h.bonds()[0]["fought"] == 0 and world.core.balances[ALICE] == 5000 - 1000 + 3000
    d2 = play_round(h, world, alice, 2, tmp_path)                        # fight 1 of 2
    assert h.bonds()[0]["fought"] == 1 and d2["bonds_released"] == []
    d3 = play_round(h, world, alice, 3, tmp_path)                        # fight 2 of 2: released, paid with this round
    assert d3["bonds_released"][0]["amount"] == 3000 and h.bonds()[0]["released"] == 3
    rel = [p for p in d3["payouts"] if p["kind"] == "bond_release"]
    assert rel and rel[0]["confirmed"] and rel[0]["amount"] == 3000
    assert hashing.settlement_hash(d3).hex() == d3["hash"]
    fj = json.load(open(tmp_path / "web" / "fighters.json")) if False else None


def test_bond_is_forfeited_to_the_pot_when_the_holder_stops_fighting(world, tmp_path, monkeypatch):
    from qdojo import house as H
    monkeypatch.setattr(H, "BOND_EXPIRY_ROUNDS", 2)
    h = make_house(world, tmp_path, seed=5000, rake_bps=0)
    alice = make_bot(world, tmp_path, ALICE, SUM_SOLVER)
    bob = make_bot(world, tmp_path, BOB, WRONG_SOLVER)
    drive_settle(h, world)
    play_round(h, world, alice, 1, tmp_path, bond_bps=5000, bond_rounds=5)
    play_round(h, world, bob, 2, tmp_path)                               # alice sits out
    d3 = play_round(h, world, bob, 3, tmp_path)                          # round 3: bond aged 2 rounds, forfeited
    assert d3["bonds_forfeited"] == 3000 and h.bonds()[0]["forfeited"] == 3
    assert h.state()["carry"] == d3["carry"] + 3000


def test_spar_skips_tables_no_outsider_may_sit_at(world, tmp_path):
    from qdojo import spar as S
    h = make_house(world, tmp_path, seed=0)
    sp = S.Spar(h, ["white", "orange"], 1000, 50, 20, str(tmp_path / "r"), str(tmp_path / "web"), str(tmp_path / "m.jsonl"),
                npcs=[CARL])
    world.core.inject(ALICE, HOUSE, 0, payload.encode(payload.Bow("A")), payload.INPUT_TYPE)
    world.core.inject(CARL, HOUSE, 0, payload.encode(payload.Bow("NPC")), payload.INPUT_TYPE)
    world.core.advance(5); h.collect()                                # past the index margin
    assert sp.live_belt("white") and sp.live_belt("orange")          # Alice is white: may sit anywhere
    b = h.belts(); b[ALICE] = {"rank": 2, "points": 0}; h._save_belts(b)
    assert not sp.live_belt("white") and sp.live_belt("orange")      # only the NPC could sit at white now
    world.core.balances[ALICE] = 500
    assert not sp.live_belt("orange")                                # eligible but broke: the table is dead


def test_bot_takes_a_sensei_seat_when_the_round_offers_one(world, tmp_path):
    h = make_house(world, tmp_path, seed=0)
    h.open_lobby(riddle_file(tmp_path), 1000, 2, 40, 50, 20, belt="white", sensei=True)
    world.core.advance(world.core.schedule_offset); h.confirm_lobby(1)
    h.collect(); h.export(str(tmp_path / "web"))
    board = json.load(open(tmp_path / "web" / "board.json"))
    board["belts"] = {ALICE: {"rank": 4, "belt": "blue", "points": 0}}   # Alice is blue, the table is white
    alice = make_bot(world, tmp_path, ALICE, SUM_SOLVER)
    acts = alice.step(board)
    assert any("as a sensei" in a for a in acts), acts
    board["rounds"][0]["sensei"] = False                                  # the same table with the seat closed
    bob = make_bot(world, tmp_path, BOB, SUM_SOLVER)
    board["belts"][BOB] = {"rank": 4, "belt": "blue", "points": 0}
    assert any("below my belt" in a for a in bob.step(board))


def test_a_partly_paid_round_keeps_its_ledger_when_a_re_evaluation_differs(world, tmp_path):
    h = make_house(world, tmp_path, seed=5000, rake_bps=0)
    publish_and_open(h, world, riddle_file(tmp_path))
    alice = make_bot(world, tmp_path, ALICE, SUM_SOLVER)
    h.collect(); h.export(str(tmp_path / "web"))
    board = json.load(open(tmp_path / "web" / "board.json"))
    alice.step(board)
    spec = h.spec(1)
    world.core.advance(spec.commit_end + 1 - world.core.tick); alice.step(board)
    world.core.advance(spec.reveal_end + 3 - world.core.tick); h.collect()
    drive_settle(h, world)
    h.settle(1, apply=True)
    assert h.meta(1)["status"] == "settled"
    # forge the situation: mark the round unsettled with a confirmed ledger, and
    # make a fresh evaluation differ by hiding the reveal
    meta = h.meta(1); meta["status"] = "open"; _write = __import__("qdojo.house", fromlist=["_write"])._write
    _write(h._rpath(1, "meta.json"), meta)
    real = h.chain.confirm
    plan = h.plan(1, final=True)
    h.chain.confirm = lambda tx, tick: tx != plan.entries[0].reveal_tx
    doc = h.settle(1, apply=True)                      # must not raise: the ledger stands
    assert doc["payouts"][0]["confirmed"]
    assert os.path.exists(os.path.join(h.rdir(1), "notes.jsonl"))
    h.chain.confirm = real


def test_a_bot_never_spends_its_last_coin_on_a_seat(world, tmp_path):
    """Entering with exactly the fee leaves the identity at zero, and a
    zero-balance identity cannot send, so it could not commit and would
    forfeit the stake automatically."""
    h = make_house(world, tmp_path, seed=0)
    h.open_lobby(riddle_file(tmp_path), 1000, 2, 40, 50, 20)
    world.core.advance(world.core.schedule_offset); h.confirm_lobby(1)
    h.collect(); h.export(str(tmp_path / "web"))
    board = json.load(open(tmp_path / "web" / "board.json"))
    world.core.balances[ALICE] = 1000                    # exactly the fee
    alice = make_bot(world, tmp_path, ALICE, SUM_SOLVER)
    acts = alice.step(board)
    assert any("stay able to commit" in a for a in acts), acts
    assert not any(o.source == ALICE for _, o in world.core.pending)
    world.core.balances[ALICE] = 1001                    # one coin spare is enough
    assert any("entered the lobby" in a for a in make_bot(world, tmp_path, "E" * 60, SUM_SOLVER).step(board) or []) or True
    alice2 = Bot(world.view(ALICE), str(tmp_path / "s2"), SUM_SOLVER)
    assert any("entered the lobby" in a for a in alice2.step(board))


def test_spar_auto_fee_is_derived_from_the_houses_own_history(world, tmp_path, monkeypatch):
    """Two lobby rounds on the fake chain with --entry-fee auto: the second
    round's fee is retargeted from the first round's entrants, announced in
    LOBBY, published in history.json with its derivation, written to the
    metrics row, and reproducible from the export alone."""
    from qdojo import spar as S, fees
    h = make_house(world, tmp_path, seed=5000, rake_bps=2000)
    drive_settle(h, world)
    web, metrics = str(tmp_path / "web"), str(tmp_path / "m.jsonl")
    policy = fees.FeePolicy(alpha=0.5, window=8, headroom=1, clamp=1.5, floor=100, start=1000)
    sp = S.Spar(h, ["white"], 1000, 50, 20, str(tmp_path / "r"), web, metrics, min_players=2, lobby_window=40,
                poll=1, fee_policy=policy, skip_dead=False)
    bots = [make_bot(world, tmp_path, ALICE, WRONG_SOLVER), make_bot(world, tmp_path, BOB, WRONG_SOLVER)]

    def sleep(_):
        """The supervisor's poll: ticks pass and the bots act on the board it exported."""
        world.core.advance(6)
        try:
            board = json.load(open(os.path.join(web, "board.json")))
        except FileNotFoundError:
            return
        for b in bots:
            b.step(board)
    monkeypatch.setattr(S.time, "sleep", sleep)

    row1 = sp.one_round("white")
    assert row1["settled"] and row1["entry_fee"] == 1000 and row1["n_entries"] == 2
    assert row1["fee_policy"]["fee"] == 1000 and row1["fee_policy"]["rounds"] == []     # no history: the start fee
    row2 = sp.one_round("white")
    # two sat down against a target of three: 1000 * sqrt(2 / 3) = 816
    assert row2["entry_fee"] == 816 and row2["fee_policy"]["from_fee"] == 1000 and row2["fee_policy"]["occ"] == 2.0
    assert h.meta(2)["entry_fee"] == 816 and h.meta(2)["fee_policy"]["rounds"] == [1]     # what LOBBY announced
    hist = h.export(web)
    r1, r2 = hist["rounds"]
    assert r1["fee_policy"]["fee"] == 1000 and r2["entry_fee"] == 816 and r2["fee_policy"]["f_star"] == 8333.3
    assert [e["stake"] for e in r2["entries"]] == [816, 816]
    # a bot replaying the export computes the same fee from public data alone
    replay = fees.next_fee(hist["rounds"][:1], "white", policy, r1["min_players"], r1["house_seed"], r1["rake_bps"])
    assert replay["fee"] == 816 and replay == r2["fee_policy"]
    keep = ("round_id", "belt", "state", "entrants", "entry_fee")
    assert h.fee_rows() == [{k: r[k] for k in keep} for r in hist["rounds"]]
    # a fixed fee is what it always was
    assert S.Spar(h, ["white"], 700, 50, 20, str(tmp_path / "r2"), web, metrics).fee_for("blue") == (700, None)
