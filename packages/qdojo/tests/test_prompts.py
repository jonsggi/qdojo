import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from qdojo import prompts

SOLVER = os.path.join(os.path.dirname(__file__), "..", "..", "..", "examples", "solvers", "prompted.py")
RIDDLE = {"round_id": 7, "title": "White belt: the sum", "statement": "Add them.",
          "input": "17 25 -8 108", "answer_format": "integer"}


def write(d, name, text):
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, name), "w", encoding="utf-8") as f:
        f.write(text)
    return os.path.join(d, name)


# ------------------------------------------------------------------ the body

def test_the_note_to_the_editor_is_never_sent_to_the_model():
    text = "# how to edit this\nbreak nothing\n\n---\nYou are a fighter.\n"
    assert prompts.body(text) == "You are a fighter."


def test_a_prompt_with_no_marker_is_sent_whole():
    assert prompts.body("just the prompt") == "just the prompt"


# ------------------------------------------------------------ placeholders

def test_braces_survive_because_a_prompt_is_full_of_them():
    """The whole reason placeholders are <<name>> and not str.format: the
    prompt's own text tells the model to answer with {"answer": VALUE}."""
    t = 'answer with {"answer": VALUE} for <<answer_format>>'
    out = prompts.render(t, {"answer_format": "integer"})
    assert out == 'answer with {"answer": VALUE} for integer'


def test_an_unknown_placeholder_is_left_visible_rather_than_raising():
    """Mid-round, with money on the table, is the wrong moment to raise."""
    assert prompts.render("hello <<nobody>>", {}) == "hello <<nobody>>"


def test_render_finds_every_placeholder():
    assert prompts.placeholders("a <<x>> b <<y>> c <<x>>") == {"x", "y"}


# ------------------------------------------------------------- the contract

def test_the_contract_sentence_is_enforced():
    with pytest.raises(prompts.PromptError) as e:
        prompts.check("solver-system.md", "be a good fighter and try hard")
    assert "LAST line" in str(e.value)


def test_a_prompt_that_keeps_the_contract_passes():
    prompts.check("solver-system.md", 'print {"answer": VALUE} last')


def test_only_named_prompts_carry_a_contract():
    prompts.check("solver-user.md", "anything at all")


# -------------------------------------------------------------- resolution

def test_the_state_dir_wins_over_the_shipped_copy(tmp_path, monkeypatch):
    monkeypatch.delenv("QDOJO_PROMPTS", raising=False)
    state = tmp_path / "bot"
    write(str(state / "prompts"), "solver-user.md", "---\nMINE <<title>>")
    text, path = prompts.load("solver-user.md", state_dir=str(state))
    assert text == "MINE <<title>>" and str(state) in path


def test_env_wins_over_everything(tmp_path, monkeypatch):
    d = tmp_path / "elsewhere"
    write(str(d), "solver-user.md", "---\nENV")
    monkeypatch.setenv("QDOJO_PROMPTS", str(d))
    state = tmp_path / "bot"
    write(str(state / "prompts"), "solver-user.md", "---\nSTATE")
    text, _ = prompts.load("solver-user.md", state_dir=str(state))
    assert text == "ENV"


def test_resolution_is_per_file_so_editing_one_does_not_orphan_the_others(tmp_path, monkeypatch):
    monkeypatch.delenv("QDOJO_PROMPTS", raising=False)
    state = tmp_path / "bot"
    write(str(state / "prompts"), "solver-user.md", "---\nMINE")
    assert prompts.load("solver-user.md", state_dir=str(state))[0] == "MINE"
    # the one they did not copy still resolves, to the shipped original
    text, path = prompts.load("solver-system.md", state_dir=str(state))
    assert str(state) not in path and "fighter" in text


def test_a_path_is_not_a_prompt_name():
    for bad in ("../secret.md", "a/b.md", ".hidden.md"):
        with pytest.raises(prompts.PromptError):
            prompts.find(bad)


