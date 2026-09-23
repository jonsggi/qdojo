// Parity runner for combat_contract.h. The only file here that uses the
// standard library.
//
// Replays each contract journal (packages/qdojo/tests/combat/fixtures/contract/
// *.journal, written by the Python reference's sim.World) through the C++
// state machine and requires the identical final event digest. Because the
// digest chains every canonical event body, a match means every emitted
// event, its fields, its order and its values agree with the reference.
//
// After every journal step it also asserts:
//   - ledger conservation: balance == sum of liabilities, no negative bucket
//   - no checked-arithmetic, slot or engine fault was recorded
// and it reports sizeof(State) and the maximum per-entry-point work.
//
// Usage: test_contract [--trace DIR] JOURNAL...
//   --trace DIR writes DIR/<name>.txt with one line per event
//   ("E seq tick type body_hex digest_hex") and per call
//   ("C tick code op target refunded"), the format of the reference dump
//   used to find the first diverging event.
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <map>
#include <memory>
#include <set>
#include <sstream>
#include <string>
#include <vector>

#include "combat_contract.h"

using namespace qdojo_contract;

// ------------------------------------------------------------ tiny JSON
struct JVal {
    enum Kind { NUL, BOOL, NUM, STR, ARR, OBJ } kind = NUL;
    bool b = false;
    long long num = 0;
    std::string str;
    std::vector<JVal> arr;
    std::map<std::string, JVal> obj;

    const JVal& at(const std::string& k) const {
        auto it = obj.find(k);
        if (it == obj.end()) {
            std::fprintf(stderr, "missing JSON key %s\n", k.c_str());
            std::exit(2);
        }
        return it->second;
    }
    bool has(const std::string& k) const { return obj.count(k) != 0; }
};

struct JParser {
    const std::string& s;
    size_t i = 0;
    explicit JParser(const std::string& text) : s(text) {}
    [[noreturn]] void fail(const char* what) {
        std::fprintf(stderr, "JSON error at %zu: %s\n", i, what);
        std::exit(2);
    }
    void ws() {
        while (i < s.size() && (s[i] == ' ' || s[i] == '\t' || s[i] == '\r' || s[i] == '\n')) ++i;
    }
    JVal value() {
        ws();
        if (i >= s.size()) fail("eof");
        char c = s[i];
        JVal v;
        if (c == '{') {
            v.kind = JVal::OBJ;
            ++i;
            ws();
            if (s[i] == '}') {
                ++i;
                return v;
            }
            for (;;) {
                ws();
                JVal k = value();
                if (k.kind != JVal::STR) fail("key");
                ws();
                if (s[i++] != ':') fail("colon");
                v.obj[k.str] = value();
                ws();
                if (s[i] == ',') {
                    ++i;
                    continue;
                }
                if (s[i] == '}') {
                    ++i;
                    return v;
                }
                fail("object");
            }
        }
        if (c == '[') {
            v.kind = JVal::ARR;
            ++i;
            ws();
            if (s[i] == ']') {
                ++i;
                return v;
            }
            for (;;) {
                v.arr.push_back(value());
                ws();
                if (s[i] == ',') {
                    ++i;
                    continue;
                }
                if (s[i] == ']') {
                    ++i;
                    return v;
                }
                fail("array");
            }
        }
        if (c == '"') {
            v.kind = JVal::STR;
            ++i;
            while (i < s.size() && s[i] != '"') {
                if (s[i] == '\\') fail("escapes are not used by journals");
                v.str += s[i++];
            }
            ++i;
            return v;
        }
        if (s.compare(i, 4, "null") == 0) {
            i += 4;
            return v;
        }
        if (s.compare(i, 4, "true") == 0) {
            i += 4;
            v.kind = JVal::BOOL;
            v.b = true;
            return v;
        }
        if (s.compare(i, 5, "false") == 0) {
            i += 5;
            v.kind = JVal::BOOL;
            return v;
        }
        if (c == '-' || (c >= '0' && c <= '9')) {
            size_t start = i;
            ++i;
            while (i < s.size() && s[i] >= '0' && s[i] <= '9') ++i;
            if (i < s.size() && (s[i] == '.' || s[i] == 'e' || s[i] == 'E')) fail("journals are integer-only");
            v.kind = JVal::NUM;
            v.num = std::stoll(s.substr(start, i - start));
            return v;
        }
        fail("unexpected character");
    }
};

