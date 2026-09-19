"""Opt-in, synthetic Qubic exercises. Pure house-side generators, not a VM.

Rules are pinned to core 9896264e9de2224bd30be71248eeba9077b56203.
Every exercise carries its complete rules and version in the hashed public
statement/input. Answers are computed from generation-time bookkeeping;
tests independently reconstruct them from the public representation.
"""
import json


def _body(family, title, statement, data, answer):
    return {
        "title": title + " v1",
        "statement": statement + " Answer with a single decimal integer. All arithmetic is exact; no overflow.",
        "input": json.dumps({"family": family, "version": 1, **data}, sort_keys=True, separators=(",", ":")),
        "answer_format": "integer",
        "answer": answer,
    }


def transaction_audit(rng):
    """Encode semantic records, retaining their known contribution before packing."""
    keys = [rng.randbytes(32).hex() for _ in range(3)]
    tick = rng.randrange(2**31, 2**32 - 100)
    typ = rng.choice([1, 257, 4096, 65535])
    metric = rng.choice(["amount", "count", "payload_u64"])
    query = {"destination": keys[0], "input_type": typ, "tick_min": tick,
             "tick_max": tick + 20, "metric": metric}
    frames, answer = [], 0
    # Always exercise every trap, then vary the mixture and order.
    modes = ["ok", "ok", "short_payload", "negative", "before", "after", "destination",
             "type", "truncated", "trailing", "size", "short_header"]
    modes += [rng.choice(modes[:8]) for _ in range(rng.randint(5, 14))]
    for mode in modes:
        amount = rng.randrange(1, 10**12)
        value = rng.randrange(2**53, 2**63)  # float parsing loses information
        when = rng.choice([tick, tick + 20, rng.randint(tick, tick + 20)])
        dest, input_type = keys[0], typ
        payload = value.to_bytes(8, "little") + rng.randbytes(rng.randint(0, 12))
        if mode == "short_payload":
            payload = rng.randbytes(rng.randint(0, 7))
        elif mode == "negative":
            amount = -amount
        elif mode == "before":
            when = tick - 1
        elif mode == "after":
            when = tick + 21
        elif mode == "destination":
            dest = keys[1]
        elif mode == "type":
            input_type = (typ + 1) % 65536
        size = len(payload) + (1 if mode == "size" else 0)
        frame = (bytes.fromhex(keys[2]) + bytes.fromhex(dest)
                 + amount.to_bytes(8, "little", signed=True) + when.to_bytes(4, "little")
                 + input_type.to_bytes(2, "little") + size.to_bytes(2, "little")
                 + payload + rng.randbytes(64))
        if mode == "truncated":
            frame = frame[:-1]
        elif mode == "trailing":
            frame += b"\x00"
        elif mode == "short_header":
            frame = frame[:rng.randint(1, 79)]
        frames.append(frame.hex())
        if mode in ("ok", "short_payload"):
            answer += {"amount": amount, "count": 1,
                       "payload_u64": value if len(payload) >= 8 else 0}[metric]
    rng.shuffle(frames)
    return _body("qubic_transaction_audit", "Qubic transaction audit",
        "Audit synthetic transaction frames from the JSON input. Each hex frame is independent. "
        "Layout: source public key bytes [0,32), destination [32,64), signed int64 amount [64,72), "
        "uint32 tick [72,76), uint16 inputType [76,78), uint16 inputSize [78,80), then inputSize "
        "payload bytes and 64 signature bytes. All integers are little-endian. Keys are raw hex, "
        "not encoded Qubic identities. Retain only frames with at least 80 bytes, exact total length "
        "80+inputSize+64, and nonnegative amount. Then filter by query destination, input_type, "
        "and inclusive tick_min..tick_max. Metric amount sums QU; count counts retained frames; "
        "payload_u64 sums the first eight payload bytes as uint64, skipping payloads shorter than eight. "
        "Duplicates count separately; an empty result is zero. Signatures are dummy bytes: this "
        "exercise checks framing and filtering, not signature validity, consensus or full protocol validity.",
        {"query": query, "frames": frames}, answer)


