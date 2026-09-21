"""Deterministic riddle generators, graded by belt.

Every generator computes its own single canonical answer. No I/O, no network,
no randomness outside the `random.Random` passed in. The answer of a generated
riddle survives `hashing.canonical_answer` unchanged after `str()`.

    generate(belt, rng, round_id)      -> riddle dict, kind picked uniformly
    kinds(belt)                        -> kind names available at that belt
    generate_kind(kind, rng, round_id) -> riddle dict of that kind
"""
import hashlib
import random

from . import hashing, qubic_riddles

BELTS = ("white", "yellow", "orange", "green", "blue")

MOD = 1_000_007

_WORDS = (
    "anchor", "bamboo", "candle", "dragon", "ember", "falcon", "garden", "harbor",
    "island", "jasmine", "kettle", "lantern", "meadow", "needle", "orchid", "pebble",
    "quartz", "river", "saddle", "timber", "umbrella", "velvet", "willow", "yonder",
    "zephyr", "acorn", "blossom", "copper", "dune", "eagle", "fern", "glacier",
    "hollow", "ivory", "juniper", "koi", "lagoon", "marble", "nectar", "oak",
    "prairie", "quill", "ridge", "sparrow", "thistle", "urchin", "valley", "walnut",
    "yarrow", "zinc", "sky", "moss", "tide", "ash", "cliff", "fog", "hawk", "oyster",
)
_ALNUM = "abcdefghijklmnopqrstuvwxyz0123456789"
_LOWER = "abcdefghijklmnopqrstuvwxyz"


class RiddleGenError(ValueError):
    """A belt or kind that does not exist."""


# --------------------------------------------------------------------------
# helpers

def _words(rng, n):
    return [rng.choice(_WORDS) for _ in range(n)]


def _token(rng, n, alphabet=_ALNUM):
    return "".join(rng.choice(alphabet) for _ in range(n))


def _sieve(limit):
    """Primality flags for 0..limit inclusive."""
    flags = bytearray([1]) * (limit + 1)
    flags[0] = 0
    if limit >= 1:
        flags[1] = 0
    i = 2
    while i * i <= limit:
        if flags[i]:
            flags[i * i::i] = bytearray(len(range(i * i, limit + 1, i)))
        i += 1
    return flags


_SAFE_BUILTINS = {
    "range": range, "len": len, "enumerate": enumerate, "sum": sum, "max": max,
    "min": min, "abs": abs, "sorted": sorted, "reversed": reversed, "list": list,
    "int": int, "str": str, "divmod": divmod,
}


def _run_program(code):
    """Execute a template program in a restricted namespace; return the single
    integer it prints. Raises if the program prints anything else."""
    out = []

    def _print(*args, **kw):
        out.append(" ".join(str(a) for a in args))

    ns = {"__builtins__": dict(_SAFE_BUILTINS, print=_print)}
    exec(code, ns)  # noqa: S102 - our own template, not user input
    if len(out) != 1:
        raise RiddleGenError(f"template printed {len(out)} lines")
    return int(out[0])


def _run_function(code, fname, args):
    """Define a template function in a restricted namespace and call it."""
    ns = {"__builtins__": dict(_SAFE_BUILTINS)}
    exec(code, ns)  # noqa: S102
    return ns[fname](*args)


# --------------------------------------------------------------------------
# white belt: pure reading

def _sum_lines(rng):
    nums = [rng.randint(-1000, 1000) for _ in range(rng.randint(15, 40))]
    return {
        "title": "sum the numbers",
        "statement": "The input holds one integer per line (some may be negative). "
                     "Compute their sum. Answer with the integer.",
        "input": "\n".join(str(n) for n in nums),
        "answer_format": "integer",
        "answer": sum(nums),
    }


