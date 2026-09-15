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


def test_indexed_tick_reads_status(monkeypatch):
    from qdojo.chain import rpc
    from qdojo.chain.base import Unknown
    import pytest
    monkeypatch.setattr(rpc, "_get", lambda path, timeout=25: {"lastProcessedTick": {"tickNumber": 80276492, "epoch": 230}})
    assert rpc.Indexer().indexed_tick() == 80276492
    monkeypatch.setattr(rpc, "_get", lambda path, timeout=25: {"lastProcessedTick": {}})
    with pytest.raises(Unknown):
        rpc.Indexer().indexed_tick()
