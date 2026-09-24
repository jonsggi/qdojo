// GoogleTest for the QDOJO contract inside Qubic Core's contract test harness
// (test/contract_testing.h). Install as test/contract_qdojo.cpp in a Core
// checkout that registers QDOJO in src/contract_core/contract_def.h; see
// contracts/qubic/README.md for the exact commands.
//
// Each test replays one reference journal
// (packages/qdojo/tests/combat/fixtures/contract/*.journal) through the real
// QPI-built contract:
//   - "start"  -> the journal's manifest is written into the zeroed state,
//                 then INITIALIZE runs at the start tick;
//   - "owner"  -> Core universe: the fighter's one-unit asset (issuer =
//                 fighter_id, name QDOJOF) is issued once and its ownership and
//                 possession are moved; "null" moves it to NULL_ID (unavailable);
//   - "mint"   -> Core spectrum: increaseEnergy(who, amount);
//   - "fail"   -> transfers to `who` must fail: while such a caller's
//                 Dispatch runs, the contract's QU are parked elsewhere, so
//                 qpi.transfer fails for real (insufficient balance);
//   - "call"   -> the Dispatch user procedure with the 512-byte frame and the
//                 attachment as invocation reward, at system.tick = t;
//   - "end"    -> END_TICK at t, then BEGIN_TICK at t + 1;
//   - "digest" -> the reference's final event digest, compared at the end.
//
// After every step the test also checks, through the real query functions:
// GetLedger balance == liabilities, no negative credit, every fault counter
// zero, and the contract's spectrum balance == its ledger balance.
//
// With QDOJO_LOCKSTEP_PORT the parity-tested C++ port
// (contracts/combat_contract/combat_contract.h) runs next to the contract and
// every call result and the event digest are compared after every step.
#define NO_UEFI

#include "contract_testing.h"

#include <chrono>
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

#ifdef QDOJO_LOCKSTEP_PORT
#include "combat_contract.h"
#endif

#ifndef QDOJO_JOURNAL_DIR
#define QDOJO_JOURNAL_DIR "packages/qdojo/tests/combat/fixtures/contract"
#endif

