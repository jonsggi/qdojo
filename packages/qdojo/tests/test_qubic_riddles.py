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


MAX_AMOUNT = 10**15
FIELDS = ("issuer", "name", "owner", "possessor", "manager")


def solve_public(d, bugs=()):
    """Reference solver from the public JSON. `bugs` names rules to break on purpose."""
    data = json.loads(d["input"])
    kind = data["family"]
    q = data["query"]
    if kind == "qubic_transaction_audit":
        total = 0
        for text in data["frames"]:
            frame = bytes.fromhex(text)
            if len(frame) < 80:
                continue
            src, dest, amount, tick, typ, size = struct.unpack("<32s32sqIHH", frame[:80])
            if len(frame) != 80 + size + 64 or amount < 0:
                continue
            if amount > MAX_AMOUNT and "max_amount" not in bugs:
                continue
            if dest.hex() != q["destination"] or typ != q["input_type"]:
                continue
            if "source" in q and src.hex() != q["source"] and "source" not in bugs:
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
            stack, valid, sub = [], True, 0
            for event in tx["events"]:
                if event["op"] == "enter":
                    if stack and event["contract"] >= stack[-1]["contract"]:
                        valid = False
                    stack.append(event)
                elif event["op"] == "exit":
                    stack.pop()
                else:
                    caller = tx["originator"] if len(stack) == 1 else f"C{stack[-2]['contract']}"
                    reward = stack[0 if "root_reward" in bugs else -1]["reward"]
                    who = caller if "invocator_check" in bugs else tx["originator"]
                    if who != event["allowed"] or reward < event["fee"]:
                        continue
                    if q["metric"] == "accepted":
                        sub += 1
                    elif q["metric"] == "refund" and caller == q["identity"]:
                        sub += reward - event["fee"]
                    elif q["metric"] == "credited" and tx["originator"] == q["identity"]:
                        sub += reward
            assert stack == []
            if valid or "validity" in bugs:
                total += sub
        return total

    def key(slot):
        return tuple(slot[k] for k in FIELDS)

    def destination(event):
        slot = dict(event["from"])
        if event["operation"] == "transfer":
            slot["owner"] = event["recipient"]
            if "owner_only" not in bugs:
                slot["possessor"] = event["recipient"]
        else:
            slot["manager"] = event["new_manager"]
        return slot

    state = {}
    for row in data["initial"]:
        state[key(row["slot"])] = state.get(key(row["slot"]), 0) + row["shares"]
    for event in data["journal"]:
        src, dst = key(event["from"]), key(destination(event))
        if data["settled"] and "ignore_status" not in bugs:
            applied = event["status"] == "applied"
        else:
            applied = state.get(src, 0) >= event["shares"]
        if applied:
            state[src] = state.get(src, 0) - event["shares"]
            state[dst] = state.get(dst, 0) + event["shares"]
    return sum(n for k, n in state.items() if k[:2] == (q["issuer"], q["name"])
               and k[FIELDS.index(q["role"])] == q["identity"]
               and (q["manager"] is None or k[4] == q["manager"]))


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
    dest, source = bytes(range(32)), bytes(range(32, 64))
    def frame(amount=MAX_AMOUNT, tick=2**31 + 7, size=8, payload=b"\x09" + b"\x00" * 7, src=source):
        return struct.pack("<32s32sqIHH", src, dest, amount, tick, 65535, size) + payload + bytes(64)
    query = {"destination": dest.hex(), "input_type": 65535, "tick_min": 2**31 + 7,
             "tick_max": 2**31 + 7, "metric": "amount"}
    frames = [frame(), frame(amount=-1), frame(amount=MAX_AMOUNT + 1), frame(tick=2**31 + 6), frame(size=9),
              frame()[:-1], frame() + b"\x00", b"short", frame(amount=5, src=bytes(32))]
    data = {"family": "qubic_transaction_audit", "query": query, "frames": [x.hex() for x in frames]}
    assert solve_public({"input": json.dumps(data)}) == MAX_AMOUNT + 5
    query["source"] = source.hex()
    assert solve_public({"input": json.dumps(data)}) == MAX_AMOUNT
    query["metric"] = "payload_u64"
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


def _replay_ledger(data):
    """Replay a ledger by the stated rules; report which boundaries the journal hit."""
    def key(slot):
        return tuple(slot[k] for k in FIELDS)
    state, seen = {}, {"overdraw": False, "exact": False, "drained": False}
    for row in data["initial"]:
        state[key(row["slot"])] = state.get(key(row["slot"]), 0) + row["shares"]
    supply = sum(state.values())
    for event in data["journal"]:
        src = key(event["from"])
        if event["operation"] == "management":
            dst = src[:4] + (event["new_manager"],)
            assert dst[4] != src[4]
        else:
            dst = src[:2] + (event["recipient"], event["recipient"], src[4])
        held = state.get(src, 0)
        assert ("status" in event) == data["settled"] and event["shares"] > 0
        applied = event["status"] == "applied" if data["settled"] else held >= event["shares"]
        if not data["settled"]:
            seen["overdraw"] |= held < event["shares"]
            seen["drained"] |= held == 0
            seen["exact"] |= held == event["shares"]
        if applied:
            assert held >= event["shares"]
            state[src] = held - event["shares"]
            state[dst] = state.get(dst, 0) + event["shares"]
        assert sum(state.values()) == supply and min(state.values()) >= 0
    return seen


