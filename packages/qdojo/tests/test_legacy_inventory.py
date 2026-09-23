import json
import os

from qdojo.cli import main


def test_inventory_reads_without_writing(tmp_path, capsys):
    d = tmp_path / "house"
    (d / "rounds" / "000001").mkdir(parents=True)
    (d / "rounds" / "000002").mkdir()
    (d / "rounds" / "000001" / "settlement.json").write_text("{}")
    (d / "rounds" / "000002" / "meta.json").write_text(json.dumps({"status": "open", "entry_fee": 1000}))
    (d / "state.json").write_text(json.dumps({"carry": 7, "shareholder_pool": 300, "pending_distribution": None}))
    (d / "bonds.json").write_text(json.dumps([
        {"identity": "A" * 60, "amount": 500, "round_id": 1, "released": None, "forfeited": None},
        {"identity": "A" * 60, "amount": 200, "round_id": 2, "released": None, "forfeited": None},
        {"identity": "B" * 60, "amount": 900, "round_id": 1, "released": 2, "forfeited": None},
    ]))
    before = {p: os.stat(p).st_mtime_ns for p in d.rglob("*")}
    main(["house", "--data", str(d), "legacy-inventory", "--json"])
    inv = json.loads(capsys.readouterr().out)
    assert inv["unsettled_rounds"] == [{"round_id": 2, "status": "open", "entry_fee": 1000}]
    assert inv["carry"] == 7 and inv["shareholder_pool_undistributed"] == 300
    assert inv["open_bonds"] == {"count": 2, "total": 700, "holders": 1, "oldest_round": 1}
    assert {p: os.stat(p).st_mtime_ns for p in d.rglob("*")} == before
