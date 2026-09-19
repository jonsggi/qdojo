import os
import stat
import sys
import textwrap

import pytest

from qdojo.chain.cli import QubicCli, check_seed_conf, SeedConfError
from qdojo.chain.base import Unknown, ChainError

ID = "A" * 60
TX = "b" * 60
SEED = "x" * 55


def conf(tmp_path, body=f"seed={SEED}\n", mode=0o600):
    p = tmp_path / "t.conf"
    p.write_text(body)
    os.chmod(p, mode)
    return str(p)


def fake_cli(tmp_path, script: str) -> str:
    """A stand-in qubic-cli: a Python script that prints per argv."""
    p = tmp_path / "qubic-cli"
    p.write_text("#!" + sys.executable + "\nimport sys\n" + textwrap.dedent(script))
    os.chmod(p, 0o755)
    return str(p)


def test_seed_conf_checks(tmp_path):
    check_seed_conf(conf(tmp_path))
    with pytest.raises(SeedConfError):
        check_seed_conf(conf(tmp_path, mode=0o644))
    with pytest.raises(SeedConfError):
        check_seed_conf(conf(tmp_path, body="nodeip=1.2.3.4\n"))
    with pytest.raises(SeedConfError):
        check_seed_conf(conf(tmp_path, body=f"seed={SEED}\nseed={SEED}\n"))
    with pytest.raises(SeedConfError):
        check_seed_conf(conf(tmp_path, body="seed=" + "X" * 55 + "\n"))
    with pytest.raises(SeedConfError):
        check_seed_conf(str(tmp_path / "missing.conf"))


def test_reads_parse_markers_and_exit_code_is_ignored(tmp_path):
    cli = fake_cli(tmp_path, f"""
        a = sys.argv
        if "-getcurrenttick" in a: print("Tick: 500\\nEpoch: 230"); sys.exit(0)
        if "-getbalance" in a: print("Identity: {ID}\\nBalance: 77\\nTick: 500"); sys.exit(1)
        if "-checktxontick" in a: print("Found tx {TX} on tick 500"); sys.exit(0)
    """)
    c = QubicCli(cli, "1.2.3.4")
    assert c.current_tick() == 500
    assert c.balance(ID) == 77
    assert c.confirm(TX, 500) is True


def test_missing_marker_is_unknown_not_zero(tmp_path):
    cli = fake_cli(tmp_path, 'print("Tick: 5\\nEpoch: 1") if "-getcurrenttick" in sys.argv else print("garbage")')
    c = QubicCli(cli, "1.2.3.4")
    with pytest.raises(Unknown):
        c.balance(ID)
    with pytest.raises(Unknown):
        c.confirm(TX, 5)


def test_connection_failure_is_unknown(tmp_path):
    cli = fake_cli(tmp_path, 'print("Failed to connect to 1.2.3.4")')
    with pytest.raises(Unknown):
        QubicCli(cli, "1.2.3.4").current_tick()


def test_timeout_is_unknown(tmp_path):
    cli = fake_cli(tmp_path, "import time; time.sleep(5)")
    with pytest.raises(Unknown):
        QubicCli(cli, "1.2.3.4", timeout=1).current_tick()


def test_send_puts_seed_in_conf_never_argv_and_needs_receipt(tmp_path):
    log = tmp_path / "argv.log"
    cli = fake_cli(tmp_path, f"""
        open({str(log)!r}, "w").write(" ".join(sys.argv))
        print("Transaction has been sent!\\nTxHash: {TX}\\nTick: 520")
    """)
    c = QubicCli(cli, "1.2.3.4", identity=ID, conf=conf(tmp_path), schedule_offset=20)
    r = c.send("B" * 60, 1000, payload=b"DOJO\x00\x01\x03abc", input_type=0x444F)
    assert (r.tx_id, r.scheduled_tick) == (TX, 520)
    argv = log.read_text()
    assert SEED not in argv and "-conf" in argv and "-scheduletick 20" in argv and "-nodeip 1.2.3.4" in argv
    assert "-sendcustomtransaction" in argv and "17487" in argv and "444f4a4f00010361626" in argv


def test_send_without_receipt_is_an_error(tmp_path):
    cli = fake_cli(tmp_path, 'print("something else")')
    c = QubicCli(cli, "1.2.3.4", identity=ID, conf=conf(tmp_path))
    with pytest.raises(ChainError):
        c.send("B" * 60, 1)


def test_read_only_chain_cannot_send(tmp_path):
    cli = fake_cli(tmp_path, 'print("")')
    with pytest.raises(ChainError):
        QubicCli(cli, "1.2.3.4").send("B" * 60, 1)


