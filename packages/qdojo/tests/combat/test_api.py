"""The read API's contract: shapes, pagination, errors, CORS, caching, static files (AUD-026)."""
import gzip
import json
import threading
import urllib.error
import urllib.request

import pytest

from qdojo.combat import api, codec, export, live
from qdojo.combat import readmodel as rm

ORIGIN = "https://qdojo.example"


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("api")
    lineup = [{"label": "a", "policy": "scout-v1", "cups": True}, {"label": "b", "policy": "kicker-v1", "cups": True},
              {"label": "e", "policy": "reader-v1", "cups": True}, {"label": "f", "policy": "search-v1", "cups": True},
              {"label": "c", "policy": "mixed-v1", "duels": True, "ranked": False},
              {"label": "d", "policy": "jabber-v1", "duels": True, "ranked": False}]
    arena = live.Arena(tmp / "arena", lineup, seed=3, deterministic=True, cup_every=600, duel_every=80,
                       log=lambda m: None)
    for _ in range(1300):
        arena.step()
    arena.save()
    out = tmp / "web" / "combat" / "v1"
    export.export_all(arena.w.contract, out, keep=4, deployment=arena.deployment(1.5))
    rm.rebuild(arena.dir, tmp / "rm.sqlite", out, log=lambda m: None)
    srv = api.Server(("127.0.0.1", 0), tmp / "rm.sqlite", out, origins=(ORIGIN,))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield {"base": f"http://127.0.0.1:{srv.server_address[1]}", "c": arena.w.contract, "out": out}
    srv.shutdown()


