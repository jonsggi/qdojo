#!/usr/bin/env python3
"""Reproduce the QDOJO checks inside Qubic's own tooling (see README.md).

  core_harness.py verify       qubic/contract-verify (the checker Core's CI pins) on QDOJO.h,
                               plus negative controls that prove the tool parses the whole file
  core_harness.py test         core-lite's GoogleTest harness (Linux/clang): build
                               test/contract_qdojo.cpp and replay every journal
  core_harness.py core-syntax  pinned qubic/core: clang syntax-only compile of the same test;
                               reports errors attributable to QDOJO.h / the test (Core's own
                               test build is MSVC-only, so Core headers do not compile on Linux)
  core_harness.py all          verify, test, core-syntax

Options: --work DIR (default $QDOJO_QUBIC_WORK or /tmp/qdojo-qubic), --jobs N (default 1).
Needs git, cmake, ninja, clang >= 18, nasm, flex, clang-tidy (CppParser's build runs it).
Nothing here touches a network node or a seed.
"""
import argparse
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
JOURNALS = os.path.join(REPO, "packages", "qdojo", "tests", "combat", "fixtures", "contract")
PORT_DIR = os.path.join(REPO, "contracts", "combat_contract")

CORE = ("https://github.com/qubic/core.git", "e3ef766686e5d69a2bdd17a12213f1d21d145778")
CORE_LITE = ("https://github.com/qubic/core-lite.git", "5ad97af4b1ccb077580a39abfbe1891783d93c78")
VERIFY = ("https://github.com/qubic/contract-verify.git", "970ce102d56df53b68f1b8fa65b2dd445d5c9d81")
CPPPARSER = ("https://github.com/satya-das/cppparser.git", "3b5801f7389fcad3b8b1865d5ca10b1141d1c9e5")


def run(cmd, cwd=None, env=None, check=True, log=None):
    print("+", " ".join(cmd), f"(in {cwd})" if cwd else "", flush=True)
    if log:
        with open(log, "w") as f:
            r = subprocess.run(cmd, cwd=cwd, env=env, stdout=f, stderr=subprocess.STDOUT)
    else:
        r = subprocess.run(cmd, cwd=cwd, env=env)
    if check and r.returncode != 0:
        sys.exit(f"command failed ({r.returncode}): {' '.join(cmd)}" + (f"; see {log}" if log else ""))
    return r.returncode


def fetch(url, sha, dst):
    """Shallow checkout of exactly `sha` into dst (idempotent)."""
    if os.path.isdir(os.path.join(dst, ".git")):
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=dst, capture_output=True, text=True).stdout.strip()
        if head == sha:
            return
    os.makedirs(dst, exist_ok=True)
    run(["git", "init", "-q"], cwd=dst)
    subprocess.run(["git", "remote", "remove", "origin"], cwd=dst, capture_output=True)
    run(["git", "remote", "add", "origin", url], cwd=dst)
    run(["git", "fetch", "-q", "--depth", "1", "origin", sha], cwd=dst)
    run(["git", "checkout", "-q", "--force", "FETCH_HEAD"], cwd=dst)