static JVal parse_json(const std::string& line) {
    JParser p(line);
    return p.value();
}

// ------------------------------------------------------------ hex
static int nib(char c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    std::fprintf(stderr, "bad hex\n");
    std::exit(2);
}
static std::vector<uint8_t> unhex(const std::string& h) {
    std::vector<uint8_t> out(h.size() / 2);
    for (size_t i = 0; i < out.size(); ++i) out[i] = uint8_t(nib(h[2 * i]) * 16 + nib(h[2 * i + 1]));
    return out;
}
static std::string hex(const uint8_t* p, size_t n) {
    static const char* d = "0123456789abcdef";
    std::string s;
    for (size_t i = 0; i < n; ++i) {
        s += d[p[i] >> 4];
        s += d[p[i] & 15];
    }
    return s;
}
static Id id_of(const std::string& h) {
    std::vector<uint8_t> v = unhex(h);
    if (v.size() != 32) {
        std::fprintf(stderr, "identity is not 32 bytes: %s\n", h.c_str());
        std::exit(2);
    }
    Id x;
    std::memcpy(x.b, v.data(), 32);
    return x;
}
static std::string key(const Id& x) { return std::string(reinterpret_cast<const char*>(x.b), 32); }

// ------------------------------------------------------------ fake chain
struct FakeHost : Host {
    std::map<std::string, Id> owners;      // asset -> owner (absent or null = unavailable)
    std::set<std::string> failing;         // recipients whose transfers fail
    bool owner_of(const Id& fid, Id& out) override {
        auto it = owners.find(key(fid));
        if (it == owners.end()) return false;
        out = it->second;
        return true;
    }
    bool transfer(const Id& to, int64_t amount) override {
        (void)amount;
        return failing.count(key(to)) == 0;
    }
};

