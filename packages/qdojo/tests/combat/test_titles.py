"""Belts and title belts (competition.md §1 and §7): the finer ladder, the
lineal SCRAP HEAP BELT's transfer rules, determinism, survival across
compaction, snapshots and replays, fighter earnings, and export/API agreement."""
import json
import random
from types import SimpleNamespace as NS

import pytest

from qdojo.combat import export, live, titles
from qdojo.combat import rating as rt
from qdojo.combat import readmodel as rm
from qdojo.combat.codec import Mode

# ---- the ladder ------------------------------------------------------------------

LIVE_FIELD = [1511, 1441, 1329, 1321, 1272, 1246, 1165, 1158, 963, 846, 789, 685, 670, 655, 597]


def test_belt_ladder_thresholds_stripes_and_dans():
    b = rt.belt_info
    assert b(639, True) == {"belt": "white", "belt_rank": 0, "belt_stripes": 3, "dan": None}
    assert b(640, True)["belt"] == "yellow" and b(800, True)["belt"] == "orange"
    assert b(1000, True) == {"belt": "green", "belt_rank": 3, "belt_stripes": 1, "dan": None}
    assert b(1279, True) == {"belt": "blue", "belt_rank": 4, "belt_stripes": 3, "dan": None}
    assert b(1280, True)["belt"] == "purple" and b(1440, True)["belt"] == "brown"
    assert b(1600, True) == {"belt": "black", "belt_rank": 7, "belt_stripes": 0, "dan": 1}
    assert b(1840, True)["dan"] == 5 and b(1899, True)["belt_rank"] == 11
    assert b(1900, True) == {"belt": "red", "belt_rank": 12, "belt_stripes": 0, "dan": None}
    assert b(3000, True)["belt"] == "red" and b(0, True)["belt_stripes"] == 0
    # Provisional: white, no stripes, whatever the rating.
    assert b(1700, False) == {"belt": "white", "belt_rank": 0, "belt_stripes": 0, "dan": None}
    # Monotone: a higher rating never shows a lower belt or fewer stripes within one belt.
    prev = (0, 0)
    for r in range(0, 3001):
        x = b(r, True)
        assert x["belt"] == rt.belt(r, True)
        cur = (x["belt_rank"], x["belt_stripes"])
        assert cur >= prev
        prev = cur
    # The live field of 2026-09-27 spreads over every colour below black.
    belts = [rt.belt(r, True) for r in LIVE_FIELD]
    assert set(belts) == {"white", "yellow", "orange", "green", "blue", "purple", "brown"}
    assert belts.count("white") == 1


# ---- the lineal belt on hand-made fights --------------------------------------------

A, B, C, D = (bytes([i]) * 32 for i in (1, 2, 3, 4))
H = {x: x.hex() for x in (A, B, C, D)}


def fight(fid, a, b, kind, winner=None, tick=None, mode=Mode.RANKED, result="KO", done=True):
    ctx = NS(mode=mode, participant_a=NS(fighter_id=a), participant_b=NS(fighter_id=b))
    res = {"kind": kind, "winner": winner, "tick": tick if tick is not None else fid * 10}
    if kind == "COMBAT" and winner:
        res["result"] = result
    return NS(fight_id=fid, context=ctx, phase="DONE" if done else "COMMIT", result=res if done else None)


class FakeContract:
    def __init__(self, fights, tick=10**6):
        self.fights = {f.fight_id: f for f in fights}
        self.next_id = {"fight": max(self.fights, default=0) + 1}
        self.contests, self.cups, self.fighters = {}, {}, {}
        self.tick = tick
        self.m = NS(season=lambda t: 0)


def fold(fights, **kw):
    st = titles.new_state()
    titles.advance(st, FakeContract(fights, **kw))
    return st


def test_first_holder_is_the_first_ranked_combat_winner():
    st = fold([fight(1, A, B, "FORFEIT", "A"),                 # a forfeit crowns nobody
               fight(2, A, B, "COMBAT", "B", mode=Mode.DUEL),  # a duel crowns nobody
               fight(3, C, D, "COMBAT", None, result="HP_TIE"),  # a draw has no winner
               fight(4, C, D, "COMBAT", "B", result="HP")])     # D wins on points
    assert titles.holder(st) == H[D]
    assert st["reigns"][0]["from_fight"] == 4 and st["reigns"][0]["won_from"] is None


