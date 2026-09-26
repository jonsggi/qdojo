// Test runner for the combat-v1 C++ core. The standard library is allowed
// here only; combat_core.h and sha256.h stay free of it.
//
//   test_combat_core [repo_root]     (default: current directory)
//
// Checks: compiled constants == docs/combat-v1.json (and its ruleset digest),
// every hand vector of docs/combat.md section 8, NIST SHA-256 vectors, the
// frozen commitment vector, and all fights in
// packages/qdojo/tests/combat/fixtures/fights-*.json. Exits nonzero on any
// mismatch.
#include "combat_core.h"
#include "sha256.h"

#include <cstdio>
#include <cstring>
#include <dirent.h>
#include <fstream>
#include <map>
#include <sstream>
#include <string>
#include <vector>

using namespace qdojo_combat;

static int g_checks = 0, g_fail = 0;

#define CHECK(cond, ...)                                                    \
    do {                                                                    \
        ++g_checks;                                                         \
        if (!(cond)) {                                                      \
            ++g_fail;                                                       \
            if (g_fail <= 40) {                                             \
                std::fprintf(stderr, "FAIL %s:%d: ", __FILE__, __LINE__);   \
                std::fprintf(stderr, __VA_ARGS__);                          \
                std::fprintf(stderr, "\n");                                 \
            }                                                               \
        }                                                                   \
    } while (0)

// ------------------------------------------------------------ mini JSON
struct Json {
    enum Kind { NUL, BOOL, NUM, STR, ARR, OBJ } kind = NUL;
    bool b = false;
    long long n = 0;
    std::string s;
    std::vector<Json> a;
    std::map<std::string, Json> o;  // sorted keys: canonical order for free

    const Json& operator[](const std::string& k) const {
        static const Json null;
        auto it = o.find(k);
        return it == o.end() ? null : it->second;
    }
    const Json& operator[](size_t i) const { return a.at(i); }
    size_t size() const { return kind == ARR ? a.size() : o.size(); }
};

struct JsonParser {
    const char* p;
    const char* end;
    bool ok = true;

    void ws() { while (p < end && (*p == ' ' || *p == '\n' || *p == '\r' || *p == '\t')) ++p; }
    bool eat(char c) { ws(); if (p < end && *p == c) { ++p; return true; } return false; }
    void fail() { ok = false; p = end; }

    std::string str() {
        std::string r;
        if (!eat('"')) { fail(); return r; }
        while (p < end && *p != '"') {
            if (*p == '\\') {
                ++p;
                if (p >= end) { fail(); return r; }
                char c = *p++;
                switch (c) {
                    case 'n': r += '\n'; break;
                    case 't': r += '\t'; break;
                    case 'r': r += '\r'; break;
                    case 'b': r += '\b'; break;
                    case 'f': r += '\f'; break;
                    case 'u': fail(); return r;  // not used by our fixtures
                    default: r += c;
                }
            } else {
                r += *p++;
            }
        }
        if (p >= end) { fail(); return r; }
        ++p;
        return r;
    }

    Json value() {
        Json j;
        ws();
        if (p >= end) { fail(); return j; }
        char c = *p;
        if (c == '{') {
            ++p;
            j.kind = Json::OBJ;
            if (eat('}')) return j;
            do {
                std::string k = str();
                if (!eat(':')) { fail(); return j; }
                j.o[k] = value();
            } while (ok && eat(','));
            if (!eat('}')) fail();
        } else if (c == '[') {
            ++p;
            j.kind = Json::ARR;
            if (eat(']')) return j;
            do { j.a.push_back(value()); } while (ok && eat(','));
            if (!eat(']')) fail();
        } else if (c == '"') {
            j.kind = Json::STR;
            j.s = str();
        } else if (c == '-' || (c >= '0' && c <= '9')) {
            j.kind = Json::NUM;
            bool neg = c == '-';
            if (neg) ++p;
            if (p >= end || *p < '0' || *p > '9') { fail(); return j; }
            while (p < end && *p >= '0' && *p <= '9') j.n = j.n * 10 + (*p++ - '0');
            if (p < end && (*p == '.' || *p == 'e' || *p == 'E')) fail();  // integers only
            if (neg) j.n = -j.n;
        } else if (end - p >= 4 && !std::strncmp(p, "null", 4)) {
            p += 4;
        } else if (end - p >= 4 && !std::strncmp(p, "true", 4)) {
            p += 4; j.kind = Json::BOOL; j.b = true;
        } else if (end - p >= 5 && !std::strncmp(p, "false", 5)) {
            p += 5; j.kind = Json::BOOL;
        } else {
            fail();
        }
        return j;
    }
};

static bool read_file(const std::string& path, std::string& out) {
    std::ifstream f(path, std::ios::binary);
    if (!f) return false;
    std::ostringstream ss;
    ss << f.rdbuf();
    out = ss.str();
    return true;
}

static bool load_json(const std::string& path, Json& out) {
    std::string text;
    if (!read_file(path, text)) { std::fprintf(stderr, "cannot read %s\n", path.c_str()); return false; }
    JsonParser jp{text.data(), text.data() + text.size()};
    out = jp.value();
    jp.ws();
    if (!jp.ok || jp.p != jp.end) { std::fprintf(stderr, "cannot parse %s\n", path.c_str()); return false; }
    return true;
}

