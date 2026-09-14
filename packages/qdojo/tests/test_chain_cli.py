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