def test_the_belt_moves_only_on_a_combat_loss():
    fights = [fight(1, A, B, "COMBAT", "A"),                    # A crowned
              fight(2, B, A, "COMBAT", "B"),                    # A defends by KO
              fight(3, A, C, "COMBAT", None, result="HP_TIE"),  # draw: a defence
              fight(4, C, A, "FORFEIT", "A"),                   # A forfeits: nothing moves
              fight(5, A, C, "DOUBLE_FAULT"),                   # nothing
              fight(6, A, D, "VOID"),                           # nothing
              fight(7, C, D, "COMBAT", "A"),                    # not a title fight
              fight(8, D, A, "COMBAT", "B", mode=Mode.CUP),     # a cup loss moves nothing
              fight(9, A, B, "COMBAT", "A", mode=Mode.DUEL),    # a duel loss moves nothing
              fight(10, C, A, "COMBAT", "A", result="HP"),      # C beats A on points: new champion
              fight(11, A, C, "COMBAT", "A")]                   # A takes it back
    st = fold(fights)
    r = st["reigns"]
    assert [x["holder"] for x in r] == [H[A], H[C], H[A]]
    assert r[0] == {**r[0], "from_fight": 1, "to_fight": 10, "lost_to": H[C], "how": "HP", "defenses": 2,
                    "wins": 1, "draws": 1, "title_fights": 6}
    assert r[1]["won_from"] == H[A] and r[1]["to_fight"] == 11 and r[1]["defenses"] == 0
    assert titles.holder(st) == H[A] and r[2]["to_fight"] is None
    look = titles.Lookup(st)
    flags = {f.fight_id: look.flags(f) for f in fights}
    assert [k for k, v in flags.items() if v["title_fight"]] == [2, 3, 4, 5, 6, 10, 11]
    assert flags[10] == {"title_fight": True, "new_champion": H[C]}
    assert flags[11] == {"title_fight": True, "new_champion": H[A]}
    assert flags[1] == {"title_fight": False}                    # the crowning fight had no holder
    # A live ranked fight is a title fight when the holder is in it.
    assert look.flags(fight(12, B, A, "COMBAT", done=False)) == {"title_fight": True}
    assert look.flags(fight(13, B, C, "COMBAT", done=False)) == {"title_fight": False}
    pub = titles.public(st)
    assert pub["lineal"]["holder"] == H[A] and pub["lineal"]["reigns_total"] == 3
    assert pub["lineal"]["history"][0]["from_fight"] == "11"            # newest first
    assert pub["fighters"][H[A]]["holds"] == ["lineal"] and pub["fighters"][H[A]]["lineal_reigns"] == 2
    assert pub["fighters"][H[C]]["lineal_reigns"] == 1


def test_fold_order_is_result_tick_then_fight_id():
    # Fight 3 ends before fight 2: the belt follows the ticks, not the IDs.
    fights = [fight(1, A, B, "COMBAT", "A", tick=10), fight(2, C, B, "COMBAT", "A", tick=50),
              fight(3, B, A, "COMBAT", "A", tick=30)]
    st = fold(fights)
    # By ID, C would have lost to nobody's belt (fight 2 before 3); by tick, B takes it
    # from A at tick 30 and loses it to C at tick 50.
    assert [x["holder"] for x in st["reigns"]] == [H[A], H[B], H[C]]
    assert [x["from_fight"] for x in st["reigns"]] == [1, 3, 2]


def test_checkpoints_at_any_ticks_give_the_same_state():
    rng = random.Random(7)
    ids = [A, B, C, D]
    fights = []
    for fid in range(1, 400):
        a, b = rng.sample(ids, 2)
        kind = rng.choice(["COMBAT"] * 6 + ["FORFEIT", "DOUBLE_FAULT", "VOID"])
        winner = rng.choice(["A", "B", None]) if kind == "COMBAT" else rng.choice(["A", "B"]) if kind == "FORFEIT" else None
        mode = rng.choice([Mode.RANKED] * 4 + [Mode.DUEL, Mode.CUP])
        fights.append(fight(fid, a, b, kind, winner, tick=rng.randrange(0, 2000), mode=mode))
    whole = fold(fights)
    for trial in range(6):
        st = titles.new_state()
        c = FakeContract([])
        dropped = set()
        cuts = sorted(rng.sample(range(0, 2000), 12)) + [10**6]
        for cut in cuts:
            # A fight is DONE once its tick has passed; each checkpoint folds what ended before `cut`.
            c.fights = {f.fight_id: (f if f.result["tick"] < cut else NS(**{**vars(f), "phase": "COMMIT", "result": None}))
                        for f in fights if f.fight_id not in dropped}
            c.next_id = {"fight": len(fights) + 1}
            c.tick = cut
            titles.advance(st, c, limit=cut)
            if trial % 2:           # compaction drops some folded fights
                dropped |= {k for k, f in c.fights.items() if f.result is not None and rng.random() < 0.5}
        assert st == whole