// Canonical JSON (protocol.md section 2): sorted keys, no whitespace.
static void canonical(const Json& j, std::string& out) {
    switch (j.kind) {
        case Json::NUL: out += "null"; break;
        case Json::BOOL: out += j.b ? "true" : "false"; break;
        case Json::NUM: out += std::to_string(j.n); break;
        case Json::STR: out += '"'; out += j.s; out += '"'; break;  // ASCII, no escapes needed
        case Json::ARR:
            out += '[';
            for (size_t i = 0; i < j.a.size(); ++i) { if (i) out += ','; canonical(j.a[i], out); }
            out += ']';
            break;
        case Json::OBJ: {
            out += '{';
            bool first = true;
            for (auto& kv : j.o) {
                if (!first) out += ',';
                first = false;
                out += '"'; out += kv.first; out += "\":";
                canonical(kv.second, out);
            }
            out += '}';
        }
    }
}

// ------------------------------------------------------------- hex utils
static std::string hex(const uint8_t* b, size_t n) {
    static const char* d = "0123456789abcdef";
    std::string s;
    for (size_t i = 0; i < n; ++i) { s += d[b[i] >> 4]; s += d[b[i] & 15]; }
    return s;
}

static std::vector<uint8_t> unhex(const std::string& s) {
    auto v = [](char c) -> int {
        if (c >= '0' && c <= '9') return c - '0';
        if (c >= 'a' && c <= 'f') return c - 'a' + 10;
        if (c >= 'A' && c <= 'F') return c - 'A' + 10;
        return -1;
    };
    std::vector<uint8_t> out;
    if (s.size() % 2) return out;
    for (size_t i = 0; i < s.size(); i += 2) {
        int hi = v(s[i]), lo = v(s[i + 1]);
        if (hi < 0 || lo < 0) return {};
        out.push_back(uint8_t(hi * 16 + lo));
    }
    return out;
}

static std::string sha_hex(const std::string& s) {
    uint8_t d[32];
    sha256(reinterpret_cast<const uint8_t*>(s.data()), uint32_t(s.size()), d);
    return hex(d, 32);
}

static std::string state_hex(const Fighter& f) {
    uint8_t b[8];
    encode_state(f, b);
    return hex(b, 8);
}

// ------------------------------------------------------------ constants
static void check_table(const std::string& path, const char* version, const RulesetTable& T) {
    Json r;
    if (!load_json(path, r)) { ++g_fail; return; }
    CHECK(r["semantic_version"].s == version, "semantic_version %s", r["semantic_version"].s.c_str());
    CHECK(r["rounds"].n == T.rounds, "rounds");
    CHECK(r["beats_per_round"].n == T.beats_per_round, "beats_per_round");
    CHECK(r["initial"]["hp"].n == T.initial_hp, "initial.hp");
    CHECK(r["initial"]["stamina"].n == T.initial_stamina, "initial.stamina");
    CHECK(r["initial"]["opening"].n == T.initial_opening, "initial.opening");
    CHECK(r["initial"]["guard_streak"].n == T.initial_guard_streak, "initial.guard_streak");
    CHECK(r["initial"]["power_available"].n == T.initial_power_available, "initial.power_available");
    CHECK(r["initial"].size() == 5 && r["limits"].size() == 3, "initial/limits key count");
    CHECK(r["limits"]["hp"].n == T.limit_hp, "limits.hp");
    CHECK(r["limits"]["stamina"].n == T.limit_stamina, "limits.stamina");
    CHECK(r["limits"]["guard_streak"].n == T.limit_guard_streak, "limits.guard_streak");
    static const char* names[ACTION_COUNT] = {"JAB", "KICK", "BLOCK", "DUCK", "THROW", "RECOVER", "EXHAUSTED"};
    CHECK(r["action_names"].size() == ACTION_COUNT, "action_names size");
    for (size_t i = 0; i < ACTION_COUNT && i < r["action_names"].size(); ++i)
        CHECK(r["action_names"][i].s == names[i], "action_names[%zu]", i);
    CHECK(r["submitted_action_ids"].size() == SUBMITTED_ACTION_COUNT, "submitted_action_ids size");
    for (size_t i = 0; i < r["submitted_action_ids"].size(); ++i)
        CHECK(r["submitted_action_ids"][i].n == (long long)i, "submitted_action_ids[%zu]", i);
    CHECK(r["base_costs"].size() == ACTION_COUNT, "base_costs size");
    for (size_t i = 0; i < ACTION_COUNT && i < r["base_costs"].size(); ++i)
        CHECK(r["base_costs"][i].n == T.base_costs[i], "base_costs[%zu]", i);
    CHECK(r["block_streak_cost"].n == T.block_streak_cost, "block_streak_cost");
    CHECK(r["block_strain"].n == T.block_strain, "block_strain");
    CHECK(r["ordinary_recovery"].n == T.ordinary_recovery, "ordinary_recovery");
    CHECK(r["recover_unhit"].n == T.recover_unhit, "recover_unhit");
    CHECK(r["recover_hit"].n == T.recover_hit, "recover_hit");
    CHECK(r["exhausted_recovery"].n == T.exhausted_recovery, "exhausted_recovery");
    CHECK(r["break_recovery"].n == T.break_recovery, "break_recovery");
    CHECK(r["opening_damage"].n == T.opening_damage, "opening_damage");
    CHECK(r["power_damage"].n == T.power_damage, "power_damage");
    CHECK(r["power_cost"].n == T.power_cost, "power_cost");
    CHECK(r["damage"].size() == ACTION_COUNT, "damage rows");
    for (size_t i = 0; i < ACTION_COUNT && i < r["damage"].size(); ++i) {
        CHECK(r["damage"][i].size() == ACTION_COUNT, "damage[%zu] cols", i);
        for (size_t k = 0; k < ACTION_COUNT && k < r["damage"][i].size(); ++k)
            CHECK(r["damage"][i][k].n == T.damage[i][k], "damage[%zu][%zu]", i, k);
    }
    // No key the core does not know about.
    CHECK(r.size() == 19, "%s has %zu top-level keys, core mirrors 19", path.c_str(), r.size());

    // Ruleset digest over canonical JSON equals the table's digest.
    std::string pre(TAG_RULES, sizeof(TAG_RULES));
    canonical(r, pre);
    uint8_t d[32];
    sha256(reinterpret_cast<const uint8_t*>(pre.data()), uint32_t(pre.size()), d);
    CHECK(hex(d, 32) == hex(T.digest, 32), "%s ruleset digest %s", version, hex(d, 32).c_str());
}