def call_audit(rng):
    """Build nested calls while recording correct audit receipts, then discard receipts."""
    users = [f"U{i}" for i in range(1, 5)]
    transactions, receipts = [], []
    for tx_index in range(rng.randint(3, 5)):
        origin = users[tx_index % len(users)]
        events = []

        def visit(contract, caller, depth):
            reward = rng.randrange(20, 10000)
            events.append({"op": "enter", "contract": contract, "reward": reward})
            # One accepted check per frame, plus rejected/threshold cases.
            for allowed, fee in [(origin, rng.randrange(reward)),
                                 (caller if caller != origin else users[(tx_index + 1) % 4], 0),
                                 (origin, reward + 1)]:
                events.append({"op": "audit", "allowed": allowed, "fee": fee})
                if allowed == origin and reward >= fee:
                    receipts.append((origin, caller, reward, reward - fee))
            if depth < 2:
                # Cross-contract calls go to lower contract indices.
                for child in rng.sample(range(1, contract), 2):
                    if child > 2 or depth == 1:
                        visit(child, f"C{contract}", depth + 1)
            # This check after returning from children tests restoration of context.
            fee = rng.choice([0, reward, reward + 1])
            events.append({"op": "audit", "allowed": origin, "fee": fee})
            if fee <= reward:
                receipts.append((origin, caller, reward, reward - fee))
            events.append({"op": "exit"})

        visit(rng.randint(20, 30), origin, 0)
        transactions.append({"originator": origin, "events": events})
    metric = rng.choice(["accepted", "refund", "credited"])
    eligible = sorted({r[1] for r in receipts if r[3] > 0}) if metric == "refund" else users
    identity = rng.choice(eligible)
    answer = sum(1 if metric == "accepted" else
                 r[3] if metric == "refund" and r[1] == identity else
                 r[2] if metric == "credited" and r[0] == identity else 0 for r in receipts)
    buggy = ("if invocator == allowed and root_reward >= fee: "
             "return (originator, root_reward - fee, invocator, root_reward)")
    return _body("qubic_call_audit", "Qubic call audit",
        "Repair the auditor's interpretation of these synthetic, completed user-procedure traces. "
        "Each transaction starts with its originator user. enter pushes a contract call frame; exit "
        "pops it. At an audit event, originator is the transaction's initiating user, invocator is "
        "the parent contract (label C followed by its index) or the user for a top-level call, "
        "and invocationReward is the reward on the CURRENT frame. Nested returns restore the parent "
        "context. The intended auditor accepts iff originator equals allowed AND invocationReward "
        "is at least fee. Each accepted audit produces a hypothetical receipt: refund "
        "(invocationReward-fee) to invocator, and credit invocationReward to originator. Rejected "
        "audits produce nothing. These are independent read-only calculations, not actual transfers "
        "or balance mutations. buggy_auditor is incorrect pseudocode to diagnose; follow the intended "
        "rules instead. Query metric accepted counts all accepted audits (ignores identity); refund "
        "sums refunds to identity; credited sums credits to identity. Labels represent distinct "
        "identities. All calls are assumed completed and sufficiently funded; no system procedures, "
        "callbacks or execution fees are modeled.",
        {"transactions": transactions, "buggy_auditor": buggy,
         "query": {"metric": metric, "identity": identity}}, answer)


def asset_ledger(rng):
    """Replay normalized effects in a complete slot ledger, then query final state."""
    fields = ("issuer", "name", "owner", "possessor", "manager")
    users = [f"U{i}" for i in range(1, 5)]
    assets = [("I1", "DOJO"), ("I2", "DOJO"), ("I1", "CUP")]
    balances, initial, journal = {}, [], []

    def slot(key):
        return dict(zip(fields, key))

    for issuer, name in assets:
        for i, user in enumerate(users):
            key = (issuer, name, user, users[(i + 1) % 4], 1)
            quantity = rng.randint(200, 2000)
            balances[key] = quantity
            # Fragmented records must be combined, not overwritten.
            split = rng.randint(1, quantity - 1)
            initial.extend([{"slot": slot(key), "shares": split},
                            {"slot": slot(key), "shares": quantity - split}])
    for i in range(rng.randint(24, 40)):
        source = rng.choice([k for k, v in balances.items() if v > 0])
        issuer, name, owner, possessor, manager = source
        operation = "management" if i % 3 == 0 else "transfer"
        if operation == "management":
            destination = (issuer, name, owner, possessor, rng.choice([m for m in (1, 2, 3) if m != manager]))
        else:
            recipient = rng.choice(users)
            destination = (issuer, name, recipient, recipient, manager)
        shares = rng.choice([1, balances[source], rng.randint(1, balances[source])])
        applied = i % 5 != 0
        journal.append({"operation": operation, "from": slot(source), "to": slot(destination),
                        "shares": shares, "status": "applied" if applied else "rejected"})
        if applied:
            balances[source] -= shares
            balances[destination] = balances.get(destination, 0) + shares
    rng.shuffle(initial)
    role = rng.choice(["owner", "possessor"])
    chosen = rng.choice([k for k, v in balances.items() if v > 0])
    manager_filter = rng.choice([None, chosen[4]])
    identity = chosen[fields.index(role)]
    answer = sum(n for k, n in balances.items() if k[:2] == chosen[:2]
                 and k[fields.index(role)] == identity and (manager_filter is None or k[4] == manager_filter))
    return _body("qubic_asset_ledger", "Qubic asset ledger",
        "Reconstruct shares from a synthetic normalized asset journal. Asset identity is the pair "
        "(issuer,name), never name alone. A slot is (issuer,name,owner,possessor,manager). In this "
        "exercise a single manager denotes BOTH ownership and possession management contracts, "
        "which are always equal. Owner, possessor and manager are distinct roles. Sum initial "
        "records with identical slots. In journal order, ignore rejected events; for each applied "
        "event subtract shares from its exact from slot and add shares to its exact to slot. "
        "Transfer effects keep asset and manager unchanged and set owner and possessor to the same "
        "recipient; management "
        "effects keep asset, owner and possessor unchanged but change manager. A self-transfer nets "
        "zero. Applied events are already confirmed and never overdraw a source. These are normalized "
        "effects, not raw Qubic logs or a simulation of authorization, callbacks or transfer fees. "
        "Query the total shares for issuer/name where the named role (owner or possessor) equals "
        "identity. manager null means all managers; otherwise require the given manager as well. "
        "No issuance or burns occur in the journal. Unknown matching holdings count as zero.",
        {"initial": initial, "journal": journal,
         "query": {"issuer": chosen[0], "name": chosen[1], "role": role,
                   "identity": identity, "manager": manager_filter}}, answer)


KINDS = {
    "orange": {"qubic_transaction_audit": transaction_audit},
    "green": {"qubic_asset_ledger": asset_ledger},
    "blue": {"qubic_call_audit": call_audit},
}