# ---- the arena: compaction, snapshots, replays, the read model and the API ------------

LINEUP = [{"label": "a", "policy": "scout-v1", "cups": True}, {"label": "b", "policy": "kicker-v1", "cups": True},
          {"label": "e", "policy": "reader-v1", "cups": True}, {"label": "f", "policy": "search-v1", "cups": True},
          {"label": "c", "policy": "mixed-v1", "duels": True, "ranked": False},
          {"label": "d", "policy": "jabber-v1", "duels": True, "ranked": False}]


def test_titles_and_earnings_survive_compaction_and_snapshot_restarts(tmp_path, monkeypatch):
    from qdojo.combat import devnet, store
    monkeypatch.setattr(live, "compact", lambda c: store.compact(c, keep_ticks=150, keep_recent=6, per_fighter=2,
                                                                 keep_cups=1))
    monkeypatch.setattr(live, "COMPACT_EVERY", 100)
    lineup = [dict(e) for e in live.DEFAULT_LINEUP]
    arena = live.Arena(tmp_path / "arena", lineup, profile="dev", seed=21, deterministic=True, cup_every=700,
                       duel_every=100, market_every=0, log=lambda m: None, snapshot_every=500)
    for i in range(1, 2401):
        arena.step()
        if i % 50 == 0:
            arena.save()
    arena.save()
    c = arena.w.contract
    assert c.history.pruned["fights"] >= 10, "the arena compacted finished fights"
    got = titles.current(c)
    assert len(got["reigns"]) >= 2 and got["recent"], "the belt changed hands in this run"
    assert got["cup_wins"] and got["money"]
    # The whole journal replayed with no compaction at all: the same titles and earnings.
    from qdojo.combat.sim import World
    records = [json.loads(x) for x in (arena.dir / devnet.JOURNAL).read_text().splitlines() if x.strip()]
    w = World(devnet.Devnet(arena.dir).m, tick=next(r for r in records if r["k"] == "start")["t"])
    devnet.apply_records(w, records)
    assert len(w.contract.fights) == c.next_id["fight"] - 1
    assert titles.current(w.contract) == got
    # A restart from the snapshot, and a full replay with compaction, agree too.
    fast = devnet.Devnet(arena.dir, compact=live.compact, compact_every=live.COMPACT_EVERY)
    assert fast.restart["mode"].startswith("snapshot")
    assert titles.current(fast.world.contract) == got
    for name in (devnet.SNAPSHOT, devnet.SNAPSHOT_PREV):
        (arena.dir / name).unlink(missing_ok=True)
    slow = devnet.Devnet(arena.dir, compact=live.compact, compact_every=live.COMPACT_EVERY)
    assert slow.restart["mode"] == "full replay"
    assert titles.persistent(slow.world.contract) == titles.persistent(c)
    assert titles.current(slow.world.contract) == got
    # Earnings are zero-sum up to the rake and the cup sponsorship.
    money = got["money"].values()
    net = sum(m[x]["won"] - m[x]["lost"] for m in money for x in titles.MODES)
    assert net == sum(m["prize_sponsorship"] for m in money) - sum(m[x]["rake"] for m in money for x in titles.MODES)
    # The read model, rebuilt from the journal, publishes the same titles.
    out = tmp_path / "web" / "combat" / "v1"
    export.export_all(c, out, keep=5, deployment=arena.deployment(1.5), qualification=arena.qualification)
    rm.rebuild(arena.dir, tmp_path / "rm.sqlite", out, log=lambda m: None)
    conn = rm.connect(tmp_path / "rm.sqlite", readonly=True)
    published = json.loads((out / "titles.json").read_text())
    assert rm.get_meta(conn, "titles") == {k: v for k, v in published.items() if k in titles.public(got)}
    assert conn.execute("SELECT COUNT(*) FROM lineal_reigns").fetchone()[0] == len(got["reigns"])