// Every compiled-in table, whichever one this build selected.
static void test_constants(const std::string& root) {
    check_table(root + "/docs/combat-v1.json", "combat-v1-candidate-1", CANDIDATE_1);
    check_table(root + "/docs/combat-v1-candidate-2.json", "combat-v1-candidate-2", CANDIDATE_2);
    CHECK(&RULES == (QDOJO_RULESET == 2 ? &CANDIDATE_2 : &CANDIDATE_1), "selected table");
}

// ----------------------------------------------------------- hand vectors
static Fighter F(uint16_t hp = INITIAL_HP, uint16_t st = INITIAL_STAMINA, uint8_t op = 0, uint8_t gs = 0, uint8_t pw = 1) {
    Fighter f;
    f.hp = hp; f.stamina = st; f.opening = op; f.guard_streak = gs; f.power_available = pw;
    return f;
}

static bool same4(const Fighter& f, int hp, int st, int op, int gs) {
    return f.hp == hp && f.stamina == st && f.opening == op && f.guard_streak == gs;
}

static BeatTrace beat(const Fighter& a, const Fighter& b, uint8_t ia, uint8_t ib, bool pa = false, bool pb = false) {
    BeatTrace t;
    std::memset(&t, 0, sizeof t);
    Error e = resolve_beat(a, b, ia, ib, pa, pb, t);
    CHECK(e == OK, "resolve_beat error %d", e);
    return t;
}

static Plan plan6(uint8_t x, uint8_t slot = NO_POWER_SLOT) {
    Plan p;
    for (auto& a : p.actions) a = x;
    p.power_slot = slot;
    return p;
}