static bool load_manifest(const JVal& h, Manifest& m) {
    std::memset(&m, 0, sizeof(m));
    m.network_id = id_of(h.at("network_id").str);
    m.contract_id = id_of(h.at("contract_id").str);
    m.admin = id_of(h.at("admin").str);
    std::vector<uint8_t> rd = unhex(h.at("ruleset_digest").str);
    if (rd.size() != 32) return false;
    std::memcpy(m.ruleset_digest, rd.data(), 32);
    uint32_t n = 0;
    for (const auto& kv : h.at("timing").obj) {
        if (n >= CAP_TIMING) return false;
        m.timing[n].id = uint32_t(std::stoul(kv.first));
        m.timing[n].commit_ticks = uint16_t(kv.second.arr.at(0).num);
        m.timing[n].reveal_ticks = uint16_t(kv.second.arr.at(1).num);
        m.timing[n].used = 1;
        ++n;
    }
    n = 0;
    for (const auto& kv : h.at("fees").obj) {
        if (n >= CAP_FEES) return false;
        FeeProfile& f = m.fees[n++];
        f.id = uint32_t(std::stoul(kv.first));
        f.rake_bps = uint16_t(kv.second.at("rake_bps").num);
        f.house_bps = uint16_t(kv.second.at("house_bps").num);
        f.dev_bps = uint16_t(kv.second.at("dev_bps").num);
        f.share_bps = uint16_t(kv.second.at("share_bps").num);
        f.house = id_of(kv.second.at("house").str);
        f.dev = id_of(kv.second.at("dev").str);
        f.share = id_of(kv.second.at("share").str);
        f.used = 1;
    }
    n = 0;
    for (const auto& kv : h.at("tiers").obj) {
        if (n >= CAP_TIERS) return false;
        m.tiers[n].id = uint16_t(std::stoul(kv.first));
        m.tiers[n].stake = kv.second.num;
        m.tiers[n].used = 1;
        ++n;
    }
    m.genesis_tick = h.at("genesis_tick").num;
    m.genesis_epoch = h.at("genesis_epoch").num;
    m.ticks_per_epoch = h.at("ticks_per_epoch").num;
    m.season_start_epoch = h.at("season_start_epoch").num;
    m.season_epochs = h.at("season_epochs").num;
    m.season_closeout_ticks = h.at("season_closeout_ticks").num;
    m.max_fighters = uint32_t(h.at("max_fighters").num);
    m.max_accounts = uint32_t(h.at("max_accounts").num);
    m.max_offers = uint32_t(h.at("max_offers").num);
    m.max_fights = uint32_t(h.at("max_fights").num);
    m.max_cups = uint32_t(h.at("max_cups").num);
    m.max_cup_entrants = uint32_t(h.at("max_cup_entrants").num);
    m.event_ring = uint32_t(h.at("event_ring").num);
    m.match_interval = uint32_t(h.at("match_interval").num);
    m.cooldown_ticks = uint64_t(h.at("cooldown_ticks").num);
    m.faults_per_epoch = uint32_t(h.at("faults_per_epoch").num);
    m.offer_lifetime_lo = uint64_t(h.at("offer_lifetime").arr.at(0).num);
    m.offer_lifetime_hi = uint64_t(h.at("offer_lifetime").arr.at(1).num);
    return true;
}

// ------------------------------------------------------------ replay
struct MaxWork {
    Work call{}, end{}, begin{};
};
static void fold(Work& into, const Work& w) {
    into.sha_blocks = std::max(into.sha_blocks, w.sha_blocks);
    into.events = std::max(into.events, w.events);
    into.fights = std::max(into.fights, w.fights);
    into.comparisons = std::max(into.comparisons, w.comparisons);
    into.scan_steps = std::max(into.scan_steps, w.scan_steps);
    into.owner_queries = std::max(into.owner_queries, w.owner_queries);
    into.transfers = std::max(into.transfers, w.transfers);
}
static void print_work(const char* name, const Work& w) {
    std::printf("    %-10s sha_blocks=%u events=%u fights=%u comparisons=%u scan_steps=%u owner_queries=%u transfers=%u\n",
                name, w.sha_blocks, w.events, w.fights, w.comparisons, w.scan_steps, w.owner_queries, w.transfers);
}

static bool faults_clear(const State& s) {
    const Faults& f = s.faults;
    return f.arithmetic == 0 && f.account_overflow == 0 && f.pair_overflow == 0 && f.slot_overflow == 0 && f.engine == 0;
}

struct Tracer {
    FILE* out = nullptr;
    uint64_t printed = 0;
    void events(const State& s) {
        if (!out) return;
        while (printed < s.event_seq) {
            ++printed;
            const Event& e = s.events[(printed - 1) % s.m.event_ring];
            std::fprintf(out, "E %llu %llu %u %s %s\n", (unsigned long long)e.seq, (unsigned long long)e.tick, e.type,
                         hex(e.body, e.len).c_str(), hex(e.digest, 32).c_str());
        }
    }
};

