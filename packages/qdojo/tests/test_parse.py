from qdojo.chain import parse

ID = "A" * 60
TX = "a" * 60


def test_current_tick_needs_tick_and_epoch():
    assert parse.current_tick("Tick: 80121151\nEpoch: 230\nInitial tick: 79300000\n") == 80121151
    assert parse.current_tick("Tick: 80121151\n") is None
    assert parse.current_tick("Epoch: 230\nTick: 0\n") is None
    assert parse.current_tick("") is None


def test_balance_three_part_acceptance():
    good = f"Identity: {ID}\nBalance: 12345\nTick: 80121151\n"
    assert parse.balance(good, ID) == 12345
    assert parse.balance(good, "B" * 60) is None
    assert parse.balance(f"Identity: {ID}\nTick: 80121151\n", ID) is None
    assert parse.balance(f"Identity: {ID}\nBalance: 0\nTick: 0\n", ID) is None
    assert parse.balance(f"Identity: {ID}\nBalance: 0\nTick: 5\n", ID) == 0  # a real zero is a zero


def test_send_receipt():
    out = ("Transaction has been sent!\n~~~~~RECEIPT~~~~~\n"
           f"TxHash: {TX}\nFrom: {ID}\nTo: {'B'*60}\nInput type: 17487\nAmount: 1000\nTick: 80121200\n"
           "Extra data size: 42\n~~~~~END-RECEIPT~~~~~\n")
    assert parse.send_receipt(out) == (TX, 80121200)
    assert parse.send_receipt(out.replace("Transaction has been sent!", "")) is None
    assert parse.send_receipt("Transaction has been sent!\n") is None


def test_check_tx_on_tick_three_states():
    assert parse.check_tx_on_tick(f"Found tx {TX} on tick 5\n", TX, 5) is True
    assert parse.check_tx_on_tick(f"Can NOT find tx {TX} on tick 5\n", TX, 5) is False
    assert parse.check_tx_on_tick("Please wait a bit more. Requested tick 5, current tick 3\n", TX, 5) is None
    assert parse.check_tx_on_tick("Tick 5 is empty, not in current epoch or in the future\n", TX, 5) is None
    assert parse.check_tx_on_tick(f"Found tx {TX} on tick 55\n", TX, 5) is None  # a different tick is not this tick


def test_connection_failed():
    assert parse.connection_failed("")
    assert parse.connection_failed("Failed to connect to 1.2.3.4")
    assert not parse.connection_failed("Tick: 1\nEpoch: 1\n")
