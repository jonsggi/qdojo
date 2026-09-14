from qdojo.chain.rpc import parse_transactions

H = "H" * 60


def test_parse_walks_nested_shapes_and_decodes_hex():
    doc = {"transactions": [{"identity": H, "tickNumber": 5, "transactions": [
        {"transaction": {"sourceId": "A" * 60, "destId": H, "amount": "1000", "tickNumber": 5, "inputType": 17487,
                         "inputSize": 6, "inputHex": "444f4a4f0001", "txId": "t" * 60}, "moneyFlew": True}]}]}
    [o] = parse_transactions(doc)
    assert (o.source, o.dest, o.amount, o.tick, o.input_type, o.payload, o.tx_id) == \
        ("A" * 60, H, 1000, 5, 17487, b"DOJO\x00\x01", "t" * 60)


def test_parse_ignores_unrelated_objects():
    assert parse_transactions({"code": 3, "message": "nope"}) == []
    assert parse_transactions([{"sourceId": "x"}]) == []