static bool replay(const std::string& path, const char* trace_dir, MaxWork& mw, std::string& summary) {
    std::ifstream in(path);
    if (!in) {
        std::fprintf(stderr, "cannot open %s\n", path.c_str());
        return false;
    }
    std::string line;
    std::getline(in, line);
    JVal head = parse_json(line);
    if (head.at("schema").str != "qdojo.combat.journal.v1") {
        std::fprintf(stderr, "%s: not a combat journal\n", path.c_str());
        return false;
    }
    Manifest m;
    if (!load_manifest(head, m)) {
        std::fprintf(stderr, "%s: manifest exceeds compiled capacities\n", path.c_str());
        return false;
    }
    std::unique_ptr<State> sp(new State());
    State& s = *sp;
    FakeHost host;
    Tracer tr;
    if (trace_dir) {
        std::string name = path.substr(path.find_last_of('/') + 1);
        name = name.substr(0, name.find('.'));
        std::string out = std::string(trace_dir) + "/" + name + ".txt";
        tr.out = std::fopen(out.c_str(), "w");
    }
    bool started = false, digest_seen = false, ok = true;
    size_t steps = 0, calls = 0, ends = 0;
    std::map<int, int> codes;
    std::string expected_digest;
    auto check = [&](const char* what, long long t) {
        int64_t liab = liabilities(s);
        if (s.balance != liab || s.balance < 0) {
            std::fprintf(stderr, "%s: conservation broken after %s at tick %lld: balance %lld liabilities %lld\n",
                         path.c_str(), what, t, (long long)s.balance, (long long)liab);
            ok = false;
        }
        for (uint32_t i = 0; i < CAP_ACCOUNTS; ++i)
            if (s.accounts[i].used && s.accounts[i].credit < 0) {
                std::fprintf(stderr, "%s: negative credit after %s at tick %lld\n", path.c_str(), what, t);
                ok = false;
                break;
            }
        if (!faults_clear(s)) {
            std::fprintf(stderr, "%s: fault counters nonzero after %s at tick %lld\n", path.c_str(), what, t);
            ok = false;
        }
    };
    while (ok && std::getline(in, line)) {
        if (line.empty()) continue;
        JVal r = parse_json(line);
        const std::string& k = r.at("k").str;
        ++steps;
        if (k == "start") {
            if (!init(s, m, uint64_t(r.at("t").num))) {
                std::fprintf(stderr, "%s: init rejected the manifest\n", path.c_str());
                return false;
            }
            started = true;
        } else if (!started) {
            std::fprintf(stderr, "%s: record before start\n", path.c_str());
            return false;
        } else if (k == "owner") {
            const JVal& o = r.at("owner");
            if (o.kind == JVal::NUL) host.owners.erase(key(id_of(r.at("id").str)));
            else host.owners[key(id_of(r.at("id").str))] = id_of(o.str);
        } else if (k == "fail") {
            std::string who = key(id_of(r.at("who").str));
            if (r.at("on").b) host.failing.insert(who);
            else host.failing.erase(who);
        } else if (k == "call") {
            std::vector<uint8_t> frame = unhex(r.at("frame").str);
            if (frame.size() != FRAME_LEN) {
                // The native SDK only sends 512-byte frames; the Qubic runtime
                // pads/truncates to sizeof(input) before the contract runs.
                frame.resize(FRAME_LEN, 0);
            }
            uint64_t t = uint64_t(r.at("t").num);
            CallResult cr = dispatch(s, host, id_of(r.at("who").str), frame.data(), r.at("amount").num, t);
            ++calls;
            ++codes[cr.code];
            tr.events(s);
            if (tr.out)
                std::fprintf(tr.out, "C %llu %u %u %llu %lld\n", (unsigned long long)t, cr.code, cr.op,
                             (unsigned long long)cr.target, (long long)cr.refunded);
            if (cr.code == HOST_ERROR) {
                std::fprintf(stderr, "%s: host error at tick %llu\n", path.c_str(), (unsigned long long)t);
                ok = false;
            }
            fold(mw.call, s.work);
            check("call", (long long)t);
        } else if (k == "end") {
            uint64_t t = uint64_t(r.at("t").num);
            end_tick(s, host, t);
            fold(mw.end, s.work);
            tr.events(s);
            check("end_tick", (long long)t);
            begin_tick(s, host, t + 1);
            fold(mw.begin, s.work);
            tr.events(s);
            check("begin_tick", (long long)t + 1);
            ++ends;
        } else if (k == "begin") {
            uint64_t t = uint64_t(r.at("t").num);
            begin_tick(s, host, t);
            fold(mw.begin, s.work);
            tr.events(s);
            check("begin_tick", (long long)t);
        } else if (k == "mint") {
            // external balances are not contract state
        } else if (k == "digest") {
            digest_seen = true;
            expected_digest = r.at("event_digest").str;
        } else {
            std::fprintf(stderr, "%s: unknown record %s\n", path.c_str(), k.c_str());
            return false;
        }
    }
    if (tr.out) {
        std::fprintf(tr.out, "F %s balance=%lld\n", hex(s.event_digest, 32).c_str(), (long long)s.balance);
        std::fclose(tr.out);
    }
    std::string got = hex(s.event_digest, 32);
    std::ostringstream os;
    os << path.substr(path.find_last_of('/') + 1) << ": " << steps << " records, " << calls << " calls, " << ends
       << " END_TICKs, " << s.event_seq << " events, balance " << s.balance << " QU; codes";
    for (const auto& kv : codes) os << " " << kv.first << "x" << kv.second;
    if (!digest_seen) {
        os << "\n    NO recorded digest";
        ok = false;
    } else if (got != expected_digest) {
        os << "\n    DIGEST MISMATCH: got " << got << " want " << expected_digest;
        ok = false;
    } else {
        os << "\n    final event digest " << got << " == reference";
    }
    summary = os.str();
    return ok;
}

