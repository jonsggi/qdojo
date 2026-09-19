"""Opt-in, synthetic Qubic exercises. Pure house-side generators, not a VM.

Rules are pinned to core 9896264e9de2224bd30be71248eeba9077b56203.
Every exercise carries its complete rules and version in the hashed public
statement/input. Answers are computed from generation-time bookkeeping;
tests independently reconstruct them from the public representation.
"""
import json

# network_messages/common_def.h: MAX_AMOUNT = ISSUANCE_RATE * 1000, and
# Transaction::checkValidity() requires 0 <= amount <= MAX_AMOUNT.
MAX_AMOUNT = 10**15


def _body(family, title, statement, data, answer):
    return {
        "title": title + " v1",
        "statement": statement + " Answer with a single decimal integer. Use exact integer arithmetic: "
        "a sum may exceed 64 bits and must not wrap.",
        "input": json.dumps({"family": family, "version": 1, **data}, sort_keys=True, separators=(",", ":")),
        "answer_format": "integer",
        "answer": answer,
    }


def transaction_audit(rng):
    """Encode semantic records, retaining their known contribution before packing."""
    dest, other_dest, source, other_source = (rng.randbytes(32).hex() for _ in range(4))
    tick = rng.randrange(2**31, 2**32 - 100)
    width = rng.choice([0, 1, 20, rng.randint(2, 60)])
    typ = rng.choice([1, 257, 4096, 65535])
    metric = rng.choice(["amount", "count", "payload_u64"])
    query = {"destination": dest, "input_type": typ, "tick_min": tick, "tick_max": tick + width, "metric": metric}
    if rng.random() < 0.5:
        query["source"] = source
    frames, answer = [], 0
    # Always exercise every trap, then vary the mixture and order.
    modes = ["ok", "ok", "short_payload", "max_amount", "negative", "too_large", "before", "after",
             "destination", "type", "source", "truncated", "trailing", "size", "short_header"]
    modes += [rng.choice(modes[:11]) for _ in range(rng.randint(3, 10))]
    for mode in modes:
        amount = rng.randrange(1, 10**12)
        value = rng.randrange(2**53, 2**63)  # float parsing loses information
        when = rng.choice([tick, tick + width, rng.randint(tick, tick + width)])
        src, dst, input_type = source, dest, typ
        payload = value.to_bytes(8, "little") + rng.randbytes(rng.randint(0, 12))
        if mode == "short_payload":
            payload = rng.randbytes(rng.randint(0, 7))
        elif mode == "max_amount":
            amount = MAX_AMOUNT
        elif mode == "negative":
            amount = -amount
        elif mode == "too_large":
            amount += MAX_AMOUNT
        elif mode == "before":
            when = tick - 1
        elif mode == "after":
            when = tick + width + 1
        elif mode == "destination":
            dst = other_dest
        elif mode == "type":
            input_type = (typ + 1) % 65536
        elif mode == "source":
            src = other_source
        size = len(payload) + (1 if mode == "size" else 0)
        frame = (bytes.fromhex(src) + bytes.fromhex(dst)
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
        if mode in ("ok", "short_payload", "max_amount") or (mode == "source" and "source" not in query):
            answer += {"amount": amount, "count": 1,
                       "payload_u64": value if len(payload) >= 8 else 0}[metric]
    rng.shuffle(frames)
    return _body("qubic_transaction_audit", "Qubic transaction audit",
        "Audit synthetic transaction frames from the JSON input. Each hex frame is independent. "
        "Layout: source public key bytes [0,32), destination [32,64), signed int64 amount [64,72), "
        "uint32 tick [72,76), uint16 inputType [76,78), uint16 inputSize [78,80), then inputSize "
        "payload bytes and 64 signature bytes. All integers are little-endian. Keys are raw hex, "
        "not encoded Qubic identities. Retain only frames with at least 80 bytes, exact total length "
        "80+inputSize+64, and amount between 0 and 1000000000000000 (MAX_AMOUNT) inclusive. Then "
        "filter by query destination, input_type, inclusive tick_min..tick_max, and, when the query "
        "has a source, that source as well. Metric amount sums QU; count counts retained frames; "
        "payload_u64 sums the first eight payload bytes as uint64, skipping payloads shorter than eight. "
        "Duplicates count separately; an empty result is zero. Signatures are dummy bytes: this "
        "exercise checks framing and filtering, not signature validity, consensus or full protocol validity.",
        {"query": query, "frames": frames}, answer)


def call_audit(rng):
    """Build nested calls while recording correct audit receipts, then discard receipts."""
    users = [f"U{i}" for i in range(1, 5)]
    transactions, receipts, labels, invalid_callers = [], [], set(), set()
    n_tx = rng.randint(3, 5)
    # Sometimes one trace breaks the lower-index rule, so validity must be checked, not assumed.
    invalid = rng.randrange(n_tx) if rng.random() < 0.4 else None
    # Every instance carries, in a valid trace, at least one nested invocator trap and one nested
    # context restoration with a refund at stake; beyond that the probe mix per frame is random.
    forced = {"trap": False, "restore": False}
    for tx_index in range(n_tx):
        origin, other = users[tx_index % 4], users[(tx_index + 1) % 4]
        valid = tx_index != invalid
        events = []

        def visit(contract, caller, depth):
            reward = rng.randrange(20, 10000)
            events.append({"op": "enter", "contract": contract, "reward": reward})
            labels.add(caller)
            if not valid:
                invalid_callers.add(caller)
            probes = [(origin, rng.randrange(reward)),  # accepted, partial refund
                      (origin, reward + 1),  # rejected: fee above the current reward
                      (origin, reward),  # accepted at the boundary, zero refund
                      (caller if caller != origin else other, 0)]  # rejected: invocator is not originator
            chosen = [p for p in probes if rng.random() < 0.6] or [probes[0]]
            if depth and valid and not forced["trap"]:
                forced["trap"] = True
                if probes[3] not in chosen:
                    chosen.append(probes[3])
            rng.shuffle(chosen)
            for allowed, fee in chosen:
                events.append({"op": "audit", "allowed": allowed, "fee": fee})
                if valid and allowed == origin and reward >= fee:
                    receipts.append((origin, caller, reward, reward - fee))
            children = []
            if depth < 2:
                # Cross-contract calls go to lower contract indices.
                children = [c for c in rng.sample(range(1, contract), 2) if c > 2 or depth == 1]
            if not valid and depth == 0:
                children = children or [rng.randint(3, contract - 1)]
                children[0] = contract + rng.randint(0, 2)  # not lower: the whole trace is invalid
            for child in children:
                visit(child, f"C{contract}", depth + 1)
            # A check after the children return tests restoration of this frame's context.
            if children and (rng.random() < 0.7 or (depth == 1 and valid and not forced["restore"])):
                fee = rng.choice([0, reward, reward + 1, rng.randrange(1, reward)])
                if depth == 1 and valid and not forced["restore"]:
                    forced["restore"], fee = True, rng.randrange(1, reward)
                events.append({"op": "audit", "allowed": origin, "fee": fee})
                if valid and fee <= reward:
                    receipts.append((origin, caller, reward, reward - fee))
            events.append({"op": "exit"})

        visit(rng.randint(10, 29), origin, 0)
        transactions.append({"originator": origin, "events": events})
    # With an invalid trace present, lean on queries its audits would change if they were counted.
    if invalid is not None and rng.random() < 0.35:
        metric = "accepted"
    else:
        metric = rng.choice(["accepted", "refund", "credited"])
    if metric == "refund":
        refunded = sorted({r[1] for r in receipts if r[3] > 0})
        pool = sorted(labels)  # any invocator seen, so a refund can come to zero
        if invalid_callers and rng.random() < 0.3:
            pool = sorted(invalid_callers)
        elif refunded and rng.random() < 0.8:
            pool = refunded
        identity = rng.choice(pool)
    elif invalid is not None and metric == "credited" and rng.random() < 0.3:
        identity = users[invalid % 4]  # the invalid trace's originator
    else:
        identity = rng.choice(users)
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
        "context. Contracts may only call contracts with a lower index: a transaction is invalid, "
        "and none of its audits count, if any nested enter names a contract index that is not lower "
        "than the contract of the frame it is entered from; a user's top-level enter may name any "
        "contract. The intended auditor accepts iff originator equals allowed AND invocationReward "
        "is at least fee. Each accepted audit produces a hypothetical receipt: refund "
        "(invocationReward-fee) to invocator, and credit invocationReward to originator. Rejected "
        "audits produce nothing. These are independent read-only calculations, not actual transfers "
        "or balance mutations. buggy_auditor is incorrect pseudocode to diagnose; follow the intended "
        "rules instead. Query metric accepted counts all accepted audits (ignores identity); refund "
        "sums refunds to identity; credited sums credits to identity. An empty sum is zero. Labels "
        "represent distinct identities. All calls are assumed completed and sufficiently funded; no "
        "system procedures, callbacks or execution fees are modeled.",
        {"transactions": transactions, "buggy_auditor": buggy,
         "query": {"metric": metric, "identity": identity}}, answer)