def test_export_and_api_agree_on_belts_titles_and_earnings(tmp_path):
    import threading
    import urllib.request
    from qdojo.combat import api
    arena = live.Arena(tmp_path / "arena", [dict(e) for e in live.DEFAULT_LINEUP], profile="dev", seed=21,
                       deterministic=True, cup_every=700, duel_every=100, market_every=0, log=lambda m: None)
    for _ in range(2400):
        arena.step()
    arena.save()
    out = tmp_path / "web" / "combat" / "v1"
    export.export_all(arena.w.contract, out, keep=300, deployment=arena.deployment(1.5),
                      qualification=arena.qualification)
    rm.rebuild(arena.dir, tmp_path / "rm.sqlite", out, log=lambda m: None)
    srv = api.Server(("127.0.0.1", 0), tmp_path / "rm.sqlite", out)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}/api/v1/"

    def get(path):
        with urllib.request.urlopen(base + path, timeout=10) as r:
            return json.loads(r.read())
    try:
        static = json.loads((out / "titles.json").read_text())
        served = get("titles")
        for k in ("lineal", "season", "cup", "fighters", "career"):
            assert served[k] == static[k], k
        assert static["lineal"]["holder"], "someone holds the belt"
        reigns = get("titles/lineal?per_page=200")
        assert reigns["total"] == static["lineal"]["reigns_total"]
        assert reigns["items"] == static["lineal"]["history"][:len(reigns["items"])]
        keys = ("belt", "belt_rank", "belt_stripes", "dan", "titles", "earnings", "streak", "owner_credit",
                "lifetime_rating", "provisional")
        for p in (out / "fighters").glob("*.json"):
            f = json.loads(p.read_text())
            a = get("fighters/" + f["fighter_id"])
            assert {k: a[k] for k in keys} == {k: f[k] for k in keys}, f["fighter_id"]
        # Fight summaries carry the same title flags; results.json too.
        results = json.loads((out / "results.json").read_text())["results"]
        assert any(x["title_fight"] for x in results)
        for x in results[:60]:
            doc = get("fights/" + x["fight_id"])
            assert doc["title_fight"] == x["title_fight"] and doc.get("new_champion") == x.get("new_champion")
            with open(out / "fights" / f"{x['fight_id']}.json") as fh:
                assert json.load(fh)["title_fight"] == x["title_fight"]
        changed = [x for x in results if x.get("new_champion")]
        froms = {r["from_fight"] for r in static["lineal"]["history"]}
        assert all(x["fight_id"] in froms for x in changed)
    finally:
        srv.shutdown()


def test_earnings_follow_the_ledger_formula(tmp_path):
    arena = live.Arena(tmp_path / "arena", LINEUP, seed=9, deterministic=True, cup_every=400, duel_every=60,
                       market_every=0, log=lambda m: None)
    for _ in range(1200):
        arena.step()
    c = arena.w.contract
    st = titles.current(c)
    want: dict = {}
    from qdojo.combat.ledger import split_purse
    for ct in c.contests.values():
        if ct.status != "DONE" or ct.mode not in (Mode.RANKED, Mode.DUEL) or ct.result["kind"] not in (
                "COMBAT", "FORFEIT") or ct.result.get("winner") is None:
            continue
        credit, rake = split_purse(2 * ct.stake, c.m.fees[ct.fee_profile_id])[:2]
        # The winner's payout recipient was credited exactly this (ledger.settle_win).
        side = {"A": ct.a, "B": ct.b}
        win = side[ct.result["winner"]]
        assert ct.settlement["credits"].get(win.payout_recipient, 0) >= credit
        mode = Mode(ct.mode).name.lower()
        w = want.setdefault(win.fighter_id.hex(), {}).setdefault(mode, [0, 0])
        w[0] += credit - ct.stake
        lose = side["B" if ct.result["winner"] == "A" else "A"]
        want.setdefault(lose.fighter_id.hex(), {}).setdefault(mode, [0, 0])[1] += ct.stake
    assert want
    for hexid, modes in want.items():
        e = titles.earnings(st, hexid)
        for mode, (won, lost) in modes.items():
            assert (int(e[mode]["won"]), int(e[mode]["lost"])) == (won, lost), (hexid, mode)
    doc = export.fighter(c, next(iter(c.fighters)))
    assert set(doc["earnings"]) >= {"ranked", "duel", "cup", "won", "lost", "net", "rake", "biggest_win"}
    assert set(doc["streak"]) == {"current", "best"}


@pytest.mark.parametrize("rating,placed,name", [(1511, True, "brown"), (597, True, "white"), (1000, False, "white")])
def test_export_fighter_belt_fields(rating, placed, name):
    x = rt.belt_info(rating, placed)
    assert x["belt"] == name and x["belt"] == rt.belt(rating, placed)