def _count_letter(rng):
    text = " ".join(_words(rng, rng.randint(30, 60)))
    letter = rng.choice(sorted(set(text) - {" "}))
    return {
        "title": "count a letter",
        "statement": f"The input is a lowercase text. Count how many times the letter "
                     f"'{letter}' occurs in it. Answer with the integer.",
        "input": text,
        "answer_format": "integer",
        "answer": text.count(letter),
    }


def _max_int(rng):
    nums = [rng.randint(-100_000, 100_000) for _ in range(rng.randint(10, 30))]
    return {
        "title": "find the largest number",
        "statement": "The input holds one integer per line. Find the largest one. "
                     "Answer with the integer.",
        "input": "\n".join(str(n) for n in nums),
        "answer_format": "integer",
        "answer": max(nums),
    }


def _longest_word(rng):
    words = _words(rng, rng.randint(15, 40))
    return {
        "title": "length of the longest word",
        "statement": "The input is a list of lowercase words separated by single spaces. "
                     "Find the length (number of letters) of the longest word. "
                     "Answer with the integer.",
        "input": " ".join(words),
        "answer_format": "integer",
        "answer": max(len(w) for w in words),
    }


# --------------------------------------------------------------------------
# yellow belt: simple transforms

def _reverse_string(rng):
    s = _token(rng, rng.randint(16, 40))
    return {
        "title": "reverse the string",
        "statement": "The input is a single string of lowercase letters and digits. "
                     "Reverse it. Answer with the reversed string exactly.",
        "input": s,
        "answer_format": "string",
        "answer": s[::-1],
    }


def _caesar_decode(rng):
    plain = " ".join(_words(rng, rng.randint(4, 8)))
    shift = rng.randint(1, 25)
    cipher = "".join(
        chr((ord(c) - 97 + shift) % 26 + 97) if c != " " else " " for c in plain
    )
    return {
        "title": "undo a Caesar shift",
        "statement": f"The input is a Caesar-encrypted text: every lowercase letter of the "
                     f"original was shifted forward by {shift} positions in the alphabet "
                     f"(wrapping from z back to a); spaces were left unchanged. Recover the "
                     f"original text. Answer with the decoded string exactly (lowercase letters "
                     f"and single spaces).",
        "input": cipher,
        "answer_format": "string",
        "answer": plain,
    }


def _xor_bytes(rng):
    s = _token(rng, rng.randint(8, 24), _ALNUM + "ABCDEFGHIJKLMNOPQRSTUVWXYZ")
    x = 0
    for b in s.encode("ascii"):
        x ^= b
    return {
        "title": "XOR all the bytes",
        "statement": "The input is a single ASCII string. XOR together the ASCII codes of "
                     "all its characters. Answer with the result as exactly two lowercase "
                     "hex digits, zero-padded (for example 0a or 7f).",
        "input": s,
        "answer_format": "hex",
        "answer": f"{x:02x}",
    }


def _digit_sum(rng):
    digits = rng.choice("123456789") + _token(rng, rng.randint(79, 159), "0123456789")
    return {
        "title": "sum of the digits",
        "statement": "The input is a large positive integer written in decimal. Add up all "
                     "of its digits. Answer with the integer.",
        "input": digits,
        "answer_format": "integer",
        "answer": sum(int(d) for d in digits),
    }


# --------------------------------------------------------------------------
# orange belt: small computation

def _nth_prime(rng):
    n = rng.randint(1, 500)
    flags = _sieve(4000)  # the 500th prime is 3571
    primes = [i for i, f in enumerate(flags) if f]
    return {
        "title": "the N-th prime",
        "statement": f"The input is a positive integer N. Find the N-th prime number, "
                     f"counting 2 as the 1st prime, 3 as the 2nd, 5 as the 3rd and so on. "
                     f"Answer with the integer.",
        "input": str(n),
        "answer_format": "integer",
        "answer": primes[n - 1],
    }