def test_asset_journals_preserve_supply_and_never_overdraw():
    for seed in range(40):
        _replay_ledger(json.loads(riddles.generate_kind("qubic_asset_ledger", random.Random(seed), 1)["input"]))


def _instances(kind, n=100):
    return [riddles.generate_kind(kind, random.Random(seed), 1) for seed in range(n)]


def test_transaction_instances_carry_every_validity_trap_and_each_rule_decides():
    sources = widths = big = 0
    for d in _instances("qubic_transaction_audit"):
        data = json.loads(d["input"])
        q = data["query"]
        amounts = [struct.unpack("<q", bytes.fromhex(f)[64:72])[0] for f in data["frames"] if len(f) >= 160]
        assert any(a > MAX_AMOUNT for a in amounts) and MAX_AMOUNT in amounts and any(a < 0 for a in amounts)
        assert solve_public(d, ("max_amount",)) != d["answer"]
        if "source" in q:
            sources += 1
            assert solve_public(d, ("source",)) != d["answer"]
        widths += q["tick_min"] == q["tick_max"]
        big += q["metric"] == "payload_u64" and d["answer"] >= 2**64
        assert "64 bits" in d["statement"]
    assert 30 <= sources <= 70 and widths >= 10 and big >= 10


def test_asset_instances_exercise_both_roles_both_status_modes_and_empty_results():
    settled = zero = possessor = possessor_bites = status_bites = drained = 0
    for d in _instances("qubic_asset_ledger"):
        data = json.loads(d["input"])
        zero += d["answer"] == 0
        if data["query"]["role"] == "possessor":
            possessor += 1
            possessor_bites += solve_public(d, ("owner_only",)) != d["answer"]
        if data["settled"]:
            settled += 1
            status_bites += solve_public(d, ("ignore_status",)) != d["answer"]
        else:
            seen = _replay_ledger(data)
            assert seen["overdraw"] and seen["exact"]
            drained += seen["drained"]
    assert 30 <= settled <= 70 and 1 <= zero <= 30 and 30 <= possessor <= 70
    assert drained * 2 >= 100 - settled
    assert possessor_bites * 2 >= possessor and status_bites * 2 >= settled


def test_call_instances_force_the_nested_traps_and_each_rule_decides():
    invalid = validity_bites = reward_bites = invocator_bites = zero = labels = 0
    for d in _instances("qubic_call_audit"):
        data = json.loads(d["input"])
        q = data["query"]
        zero += d["answer"] == 0
        labels += q["metric"] == "refund" and q["identity"].startswith("C")
        trap = restore = bad = False
        for tx in data["transactions"]:
            stack, parents, tx_bad, tx_trap, tx_restore = [], [], False, False, False
            for e in tx["events"]:
                if e["op"] == "enter":
                    tx_bad |= bool(stack) and e["contract"] >= stack[-1]["contract"]
                    if stack:
                        parents[-1] = True
                    stack.append(e)
                    parents.append(False)
                elif e["op"] == "exit":
                    stack.pop()
                    parents.pop()
                elif len(stack) >= 2:
                    tx_trap |= e["allowed"] == f"C{stack[-2]['contract']}"
                    tx_restore |= (len(stack) == 2 and parents[-1] and e["allowed"] == tx["originator"]
                                   and 0 < e["fee"] < stack[-1]["reward"])
            bad |= tx_bad
            # The forced probes must sit in a trace whose audits count, or nothing is at stake.
            trap |= tx_trap and not tx_bad
            restore |= tx_restore and not tx_bad
        assert trap and restore
        if bad:
            invalid += 1
            validity_bites += solve_public(d, ("validity",)) != d["answer"]
        reward_bites += solve_public(d, ("root_reward",)) != d["answer"]
        invocator_bites += solve_public(d, ("invocator_check",)) != d["answer"]
    assert 20 <= invalid <= 60 and 1 <= zero <= 20 and labels >= 10
    assert validity_bites * 2 >= invalid and reward_bites >= 50 and invocator_bites >= 50


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
    script = f"import json, struct, sys\nMAX_AMOUNT = {MAX_AMOUNT}\nFIELDS = {FIELDS!r}\n"
    script += inspect.getsource(solve_public)
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