#if QDOJO_RULESET == 1
static void test_hand_vectors() {
    struct Row { uint8_t a, b; int A[4], B[4]; };
    const Row table[] = {
        {JAB, BLOCK, {100, 56, 0, 0}, {100, 58, 0, 1}},
        {JAB, KICK, {86, 56, 0, 0}, {92, 50, 0, 0}},
        {DUCK, JAB, {100, 58, 1, 0}, {100, 56, 0, 0}},
        {KICK, DUCK, {100, 50, 0, 0}, {82, 58, 0, 0}},
        {THROW, BLOCK, {100, 53, 0, 0}, {86, 58, 0, 1}},
        {BLOCK, KICK, {100, 52, 0, 1}, {100, 50, 0, 0}},
        {RECOVER, JAB, {88, 60, 0, 0}, {100, 56, 1, 0}},
        {THROW, THROW, {100, 53, 0, 0}, {100, 53, 0, 0}},
    };
    for (const Row& r : table) {
        BeatTrace t = beat(F(), F(), r.a, r.b);
        CHECK(same4(t.a.after, r.A[0], r.A[1], r.A[2], r.A[3]), "table %d/%d A=%s", r.a, r.b, state_hex(t.a.after).c_str());
        CHECK(same4(t.b.after, r.B[0], r.B[1], r.B[2], r.B[3]), "table %d/%d B=%s", r.a, r.b, state_hex(t.b.after).c_str());
        CHECK(!t.terminal, "table not terminal");
    }

    {  // DUCK/JAB then KICK/JAB
        BeatTrace t1 = beat(F(), F(), DUCK, JAB);
        BeatTrace t2 = beat(t1.a.after, t1.b.after, KICK, JAB);
        CHECK(same4(t2.a.after, 92, 48, 0, 0), "duck-then-kick A");
        CHECK(same4(t2.b.after, 82, 52, 0, 0), "duck-then-kick B");
        CHECK(t2.a.dealt == 18 && t2.a.base == 14 && t2.a.opening_bonus == 4, "kick dealt 18 via opening");
        CHECK(t2.a.reasons & R_OPENING_USED, "opening used reason");
    }
    {  // stamina 11 KICK vs JAB -> EXHAUSTED
        BeatTrace t = beat(F(100, 11), F(), KICK, JAB);
        CHECK(t.a.effective == EXHAUSTED && t.a.cost == 12 && t.a.cost_paid == 0, "exhausted kick");
        CHECK(t.a.reasons & R_INSUFFICIENT_STAMINA, "insufficient stamina reason");
        CHECK(same4(t.a.after, 88, 17, 0, 0), "exhausted A");
        CHECK(same4(t.b.after, 100, 56, 1, 0), "exhausted B");
    }
    {  // stamina 12 KICK executes -> 2 (vs BLOCK: no damage, no strain on kicker)
        BeatTrace t = beat(F(100, 12), F(), KICK, BLOCK);
        CHECK(t.a.effective == KICK && t.a.after.stamina == 2, "kick at 12 -> %d", t.a.after.stamina);
    }
    {  // opening=1 powered KICK into DUCK
        BeatTrace t = beat(F(100, 60, 1), F(), KICK, DUCK, true, false);
        CHECK(t.a.after.stamina == 46 && t.a.after.power_available == 0, "powered kick A");
        CHECK(t.b.lost == 26 && t.b.after.hp == 74 && t.a.lost == 0, "powered kick damage");
        CHECK((t.a.reasons & R_POWER_USED) && (t.a.reasons & R_OPENING_USED), "powered kick reasons");
    }
    {  // powered JAB into BLOCK
        BeatTrace t = beat(F(), F(), JAB, BLOCK, true, false);
        CHECK(t.a.after.stamina == 52 && t.a.after.power_available == 0, "powered jab A");
        CHECK(t.a.lost == 0 && t.b.lost == 0, "powered jab no hp loss");
        CHECK(t.a.reasons & R_POWER_WASTED, "power wasted reason");
    }
    {  // stamina 9 powered JAB into JAB -> EXHAUSTED
        BeatTrace t = beat(F(100, 9), F(), JAB, JAB, true, false);
        CHECK(t.a.cost == 10 && t.a.effective == EXHAUSTED, "powered jab cost 10 exhausted");
        CHECK(t.a.lost == 12 && t.a.after.stamina == 15 && t.a.after.power_available == 0, "powered exhausted A");
    }
    {  // four BLOCKs vs RECOVER, fifth costs 13
        Fighter a = F(), b = F();
        const int st[4] = {58, 53, 45, 34}, gs[4] = {1, 2, 3, 3};
        for (int i = 0; i < 4; ++i) {
            BeatTrace t = beat(a, b, BLOCK, RECOVER);
            a = t.a.after; b = t.b.after;
            CHECK(a.stamina == st[i] && a.guard_streak == gs[i], "block chain %d: %d/%d", i, a.stamina, a.guard_streak);
        }
        CHECK(action_cost(BLOCK, a.guard_streak, false) == 13, "fifth block costs 13");
        BeatTrace t = beat(a, b, BLOCK, RECOVER);
        CHECK(t.a.cost_paid == 13, "fifth block paid 13");
    }
    {  // BLOCK at 4 into KICK
        BeatTrace t = beat(F(100, 4), F(), BLOCK, KICK);
        CHECK(t.a.effective == BLOCK && t.a.cost_paid == 4 && t.a.strain == 0, "block at 4");
        CHECK(t.a.after.stamina == 2 && t.a.after.hp == 100 && t.a.after.guard_streak == 1, "block at 4 after");
        CHECK(t.a.reasons & R_GUARD_STRAIN, "guard strain reason");
        CHECK(action_cost(BLOCK, t.a.after.guard_streak, false) == 7, "next block costs 7");
        BeatTrace t2 = beat(t.a.after, t.b.after, BLOCK, RECOVER);
        CHECK(t2.a.effective == EXHAUSTED, "next block unaffordable");
    }
    {  // HP 8 both JAB -> double KO
        BeatTrace t = beat(F(8), F(8), JAB, JAB);
        CHECK(t.terminal && t.a.dealt == 8 && t.b.dealt == 8 && t.a.after.hp == 0 && t.b.after.hp == 0, "double KO");
        CHECK((t.a.reasons & R_DOUBLE_KO) && (t.b.reasons & R_DOUBLE_KO), "double KO reasons");
    }
    {  // A HP 14 JAB / B HP 8 KICK -> double KO (via resolve_round)
        FightState s = new_fight();
        s.a.hp = 14; s.b.hp = 8;
        RoundResult rr;
        CHECK(resolve_round(s, plan6(JAB), plan6(KICK), rr) == OK, "round ok");
        CHECK(rr.executed == 1 && rr.end.outcome == OUTCOME_DOUBLE_KO && rr.end.winner == WINNER_NONE, "14/8 double KO");
    }
    {  // six RECOVERs x3 rounds -> HP_TIE
        FightState s = new_fight();
        for (int r = 0; r < 3; ++r) {
            RoundResult rr;
            CHECK(resolve_round(s, plan6(RECOVER), plan6(RECOVER), rr) == OK, "recover round");
            s = rr.end;
            CHECK(s.a.hp == 100 && s.b.hp == 100 && s.a.stamina == 60 && s.b.stamina == 60, "recover state");
        }
        CHECK(s.outcome == OUTCOME_HP_TIE && s.winner == WINNER_NONE, "recover HP_TIE");
    }
    {  // six JABs per round
        FightState s = new_fight();
        RoundResult rr;
        CHECK(resolve_round(s, plan6(JAB), plan6(JAB), rr) == OK, "jab r0");
        CHECK(rr.beats[5].a.after.stamina == 36 && rr.beats[5].a.after.hp == 52, "jab r0 before break");
        CHECK(rr.end.a.hp == 52 && rr.end.b.hp == 52 && rr.end.a.stamina == 46 && rr.end.b.stamina == 46 &&
                  rr.end.a.opening == 0 && rr.break_recovery == 1 && rr.end.round_index == 1, "jab r0 after break");
        s = rr.end;
        CHECK(resolve_round(s, plan6(JAB), plan6(JAB), rr) == OK, "jab r1");
        CHECK(rr.beats[5].a.after.stamina == 22 && rr.beats[5].b.after.hp == 4, "jab r1 before break");
        CHECK(rr.end.a.hp == 4 && rr.end.a.stamina == 32 && rr.end.b.stamina == 32, "jab r1 after break");
        s = rr.end;
        CHECK(resolve_round(s, plan6(JAB, 3), plan6(JAB), rr) == OK, "jab r2");
        CHECK(rr.executed == 1 && rr.end.outcome == OUTCOME_DOUBLE_KO, "jab r2 double KO on first beat");
        // Planned power at slot 3 after the KO: unexecuted, not charged.
        CHECK(rr.end.a.power_available == 1 && rr.beats[0].a.cost_paid == 6, "unexecuted power slot not charged");
    }
    {  // validation
        Fighter f = F();
        Plan p = plan6(JAB);
        CHECK(validate_plan(p, f), "plain plan valid");
        p.actions[2] = EXHAUSTED;
        CHECK(!validate_plan(p, f), "EXHAUSTED rejected");
        p = plan6(BLOCK, 0);
        CHECK(!validate_plan(p, f), "power on BLOCK rejected");
        p = plan6(THROW, 5);
        CHECK(validate_plan(p, f), "power on THROW ok");
        CHECK(!validate_plan(p, F(100, 60, 0, 0, 0)), "spent power rejected");
        p.power_slot = 6;
        CHECK(!validate_plan(p, f), "slot 6 rejected");
        FightState s = new_fight();
        s.a.stamina = 61;
        RoundResult rr;
        CHECK(resolve_round(s, plan6(JAB), plan6(JAB), rr) == BAD_STATE, "impossible state rejected");
        s = new_fight();
        CHECK(resolve_round(s, plan6(JAB), plan6(DUCK, 0), rr) == BAD_PLAN_B, "bad plan B rejected");
        uint8_t bad[8] = {100, 0, 60, 0, 0, 0, 1, 1};
        Fighter g;
        CHECK(decode_state(bad, g) == BAD_ENCODING, "nonzero reserved byte rejected");
    }
}