def get(site, path, headers=None):
    req = urllib.request.Request(site["base"] + path, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            body = r.read()
            return r.status, dict(r.headers), body
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def j(site, path):
    status, _h, body = get(site, path)
    assert status == 200, (path, body)
    return json.loads(body)


def test_status_and_counts(site):
    doc = j(site, "/api/v1/status")
    assert doc["schema"] == "qdojo.combat.api.status.v1"
    assert doc["counts"]["fights"] == len(site["c"].fights)
    assert int(doc["generated_tick"]) == site["c"].tick


def test_fighters_and_leaderboard_carry_full_history(site):
    c = site["c"]
    fighters = j(site, "/api/v1/fighters")["fighters"]
    assert {f["fighter_id"] for f in fighters} == {f.hex() for f in c.fighters}
    by_mode = export.records_by_mode(c)
    for f in fighters:
        fid = bytes.fromhex(f["fighter_id"])
        assert f["records_by_mode"] == {m: {**r} for m, r in by_mode.get(fid, {}).items()}
        assert f["record"] == c.fighters[fid].record and f["origin"] == "house" and f["name"]
    board = j(site, "/api/v1/leaderboard")["fighters"]
    assert [x["rank"] for x in board] == list(range(1, len(board) + 1))
    ratings = [x["lifetime_rating"] for x in board]
    assert ratings == sorted(ratings, reverse=True)
    one = j(site, "/api/v1/fighters/" + board[0]["fighter_id"])
    assert one["fights_total"] == sum(1 for x in c.fights.values() if bytes.fromhex(board[0]["fighter_id"]) in
                                      (x.context.participant_a.fighter_id, x.context.participant_b.fighter_id))
    assert len(one["form"]) <= 10 and one["ratings_recent"]


def test_fight_pages_cover_every_fight_once_newest_first(site):
    c = site["c"]
    first = j(site, "/api/v1/fights?per_page=7")
    assert first["total"] == len(c.fights) and first["pages"] == -(-len(c.fights) // 7)
    seen = []
    for page in range(1, first["pages"] + 1):
        doc = j(site, f"/api/v1/fights?per_page=7&page={page}")
        assert len(doc["items"]) <= 7
        seen += [int(x["fight_id"]) for x in doc["items"]]
    assert seen == sorted(c.fights, reverse=True)
    assert j(site, f"/api/v1/fights?per_page=7&page={first['pages'] + 5}")["items"] == []
    assert j(site, "/api/v1/fights?per_page=100000")["per_page"] == api.MAX_PER_PAGE


def test_fight_filters(site):
    c = site["c"]
    fid = next(iter(c.fighters)).hex()
    mine = j(site, f"/api/v1/fighters/{fid}/fights?per_page=200")
    assert all(fid in (x["fighters"]["A"]["fighter_id"], x["fighters"]["B"]["fighter_id"]) for x in mine["items"])
    assert all(x["slot"] in "AB" for x in mine["items"])
    assert j(site, f"/api/v1/fights?fighter={fid}&per_page=1")["total"] == mine["total"]
    duels = j(site, "/api/v1/fights?mode=duel&per_page=200")
    assert duels["total"] == sum(1 for x in c.fights.values() if x.context.mode == codec.Mode.DUEL) > 0
    assert all(x["mode"] == "duel" for x in duels["items"])
    done = j(site, "/api/v1/fights?status=done&per_page=200")["items"]
    assert all(x["phase"] == "DONE" for x in done)


def test_fight_and_replay_match_the_exporter(site):
    c = site["c"]
    done = next(f for f in sorted(c.fights) if c.fights[f].phase == "DONE" and
                c.contests[c.fights[f].contest_id].status == "DONE" and c.fights[f].rounds)
    status, headers, body = get(site, f"/api/v1/fights/{done}/replay")
    doc = json.loads(body)
    want = export.fight_replay(c, done)
    want.pop("generated_tick")
    doc.pop("generated_tick")
    assert doc == want
    assert "max-age=86400" in headers["Cache-Control"]
    assert j(site, f"/api/v1/fights/{done}")["final"] is True


def test_replay_batches_for_scouting(site):
    fid = next(iter(site["c"].fighters)).hex()
    doc = j(site, f"/api/v1/fighters/{fid}/replays?limit=3")
    assert len(doc["items"]) <= 3 and doc["total"] >= len(doc["items"])
    if doc["next_before"]:
        more = j(site, f"/api/v1/fighters/{fid}/replays?limit=3&before={doc['next_before']}")
        assert all(int(x["fight_id"]) < int(doc["next_before"]) for x in more["items"])


def test_seasons_cups_duels_owners_search(site):
    c = site["c"]
    assert j(site, "/api/v1/seasons")["seasons"]
    cups = j(site, "/api/v1/cups")
    assert cups["total"] == len(c.cups)
    if c.cups:
        assert j(site, f"/api/v1/cups/{max(c.cups)}")["cup_id"] == str(max(c.cups))
    duels = j(site, "/api/v1/duels")
    assert all(d["mode"] == "duel" for d in duels["items"])
    f = next(iter(c.fighters.values()))
    assert f.fighter_id.hex() in j(site, f"/api/v1/owners/{f.owner.hex()}")["owned"]
    hit = j(site, "/api/v1/search?q=a")
    assert any(x["name"] == "a" for x in hit["fighters"])
    assert j(site, f"/api/v1/search?q={max(c.fights)}")["fights"] == [str(max(c.fights))]


@pytest.mark.parametrize("path,status,code", [
    ("/api/v1/fighters/xyz", 400, "bad_id"), ("/api/v1/fighters/" + "0" * 64, 404, "not_found"),
    ("/api/v1/fights/abc", 400, "bad_id"), ("/api/v1/fights/999999", 404, "not_found"),
    ("/api/v1/fights?mode=bogus", 400, "bad_query"), ("/api/v1/fights?page=-1", 400, "bad_query"),
    ("/api/v1/nope", 404, "not_found"), ("/api/v1/search?q=", 400, "bad_query"),
    ("/api/v1/tx", 404, "join_disabled"),
])
def test_errors_are_json(site, path, status, code):
    got, headers, body = get(site, path)
    assert got == status and headers["Content-Type"].startswith("application/json")
    doc = json.loads(body)
    assert doc["error"]["code"] == code and doc["error"]["status"] == status


def test_read_only(site):
    req = urllib.request.Request(site["base"] + "/api/v1/fights", data=b"{}", method="POST",
                                 headers={"Content-Type": "application/json"})
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req, timeout=5)
    assert e.value.code == 405


def test_cors_only_for_configured_origins(site):
    _s, h, _b = get(site, "/api/v1/status", {"Origin": ORIGIN})
    assert h["Access-Control-Allow-Origin"] == ORIGIN and "Origin" in h["Vary"]
    _s, h, _b = get(site, "/api/v1/status", {"Origin": "https://evil.example"})
    assert "Access-Control-Allow-Origin" not in h


def test_etag_and_gzip(site):
    status, h, body = get(site, "/api/v1/leaderboard", {"Accept-Encoding": "gzip"})
    assert status == 200 and h.get("Content-Encoding") == "gzip"
    assert json.loads(gzip.decompress(body))["schema"] == "qdojo.combat.api.leaderboard.v1"
    status, _h, _b = get(site, "/api/v1/leaderboard", {"If-None-Match": h["ETag"]})
    assert status == 304


def test_static_export_is_still_served(site):
    status, h, body = get(site, "/index.json")
    assert status == 200 and json.loads(body)["schema"] == "qdojo.combat.index.v1" and "Last-Modified" in h
    assert get(site, "/data/combat/v1/manifest.json")[0] == 200
    for bad in ("/../../../etc/passwd", "/%2e%2e/%2e%2e/etc/passwd", "/fights"):
        assert get(site, bad)[0] == 404