namespace qdojo_test
{

// ------------------------------------------------------------ tiny JSON (journals are integer-only)
struct JVal
{
    enum Kind { NUL, BOOL, NUM, STR, ARR, OBJ } kind = NUL;
    bool b = false;
    long long num = 0;
    std::string str;
    std::vector<JVal> arr;
    std::map<std::string, JVal> obj;
    const JVal& at(const std::string& k) const
    {
        auto it = obj.find(k);
        if (it == obj.end())
        {
            ADD_FAILURE() << "missing JSON key " << k;
            static JVal none;
            return none;
        }
        return it->second;
    }
};

struct JParser
{
    const std::string& s;
    size_t i = 0;
    explicit JParser(const std::string& text) : s(text) {}
    void ws()
    {
        while (i < s.size() && (s[i] == ' ' || s[i] == '\t' || s[i] == '\r' || s[i] == '\n'))
            ++i;
    }
    JVal value()
    {
        ws();
        JVal v;
        if (i >= s.size())
            return v;
        char c = s[i];
        if (c == '{')
        {
            v.kind = JVal::OBJ;
            ++i;
            ws();
            if (s[i] == '}')
            {
                ++i;
                return v;
            }
            for (;;)
            {
                ws();
                JVal k = value();
                ws();
                ++i;  // ':'
                v.obj[k.str] = value();
                ws();
                if (s[i] == ',')
                {
                    ++i;
                    continue;
                }
                ++i;  // '}'
                return v;
            }
        }
        if (c == '[')
        {
            v.kind = JVal::ARR;
            ++i;
            ws();
            if (s[i] == ']')
            {
                ++i;
                return v;
            }
            for (;;)
            {
                v.arr.push_back(value());
                ws();
                if (s[i] == ',')
                {
                    ++i;
                    continue;
                }
                ++i;  // ']'
                return v;
            }
        }
        if (c == '"')
        {
            v.kind = JVal::STR;
            ++i;
            while (i < s.size() && s[i] != '"')
                v.str += s[i++];
            ++i;
            return v;
        }
        if (s.compare(i, 4, "null") == 0)
        {
            i += 4;
            return v;
        }
        if (s.compare(i, 4, "true") == 0)
        {
            i += 4;
            v.kind = JVal::BOOL;
            v.b = true;
            return v;
        }
        if (s.compare(i, 5, "false") == 0)
        {
            i += 5;
            v.kind = JVal::BOOL;
            return v;
        }
        size_t start = i;
        ++i;
        while (i < s.size() && s[i] >= '0' && s[i] <= '9')
            ++i;
        v.kind = JVal::NUM;
        v.num = std::stoll(s.substr(start, i - start));
        return v;
    }
};

static JVal parseJson(const std::string& line)
{
    JParser p(line);
    return p.value();
}

static std::vector<uint8_t> unhex(const std::string& h)
{
    std::vector<uint8_t> out(h.size() / 2);
    for (size_t i = 0; i < out.size(); ++i)
        out[i] = (uint8_t)std::stoul(h.substr(2 * i, 2), nullptr, 16);
    return out;
}

static std::string hex(const void* p, size_t n)
{
    static const char* d = "0123456789abcdef";
    const uint8_t* b = (const uint8_t*)p;
    std::string s;
    for (size_t i = 0; i < n; ++i)
    {
        s += d[b[i] >> 4];
        s += d[b[i] & 15];
    }
    return s;
}

static m256i idOf(const std::string& h)
{
    std::vector<uint8_t> v = unhex(h);
    m256i x = m256i::zero();
    if (v.size() == 32)
        memcpy(x.m256i_u8, v.data(), 32);
    else
        ADD_FAILURE() << "identity is not 32 bytes: " << h;
    return x;
}

static std::string key(const m256i& x)
{
    return std::string((const char*)x.m256i_u8, 32);
}

// Where "fail" callers' QU are parked while their Dispatch runs.
static const m256i PARKING(0x5041524b494e47ULL, 0, 0, 0x71646f6a6fULL);

// ------------------------------------------------------------ the chain
class QdojoChain : protected ContractTesting
{
public:
    struct Holding
    {
        int ownership;
        int possession;
        m256i owner;
    };
    std::map<std::string, Holding> holdings;   // fighter asset -> current ownership/possession record
    std::set<std::string> failing;             // callers whose paybacks must fail
    double dispatchSeconds = 0, endTickSeconds = 0, beginTickSeconds = 0;
    unsigned long long dispatches = 0, endTicks = 0;
    double maxDispatch = 0, maxEndTick = 0;

    QdojoChain()
    {
        initEmptySpectrum();
        initEmptyUniverse();
        INIT_CONTRACT(QDOJO);
        system.epoch = contractDescriptions[QDOJO_CONTRACT_INDEX].constructionEpoch;
    }

    QDOJO::StateData& st()
    {
        return *reinterpret_cast<QDOJO::StateData*>(contractStates[QDOJO_CONTRACT_INDEX]);
    }

    static m256i contractId()
    {
        return m256i(QDOJO_CONTRACT_INDEX, 0, 0, 0);
    }

    void initialize(const QDOJO::Manifest& m, uint64 tick)
    {
        st().m = m;
        st().manifestLoaded = 1;
        system.tick = (unsigned int)tick;
        callSystemProcedure(QDOJO_CONTRACT_INDEX, INITIALIZE);
    }

    // INITIALIZE without a preloaded manifest: the compiled-in profile.
    void initializeCompiled(uint64 tick)
    {
        st().manifestLoaded = 0;
        system.tick = (unsigned int)tick;
        callSystemProcedure(QDOJO_CONTRACT_INDEX, INITIALIZE);
    }

    void mint(const m256i& who, long long amount)
    {
        increaseEnergy(who, amount);
    }

    void setOwner(const m256i& fighterId, bool present, const m256i& owner)
    {
        auto it = holdings.find(key(fighterId));
        if (it == holdings.end())
        {
            if (!present)
                return;  // never issued: stays unavailable
            int issuance, ownership, possession;
            char name[7] = { 'Q', 'D', 'O', 'J', 'O', 'F', 0 };
            char unit[7] = { 0 };
            ASSERT_EQ(issueAsset(fighterId, name, 0, unit, 1, QDOJO_CONTRACT_INDEX, &issuance, &ownership, &possession), 1);
            it = holdings.emplace(key(fighterId), Holding{ ownership, possession, fighterId }).first;
        }
        m256i dest = present ? owner : m256i::zero();
        if (dest == it->second.owner)
            return;
        int dstOwnership, dstPossession;
        ASSERT_TRUE(transferShareOwnershipAndPossession(it->second.ownership, it->second.possession, dest, 1,
            &dstOwnership, &dstPossession, true));
        it->second = Holding{ dstOwnership, dstPossession, dest };
    }

