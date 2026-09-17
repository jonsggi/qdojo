"""The local page writes files to disk from a browser. These are the tests
that make that acceptable."""
import json
import os
import threading
import urllib.error
import urllib.request

import pytest

from qdojo import dash, prompts


@pytest.fixture
def served(tmp_path, monkeypatch):
    state = tmp_path / "bot"
    os.makedirs(state, exist_ok=True)
    # a seed sitting next to the state, exactly as a real bot has one
    with open(state / "bot.conf", "w") as f:
        f.write("seed=" + "a" * 55 + "\n")
    os.chmod(state / "bot.conf", 0o600)
    json.dump({"identity": "A" * 60, "name": "RYUBOT", "model": "m",
               "key_source": "env:OPENROUTER_API_KEY"}, open(state / "bot.json", "w"))
    json.dump({"scorecard": {"fought": 3, "solved": 2, "would_have_placed": 1,
                             "would_have_earned": 500, "median_solve_ticks": 21},
               "attempts": []}, open(state / "training.json", "w"))
    pdir = tmp_path / "prompts"
    monkeypatch.setenv("QDOJO_PROMPTS", str(pdir))
    prompts.install(str(tmp_path))          # -> tmp_path/prompts
    httpd, url = dash.serve(str(state), board="", port=0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base, _, q = url.partition("?")
    token = q.split("=", 1)[1]
    yield {"base": base.rstrip("/"), "token": token, "state": str(state), "prompts": str(pdir), "url": url}
    httpd.shutdown()


def get(s, path, token=None, host=None):
    t = s["token"] if token is None else token
    req = urllib.request.Request(f"{s['base']}{path}{'&' if '?' in path else '?'}t={t}")
    if host:
        req.add_header("Host", host)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read().decode(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(), dict(e.headers)


def put(s, name, text, token=None, host=None, raw=None):
    body = raw if raw is not None else json.dumps({"name": name, "text": text}).encode()
    req = urllib.request.Request(f"{s['base']}/api/prompt?t={s['token']}", data=body, method="PUT")
    req.add_header("Content-Type", "application/json")
    req.add_header("X-QDojo-Token", s["token"] if token is None else token)
    if host:
        req.add_header("Host", host)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "{}")


# ------------------------------------------------------------------ the seed

def test_no_route_reaches_the_state_directory(served):
    """The seed is the thing that must never be served, by any path."""
    for path in ("/bot.conf", "/../bot.conf", "/api/prompt?name=../bot.conf",
                 "/api/prompt?name=../../bot.conf", "/state/bot.conf", "/bot.json"):
        code, body, _ = get(served, path)
        assert code in (400, 403, 404), (path, code)
        assert "seed=" not in body and "a" * 55 not in body


def test_the_module_reads_exactly_three_files_out_of_the_state_dir():
    """Naming them is the point: bot.json, training.json, rounds.json, and
    nothing else. The seed conf is not among them and must never be."""
    import ast
    src = open(os.path.join(os.path.dirname(dash.__file__), "dash.py"), encoding="utf-8").read()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef)) and ast.get_docstring(node):
            node.body = node.body[1:]
    literals = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    named = {x for x in literals if x.endswith(".json")}
    assert named == {"bot.json", "training.json", "rounds.json", "fighters.json", "/fighters.json"}, named
    # No path-LIKE literal may name a conf. Prose is exempt: the guard's own
    # refusal message has to be able to say the word.
    paths = {x for x in literals if x and " " not in x}
    assert not [x for x in paths if "conf" in x and x != ".conf"], paths
    assert ".conf" in paths             # present only as the guard that REFUSES such a directory


def test_it_refuses_to_serve_a_directory_holding_a_seed(tmp_path, monkeypatch):
    d = tmp_path / "mixed"
    os.makedirs(d)
    open(d / "solver-system.md", "w").write('---\n{"answer": V}')
    open(d / "bot.conf", "w").write("seed=" + "a" * 55)
    monkeypatch.setenv("QDOJO_PROMPTS", str(d))
    with pytest.raises(dash.DashError) as e:
        dash.Fighter(str(tmp_path), "")
    assert "never share a directory with a seed" in str(e.value)


# --------------------------------------------------------------- the token

def test_the_api_needs_the_token_the_command_printed(served):
    assert get(served, "/api/fighter", token="")[0] == 403
    assert get(served, "/api/fighter", token="wrong")[0] == 403
    assert get(served, "/api/fighter")[0] == 200


def test_a_write_needs_the_token_in_a_header_not_just_the_url(served):
    code, doc = put(served, "solver-user.md", "---\nx", token="wrong")
    assert code == 403 and "token" in doc["error"]