def _collatz_steps(rng):
    start = rng.randint(2, 500_000)
    x, steps = start, 0
    while x != 1:
        x = x // 2 if x % 2 == 0 else 3 * x + 1
        steps += 1
    return {
        "title": "Collatz steps to 1",
        "statement": "The input is a positive integer s. Repeatedly apply the rule: if the "
                     "number is even divide it by 2, otherwise replace it by 3 times the "
                     "number plus 1, until the number becomes 1. Count how many times the "
                     "rule was applied (for s = 1 the count is 0). Answer with the integer.",
        "input": str(start),
        "answer_format": "integer",
        "answer": steps,
    }


def _program_templates(rng):
    """Short deterministic programs printing one integer, built from a few
    parameterised templates. Each returns source text."""
    a, m, k = rng.randint(1, 50), rng.randint(2, 9), rng.randint(2, 7)
    n = rng.randint(20, 200)
    s = _token(rng, rng.randint(12, 30), _LOWER)
    return [
        (
            f"total = {a}\n"
            f"for i in range(1, {n} + 1):\n"
            f"    if i % {m} == 0:\n"
            f"        total += i * {k}\n"
            f"    else:\n"
            f"        total -= i\n"
            f"print(total)\n"
        ),
        (
            f"xs = [(i * i + {a}) % {m * 7} for i in range({n})]\n"
            f"evens = [x for x in xs if x % 2 == 0]\n"
            f"print(sum(evens) + len(evens))\n"
        ),
        (
            f"s = \"{s}\"\n"
            f"count = 0\n"
            f"for i, c in enumerate(s):\n"
            f"    if c in \"aeiou\":\n"
            f"        count += i + {k}\n"
            f"print(count)\n"
        ),
        (
            f"t = 0\n"
            f"for i in range({rng.randint(10, 60)}):\n"
            f"    for j in range(i):\n"
            f"        t += (i ^ j) % {m}\n"
            f"print(t)\n"
        ),
        (
            f"x = {rng.randint(100, 5000)}\n"
            f"n = 0\n"
            f"while x > 1 and n < 100:\n"
            f"    x = x // {k} if x % {k} == 0 else abs(x - {m})\n"
            f"    n += 1\n"
            f"print(x * 1000 + n)\n"
        ),
        (
            f"xs = [({a} * i + {k}) % {m * 5 + 1} for i in range({n})]\n"
            f"best = xs[0]\n"
            f"for v in xs:\n"
            f"    if v > best:\n"
            f"        best = v\n"
            f"print(best * len(xs) - sum(xs))\n"
        ),
    ]


def _program_output(rng):
    templates = _program_templates(rng)
    code = rng.choice(templates)
    return {
        "title": "what does this program print",
        "statement": "The input is a short Python 3 program with no imports. It is "
                     "deterministic and prints exactly one integer. Determine what it "
                     "prints. Answer with the integer.",
        "input": code,
        "answer_format": "integer",
        "answer": _run_program(code),
    }


def _recurrence_sum(rng):
    a1, a2 = rng.randint(1, 100), rng.randint(1, 100)
    p, q, n = rng.randint(2, 9), rng.randint(1, 9), rng.randint(100, 3000)
    prev, cur, total = a1, a2, (a1 + a2) % MOD
    for _ in range(3, n + 1):
        prev, cur = cur, (p * cur + q * prev) % MOD
        total = (total + cur) % MOD
    return {
        "title": "sum of a recurrence",
        "statement": f"A sequence is defined by a(1) = {a1}, a(2) = {a2}, and for every "
                     f"n >= 3: a(n) = ({p} * a(n-1) + {q} * a(n-2)) mod {MOD}. The input is "
                     f"the term count N. Compute (a(1) + a(2) + ... + a(N)) mod {MOD}. "
                     f"Answer with the integer.",
        "input": str(n),
        "answer_format": "integer",
        "answer": total,
    }


# --------------------------------------------------------------------------
# green belt: needs a machine

