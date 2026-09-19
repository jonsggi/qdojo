"""Reconstruct answers from public inputs, independently of generator bookkeeping."""
import json
import random
import struct

import pytest

from qdojo import hashing, riddle, riddles


FAMILIES = {
    "qubic_transaction_audit": "orange",
    "qubic_asset_ledger": "green",
    "qubic_call_audit": "blue",
}


def solve_public(d):
    data = json.loads(d["input"])
    kind = data["family"]
    q = data["query"]
    if kind == "qubic_transaction_audit":
        total = 0
        for text in data["frames"]:
            frame = bytes.fromhex(text)
            if len(frame) < 80:
                continue
            _, dest, amount, tick, typ, size = struct.unpack("<32s32sqIHH", frame[:80])
            if len(frame) != 80 + size + 64 or amount < 0:
                continue
            if dest.hex() != q["destination"] or typ != q["input_type"]:
                continue
            if not q["tick_min"] <= tick <= q["tick_max"]:
                continue
            if q["metric"] == "amount":
                total += amount
            elif q["metric"] == "count":
                total += 1
            elif size >= 8:
                total += struct.unpack("<Q", frame[80:88])[0]
        return total
    if kind == "qubic_call_audit":
        total = 0
        for tx in data["transactions"]:
            stack = []
            for event in tx["events"]:
                if event["op"] == "enter":
                    stack.append(event)
                elif event["op"] == "exit":
                    stack.pop()
                else:
                    caller = tx["originator"] if len(stack) == 1 else f"C{stack[-2]['contract']}"
                    reward = stack[-1]["reward"]
                    if tx["originator"] != event["allowed"] or reward < event["fee"]:
                        continue
                    if q["metric"] == "accepted":
                        total += 1
                    elif q["metric"] == "refund" and caller == q["identity"]:
                        total += reward - event["fee"]
                    elif q["metric"] == "credited" and tx["originator"] == q["identity"]:
                        total += reward
            assert stack == []
        return total
    # A query can be answered by projecting each journal movement onto the
    # queried balance; no mutable universe or generator's slot table needed.
    def matches(slot):
        return (slot["issuer"] == q["issuer"] and slot["name"] == q["name"]
                and slot[q["role"]] == q["identity"]
                and (q["manager"] is None or slot["manager"] == q["manager"]))

    total = sum(row["shares"] for row in data["initial"] if matches(row["slot"]))
    for event in data["journal"]:
        if event["status"] == "applied":
            total += event["shares"] * (int(matches(event["to"])) - int(matches(event["from"])))
    return total


@pytest.mark.parametrize("kind,belt", FAMILIES.items())
def test_generated_answers_independently_recomputed(kind, belt, tmp_path):
    variants, answers, inputs = set(), set(), set()
    for seed in range(100):
        d = riddles.generate_kind(kind, random.Random(seed), 17)
        assert d == riddles.generate_kind(kind, random.Random(seed), 17)
        assert d["belt"] == belt and d["answer_format"] == "integer"
        assert d["answer"] == solve_public(d)
        assert hashing.canonical_answer(d["answer"], "integer") == str(d["answer"])
        data = json.loads(d["input"])
        assert data["family"] == kind and data["version"] == 1
        assert "seed" not in data and "answer" not in data
        variants.add(data["query"].get("metric", data["query"].get("role")))
        answers.add(d["answer"])
        inputs.add(d["input"])
        # Exercise the real authored/public/commitment boundary.
        path = tmp_path / "authored.json"
        path.write_text(json.dumps(d))
        public, secret = riddle.load_authored(str(path))
        assert "answer" not in public.public() and "kind" not in public.public()
        assert riddle.check_answer(public, secret, str(solve_public(public.public())))
        assert not riddle.check_answer(public, secret, str(d["answer"] + 1))
        assert riddle.commitment_for(public, secret) == hashing.answer_commitment(17, secret.dojo_salt, str(d["answer"]))
        changed = dict(data, version=2)
        assert riddle.from_public(dict(public.public(), input=json.dumps(changed))).hash() != public.hash()
    assert len(variants) >= 2 and len(answers) > 15 and len(inputs) == 100


def test_classic_pool_unchanged_and_mixed_opt_in():
    for belt in riddles.BELTS:
        classic = riddles.kinds(belt)
        assert not set(classic) & FAMILIES.keys()
        extra = [k for k, b in FAMILIES.items() if b == belt]
        assert riddles.kinds(belt, pack="mixed") == classic + extra
        assert riddles.kinds(belt, pack="qubic") == extra
        for seed in range(10):
            assert riddles.generate(belt, random.Random(seed), 1) == riddles.generate(belt, random.Random(seed), 1, pack="classic")
        if extra:
            assert riddles.generate(belt, random.Random(0), 1, pack="qubic")["kind"] == extra[0]
    with pytest.raises(riddles.RiddleGenError, match="no riddles"):
        riddles.generate("white", random.Random(0), 1, pack="qubic")
    with pytest.raises(riddles.RiddleGenError, match="pack"):
        riddles.kinds("orange", pack="typo")