# ----------------------------------------------------------- the browser rules

def test_no_cors_header_is_ever_sent(served):
    for path in ("/", "/api/fighter"):
        _, _, headers = get(served, path)
        assert not [k for k in headers if k.lower().startswith("access-control")]


def test_a_rebound_host_is_refused(served):
    """A DNS-rebinding request arrives carrying the attacker's hostname."""
    assert get(served, "/api/fighter", host="evil.example")[0] == 403
    assert get(served, "/api/fighter", host="127.0.0.1:1")[0] == 403


def test_the_security_headers_are_present(served):
    _, _, h = get(served, "/")
    assert h["X-Frame-Options"] == "DENY"
    assert h["Referrer-Policy"] == "no-referrer"          # the token must not leak in a Referer
    assert "frame-ancestors 'none'" in h["Content-Security-Policy"]


def test_the_page_does_not_pull_a_web_font(served):
    """A font request would carry the token in a Referer, and the page has to
    work with no network at all."""
    _, body, _ = get(served, "/")
    assert "fonts.googleapis" not in body and "fonts.gstatic" not in body


# --------------------------------------------------------------- the writing

def test_a_prompt_can_be_edited_and_is_live_next_round(served):
    text = open(os.path.join(served["prompts"], "solver-user.md"), encoding="utf-8").read()
    code, doc = put(served, "solver-user.md", text + "\nBE BOLD")
    assert code == 200 and doc["live"] == "next round"
    assert "BE BOLD" in open(os.path.join(served["prompts"], "solver-user.md"), encoding="utf-8").read()
    assert os.path.exists(os.path.join(served["prompts"], "solver-user.md.bak"))


def test_traversal_cannot_escape_the_prompts_directory(served):
    for name in ("../bot.conf", "../../etc/passwd", "/etc/passwd", "a/b.md", "..%2Fbot.conf"):
        code, doc = put(served, name, "x")
        assert code == 400, (name, code)
        assert "prompt name" in doc["error"] or "outside" in doc["error"]


def test_a_symlink_planted_in_the_prompts_directory_cannot_escape(served):
    link = os.path.join(served["prompts"], "escape.md")
    os.symlink(os.path.join(served["state"], "bot.conf"), link)
    code, doc = put(served, "escape.md", "---\npwned")
    assert code == 400 and "outside" in doc["error"]
    assert "seed=" in open(os.path.join(served["state"], "bot.conf"), encoding="utf-8").read()


def test_only_md_and_only_files_that_already_exist(served):
    assert put(served, "new.md", "---\nx")[0] == 400            # no create
    assert put(served, "solver-user.txt", "x")[0] == 400        # no other extension


def test_an_oversized_body_is_refused(served):
    code, _ = put(served, "solver-user.md", "x" * (dash.MAX_BODY + 10))
    assert code in (400, 413)


def test_an_edit_that_breaks_the_parser_contract_is_refused(served):
    code, doc = put(served, "solver-system.md", "---\njust be nice")
    assert code == 400 and "LAST line" in doc["error"]


def test_options_is_refused_so_a_cross_origin_write_cannot_preflight(served):
    req = urllib.request.Request(f"{served['base']}/api/fighter", method="OPTIONS")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            code = r.status
    except urllib.error.HTTPError as e:
        code = e.code
    assert code == 405


def test_read_only_shows_everything_and_saves_nothing(tmp_path, monkeypatch):
    state = tmp_path / "bot"
    os.makedirs(state)
    json.dump({"identity": "A" * 60}, open(state / "bot.json", "w"))
    monkeypatch.setenv("QDOJO_PROMPTS", str(tmp_path / "prompts"))
    prompts.install(str(tmp_path))
    httpd, url = dash.serve(str(state), board="", port=0, read_only=True)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base, _, q = url.partition("?")
    s = {"base": base.rstrip("/"), "token": q.split("=", 1)[1]}
    try:
        assert get(s, "/api/fighter")[0] == 200
        assert put(s, "solver-user.md", "---\nx")[0] == 403
    finally:
        httpd.shutdown()


# ------------------------------------------------------------------ content

def test_the_api_shows_the_training_scorecard_and_never_a_key(served):
    code, body, _ = get(served, "/api/fighter")
    assert code == 200
    doc = json.loads(body)
    assert doc["training"]["scorecard"]["solved"] == 2
    assert doc["profile"]["key_source"] == "env:OPENROUTER_API_KEY"   # the NAME of a place
    assert "sk-" not in body and "seed" not in body
    assert {"identity", "name", "provider", "model", "key_source"} == set(doc["profile"])
