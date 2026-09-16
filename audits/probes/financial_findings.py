"""Read-only audit reproductions: fake balances, temporary state, no real chain.

Run: uv run python audits/probes/financial_findings.py
These assertions demonstrate CURRENT defects, not desired regression behavior.
They should fail once the defects are fixed; replace them with prevention tests.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

from qdojo.chain import FakeChain
from qdojo.chain.base import Unknown
from qdojo.house import House, _write
from qdojo.bot import Bot

HOUSE = "A" * 60
PLAYER = "B" * 60


def empty_round(base):
    chain = FakeChain(identity=HOUSE, balances={HOUSE: 100_000})
    house = House(chain, str(base / "house"), HOUSE)
    riddle = base / "riddle.json"
    riddle.write_text(json.dumps({"round_id": 1, "title": "Audit fixture", "statement": "Return 1",
                                  "input": "1", "answer_format": "integer", "answer": 1}))
    house.publish(str(riddle), 1000, 10, 10, house_seed=1000, match_bps=0)
    chain.advance(5)
    house.confirm_publish(1)
    chain.advance(23)
    house.collect()
    return chain, house


def lost_receipt(base):
    chain = FakeChain(identity=HOUSE, balances={HOUSE: 100_000, PLAYER: 0})
    house = House(chain, str(base / "house"), HOUSE)
    os.makedirs(house.rdir(1))
    ledger = [{"identity": PLAYER, "amount": 1000, "kind": "win", "tx": None, "tick": None, "confirmed": False}]
    _write(house._ledger_path(1), ledger)
    send = chain.send

    def send_then_lose_receipt(*args, **kwargs):
        send(*args, **kwargs)  # network accepted the transaction
        raise Unknown("simulated lost receipt after acceptance")

    chain.send = send_then_lose_receipt
    try:
        house._pay_ledger(1, ledger)
    except Unknown:
        pass
    chain.advance(5)  # first payout lands despite the lost receipt
    chain.send = send
    confirm = chain.confirm

    def advancing_confirm(tx, tick):
        chain.advance(max(0, tick - chain.tick))
        return confirm(tx, tick)

    chain.confirm = advancing_confirm
    resumed = House(chain, house.data_dir, HOUSE)
    resumed._pay_ledger(1, json.loads(Path(house._ledger_path(1)).read_text()))
    assert chain.balance(PLAYER) == 2000, "defect no longer reproduces"
    print("AUD-001: one 1,000-QU ledger item paid twice after receipt loss (fake QU only)")


def partial_closeout(base):
    chain, house = empty_round(base)

    def fail_state_write(_):
        raise OSError("simulated crash before aggregate state write")

    house._save_state = fail_state_write
    try:
        house.settle(1, apply=True)
    except OSError:
        pass
    resumed = House(chain, house.data_dir, HOUSE)
    doc = resumed.settle(1, apply=True)
    assert resumed.meta(1)["status"] == "settled"
    assert doc["carry"] == 1000 and resumed.state()["carry"] == 0, "defect no longer reproduces"
    print("AUD-002: terminal round carries 1,000 QU, aggregate carry remains 0 after restart")


def unconfirmed_closeout(base):
    chain, house = empty_round(base)
    chain.drop_next_send = True  # lose SETTLE, not a payout: this round has none
    doc = house.settle(1, apply=True)
    chain.advance(5)
    assert not chain.confirm(doc["settle_tx"], doc["settle_tick"])
    assert house.meta(1)["status"] == "settled", "defect no longer reproduces"
    assert house.settle(1, apply=True) == doc
    print("AUD-003: round stays settled even though SETTLE is absent from its tick")


def fail_open_strategy(base):
    chain = FakeChain(identity=PLAYER, balances={PLAYER: 5000})
    bot = Bot(chain, str(base / "bot"), [],
              strategy_cmd=[sys.executable, "-c", "raise SystemExit(1)"])
    actions = []
    allowed = bot._strategy_says_enter({"round_id": 1, "entry_fee": 1000}, {}, 1000, actions, "1")
    assert allowed is True, "defect no longer reproduces"
    assert "entering anyway" in actions[0]
    assert chain.pending == []  # decision only; no even-fake transaction sent
    print("AUD-005: crashed strategy authorizes entry instead of declining it")


if __name__ == "__main__":
    for probe in (lost_receipt, partial_closeout, unconfirmed_closeout, fail_open_strategy):
        with tempfile.TemporaryDirectory(prefix="qdojo-audit-") as tmp:
            probe(Path(tmp))