def test_reads_fall_back_to_another_node_but_signing_does_not(tmp_path):
    cli = fake_cli(tmp_path, f"""
        a = sys.argv
        ip = a[a.index("-nodeip") + 1]
        if ip == "1.1.1.1":
            print("Failed to connect to 1.1.1.1"); sys.exit(0)
        if "-getcurrenttick" in a: print("Tick: 500\\nEpoch: 231")
        if "-sendtoaddress" in a: print("Transaction has been sent!\\nTxHash: {TX}\\nTick: 520")
    """)
    c = QubicCli(cli, "1.1.1.1", identity=ID, conf=conf(tmp_path), fallback_nodes=("2.2.2.2",))
    assert c.current_tick() == 500                       # the read fell through to the healthy node
    with pytest.raises(Unknown):
        c.send("B" * 60, 1)                              # the signed call stays on the dead primary
    c2 = QubicCli(cli, "1.1.1.1", fallback_nodes=("3.3.3.3", "4.4.4.4"))
    assert c2.current_tick() == 500
    c3 = QubicCli(cli, "1.1.1.1", fallback_nodes=())
    with pytest.raises(Unknown):
        c3.current_tick()


def test_an_empty_past_tick_in_this_epoch_means_the_tx_never_landed(tmp_path):
    """A transaction is only valid for the tick signed into it, so once that
    tick has passed with no data, it is dead — not 'undecided for ever'."""
    cli = fake_cli(tmp_path, f"""
        a = sys.argv
        if "-checktxontick" in a: print("Tick " + a[a.index("-checktxontick")+1] + " is empty, not in current epoch or in the future")
        if "-getcurrenttick" in a: print("Tick: 80386795\\nEpoch: 231\\nInitial tick: 80371514")
    """)
    c = QubicCli(cli, "1.2.3.4")
    assert c.confirm(TX, 80384089) is False        # well past, inside this epoch: dead
    with pytest.raises(Unknown):
        c.confirm(TX, 80386790)                    # only 5 ticks back: still too fresh to judge
    with pytest.raises(Unknown):
        c.confirm(TX, 80300000)                    # before this epoch: the data is simply gone


def test_a_node_that_answers_badly_moves_the_read_to_the_next_node(tmp_path):
    cli = fake_cli(tmp_path, f"""
        a = sys.argv
        ip = a[a.index("-nodeip") + 1]
        if ip == "1.1.1.1":
            print("garbage that parses to nothing"); sys.exit(0)   # reachable, useless
        if "-getbalance" in a: print("Identity: {ID}\\nBalance: 77\\nTick: 500")
        if "-getcurrenttick" in a: print("Tick: 500\\nEpoch: 231")
    """)
    c = QubicCli(cli, "1.1.1.1", fallback_nodes=("2.2.2.2",))
    assert c.balance(ID) == 77 and c.current_tick() == 500
    with pytest.raises(Unknown):
        QubicCli(cli, "1.1.1.1").balance(ID)        # no fallback: still Unknown


def test_share_reads_and_a_contract_send_through_the_binary(tmp_path):
    """`--chain cli` answers the same four reads as the native chain, out of
    qubic-cli's text, and a contract call goes out as -sendcustomtransaction
    with the very bytes the native builder makes."""
    from qdojo.qubic import contracts
    from qdojo.shares import Shares
    log = tmp_path / "argv.log"
    cli = fake_cli(tmp_path, f"""
        a = sys.argv
        if "-qxgetfee" in a: print("Asset issuance fee: 1000000000\\nTransfer fee: 100\\nTrade fee: 3000000")
        if "-qutilgetfee" in a: print("DistributeQuToShareholders fee (var 3): 5 per shareholder")
        if "-getasset" in a: print("======== OWNERSHIP ========\\nAsset issuer: {ID}\\nAsset name: KEN\\nNumber Of Shares: 7\\nTick: 5")
        if "-queryassets" in a: print("Share ownership\\n\\towner = {ID}\\n\\tnumber of shares = 7\\n\\tmanaging contract = 1")
        if "-getbalance" in a: print("Identity: {ID}\\nBalance: 2000000000\\nTick: 500")
        if "-sendcustomtransaction" in a:
            open({str(log)!r}, "w").write(" ".join(a))
            print("Transaction has been sent!\\nTxHash: {TX}\\nTick: 520")
    """)
    c = QubicCli(cli, "1.2.3.4", identity=ID, conf=conf(tmp_path), schedule_offset=20)
    assert c.qx_fees()["issue"] == 1_000_000_000 and c.qutil_fees() == {"distribute_per_shareholder": 5}
    assert c.owned_assets(ID) == [{"issuer": ID, "name": "KEN", "shares": 7}]
    assert c.asset_holders(ID, "KEN") == [{"owner": ID, "shares": 7, "managing_contract": 1}]
    r = Shares(c).issue("RYUBOT", 1000)
    assert r.tx_id == TX
    argv = log.read_text().split()
    i = argv.index("-sendcustomtransaction")
    assert argv[i + 1:i + 6] == [contracts.QX_IDENTITY, "1", "1000000000", "32",
                                 contracts.issue_asset_input("RYUBOT", 1000).hex()]
    assert SEED not in log.read_text()


def test_share_reads_without_their_marker_are_unknown(tmp_path):
    cli = fake_cli(tmp_path, 'print("Failed to connect 1.2.3.4")')
    c = QubicCli(cli, "1.2.3.4")
    for call in (c.qx_fees, c.qutil_fees, lambda: c.owned_assets(ID), lambda: c.asset_holders(ID, "KEN")):
        with pytest.raises(Unknown):
            call()