def _pow_nonce(rng):
    prefix = _token(rng, 8)
    zeros = rng.choice((3, 4))
    target = "0" * zeros
    n = 0
    while not hashlib.sha256(f"{prefix}{n}".encode("ascii")).hexdigest().startswith(target):
        n += 1
    return {
        "title": "find the proof-of-work nonce",
        "statement": f"The input is an 8-character prefix. Find the smallest non-negative "
                     f"integer n such that the SHA-256 hex digest of the ASCII string formed "
                     f"by the prefix immediately followed by n in decimal (no separator, no "
                     f"leading zeros, no newline) starts with {zeros} zero characters "
                     f"(\"{target}\"). Answer with the nonce n as an integer.",
        "input": prefix,
        "answer_format": "integer",
        "answer": n,
    }


def _prime_count(rng):
    limit = rng.randint(1_000, 200_000)
    flags = _sieve(limit - 1)
    return {
        "title": "count the primes below N",
        "statement": "The input is a positive integer N. Count how many prime numbers are "
                     "strictly less than N. Answer with the integer.",
        "input": str(limit),
        "answer_format": "integer",
        "answer": sum(flags),
    }


def _sha256_hex(rng):
    s = _token(rng, rng.randint(8, 32), _ALNUM + "ABCDEFGHIJKLMNOPQRSTUVWXYZ-_")
    return {
        "title": "SHA-256 of a string",
        "statement": "The input is a single ASCII string. Compute the SHA-256 digest of its "
                     "ASCII bytes exactly as given (no trailing newline). Answer with the "
                     "64-character lowercase hex digest.",
        "input": s,
        "answer_format": "hex",
        "answer": hashlib.sha256(s.encode("ascii")).hexdigest(),
    }


# --------------------------------------------------------------------------
# blue belt: fix the code

# Each template: name, intended behaviour, correct source, buggy source, input maker.
# The buggy source differs from the correct one by exactly one edit.

def _ints(rng, lo, hi, n):
    return [rng.randint(lo, hi) for _ in range(n)]


def _dot_mod_args(rng):
    n = rng.randint(5, 12)
    return _ints(rng, 1, 40, n), _ints(rng, 1, 40, n), rng.randint(50, 999)