int main(int argc, char** argv) {
    const char* trace_dir = nullptr;
    std::vector<std::string> journals;
    for (int i = 1; i < argc; ++i) {
        if (std::strcmp(argv[i], "--trace") == 0 && i + 1 < argc) trace_dir = argv[++i];
        else journals.push_back(argv[i]);
    }
    if (journals.empty()) {
        std::fprintf(stderr, "usage: test_contract [--trace DIR] JOURNAL...\n");
        return 2;
    }
    std::printf("sizeof(State) = %zu bytes (%.1f KiB)\n", sizeof(State), double(sizeof(State)) / 1024.0);
    std::printf("  fighters %zu x %zu, accounts %zu x %zu, assets %zu x %zu, events %zu x %zu, pairs %zu x %zu\n",
                size_t(CAP_FIGHTERS), sizeof(Fighter), size_t(CAP_ACCOUNTS), sizeof(Account), size_t(CAP_ASSETS),
                sizeof(Asset), size_t(CAP_EVENTS), sizeof(Event), size_t(CAP_PAIRS), sizeof(PairRecord));
    std::printf("  offers %zu x %zu, contests %zu x %zu, fights %zu x %zu, cups %zu x %zu\n", size_t(CAP_OFFER_SLOTS),
                sizeof(Offer), size_t(CAP_CONTEST_SLOTS), sizeof(Contest), size_t(CAP_FIGHT_SLOTS), sizeof(Fight),
                size_t(CAP_CUP_SLOTS), sizeof(Cup));
    int failures = 0;
    MaxWork total;
    for (const std::string& j : journals) {
        MaxWork mw;
        std::string summary;
        bool ok = replay(j, trace_dir, mw, summary);
        std::printf("%s %s\n", ok ? "PASS" : "FAIL", summary.c_str());
        std::printf("  max work per entry point:\n");
        print_work("dispatch", mw.call);
        print_work("end_tick", mw.end);
        print_work("begin_tick", mw.begin);
        fold(total.call, mw.call);
        fold(total.end, mw.end);
        fold(total.begin, mw.begin);
        if (!ok) ++failures;
    }
    std::printf("max work over all journals:\n");
    print_work("dispatch", total.call);
    print_work("end_tick", total.end);
    print_work("begin_tick", total.begin);
    std::printf("%d of %zu journals failed\n", failures, journals.size());
    return failures ? 1 : 0;
}