def test_a_missing_prompt_says_where_it_looked_and_what_to_do(tmp_path, monkeypatch):
    monkeypatch.setenv("QDOJO_PROMPTS", str(tmp_path))
    with pytest.raises(prompts.PromptError) as e:
        prompts.load("nope.md", state_dir=str(tmp_path))
    assert "prompts install" in str(e.value)


# ----------------------------------------------------------------- shipped

def test_every_shipped_prompt_loads_renders_and_keeps_its_contract():
    names = [x["name"] for x in prompts.listing()]
    assert {"solver-system.md", "solver-user.md"} <= set(names)
    for name in ("solver-system.md", "solver-user.md"):
        text, _ = prompts.load(name)
        out = prompts.render(text, RIDDLE)
        assert out and "<<" not in out, f"{name} has an unfilled placeholder: {out}"


def test_install_never_overwrites_an_edit(tmp_path):
    state = str(tmp_path / "bot")
    assert prompts.install(state)
    mine = os.path.join(state, "prompts", "solver-user.md")
    with open(mine, "w", encoding="utf-8") as f:
        f.write("---\nMINE")
    prompts.install(state)
    with open(mine, encoding="utf-8") as f:
        assert f.read() == "---\nMINE"
    assert prompts.install(state, force=True)
    with open(mine, encoding="utf-8") as f:
        assert f.read() != "---\nMINE"


# ------------------------------------------------- the whole path, for real

class _Chat(BaseHTTPRequestHandler):
    seen = {}

    def do_POST(self):
        n = int(self.headers["Content-Length"])
        _Chat.seen.update(json.loads(self.rfile.read(n)))
        out = json.dumps({"choices": [{"message": {"content": 'thinking...\n{"answer": 142}'}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        pass


@pytest.fixture
def chat():
    srv = HTTPServer(("127.0.0.1", 0), _Chat)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    _Chat.seen = {}
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def test_the_prompt_really_reaches_the_model_and_the_answer_comes_back(chat, tmp_path):
    """Prompt file -> HTTP body -> parsed answer, end to end, no network.
    Nothing else pins this path, and it is the path a prompt edit travels."""
    env = dict(os.environ, OPENAI_BASE_URL=chat, OPENAI_MODEL="m", OPENAI_API_KEY="x",
               QDOJO_PROMPTS=str(tmp_path))
    write(str(tmp_path), "solver-system.md", '---\nCANARY-SYSTEM {"answer": V} <<answer_format>>')
    write(str(tmp_path), "solver-user.md", "---\nCANARY-USER <<title>> / <<input>>")
    p = subprocess.run([sys.executable, SOLVER], input=json.dumps(RIDDLE).encode(),
                       capture_output=True, env=env, timeout=30)
    assert p.returncode == 0, p.stderr.decode()
    assert json.loads(p.stdout.decode().strip())["answer"] == 142
    sent = {m["role"]: m["content"] for m in _Chat.seen["messages"]}
    assert "CANARY-SYSTEM" in sent["system"] and "integer" in sent["system"]
    assert "CANARY-USER" in sent["user"] and RIDDLE["title"] in sent["user"]
    assert "17 25 -8 108" in sent["user"]


def test_an_edit_that_breaks_the_contract_fails_loudly_not_silently(chat, tmp_path):
    env = dict(os.environ, OPENAI_BASE_URL=chat, OPENAI_MODEL="m", QDOJO_PROMPTS=str(tmp_path))
    write(str(tmp_path), "solver-system.md", "---\njust be nice about it")
    write(str(tmp_path), "solver-user.md", "---\n<<title>>")
    p = subprocess.run([sys.executable, SOLVER], input=json.dumps(RIDDLE).encode(),
                       capture_output=True, env=env, timeout=30)
    assert p.returncode == 2
    assert "LAST line" in p.stderr.decode()