    // invokeUserProcedure, plus the "fail" hook between the reward transfer and the call.
    bool dispatch(const m256i& user, long long amount, const std::vector<uint8_t>& frame, QDOJO::Dispatch_output& out)
    {
        QDOJO::Dispatch_input in;
        setMem(&in, sizeof(in), 0);
        for (size_t i = 0; i < frame.size() && i < 512; ++i)
            in.frame.set(i, frame[i]);
        setMem(&out, sizeof(out), 0);
        int userIdx = spectrumIndex(user);
        if (amount > 0 && (userIdx < 0 || !decreaseEnergy(userIdx, amount)))
            return false;
        if (amount > 0)
            increaseEnergy(contractId(), amount);
        long long parked = 0;
        if (failing.count(key(user)))
        {
            parked = getBalance(contractId());
            if (parked > 0)
            {
                EXPECT_TRUE(decreaseEnergy(spectrumIndex(contractId()), parked));
                increaseEnergy(PARKING, parked);
            }
        }
        auto t0 = std::chrono::steady_clock::now();
        QpiContextUserProcedureCall qpiContext(QDOJO_CONTRACT_INDEX, user, amount);
        qpiContext.call(1, &in, sizeof(in));
        auto t1 = std::chrono::steady_clock::now();
        double sec = std::chrono::duration<double>(t1 - t0).count();
        dispatchSeconds += sec;
        maxDispatch = std::max(maxDispatch, sec);
        ++dispatches;
        EXPECT_EQ((int)qpiContext.outputSize, (int)sizeof(out));
        EXPECT_EQ(contractError[QDOJO_CONTRACT_INDEX], 0u);
        copyMem(&out, qpiContext.outputBuffer, sizeof(out));
        qpiContext.freeBuffer();
        if (parked > 0)
        {
            EXPECT_TRUE(decreaseEnergy(spectrumIndex(PARKING), parked));
            increaseEnergy(contractId(), parked);
        }
        return true;
    }

    void endTick(uint64 t)
    {
        system.tick = (unsigned int)t;
        auto t0 = std::chrono::steady_clock::now();
        callSystemProcedure(QDOJO_CONTRACT_INDEX, END_TICK);
        auto t1 = std::chrono::steady_clock::now();
        system.tick = (unsigned int)(t + 1);
        callSystemProcedure(QDOJO_CONTRACT_INDEX, BEGIN_TICK);
        auto t2 = std::chrono::steady_clock::now();
        double e = std::chrono::duration<double>(t1 - t0).count();
        endTickSeconds += e;
        beginTickSeconds += std::chrono::duration<double>(t2 - t1).count();
        maxEndTick = std::max(maxEndTick, e);
        ++endTicks;
    }

    void beginTick(uint64 t)
    {
        system.tick = (unsigned int)t;
        callSystemProcedure(QDOJO_CONTRACT_INDEX, BEGIN_TICK);
    }

    template <typename In, typename Out>
    void query(unsigned short fn, const In& in, Out& out)
    {
        callFunction(QDOJO_CONTRACT_INDEX, fn, in, out);
    }