_BLUE_TEMPLATES = (
    {
        "fname": "sum_to_n",
        "intent": "return the sum of all integers from 1 to n inclusive",
        "correct": (
            "def sum_to_n(n):\n"
            "    total = 0\n"
            "    for i in range(1, n + 1):\n"
            "        total += i\n"
            "    return total\n"
        ),
        "buggy": (
            "def sum_to_n(n):\n"
            "    total = 0\n"
            "    for i in range(1, n):\n"
            "        total += i\n"
            "    return total\n"
        ),
        "args": lambda rng: (rng.randint(10, 500),),
    },
    {
        "fname": "count_evens",
        "intent": "return how many of the integers in the list xs are even",
        "correct": (
            "def count_evens(xs):\n"
            "    count = 0\n"
            "    for x in xs:\n"
            "        if x % 2 == 0:\n"
            "            count += 1\n"
            "    return count\n"
        ),
        "buggy": (
            "def count_evens(xs):\n"
            "    count = 0\n"
            "    for x in xs:\n"
            "        if x % 2 != 0:\n"
            "            count += 1\n"
            "    return count\n"
        ),
        "args": lambda rng: (_ints(rng, -50, 50, rng.randint(7, 15)),),
    },
    {
        "fname": "longest_run",
        "intent": "return the length of the longest run of equal consecutive elements "
                  "in the non-empty list xs (for [1, 1, 2] the answer is 2)",
        "correct": (
            "def longest_run(xs):\n"
            "    best = 1\n"
            "    cur = 1\n"
            "    for i in range(1, len(xs)):\n"
            "        if xs[i] == xs[i - 1]:\n"
            "            cur += 1\n"
            "        else:\n"
            "            cur = 1\n"
            "        if cur > best:\n"
            "            best = cur\n"
            "    return best\n"
        ),
        "buggy": (
            "def longest_run(xs):\n"
            "    best = 1\n"
            "    cur = 1\n"
            "    for i in range(1, len(xs)):\n"
            "        if xs[i] == xs[i - 1]:\n"
            "            cur += 1\n"
            "        else:\n"
            "            cur = 0\n"
            "        if cur > best:\n"
            "            best = cur\n"
            "    return best\n"
        ),
        "args": lambda rng: (_ints(rng, 1, 3, rng.randint(10, 20)),),
    },
    {
        "fname": "dot_mod",
        "intent": "return the sum over i of xs[i] * ys[i], taken modulo m (xs and ys have "
                  "the same length, m is positive)",
        "correct": (
            "def dot_mod(xs, ys, m):\n"
            "    acc = 0\n"
            "    for i in range(len(xs)):\n"
            "        acc += xs[i] * ys[i]\n"
            "    return acc % m\n"
        ),
        "buggy": (
            "def dot_mod(xs, ys, m):\n"
            "    acc = 0\n"
            "    for i in range(len(xs)):\n"
            "        acc += xs[i] + ys[i]\n"
            "    return acc % m\n"
        ),
        "args": _dot_mod_args,
    },
    {
        "fname": "odd_product",
        "intent": "return the product of all odd integers from 1 to n inclusive",
        "correct": (
            "def odd_product(n):\n"
            "    prod = 1\n"
            "    for i in range(1, n + 1, 2):\n"
            "        prod *= i\n"
            "    return prod\n"
        ),
        "buggy": (
            "def odd_product(n):\n"
            "    prod = 1\n"
            "    for i in range(1, n, 2):\n"
            "        prod *= i\n"
            "    return prod\n"
        ),
        "args": lambda rng: (rng.randint(3, 25),),
    },
    {
        "fname": "first_min_index",
        "intent": "return the index of the smallest element of the non-empty list xs, "
                  "choosing the first occurrence if the smallest value repeats",
        "correct": (
            "def first_min_index(xs):\n"
            "    best = 0\n"
            "    for i in range(1, len(xs)):\n"
            "        if xs[i] < xs[best]:\n"
            "            best = i\n"
            "    return best\n"
        ),
        "buggy": (
            "def first_min_index(xs):\n"
            "    best = 0\n"
            "    for i in range(1, len(xs)):\n"
            "        if xs[i] <= xs[best]:\n"
            "            best = i\n"
            "    return best\n"
        ),
        "args": lambda rng: (_ints(rng, 1, 6, rng.randint(8, 16)),),
    },
    {
        "fname": "max_prefix_sum",
        "intent": "return the largest sum of any prefix of xs, where the empty prefix "
                  "counts and has sum 0 (so the result is never negative)",
        "correct": (
            "def max_prefix_sum(xs):\n"
            "    best = 0\n"
            "    acc = 0\n"
            "    for x in xs:\n"
            "        acc += x\n"
            "        if acc > best:\n"
            "            best = acc\n"
            "    return best\n"
        ),
        "buggy": (
            "def max_prefix_sum(xs):\n"
            "    best = xs[0]\n"
            "    acc = 0\n"
            "    for x in xs:\n"
            "        acc += x\n"
            "        if acc > best:\n"
            "            best = acc\n"
            "    return best\n"
        ),
        "args": lambda rng: (_ints(rng, -30, 30, rng.randint(6, 14)),),
    },
)


def _call_text(fname, args):
    return f"{fname}({', '.join(repr(a) for a in args)})"