def test_transaction_hand_fixture_catches_signedness_bounds_and_framing():
    dest = bytes(range(32))
    def frame(amount=2**54 + 3, tick=2**31 + 7, size=8, payload=b"\x09" + b"\x00" * 7):
        return struct.pack("<32s32sqIHH", bytes(32), dest, amount, tick, 65535, size) + payload + bytes(64)
    data = {"family": "qubic_transaction_audit", "query": {
        "destination": dest.hex(), "input_type": 65535, "tick_min": 2**31 + 7,
        "tick_max": 2**31 + 7, "metric": "amount"}, "frames": [x.hex() for x in (
            frame(), frame(amount=-1), frame(tick=2**31 + 6), frame(size=9), frame()[:-1], frame() + b"\x00", b"short")]}
    assert solve_public({"input": json.dumps(data)}) == 2**54 + 3
    data["query"]["metric"] = "payload_u64"
    assert solve_public({"input": json.dumps(data)}) == 9


def test_sample_cli_public_by_default_and_explicit_authored(capsys):
    from qdojo.cli import main
    args = ["riddle", "sample", "qubic_call_audit", "--rng-seed", "7"]
    main(args)
    public = json.loads(capsys.readouterr().out)
    assert set(public) == {"round_id", "title", "statement", "input", "answer_format"}
    main(args + ["--with-answer"])
    authored = json.loads(capsys.readouterr().out)
    assert authored["answer"] == solve_public(public)
    assert riddle.from_public(authored).public() == public


def test_spar_rejects_empty_pool_before_creating_files(tmp_path):
    from qdojo.spar import Spar
    with pytest.raises(riddles.RiddleGenError, match="no riddles"):
        Spar(None, ["white"], 1000, 50, 20, str(tmp_path / "r"), "web", "metrics", riddle_pack="qubic")
    assert not (tmp_path / "r").exists()


def test_asset_journals_preserve_supply_and_never_overdraw():
    for seed in range(40):
        d = json.loads(riddles.generate_kind("qubic_asset_ledger", random.Random(seed), 1)["input"])
        def key(slot):
            return tuple(slot[k] for k in ("issuer", "name", "owner", "possessor", "manager"))
        state = {}
        for row in d["initial"]:
            k = key(row["slot"])
            state[k] = state.get(k, 0) + row["shares"]
        supply = sum(state.values())
        for event in d["journal"]:
            src, dst = key(event["from"]), key(event["to"])
            assert src[:2] == dst[:2]
            if event["operation"] == "management":
                assert src[:4] == dst[:4]
            else:
                assert src[4] == dst[4] and dst[2] == dst[3]
            if event["status"] == "applied":
                assert state[src] >= event["shares"] > 0
                state[src] -= event["shares"]
                state[dst] = state.get(dst, 0) + event["shares"]
            assert sum(state.values()) == supply


@pytest.mark.parametrize("kind,belt", FAMILIES.items())
def test_qubic_spar_round_commits_reveals_settles_and_exports(kind, belt, tmp_path, monkeypatch):
    import inspect
    import sys
    import time
    from qdojo import spar
    from conftest import ALICE, BOB
    from test_house_and_bot import World, make_house, make_bot, drive_settle, WRONG_SOLVER

    world = World()
    house = make_house(world, tmp_path, seed=1000)
    # The solver receives only the normal public JSON through stdin.
    script = "import json, struct, sys\n" + inspect.getsource(solve_public)
    script += "\nprint(json.dumps({'answer': str(solve_public(json.load(sys.stdin)))}))\n"
    alice = make_bot(world, tmp_path, ALICE, [sys.executable, "-c", script])
    bob = make_bot(world, tmp_path, BOB, WRONG_SOLVER)
    board_path = tmp_path / "web" / "board.json"
    drive_settle(house, world)

    def advance(_):
        world.core.advance(1)
        if board_path.exists():
            board = json.loads(board_path.read_text())
            alice.step(board)
            bob.step(board)

    # Patch spar's view of time only. Patching time.sleep globally would also catch
    # subprocess.run's own polling sleep inside the solver call, and every such poll
    # would re-enter this harness and step the bots again mid-solve: the bot then
    # commits once per nesting level, and the reveal matches none of them.
    class SparTime:
        sleep = staticmethod(advance)

        def __getattr__(self, name):
            return getattr(time, name)

    monkeypatch.setattr(spar, "time", SparTime())
    runner = spar.Spar(house, [belt], 1000, 50, 20, str(tmp_path / "riddles"),
                       str(tmp_path / "web"), str(tmp_path / "metrics.jsonl"),
                       seed=7, poll=0, riddle_pack="qubic")
    row = runner.one_round(belt)
    assert row["kind"] == kind and row["riddle_pack"] == "qubic"
    assert row["settled"] and row["n_entries"] == 2 and row["n_solved"] == 1
    assert {e["identity"]: e["verdict"] for e in row["entries"]} == {ALICE: "winner", BOB: "wrong"}
    doc = house.settle(1)
    assert hashing.answer_commitment(1, bytes.fromhex(doc["dojo_salt"]), doc["answer"]).hex() == house.meta(1)["answer_commitment"]
    public = json.loads((tmp_path / "web" / "rounds" / "1.json").read_text())
    assert "answer" not in public and "dojo_salt" not in public
    assert json.loads((tmp_path / "metrics.jsonl").read_text())["kind"] == kind