#endif  // QDOJO_RULESET == 1

#if QDOJO_RULESET == 2
// docs/combat.md "Candidate 2" hand vectors: fresh fighters are (120, 48, 0, 0).
static void test_hand_vectors() {
    struct Row { uint8_t a, b; int A[4], B[4]; };
    const Row table[] = {
        {JAB, BLOCK, {120, 44, 0, 0}, {120, 46, 0, 1}},
        {JAB, KICK, {116, 44, 0, 0}, {110, 38, 0, 0}},
        {DUCK, JAB, {120, 46, 1, 0}, {116, 44, 0, 0}},
        {KICK, DUCK, {120, 38, 0, 0}, {102, 46, 0, 0}},
        {THROW, BLOCK, {120, 41, 0, 0}, {100, 46, 0, 1}},
        {BLOCK, KICK, {120, 40, 0, 1}, {120, 38, 0, 0}},
        {RECOVER, JAB, {108, 48, 0, 0}, {120, 44, 1, 0}},
        {THROW, THROW, {120, 41, 0, 0}, {120, 41, 0, 0}},
    };
    for (const Row& r : table) {
        BeatTrace t = beat(F(), F(), r.a, r.b);
        CHECK(same4(t.a.after, r.A[0], r.A[1], r.A[2], r.A[3]), "c2 table %d/%d A=%s", r.a, r.b, state_hex(t.a.after).c_str());
        CHECK(same4(t.b.after, r.B[0], r.B[1], r.B[2], r.B[3]), "c2 table %d/%d B=%s", r.a, r.b, state_hex(t.b.after).c_str());
    }
    {  // DUCK/JAB (duck counters for 4 and earns an opening) then KICK/JAB
        BeatTrace t1 = beat(F(), F(), DUCK, JAB);
        CHECK(t1.a.dealt == 4 && (t1.a.reasons & R_HIT) && (t1.b.reasons & R_EVADED), "duck counter");
        BeatTrace t2 = beat(t1.a.after, t1.b.after, KICK, JAB);
        CHECK(same4(t2.a.after, 110, 36, 0, 0), "c2 duck-then-kick A");
        CHECK(same4(t2.b.after, 104, 40, 0, 0), "c2 duck-then-kick B");
        CHECK(t2.a.dealt == 12 && t2.a.base == 4 && t2.a.opening_bonus == 8 && t2.b.dealt == 10, "kick 4+8 vs jab 10");
    }
    {  // opening=1 powered KICK into DUCK: 18 + 8 + 12
        BeatTrace t = beat(F(INITIAL_HP, 48, 1), F(), KICK, DUCK, true, false);
        CHECK(t.a.after.stamina == 34 && t.a.after.power_available == 0, "c2 powered kick A");
        CHECK(t.b.lost == 38 && t.b.after.hp == 82 && t.a.lost == 0, "c2 powered kick damage");
    }
    {  // a duck counter with an opening: 4 + 8; no power on a duck
        BeatTrace t = beat(F(INITIAL_HP, 48, 1), F(), DUCK, JAB);
        CHECK(t.a.dealt == 12 && t.b.after.hp == 108 && t.a.after.opening == 1, "c2 duck counter with opening");
    }
    {  // stamina 11 KICK vs JAB -> EXHAUSTED, takes the jab's 12 (jab vs exhausted)
        BeatTrace t = beat(F(INITIAL_HP, 11), F(), KICK, JAB);
        CHECK(t.a.effective == EXHAUSTED && same4(t.a.after, 108, 17, 0, 0), "c2 exhausted kick");
        CHECK(same4(t.b.after, 120, 44, 1, 0), "c2 exhausted B");
    }
    {  // six JABs per round: 120 -> 72 -> 24 -> double KO on the third beat of round 2
        FightState s = new_fight();
        RoundResult rr;
        CHECK(resolve_round(s, plan6(JAB), plan6(JAB), rr) == OK, "c2 jab r0");
        CHECK(rr.end.a.hp == 72 && rr.end.b.hp == 72 && rr.end.a.stamina == 34, "c2 jab r0 after break");
        s = rr.end;
        CHECK(resolve_round(s, plan6(JAB), plan6(JAB), rr) == OK, "c2 jab r1");
        CHECK(rr.end.a.hp == 24 && rr.end.a.stamina == 20, "c2 jab r1 after break");
        s = rr.end;
        CHECK(resolve_round(s, plan6(JAB), plan6(JAB), rr) == OK, "c2 jab r2");
        CHECK(rr.executed == 3 && rr.end.outcome == OUTCOME_DOUBLE_KO, "c2 jab r2 double KO on beat 3");
    }
    {  // six RECOVERs x3 rounds -> HP_TIE at 120
        FightState s = new_fight();
        for (int r = 0; r < 3; ++r) {
            RoundResult rr;
            CHECK(resolve_round(s, plan6(RECOVER), plan6(RECOVER), rr) == OK, "c2 recover round");
            s = rr.end;
        }
        CHECK(s.a.hp == 120 && s.outcome == OUTCOME_HP_TIE, "c2 recover HP_TIE");
    }
}
#endif  // QDOJO_RULESET == 2