    long long spectrumBalance()
    {
        return getBalance(contractId());
    }
};

#ifdef QDOJO_LOCKSTEP_PORT
// The port's host: the same owners and failing callers as the chain.
struct PortHost : qdojo_contract::Host
{
    std::map<std::string, qdojo_contract::Id> owners;
    std::set<std::string> failing;
    static std::string k(const qdojo_contract::Id& x)
    {
        return std::string((const char*)x.b, 32);
    }
    bool owner_of(const qdojo_contract::Id& fid, qdojo_contract::Id& out) override
    {
        auto it = owners.find(k(fid));
        if (it == owners.end())
            return false;
        out = it->second;
        return true;
    }
    bool transfer(const qdojo_contract::Id& to, int64_t) override
    {
        return failing.count(k(to)) == 0;
    }
};

static qdojo_contract::Id portId(const m256i& x)
{
    qdojo_contract::Id r;
    memcpy(r.b, x.m256i_u8, 32);
    return r;
}
#endif

static bool loadManifest(const JVal& h, QDOJO::Manifest& m)
{
    setMem(&m, sizeof(m), 0);
    m.networkId = idOf(h.at("network_id").str);
    m.contractId = idOf(h.at("contract_id").str);
    m.admin = idOf(h.at("admin").str);
    m.rulesetDigest = idOf(h.at("ruleset_digest").str);
    unsigned n = 0;
    for (const auto& kv : h.at("timing").obj)
    {
        if (n >= QDOJO_CAP_TIMING)
            return false;
        QDOJO::TimingProfile tp{};
        tp.profileId = (uint32)std::stoul(kv.first);
        tp.commitTicks = (uint16)kv.second.arr.at(0).num;
        tp.revealTicks = (uint16)kv.second.arr.at(1).num;
        tp.used = 1;
        m.timing.set(n++, tp);
    }
    n = 0;
    for (const auto& kv : h.at("fees").obj)
    {
        if (n >= QDOJO_CAP_FEES)
            return false;
        QDOJO::FeeProfile f{};
        f.profileId = (uint32)std::stoul(kv.first);
        f.rakeBps = (uint16)kv.second.at("rake_bps").num;
        f.houseBps = (uint16)kv.second.at("house_bps").num;
        f.devBps = (uint16)kv.second.at("dev_bps").num;
        f.shareBps = (uint16)kv.second.at("share_bps").num;
        f.house = idOf(kv.second.at("house").str);
        f.dev = idOf(kv.second.at("dev").str);
        f.share = idOf(kv.second.at("share").str);
        f.used = 1;
        m.fees.set(n++, f);
    }
    n = 0;
    for (const auto& kv : h.at("tiers").obj)
    {
        if (n >= QDOJO_CAP_TIERS)
            return false;
        QDOJO::Tier t{};
        t.tierId = (uint16)std::stoul(kv.first);
        t.stake = kv.second.num;
        t.used = 1;
        m.tiers.set(n++, t);
    }
    m.genesisTick = h.at("genesis_tick").num;
    m.genesisEpoch = h.at("genesis_epoch").num;
    m.ticksPerEpoch = h.at("ticks_per_epoch").num;
    m.seasonStartEpoch = h.at("season_start_epoch").num;
    m.seasonEpochs = h.at("season_epochs").num;
    m.seasonCloseoutTicks = h.at("season_closeout_ticks").num;
    m.maxFighters = (uint32)h.at("max_fighters").num;
    m.maxAccounts = (uint32)h.at("max_accounts").num;
    m.maxOffers = (uint32)h.at("max_offers").num;
    m.maxFights = (uint32)h.at("max_fights").num;
    m.maxCups = (uint32)h.at("max_cups").num;
    m.maxCupEntrants = (uint32)h.at("max_cup_entrants").num;
    m.eventRing = (uint32)h.at("event_ring").num;
    m.matchInterval = (uint32)h.at("match_interval").num;
    m.cooldownTicks = (uint64)h.at("cooldown_ticks").num;
    m.faultsPerEpoch = (uint32)h.at("faults_per_epoch").num;
    m.pairStartsPerEpoch = (uint32)h.at("pair_starts_per_epoch").num;
    m.pairRematchTicks = (uint64)h.at("pair_rematch_ticks").num;
    m.offerLifetimeLo = (uint64)h.at("offer_lifetime").arr.at(0).num;
    m.offerLifetimeHi = (uint64)h.at("offer_lifetime").arr.at(1).num;
    return true;
}

static std::string journalPath(const char* name)
{
    const char* dir = getenv("QDOJO_JOURNAL_DIR");
    return std::string(dir ? dir : QDOJO_JOURNAL_DIR) + "/" + name;
}

struct ReplaySummary
{
    size_t records = 0, calls = 0, ends = 0;
    std::map<int, int> codes;
    std::string finalDigest, expectedDigest;
    long long balance = 0;
    uint64 events = 0;
};

// Replays one journal; every mismatch is a gtest failure. Returns the summary.
static ReplaySummary replay(const char* name)
{
    ReplaySummary sum;
    std::ifstream in(journalPath(name));
    EXPECT_TRUE((bool)in) << "cannot open " << journalPath(name) << " (set QDOJO_JOURNAL_DIR)";
    if (!in)
        return sum;
    std::string line;
    std::getline(in, line);
    JVal head = parseJson(line);
    EXPECT_EQ(head.at("schema").str, "qdojo.combat.journal.v1");
    QDOJO::Manifest manifest;
    EXPECT_TRUE(loadManifest(head, manifest));

    std::unique_ptr<QdojoChain> chain(new QdojoChain());
#ifdef QDOJO_LOCKSTEP_PORT
    qdojo_contract::Manifest pm;
    {
        // The port's manifest from the same header (test_contract.cpp load_manifest).
        memset(&pm, 0, sizeof(pm));
        pm.network_id = portId(manifest.networkId);
        pm.contract_id = portId(manifest.contractId);
        pm.admin = portId(manifest.admin);
        memcpy(pm.ruleset_digest, manifest.rulesetDigest.m256i_u8, 32);
        for (unsigned i = 0; i < QDOJO_CAP_TIMING; ++i)
        {
            const auto& t = manifest.timing.get(i);
            pm.timing[i] = qdojo_contract::TimingProfile{ t.profileId, t.commitTicks, t.revealTicks, t.used };
        }
        for (unsigned i = 0; i < QDOJO_CAP_FEES; ++i)
        {
            const auto& f = manifest.fees.get(i);
            pm.fees[i].id = f.profileId;
            pm.fees[i].rake_bps = f.rakeBps;
            pm.fees[i].house_bps = f.houseBps;
            pm.fees[i].dev_bps = f.devBps;
            pm.fees[i].share_bps = f.shareBps;
            pm.fees[i].house = portId(f.house);
            pm.fees[i].dev = portId(f.dev);
            pm.fees[i].share = portId(f.share);
            pm.fees[i].used = f.used;
        }
        for (unsigned i = 0; i < QDOJO_CAP_TIERS; ++i)
        {
            const auto& t = manifest.tiers.get(i);
            pm.tiers[i] = qdojo_contract::Tier{ t.tierId, t.stake, t.used };
        }
        pm.genesis_tick = manifest.genesisTick;
        pm.genesis_epoch = manifest.genesisEpoch;
        pm.ticks_per_epoch = manifest.ticksPerEpoch;
        pm.season_start_epoch = manifest.seasonStartEpoch;
        pm.season_epochs = manifest.seasonEpochs;
        pm.season_closeout_ticks = manifest.seasonCloseoutTicks;
        pm.max_fighters = manifest.maxFighters;
        pm.max_accounts = manifest.maxAccounts;
        pm.max_offers = manifest.maxOffers;
        pm.max_fights = manifest.maxFights;
        pm.max_cups = manifest.maxCups;
        pm.max_cup_entrants = manifest.maxCupEntrants;
        pm.event_ring = manifest.eventRing;
        pm.match_interval = manifest.matchInterval;
        pm.offer_lifetime_lo = manifest.offerLifetimeLo;
        pm.offer_lifetime_hi = manifest.offerLifetimeHi;
        pm.cooldown_ticks = manifest.cooldownTicks;
        pm.faults_per_epoch = manifest.faultsPerEpoch;
        pm.pair_starts_per_epoch = manifest.pairStartsPerEpoch;
        pm.pair_rematch_ticks = manifest.pairRematchTicks;
    }
    std::unique_ptr<qdojo_contract::State> port(new qdojo_contract::State());
    PortHost host;
#endif

    bool started = false;
    int failures = 0;
    auto check = [&](const char* what, long long t) {
        if (failures > 5)
            return;
        QDOJO::GetLedger_input li{};
        QDOJO::GetLedger_output lo{};
        chain->query(10, li, lo);
        bool ok = lo.balance == lo.liabilities && lo.balance >= 0 && lo.negativeCredits == 0 && lo.faults.arithmetic == 0
            && lo.faults.accountOverflow == 0 && lo.faults.pairOverflow == 0 && lo.faults.slotOverflow == 0
            && lo.faults.engine == 0 && chain->spectrumBalance() == lo.balance;
        if (!ok)
        {
            ++failures;
            ADD_FAILURE() << name << ": ledger check after " << what << " at tick " << t << ": balance " << lo.balance
                          << " liabilities " << lo.liabilities << " spectrum " << chain->spectrumBalance()
                          << " negative " << lo.negativeCredits << " faults " << lo.faults.arithmetic << "/"
                          << lo.faults.accountOverflow << "/" << lo.faults.pairOverflow << "/" << lo.faults.slotOverflow
                          << "/" << lo.faults.engine;
        }
#ifdef QDOJO_LOCKSTEP_PORT
        if (port->event_seq != chain->st().eventSeq || memcmp(port->event_digest, chain->st().eventDigest.m256i_u8, 32) != 0
            || port->balance != chain->st().balance)
        {
            ++failures;
            ADD_FAILURE() << name << ": diverged from the port after " << what << " at tick " << t << ": events "
                          << chain->st().eventSeq << " vs port " << port->event_seq << ", balance " << chain->st().balance
                          << " vs port " << port->balance;
            // First diverging retained event.
            uint64 lo2 = std::min<uint64>(port->event_seq, chain->st().eventSeq);
            uint64 ring = chain->st().m.eventRing;
            for (uint64 seq = (lo2 > ring ? lo2 - ring + 1 : 1); seq <= lo2; ++seq)
            {
                const auto& ce = chain->st().events.get((seq - 1) % ring);
                const auto& pe = port->events[(seq - 1) % port->m.event_ring];
                if (memcmp(ce.digest.m256i_u8, pe.digest, 32) != 0)
                {
                    printf("  first diverging event %llu: contract type %u body %s\n", (unsigned long long)seq, ce.type,
                        hex(&ce.body, ce.len).c_str());
                    printf("                            port type %u body %s\n", pe.type, hex(pe.body, pe.len).c_str());
                    break;
                }
            }
        }
#endif
    };

    while (failures <= 5 && std::getline(in, line))
    {
        if (line.empty())
            continue;
        JVal r = parseJson(line);
        const std::string& k = r.at("k").str;
        ++sum.records;
        if (k == "start")
        {
            uint64 t = (uint64)r.at("t").num;
            chain->initialize(manifest, t);
            EXPECT_EQ(chain->st().initOk, 1) << name << ": INITIALIZE rejected the manifest";
#ifdef QDOJO_LOCKSTEP_PORT
            EXPECT_TRUE(qdojo_contract::init(*port, pm, t));
#endif
            started = true;
            check("start", (long long)t);
        }
        else if (!started)
        {
            ADD_FAILURE() << name << ": record before start";
            break;
        }
        else if (k == "owner")
        {
            const JVal& o = r.at("owner");
            m256i fid = idOf(r.at("id").str);
            bool present = o.kind != JVal::NUL;
            m256i owner = present ? idOf(o.str) : m256i::zero();
            chain->setOwner(fid, present, owner);
#ifdef QDOJO_LOCKSTEP_PORT
            if (present)
                host.owners[PortHost::k(portId(fid))] = portId(owner);
            else
                host.owners.erase(PortHost::k(portId(fid)));
#endif
        }
        else if (k == "fail")
        {
            m256i who = idOf(r.at("who").str);
            if (r.at("on").b)
                chain->failing.insert(key(who));
            else
                chain->failing.erase(key(who));
#ifdef QDOJO_LOCKSTEP_PORT
            if (r.at("on").b)
                host.failing.insert(key(who));
            else
                host.failing.erase(key(who));
#endif
        }
        else if (k == "mint")
        {
            chain->mint(idOf(r.at("who").str), r.at("amount").num);
        }
        else if (k == "call")
        {
            std::vector<uint8_t> frame = unhex(r.at("frame").str);
            frame.resize(512, 0);  // the runtime pads/truncates to sizeof(Dispatch_input)
            uint64 t = (uint64)r.at("t").num;
            long long amount = r.at("amount").num;
            m256i who = idOf(r.at("who").str);
            system.tick = (unsigned int)t;
            QDOJO::Dispatch_output out;
            bool invoked = chain->dispatch(who, amount, frame, out);
            EXPECT_TRUE(invoked) << name << ": caller cannot pay the attachment at tick " << t;
            ++sum.calls;
            ++sum.codes[out.code];
            EXPECT_NE(out.code, QDOJO_HOST_ERROR) << name << ": host error at tick " << t;
#ifdef QDOJO_LOCKSTEP_PORT
            qdojo_contract::CallResult pr = qdojo_contract::dispatch(*port, host, portId(who), frame.data(), amount, t);
            if (pr.code != out.code || pr.op != out.op || pr.target != out.target || pr.refunded != out.refunded)
            {
                ++failures;
                ADD_FAILURE() << name << ": call result differs at tick " << t << ": contract " << (int)out.code << "/"
                              << out.op << "/" << out.target << "/" << out.refunded << " port " << (int)pr.code << "/"
                              << pr.op << "/" << pr.target << "/" << pr.refunded;
            }
#endif
            check("call", (long long)t);
        }
        else if (k == "end")
        {
            uint64 t = (uint64)r.at("t").num;
            chain->endTick(t);
            ++sum.ends;
#ifdef QDOJO_LOCKSTEP_PORT
            qdojo_contract::end_tick(*port, host, t);
            qdojo_contract::begin_tick(*port, host, t + 1);
#endif
            check("end_tick", (long long)t);
        }
        else if (k == "begin")
        {
            uint64 t = (uint64)r.at("t").num;
            chain->beginTick(t);
#ifdef QDOJO_LOCKSTEP_PORT
            qdojo_contract::begin_tick(*port, host, t);
#endif
            check("begin_tick", (long long)t);
        }
        else if (k == "digest")
        {
            sum.expectedDigest = r.at("event_digest").str;
        }
        else
        {
            ADD_FAILURE() << name << ": unknown record " << k;
            break;
        }
    }
    // The final event digest, read through the real GetService query function.
    QDOJO::GetService_input si{};
    QDOJO::GetService_output so{};
    chain->query(1, si, so);
    sum.finalDigest = hex(so.eventDigest.m256i_u8, 32);
    sum.balance = so.balance;
    sum.events = so.eventSeq;
    EXPECT_FALSE(sum.expectedDigest.empty()) << name << ": journal has no digest record";
    EXPECT_EQ(sum.finalDigest, sum.expectedDigest) << name << ": final event digest differs from the reference";

    // Bounded queries answer from the replayed state.
    QDOJO::GetEvents_input ei{ so.eventSeq > 3 ? so.eventSeq - 3 : 0, 64 };
    QDOJO::GetEvents_output eo{};
    chain->query(3, ei, eo);
    EXPECT_EQ(eo.count, (uint32)std::min<uint64>(3, so.eventSeq));
    if (eo.count)
    {
        EXPECT_EQ(eo.events.get(eo.count - 1).seq, so.eventSeq);
        EXPECT_EQ(hex(eo.events.get(eo.count - 1).digest.m256i_u8, 32), sum.finalDigest);
    }
#ifdef QDOJO_LOCKSTEP_PORT
    for (uint32 season = 1; season <= 2; ++season)
    {
        QDOJO::GetStandings_input gi{ season };
        QDOJO::GetStandings_output go{};
        chain->query(9, gi, go);
        qdojo_contract::Standings ps;
        qdojo_contract::query_standings(*port, season, system.tick, ps);
        EXPECT_EQ(go.nRows, ps.n_rows) << name << " season " << season;
        EXPECT_EQ(go.nPage, ps.n_page) << name << " season " << season;
        EXPECT_EQ(go.status, ps.status) << name << " season " << season;
        for (uint32 i = 0; i < go.nPage && i < ps.n_page; ++i)
        {
            EXPECT_EQ(memcmp(go.page.get(i).fighterId.m256i_u8, ps.page[i].fighter_id.b, 32), 0);
            EXPECT_EQ(go.page.get(i).rating, ps.page[i].rating);
            EXPECT_EQ(go.page.get(i).qualified, ps.page[i].qualified);
        }
    }
#endif

    printf("%s: %zu records, %zu calls, %zu END_TICKs, %llu events, balance %lld QU; codes", name, sum.records, sum.calls,
        sum.ends, (unsigned long long)sum.events, sum.balance);
    for (const auto& kv : sum.codes)
        printf(" %dx%d", kv.first, kv.second);
    printf("\n    final event digest %s (reference %s) %s\n", sum.finalDigest.c_str(), sum.expectedDigest.c_str(),
        sum.finalDigest == sum.expectedDigest ? "MATCH" : "MISMATCH");
    printf("    contract time: Dispatch avg %.1f us max %.1f us; END_TICK avg %.1f us max %.1f us; BEGIN_TICK avg %.1f us\n",
        chain->dispatches ? 1e6 * chain->dispatchSeconds / chain->dispatches : 0.0, 1e6 * chain->maxDispatch,
        chain->endTicks ? 1e6 * chain->endTickSeconds / chain->endTicks : 0.0, 1e6 * chain->maxEndTick,
        chain->endTicks ? 1e6 * chain->beginTickSeconds / chain->endTicks : 0.0);
    return sum;
}

}  // namespace qdojo_test

