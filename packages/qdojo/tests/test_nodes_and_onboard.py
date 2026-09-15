import os
import sys
import textwrap

import pytest

from qdojo import nodes, onboard


def test_parse_node_list_keeps_only_ips():
    out = "Fetching node ip list from 1.2.3.4\n145.239.149.54\n32.217.18.210\nnot an ip\n\n"
    assert nodes.parse_node_list(out) == ["145.239.149.54", "32.217.18.210"]


def test_discover_expands_peers_and_keeps_agreeing_nodes():
    world = {"1.1.1.1": (1000, ["2.2.2.2", "3.3.3.3", "4.4.4.4"]), "2.2.2.2": (1002, []),
             "3.3.3.3": (900, []), "4.4.4.4": (None, []), "5.5.5.5": (None, [])}
    found = nodes.discover(lambda ip: world.get(ip, (None, [])), seeds=["1.1.1.1", "5.5.5.5"])
    assert [n["ip"] for n in found] == ["2.2.2.2", "1.1.1.1"]      # best first; 3.3.3.3 is 102 ticks stale; 4/5 dead
    assert found[0]["lag"] == 0 and found[1]["lag"] == 2


def test_discover_returns_empty_when_nothing_answers():
    assert nodes.discover(lambda ip: (None, []), seeds=["1.1.1.1"]) == []


def test_best_node_caches_and_refreshes(tmp_path):
    calls = []
    def probe(ip):
        calls.append(ip); return (1000, [])
    assert nodes.best_node(str(tmp_path), probe, seeds=None) if False else nodes.best_node(str(tmp_path), probe) in nodes.BOOTSTRAP
    n = len(calls)
    nodes.best_node(str(tmp_path), probe)
    assert len(calls) == n                                            # served from cache
    nodes.best_node(str(tmp_path), probe, force=True)
    assert len(calls) > n


def test_new_seed_shape():
    s = onboard.new_seed()
    assert len(s) == 55 and s.islower() and s.isalpha()
    assert onboard.new_seed() != s


def test_create_conf_is_0600_and_never_overwrites(tmp_path):
    p = str(tmp_path / "d" / "bot.conf")
    onboard.create_conf(p)
    assert oct(os.stat(p).st_mode & 0o777) == "0o600"
    body = open(p).read()
    assert body.startswith("seed=") and len(body.strip()) == 60
    with pytest.raises(onboard.OnboardError):
        onboard.create_conf(p)
    with pytest.raises(onboard.OnboardError):
        onboard.create_conf(str(tmp_path / "bad.conf"), seed="tooshort")


def fake_cli(tmp_path):
    p = tmp_path / "qubic-cli"
    p.write_text("#!" + sys.executable + "\n" + textwrap.dedent("""
        import sys
        conf = sys.argv[sys.argv.index('-conf') + 1]
        seed = [l for l in open(conf) if l.startswith('seed=')][0][5:].strip()
        print('Seed: ' + seed)           # the real tool prints secrets too; we must not echo them
        print('Private key: ' + 'x' * 60)
        print('Identity: ' + (seed[:1].upper() * 60))
    """))
    os.chmod(p, 0o755)
    return str(p)


def test_derive_identity_reads_only_the_identity_line(tmp_path):
    cli = fake_cli(tmp_path)
    conf = onboard.create_conf(str(tmp_path / "bot.conf"), seed="q" * 55)
    assert onboard.derive_identity(cli, conf) == "Q" * 60


def test_find_cli_prefers_explicit_then_env(tmp_path, monkeypatch):
    cli = fake_cli(tmp_path)
    assert onboard.find_cli(cli) == cli
    monkeypatch.setenv("QUBIC_CLI", cli)
    assert onboard.find_cli(None) == cli
    monkeypatch.delenv("QUBIC_CLI")
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    monkeypatch.setattr(os.path, "expanduser", lambda p: str(tmp_path / "nohome"))
    with pytest.raises(onboard.OnboardError):
        onboard.find_cli(None)


def test_bot_init_end_to_end(tmp_path, monkeypatch, capsys):
    from qdojo.cli import main
    cli = fake_cli(tmp_path)
    state = str(tmp_path / "state")
    monkeypatch.setattr(nodes, "cli_probe", lambda binary, timeout=6.0: (lambda ip: (1000, [])))
    main(["--cli", cli, "bot", "--state", state, "init", "--name", "RYUBOT"])
    out = capsys.readouterr().out
    assert "identity :" in out and "NEW seed created" in out
    prof = onboard.load_profile(state)
    assert prof["name"] == "RYUBOT" and len(prof["identity"]) == 60 and os.path.exists(prof["conf"])
    assert nodes.load(state)[0]["ip"] in nodes.BOOTSTRAP
    main(["--cli", cli, "bot", "--state", state, "init"])                 # second run keeps the seed
    assert "existing seed" in capsys.readouterr().out
