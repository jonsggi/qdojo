"""Durable contract state by input journal (event sourcing).

The reference contract is deterministic, so its state is exactly the replay
of its confirmed inputs: calls (invocator, 512-byte frame, attached QU),
tick boundaries, asset-owner changes and recipients whose transfers fail.
A journal is JSON lines, appended and fsynced per record; a torn final line
is dropped on load. `replay` rebuilds the contract and checks that the
recorded event digest matches, so a journal from another ruleset, manifest
or build cannot be silently loaded.

Riddle-era state (rounds.json, observed.jsonl) is refused outright.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from .contract import CombatContract, Manifest

SCHEMA = "qdojo.combat.journal.v1"
LEGACY_MARKERS = ("rounds.json", "observed.jsonl", "secret.json")


class StoreError(RuntimeError):
    pass


def refuse_legacy(directory: Path):
    for name in LEGACY_MARKERS:
        if (Path(directory) / name).exists():
            raise StoreError(f"{directory} holds riddle-era state ({name}); combat never loads it")


def header(manifest: Manifest) -> dict:
    """Every manifest value, so an independent implementation can replay the journal."""
    m = manifest
    return {"schema": SCHEMA, "network_id": m.network_id.hex(), "contract_id": m.contract_id.hex(),
            "ruleset_digest": m.ruleset.digest.hex(), "admin": m.admin.hex(),
            "timing": {str(k): list(v) for k, v in m.timing.items()},
            "fees": {str(k): {"rake_bps": f.rake_bps, "house_bps": f.house_bps, "dev_bps": f.dev_bps,
                              "share_bps": f.share_bps, "house": f.house.hex(), "dev": f.dev.hex(),
                              "share": f.share.hex()} for k, f in m.fees.items()},
            "tiers": {str(k): v for k, v in m.tiers.items()},
            **{k: getattr(m, k) for k in (
                "genesis_tick", "genesis_epoch", "ticks_per_epoch", "season_start_epoch", "season_epochs",
                "season_closeout_ticks", "max_fighters", "max_accounts", "max_offers", "max_fights", "max_cups",
                "max_cup_entrants", "event_ring", "match_interval", "cooldown_ticks", "faults_per_epoch",
                "pair_starts_per_epoch", "pair_rematch_ticks")},
            "offer_lifetime": list(m.offer_lifetime)}


def write(path: Path, manifest: Manifest, journal: list, final_event_digest: bytes | None = None):
    """Write a whole journal atomically (tmp + rename)."""
    path = Path(path)
    refuse_legacy(path.parent)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(json.dumps(header(manifest)) + "\n")
        for rec in journal:
            f.write(json.dumps(rec, separators=(",", ":")) + "\n")
        if final_event_digest is not None:
            f.write(json.dumps({"k": "digest", "event_digest": final_event_digest.hex()}) + "\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def load(path: Path) -> tuple[dict, list]:
    lines = Path(path).read_text(encoding="utf-8").split("\n")
    head = json.loads(lines[0])
    if head.get("schema") != SCHEMA:
        raise StoreError("not a combat journal")
    records = []
    for i, line in enumerate(lines[1:], 1):
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            if i == len(lines) - 1 or all(not x for x in lines[i + 1:]):
                break          # torn tail from a crash mid-append
            raise StoreError(f"corrupt journal line {i}") from None
    return head, records


def replay(manifest: Manifest, head: dict, records: list) -> CombatContract:
    """Rebuild the contract from its inputs and verify the recorded digest."""
    if head != header(manifest):
        raise StoreError("journal belongs to a different network, contract, ruleset or admin")
    owners: dict[bytes, bytes | None] = {}
    failing: set[bytes] = set()

    def transfer(to, amount):
        return to not in failing

    contract = None
    for rec in records:
        k = rec["k"]
        if k == "start":
            contract = CombatContract(manifest, owners.get, transfer, rec["t"])
        elif k == "owner":
            owners[bytes.fromhex(rec["id"])] = bytes.fromhex(rec["owner"]) if rec["owner"] else None
        elif k == "fail":
            (failing.add if rec["on"] else failing.discard)(bytes.fromhex(rec["who"]))
        elif k == "call":
            contract.call(bytes.fromhex(rec["who"]), bytes.fromhex(rec["frame"]), rec["amount"], rec["t"])
        elif k == "end":
            contract.end_tick(rec["t"])
            contract.begin_tick(rec["t"] + 1)
        elif k == "begin":
            contract.begin_tick(rec["t"])
        elif k == "mint":
            pass                # external balances are not contract state
        elif k == "digest":
            if contract.event_digest.hex() != rec["event_digest"]:
                raise StoreError("replayed event digest differs from the recorded one")
        else:
            raise StoreError(f"unknown journal record {k!r}")
    if contract is None:
        raise StoreError("empty journal")
    return contract