// Break carry: the literal vector (stamina 55, opening 1, guard 3 -> 60, 1, 3)
// is not reachable by play (guard 3 needs a final BLOCK, which never earns an
// opening), so check the break rule on the literal values and on a real round.
static void test_break_carry() {
    FightState t = new_fight();
    t.a = F(70, uint16_t(LIMIT_STAMINA - 5), 1, 3, 1);
    apply_break_recovery(t);
    CHECK(same4(t.a, 70, LIMIT_STAMINA, 1, 3) && t.a.power_available == 1 && t.round_index == 1, "limit-5/1/3 -> limit/1/3");

    FightState s = new_fight();
    s.a = F(100, LIMIT_STAMINA, 0, 3, 1);
    Plan pa = plan6(BLOCK), pb = plan6(RECOVER);
    pa.actions[5] = DUCK;
    pb.actions[5] = JAB;  // DUCK vs JAB earns A an opening on the last beat
    RoundResult rr;
    CHECK(resolve_round(s, pa, pb, rr) == OK, "carry round");
    const Fighter& before = rr.beats[5].a.after;
    const Fighter& after = rr.end.a;
    CHECK(before.opening == 1 && after.opening == 1, "opening carries through break");
    CHECK(after.guard_streak == before.guard_streak && after.hp == before.hp &&
              after.power_available == before.power_available, "break carries hp/guard/power");
    CHECK(after.stamina == min_u16(uint16_t(before.stamina + BREAK_RECOVERY), LIMIT_STAMINA), "break recovery capped");
}