def register(core_dir):
    """Register QDOJO in contract_def.h (line endings kept) and add a qdojo-only test target."""
    p = os.path.join(core_dir, "src", "contract_core", "contract_def.h")
    s = open(p, "rb").read().decode()
    if "QDOJO" not in s:
        nl = "\r\n" if "\r\n" in s else "\n"
        fix = lambda t: t.replace("\n", nl)
        edits = [
            ("#endif\n\n// new contracts should be added above this line\n\n#ifdef INCLUDE_CONTRACT_TEST_EXAMPLES\n",
             "#endif\n\n#undef CONTRACT_INDEX\n#undef CONTRACT_STATE_TYPE\n#undef CONTRACT_STATE2_TYPE\n\n"
             "#ifndef NO_QTREAT\n#define QDOJO_CONTRACT_INDEX (QTREAT_CONTRACT_INDEX + 1)\n"
             "#else\n#define QDOJO_CONTRACT_INDEX (QPAYHUB_CONTRACT_INDEX + 1)\n#endif\n"
             "#define CONTRACT_INDEX QDOJO_CONTRACT_INDEX\n#define CONTRACT_STATE_TYPE QDOJO\n"
             "#define CONTRACT_STATE2_TYPE QDOJO2\n#include \"contracts/QDOJO.h\"\n\n"
             "// new contracts should be added above this line\n\n#ifdef INCLUDE_CONTRACT_TEST_EXAMPLES\n"),
            ("    {\"QTREAT\", 233, 10000, sizeof(QTREAT::StateData)}, // proposal in epoch 231, IPO in 232, construction and first use in 233\n#endif\n",
             None),
            ("    REGISTER_CONTRACT_FUNCTIONS_AND_PROCEDURES(QTREAT);\n#endif\n", None),
        ]
        a, b = edits[0]
        assert s.count(fix(a)) == 1, "contract_def.h anchor 1 not found"
        s = s.replace(fix(a), fix(b))
        a = edits[1][0]
        assert s.count(fix(a)) == 1, "contract_def.h anchor 2 not found"
        s = s.replace(fix(a), fix(a + "    {\"QDOJO\", 240, 10000, sizeof(QDOJO::StateData)}, // qdojo combat (local test build only; not proposed)\n"))
        a = edits[2][0]
        assert s.count(fix(a)) == 1, "contract_def.h anchor 3 not found"
        s = s.replace(fix(a), fix(a + "    REGISTER_CONTRACT_FUNCTIONS_AND_PROCEDURES(QDOJO);\n"))
        open(p, "wb").write(s.encode())
    lite = os.path.exists(os.path.join(core_dir, "src", "platform", "msvc_polyfill.h"))
    p = os.path.join(core_dir, "test", "CMakeLists.txt")
    s = open(p).read()
    if "qdojo_core_tests" not in s:
        if lite:
            s += """
# ---- qdojo: a separate target so only the QDOJO contract test is compiled ----
# Same flags as qubic_core_tests in core-lite, minus -w so warnings stay visible.
# common_def.cpp defines the Core globals, stdlib_impl.cpp the NO_UEFI memory helpers.
add_executable(qdojo_core_tests contract_qdojo.cpp common_def.cpp stdlib_impl.cpp)
target_compile_options(qdojo_core_tests PRIVATE -include "${LOGGING_VM_TEST_CONFIG}")
apply_test_compiler_flags(qdojo_core_tests)
target_compile_options(qdojo_core_tests PRIVATE -mrdrnd -Wno-error -mbmi -mlzcnt -fshort-wchar)
"""
        else:
            s += """
# ---- qdojo: a separate target so only the QDOJO contract test is compiled ----
add_executable(qdojo_core_tests contract_qdojo.cpp)
apply_test_compiler_flags(qdojo_core_tests)
target_compile_options(qdojo_core_tests PRIVATE -mrdrnd)
"""
        s += """if(QDOJO_PORT_DIR)
  target_include_directories(qdojo_core_tests PRIVATE ${QDOJO_PORT_DIR})
  target_compile_definitions(qdojo_core_tests PRIVATE QDOJO_LOCKSTEP_PORT=1)
endif()
target_link_libraries(qdojo_core_tests PRIVATE GTest::gtest_main platform_common platform_os%s)
""" % (" Blosc2::blosc2_static" if lite else "")
        open(p, "w").write(s)


def install(core_dir):
    register(core_dir)
    for src, dst in (("QDOJO.h", "src/contracts/QDOJO.h"), ("test_qdojo_core.cpp", "test/contract_qdojo.cpp")):
        data = open(os.path.join(HERE, src)).read()
        open(os.path.join(core_dir, dst), "w").write(data)


def configure(core_dir, build, lite):
    cmd = ["cmake", "-S", core_dir, "-B", build, "-G", "Ninja", "-DCMAKE_C_COMPILER=clang",
           "-DCMAKE_CXX_COMPILER=clang++", "-DBUILD_TESTS:BOOL=ON", "-DCMAKE_BUILD_TYPE=Release",
           "-DENABLE_AVX512=ON", "-DUSE_SANITIZER=OFF", f"-DQDOJO_PORT_DIR={PORT_DIR}"]
    cmd += ["-DBUILD_BINARY:BOOL=OFF", "-DANT_WALKER=OFF"] if lite else ["-DBUILD_EFI:BOOL=OFF"]
    run(cmd, log=os.path.join(build, "..", "cmake-" + os.path.basename(build) + ".log"))


