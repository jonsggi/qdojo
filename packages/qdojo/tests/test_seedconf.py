"""Seed confs on tmpfs outlive the run that made them (issue #19).

Two defences, tested apart because they must stay apart: a startup check
that REPORTS what is in the runtime directory and deletes nothing, and an
opt-in shred-on-exit that touches only the one conf a run was told is
throwaway. The check exists because "there are none" was once concluded from
`ls | head`, which showed five files of twenty-six.
"""
import os
import signal
import time

import pytest

from qdojo import onboard, seedconf
from qdojo.chain import FakeChain
from conftest import HOUSE

SEED = "q" * 55


def conf(path, seed=SEED, mtime=None):
    """A 0600 conf the way the operator's scripts write one."""
    path = str(path)
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(f"seed={seed}\n")
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


# ----------------------------------------------------------------- the check

def test_runtime_dir_is_xdg_then_run_user(monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/x")
    assert seedconf.runtime_dir() == "/x/qdojo"
    monkeypatch.delenv("XDG_RUNTIME_DIR")
    assert seedconf.runtime_dir() == f"/run/user/{os.getuid()}/qdojo"


def test_missing_directory_is_silent(tmp_path, capsys):
    assert seedconf.warn_leftovers(str(tmp_path / "nope")) == []
    (tmp_path / "afile").write_text("")
    assert seedconf.warn_leftovers(str(tmp_path / "afile")) == []       # not a directory: also silent
    assert capsys.readouterr().err == ""


def test_empty_directory_is_silent(tmp_path, capsys):
    (tmp_path / "other.txt").write_text("")
    (tmp_path / "web").mkdir()
    assert seedconf.warn_leftovers(str(tmp_path)) == []
    assert capsys.readouterr().err == ""


def test_every_conf_is_listed_oldest_first_and_none_is_deleted(tmp_path, capsys):
    """Twenty-six, like the session that started this: a pipe through head
    would show five. The whole directory must come out, every name, oldest
    first, with an age -- and every file must still be there afterwards."""
    now = time.time()
    names = [f"qdojo_{i:02d}.conf" for i in range(26)]
    for i, n in enumerate(names):
        conf(tmp_path / n, mtime=now - (26 - i) * 3600)     # 26h .. 1h old
    (tmp_path / "cohort2.txt").write_text("not a conf")
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "nested.conf").write_text("")      # a subdirectory is not walked
    found = seedconf.warn_leftovers(str(tmp_path))
    assert [x["name"] for x in found] == names               # oldest first
    err = capsys.readouterr().err
    assert err.startswith(f"warning: 26 seed confs in {tmp_path} from earlier runs (nothing is deleted")
    for n in names:
        assert n in err and os.path.exists(tmp_path / n)
    assert "1d 2h" in err and "1h 0m" in err
    assert "cohort2.txt" not in err and "nested.conf" not in err
    assert SEED not in err                                    # names and ages, never contents


def test_the_conf_in_use_is_not_a_leftover(tmp_path, capsys):
    mine = conf(tmp_path / "qdojo_mine.conf")
    other = conf(tmp_path / "qdojo_other.conf")
    found = seedconf.warn_leftovers(str(tmp_path), exclude=mine)
    assert [x["path"] for x in found] == [other]
    assert "1 seed conf in" in capsys.readouterr().err
    assert seedconf.warn_leftovers(str(tmp_path), exclude=other) and os.path.exists(mine) and os.path.exists(other)
    os.unlink(other)
    assert seedconf.warn_leftovers(str(tmp_path), exclude=mine) == []
    assert capsys.readouterr().err.count("warning:") == 1     # the second call was silent


def test_format_age():
    assert seedconf.format_age(10) == "10s"
    assert seedconf.format_age(42 * 60) == "42m"
    assert seedconf.format_age(3 * 3600 + 12 * 60) == "3h 12m"
    assert seedconf.format_age(4 * 86400 + 20 * 3600 + 59) == "4d 20h"


# ----------------------------------------------------------------- the shred

def test_shred_overwrites_then_unlinks(tmp_path):
    p = conf(tmp_path / "t.conf")
    size = os.stat(p).st_size
    fd = os.open(p, os.O_RDONLY)              # an open descriptor keeps the pages, so the overwrite can be seen
    try:
        assert seedconf.shred(p) is True
        assert not os.path.exists(p)
        assert os.pread(fd, size, 0) == b"\0" * size
    finally:
        os.close(fd)
    assert seedconf.shred(p) is False         # gone already: not an error