def asset_ledger(rng):
    """Replay normalized effects in a complete slot ledger, then query final state."""
    fields = ("issuer", "name", "owner", "possessor", "manager")
    users = [f"U{i}" for i in range(1, 5)]
    assets = [("I1", "DOJO"), ("I2", "DOJO"), ("I1", "CUP")]
    balances, initial, journal, touched = {}, [], [], []
    settled = rng.random() < 0.5  # statuses given, or derived from what the source slot holds

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
        applied = i % 5 != 0
        empty = [k for k, v in balances.items() if v == 0]
        if not applied and not settled and empty and rng.random() < 0.5:
            source = rng.choice(empty)  # a drained slot holds nothing, whatever it once held
        else:
            source = rng.choice([k for k, v in balances.items() if v > 0])
        issuer, name, owner, possessor, manager = source
        held = balances[source]
        if i % 3 == 0:
            new_manager = rng.choice([m for m in (1, 2, 3) if m != manager])
            event = {"operation": "management", "new_manager": new_manager}
            destination = (issuer, name, owner, possessor, new_manager)
        else:
            recipient = rng.choice(users)
            event = {"operation": "transfer", "recipient": recipient}
            destination = (issuer, name, recipient, recipient, manager)
        if applied:
            shares = rng.choice([1, held, rng.randint(1, held)])
        elif settled:
            # A given rejection may have any cause: overdraw must not be the tell.
            shares = rng.choice([held + 1, rng.randint(1, max(held, 1))])
            if shares <= held:
                touched.append(source)
        else:
            shares = held + rng.choice([1, rng.randint(1, 500)])  # only an overdraw rejects
        event.update({"from": slot(source), "shares": shares})
        if settled:
            event["status"] = "applied" if applied else "rejected"
        journal.append(event)
        if applied:
            balances[source] -= shares
            balances[destination] = balances.get(destination, 0) + shares
    rng.shuffle(initial)
    role = rng.choice(["owner", "possessor"])
    chosen = rng.choice([k for k, v in balances.items() if v > 0])
    if touched and rng.random() < 0.75:
        chosen = rng.choice(touched)  # a holding a given rejection would have moved: status must be read
    # Usually a holding that exists; sometimes an identity or manager that may hold nothing.
    identity = chosen[fields.index(role)] if rng.random() < 0.75 else rng.choice(users)
    manager_filter = rng.choice([None, None, chosen[4], rng.randint(1, 3)])
    answer = sum(n for k, n in balances.items() if k[:2] == chosen[:2]
                 and k[fields.index(role)] == identity and (manager_filter is None or k[4] == manager_filter))
    return _body("qubic_asset_ledger", "Qubic asset ledger",
        "Reconstruct shares from a synthetic normalized asset journal. Asset identity is the pair "
        "(issuer,name), never name alone. A slot is (issuer,name,owner,possessor,manager). In this "
        "exercise a single manager denotes BOTH ownership and possession management contracts, "
        "which are always equal. Owner, possessor and manager are distinct roles. Sum initial "
        "records with identical slots. Each journal event names its exact from slot and its shares; "
        "the destination slot is derived. A transfer moves ownership and possession together: its "
        "destination has the same issuer, name and manager, and recipient as both owner and "
        "possessor. A management event's destination has the same issuer, name, owner and possessor, "
        "and manager new_manager. A self-transfer nets zero. Process events in journal order, "
        "subtracting shares from the from slot and adding them to the destination slot. If settled "
        "is true, every event carries a status: rejected events have no effect, and applied events "
        "never overdraw their source. If settled is false, no status is given: an event is applied "
        "iff its exact from slot holds at least shares immediately before it, otherwise it is "
        "rejected and has no effect. These are normalized effects, not raw Qubic logs or a "
        "simulation of authorization, callbacks or transfer fees. Query the total shares for "
        "issuer/name where the named role (owner or possessor) equals identity. manager null means "
        "all managers; otherwise require the given manager as well. No issuance or burns occur in "
        "the journal. Unknown or empty matching holdings count as zero.",
        {"settled": settled, "initial": initial, "journal": journal,
         "query": {"issuer": chosen[0], "name": chosen[1], "role": role,
                   "identity": identity, "manager": manager_filter}}, answer)


KINDS = {
    "orange": {"qubic_transaction_audit": transaction_audit},
    "green": {"qubic_asset_ledger": asset_ledger},
    "blue": {"qubic_call_audit": call_audit},
}