// ------------------------------------------------------------------- NIST
static void test_sha256() {
    CHECK(sha_hex("") == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", "sha256('')");
    CHECK(sha_hex("abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad", "sha256('abc')");
    CHECK(sha_hex("abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq") ==
              "248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1",
          "sha256 448-bit");
    CHECK(sha_hex("abcdefghbcdefghicdefghijdefghijkefghijklfghijklmghijklmnhijklmnoijklmnopjklmnopqklmnopqrlmnopqrsmnopqrstnopqrstu") ==
              "cf5b16a778af8380036ce59e7b0492370b249b11e8f07a51afac45037afee9d1",
          "sha256 896-bit");
    Sha256 s;
    sha256_init(s);
    uint8_t chunk[1000];
    std::memset(chunk, 'a', sizeof chunk);
    for (int i = 0; i < 1000; ++i) sha256_update(s, chunk, sizeof chunk);
    uint8_t d[32];
    sha256_final(s, d);
    CHECK(hex(d, 32) == "cdc76e5c9914fb9281a1c7e284d73e67f1809a48a497200e046d39ccc7112cd0", "sha256 1M 'a'");
}

// -------------------------------------------------------- commitment vector
static void test_commitment(const std::string& root) {
    Json j;
    if (!load_json(root + "/docs/fixtures/commitment-v1.json", j)) { ++g_fail; return; }
    auto ctx = unhex(j["context_bytes"].s);
    CHECK(ctx.size() == CONTEXT_BYTES, "context size %zu", ctx.size());
    if (ctx.size() != CONTEXT_BYTES) return;
    uint8_t cd[32];
    context_digest(ctx.data(), cd);
    CHECK(hex(cd, 32) == j["context_digest"].s, "context_digest %s", hex(cd, 32).c_str());
    // Context embeds the ruleset digest at offset 102.
    // (The frozen vector is a candidate 1 context; hashing does not depend on the build's table.)
    CHECK(hex(ctx.data() + 102, 32) == hex(CANDIDATE_1.digest, 32), "context ruleset digest");
    CHECK(j["ruleset_digest"].s == hex(CANDIDATE_1.digest, 32), "fixture ruleset digest");

    auto rs = unhex(j["round_state_bytes"].s);
    CHECK(rs.size() == 49, "round_state_bytes size");
    if (rs.size() != 49) return;
    CHECK(hex(rs.data(), 32) == hex(cd, 32), "round state carries context digest");
    // Round-start state must be canonical initial state, reproduced by the codec.
    Fighter fa, fb;
#if QDOJO_RULESET == 1
    CHECK(decode_state(rs.data() + 33, fa) == OK && decode_state(rs.data() + 41, fb) == OK, "decode states");
#else
    // A candidate 1 state (stamina 60) is out of this build's limits; decode_state rightly refuses it.
    CHECK(decode_state(rs.data() + 33, fa) == BAD_ENCODING, "candidate 1 state refused by this build");
    fa = fb = F(CANDIDATE_1.initial_hp, CANDIDATE_1.initial_stamina, 0, 0, 1);
#endif
    uint8_t ea[8], eb[8];
    Fighter c1 = F(CANDIDATE_1.initial_hp, CANDIDATE_1.initial_stamina, CANDIDATE_1.initial_opening,
                   CANDIDATE_1.initial_guard_streak, CANDIDATE_1.initial_power_available);
    encode_state(c1, ea);
    encode_state(c1, eb);
    CHECK(hex(ea, 8) == hex(rs.data() + 33, 8) && hex(eb, 8) == hex(rs.data() + 41, 8), "initial state bytes");
    uint8_t sd[32];
    round_state_digest(cd, rs[32], ea, eb, sd);
    CHECK(hex(sd, 32) == j["round_state_digest"].s, "round_state_digest %s", hex(sd, 32).c_str());

    auto plan = unhex(j["plan_bytes"].s);
    auto salt = unhex(j["salt"].s);
    CHECK(plan.size() == 7 && salt.size() == 32, "plan/salt size");
    if (plan.size() != 7 || salt.size() != 32) return;
    Plan p;
    decode_plan(plan.data(), p);
    CHECK(validate_plan(p, fa), "fixture plan valid");
    uint8_t pe[7];
    encode_plan(p, pe);
    CHECK(hex(pe, 7) == j["plan_bytes"].s, "plan roundtrip");

    // Fields from the context: network/contract at 0/32, fight_id at 72,
    // participant A (fighter A, operator, auth_version) from offset 254.
    const uint8_t* c = ctx.data();
    uint64_t fight_id = 0;
    for (int i = 7; i >= 0; --i) fight_id = (fight_id << 8) | c[72 + i];
    const uint8_t* pa = c + 254;
    uint32_t auth = uint32_t(pa[96]) | uint32_t(pa[97]) << 8 | uint32_t(pa[98]) << 16 | uint32_t(pa[99]) << 24;
    uint8_t cm[32];
    commitment(c, c + 32, fight_id, rs[32], cd, sd, pa, pa + 64, auth, salt.data(), pe, cm);
    CHECK(hex(cm, 32) == j["commitment"].s, "commitment %s", hex(cm, 32).c_str());
    CHECK(hex(cm, 32) == "f0754c65c5aaea97811a9a64b46696084c419abd29a80853af538b017c0742fe", "commitment (protocol.md)");
    auto pre = unhex(j["commitment_preimage"].s);
    uint8_t cm2[32];
    sha256(pre.data(), uint32_t(pre.size()), cm2);
    CHECK(hex(cm2, 32) == j["commitment"].s, "hash of frozen preimage");
    CHECK(pre.size() == sizeof(TAG_COMMIT) + 244, "preimage length %zu", pre.size());
}

// ------------------------------------------------------------ fight replay
static const char* OUTCOME_NAMES[] = {"", "KO", "DOUBLE_KO", "HP", "HP_TIE"};

static uint32_t reason_bit(const std::string& n) {
    static const char* names[] = {"HIT", "BLOCKED", "EVADED", "THROW_INTERRUPTED", "THROW_CLASH",
                                  "INSUFFICIENT_STAMINA", "RECOVERY_PUNISHED", "GUARD_STRAIN",
                                  "OPENING_EARNED", "OPENING_USED", "OPENING_EXPIRED", "POWER_USED",
                                  "POWER_WASTED", "KO", "DOUBLE_KO"};
    for (uint32_t i = 0; i < 15; ++i)
        if (n == names[i]) return 1u << i;
    return 1u << 31;  // unknown
}

struct ReasonStats { long agree = 0, differ = 0; std::map<std::string, long> diffs; };

static void check_side(const SideTrace& t, const Json& j, size_t f, size_t r, size_t b, char side, ReasonStats& rs) {
    std::string after = state_hex(t.after);
    CHECK(after == j["after"].s, "fight %zu r%zu b%zu %c after %s want %s", f, r, b, side, after.c_str(), j["after"].s.c_str());
    CHECK(t.effective == j["effective"].n, "fight %zu r%zu b%zu %c effective", f, r, b, side);
    CHECK(t.cost_paid == j["cost_paid"].n, "fight %zu r%zu b%zu %c cost_paid %d want %lld", f, r, b, side, t.cost_paid, j["cost_paid"].n);
    CHECK(t.base == j["base"].n, "fight %zu r%zu b%zu %c base", f, r, b, side);
    CHECK(t.dealt == j["dealt"].n, "fight %zu r%zu b%zu %c dealt", f, r, b, side);
    CHECK(t.lost == j["lost"].n, "fight %zu r%zu b%zu %c lost", f, r, b, side);
    CHECK(t.strain == j["strain"].n, "fight %zu r%zu b%zu %c strain %d want %lld", f, r, b, side, t.strain, j["strain"].n);
    CHECK(t.recovered == j["recovered"].n, "fight %zu r%zu b%zu %c recovered %d want %lld", f, r, b, side, t.recovered, j["recovered"].n);
    // Reason codes are descriptive and not normatively defined per side;
    // compare informationally only.
    uint32_t want = 0;
    for (auto& x : j["reasons"].a) want |= reason_bit(x.s);
    if (want == t.reasons) {
        ++rs.agree;
    } else {
        ++rs.differ;
        for (uint32_t i = 0; i < 32; ++i) {
            uint32_t m = 1u << i;
            if ((want & m) != (t.reasons & m))
                rs.diffs[std::string((want & m) ? "python-only bit " : "c++-only bit ") + std::to_string(i)]++;
        }
    }
}

static void test_fights(const std::string& root) {
    std::string dir = root + "/packages/qdojo/tests/combat/fixtures";
    std::vector<std::string> files;
    if (DIR* d = opendir(dir.c_str())) {
        while (dirent* e = readdir(d)) {
            std::string n = e->d_name;
            if (n.rfind("fights-", 0) == 0 && n.size() > 5 && n.substr(n.size() - 5) == ".json") files.push_back(dir + "/" + n);
        }
        closedir(d);
    }
    CHECK(!files.empty(), "no fight fixtures in %s", dir.c_str());
    int matched = 0;
    long fights = 0, rounds = 0, beats = 0, traced_fights = 0, traced_beats = 0;
    ReasonStats rs;
    for (auto& path : files) {
        Json doc;
        if (!load_json(path, doc)) { ++g_fail; continue; }
        if (doc["ruleset_digest"].s != hex(RULESET_DIGEST, 32)) {  // another ruleset's parity set
            std::printf("skipping %s (ruleset %s is not this build's)\n", path.c_str(), doc["ruleset_digest"].s.c_str());
            continue;
        }
        ++matched;
        const Json& fs = doc["fights"];
        const Json& tr = doc["traced"];
        for (size_t fi = 0; fi < fs.size(); ++fi) {
            const Json& fj = fs[fi];
            bool traced = fi < tr.size();
            FightState s = new_fight();
            const Json& rj = fj["rounds"];
            for (size_t ri = 0; ri < rj.size(); ++ri) {
                auto pab = unhex(rj[ri][0].s), pbb = unhex(rj[ri][1].s);
                if (pab.size() != 7 || pbb.size() != 7) { CHECK(false, "fight %zu bad plan hex", fi); break; }
                Plan pa, pb;
                decode_plan(pab.data(), pa);
                decode_plan(pbb.data(), pb);
                RoundResult rr;
                Error e = resolve_round(s, pa, pb, rr);
                CHECK(e == OK, "fight %zu round %zu error %d", fi, ri, e);
                if (e != OK) break;
                CHECK(rr.executed == rj[ri][2].n, "fight %zu round %zu executed %d want %lld", fi, ri, rr.executed, rj[ri][2].n);
                std::string end = state_hex(rr.end.a) + state_hex(rr.end.b);
                CHECK(end == rj[ri][3].s, "fight %zu round %zu end %s want %s", fi, ri, end.c_str(), rj[ri][3].s.c_str());
                ++rounds;
                beats += rr.executed;
                if (traced) {
                    const Json& bj = tr[fi][ri];
                    CHECK(bj.size() == rr.executed, "fight %zu round %zu traced beats", fi, ri);
                    for (size_t bi = 0; bi < bj.size() && bi < rr.executed; ++bi) {
                        check_side(rr.beats[bi].a, bj[bi][0], fi, ri, bi, 'A', rs);
                        check_side(rr.beats[bi].b, bj[bi][1], fi, ri, bi, 'B', rs);
                        ++traced_beats;
                    }
                }
                s = rr.end;
                bool last = ri + 1 == rj.size();
                CHECK((s.outcome != OUTCOME_NONE) == last, "fight %zu round %zu terminal flag", fi, ri);
            }
            if (traced) {
                CHECK(tr[fi].size() == rj.size(), "fight %zu traced rounds", fi);
                ++traced_fights;
            }
            const Json& oj = fj["outcome"];
            std::string want_w = oj[0].kind == Json::NUL ? "" : oj[0].s;
            std::string got_w = s.winner == WINNER_A ? "A" : s.winner == WINNER_B ? "B" : "";
            CHECK(s.outcome < 5 && oj[1].s == OUTCOME_NAMES[s.outcome] && want_w == got_w,
                  "fight %zu outcome %s/%s want %s/%s", fi, got_w.c_str(), s.outcome < 5 ? OUTCOME_NAMES[s.outcome] : "?",
                  want_w.c_str(), oj[1].s.c_str());
            ++fights;
        }
    }
    CHECK(matched == 1, "%d fight fixture files for this build's ruleset, want 1", matched);
    std::printf("fights: %ld fights, %ld rounds, %ld beats replayed; %ld traced fights, %ld traced beats\n", fights,
                rounds, beats, traced_fights, traced_beats);
    std::printf("reason codes (informational, not asserted): %ld sides agree, %ld differ\n", rs.agree, rs.differ);
    for (auto& kv : rs.diffs) std::printf("  %s: %ld\n", kv.first.c_str(), kv.second);
}

int main(int argc, char** argv) {
    std::string root = argc > 1 ? argv[1] : ".";
    int before;
    before = g_fail; test_constants(root);    std::printf("ruleset tables vs JSON (build selects %d): %s\n", QDOJO_RULESET, g_fail == before ? "ok" : "FAIL");
    before = g_fail; test_hand_vectors(); test_break_carry(); std::printf("hand vectors: %s\n", g_fail == before ? "ok" : "FAIL");
    before = g_fail; test_sha256();           std::printf("NIST SHA-256: %s\n", g_fail == before ? "ok" : "FAIL");
    before = g_fail; test_commitment(root);   std::printf("commitment-v1 vector: %s\n", g_fail == before ? "ok" : "FAIL");
    before = g_fail; test_fights(root);       std::printf("fight fixtures: %s\n", g_fail == before ? "ok" : "FAIL");
    std::printf("%d checks, %d failed\n", g_checks, g_fail);
    return g_fail ? 1 : 0;
}
