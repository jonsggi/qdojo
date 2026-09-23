import json

import pytest

from qdojo.cli import main


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("QDOJO_COMBAT_HOME", str(tmp_path))
    return tmp_path


def run(capsys, *argv):
    main(list(argv))
    return capsys.readouterr().out


def test_devnet_queue_match_play_withdraw(home, capsys):
    run(capsys, "combat", "fighter", "register", "musashi")
    run(capsys, "combat", "bot", "run", "--fighter", "musashi", "--npc", "scout-v1", "--spar", "kicker-v1",
        "--ticks", "250", "--quiet")
    doc = json.loads(run(capsys, "combat", "fighter", "show", "musashi", "--json"))
    assert sum(doc["record"].values()) >= 1
    out = json.loads(run(capsys, "combat", "withdraw", "--as", "musashi", "--json"))
    assert out["code"] == "OK"
    status = json.loads(run(capsys, "combat", "devnet", "status", "--json"))
    assert status["fighters"] == 2


def test_manual_queue_and_cancel(home, capsys):
    run(capsys, "combat", "fighter", "register", "a")
    r = json.loads(run(capsys, "combat", "queue", "enter", "--fighter", "a", "--json"))
    offer = r["data"]["offer_id"]
    listing = json.loads(run(capsys, "combat", "queue", "list", "--json"))
    assert [o["offer_id"] for o in listing["offers"]] == [str(offer)]
    assert json.loads(run(capsys, "combat", "queue", "cancel", str(offer), "--json"))["code"] == "OK"
    # Repeated cancellation is idempotent (matchmaking.md §4).
    assert json.loads(run(capsys, "combat", "queue", "cancel", str(offer), "--json"))["code"] == "DUPLICATE"


def test_duel_and_cup_commands(home, capsys):
    for x in ("a", "b", "c", "d"):
        run(capsys, "combat", "fighter", "register", x)
    r = json.loads(run(capsys, "combat", "duel", "offer", "--fighter", "a", "--opponent", "b", "--stake", "3000", "--json"))
    acc = json.loads(run(capsys, "combat", "duel", "accept", str(r["data"]["offer_id"]), "--fighter", "b", "--json"))
    assert acc["code"] == "OK" and "contest_id" in acc["data"]
    json.loads(run(capsys, "combat", "cup", "create", "--sponsorship", "500", "--json"))
    cups = json.loads(run(capsys, "combat", "cup", "list", "--json"))
    assert cups[0]["status"] == "REGISTRATION"
    for x in ("c", "d"):
        assert json.loads(run(capsys, "combat", "cup", "register", "1", "--fighter", x, "--json"))["code"] == "OK"


def test_doctor_is_non_spending_and_honest(home, capsys):
    out = run(capsys, "combat", "doctor")
    assert "WARN  deployment manifest" in out and "paid admission stays disabled" in out
    assert not (home / "devnet").exists()


def test_rejections_exit_nonzero(home, capsys):
    run(capsys, "combat", "fighter", "register", "a")
    with pytest.raises(SystemExit):
        main(["combat", "queue", "enter", "--fighter", "a", "--max-gap", "999"])
    assert "BAD_BODY" in capsys.readouterr().out