TEST(ContractQdojo, StateAndLocalsSizes)
{
    printf("sizeof(QDOJO::StateData) = %zu bytes (%.1f KiB); MAX_CONTRACT_STATE_SIZE = %llu\n", sizeof(QDOJO::StateData),
        sizeof(QDOJO::StateData) / 1024.0, (unsigned long long)MAX_CONTRACT_STATE_SIZE);
    printf("  fighters 1024 x %zu, assets 2048 x %zu, accounts 2048 x %zu, events 2048 x %zu, pairs 4096 x %zu\n",
        sizeof(QDOJO::Fighter), sizeof(QDOJO::RegistryAsset), sizeof(QDOJO::Account), sizeof(QDOJO::Event),
        sizeof(QDOJO::PairRecord));
    printf("  offers 128 x %zu, contests 32 x %zu, fights 32 x %zu, cups 8 x %zu\n", sizeof(QDOJO::Offer),
        sizeof(QDOJO::Contest), sizeof(QDOJO::Fight), sizeof(QDOJO::Cup));
    printf("locals: Ctx %zu, Dispatch %zu, END_TICK %zu, BEGIN_TICK %zu, INITIALIZE %zu (limit %u)\n", sizeof(QDOJO::Ctx),
        sizeof(QDOJO::Dispatch_locals), sizeof(QDOJO::END_TICK_locals), sizeof(QDOJO::BEGIN_TICK_locals),
        sizeof(QDOJO::INITIALIZE_locals), MAX_SIZE_OF_CONTRACT_LOCALS);
    EXPECT_LE(sizeof(QDOJO::END_TICK_locals), (size_t)MAX_SIZE_OF_CONTRACT_LOCALS);
    EXPECT_LE(sizeof(QDOJO::StateData), (size_t)MAX_CONTRACT_STATE_SIZE);

    // Core rehashes a dirty state with K12 at the end of the tick; END_TICK
    // dirties QDOJO's state every tick. Time that digest for this state size.
    std::vector<unsigned char> buf(sizeof(QDOJO::StateData), 0x5a);
    unsigned char digest[32];
    auto t0 = std::chrono::steady_clock::now();
    const int reps = 20;
    for (int i = 0; i < reps; ++i)
    {
        buf[i] ^= 1;
        KangarooTwelve(buf.data(), (unsigned int)buf.size(), digest, 32);
    }
    auto t1 = std::chrono::steady_clock::now();
    printf("K12 over %zu state bytes: %.1f us per digest (this host, %d reps)\n", buf.size(),
        1e6 * std::chrono::duration<double>(t1 - t0).count() / reps, reps);
}

TEST(ContractQdojo, InitializeWithCompiledManifest)
{
    qdojo_test::QdojoChain chain;
    chain.initializeCompiled(1000);
    EXPECT_EQ(chain.st().initOk, 1);
    EXPECT_EQ(chain.st().generation, 1u);
    EXPECT_EQ(chain.st().lastServiced, 1000u);
    EXPECT_EQ(chain.st().nSlots, 4u);  // admin + house + dev + share
    EXPECT_TRUE(chain.st().m.contractId == m256i(QDOJO_CONTRACT_INDEX, 0, 0, 0));
}

TEST(ContractQdojo, ReplayScenarios)
{
    qdojo_test::replay("scenarios.journal");
}

TEST(ContractQdojo, ReplayFuzz1)
{
    qdojo_test::replay("fuzz-1.journal");
}

TEST(ContractQdojo, ReplayFuzz2)
{
    qdojo_test::replay("fuzz-2.journal");
}

TEST(ContractQdojo, ReplaySeason)
{
    qdojo_test::replay("season.journal");
}

// Non-default pair limits (6 starts per epoch, 60-tick rematch gap) from the header.
TEST(ContractQdojo, ReplayDemoProfile)
{
    qdojo_test::replay("demo-profile.journal");
}