def cmd_verify(work, jobs):
    d = os.path.join(work, "contract-verify")
    fetch(*VERIFY, d)
    fetch(*CPPPARSER, os.path.join(d, "deps", "CppParser"))
    b1 = os.path.join(d, "deps", "CppParser", "builds")
    if not os.path.exists(os.path.join(b1, "CMakeCache.txt")):
        os.makedirs(b1, exist_ok=True)
        run(["cmake", "-DCMAKE_BUILD_TYPE=Release", ".."], cwd=b1, log=os.path.join(work, "cppparser-cmake.log"))
    run(["cmake", "--build", ".", "--config", "Release", f"-j{jobs}"], cwd=b1, log=os.path.join(work, "cppparser-build.log"))
    b2 = os.path.join(d, "build")
    os.makedirs(b2, exist_ok=True)
    run(["cmake", "-DCMAKE_BUILD_TYPE=Release", "-DBUILD_CONTRACTVERIFY_TESTS:BOOL=OFF", ".."], cwd=b2,
        log=os.path.join(work, "verify-cmake.log"))
    run(["cmake", "--build", ".", "--config", "Release", f"-j{jobs}"], cwd=b2, log=os.path.join(work, "verify-build.log"))
    tool = os.path.join(b2, "src", "contractverify")
    src = os.path.join(HERE, "QDOJO.h")
    print("contract-verify on QDOJO.h:", flush=True)
    rc = run([tool, src], check=False)
    t = open(src).read()
    negatives = {
        "division in an engine helper": ("c.fs_st = uint16(out.stamina + c.fs_gain);",
                                         "c.fs_st = uint16(out.stamina + c.fs_gain / 2);"),
        "local variable in emit": ("        s.eventSeq += 1;\n        shaInit(c.sha);",
                                   "        uint32 z = 0;\n        s.eventSeq += 1;\n        shaInit(c.sha);"),
        "brackets in a query": ("            output.count += 1;\n            locals.seq += 1;",
                                "            output.count += 1;\n            locals.seq += locals.oldest[0];"),
        "string literal in the last function": ("output.status = 2;", "output.status = sizeof(\"x\");"),
        "modulo in the cup code": ("c.lr_size *= 2;", "c.lr_size = c.lr_size % 7;"),
        "pointer in the END_TICK helper": ("        s.lastServiced = t;\n    }", "        s.lastServiced = *(&t);\n    }"),
    }
    missed = 0
    for name, (a, b) in negatives.items():
        p = os.path.join(work, "negative.h")
        open(p, "w").write(t.replace(a, b, 1))
        r = subprocess.run([tool, p], capture_output=True, text=True)
        ok = r.returncode != 0
        missed += 0 if ok else 1
        print(f"  negative control ({name}): {'rejected' if ok else 'NOT REJECTED'}")
    if rc != 0 or missed:
        sys.exit("verify: FAILED")
    print("verify: QDOJO.h PASSED; all negative controls rejected")


def cmd_test(work, jobs):
    d = os.path.join(work, "core-lite")
    fetch(*CORE_LITE, d)
    install(d)
    build = os.path.join(work, "build-core-lite")
    os.makedirs(build, exist_ok=True)
    configure(d, build, True)
    run(["ninja", f"-j{jobs}", "qdojo_core_tests"], cwd=build, log=os.path.join(work, "build-core-lite.log"))
    env = dict(os.environ, QDOJO_JOURNAL_DIR=JOURNALS)
    rc = run([os.path.join(build, "test", "qdojo_core_tests")], cwd=build, env=env, check=False)
    if rc != 0:
        sys.exit("test: FAILED")


def cmd_core_syntax(work, jobs):
    d = os.path.join(work, "core")
    fetch(*CORE, d)
    install(d)
    build = os.path.join(work, "build-core")
    os.makedirs(build, exist_ok=True)
    configure(d, build, False)
    run(["ninja", f"-j{jobs}", "gtest_main"], cwd=build, log=os.path.join(work, "build-core-gtest.log"))
    cmds = subprocess.run(["ninja", "-t", "commands", "qdojo_core_tests"], cwd=build, capture_output=True,
                          text=True).stdout.splitlines()
    line = [c for c in cmds if "contract_qdojo.cpp" in c and " -c " in c][0]
    args = line.split()
    out = []
    skip = False
    for i, a in enumerate(args):
        if skip:
            skip = False
            continue
        if a in ("-o", "-MT", "-MF"):
            skip = True
            continue
        if a in ("-MD", "-Werror"):
            continue
        out.append(a)
    out += ["-fsyntax-only", "-ferror-limit=0", "-Wno-error"]
    log = os.path.join(work, "core-syntax.log")
    run(out, cwd=build, check=False, log=log)
    text = open(log).read().splitlines()
    errors = [l for l in text if ": error:" in l]
    ours = [l for l in errors if "QDOJO.h:" in l or "contract_qdojo.cpp:" in l]
    warn = [l for l in text if "QDOJO.h:" in l and ": warning:" in l]
    print(f"core-syntax: {len(errors)} errors in total, {len(ours)} in QDOJO.h or the test, "
          f"{len(warn)} warnings in QDOJO.h (log: {log})")
    for l in ours[:20]:
        print("  ", l)
    if ours:
        sys.exit("core-syntax: FAILED")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("what", choices=["verify", "test", "core-syntax", "all"])
    ap.add_argument("--work", default=os.environ.get("QDOJO_QUBIC_WORK", "/tmp/qdojo-qubic"))
    ap.add_argument("--jobs", type=int, default=1)
    a = ap.parse_args()
    os.makedirs(a.work, exist_ok=True)
    if a.what in ("verify", "all"):
        cmd_verify(a.work, a.jobs)
    if a.what in ("test", "all"):
        cmd_test(a.work, a.jobs)
    if a.what in ("core-syntax", "all"):
        cmd_core_syntax(a.work, a.jobs)


if __name__ == "__main__":
    main()
