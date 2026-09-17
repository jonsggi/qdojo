"""Prompts as files you can edit, so a fighter can be tuned without code.

The point is a person who does not write Python still having something real to
change. With a prompt-driven solver the whole fighter is two text files: what
the model is told about the dojo, and how the riddle is put to it. Edit a
sentence, save, and the next round uses it -- no restart, because the bot runs
the solver as a fresh subprocess per riddle, so the file is re-read anyway.

Two decisions worth keeping:

**Placeholders are `<<name>>`, not `str.format`.** A prompt is full of braces:
it tells the model to answer with `{"answer": VALUE}`. `str.format` would make
the author double every one of them, which is unreadable to exactly the person
this exists for, and a single missed brace would be a KeyError mid-round with
money on the table. An unknown placeholder is left in the text, visible and
harmless, rather than raising.

**A prompt is prose except for one line, which is a contract.** "Your FINAL
line must be ONLY a JSON object" is what `solver.run_solver` relies on when it
reads the last line of stdout. Change its meaning and every answer is rejected.
`check()` asserts the marker survives, and the file says so above the fold.
"""
import os
import re

MARK = "---"                     # everything above it is a note to the editor
PLACEHOLDER = re.compile(r"<<([a-z_]+)>>")

# name -> a substring that must survive editing, because code depends on it.
CONTRACTS = {
    "solver-system.md": '{"answer"',
}


class PromptError(Exception):
    pass


def repo_dir() -> str:
    """The shipped prompts, found the way wizard.examples_dir finds solvers."""
    here = os.path.dirname(os.path.abspath(__file__))
    for cand in (os.path.join(here, "..", "..", "..", "..", "prompts"),
                 os.path.join(os.getcwd(), "prompts"),
                 os.path.expanduser("~/.qdojo/prompts")):
        if os.path.isdir(cand):
            return os.path.abspath(cand)
    return os.path.abspath(os.path.join(here, "..", "..", "..", "..", "prompts"))


def search_path(state_dir: str | None = None) -> list[str]:
    """Where a prompt is looked for, first hit wins, per file name -- so
    editing one prompt does not orphan the others."""
    out = []
    for d in (os.environ.get("QDOJO_PROMPTS") or "").split(os.pathsep):
        if d.strip():
            out.append(os.path.abspath(os.path.expanduser(d.strip())))
    if state_dir:
        out.append(os.path.join(os.path.abspath(os.path.expanduser(state_dir)), "prompts"))
    out.append(os.path.expanduser("~/.qdojo/prompts"))
    out.append(repo_dir())
    seen, uniq = set(), []
    for d in out:
        if d not in seen:
            seen.add(d); uniq.append(d)
    return uniq


def find(name: str, state_dir: str | None = None) -> str:
    if os.sep in name or name.startswith("."):
        raise PromptError(f"a prompt name is a plain file name, not a path: {name!r}")
    for d in search_path(state_dir):
        p = os.path.join(d, name)
        if os.path.isfile(p):
            return p
    raise PromptError(f"no prompt {name!r} on {os.pathsep.join(search_path(state_dir))}; "
                      f"run `qdojo prompts install` to put an editable copy where you can reach it")


def body(text: str) -> str:
    """What is actually sent: everything below the first marker line. The part
    above is the note telling the editor which sentence they must not break."""
    for i, line in enumerate(text.splitlines()):
        if line.strip() == MARK:
            return "\n".join(text.splitlines()[i + 1:]).strip()
    return text.strip()


def load(name: str, state_dir: str | None = None) -> tuple[str, str]:
    """(the text to send, the file it came from)."""
    path = find(name, state_dir)
    with open(path, encoding="utf-8") as f:
        text = f.read()
    out = body(text)
    if not out:
        raise PromptError(f"{path} is empty below the '{MARK}' line")
    check(name, out, path)
    return out, path


def check(name: str, text: str, path: str = "") -> None:
    """The one line that is a contract with code, not prose."""
    need = CONTRACTS.get(os.path.basename(name))
    if need and need not in text:
        raise PromptError(
            f"{path or name} no longer contains {need!r}. That is not a style rule: "
            f"the dojo reads the LAST line your model prints and expects a JSON object "
            f"there. Put that instruction back, or every answer will be rejected.")


def render(text: str, values: dict) -> str:
    """Fill `<<name>>`. An unknown name is left as written: visible in what the
    model is shown, which is loud and harmless, rather than raising mid-round."""
    return PLACEHOLDER.sub(lambda m: str(values.get(m.group(1), m.group(0))), text)


def placeholders(text: str) -> set:
    return set(PLACEHOLDER.findall(text))


def listing(state_dir: str | None = None) -> list[dict]:
    """Every prompt that can be loaded, and where it is being read from."""
    out, seen = [], set()
    for d in search_path(state_dir):
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if fn.endswith(".md") and fn not in seen:
                seen.add(fn)
                p = os.path.join(d, fn)
                out.append({"name": fn, "path": p, "dir": d, "editable": os.access(p, os.W_OK),
                            "bytes": os.path.getsize(p)})
    return out


def install(state_dir: str, force: bool = False) -> list[str]:
    """Copy the shipped prompts somewhere the player owns, so their edits are
    not in the git checkout where a pull would fight them."""
    src = repo_dir()
    dst = os.path.join(os.path.abspath(os.path.expanduser(state_dir)), "prompts")
    os.makedirs(dst, mode=0o700, exist_ok=True)
    done = []
    for fn in sorted(os.listdir(src)) if os.path.isdir(src) else []:
        if not fn.endswith(".md"):
            continue
        target = os.path.join(dst, fn)
        if os.path.exists(target) and not force:
            continue          # never overwrite an edit, the same rule as a seed conf
        with open(os.path.join(src, fn), encoding="utf-8") as f:
            text = f.read()
        with open(target, "w", encoding="utf-8") as f:
            f.write(text)
        done.append(target)
    return done