def test_shred_unlinks_a_symlink_without_following_it(tmp_path):
    target = conf(tmp_path / "keep.conf")
    link = str(tmp_path / "link.conf")
    os.symlink(target, link)
    assert seedconf.shred(link) is True
    assert not os.path.lexists(link)
    assert open(target).read() == f"seed={SEED}\n"


def test_shred_unlinks_even_when_the_overwrite_fails(tmp_path):
    p = conf(tmp_path / "ro.conf")
    os.chmod(p, 0o400)
    with pytest.raises(PermissionError):
        seedconf.shred(p)
    assert not os.path.exists(p)


# -------------------------------------------------------------- the exit paths

def test_ephemeral_shreds_on_a_normal_return(tmp_path):
    p = conf(tmp_path / "t.conf")
    with seedconf.ephemeral(p) as got:
        assert got == p and os.path.exists(p)
    assert not os.path.exists(p)


def test_ephemeral_shreds_on_an_exception(tmp_path):
    p = conf(tmp_path / "t.conf")
    with pytest.raises(ValueError):
        with seedconf.ephemeral(p):
            raise ValueError("mid-round")
    assert not os.path.exists(p)


def test_ephemeral_shreds_on_ctrl_c(tmp_path):
    p = conf(tmp_path / "t.conf")
    with pytest.raises(KeyboardInterrupt):
        with seedconf.ephemeral(p):
            raise KeyboardInterrupt
    assert not os.path.exists(p)


def test_ephemeral_shreds_on_sigterm_and_restores_the_handler(tmp_path):
    p = conf(tmp_path / "t.conf")
    before = signal.getsignal(signal.SIGTERM)
    with pytest.raises(SystemExit) as e:
        with seedconf.ephemeral(p):
            assert signal.getsignal(signal.SIGTERM) is not before
            os.kill(os.getpid(), signal.SIGTERM)
            time.sleep(5)                     # the handler raises out of the sleep
    assert e.value.code == 128 + signal.SIGTERM
    assert not os.path.exists(p)
    assert signal.getsignal(signal.SIGTERM) is before


def test_ephemeral_none_touches_nothing(tmp_path):
    p = conf(tmp_path / "t.conf")
    with seedconf.ephemeral(None) as got:
        assert got is None
    assert os.path.exists(p)


# ------------------------------------------------------------ through the CLI

def fake_cli(tmp_path):
    """_bot_defaults still insists a qubic-cli can be found; any executable will do."""
    p = tmp_path / "qubic-cli"
    p.write_text("#!/bin/sh\nexit 0\n")
    os.chmod(p, 0o755)
    return str(p)


@pytest.fixture
def offline(monkeypatch, tmp_path):
    """A `bot run --once` and a `house spar --rounds 0` that never touch a
    node: the chain is fake and the board is a dict."""
    from qdojo import cli
    monkeypatch.setattr(cli, "_chain", lambda a, signing: FakeChain(identity=a.identity, balances={a.identity: 5000}))
    monkeypatch.setattr(cli, "fetch_board", lambda src: {"house": HOUSE, "rounds": []})
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "rt"))    # so the real runtime dir is never read
    monkeypatch.delenv("QDOJO_CONF", raising=False)
    return cli


def bot_run(cli, tmp_path, state, *extra, top=()):
    """`top` is for the parser's global options (--conf), which argparse only
    takes before the subcommand; `extra` goes after `run`."""
    cli.main(["--node", "1.2.3.4", "--cli", fake_cli(tmp_path), *top, "bot", "--state", state,
              "run", "--board", "x", "--solver", "true", "--once", *extra])


def test_bot_run_shreds_only_the_conf_passed_as_ephemeral(offline, tmp_path):
    state = str(tmp_path / "state")
    durable = onboard.create_conf(os.path.join(state, "bot.conf"))
    throwaway = conf(tmp_path / "rt" / "qdojo" / "qdojo_t1.conf")
    bot_run(offline, tmp_path, state, "--ephemeral-conf", throwaway)
    assert not os.path.exists(throwaway)
    assert os.path.exists(durable)
    bot_run(offline, tmp_path, state)                       # the profile's conf: no flag, no shred
    assert os.path.exists(durable)
    bot_run(offline, tmp_path, state, top=["--conf", durable])   # --conf alone is never a shred either
    assert os.path.exists(durable)


