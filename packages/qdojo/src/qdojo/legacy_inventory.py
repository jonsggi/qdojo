"""Read-only inventory of what the riddle-era house still owes (pivot-plan P8).

Reads the house data directory and reports legacy custody: unsettled rounds,
carry, open bonds, the undistributed shareholder pool and pending
distributions. It never writes, signs or sends. The combat contract never
imports any of this; these obligations are closed out under the legacy audit
gates, separately.
"""
from __future__ import annotations

import json
import os


def _read(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def inventory(data_dir: str) -> dict:
    state = _read(os.path.join(data_dir, "state.json"), {}) or {}
    bonds = _read(os.path.join(data_dir, "bonds.json"), []) or []
    open_bonds = [b for b in bonds if not b.get("released") and not b.get("forfeited")]
    by_holder: dict[str, int] = {}
    for b in open_bonds:
        by_holder[b["identity"]] = by_holder.get(b["identity"], 0) + b["amount"]
    rounds_dir = os.path.join(data_dir, "rounds")
    rounds = sorted(d for d in os.listdir(rounds_dir) if d.isdigit()) if os.path.isdir(rounds_dir) else []
    unsettled = []
    for d in rounds:
        if not os.path.exists(os.path.join(rounds_dir, d, "settlement.json")):
            meta = _read(os.path.join(rounds_dir, d, "meta.json"), {}) or {}
            unsettled.append({"round_id": int(d), "status": meta.get("status"), "entry_fee": meta.get("entry_fee")})
    pending = state.get("pending_distribution")
    return {
        "schema": "qdojo.legacy.inventory.v1",
        "data_dir": os.path.abspath(data_dir),
        "rounds": len(rounds),
        "unsettled_rounds": unsettled,
        "carry": state.get("carry", 0),
        "open_bonds": {"count": len(open_bonds), "total": sum(b["amount"] for b in open_bonds),
                       "holders": len(by_holder),
                       "oldest_round": min((b["round_id"] for b in open_bonds), default=None)},
        "shareholder_pool_undistributed": state.get("shareholder_pool", 0),
        "shareholder_paid": state.get("shareholder_paid", 0),
        "dev_paid": state.get("dev_paid", 0),
        "distribution_pending": pending,
        "note": "Legacy liabilities only. Not combat funds, not available balance; closing them needs the "
                "legacy audit gates and explicit authorisation.",
    }


def text(inv: dict) -> str:
    b = inv["open_bonds"]
    lines = [
        f"legacy house data: {inv['data_dir']}",
        f"rounds on disk: {inv['rounds']}; unsettled: {len(inv['unsettled_rounds'])}"
        + (f" ({', '.join(str(u['round_id']) for u in inv['unsettled_rounds'])})" if inv["unsettled_rounds"] else ""),
        f"carry: {inv['carry']} QU",
        f"open bonds: {b['count']} bonds, {b['total']} QU, {b['holders']} holders, oldest from round {b['oldest_round']}",
        f"shareholder pool not yet distributed: {inv['shareholder_pool_undistributed']} QU "
        f"(paid so far {inv['shareholder_paid']} QU)",
        f"distribution pending confirmation: {'yes' if inv['distribution_pending'] else 'no'}",
        inv["note"],
    ]
    return "\n".join(lines)