def _fix_the_bug(rng):
    t = rng.choice(_BLUE_TEMPLATES)
    for _ in range(1000):
        args = t["args"](rng)
        correct = _run_function(t["correct"], t["fname"], args)
        buggy = _run_function(t["buggy"], t["fname"], args)
        if buggy != correct:
            break
    else:  # pragma: no cover - every template differs on almost all inputs
        raise RiddleGenError(f"could not find a distinguishing input for {t['fname']}")
    assert buggy != correct
    call = _call_text(t["fname"], args)
    return {
        "title": f"fix {t['fname']}",
        "statement": f"The input is a Python 3 function that is meant to {t['intent']}. "
                     f"It contains exactly one bug: an off-by-one, a wrong operator, or a "
                     f"wrong initial value. Fix the bug, then evaluate the corrected function "
                     f"for the call `{call}`. Answer with the integer it returns.",
        "input": t["buggy"],
        "answer_format": "integer",
        "answer": int(correct),
    }


# --------------------------------------------------------------------------
# registry

_KINDS = {
    "white": {
        "sum_lines": _sum_lines,
        "count_letter": _count_letter,
        "max_int": _max_int,
        "longest_word": _longest_word,
    },
    "yellow": {
        "reverse_string": _reverse_string,
        "caesar_decode": _caesar_decode,
        "xor_bytes": _xor_bytes,
        "digit_sum": _digit_sum,
    },
    "orange": {
        "nth_prime": _nth_prime,
        "collatz_steps": _collatz_steps,
        "program_output": _program_output,
        "recurrence_sum": _recurrence_sum,
    },
    "green": {
        "pow_nonce": _pow_nonce,
        "prime_count": _prime_count,
        "sha256_hex": _sha256_hex,
    },
    "blue": {
        "fix_the_bug": _fix_the_bug,
    },
}
assert tuple(_KINDS) == BELTS

PACKS = ("classic", "qubic", "mixed")
_ALL_KINDS = {belt: {**table, **qubic_riddles.KINDS.get(belt, {})} for belt, table in _KINDS.items()}
_KIND_BELT = {kind: belt for belt, table in _ALL_KINDS.items() for kind in table}


def kinds(belt: str, *, pack: str = "classic") -> list[str]:
    """The kind names available at `belt`, in a stable order."""
    if belt not in _KINDS:
        raise RiddleGenError(f"unknown belt {belt!r}; expected one of {BELTS}")
    if pack not in PACKS:
        raise RiddleGenError(f"unknown riddle pack {pack!r}; expected one of {PACKS}")
    table = {"classic": _KINDS, "qubic": qubic_riddles.KINDS, "mixed": _ALL_KINDS}[pack]
    return list(table.get(belt, {}))


def generate_kind(kind: str, rng: random.Random, round_id: int) -> dict:
    """Generate one riddle of `kind`. Deterministic for a given rng state."""
    if kind not in _KIND_BELT:
        raise RiddleGenError(f"unknown riddle kind {kind!r}")
    belt = _KIND_BELT[kind]
    body = _ALL_KINDS[belt][kind](rng)
    title = f"{belt.capitalize()} belt: {body['title']}"
    if len(title) > 120:
        raise RiddleGenError(f"title too long: {title!r}")
    answer = body["answer"]
    fmt = body["answer_format"]
    # The answer must be exactly what the house will canonicalise to.
    if hashing.canonical_answer(answer, fmt) != str(answer):
        raise RiddleGenError(f"answer {answer!r} is not canonical under {fmt}")
    return {
        "round_id": round_id,
        "title": title,
        "statement": body["statement"],
        "input": body["input"],
        "answer_format": fmt,
        "answer": answer,
        "belt": belt,
        "kind": kind,
    }


def generate(belt: str, rng: random.Random, round_id: int, *, pack: str = "classic") -> dict:
    """Generate a riddle for `belt`, picking a kind uniformly with `rng`.

    Returns {"round_id", "title", "statement", "input", "answer_format",
    "answer", "belt", "kind"}. Deterministic for a given (belt, rng state,
    round_id)."""
    pool = kinds(belt, pack=pack)
    if not pool:
        raise RiddleGenError(f"no riddles for belt {belt!r} in pack {pack!r}")
    kind = rng.choice(pool)
    return generate_kind(kind, rng, round_id)