def test_bot_run_shreds_the_ephemeral_conf_on_a_startup_failure(offline, tmp_path):
    """Every exit path means every one: a run that never got going still
    takes its throwaway conf with it."""
    state = str(tmp_path / "state")
    throwaway = conf(tmp_path / "rt" / "qdojo" / "qdojo_t1.conf")
    with pytest.raises(SystemExit):
        offline.main(["--node", "1.2.3.4", "--cli", fake_cli(tmp_path), "bot", "--state", state,
                      "run", "--board", "x", "--once", "--ephemeral-conf", throwaway])   # no solver anywhere
    assert not os.path.exists(throwaway)


def test_two_different_confs_are_refused_and_neither_is_shredded(offline, tmp_path):
    state = str(tmp_path / "state")
    durable = onboard.create_conf(os.path.join(state, "bot.conf"))
    throwaway = conf(tmp_path / "rt" / "qdojo" / "qdojo_t1.conf")
    with pytest.raises(SystemExit) as e:
        bot_run(offline, tmp_path, state, "--ephemeral-conf", throwaway, top=["--conf", durable])
    assert "different files" in str(e.value)
    assert os.path.exists(durable) and os.path.exists(throwaway)
    bot_run(offline, tmp_path, state, "--ephemeral-conf", throwaway, top=["--conf", throwaway])   # the same file: fine
    assert not os.path.exists(throwaway) and os.path.exists(durable)


def test_house_spar_shreds_the_ephemeral_conf(offline, tmp_path):
    throwaway = conf(tmp_path / "rt" / "qdojo" / "qdojo_house.conf")
    offline.main(["--node", "1.2.3.4", "--identity", HOUSE, "house", "--data", str(tmp_path / "house"),
                  "spar", "--rounds", "0", "--ephemeral-conf", throwaway])
    assert not os.path.exists(throwaway)
    kept = conf(tmp_path / "rt" / "qdojo" / "qdojo_house.conf")
    offline.main(["--node", "1.2.3.4", "--identity", HOUSE, "--conf", kept, "house", "--data", str(tmp_path / "house"),
                  "spar", "--rounds", "0"])
    assert os.path.exists(kept)


def test_startup_check_runs_in_bot_run_house_spar_and_bot_init(offline, tmp_path, monkeypatch, capsys):
    """The three commands the issue names all report, and none deletes. The
    conf a run was handed is in use, not left over, so it is not counted."""
    from qdojo import nodes
    old = conf(tmp_path / "rt" / "qdojo" / "qdojo_old.conf", mtime=time.time() - 4 * 86400)
    older = conf(tmp_path / "rt" / "qdojo" / "qdojo_older.conf", mtime=time.time() - 5 * 86400)
    state = str(tmp_path / "state")
    onboard.create_conf(os.path.join(state, "bot.conf"))

    bot_run(offline, tmp_path, state)
    err = capsys.readouterr().err
    assert "warning: 2 seed confs in" in err and err.index("qdojo_older.conf") < err.index("qdojo_old.conf")
    assert "4d" in err and "5d" in err

    offline.main(["--node", "1.2.3.4", "--identity", HOUSE, "--conf", old, "house", "--data", str(tmp_path / "house"),
                  "spar", "--rounds", "0"])
    err = capsys.readouterr().err
    assert "warning: 1 seed conf in" in err and "qdojo_older.conf" in err and "qdojo_old.conf" not in err

    monkeypatch.setattr(nodes, "native_probe", lambda timeout=6.0: (lambda ip: (1000, [])))
    offline.main(["--cli", fake_cli(tmp_path), "bot", "--state", str(tmp_path / "fresh"), "init", "--name", "RYUBOT",
                  "--provider", "none", "--skip-probe", "--yes", "--no-color"])
    assert "warning: 2 seed confs in" in capsys.readouterr().err
    assert os.path.exists(old) and os.path.exists(older)


def test_startup_check_is_silent_without_a_runtime_dir(offline, tmp_path, capsys):
    state = str(tmp_path / "state")
    onboard.create_conf(os.path.join(state, "bot.conf"))
    bot_run(offline, tmp_path, state)
    assert "warning:" not in capsys.readouterr().err
