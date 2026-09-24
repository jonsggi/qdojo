// qdojo combat contract: C++ port of the reference state machine
// (packages/qdojo/src/qdojo/combat/contract.py with ledger.py, matchmaking.py,
// series.py, rating.py and codec.py), in the shape a Qubic contract needs.
//
// Entry points mirror the chain runtime:
//   init(state, manifest, construction_tick)          INITIALIZE
//   begin_tick(state, host, T)                         BEGIN_TICK
//   dispatch(state, host, invocator, frame, amount, T) the single Dispatch user procedure
//   end_tick(state, host, T)                           END_TICK
//   query_* (const state, ...)                         read-only user functions
//
// The host supplies exactly two capabilities: the live owner of a registry
// asset (Host::owner_of, the QPI asset-ownership query on chain) and an
// outgoing QU transfer (Host::transfer, qpi.transfer on chain). Nothing else
// leaves the state struct.
//
// Contract restrictions followed (see README.md for what is NOT yet verified):
//   - header-only; includes only <stdint.h> and the combat core headers
//   - no heap, no STL, no exceptions, no RTTI use, no floating point
//   - no global mutable state: everything lives in `State`
//   - fixed-capacity arrays sized by the manifest's candidate capacities;
//     every loop is bounded by a compile-time capacity
//   - QU arithmetic is checked signed 64-bit; tick arithmetic is checked u64.
//     A checked failure never wraps: it saturates and increments
//     State::faults, which the parity test asserts stays zero.
//
// Bounded-state decisions the unbounded Python reference does not make are
// listed in README.md ("Where the port must bound what the reference does
// not"). None of them is reached by the parity journals.
#ifndef QDOJO_COMBAT_CONTRACT_H
#define QDOJO_COMBAT_CONTRACT_H

#include <stdint.h>

#include "../combat_core/combat_core.h"
#include "../combat_core/sha256.h"

namespace qdojo_contract {

// ------------------------------------------------------------ capacities
static constexpr uint32_t CAP_FIGHTERS = 1024;
static constexpr uint32_t CAP_ACCOUNTS = 2048;      // unified nonce + credit slots
static constexpr uint32_t CAP_ASSETS = 2048;        // admin-registered registry assets
static constexpr uint32_t CAP_OPEN_OFFERS = 64;     // OPEN offers (manifest max_offers)
static constexpr uint32_t CAP_OFFER_SLOTS = 128;    // OPEN plus recently terminal offers
static constexpr uint32_t CAP_FIGHTS = 16;          // active fights (manifest max_fights)
static constexpr uint32_t CAP_FIGHT_SLOTS = 32;     // active plus recently terminal fights
static constexpr uint32_t CAP_CONTEST_SLOTS = 32;   // active plus recently terminal contests
static constexpr uint32_t CAP_CUPS = 4;             // live cups (manifest max_cups)
static constexpr uint32_t CAP_CUP_SLOTS = 8;        // live plus recently terminal cups
static constexpr uint32_t CAP_CUP_ENTRANTS = 16;
static constexpr uint32_t CAP_PAIRINGS = 16;        // 8 + 4 + 2 + 1 for a 16-slot bracket
static constexpr uint32_t CAP_EVENTS = 2048;
static constexpr uint32_t CAP_PAIRS = 4096;         // ranked pair history (starts per epoch, last result)
static constexpr uint32_t CAP_TIMING = 4;
static constexpr uint32_t CAP_FEES = 4;
static constexpr uint32_t CAP_TIERS = 8;
static constexpr uint32_t EVENT_BODY_MAX = 112;     // largest canonical body is REVEALED, 98 bytes
static constexpr uint32_t STANDINGS_PAGE = 16;

// ------------------------------------------------------------ protocol constants
static constexpr uint32_t FRAME_LEN = 512;
static constexpr uint32_t FRAME_HEADER = 24;
static constexpr uint32_t MAX_BODY = FRAME_LEN - FRAME_HEADER - 1;  // 487
static constexpr uint8_t FRAME_SENTINEL = 0xA5;
static constexpr int64_t MAX_STAKE = 1000000000000LL;
static constexpr int64_t I64_MAX = 0x7fffffffffffffffLL;
static constexpr int64_t BPS = 10000;

// rating.py
static constexpr int64_t RATING_INITIAL = 1000;
static constexpr int64_t RATING_CEILING = 3000;
static constexpr uint32_t PLACEMENT_FIGHTS = 10;
static constexpr int64_t SCORE_WIN = 2000, SCORE_DRAW = 1000, SCORE_LOSS = 0;

// matchmaking.py
static constexpr uint64_t BASE_WINDOW = 100;
static constexpr uint64_t WIDEN_STEP = 50;
static constexpr uint64_t WIDEN_TICKS = 40;
static constexpr uint16_t MAX_GAP_LO = 100, MAX_GAP_HI = 200;
static constexpr uint32_t PASS_SNAPSHOT = 64;
static constexpr uint32_t PASS_MATCHES = 4;
// Anti-farming pair limits are manifest values (Manifest::pair_starts_per_epoch,
// Manifest::pair_rematch_ticks); matchmaking.md specifies 2 and 120.

// Result codes (docs/protocol.md section 6). HOST_ERROR is not a protocol
// code: it marks a call the runtime can never produce (ticks running
// backwards, an attachment that overflows the balance) and mutates nothing.
enum Code : uint8_t {
    OK = 0, DUPLICATE = 1, BAD_FRAME = 2, BAD_OPCODE = 3, BAD_BODY = 4, BAD_AMOUNT = 5,
    UNKNOWN_FIGHTER = 6, NOT_OWNER = 7, NOT_OPERATOR = 8, STALE_AUTH = 9, FIGHTER_BUSY = 10,
    COOLDOWN = 11, FULL = 12, NONCE_CONFLICT = 13, STALE = 14, NOT_FOUND = 15, EXPIRED = 16,
    ALREADY_MATCHED = 17, INCOMPATIBLE = 18, RULESET_RETIRED = 19, WRONG_PHASE = 20, LATE = 21,
    ALREADY_COMMITTED = 22, BAD_STATE = 23, BAD_COMMITMENT = 24, BAD_PLAN = 25, ALREADY_REVEALED = 26,
    TERMINAL = 27, SERVICE_VOID = 28, TRANSFER_FAILED = 29, HOST_ERROR = 255,
};

enum Op : uint16_t {
    OP_REGISTER_FIGHTER = 1, OP_SET_OPERATOR = 2, OP_QUEUE_ENTER = 3, OP_QUEUE_CANCEL = 4,
    OP_DUEL_OFFER = 5, OP_DUEL_ACCEPT = 6, OP_COMMIT = 7, OP_REVEAL = 8, OP_ADVANCE = 9,
    OP_WITHDRAW = 10, OP_CUP_REGISTER = 11, OP_CUP_WITHDRAW = 12, OP_CUP_CHECK_IN = 13,
    OP_DUEL_CANCEL = 14, OP_ADMIN_REGISTER_ASSET = 100, OP_ADMIN_CREATE_CUP = 101,
    OP_ADMIN_RETIRE_RULESET = 102,
};

// Event type numbers: contract.py EVENT_TYPES.
enum EventType : uint16_t {
    EV_SERVICE_GAP = 1, EV_FIGHTER_REGISTERED = 2, EV_OPERATOR_SET = 3, EV_OFFER_OPEN = 4,
    EV_OFFER_CLOSED = 5, EV_MATCHED = 6, EV_DUEL_ACCEPTED = 7, EV_FIGHT_CREATED = 8,
    EV_COMMITTED = 9, EV_REVEALED = 10, EV_ROUND_RESOLVED = 11, EV_FIGHT_ENDED = 12,
    EV_CONTEST_SETTLED = 13, EV_RATING = 14, EV_FAULT = 15, EV_WITHDRAWN = 16,
    EV_WITHDRAW_FAILED = 17, EV_CUP_CREATED = 18, EV_CUP_ENTRY = 19, EV_CUP_BRACKET = 20,
    EV_CUP_LEVEL = 21, EV_CUP_PAIRING = 22, EV_CUP_FINISHED = 23, EV_ASSET_REGISTERED = 24,
    EV_RULESET_RETIRED = 25, EV_REFUND_CREDIT = 26, EV_CUP_WITHDRAWN = 27, EV_CUP_CHECKED_IN = 28,
    EV_CUP_REPLAY_SCHEDULED = 29,
};

enum Lock : uint8_t { L_IDLE = 0, L_QUEUED = 1, L_DUEL_OFFER = 2, L_CONTEST = 3, L_TOURNAMENT = 4 };
enum OfferStatus : uint8_t { O_OPEN = 1, O_MATCHED = 2, O_CANCELLED = 3, O_EXPIRED = 4, O_INVALIDATED = 5 };
enum OfferKind : uint8_t { K_RANKED = 0, K_DUEL = 1 };
enum Mode : uint8_t { M_RANKED = 0, M_DUEL = 1, M_CUP = 2, M_EXHIBITION = 3 };
enum Format : uint8_t { F_SINGLE = 0, F_BO3 = 1, F_BO5 = 2 };
enum Phase : uint8_t { P_COMMIT = 1, P_REVEAL = 2, P_DONE = 3 };
enum ResultKind : uint8_t { R_NONE = 0, R_COMBAT = 1, R_FORFEIT = 2, R_DOUBLE_FAULT = 3, R_VOID = 4 };
enum Side : uint8_t { S_NONE = 0, S_A = 1, S_B = 2 };
enum ContestStatus : uint8_t { C_ACTIVE = 1, C_DONE = 2 };
enum CupStatus : uint8_t { CUP_REGISTRATION = 1, CUP_RUNNING = 2, CUP_COMPLETE = 3, CUP_CANCELLED = 4, CUP_ABORTED = 5 };
enum PairingStatus : uint8_t { PS_SCHEDULED = 1, PS_PLAYING = 2, PS_REPLAY_WAIT = 3, PS_DONE = 4, PS_UNRESOLVED = 5, PS_EMPTY = 6 };
enum AbortWhy : uint8_t { AB_SERVICE_VOID = 1, AB_EXPIRED = 2, AB_CAPACITY = 3, AB_NO_CHAMPION = 4 };

// ------------------------------------------------------------ identities
struct Id {
    uint8_t b[32];
};

inline bool id_eq(const Id& x, const Id& y) {
    for (uint32_t i = 0; i < 32; ++i)
        if (x.b[i] != y.b[i]) return false;
    return true;
}
// Unsigned lexicographic order, as Python compares bytes.
inline int id_cmp(const Id& x, const Id& y) {
    for (uint32_t i = 0; i < 32; ++i)
        if (x.b[i] != y.b[i]) return x.b[i] < y.b[i] ? -1 : 1;
    return 0;
}
inline Id id_zero() {
    Id z;
    for (uint32_t i = 0; i < 32; ++i) z.b[i] = 0;
    return z;
}
inline void copy32(uint8_t* dst, const uint8_t* src) {
    for (uint32_t i = 0; i < 32; ++i) dst[i] = src[i];
}
inline bool eq32(const uint8_t* x, const uint8_t* y) {
    for (uint32_t i = 0; i < 32; ++i)
        if (x[i] != y[i]) return false;
    return true;
}

// ------------------------------------------------------------ host
// Implemented by the QPI adapter (qpi_adapter.h) and by the test's fake chain.
struct Host {
    // The live owner of the registry asset behind fighter_id. Return false
    // when ownership is unavailable; the contract never guesses an owner.
    virtual bool owner_of(const Id& fighter_id, Id& owner_out) = 0;
    // Pay `amount` QU from the contract to `to`. Return false on a reported
    // failure; the contract then restores the debited credit.
    virtual bool transfer(const Id& to, int64_t amount) = 0;

   protected:
    ~Host() {}
};

// ------------------------------------------------------------ manifest
struct TimingProfile {
    uint32_t id;
    uint16_t commit_ticks;
    uint16_t reveal_ticks;
    uint8_t used;
};

struct FeeProfile {
    uint32_t id;
    uint16_t rake_bps, house_bps, dev_bps, share_bps;
    Id house, dev, share;
    uint8_t used;
};

struct Tier {
    uint16_t id;
    int64_t stake;
    uint8_t used;
};

// Deployment values (contract.py Manifest). On chain these are compiled-in
// constants from the reviewed release manifest; the test loads them from the
// journal header.
struct Manifest {
    Id network_id, contract_id, admin;
    uint8_t ruleset_digest[32];
    TimingProfile timing[CAP_TIMING];
    FeeProfile fees[CAP_FEES];
    Tier tiers[CAP_TIERS];
    int64_t genesis_tick, genesis_epoch, ticks_per_epoch;
    int64_t season_start_epoch, season_epochs, season_closeout_ticks;
    uint32_t max_fighters, max_accounts, max_offers, max_fights, max_cups, max_cup_entrants, event_ring;
    uint32_t match_interval;
    uint64_t offer_lifetime_lo, offer_lifetime_hi;
    uint64_t cooldown_ticks;
    uint32_t faults_per_epoch;
    uint32_t pair_starts_per_epoch;   // ranked starts per pair per epoch (spec: 2)
    uint64_t pair_rematch_ticks;      // minimum gap after a pair's last result (spec: 120)
};

// ------------------------------------------------------------ records
struct SeasonSlot {           // one season's rating and qualification stats
    uint32_t season;          // 0 = slot unused
    uint8_t has_rating;
    uint8_t has_stats;
    uint16_t rating;
    uint32_t fights, wins, final_epoch_fights;
    uint16_t defeated;        // exact distinct defeated opponents (tiebreak)
    uint8_t opponents;        // distinct opponents, saturating at 4 (only >= 4 is read)
    uint16_t opponent_idx[4];
    uint64_t defeated_bits[CAP_FIGHTERS / 64];
};

struct Fighter {
    Id fighter_id, owner, op;
    uint32_t auth_version;
    uint8_t house_npc;
    uint8_t lock;
    uint64_t lock_ref;
    uint16_t lifetime;
    uint32_t placement;
    int64_t fault_epoch;
    uint32_t fault_count;     // terminal faults in fault_epoch
    uint64_t cooldown_until;
    int64_t suspended_epoch;
    uint32_t rec_w, rec_d, rec_l, rec_fw, rec_fl;
    SeasonSlot seasons[2];    // indexed by season % 2: current and previous
};

struct Asset {
    Id fighter_id;
    uint32_t registry_version;
    uint8_t house_npc;
    uint8_t used;
};

struct Account {
    Id who;
    int64_t credit;           // withdrawable QU
    uint8_t used;
    uint8_t slot;             // holds an account slot (contract.py self.accounts); never released
    uint8_t has_nonce;
    uint16_t last_op;
    uint64_t nonce;           // last accepted nonce
    uint8_t digest[32];       // SHA-256 of the last accepted frame
    uint64_t last_target;     // stored result target for identical retries
};

struct Offer {
    uint64_t offer_id;
    uint16_t fighter_idx;
    Id fighter_id, owner, op, payer, payout;
    uint32_t auth_version;
    uint32_t timing_id, fee_id;
    uint16_t tier_id;
    int64_t amount;
    uint16_t rating;
    uint16_t max_gap;
    uint64_t created, expires, generation;
    uint8_t status, kind;
    Id opponent_id;
    uint8_t series_format;
    uint64_t contest_id;
    uint8_t escrowed;         // ledger.offers holds (payer, amount)
    uint8_t used;
};

struct Participant {
    Id fighter_id, owner, op;
    uint32_t auth_version;
    Id payout;
    uint16_t lifetime, season_rating;
};

struct Series {
    uint8_t need, cap, wins_a, wins_b, fights;
};

struct Contest {
    uint64_t contest_id;
    uint8_t mode, fmt, status, replay;
    Participant a, b;
    uint16_t a_idx, b_idx;
    Id payer_a, payer_b;
    int64_t pot_a, pot_b;     // ledger.contests; both zero and has_pot=0 when settled
    uint8_t has_pot;
    int64_t stake;
    uint32_t fee_id, timing_id;
    uint64_t generation, start_tick;
    uint32_t season;
    Series series;
    uint64_t cup_id, pairing_id;
    uint64_t current_fight;
    uint8_t result_kind, result_winner;
    uint8_t has_starts_key;
    int64_t starts_epoch;
    uint8_t used;
};

struct Fight {
    uint64_t fight_id, contest_id;
    uint8_t phase;
    uint16_t commit_ticks, reveal_ticks;
    uint64_t start_tick, commit_last, reveal_last;
    uint8_t context_digest[32];
    uint8_t round_state_digest[32];   // cached for the current round start
    qdojo_combat::FightState state;
    uint8_t committed[2];
    uint8_t commitment[2][32];
    uint8_t revealed[2];
    uint8_t salt[2][32];
    qdojo_combat::Plan plan[2];
    uint8_t result_kind, result_winner;
    uint8_t used;
};

struct CupEntry {
    Id fighter_id, payer, owner, op;
    uint16_t fighter_idx;
    int64_t amount;
};

struct Pairing {
    uint64_t pairing_id;
    uint8_t level;
    Id a, b;
    uint8_t has_a, has_b;
    uint8_t checked_a, checked_b;
    uint64_t contest_id;
    Id winner;
    uint8_t has_winner;
    uint8_t status;
    uint64_t replay_at;
    Id final_owner;
    uint8_t has_final_owner;
};

struct CupDescriptor {
    uint32_t timing_id, fee_id;
    int64_t entry_fee;
    uint64_t registration_close;
    uint8_t min_entrants, max_entrants;
    uint16_t level_ticks, first_level_delay, checkin_ticks, replay_delay;
};

struct Cup {
    uint64_t cup_id;
    CupDescriptor d;
    Id sponsor;
    int64_t sponsorship;
    uint64_t generation, created;
    CupEntry entries[CAP_CUP_ENTRANTS];
    uint8_t n_entries;
    uint8_t status;
    uint8_t levels, level;
    uint64_t level_start;
    uint16_t postponed_mask;
    uint8_t pending_reservation;
    uint32_t reserved;
    Pairing pairings[CAP_PAIRINGS];   // pairing_id - 1
    uint8_t n_pairings;
    Id slots[CAP_CUP_ENTRANTS];
    uint8_t slot_used[CAP_CUP_ENTRANTS];
    uint8_t n_slots;
    Id champion;
    uint32_t combat_fights;
    uint64_t expiry_tick;
    uint8_t has_pot;          // ledger.cups: sponsorship + entries while live
    uint8_t used;
};

struct PairRecord {           // ranked pair history keyed by unordered fighter indices
    uint16_t lo, hi;
    int64_t epoch;
    uint32_t starts;          // ranked starts in `epoch`
    uint64_t last;            // tick of the last ranked result
    uint8_t has_last;
    uint8_t used;
};

struct Event {
    uint64_t seq, tick;
    uint16_t type;
    uint16_t len;
    uint8_t digest[32];
    uint8_t body[EVENT_BODY_MAX];
};

// Per-entry-point work counters, reset at every entry point. The parity test
// records their maxima; the QPI cost model needs them (README.md).
struct Work {
    uint32_t sha_blocks;      // SHA-256 compression blocks
    uint32_t events;
    uint32_t fights;          // fights advanced in END_TICK
    uint32_t comparisons;     // matching compatibility checks
    uint32_t scan_steps;      // table slots visited by linear lookups
    uint32_t owner_queries;   // Host::owner_of calls
    uint32_t transfers;       // Host::transfer calls
};

struct Faults {               // must stay zero; see README.md
    uint32_t arithmetic;
    uint32_t account_overflow;
    uint32_t pair_overflow;
    uint32_t slot_overflow;
    uint32_t engine;
};

struct State {
    Manifest m;
    // ledger
    int64_t balance;
    int64_t paid_out;
    int64_t overflow_credit;  // credits that found no account slot (fault)
    uint32_t credit_count;    // accounts holding a positive credit (len(ledger.credits))
    uint32_t n_slots;         // len(self.accounts): slot holders, bounded by manifest max_accounts
    // service heartbeat
    uint64_t generation;
    uint64_t last_serviced, last_observed, tick;
    // ids
    uint64_t next_offer, next_contest, next_fight, next_cup;
    // registry
    uint8_t ruleset_retired;
    uint32_t n_fighters;
    Fighter fighters[CAP_FIGHTERS];
    Asset assets[CAP_ASSETS];
    Account accounts[CAP_ACCOUNTS];
    Offer offers[CAP_OFFER_SLOTS];
    Contest contests[CAP_CONTEST_SLOTS];
    Fight fights[CAP_FIGHT_SLOTS];
    Cup cups[CAP_CUP_SLOTS];
    PairRecord pairs[CAP_PAIRS];
    // events
    uint64_t event_seq;
    uint8_t event_digest[32];
    Event events[CAP_EVENTS];
    Work work;
    Faults faults;
};

struct CallResult {
    uint8_t code;
    uint16_t op;
    uint64_t target;
    int64_t refunded;
};

// ============================================================ internals
namespace detail {

// ---- checked arithmetic --------------------------------------------------
inline int64_t add_i64(State& s, int64_t x, int64_t y) {
    if ((y > 0 && x > I64_MAX - y) || (y < 0 && x < -I64_MAX - 1 - y)) {
        ++s.faults.arithmetic;
        return y > 0 ? I64_MAX : -I64_MAX - 1;
    }
    return x + y;
}
inline int64_t sub_i64(State& s, int64_t x, int64_t y) {
    if (y == -I64_MAX - 1) {
        ++s.faults.arithmetic;
        return I64_MAX;
    }
    return add_i64(s, x, -y);
}
inline int64_t mul_i64(State& s, int64_t x, int64_t y) {   // nonnegative operands only
    if (x < 0 || y < 0 || (x != 0 && y > I64_MAX / x)) {
        ++s.faults.arithmetic;
        return I64_MAX;
    }
    return x * y;
}
inline uint64_t add_u64(State& s, uint64_t x, uint64_t y) {
    if (x > ~uint64_t(0) - y) {
        ++s.faults.arithmetic;
        return ~uint64_t(0);
    }
    return x + y;
}
inline int64_t floordiv(int64_t x, int64_t y) {  // y > 0
    int64_t q = x / y;
    if ((x % y) != 0 && x < 0) --q;
    return q;
}

// ---- time ------------------------------------------------------------------
inline int64_t epoch_of(const State& s, uint64_t t) {
    return s.m.genesis_epoch + floordiv(int64_t(t) - s.m.genesis_tick, s.m.ticks_per_epoch);
}
inline uint32_t season_of(const State& s, uint64_t t) {
    int64_t e = epoch_of(s, t);
    if (e < s.m.season_start_epoch) return 0;
    return uint32_t(1 + floordiv(e - s.m.season_start_epoch, s.m.season_epochs));
}

// ---- hashing ---------------------------------------------------------------
inline uint32_t blocks_for(uint32_t len) { return (len + 9 + 63) / 64; }

inline void sha(State& s, const uint8_t* data, uint32_t len, uint8_t out[32]) {
    s.work.sha_blocks += blocks_for(len);
    qdojo_combat::sha256(data, len, out);
}

static constexpr char TAG_EVENT[] = "qdojo/combat/event/v1";
static constexpr char TAG_EVENT_GENESIS[] = "qdojo/combat/event/genesis/v1";

// ---- canonical event bodies (contract.py _event_body) -----------------------
struct Body {
    uint8_t b[160];
    uint32_t n;
};
inline void b_u64(Body& x, uint64_t v) {
    x.b[x.n++] = 0;
    for (uint32_t i = 0; i < 8; ++i) x.b[x.n++] = uint8_t(v >> (8 * i));
}
inline void b_bytes(Body& x, const uint8_t* p, uint16_t len) {
    x.b[x.n++] = 1;
    x.b[x.n++] = uint8_t(len & 0xff);
    x.b[x.n++] = uint8_t(len >> 8);
    for (uint32_t i = 0; i < len; ++i) x.b[x.n++] = p[i];
}
inline void b_id(Body& x, const Id& id) { b_bytes(x, id.b, 32); }
inline void b_str(Body& x, const char* str) {
    uint8_t len = 0;
    while (len < 32 && str[len]) ++len;
    x.b[x.n++] = 2;
    x.b[x.n++] = len;
    for (uint32_t i = 0; i < len; ++i) x.b[x.n++] = uint8_t(str[i]);
}

inline const char* offer_status_str(uint8_t st) {
    switch (st) {
        case O_OPEN: return "OPEN";
        case O_MATCHED: return "MATCHED";
        case O_CANCELLED: return "CANCELLED";
        case O_EXPIRED: return "EXPIRED";
        default: return "INVALIDATED";
    }
}
inline const char* kind_str(uint8_t k) {
    switch (k) {
        case R_COMBAT: return "COMBAT";
        case R_FORFEIT: return "FORFEIT";
        case R_DOUBLE_FAULT: return "DOUBLE_FAULT";
        default: return "VOID";
    }
}
inline const char* side_str(uint8_t w) { return w == S_A ? "A" : w == S_B ? "B" : "-"; }
inline const char* pairing_status_str(uint8_t st) {
    switch (st) {
        case PS_SCHEDULED: return "SCHEDULED";
        case PS_PLAYING: return "PLAYING";
        case PS_REPLAY_WAIT: return "REPLAY_WAIT";
        case PS_DONE: return "DONE";
        case PS_UNRESOLVED: return "UNRESOLVED";
        default: return "EMPTY";
    }
}
inline const char* abort_str(uint8_t why) {
    switch (why) {
        case AB_SERVICE_VOID: return "SERVICE_VOID";
        case AB_EXPIRED: return "EXPIRED";
        case AB_CAPACITY: return "CAPACITY";
        default: return "NO_CHAMPION";
    }
}

// event_digest = SHA256("qdojo/combat/event/v1\0" || previous[32] || seq u64 || type u16 || body)
inline void emit(State& s, uint16_t type, const Body& body) {
    s.event_seq += 1;
    qdojo_combat::Sha256 h;
    qdojo_combat::sha256_init(h);
    qdojo_combat::sha256_update_tag(h, TAG_EVENT, sizeof(TAG_EVENT));
    qdojo_combat::sha256_update(h, s.event_digest, 32);
    qdojo_combat::put_u64le(h, s.event_seq);
    uint8_t tb[2] = {uint8_t(type & 0xff), uint8_t(type >> 8)};
    qdojo_combat::sha256_update(h, tb, 2);
    qdojo_combat::sha256_update(h, body.b, body.n);
    qdojo_combat::sha256_final(h, s.event_digest);
    s.work.sha_blocks += blocks_for(uint32_t(sizeof(TAG_EVENT)) + 32 + 8 + 2 + body.n);
    s.work.events += 1;
    Event& e = s.events[(s.event_seq - 1) % s.m.event_ring];
    e.seq = s.event_seq;
    e.tick = s.tick;
    e.type = type;
    uint32_t n = body.n < EVENT_BODY_MAX ? body.n : EVENT_BODY_MAX;
    e.len = uint16_t(n);
    for (uint32_t i = 0; i < EVENT_BODY_MAX; ++i) e.body[i] = i < n ? body.b[i] : 0;
    copy32(e.digest, s.event_digest);
}

// ---- lookups -----------------------------------------------------------------
inline int32_t fighter_index(State& s, const Id& id) {
    for (uint32_t i = 0; i < CAP_FIGHTERS; ++i) {
        if (i >= s.n_fighters) break;
        ++s.work.scan_steps;
        if (id_eq(s.fighters[i].fighter_id, id)) return int32_t(i);
    }
    return -1;
}

inline int32_t asset_index(State& s, const Id& id) {
    for (uint32_t i = 0; i < CAP_ASSETS; ++i) {
        ++s.work.scan_steps;
        if (s.assets[i].used && id_eq(s.assets[i].fighter_id, id)) return int32_t(i);
    }
    return -1;
}

inline int32_t account_index(State& s, const Id& who) {
    for (uint32_t i = 0; i < CAP_ACCOUNTS; ++i) {
        ++s.work.scan_steps;
        if (s.accounts[i].used && id_eq(s.accounts[i].who, who)) return int32_t(i);
    }
    return -1;
}

// A table entry is reusable when it is not a slot holder and holds no credit
// (credit-only entries come from a failed direct payback).
inline int32_t account_free_slot(State& s) {
    for (uint32_t i = 0; i < CAP_ACCOUNTS; ++i) {
        ++s.work.scan_steps;
        const Account& a = s.accounts[i];
        if (!a.used || (!a.slot && a.credit == 0)) return int32_t(i);
    }
    return -1;
}

inline int32_t account_get_or_alloc(State& s, const Id& who) {
    int32_t i = account_index(s, who);
    if (i >= 0) return i;
    i = account_free_slot(s);
    if (i < 0) return -1;
    Account& a = s.accounts[i];
    a.who = who;
    a.credit = 0;
    a.used = 1;
    a.slot = 0;
    a.has_nonce = 0;
    a.last_op = 0;
    a.nonce = 0;
    for (uint32_t k = 0; k < 32; ++k) a.digest[k] = 0;
    a.last_target = 0;
    return i;
}

inline int32_t offer_slot(State& s, uint64_t id) {
    for (uint32_t i = 0; i < CAP_OFFER_SLOTS; ++i) {
        ++s.work.scan_steps;
        if (s.offers[i].used && s.offers[i].offer_id == id) return int32_t(i);
    }
    return -1;
}
inline int32_t contest_slot(State& s, uint64_t id) {
    for (uint32_t i = 0; i < CAP_CONTEST_SLOTS; ++i) {
        ++s.work.scan_steps;
        if (s.contests[i].used && s.contests[i].contest_id == id) return int32_t(i);
    }
    return -1;
}
inline int32_t fight_slot(State& s, uint64_t id) {
    for (uint32_t i = 0; i < CAP_FIGHT_SLOTS; ++i) {
        ++s.work.scan_steps;
        if (s.fights[i].used && s.fights[i].fight_id == id) return int32_t(i);
    }
    return -1;
}
inline int32_t cup_slot(State& s, uint64_t id) {
    for (uint32_t i = 0; i < CAP_CUP_SLOTS; ++i) {
        ++s.work.scan_steps;
        if (s.cups[i].used && s.cups[i].cup_id == id) return int32_t(i);
    }
    return -1;
}

// New record slots: a free slot, else the lowest-id terminal record is
// evicted (terminal records carry no liability or lock). -1 only if every
// slot is live, which the admission capacities rule out.
inline int32_t new_offer_slot(State& s) {
    int32_t best = -1;
    for (uint32_t i = 0; i < CAP_OFFER_SLOTS; ++i) {
        ++s.work.scan_steps;
        const Offer& o = s.offers[i];
        if (!o.used) return int32_t(i);
        if (o.status != O_OPEN && !o.escrowed && (best < 0 || o.offer_id < s.offers[best].offer_id))
            best = int32_t(i);
    }
    if (best < 0) ++s.faults.slot_overflow;
    return best;
}
inline int32_t new_contest_slot(State& s) {
    int32_t best = -1;
    for (uint32_t i = 0; i < CAP_CONTEST_SLOTS; ++i) {
        ++s.work.scan_steps;
        const Contest& c = s.contests[i];
        if (!c.used) return int32_t(i);
        if (c.status == C_DONE && !c.has_pot && (best < 0 || c.contest_id < s.contests[best].contest_id))
            best = int32_t(i);
    }
    if (best < 0) ++s.faults.slot_overflow;
    return best;
}
inline int32_t new_fight_slot(State& s) {
    int32_t best = -1;
    for (uint32_t i = 0; i < CAP_FIGHT_SLOTS; ++i) {
        ++s.work.scan_steps;
        const Fight& f = s.fights[i];
        if (!f.used) return int32_t(i);
        if (f.phase == P_DONE && (best < 0 || f.fight_id < s.fights[best].fight_id)) best = int32_t(i);
    }
    if (best < 0) ++s.faults.slot_overflow;
    return best;
}
inline int32_t new_cup_slot(State& s) {
    int32_t best = -1;
    for (uint32_t i = 0; i < CAP_CUP_SLOTS; ++i) {
        ++s.work.scan_steps;
        const Cup& c = s.cups[i];
        if (!c.used) return int32_t(i);
        if (c.status != CUP_REGISTRATION && c.status != CUP_RUNNING && !c.has_pot &&
            (best < 0 || c.cup_id < s.cups[best].cup_id))
            best = int32_t(i);
    }
    if (best < 0) ++s.faults.slot_overflow;
    return best;
}

inline const TimingProfile* timing(const State& s, uint32_t id) {
    for (uint32_t i = 0; i < CAP_TIMING; ++i)
        if (s.m.timing[i].used && s.m.timing[i].id == id) return &s.m.timing[i];
    return nullptr;
}
inline const FeeProfile* fee(const State& s, uint32_t id) {
    for (uint32_t i = 0; i < CAP_FEES; ++i)
        if (s.m.fees[i].used && s.m.fees[i].id == id) return &s.m.fees[i];
    return nullptr;
}
inline const Tier* tier(const State& s, uint16_t id) {
    for (uint32_t i = 0; i < CAP_TIERS; ++i)
        if (s.m.tiers[i].used && s.m.tiers[i].id == id) return &s.m.tiers[i];
    return nullptr;
}
inline int64_t min_tier_stake(const State& s) {
    int64_t best = I64_MAX;
    for (uint32_t i = 0; i < CAP_TIERS; ++i)
        if (s.m.tiers[i].used && s.m.tiers[i].stake < best) best = s.m.tiers[i].stake;
    return best;
}

inline bool owner_of(State& s, Host& h, const Id& fid, Id& out) {
    ++s.work.owner_queries;
    return h.owner_of(fid, out);
}
inline bool transfer(State& s, Host& h, const Id& to, int64_t amount) {
    ++s.work.transfers;
    return h.transfer(to, amount);
}

// ---- ledger (ledger.py) ------------------------------------------------------
inline void credit(State& s, const Id& who, int64_t amount) {
    if (!amount) return;
    int32_t i = account_get_or_alloc(s, who);
    if (i < 0) {
        // No slot: keep the liability rather than lose it (README.md).
        ++s.faults.account_overflow;
        s.overflow_credit = add_i64(s, s.overflow_credit, amount);
        return;
    }
    Account& a = s.accounts[i];
    if (a.credit == 0) ++s.credit_count;
    a.credit = add_i64(s, a.credit, amount);
}

// ---- fighters ------------------------------------------------------------------
inline SeasonSlot& season_slot(Fighter& f, uint32_t season) { return f.seasons[season % 2]; }

inline uint16_t rating_in(const Fighter& f, uint32_t season) {
    const SeasonSlot& sl = f.seasons[season % 2];
    if (season != 0 && sl.season == season && sl.has_rating) return sl.rating;
    return uint16_t(RATING_INITIAL);
}

// Claim the slot for `season`, clearing an older season's data.
inline SeasonSlot& season_claim(Fighter& f, uint32_t season) {
    SeasonSlot& sl = season_slot(f, season);
    if (sl.season != season) {
        sl.season = season;
        sl.has_rating = 0;
        sl.has_stats = 0;
        sl.rating = uint16_t(RATING_INITIAL);
        sl.fights = sl.wins = sl.final_epoch_fights = 0;
        sl.defeated = 0;
        sl.opponents = 0;
        for (uint32_t i = 0; i < 4; ++i) sl.opponent_idx[i] = 0;
        for (uint32_t i = 0; i < CAP_FIGHTERS / 64; ++i) sl.defeated_bits[i] = 0;
    }
    return sl;
}

// ---- pair history (contract.py pair_starts / pair_last) ------------------------
// An entry is semantically absent once it can no longer affect matching:
// its starts are for an older epoch (or zero) and its last result is older
// than the rematch interval. Such entries are reused.
inline bool pair_stale(const PairRecord& p, int64_t epoch, uint64_t t, uint64_t rematch_ticks) {
    bool starts_dead = p.starts == 0 || p.epoch != epoch;
    bool last_dead = !p.has_last || t - p.last >= rematch_ticks;
    return starts_dead && last_dead;
}

inline uint32_t pair_hash(uint16_t lo, uint16_t hi) {
    return (uint32_t(lo) * 2654435761u ^ uint32_t(hi) * 40503u) % CAP_PAIRS;
}

// Find (or, with create, claim) the record for fighter indices x, y.
inline int32_t pair_find(State& s, uint16_t x, uint16_t y, bool create, int64_t epoch, uint64_t t) {
    uint16_t lo = x < y ? x : y, hi = x < y ? y : x;
    uint32_t start = pair_hash(lo, hi);
    int32_t reuse = -1;
    for (uint32_t k = 0; k < CAP_PAIRS; ++k) {
        ++s.work.scan_steps;
        uint32_t i = (start + k) % CAP_PAIRS;
        PairRecord& p = s.pairs[i];
        if (!p.used) {
            if (reuse < 0) reuse = int32_t(i);
            break;  // end of the probe chain
        }
        if (p.lo == lo && p.hi == hi) return int32_t(i);
        if (reuse < 0 && pair_stale(p, epoch, t, s.m.pair_rematch_ticks)) reuse = int32_t(i);
    }
    if (!create) return -1;
    if (reuse < 0) {
        ++s.faults.pair_overflow;
        return -1;
    }
    PairRecord& p = s.pairs[reuse];
    p.lo = lo;
    p.hi = hi;
    p.epoch = epoch;
    p.starts = 0;
    p.last = 0;
    p.has_last = 0;
    p.used = 1;
    return reuse;
}

// ---- reject / refund -------------------------------------------------------------
struct Res {
    uint8_t code;
    uint64_t target;
};
inline Res ok(uint64_t target = 0) { return Res{OK, target}; }
inline Res dup(uint64_t target = 0) { return Res{DUPLICATE, target}; }
inline Res rej(uint8_t code) { return Res{code, 0}; }
inline bool accepted(const Res& r) { return r.code == OK || r.code == DUPLICATE; }

inline bool holds_slot(State& s, const Id& who) {
    int32_t a = account_index(s, who);
    return a >= 0 && s.accounts[a].slot;
}

// Give `who` a slot, ignoring the manifest bound (construction seeding).
inline bool add_slot(State& s, const Id& who) {
    int32_t a = account_get_or_alloc(s, who);
    if (a < 0) {
        ++s.faults.account_overflow;
        return false;
    }
    if (!s.accounts[a].slot) {
        s.accounts[a].slot = 1;
        s.n_slots += 1;
    }
    return true;
}

// contract.py _claim: reserve an account slot (nonce + credit) before
// accepting funds for `who`; FULL when it is new and the table is full.
inline Res claim(State& s, const Id& who) {
    if (holds_slot(s, who)) return ok();
    if (s.n_slots >= s.m.max_accounts) return rej(FULL);
    return add_slot(s, who) ? ok() : rej(FULL);
}

// contract.py _eligible: only account holders, owners/operators of registered
// fighters, and the live owner registering a registry asset get a slot.
inline bool eligible(State& s, Host& h, const Id& who, uint16_t op, const uint8_t* body) {
    if (holds_slot(s, who)) return true;
    for (uint32_t i = 0; i < CAP_FIGHTERS; ++i) {
        if (i >= s.n_fighters) break;
        ++s.work.scan_steps;
        if (id_eq(s.fighters[i].owner, who) || id_eq(s.fighters[i].op, who)) return true;
    }
    if (op == OP_REGISTER_FIGHTER) {
        Id fid;
        copy32(fid.b, body);
        if (asset_index(s, fid) < 0) return false;
        Id owner;
        return owner_of(s, h, fid, owner) && id_eq(owner, who);
    }
    return false;
}

// contract.py _refund: rejected attachments become withdrawal credit for slot
// holders; anyone else is paid straight back and never given a slot, and if
// that transfer fails the amount is still owed as credit.
inline int64_t refund(State& s, Host& h, const Id& who, int64_t amount) {
    if (!amount) return 0;
    Body b{};
    b_id(b, who);
    b_u64(b, uint64_t(amount));
    if (holds_slot(s, who)) {
        credit(s, who, amount);
        emit(s, EV_REFUND_CREDIT, b);
        return amount;
    }
    s.balance = sub_i64(s, s.balance, amount);
    if (!transfer(s, h, who, amount)) {
        s.balance = add_i64(s, s.balance, amount);
        credit(s, who, amount);
        emit(s, EV_REFUND_CREDIT, b);
    }
    return amount;
}

// ---- fighters: authority ----------------------------------------------------------
inline Res authorize(State& s, Host& h, Fighter& f, const Id& inv, uint32_t auth_version) {
    Id owner;
    if (!owner_of(s, h, f.fighter_id, owner)) return rej(BAD_STATE);
    if (!id_eq(owner, f.owner)) return rej(NOT_OWNER);
    if (auth_version != f.auth_version) return rej(STALE_AUTH);
    if (!id_eq(inv, f.op) && !id_eq(inv, f.owner)) return rej(NOT_OPERATOR);
    return ok();
}

inline Res profiles(const State& s, const uint8_t* ruleset_digest, uint32_t timing_id, uint32_t fee_id) {
    if (!eq32(ruleset_digest, s.m.ruleset_digest)) return rej(INCOMPATIBLE);
    if (s.ruleset_retired) return rej(RULESET_RETIRED);
    if (!timing(s, timing_id) || !fee(s, fee_id)) return rej(INCOMPATIBLE);
    return ok();
}

inline uint32_t open_offers(State& s) {
    uint32_t n = 0;
    for (uint32_t i = 0; i < CAP_OFFER_SLOTS; ++i) {
        ++s.work.scan_steps;
        if (s.offers[i].used && s.offers[i].status == O_OPEN) ++n;
    }
    return n;
}

inline uint32_t live_cups(State& s) {
    uint32_t n = 0;
    for (uint32_t i = 0; i < CAP_CUP_SLOTS; ++i)
        if (s.cups[i].used && (s.cups[i].status == CUP_REGISTRATION || s.cups[i].status == CUP_RUNNING)) ++n;
    return n;
}

// Slots held by non-cup fights plus every running cup's level reservation.
inline uint32_t fights_in_use(State& s) {
    uint32_t n = 0;
    for (uint32_t i = 0; i < CAP_CONTEST_SLOTS; ++i) {
        const Contest& c = s.contests[i];
        if (c.used && c.status == C_ACTIVE && c.mode != M_CUP) ++n;
    }
    for (uint32_t i = 0; i < CAP_CUP_SLOTS; ++i) {
        const Cup& c = s.cups[i];
        if (c.used && c.status == CUP_RUNNING) n += c.reserved;
    }
    return n;
}

// ---- small sorts (bounded insertion sorts) --------------------------------------
inline void sort_u64(uint64_t* v, uint32_t n) {
    for (uint32_t i = 1; i < n; ++i) {
        uint64_t x = v[i];
        uint32_t j = i;
        while (j > 0 && v[j - 1] > x) {
            v[j] = v[j - 1];
            --j;
        }
        v[j] = x;
    }
}

// ---- offers -----------------------------------------------------------------------
inline void close_offer(State& s, Offer& o, uint8_t status) {
    o.status = status;
    if (o.escrowed) {
        o.escrowed = 0;
        credit(s, o.payer, o.amount);
    }
    Fighter& f = s.fighters[o.fighter_idx];
    if ((f.lock == L_QUEUED || f.lock == L_DUEL_OFFER) && f.lock_ref == o.offer_id) {
        f.lock = L_IDLE;
        f.lock_ref = 0;
    }
    Body b{};
    b_u64(b, o.offer_id);
    b_str(b, offer_status_str(status));
    emit(s, EV_OFFER_CLOSED, b);
}

inline bool still_valid(State& s, Host& h, const Offer& o) {
    const Fighter& f = s.fighters[o.fighter_idx];
    Id owner;
    if (!owner_of(s, h, o.fighter_id, owner)) return false;
    return id_eq(owner, o.owner) && id_eq(o.owner, f.owner) && id_eq(f.op, o.op) &&
           f.auth_version == o.auth_version && f.lock_ref == o.offer_id;
}

// ---- fights -------------------------------------------------------------------------
inline void encode_participant(const Participant& p, uint8_t* out) {
    uint32_t k = 0;
    for (uint32_t i = 0; i < 32; ++i) out[k++] = p.fighter_id.b[i];
    for (uint32_t i = 0; i < 32; ++i) out[k++] = p.owner.b[i];
    for (uint32_t i = 0; i < 32; ++i) out[k++] = p.op.b[i];
    for (uint32_t i = 0; i < 4; ++i) out[k++] = uint8_t(p.auth_version >> (8 * i));
    for (uint32_t i = 0; i < 32; ++i) out[k++] = p.payout.b[i];
    out[k++] = uint8_t(p.lifetime & 0xff);
    out[k++] = uint8_t(p.lifetime >> 8);
    out[k++] = uint8_t(p.season_rating & 0xff);
    out[k++] = uint8_t(p.season_rating >> 8);
}

inline void put_le(uint8_t* out, uint32_t& k, uint64_t v, uint32_t width) {
    for (uint32_t i = 0; i < width; ++i) out[k++] = uint8_t(v >> (8 * i));
}

inline void context_digest(State& s, const Contest& c, uint64_t fight_id, uint64_t t, const TimingProfile& tp,
                           const FeeProfile& fp, uint8_t out[32]) {
    uint8_t ctx[qdojo_combat::CONTEXT_BYTES];
    uint32_t k = 0;
    for (uint32_t i = 0; i < 32; ++i) ctx[k++] = s.m.network_id.b[i];
    for (uint32_t i = 0; i < 32; ++i) ctx[k++] = s.m.contract_id.b[i];
    put_le(ctx, k, c.contest_id, 8);
    put_le(ctx, k, fight_id, 8);
    put_le(ctx, k, c.mode, 1);
    put_le(ctx, k, c.fmt, 1);
    put_le(ctx, k, c.cup_id, 8);
    put_le(ctx, k, c.season, 4);
    put_le(ctx, k, t, 8);
    for (uint32_t i = 0; i < 32; ++i) ctx[k++] = s.m.ruleset_digest[i];
    put_le(ctx, k, tp.commit_ticks, 2);
    put_le(ctx, k, tp.reveal_ticks, 2);
    put_le(ctx, k, fp.id, 4);
    put_le(ctx, k, uint64_t(c.stake), 8);
    put_le(ctx, k, fp.rake_bps, 2);
    put_le(ctx, k, fp.house_bps, 2);
    put_le(ctx, k, fp.dev_bps, 2);
    put_le(ctx, k, fp.share_bps, 2);
    for (uint32_t i = 0; i < 32; ++i) ctx[k++] = fp.house.b[i];
    for (uint32_t i = 0; i < 32; ++i) ctx[k++] = fp.dev.b[i];
    for (uint32_t i = 0; i < 32; ++i) ctx[k++] = fp.share.b[i];
    encode_participant(c.a, ctx + k);
    k += qdojo_combat::PARTICIPANT_BYTES;
    encode_participant(c.b, ctx + k);
    s.work.sha_blocks += blocks_for(uint32_t(sizeof(qdojo_combat::TAG_CONTEXT)) + qdojo_combat::CONTEXT_BYTES);
    qdojo_combat::context_digest(ctx, out);
}

inline void refresh_round_digest(State& s, Fight& f) {
    uint8_t sa[8], sb[8];
    qdojo_combat::encode_state(f.state.a, sa);
    qdojo_combat::encode_state(f.state.b, sb);
    s.work.sha_blocks += blocks_for(uint32_t(sizeof(qdojo_combat::TAG_STATE)) + 32 + 1 + 16);
    qdojo_combat::round_state_digest(f.context_digest, f.state.round_index, sa, sb, f.round_state_digest);
}

inline void new_fight(State& s, Contest& c, uint64_t t) {
    uint64_t fid = s.next_fight++;
    const TimingProfile* tp = timing(s, c.timing_id);
    const FeeProfile* fp = fee(s, c.fee_id);
    int32_t slot = new_fight_slot(s);
    if (slot < 0 || !tp || !fp) return;  // counted in faults; admission capacities prevent it
    Fight& f = s.fights[slot];
    f = Fight{};
    f.used = 1;
    f.fight_id = fid;
    f.contest_id = c.contest_id;
    f.phase = P_COMMIT;
    f.commit_ticks = tp->commit_ticks;
    f.reveal_ticks = tp->reveal_ticks;
    f.start_tick = t;
    f.commit_last = add_u64(s, t, tp->commit_ticks);
    f.reveal_last = add_u64(s, f.commit_last, tp->reveal_ticks);
    context_digest(s, c, fid, t, *tp, *fp, f.context_digest);
    f.state = qdojo_combat::new_fight();
    refresh_round_digest(s, f);
    c.current_fight = fid;
    Body b{};
    b_u64(b, fid);
    b_u64(b, c.contest_id);
    b_u64(b, t);
    b_u64(b, f.commit_last);
    b_u64(b, f.reveal_last);
    emit(s, EV_FIGHT_CREATED, b);
}

inline Participant participant(State& s, const Offer& o, uint32_t season) {
    const Fighter& f = s.fighters[o.fighter_idx];
    Participant p;
    p.fighter_id = o.fighter_id;
    p.owner = o.owner;
    p.op = o.op;
    p.auth_version = o.auth_version;
    p.payout = o.payout;
    p.lifetime = f.lifetime;
    p.season_rating = rating_in(f, season);
    return p;
}

inline Series series_of(uint8_t fmt) {
    Series se{};
    if (fmt == F_BO3) {
        se.need = 2;
        se.cap = 5;
    } else if (fmt == F_BO5) {
        se.need = 3;
        se.cap = 7;
    } else {
        se.need = 1;
        se.cap = 1;
    }
    return se;
}
inline bool series_done(const Series& se) {
    return se.wins_a >= se.need || se.wins_b >= se.need || se.fights >= se.cap;
}
inline uint8_t series_winner(const Series& se) {
    if (!series_done(se) || se.wins_a == se.wins_b) return S_NONE;
    return se.wins_a > se.wins_b ? S_A : S_B;
}

// contract.py _start_contest. `x` and `y` are offer snapshots; offers with a
// nonzero id have their escrow moved into the contest pot.
inline int32_t start_contest(State& s, uint8_t mode, uint8_t fmt, Offer x, Offer y, uint64_t t, bool has_key,
                             int64_t key_epoch, uint64_t cup_id, uint64_t pairing_id) {
    if (id_cmp(x.fighter_id, y.fighter_id) > 0) {
        Offer tmp = x;
        x = y;
        y = tmp;
    }
    uint32_t season = mode == M_RANKED ? season_of(s, t) : 0;
    uint64_t cid = s.next_contest++;
    int32_t slot = new_contest_slot(s);
    if (slot < 0) return -1;
    Contest& c = s.contests[slot];
    c = Contest{};
    c.used = 1;
    c.contest_id = cid;
    c.mode = mode;
    c.fmt = fmt;
    c.status = C_ACTIVE;
    c.a = participant(s, x, season);
    c.b = participant(s, y, season);
    c.a_idx = x.fighter_idx;
    c.b_idx = y.fighter_idx;
    c.payer_a = x.payer;
    c.payer_b = y.payer;
    c.stake = x.amount;
    c.fee_id = x.fee_id;
    c.timing_id = x.timing_id;
    c.generation = s.generation;
    c.start_tick = t;
    c.season = season;
    c.series = series_of(fmt);
    c.cup_id = cup_id;
    c.pairing_id = pairing_id;
    c.has_starts_key = has_key ? 1 : 0;
    c.starts_epoch = key_epoch;
    if (x.offer_id && y.offer_id) {
        c.has_pot = 1;
        int32_t sx = offer_slot(s, x.offer_id), sy = offer_slot(s, y.offer_id);
        if (sx >= 0 && s.offers[sx].escrowed) {
            s.offers[sx].escrowed = 0;
            s.offers[sx].contest_id = cid;
            c.pot_a = s.offers[sx].amount;
        }
        if (sy >= 0 && s.offers[sy].escrowed) {
            s.offers[sy].escrowed = 0;
            s.offers[sy].contest_id = cid;
            c.pot_b = s.offers[sy].amount;
        }
    }
    if (mode != M_CUP) {
        s.fighters[x.fighter_idx].lock = L_CONTEST;
        s.fighters[x.fighter_idx].lock_ref = cid;
        s.fighters[y.fighter_idx].lock = L_CONTEST;
        s.fighters[y.fighter_idx].lock_ref = cid;
    }
    new_fight(s, c, t);
    return slot;
}

// ---- settlement ---------------------------------------------------------------
inline void fault(State& s, Fighter& f, uint64_t t) {
    int64_t e = epoch_of(s, t);
    if (f.fault_epoch != e) {
        f.fault_epoch = e;
        f.fault_count = 0;
    }
    f.fault_count += 1;
    uint64_t until = add_u64(s, t, s.m.cooldown_ticks);
    if (until > f.cooldown_until) f.cooldown_until = until;
    if (f.fault_count >= s.m.faults_per_epoch) f.suspended_epoch = e;
    Body b{};
    b_id(b, f.fighter_id);
    b_u64(b, f.fault_count);
    emit(s, EV_FAULT, b);
}

// rating.py delta/update: zero-sum from both OLD ratings.
inline int64_t rating_delta(int64_t ra, int64_t rb, int64_t score_a) {
    int64_t expected = 1000 + 2 * (ra - rb);
    if (expected < 100) expected = 100;
    if (expected > 1900) expected = 1900;
    int64_t raw = 32 * (score_a - expected);
    int64_t mag = (raw < 0 ? -raw : raw) / 2000;
    int64_t d = raw > 0 ? mag : raw < 0 ? -mag : 0;
    if (d > 0) {
        if (d > rb) d = rb;
        if (d > RATING_CEILING - ra) d = RATING_CEILING - ra;
    } else if (d < 0) {
        int64_t m = -d;
        if (m > ra) m = ra;
        if (m > RATING_CEILING - rb) m = RATING_CEILING - rb;
        d = -m;
    }
    return d;
}

inline void add_opponent(SeasonSlot& sl, uint16_t opp) {
    for (uint32_t i = 0; i < 4; ++i)
        if (i < sl.opponents && sl.opponent_idx[i] == opp) return;
    if (sl.opponents < 4) sl.opponent_idx[sl.opponents++] = opp;
}
inline void add_defeated(SeasonSlot& sl, uint16_t opp) {
    uint64_t bit = uint64_t(1) << (opp % 64);
    uint64_t& w = sl.defeated_bits[opp / 64];
    if (!(w & bit)) {
        w |= bit;
        sl.defeated = uint16_t(sl.defeated + 1);
    }
}

inline void rate(State& s, const Contest& c, uint8_t kind, uint8_t winner) {
    if (kind != R_COMBAT && kind != R_FORFEIT) return;
    Fighter& fa = s.fighters[c.a_idx];
    Fighter& fb = s.fighters[c.b_idx];
    int64_t score = winner == S_NONE ? SCORE_DRAW : winner == S_A ? SCORE_WIN : SCORE_LOSS;
    int64_t d = rating_delta(c.a.lifetime, c.b.lifetime, score);
    fa.lifetime = uint16_t(c.a.lifetime + d);
    fb.lifetime = uint16_t(c.b.lifetime - d);
    uint32_t se = c.season;
    if (se) {
        int64_t ds = rating_delta(c.a.season_rating, c.b.season_rating, score);
        SeasonSlot& sa = season_claim(fa, se);
        SeasonSlot& sb = season_claim(fb, se);
        sa.rating = uint16_t(c.a.season_rating + ds);
        sa.has_rating = 1;
        sb.rating = uint16_t(c.b.season_rating - ds);
        sb.has_rating = 1;
    }
    bool combat = kind == R_COMBAT;
    for (uint32_t side = 0; side < 2; ++side) {
        Fighter& me = side == 0 ? fa : fb;
        uint16_t opp_idx = side == 0 ? c.b_idx : c.a_idx;
        uint8_t mine = side == 0 ? S_A : S_B;
        bool won = winner == mine;
        if (combat) {
            me.placement += 1;
            if (won) ++me.rec_w;
            else if (winner == S_NONE) ++me.rec_d;
            else ++me.rec_l;
        } else {
            if (won) ++me.rec_fw;
            else ++me.rec_fl;
        }
        if (se && combat) {
            SeasonSlot& st = season_claim(me, se);
            st.has_stats = 1;
            st.fights += 1;
            add_opponent(st, opp_idx);
            if (won) {
                st.wins += 1;
                add_defeated(st, opp_idx);
            }
            int64_t final_epoch = s.m.season_start_epoch + int64_t(se) * s.m.season_epochs - 1;
            if (epoch_of(s, c.start_tick) == final_epoch) st.final_epoch_fights += 1;
        }
    }
    Body b{};
    b_id(b, fa.fighter_id);
    b_u64(b, fa.lifetime);
    b_id(b, fb.fighter_id);
    b_u64(b, fb.lifetime);
    emit(s, EV_RATING, b);
}

inline void settle_win(State& s, Contest& c, const Id& winner, const FeeProfile& fp) {
    int64_t gross = add_i64(s, c.pot_a, c.pot_b);
    int64_t rake = mul_i64(s, gross, fp.rake_bps) / BPS;
    int64_t dev = mul_i64(s, rake, fp.dev_bps) / BPS;
    int64_t share = mul_i64(s, rake, fp.share_bps) / BPS;
    c.has_pot = 0;
    c.pot_a = c.pot_b = 0;
    credit(s, winner, sub_i64(s, gross, rake));
    credit(s, fp.house, sub_i64(s, sub_i64(s, rake, dev), share));
    credit(s, fp.dev, dev);
    credit(s, fp.share, share);
}

inline void settle_refund(State& s, Contest& c) {
    if (!c.has_pot) return;
    int64_t a = c.pot_a, b = c.pot_b;
    c.has_pot = 0;
    c.pot_a = c.pot_b = 0;
    credit(s, c.payer_a, a);
    credit(s, c.payer_b, b);
}

// ---- cups (forward declarations) ---------------------------------------------------
inline void cup_pairing_done(State& s, Contest& c, uint64_t t);

inline void finish_contest(State& s, Contest& c, uint64_t t, uint8_t kind, uint8_t winner) {
    c.status = C_DONE;
    c.result_kind = kind;
    c.result_winner = winner;
    Fighter& fa = s.fighters[c.a_idx];
    Fighter& fb = s.fighters[c.b_idx];
    if (kind == R_DOUBLE_FAULT) {
        fault(s, fa, t);
        fault(s, fb, t);
    } else if (kind == R_FORFEIT) {
        fault(s, winner == S_A ? fb : fa, t);
    }
    if (c.mode == M_RANKED || c.mode == M_DUEL) {
        const FeeProfile* fp = fee(s, c.fee_id);
        if ((kind == R_COMBAT || kind == R_FORFEIT) && winner != S_NONE && fp)
            settle_win(s, c, winner == S_A ? c.a.payout : c.b.payout, *fp);
        else
            settle_refund(s, c);
    }
    if (c.mode == M_RANKED) {
        rate(s, c, kind, winner);
        int32_t p = pair_find(s, c.a_idx, c.b_idx, true, epoch_of(s, t), t);
        if (p >= 0) {
            s.pairs[p].last = t;
            s.pairs[p].has_last = 1;
        }
    }
    if (c.mode != M_CUP) {
        if (fa.lock == L_CONTEST && fa.lock_ref == c.contest_id) {
            fa.lock = L_IDLE;
            fa.lock_ref = 0;
        }
        if (fb.lock == L_CONTEST && fb.lock_ref == c.contest_id) {
            fb.lock = L_IDLE;
            fb.lock_ref = 0;
        }
    }
    Body b{};
    b_u64(b, c.contest_id);
    b_str(b, kind_str(kind));
    b_str(b, side_str(winner));
    emit(s, EV_CONTEST_SETTLED, b);
    if (c.mode == M_CUP) cup_pairing_done(s, c, t);
}

// Objective service void: refund, no rating, no fault; reverse the pair start once.
inline void void_contest(State& s, Contest& c, uint64_t t) {
    int32_t fs = fight_slot(s, c.current_fight);
    if (fs >= 0 && s.fights[fs].phase != P_DONE) {
        s.fights[fs].phase = P_DONE;
        s.fights[fs].result_kind = R_VOID;
        s.fights[fs].result_winner = S_NONE;
    }
    c.status = C_DONE;
    c.result_kind = R_VOID;
    c.result_winner = S_NONE;
    if (c.mode == M_RANKED || c.mode == M_DUEL) settle_refund(s, c);
    if (c.has_starts_key) {
        int32_t p = pair_find(s, c.a_idx, c.b_idx, false, epoch_of(s, t), t);
        if (p >= 0 && s.pairs[p].epoch == c.starts_epoch && s.pairs[p].starts > 0) s.pairs[p].starts -= 1;
    }
    Fighter& fa = s.fighters[c.a_idx];
    Fighter& fb = s.fighters[c.b_idx];
    if (fa.lock == L_CONTEST && fa.lock_ref == c.contest_id) {
        fa.lock = L_IDLE;
        fa.lock_ref = 0;
    }
    if (fb.lock == L_CONTEST && fb.lock_ref == c.contest_id) {
        fb.lock = L_IDLE;
        fb.lock_ref = 0;
    }
    Body b{};
    b_u64(b, c.contest_id);
    b_str(b, "VOID");
    b_str(b, "-");
    emit(s, EV_CONTEST_SETTLED, b);
}

inline void end_fight(State& s, Fight& f, uint64_t t, uint8_t kind, uint8_t winner) {
    f.phase = P_DONE;
    f.result_kind = kind;
    f.result_winner = winner;
    Body b{};
    b_u64(b, f.fight_id);
    b_str(b, kind_str(kind));
    b_str(b, side_str(winner));
    emit(s, EV_FIGHT_ENDED, b);
    int32_t cs = contest_slot(s, f.contest_id);
    if (cs < 0) {
        ++s.faults.slot_overflow;
        return;
    }
    Contest& c = s.contests[cs];
    if (kind == R_COMBAT) {
        if (c.mode == M_CUP) {
            int32_t k = cup_slot(s, c.cup_id);
            if (k >= 0) s.cups[k].combat_fights += 1;
        }
        c.series.fights = uint8_t(c.series.fights + 1);
        if (winner == S_A) c.series.wins_a = uint8_t(c.series.wins_a + 1);
        else if (winner == S_B) c.series.wins_b = uint8_t(c.series.wins_b + 1);
        if (!series_done(c.series)) {
            new_fight(s, c, t);
            return;
        }
        finish_contest(s, c, t, R_COMBAT, series_winner(c.series));
    } else {
        finish_contest(s, c, t, kind, winner);
    }
}

inline void resolve(State& s, Fight& f, uint64_t t) {
    qdojo_combat::RoundResult res;
    qdojo_combat::Error e = qdojo_combat::resolve_round(f.state, f.plan[0], f.plan[1], res);
    if (e != qdojo_combat::OK) {  // unreachable: both plans were validated at reveal
        ++s.faults.engine;
        return;
    }
    uint8_t states[16];
    qdojo_combat::encode_state(res.end.a, states);
    qdojo_combat::encode_state(res.end.b, states + 8);
    Body b{};
    b_u64(b, f.fight_id);
    b_u64(b, f.state.round_index);
    b_u64(b, res.executed);
    b_bytes(b, states, 16);
    emit(s, EV_ROUND_RESOLVED, b);
    f.state = res.end;
    f.committed[0] = f.committed[1] = 0;
    f.revealed[0] = f.revealed[1] = 0;
    if (res.end.outcome != qdojo_combat::OUTCOME_NONE) {
        uint8_t w = res.end.winner == qdojo_combat::WINNER_A ? S_A : res.end.winner == qdojo_combat::WINNER_B ? S_B : S_NONE;
        end_fight(s, f, t, R_COMBAT, w);
        return;
    }
    f.phase = P_COMMIT;
    f.start_tick = t;
    f.commit_last = add_u64(s, t, f.commit_ticks);
    f.reveal_last = add_u64(s, f.commit_last, f.reveal_ticks);
    refresh_round_digest(s, f);
}

inline void fight_tick(State& s, Fight& f, uint64_t t) {
    if (f.phase == P_COMMIT && t == f.commit_last) {
        if (f.committed[0] && f.committed[1]) {
            f.phase = P_REVEAL;
        } else if (f.committed[0] || f.committed[1]) {
            end_fight(s, f, t, R_FORFEIT, f.committed[0] ? S_A : S_B);
        } else {
            end_fight(s, f, t, R_DOUBLE_FAULT, S_NONE);
        }
        return;
    }
    if (f.phase != P_REVEAL) return;
    if (f.revealed[0] && f.revealed[1]) {
        resolve(s, f, t);
    } else if (t == f.reveal_last) {
        if (f.revealed[0] || f.revealed[1])
            end_fight(s, f, t, R_FORFEIT, f.revealed[0] ? S_A : S_B);
        else
            end_fight(s, f, t, R_DOUBLE_FAULT, S_NONE);
    }
}

// ---- cups ----------------------------------------------------------------------------
inline bool cup_has_entry(const Cup& cup, const Id& fid) {
    for (uint32_t i = 0; i < CAP_CUP_ENTRANTS; ++i)
        if (i < cup.n_entries && id_eq(cup.entries[i].fighter_id, fid)) return true;
    return false;
}
inline bool cup_in_slots(const Cup& cup, const Id& fid) {
    for (uint32_t i = 0; i < CAP_CUP_ENTRANTS; ++i)
        if (i < cup.n_slots && cup.slot_used[i] && id_eq(cup.slots[i], fid)) return true;
    return false;
}
inline bool alive_in_cup(const Cup& cup, const Id& fid) {
    if (cup.status == CUP_REGISTRATION) return cup_has_entry(cup, fid);
    return cup_in_slots(cup, fid);
}

inline bool represented(State& s, const Cup& cup, const Id& owner, const Id& op, const Id* exclude) {
    for (uint32_t i = 0; i < CAP_CUP_ENTRANTS; ++i) {
        if (i >= cup.n_entries) break;
        const CupEntry& e = cup.entries[i];
        if ((exclude && id_eq(e.fighter_id, *exclude)) || !alive_in_cup(cup, e.fighter_id)) continue;
        const Fighter& f = s.fighters[e.fighter_idx];
        if (id_eq(owner, f.owner) || id_eq(owner, f.op) || id_eq(op, f.owner) || id_eq(op, f.op)) return true;
    }
    return false;
}

inline bool between_pairings(const Cup& cup, const Id& fid) {
    if (cup.status == CUP_REGISTRATION) return true;
    for (uint32_t i = 0; i < CAP_PAIRINGS; ++i) {
        if (i >= cup.n_pairings) break;
        const Pairing& p = cup.pairings[i];
        bool is_a = p.has_a && id_eq(p.a, fid), is_b = p.has_b && id_eq(p.b, fid);
        if (!is_a && !is_b) continue;
        if (p.status == PS_PLAYING || p.status == PS_REPLAY_WAIT) return false;
        if (p.status == PS_SCHEDULED && ((is_a && p.checked_a) || (is_b && p.checked_b))) return false;
    }
    return true;
}

inline void release_cup_locks(State& s, Cup& cup) {
    for (uint32_t i = 0; i < CAP_CUP_ENTRANTS; ++i) {
        if (i >= cup.n_entries) break;
        Fighter& f = s.fighters[cup.entries[i].fighter_idx];
        if (f.lock == L_TOURNAMENT && f.lock_ref == cup.cup_id) {
            f.lock = L_IDLE;
            f.lock_ref = 0;
        }
    }
}

inline void refund_cup(State& s, Cup& cup) {
    if (!cup.has_pot) return;
    cup.has_pot = 0;
    credit(s, cup.sponsor, cup.sponsorship);
    for (uint32_t i = 0; i < CAP_CUP_ENTRANTS; ++i) {
        if (i >= cup.n_entries) break;
        credit(s, cup.entries[i].payer, cup.entries[i].amount);
    }
}

inline void finished_event(State& s, const Cup& cup, const char* what, const Id* champion, const char* why) {
    Body b{};
    b_u64(b, cup.cup_id);
    b_str(b, what);
    if (champion) b_id(b, *champion);
    if (why) b_str(b, why);
    emit(s, EV_CUP_FINISHED, b);
}

// Whole-event abort: every entry and the sponsorship go back, no rake, no trophy.
inline void abort_cup(State& s, Cup& cup, uint64_t t, uint8_t why) {
    (void)t;
    for (uint32_t i = 0; i < CAP_CONTEST_SLOTS; ++i) {
        Contest& c = s.contests[i];
        if (!c.used || c.cup_id != cup.cup_id || c.status != C_ACTIVE) continue;
        int32_t fs = fight_slot(s, c.current_fight);
        if (fs >= 0 && s.fights[fs].phase != P_DONE) {
            s.fights[fs].phase = P_DONE;
            s.fights[fs].result_kind = R_VOID;
            s.fights[fs].result_winner = S_NONE;
        }
        c.status = C_DONE;
        c.result_kind = R_VOID;
        c.result_winner = S_NONE;
    }
    refund_cup(s, cup);
    cup.status = CUP_ABORTED;
    cup.reserved = 0;
    release_cup_locks(s, cup);
    finished_event(s, cup, "ABORTED", nullptr, abort_str(why));
}

inline void cup_level_event(State& s, const Cup& cup, uint64_t postponed) {
    Body b{};
    b_u64(b, cup.cup_id);
    b_u64(b, cup.level);
    b_u64(b, cup.level_start);
    b_u64(b, postponed);
    emit(s, EV_CUP_LEVEL, b);
}

inline void schedule_level(State& s, Cup& cup, uint64_t t) {
    uint32_t need = 0;
    for (uint32_t i = 0; i + 1 < CAP_CUP_ENTRANTS; i += 2) {
        if (i >= cup.n_slots) break;
        if (cup.slot_used[i] && cup.slot_used[i + 1]) ++need;
    }
    uint32_t in_use = fights_in_use(s);
    uint32_t free = s.m.max_fights > in_use ? s.m.max_fights - in_use : 0;
    if (need > free) {
        uint16_t bit = uint16_t(1u << cup.level);
        if (cup.postponed_mask & bit) {
            abort_cup(s, cup, t, AB_CAPACITY);
            return;
        }
        cup.postponed_mask = uint16_t(cup.postponed_mask | bit);
        cup.level_start = add_u64(s, cup.level_start, cup.d.level_ticks);
        cup.expiry_tick = add_u64(s, cup.expiry_tick, cup.d.level_ticks);
        cup_level_event(s, cup, 1);
        cup.pending_reservation = 1;
        return;
    }
    cup.pending_reservation = 0;
    cup.reserved = need;
    for (uint32_t i = 0; i + 1 < CAP_CUP_ENTRANTS; i += 2) {
        if (i >= cup.n_slots) break;
        if (cup.n_pairings >= CAP_PAIRINGS) {
            ++s.faults.slot_overflow;
            break;
        }
        Pairing& p = cup.pairings[cup.n_pairings];
        p = Pairing{};
        p.pairing_id = uint64_t(cup.n_pairings) + 1;
        cup.n_pairings = uint8_t(cup.n_pairings + 1);
        p.level = cup.level;
        p.has_a = cup.slot_used[i];
        p.has_b = cup.slot_used[i + 1];
        if (p.has_a) p.a = cup.slots[i];
        if (p.has_b) p.b = cup.slots[i + 1];
        p.status = PS_SCHEDULED;
        if (!p.has_a || !p.has_b) {
            if (p.has_a) {
                p.winner = p.a;
                p.has_winner = 1;
            } else if (p.has_b) {
                p.winner = p.b;
                p.has_winner = 1;
            }
            p.status = p.has_winner ? PS_DONE : PS_EMPTY;
        }
    }
    cup_level_event(s, cup, 0);
}

// bracket(): rating descending, then ID ascending; standard seed order; None is a bye.
inline void lock_roster(State& s, Cup& cup, uint64_t t) {
    if (cup.n_entries < cup.d.min_entrants) {
        release_cup_locks(s, cup);
        refund_cup(s, cup);
        cup.status = CUP_CANCELLED;
        finished_event(s, cup, "CANCELLED", nullptr, nullptr);
        return;
    }
    uint8_t order[CAP_CUP_ENTRANTS];
    uint32_t n = cup.n_entries;
    for (uint32_t i = 0; i < CAP_CUP_ENTRANTS; ++i) order[i] = uint8_t(i);
    for (uint32_t i = 1; i < CAP_CUP_ENTRANTS; ++i) {
        if (i >= n) break;
        uint8_t x = order[i];
        uint32_t j = i;
        while (j > 0) {
            const CupEntry& ex = cup.entries[x];
            const CupEntry& ey = cup.entries[order[j - 1]];
            uint16_t rx = s.fighters[ex.fighter_idx].lifetime, ry = s.fighters[ey.fighter_idx].lifetime;
            bool before = rx > ry || (rx == ry && id_cmp(ex.fighter_id, ey.fighter_id) < 0);
            if (!before) break;
            order[j] = order[j - 1];
            --j;
        }
        order[j] = x;
    }
    uint32_t size = 2;
    while (size < n) size *= 2;
    uint8_t pos[CAP_CUP_ENTRANTS];
    uint32_t len = 2;
    pos[0] = 1;
    pos[1] = 2;
    while (len < size) {  // at most three doublings for 16
        uint8_t next[CAP_CUP_ENTRANTS];
        uint32_t m = 2 * len + 1;
        for (uint32_t i = 0; i < len; ++i) {
            next[2 * i] = pos[i];
            next[2 * i + 1] = uint8_t(m - pos[i]);
        }
        len *= 2;
        for (uint32_t i = 0; i < len; ++i) pos[i] = next[i];
    }
    cup.n_slots = uint8_t(size);
    uint8_t bytes[CAP_CUP_ENTRANTS * 32];
    for (uint32_t i = 0; i < CAP_CUP_ENTRANTS; ++i) {
        if (i >= size) break;
        uint32_t seed = pos[i];
        if (seed <= n) {
            cup.slots[i] = cup.entries[order[seed - 1]].fighter_id;
            cup.slot_used[i] = 1;
        } else {
            cup.slots[i] = id_zero();
            cup.slot_used[i] = 0;
        }
        copy32(bytes + 32 * i, cup.slots[i].b);
    }
    uint8_t levels = 0;
    while ((uint32_t(1) << (levels + 1)) <= size) ++levels;
    cup.levels = levels;
    cup.status = CUP_RUNNING;
    cup.level = 0;
    cup.level_start = add_u64(s, t, cup.d.first_level_delay);
    uint64_t span = uint64_t(cup.levels + 1) * cup.d.level_ticks + cup.d.level_ticks;
    cup.expiry_tick = add_u64(s, cup.level_start, span);
    uint8_t digest[32];
    sha(s, bytes, 32 * size, digest);
    Body b{};
    b_u64(b, cup.cup_id);
    b_bytes(b, digest, 32);
    emit(s, EV_CUP_BRACKET, b);
    schedule_level(s, cup, t);
}

inline Offer pairing_offer(State& s, const Cup& cup, const Id& fid, uint64_t t) {
    Offer o{};
    int32_t fi = fighter_index(s, fid);
    const Fighter& f = s.fighters[fi < 0 ? 0 : fi];
    o.offer_id = 0;
    o.fighter_idx = uint16_t(fi < 0 ? 0 : fi);
    o.fighter_id = fid;
    o.owner = f.owner;
    o.op = f.op;
    o.auth_version = f.auth_version;
    o.payer = id_zero();
    o.payout = f.owner;
    o.timing_id = cup.d.timing_id;
    o.fee_id = cup.d.fee_id;
    o.amount = 0;
    o.rating = f.lifetime;
    o.created = t;
    o.expires = t;
    o.generation = s.generation;
    return o;
}

inline void start_pairing_contest(State& s, Cup& cup, Pairing& p, uint64_t t, bool replay) {
    bool final = cup.level == cup.levels - 1;
    uint8_t fmt = final ? F_BO5 : F_BO3;
    Offer x = pairing_offer(s, cup, p.a, t), y = pairing_offer(s, cup, p.b, t);
    int32_t cs = start_contest(s, M_CUP, fmt, x, y, t, false, 0, cup.cup_id, p.pairing_id);
    if (cs < 0) return;
    Contest& c = s.contests[cs];
    if (replay) {
        c.series = Series{1, 3, 0, 0, 0};
        c.replay = 1;
    }
    if (final) p.has_final_owner = 0;
    p.contest_id = c.contest_id;
    p.status = PS_PLAYING;
}

inline void pairing_event(State& s, const Cup& cup, const Pairing& p) {
    Body b{};
    b_u64(b, cup.cup_id);
    b_u64(b, p.pairing_id);
    b_str(b, pairing_status_str(p.status));
    emit(s, EV_CUP_PAIRING, b);
}

inline void start_level_pairings(State& s, Cup& cup, uint64_t t) {
    for (uint32_t i = 0; i < CAP_PAIRINGS; ++i) {
        if (i >= cup.n_pairings) break;
        Pairing& p = cup.pairings[i];
        if (p.level != cup.level || p.status != PS_SCHEDULED) continue;
        if (p.checked_a && p.checked_b) {
            start_pairing_contest(s, cup, p, t, false);
        } else if (p.checked_a || p.checked_b) {
            // The absent fighter forfeits; a missed check-in is not a
            // commit/reveal fault, so no cooldown is added.
            p.winner = p.checked_a ? p.a : p.b;
            p.has_winner = 1;
            p.status = PS_DONE;
            cup.reserved -= 1;
        } else {
            p.status = PS_UNRESOLVED;
            cup.reserved -= 1;
        }
        pairing_event(s, cup, p);
    }
}

inline void cup_pairing_done(State& s, Contest& c, uint64_t t) {
    int32_t k = cup_slot(s, c.cup_id);
    if (k < 0) return;
    Cup& cup = s.cups[k];
    if (c.pairing_id < 1 || c.pairing_id > cup.n_pairings) return;
    Pairing& p = cup.pairings[c.pairing_id - 1];
    uint8_t kind = c.result_kind, winner = c.result_winner;
    if ((kind == R_COMBAT || kind == R_FORFEIT) && winner != S_NONE) {
        const Participant& w = winner == S_A ? c.a : c.b;
        p.winner = w.fighter_id;
        p.has_winner = 1;
        p.final_owner = w.payout;
        p.has_final_owner = 1;
        p.status = PS_DONE;
    } else if (kind == R_COMBAT && !c.replay) {
        p.status = PS_REPLAY_WAIT;
        p.replay_at = add_u64(s, t, cup.d.replay_delay);
        Body b{};
        b_u64(b, cup.cup_id);
        b_u64(b, p.pairing_id);
        b_u64(b, p.replay_at);
        emit(s, EV_CUP_REPLAY_SCHEDULED, b);
        return;
    } else {
        p.status = PS_UNRESOLVED;
    }
    cup.reserved -= 1;
    pairing_event(s, cup, p);
}

inline void pay_cup(State& s, Cup& cup, const Pairing& final_p) {
    int64_t entry_gross = 0;
    for (uint32_t i = 0; i < CAP_CUP_ENTRANTS; ++i)
        if (i < cup.n_entries) entry_gross = add_i64(s, entry_gross, cup.entries[i].amount);
    Id recipient;
    if (final_p.has_final_owner) {
        recipient = final_p.final_owner;
    } else {
        int32_t fi = fighter_index(s, final_p.winner);
        recipient = fi >= 0 ? s.fighters[fi].owner : final_p.winner;
    }
    const FeeProfile* fp = fee(s, cup.d.fee_id);
    int64_t gross = add_i64(s, cup.sponsorship, entry_gross);
    int64_t rake = fp ? mul_i64(s, entry_gross, fp->rake_bps) / BPS : 0;
    int64_t dev = fp ? mul_i64(s, rake, fp->dev_bps) / BPS : 0;
    int64_t share = fp ? mul_i64(s, rake, fp->share_bps) / BPS : 0;
    cup.has_pot = 0;
    credit(s, recipient, sub_i64(s, gross, rake));
    if (fp) {
        credit(s, fp->house, sub_i64(s, sub_i64(s, rake, dev), share));
        credit(s, fp->dev, dev);
        credit(s, fp->share, share);
    }
    cup.status = CUP_COMPLETE;
    cup.champion = final_p.winner;
    release_cup_locks(s, cup);
    finished_event(s, cup, "COMPLETE", &final_p.winner, nullptr);
}

inline void advance_level(State& s, Cup& cup, uint64_t t) {
    Id survivors[CAP_CUP_ENTRANTS];
    uint8_t alive[CAP_CUP_ENTRANTS];
    uint32_t ns = 0;
    int32_t first = -1;
    for (uint32_t i = 0; i < CAP_PAIRINGS; ++i) {
        if (i >= cup.n_pairings) break;
        Pairing& p = cup.pairings[i];
        if (p.level != cup.level) continue;
        if (first < 0) first = int32_t(i);
        bool done = p.status == PS_DONE;
        survivors[ns] = done && p.has_winner ? p.winner : id_zero();
        alive[ns] = done && p.has_winner ? 1 : 0;
        ++ns;
        for (uint32_t side = 0; side < 2; ++side) {
            bool has = side == 0 ? p.has_a : p.has_b;
            const Id& fid = side == 0 ? p.a : p.b;
            if (!has || (p.has_winner && id_eq(fid, p.winner)) || !cup_has_entry(cup, fid)) continue;
            int32_t fi = fighter_index(s, fid);
            if (fi < 0) continue;
            Fighter& f = s.fighters[fi];
            if (f.lock == L_TOURNAMENT && f.lock_ref == cup.cup_id) {
                f.lock = L_IDLE;
                f.lock_ref = 0;
            }
        }
    }
    cup.reserved = 0;
    if (cup.level == cup.levels - 1) {
        if (first >= 0) {
            const Pairing& fin = cup.pairings[first];
            if (fin.status == PS_DONE && fin.has_winner && cup.combat_fights > 0) {
                pay_cup(s, cup, fin);
                return;
            }
        }
        abort_cup(s, cup, t, AB_NO_CHAMPION);
        return;
    }
    for (uint32_t i = 0; i < CAP_CUP_ENTRANTS; ++i) {
        if (i >= ns) break;
        cup.slots[i] = survivors[i];
        cup.slot_used[i] = alive[i];
    }
    cup.n_slots = uint8_t(ns);
    cup.level = uint8_t(cup.level + 1);
    cup.level_start = add_u64(s, cup.level_start, cup.d.level_ticks);
    if (t >= cup.level_start) cup.level_start = add_u64(s, t, 1);
    schedule_level(s, cup, t);
}

inline void cup_tick(State& s, Cup& cup, uint64_t t) {
    if (cup.status == CUP_REGISTRATION && t >= cup.d.registration_close) {
        lock_roster(s, cup, t);
        return;
    }
    if (cup.status != CUP_RUNNING) return;
    if (t >= cup.expiry_tick) {
        abort_cup(s, cup, t, AB_EXPIRED);
        return;
    }
    if (cup.pending_reservation) {
        // A postponed level retries its reservation just before its check-in opens.
        if (t + 1 == cup.level_start) schedule_level(s, cup, t);
        return;
    }
    uint64_t checkin_end = cup.level_start + cup.d.checkin_ticks - 1;
    if (t == checkin_end) start_level_pairings(s, cup, t);
    for (uint32_t i = 0; i < CAP_PAIRINGS; ++i) {
        if (i >= cup.n_pairings) break;
        Pairing& p = cup.pairings[i];
        if (p.level == cup.level && p.status == PS_REPLAY_WAIT && t >= p.replay_at)
            start_pairing_contest(s, cup, p, t, true);
    }
    if (t > checkin_end) {
        bool all = true;
        for (uint32_t i = 0; i < CAP_PAIRINGS; ++i) {
            if (i >= cup.n_pairings) break;
            const Pairing& p = cup.pairings[i];
            if (p.level == cup.level && p.status != PS_DONE && p.status != PS_UNRESOLVED && p.status != PS_EMPTY)
                all = false;
        }
        if (all) advance_level(s, cup, t);
    }
}

// ---- matching (matchmaking.py matching_pass) -------------------------------------------
inline uint64_t window_of(const Offer& o, uint64_t t) {
    uint64_t w = BASE_WINDOW + WIDEN_STEP * ((t - o.created) / WIDEN_TICKS);
    return o.max_gap < w ? o.max_gap : w;
}

inline bool in_cooldown(const State& s, const Fighter& f, uint64_t t, int64_t epoch) {
    (void)s;
    return t < f.cooldown_until || f.suspended_epoch == epoch;
}

inline bool compatible(State& s, const Offer& x, const Offer& y, uint64_t t, int64_t epoch) {
    const Offer* both[2] = {&x, &y};
    for (uint32_t i = 0; i < 2; ++i) {
        const Offer& o = *both[i];
        if (o.status != O_OPEN || t >= o.expires || o.generation != s.generation) return false;
    }
    if (id_eq(x.fighter_id, y.fighter_id) || id_eq(x.owner, y.owner) || id_eq(x.op, y.op)) return false;
    const Fighter& fx = s.fighters[x.fighter_idx];
    const Fighter& fy = s.fighters[y.fighter_idx];
    if (fx.house_npc || fy.house_npc) return false;
    if (x.timing_id != y.timing_id || x.fee_id != y.fee_id || x.tier_id != y.tier_id || x.amount != y.amount)
        return false;
    uint64_t gap = x.rating > y.rating ? uint64_t(x.rating - y.rating) : uint64_t(y.rating - x.rating);
    if (gap > window_of(x, t) || gap > window_of(y, t)) return false;
    int32_t p = pair_find(s, x.fighter_idx, y.fighter_idx, false, epoch, t);
    if (p >= 0) {
        const PairRecord& r = s.pairs[p];
        if (r.epoch == epoch && r.starts >= s.m.pair_starts_per_epoch) return false;
        if (r.has_last && t - r.last < s.m.pair_rematch_ticks) return false;
    }
    if (in_cooldown(s, fx, t, epoch) || in_cooldown(s, fy, t, epoch)) return false;
    uint32_t used = fights_in_use(s);
    return s.m.max_fights > used;
}

inline void matching(State& s, Host& h, uint64_t t) {
    int64_t epoch = epoch_of(s, t);
    uint64_t ids[CAP_OFFER_SLOTS];
    uint32_t n = 0;
    for (uint32_t i = 0; i < CAP_OFFER_SLOTS; ++i) {
        const Offer& o = s.offers[i];
        if (o.used && o.status == O_OPEN && o.kind == K_RANKED) ids[n++] = o.offer_id;
    }
    sort_u64(ids, n);
    if (n > PASS_SNAPSHOT) n = PASS_SNAPSHOT;
    int32_t live[PASS_SNAPSHOT];
    uint32_t nl = 0;
    for (uint32_t i = 0; i < PASS_SNAPSHOT; ++i) {
        if (i >= n) break;
        int32_t k = offer_slot(s, ids[i]);
        if (k < 0) continue;
        Offer& o = s.offers[k];
        if (t >= o.expires || o.generation != s.generation || !still_valid(s, h, o))
            close_offer(s, o, t >= o.expires ? O_EXPIRED : O_INVALIDATED);
        else
            live[nl++] = k;
    }
    if (nl < 2) return;
    uint32_t matched = 0;
    uint8_t taken[PASS_SNAPSHOT] = {};
    for (uint32_t i = 0; i < PASS_SNAPSHOT; ++i) {
        if (i >= nl) break;
        if (matched >= PASS_MATCHES) break;
        if (taken[i]) continue;
        for (uint32_t j = i + 1; j < PASS_SNAPSHOT; ++j) {
            if (j >= nl) break;
            if (taken[j]) continue;
            ++s.work.comparisons;
            Offer& x = s.offers[live[i]];
            Offer& y = s.offers[live[j]];
            if (!compatible(s, x, y, t, epoch)) continue;
            taken[i] = taken[j] = 1;
            x.status = y.status = O_MATCHED;
            int32_t p = pair_find(s, x.fighter_idx, y.fighter_idx, true, epoch, t);
            if (p >= 0) {
                if (s.pairs[p].epoch != epoch) {
                    s.pairs[p].epoch = epoch;
                    s.pairs[p].starts = 0;
                }
                s.pairs[p].starts += 1;
            }
            Body b{};
            b_u64(b, x.offer_id);
            b_u64(b, y.offer_id);
            emit(s, EV_MATCHED, b);
            start_contest(s, M_RANKED, F_SINGLE, x, y, t, true, epoch, 0, 0);
            ++matched;
            break;
        }
    }
}

// ---- frames (codec.py decode_frame) ---------------------------------------------------
struct Frame {
    uint16_t op;
    uint64_t nonce;
    const uint8_t* body;
    uint16_t len;
};

inline uint64_t le(const uint8_t* p, uint32_t width) {
    uint64_t v = 0;
    for (uint32_t i = 0; i < width; ++i) v |= uint64_t(p[i]) << (8 * i);
    return v;
}

inline int32_t body_len(uint16_t op) {
    switch (op) {
        case OP_REGISTER_FIGHTER: return 32 + 4;
        case OP_SET_OPERATOR: return 32 + 32 + 4;
        case OP_QUEUE_ENTER: return 32 + 4 + 32 + 4 + 4 + 2 + 2 + 8;
        case OP_QUEUE_CANCEL: return 8;
        case OP_DUEL_OFFER: return 32 + 4 + 32 + 32 + 4 + 4 + 8 + 1 + 8;
        case OP_DUEL_ACCEPT: return 8 + 32 + 4;
        case OP_COMMIT: return 8 + 1 + 32 + 4 + 32 + 32;
        case OP_REVEAL: return 8 + 1 + 32 + 4 + 32 + 32 + 7;
        case OP_ADVANCE: return 1 + 8;
        case OP_WITHDRAW: return 0;
        case OP_CUP_REGISTER: return 8 + 32 + 4;
        case OP_CUP_WITHDRAW: return 8 + 32;
        case OP_CUP_CHECK_IN: return 8 + 8 + 32 + 4;
        case OP_DUEL_CANCEL: return 8;
        case OP_ADMIN_REGISTER_ASSET: return 32 + 4 + 1;
        case OP_ADMIN_CREATE_CUP: return 32 + 4 + 4 + 8 + 8 + 1 + 1 + 2 + 2 + 2 + 2;
        case OP_ADMIN_RETIRE_RULESET: return 32;
        default: return -1;
    }
}

// Structural plan check at decode (codec.decode_plan + Plan.of): BAD_PLAN.
inline bool plan_shape_ok(const uint8_t* p) {
    for (uint32_t i = 0; i < 6; ++i)
        if (p[i] > 5) return false;
    uint8_t slot = p[6];
    if (slot == qdojo_combat::NO_POWER_SLOT) return true;
    if (slot > 5) return false;
    return qdojo_combat::is_attack(p[slot]);
}

inline uint8_t decode_frame(const uint8_t* frame, Frame& out) {
    if (frame[FRAME_LEN - 1] != FRAME_SENTINEL) return BAD_FRAME;
    if (frame[0] != 'Q' || frame[1] != 'D' || frame[2] != 'C' || frame[3] != '1') return BAD_FRAME;
    uint16_t op = uint16_t(le(frame + 4, 2));
    uint16_t flags = uint16_t(le(frame + 6, 2));
    uint64_t nonce = le(frame + 8, 8);
    uint16_t len = uint16_t(le(frame + 16, 2));
    if (flags) return BAD_FRAME;
    for (uint32_t i = 18; i < 24; ++i)
        if (frame[i]) return BAD_FRAME;
    if (len > MAX_BODY) return BAD_FRAME;
    int32_t want = body_len(op);
    if (want < 0) return BAD_OPCODE;
    for (uint32_t i = FRAME_HEADER; i < FRAME_LEN - 1; ++i)
        if (i >= FRAME_HEADER + uint32_t(len) && frame[i]) return BAD_FRAME;
    if (int32_t(len) != want) return BAD_BODY;
    if (op == OP_REVEAL && !plan_shape_ok(frame + FRAME_HEADER + 8 + 1 + 32 + 4 + 32 + 32)) return BAD_PLAN;
    out.op = op;
    out.nonce = nonce;
    out.body = frame + FRAME_HEADER;
    out.len = len;
    return OK;
}

// Sequential little-endian body reader.
struct Reader {
    const uint8_t* p;
    uint32_t at;
    uint64_t u(uint32_t width) {
        uint64_t v = le(p + at, width);
        at += width;
        return v;
    }
    Id id() {
        Id x;
        copy32(x.b, p + at);
        at += 32;
        return x;
    }
    const uint8_t* raw(uint32_t width) {
        const uint8_t* r = p + at;
        at += width;
        return r;
    }
};

// ---- handlers (contract.py _op_*) -------------------------------------------------------
inline Res need_zero(int64_t amount) { return amount ? rej(BAD_AMOUNT) : ok(); }

// Live records are never evicted, so an id that was issued (1 <= id < next)
// but is no longer retained belonged to a terminal record. Answer as the
// reference does for a terminal record (protocol.md section 3: a terminal
// target returns its terminal status idempotently).
inline bool archived(uint64_t id, uint64_t next) { return id >= 1 && id < next; }

#define QD_TRY(expr)                   \
    do {                               \
        Res _r = (expr);               \
        if (!accepted(_r)) return _r;  \
    } while (0)

inline Res op_admin_register_asset(State& s, const Id& inv, Reader r, int64_t amount) {
    QD_TRY(need_zero(amount));
    Id fid = r.id();
    uint32_t version = uint32_t(r.u(4));
    uint8_t npc = uint8_t(r.u(1));
    if (!id_eq(inv, s.m.admin)) return rej(NOT_OWNER);
    if (npc > 1) return rej(BAD_BODY);
    int32_t a = asset_index(s, fid);
    if (a < 0) {
        for (uint32_t i = 0; i < CAP_ASSETS; ++i) {
            if (!s.assets[i].used) {
                a = int32_t(i);
                break;
            }
        }
        if (a < 0) return rej(FULL);  // the reference registry is unbounded (README.md)
    }
    s.assets[a].used = 1;
    s.assets[a].fighter_id = fid;
    s.assets[a].registry_version = version;
    s.assets[a].house_npc = npc;
    Body b{};
    b_id(b, fid);
    b_u64(b, version);
    b_u64(b, npc);
    emit(s, EV_ASSET_REGISTERED, b);
    return ok();
}

inline Res op_admin_retire_ruleset(State& s, const Id& inv, Reader r, int64_t amount) {
    QD_TRY(need_zero(amount));
    const uint8_t* digest = r.raw(32);
    if (!id_eq(inv, s.m.admin)) return rej(NOT_OWNER);
    // Only the manifest's ruleset can ever be admitted, so only its
    // retirement changes behaviour; the event records any digest.
    if (eq32(digest, s.m.ruleset_digest)) s.ruleset_retired = 1;
    Body b{};
    b_bytes(b, digest, 32);
    emit(s, EV_RULESET_RETIRED, b);
    return ok();
}

inline Res op_register_fighter(State& s, Host& h, const Id& inv, Reader r, int64_t amount) {
    QD_TRY(need_zero(amount));
    Id fid = r.id();
    uint32_t version = uint32_t(r.u(4));
    int32_t a = asset_index(s, fid);
    if (a < 0 || s.assets[a].registry_version != version) return rej(UNKNOWN_FIGHTER);
    Id owner;
    if (!owner_of(s, h, fid, owner)) return rej(BAD_STATE);
    if (!id_eq(owner, inv)) return rej(NOT_OWNER);
    int32_t fi = fighter_index(s, fid);
    if (fi < 0) {
        if (s.n_fighters >= s.m.max_fighters || s.n_fighters >= CAP_FIGHTERS) return rej(FULL);
        fi = int32_t(s.n_fighters++);
        Fighter& f = s.fighters[fi];
        f = Fighter{};
        f.fighter_id = fid;
        f.owner = owner;
        f.op = owner;
        f.auth_version = 1;
        f.house_npc = s.assets[a].house_npc;
        f.lock = L_IDLE;
        f.lifetime = uint16_t(RATING_INITIAL);
    } else if (!id_eq(s.fighters[fi].owner, owner)) {
        Fighter& f = s.fighters[fi];
        if (f.lock != L_IDLE && f.lock != L_TOURNAMENT) return rej(FIGHTER_BUSY);
        // The buyer binds the asset; rating, history and faults follow the fighter.
        f.owner = owner;
        f.op = owner;
        f.auth_version += 1;
    } else {
        return dup();
    }
    Body b{};
    b_id(b, fid);
    b_id(b, owner);
    b_u64(b, s.fighters[fi].auth_version);
    emit(s, EV_FIGHTER_REGISTERED, b);
    return ok();
}

inline Res op_set_operator(State& s, Host& h, const Id& inv, Reader r, int64_t amount) {
    QD_TRY(need_zero(amount));
    Id fid = r.id();
    Id new_op = r.id();
    uint32_t expected = uint32_t(r.u(4));
    int32_t fi = fighter_index(s, fid);
    if (fi < 0) return rej(UNKNOWN_FIGHTER);
    Fighter& f = s.fighters[fi];
    Id owner;
    if (!owner_of(s, h, fid, owner)) return rej(BAD_STATE);
    if (!id_eq(inv, owner) || !id_eq(owner, f.owner)) return rej(NOT_OWNER);
    if (expected != f.auth_version) return rej(STALE_AUTH);
    if (f.lock == L_TOURNAMENT) {
        int32_t k = cup_slot(s, f.lock_ref);
        if (k < 0 || !between_pairings(s.cups[k], f.fighter_id)) return rej(FIGHTER_BUSY);
    } else if (f.lock != L_IDLE) {
        return rej(FIGHTER_BUSY);
    }
    f.op = new_op;
    f.auth_version += 1;
    Body b{};
    b_id(b, f.fighter_id);
    b_id(b, f.op);
    b_u64(b, f.auth_version);
    emit(s, EV_OPERATOR_SET, b);
    return ok();
}

inline bool lifetime_ok(const State& s, uint64_t expires, uint64_t t) {
    if (expires < t) return false;  // negative lifetime
    uint64_t life = expires - t;
    return s.m.offer_lifetime_lo <= life && life <= s.m.offer_lifetime_hi;
}

inline Res open_offer(State& s, Fighter& f, uint16_t fi, const Id& inv, int64_t amount, uint32_t timing_id,
                      uint32_t fee_id, uint16_t tier_id, uint16_t max_gap, uint64_t t, uint64_t expires,
                      uint8_t kind, const Id& opponent, uint8_t fmt, uint8_t lock) {
    int32_t k = new_offer_slot(s);
    if (k < 0) return rej(FULL);
    uint64_t oid = s.next_offer++;
    Offer& o = s.offers[k];
    o = Offer{};
    o.used = 1;
    o.offer_id = oid;
    o.fighter_idx = fi;
    o.fighter_id = f.fighter_id;
    o.owner = f.owner;
    o.op = f.op;
    o.auth_version = f.auth_version;
    o.payer = inv;
    o.payout = f.owner;
    o.timing_id = timing_id;
    o.fee_id = fee_id;
    o.tier_id = tier_id;
    o.amount = amount;
    o.rating = f.lifetime;
    o.max_gap = max_gap;
    o.created = t;
    o.expires = expires;
    o.generation = s.generation;
    o.status = O_OPEN;
    o.kind = kind;
    o.opponent_id = opponent;
    o.series_format = fmt;
    o.escrowed = 1;
    f.lock = lock;
    f.lock_ref = oid;
    Body b{};
    b_u64(b, oid);
    b_id(b, f.fighter_id);
    b_u64(b, uint64_t(amount));
    b_u64(b, expires);
    emit(s, EV_OFFER_OPEN, b);
    return ok(oid);
}

inline Res op_queue_enter(State& s, Host& h, const Id& inv, Reader r, int64_t amount, uint64_t t) {
    Id fid = r.id();
    uint32_t auth = uint32_t(r.u(4));
    const uint8_t* ruleset = r.raw(32);
    uint32_t timing_id = uint32_t(r.u(4));
    uint32_t fee_id = uint32_t(r.u(4));
    uint16_t tier_id = uint16_t(r.u(2));
    uint16_t max_gap = uint16_t(r.u(2));
    uint64_t expires = r.u(8);
    int32_t fi = fighter_index(s, fid);
    if (fi < 0) return rej(UNKNOWN_FIGHTER);
    Fighter& f = s.fighters[fi];
    QD_TRY(authorize(s, h, f, inv, auth));
    QD_TRY(profiles(s, ruleset, timing_id, fee_id));
    const Tier* tr = tier(s, tier_id);
    if (!tr) return rej(INCOMPATIBLE);
    if (amount != tr->stake) return rej(BAD_AMOUNT);
    if (max_gap < MAX_GAP_LO || max_gap > MAX_GAP_HI) return rej(BAD_BODY);
    if (!lifetime_ok(s, expires, t)) return rej(BAD_BODY);
    if (f.lock != L_IDLE) return rej(FIGHTER_BUSY);
    if (f.house_npc) return rej(INCOMPATIBLE);
    if (t < f.cooldown_until) return rej(COOLDOWN);
    if (f.suspended_epoch == epoch_of(s, t)) return rej(COOLDOWN);
    if (open_offers(s) >= s.m.max_offers) return rej(FULL);
    QD_TRY(claim(s, f.owner));  // the payout recipient needs a credit slot
    return open_offer(s, f, uint16_t(fi), inv, amount, timing_id, fee_id, tier_id, max_gap, t, expires, K_RANKED,
                      id_zero(), 0, L_QUEUED);
}

inline Res cancel(State& s, Host& h, const Id& inv, uint64_t offer_id, uint8_t kind) {
    int32_t k = offer_slot(s, offer_id);
    if (k < 0 || s.offers[k].kind != kind) return rej(NOT_FOUND);
    Offer& o = s.offers[k];
    Id live;
    bool have = owner_of(s, h, o.fighter_id, live);
    if (!id_eq(inv, o.owner) && !id_eq(inv, o.op) && !(have && id_eq(inv, live))) return rej(NOT_OWNER);
    if (o.status == O_MATCHED) return rej(ALREADY_MATCHED);
    if (o.status != O_OPEN) return dup(offer_id);
    close_offer(s, o, O_CANCELLED);
    return ok(offer_id);
}

inline Res op_duel_offer(State& s, Host& h, const Id& inv, Reader r, int64_t amount, uint64_t t) {
    Id fid = r.id();
    uint32_t auth = uint32_t(r.u(4));
    Id opp_id = r.id();
    const uint8_t* ruleset = r.raw(32);
    uint32_t timing_id = uint32_t(r.u(4));
    uint32_t fee_id = uint32_t(r.u(4));
    uint64_t stake = r.u(8);
    uint8_t fmt = uint8_t(r.u(1));
    uint64_t expires = r.u(8);
    int32_t fi = fighter_index(s, fid);
    if (fi < 0) return rej(UNKNOWN_FIGHTER);
    Fighter& f = s.fighters[fi];
    QD_TRY(authorize(s, h, f, inv, auth));
    QD_TRY(profiles(s, ruleset, timing_id, fee_id));
    int32_t oi = fighter_index(s, opp_id);
    if (oi < 0) return rej(UNKNOWN_FIGHTER);
    if (oi == fi) return rej(INCOMPATIBLE);
    if (fmt > 2) return rej(BAD_BODY);
    if (stake < uint64_t(min_tier_stake(s)) || stake > uint64_t(MAX_STAKE)) return rej(BAD_AMOUNT);
    if (uint64_t(amount) != stake) return rej(BAD_AMOUNT);
    if (!lifetime_ok(s, expires, t)) return rej(BAD_BODY);
    if (f.lock != L_IDLE) return rej(FIGHTER_BUSY);
    if (t < f.cooldown_until) return rej(COOLDOWN);
    if (open_offers(s) >= s.m.max_offers) return rej(FULL);
    QD_TRY(claim(s, f.owner));  // the payout recipient needs a credit slot
    return open_offer(s, f, uint16_t(fi), inv, amount, timing_id, fee_id, 0, 0, t, expires, K_DUEL,
                      s.fighters[oi].fighter_id, fmt, L_DUEL_OFFER);
}

inline Res op_duel_accept(State& s, Host& h, const Id& inv, Reader r, int64_t amount, uint64_t t) {
    uint64_t offer_id = r.u(8);
    Id fid = r.id();
    uint32_t auth = uint32_t(r.u(4));
    int32_t k = offer_slot(s, offer_id);
    if (k < 0 || s.offers[k].kind != K_DUEL) return rej(NOT_FOUND);
    if (s.offers[k].status == O_MATCHED) return rej(ALREADY_MATCHED);
    if (s.offers[k].status != O_OPEN) return rej(EXPIRED);
    if (t >= s.offers[k].expires || s.offers[k].generation != s.generation) {
        close_offer(s, s.offers[k], t >= s.offers[k].expires ? O_EXPIRED : O_INVALIDATED);
        return rej(EXPIRED);
    }
    if (!still_valid(s, h, s.offers[k])) {
        close_offer(s, s.offers[k], O_INVALIDATED);
        return rej(INCOMPATIBLE);
    }
    if (!id_eq(fid, s.offers[k].opponent_id)) return rej(INCOMPATIBLE);
    int32_t di = fighter_index(s, fid);
    if (di < 0) return rej(UNKNOWN_FIGHTER);
    Fighter& d = s.fighters[di];
    QD_TRY(authorize(s, h, d, inv, auth));
    if (d.lock != L_IDLE) return rej(FIGHTER_BUSY);
    if (t < d.cooldown_until) return rej(COOLDOWN);
    if (amount != s.offers[k].amount) return rej(BAD_AMOUNT);
    if (fights_in_use(s) >= s.m.max_fights) return rej(FULL);
    QD_TRY(claim(s, d.owner));
    int32_t mk = new_offer_slot(s);
    if (mk < 0) return rej(FULL);
    Offer& o = s.offers[k];
    uint64_t mine = s.next_offer++;
    Offer& acc = s.offers[mk];
    acc = Offer{};
    acc.used = 1;
    acc.offer_id = mine;
    acc.fighter_idx = uint16_t(di);
    acc.fighter_id = d.fighter_id;
    acc.owner = d.owner;
    acc.op = d.op;
    acc.auth_version = d.auth_version;
    acc.payer = inv;
    acc.payout = d.owner;
    acc.timing_id = o.timing_id;
    acc.fee_id = o.fee_id;
    acc.amount = amount;
    acc.rating = d.lifetime;
    acc.created = t;
    acc.expires = o.expires;
    acc.generation = s.generation;
    acc.status = O_MATCHED;
    acc.kind = K_DUEL;
    acc.escrowed = 1;
    o.status = O_MATCHED;
    int32_t cs = start_contest(s, M_DUEL, o.series_format, o, acc, t, false, 0, 0, 0);
    uint64_t cid = cs >= 0 ? s.contests[cs].contest_id : 0;
    Body b{};
    b_u64(b, o.offer_id);
    b_u64(b, cid);
    emit(s, EV_DUEL_ACCEPTED, b);
    return ok(cid);
}

struct FightRef {
    Fight* f;
    uint8_t slot;  // 0 = A, 1 = B
    const Participant* part;
};

inline Res fight_for(State& s, const Id& inv, uint64_t fight_id, uint8_t round_index, const Id& fid, uint32_t auth,
                     const uint8_t* rsd, FightRef& out) {
    int32_t k = fight_slot(s, fight_id);
    if (k < 0) return rej(archived(fight_id, s.next_fight) ? TERMINAL : NOT_FOUND);
    Fight& f = s.fights[k];
    if (f.phase == P_DONE) return rej(TERMINAL);
    int32_t cs = contest_slot(s, f.contest_id);
    if (cs < 0) return rej(NOT_FOUND);
    const Contest& c = s.contests[cs];
    uint8_t slot;
    if (id_eq(fid, c.a.fighter_id)) slot = 0;
    else if (id_eq(fid, c.b.fighter_id)) slot = 1;
    else return rej(UNKNOWN_FIGHTER);
    const Participant& p = slot == 0 ? c.a : c.b;
    if (!id_eq(inv, p.op)) return rej(NOT_OPERATOR);
    if (auth != p.auth_version) return rej(STALE_AUTH);
    if (round_index != f.state.round_index) return rej(BAD_STATE);
    if (!eq32(rsd, f.round_state_digest)) return rej(BAD_STATE);
    out.f = &f;
    out.slot = slot;
    out.part = &p;
    return ok();
}

inline Res op_commit(State& s, const Id& inv, Reader r, int64_t amount, uint64_t t) {
    QD_TRY(need_zero(amount));
    uint64_t fight_id = r.u(8);
    uint8_t round = uint8_t(r.u(1));
    Id fid = r.id();
    uint32_t auth = uint32_t(r.u(4));
    const uint8_t* rsd = r.raw(32);
    const uint8_t* commitment = r.raw(32);
    FightRef fr;
    QD_TRY(fight_for(s, inv, fight_id, round, fid, auth, rsd, fr));
    Fight& f = *fr.f;
    if (f.phase != P_COMMIT || t <= f.start_tick) return rej(WRONG_PHASE);
    if (t > f.commit_last) return rej(LATE);
    if (f.committed[fr.slot]) {
        if (eq32(f.commitment[fr.slot], commitment)) return dup(f.fight_id);
        return rej(ALREADY_COMMITTED);
    }
    f.committed[fr.slot] = 1;
    copy32(f.commitment[fr.slot], commitment);
    Body b{};
    b_u64(b, f.fight_id);
    b_u64(b, f.state.round_index);
    b_id(b, fid);
    b_bytes(b, commitment, 32);
    emit(s, EV_COMMITTED, b);
    return ok(f.fight_id);
}

inline Res op_reveal(State& s, const Id& inv, Reader r, int64_t amount, uint64_t t) {
    QD_TRY(need_zero(amount));
    uint64_t fight_id = r.u(8);
    uint8_t round = uint8_t(r.u(1));
    Id fid = r.id();
    uint32_t auth = uint32_t(r.u(4));
    const uint8_t* rsd = r.raw(32);
    const uint8_t* salt = r.raw(32);
    const uint8_t* plan_bytes = r.raw(7);
    FightRef fr;
    QD_TRY(fight_for(s, inv, fight_id, round, fid, auth, rsd, fr));
    Fight& f = *fr.f;
    if (f.phase == P_COMMIT && t <= f.commit_last) return rej(WRONG_PHASE);
    if (f.phase != P_REVEAL) return rej(WRONG_PHASE);
    if (t > f.reveal_last) return rej(LATE);
    const Participant& p = *fr.part;
    uint8_t expected[32];
    s.work.sha_blocks += blocks_for(uint32_t(sizeof(qdojo_combat::TAG_COMMIT)) + 32 + 32 + 8 + 1 + 32 + 32 + 32 + 32 + 4 + 32 + 7);
    qdojo_combat::commitment(s.m.network_id.b, s.m.contract_id.b, f.fight_id, f.state.round_index, f.context_digest,
                             f.round_state_digest, p.fighter_id.b, p.op.b, p.auth_version, salt, plan_bytes,
                             expected);
    if (!f.committed[fr.slot] || !eq32(f.commitment[fr.slot], expected)) return rej(BAD_COMMITMENT);
    qdojo_combat::Plan plan;
    qdojo_combat::decode_plan(plan_bytes, plan);
    const qdojo_combat::Fighter& st = fr.slot == 0 ? f.state.a : f.state.b;
    if (!qdojo_combat::validate_plan(plan, st)) return rej(BAD_PLAN);
    if (f.revealed[fr.slot]) {
        bool same = eq32(f.salt[fr.slot], salt) && f.plan[fr.slot].power_slot == plan.power_slot;
        for (uint32_t i = 0; i < 6; ++i)
            if (f.plan[fr.slot].actions[i] != plan.actions[i]) same = false;
        return same ? dup(f.fight_id) : rej(ALREADY_REVEALED);
    }
    f.revealed[fr.slot] = 1;
    copy32(f.salt[fr.slot], salt);
    f.plan[fr.slot] = plan;
    Body b{};
    b_u64(b, f.fight_id);
    b_u64(b, f.state.round_index);
    b_id(b, p.fighter_id);
    b_bytes(b, salt, 32);
    b_bytes(b, plan_bytes, 7);
    emit(s, EV_REVEALED, b);
    return ok(f.fight_id);
}

inline Res op_advance(State& s, Reader r, int64_t amount, uint64_t t) {
    QD_TRY(need_zero(amount));
    uint8_t kind = uint8_t(r.u(1));
    uint64_t target = r.u(8);
    if (kind == 1) {
        int32_t k = offer_slot(s, target);
        if (k < 0) return archived(target, s.next_offer) ? ok(target) : rej(NOT_FOUND);
        Offer& o = s.offers[k];
        if (o.status == O_OPEN && (t >= o.expires || o.generation != s.generation))
            close_offer(s, o, t >= o.expires ? O_EXPIRED : O_INVALIDATED);
        return ok(target);
    }
    if (kind == 2) return fight_slot(s, target) >= 0 || archived(target, s.next_fight) ? ok(target) : rej(NOT_FOUND);
    if (kind == 3) return cup_slot(s, target) >= 0 || archived(target, s.next_cup) ? ok(target) : rej(NOT_FOUND);
    return rej(BAD_BODY);
}

inline Res op_withdraw(State& s, Host& h, const Id& inv, int64_t amount) {
    QD_TRY(need_zero(amount));
    int32_t a = account_index(s, inv);
    int64_t value = a >= 0 ? s.accounts[a].credit : 0;
    if (!value) return ok();
    // Debit first; restore on a reported failure (spec.md section 5).
    s.accounts[a].credit = 0;
    s.credit_count -= 1;
    s.balance = sub_i64(s, s.balance, value);
    s.paid_out = add_i64(s, s.paid_out, value);
    if (!transfer(s, h, inv, value)) {
        s.balance = add_i64(s, s.balance, value);
        s.paid_out = sub_i64(s, s.paid_out, value);
        credit(s, inv, value);
        Body b{};
        b_id(b, inv);
        b_u64(b, uint64_t(value));
        emit(s, EV_WITHDRAW_FAILED, b);
        return rej(TRANSFER_FAILED);
    }
    Body b{};
    b_id(b, inv);
    b_u64(b, uint64_t(value));
    emit(s, EV_WITHDRAWN, b);
    return ok();
}

inline Res op_admin_create_cup(State& s, const Id& inv, Reader r, int64_t amount, uint64_t t) {
    const uint8_t* ruleset = r.raw(32);
    CupDescriptor d{};
    d.timing_id = uint32_t(r.u(4));
    d.fee_id = uint32_t(r.u(4));
    uint64_t entry_fee = r.u(8);
    d.registration_close = r.u(8);
    d.min_entrants = uint8_t(r.u(1));
    d.max_entrants = uint8_t(r.u(1));
    d.level_ticks = uint16_t(r.u(2));
    d.first_level_delay = uint16_t(r.u(2));
    d.checkin_ticks = uint16_t(r.u(2));
    d.replay_delay = uint16_t(r.u(2));
    if (!id_eq(inv, s.m.admin)) return rej(NOT_OWNER);
    QD_TRY(profiles(s, ruleset, d.timing_id, d.fee_id));
    if (live_cups(s) >= s.m.max_cups) return rej(FULL);
    if (!(4 <= d.min_entrants && d.min_entrants <= d.max_entrants && d.max_entrants <= s.m.max_cup_entrants))
        return rej(BAD_BODY);
    if (!(0 < entry_fee && entry_fee <= uint64_t(MAX_STAKE)) || d.registration_close <= t) return rej(BAD_BODY);
    // Every scheduled boundary must fall on a tick END_TICK examines.
    if (d.checkin_ticks < 1 || d.first_level_delay < 2 || d.replay_delay < 1) return rej(BAD_BODY);
    d.entry_fee = int64_t(entry_fee);
    const TimingProfile* tp = timing(s, d.timing_id);
    uint64_t cr = uint64_t(tp->commit_ticks) + tp->reveal_ticks;
    uint64_t worst = uint64_t(d.checkin_ticks) + 7 * 3 * cr + d.replay_delay + 3 * 3 * cr + 2;
    if (worst > d.level_ticks) return rej(INCOMPATIBLE);
    int32_t k = new_cup_slot(s);
    if (k < 0) return rej(FULL);
    uint64_t cid = s.next_cup++;
    Cup& cup = s.cups[k];
    cup = Cup{};
    cup.used = 1;
    cup.cup_id = cid;
    cup.d = d;
    cup.sponsor = inv;
    cup.sponsorship = amount;
    cup.generation = s.generation;
    cup.created = t;
    cup.status = CUP_REGISTRATION;
    cup.has_pot = amount ? 1 : 0;
    Body b{};
    b_u64(b, cid);
    b_u64(b, entry_fee);
    b_u64(b, uint64_t(amount));
    b_u64(b, d.registration_close);
    emit(s, EV_CUP_CREATED, b);
    return ok(cid);
}

inline Res op_cup_register(State& s, Host& h, const Id& inv, Reader r, int64_t amount, uint64_t t) {
    uint64_t cup_id = r.u(8);
    Id fid = r.id();
    uint32_t auth = uint32_t(r.u(4));
    int32_t k = cup_slot(s, cup_id);
    if (k < 0) return rej(archived(cup_id, s.next_cup) ? WRONG_PHASE : NOT_FOUND);
    Cup& cup = s.cups[k];
    if (cup.status != CUP_REGISTRATION || t >= cup.d.registration_close) return rej(WRONG_PHASE);
    int32_t fi = fighter_index(s, fid);
    if (fi < 0) return rej(UNKNOWN_FIGHTER);
    Fighter& f = s.fighters[fi];
    QD_TRY(authorize(s, h, f, inv, auth));
    if (f.house_npc) return rej(INCOMPATIBLE);
    if (amount != cup.d.entry_fee) return rej(BAD_AMOUNT);
    if (f.lock != L_IDLE) return rej(FIGHTER_BUSY);
    if (t < f.cooldown_until) return rej(COOLDOWN);
    if (cup.n_entries >= cup.d.max_entrants || cup.n_entries >= CAP_CUP_ENTRANTS) return rej(FULL);
    if (represented(s, cup, f.owner, f.op, nullptr)) return rej(INCOMPATIBLE);
    QD_TRY(claim(s, f.owner));
    CupEntry& e = cup.entries[cup.n_entries];
    cup.n_entries = uint8_t(cup.n_entries + 1);
    e.fighter_id = f.fighter_id;
    e.payer = inv;
    e.owner = f.owner;
    e.op = f.op;
    e.fighter_idx = uint16_t(fi);
    e.amount = amount;
    cup.has_pot = 1;
    f.lock = L_TOURNAMENT;
    f.lock_ref = cup.cup_id;
    Body b{};
    b_u64(b, cup.cup_id);
    b_id(b, f.fighter_id);
    b_u64(b, uint64_t(amount));
    emit(s, EV_CUP_ENTRY, b);
    return ok(cup.cup_id);
}

inline Res op_cup_withdraw(State& s, const Id& inv, Reader r, int64_t amount, uint64_t t) {
    QD_TRY(need_zero(amount));
    uint64_t cup_id = r.u(8);
    Id fid = r.id();
    int32_t k = cup_slot(s, cup_id);
    if (k < 0) return rej(archived(cup_id, s.next_cup) ? WRONG_PHASE : NOT_FOUND);
    Cup& cup = s.cups[k];
    if (cup.status != CUP_REGISTRATION || t >= cup.d.registration_close) return rej(WRONG_PHASE);
    int32_t ei = -1;
    for (uint32_t i = 0; i < CAP_CUP_ENTRANTS; ++i)
        if (i < cup.n_entries && id_eq(cup.entries[i].fighter_id, fid)) ei = int32_t(i);
    if (ei < 0) return rej(NOT_FOUND);
    CupEntry e = cup.entries[ei];
    Fighter& f = s.fighters[e.fighter_idx];
    if (!id_eq(inv, f.owner) && !id_eq(inv, f.op) && !id_eq(inv, e.payer)) return rej(NOT_OWNER);
    for (uint32_t i = 0; i + 1 < CAP_CUP_ENTRANTS; ++i)
        if (int32_t(i) >= ei && i + 1 < cup.n_entries) cup.entries[i] = cup.entries[i + 1];
    cup.n_entries = uint8_t(cup.n_entries - 1);
    credit(s, e.payer, e.amount);
    if (cup.n_entries == 0 && cup.sponsorship == 0) cup.has_pot = 0;
    f.lock = L_IDLE;
    f.lock_ref = 0;
    Body b{};
    b_u64(b, cup.cup_id);
    b_id(b, e.fighter_id);
    b_id(b, e.payer);
    b_u64(b, uint64_t(e.amount));
    emit(s, EV_CUP_WITHDRAWN, b);
    return ok(cup.cup_id);
}

inline Res op_cup_check_in(State& s, Host& h, const Id& inv, Reader r, int64_t amount, uint64_t t) {
    QD_TRY(need_zero(amount));
    uint64_t cup_id = r.u(8);
    uint64_t pairing_id = r.u(8);
    Id fid = r.id();
    uint32_t auth = uint32_t(r.u(4));
    int32_t k = cup_slot(s, cup_id);
    if (k < 0) return rej(archived(cup_id, s.next_cup) ? WRONG_PHASE : NOT_FOUND);
    Cup& cup = s.cups[k];
    bool found = pairing_id >= 1 && pairing_id <= cup.n_pairings;
    if (cup.status != CUP_RUNNING || !found) return rej(WRONG_PHASE);
    Pairing& p = cup.pairings[pairing_id - 1];
    if (p.status != PS_SCHEDULED) return rej(WRONG_PHASE);
    if (!(cup.level_start <= t && t < cup.level_start + cup.d.checkin_ticks) || p.level != cup.level)
        return rej(WRONG_PHASE);
    bool is_a = p.has_a && id_eq(p.a, fid), is_b = p.has_b && id_eq(p.b, fid);
    if (!is_a && !is_b) return rej(UNKNOWN_FIGHTER);
    int32_t fi = fighter_index(s, fid);
    if (fi < 0) return rej(UNKNOWN_FIGHTER);
    Fighter& f = s.fighters[fi];
    QD_TRY(authorize(s, h, f, inv, auth));
    if (represented(s, cup, f.owner, f.op, &fid)) return rej(INCOMPATIBLE);
    if ((is_a && p.checked_a) || (is_b && p.checked_b)) return dup(p.pairing_id);
    if (t < f.cooldown_until) return rej(COOLDOWN);  // check-in observes the fault cooldown
    QD_TRY(claim(s, f.owner));                        // a transferred finalist's owner may be new
    if (is_a) p.checked_a = 1;
    else p.checked_b = 1;
    Body b{};
    b_u64(b, cup.cup_id);
    b_u64(b, p.pairing_id);
    b_id(b, fid);
    emit(s, EV_CUP_CHECKED_IN, b);
    return ok(p.pairing_id);
}

#undef QD_TRY

inline Res run_handler(State& s, Host& h, const Id& inv, const Frame& fr, int64_t amount, uint64_t t) {
    Reader r{fr.body, 0};
    switch (fr.op) {
        case OP_REGISTER_FIGHTER: return op_register_fighter(s, h, inv, r, amount);
        case OP_SET_OPERATOR: return op_set_operator(s, h, inv, r, amount);
        case OP_QUEUE_ENTER: return op_queue_enter(s, h, inv, r, amount, t);
        case OP_QUEUE_CANCEL: {
            if (amount) return rej(BAD_AMOUNT);
            return cancel(s, h, inv, r.u(8), K_RANKED);
        }
        case OP_DUEL_OFFER: return op_duel_offer(s, h, inv, r, amount, t);
        case OP_DUEL_ACCEPT: return op_duel_accept(s, h, inv, r, amount, t);
        case OP_COMMIT: return op_commit(s, inv, r, amount, t);
        case OP_REVEAL: return op_reveal(s, inv, r, amount, t);
        case OP_ADVANCE: return op_advance(s, r, amount, t);
        case OP_WITHDRAW: return op_withdraw(s, h, inv, amount);
        case OP_CUP_REGISTER: return op_cup_register(s, h, inv, r, amount, t);
        case OP_CUP_WITHDRAW: return op_cup_withdraw(s, inv, r, amount, t);
        case OP_CUP_CHECK_IN: return op_cup_check_in(s, h, inv, r, amount, t);
        case OP_DUEL_CANCEL: {
            if (amount) return rej(BAD_AMOUNT);
            return cancel(s, h, inv, r.u(8), K_DUEL);
        }
        case OP_ADMIN_REGISTER_ASSET: return op_admin_register_asset(s, inv, r, amount);
        case OP_ADMIN_CREATE_CUP: return op_admin_create_cup(s, inv, r, amount, t);
        case OP_ADMIN_RETIRE_RULESET: return op_admin_retire_ruleset(s, inv, r, amount);
        default: return rej(BAD_OPCODE);
    }
}

// protocol.md section 5: ensure_service(T). Returns false if ticks run backwards.
inline bool ensure_service(State& s, uint64_t t) {
    if (t < s.last_observed) return false;
    if (t == s.last_observed) return true;
    if (t - 1 != s.last_serviced) {
        s.generation += 1;
        Body b{};
        b_u64(b, s.generation);
        b_u64(b, s.last_serviced);
        b_u64(b, t);
        emit(s, EV_SERVICE_GAP, b);
    }
    s.last_observed = t;
    s.tick = t;
    return true;
}

inline void reset_work(State& s) { s.work = Work{}; }

inline CallResult reject(State& s, Host& h, const Id& inv, int64_t amount, uint8_t code, uint16_t op) {
    CallResult out;
    out.code = code;
    out.op = op;
    out.target = 0;
    out.refunded = refund(s, h, inv, amount);
    return out;
}

}  // namespace detail

// ============================================================ entry points

// INITIALIZE. Returns false for a manifest the compiled capacities or
// ruleset cannot serve; the state is then unusable.
inline bool init(State& s, const Manifest& m, uint64_t construction_tick) {
    // Qubic hands a contract zeroed state; zero it here too so init is
    // total, without a state-sized temporary.
    uint8_t* raw = reinterpret_cast<uint8_t*>(&s);
    for (uint64_t i = 0; i < sizeof(State); ++i) raw[i] = 0;
    s.m = m;
    for (uint32_t i = 0; i < 32; ++i)
        if (m.ruleset_digest[i] != qdojo_combat::RULESET_DIGEST[i]) return false;
    if (m.max_fighters > CAP_FIGHTERS || m.max_accounts > CAP_ACCOUNTS || m.max_offers > CAP_OPEN_OFFERS ||
        m.max_fights > CAP_FIGHTS || m.max_cups > CAP_CUPS || m.max_cup_entrants > CAP_CUP_ENTRANTS ||
        m.event_ring > CAP_EVENTS || m.event_ring == 0 || m.ticks_per_epoch <= 0 || m.season_epochs <= 0 ||
        m.match_interval == 0 || m.faults_per_epoch == 0)
        return false;
    bool any_tier = false;
    for (uint32_t i = 0; i < CAP_TIERS; ++i)
        if (m.tiers[i].used) any_tier = true;
    if (!any_tier) return false;
    for (uint32_t i = 0; i < CAP_FEES; ++i) {
        const FeeProfile& f = m.fees[i];
        if (!f.used) continue;
        if (f.rake_bps > BPS || uint32_t(f.house_bps) + f.dev_bps + f.share_bps != uint32_t(BPS)) return false;
    }
    s.generation = 1;
    s.last_serviced = s.last_observed = s.tick = construction_tick;
    s.next_offer = s.next_contest = s.next_fight = s.next_cup = 1;
    // The admin and the fee recipients hold account slots from construction.
    detail::add_slot(s, m.admin);
    for (uint32_t i = 0; i < CAP_FEES; ++i) {
        if (!m.fees[i].used) continue;
        detail::add_slot(s, m.fees[i].house);
        detail::add_slot(s, m.fees[i].dev);
        detail::add_slot(s, m.fees[i].share);
    }
    // EVENT_TAG_GENESIS = SHA256("qdojo/combat/event/genesis/v1\0")
    qdojo_combat::sha256(reinterpret_cast<const uint8_t*>(detail::TAG_EVENT_GENESIS),
                         uint32_t(sizeof(detail::TAG_EVENT_GENESIS)), s.event_digest);
    return true;
}

// BEGIN_TICK
inline void begin_tick(State& s, Host& h, uint64_t t) {
    (void)h;
    detail::reset_work(s);
    detail::ensure_service(s, t);
}

// The single Dispatch user procedure: one confirmed transaction with
// invocator == originator and `amount` QU attached.
inline CallResult dispatch(State& s, Host& h, const Id& inv, const uint8_t frame[FRAME_LEN], int64_t amount,
                           uint64_t t) {
    using namespace detail;
    reset_work(s);
    CallResult out{HOST_ERROR, 0, 0, 0};
    if (amount < 0 || s.balance > I64_MAX - amount || t < s.last_observed) return out;
    ensure_service(s, t);
    s.balance += amount;
    Frame fr;
    uint8_t code = decode_frame(frame, fr);
    if (code != OK) return reject(s, h, inv, amount, code, 0);
    uint8_t digest[32];
    sha(s, frame, FRAME_LEN, digest);
    if (fr.op == OP_ADVANCE && fr.nonce != 0) return reject(s, h, inv, amount, BAD_BODY, fr.op);
    int32_t acct = -1;
    if (fr.op != OP_ADVANCE) {
        // Only registry-backed users and account holders get state slots (protocol.md section 3).
        if (!eligible(s, h, inv, fr.op, fr.body)) return reject(s, h, inv, amount, NOT_OWNER, fr.op);
        Res c = claim(s, inv);
        if (!accepted(c)) return reject(s, h, inv, amount, c.code, fr.op);
        acct = account_index(s, inv);
        if (acct >= 0 && s.accounts[acct].has_nonce) {
            const Account& a = s.accounts[acct];
            if (fr.nonce == a.nonce) {
                if (eq32(a.digest, digest)) {
                    uint64_t target = a.last_target;
                    out.code = DUPLICATE;
                    out.op = fr.op;
                    out.target = target;
                    out.refunded = refund(s, h, inv, amount);
                    return out;
                }
                return reject(s, h, inv, amount, NONCE_CONFLICT, fr.op);
            }
            if (fr.nonce < a.nonce) return reject(s, h, inv, amount, STALE, fr.op);
        }
        if (fr.nonce == 0) return reject(s, h, inv, amount, STALE, fr.op);
    }
    Res r = run_handler(s, h, inv, fr, amount, t);
    if (!accepted(r)) return reject(s, h, inv, amount, r.code, fr.op);
    if (fr.op != OP_ADVANCE) {
        acct = account_get_or_alloc(s, inv);
        if (acct >= 0) {
            Account& a = s.accounts[acct];
            a.has_nonce = 1;
            a.nonce = fr.nonce;
            copy32(a.digest, digest);
            a.last_target = r.target;
            a.last_op = fr.op;
        } else {
            ++s.faults.account_overflow;
        }
    }
    out.code = r.code;
    out.op = fr.op;
    out.target = r.target;
    out.refunded = 0;
    return out;
}

// END_TICK: service voids, deadlines and resolution, duel expiry, matching, cups.
inline void end_tick(State& s, Host& h, uint64_t t) {
    using namespace detail;
    reset_work(s);
    if (!ensure_service(s, t)) return;
    // Objective service gaps void unfinished work captured under an older generation.
    {
        uint64_t ids[CAP_CONTEST_SLOTS];
        uint32_t n = 0;
        for (uint32_t i = 0; i < CAP_CONTEST_SLOTS; ++i) {
            const Contest& c = s.contests[i];
            if (c.used && c.status == C_ACTIVE && c.generation != s.generation && c.mode != M_CUP)
                ids[n++] = c.contest_id;
        }
        sort_u64(ids, n);
        for (uint32_t i = 0; i < CAP_CONTEST_SLOTS; ++i) {
            if (i >= n) break;
            int32_t k = contest_slot(s, ids[i]);
            if (k >= 0) void_contest(s, s.contests[k], t);
        }
    }
    {
        uint64_t ids[CAP_OFFER_SLOTS];
        uint32_t n = 0;
        for (uint32_t i = 0; i < CAP_OFFER_SLOTS; ++i) {
            const Offer& o = s.offers[i];
            if (o.used && o.status == O_OPEN && o.generation != s.generation) ids[n++] = o.offer_id;
        }
        sort_u64(ids, n);
        for (uint32_t i = 0; i < CAP_OFFER_SLOTS; ++i) {
            if (i >= n) break;
            int32_t k = offer_slot(s, ids[i]);
            if (k >= 0) close_offer(s, s.offers[k], O_INVALIDATED);
        }
    }
    {
        uint64_t ids[CAP_CUP_SLOTS];
        uint32_t n = 0;
        for (uint32_t i = 0; i < CAP_CUP_SLOTS; ++i) {
            const Cup& c = s.cups[i];
            if (c.used && (c.status == CUP_REGISTRATION || c.status == CUP_RUNNING) && c.generation != s.generation)
                ids[n++] = c.cup_id;
        }
        sort_u64(ids, n);
        for (uint32_t i = 0; i < CAP_CUP_SLOTS; ++i) {
            if (i >= n) break;
            int32_t k = cup_slot(s, ids[i]);
            if (k >= 0) abort_cup(s, s.cups[k], t, AB_SERVICE_VOID);
        }
    }
    // Deadlines and resolution, at most max_fights, in fight_id order. The
    // set is fixed before processing: fights created now start next tick.
    {
        uint64_t ids[CAP_FIGHT_SLOTS];
        uint32_t n = 0;
        for (uint32_t i = 0; i < CAP_FIGHT_SLOTS; ++i) {
            const Fight& f = s.fights[i];
            if (f.used && f.phase != P_DONE) ids[n++] = f.fight_id;
        }
        sort_u64(ids, n);
        for (uint32_t i = 0; i < CAP_FIGHT_SLOTS; ++i) {
            if (i >= n || i >= s.m.max_fights) break;
            s.work.fights += 1;
            int32_t k = fight_slot(s, ids[i]);
            if (k >= 0 && s.fights[k].phase != P_DONE) fight_tick(s, s.fights[k], t);
        }
    }
    {
        uint64_t ids[CAP_OFFER_SLOTS];
        uint32_t n = 0;
        for (uint32_t i = 0; i < CAP_OFFER_SLOTS; ++i) {
            const Offer& o = s.offers[i];
            if (o.used && o.status == O_OPEN && o.kind == K_DUEL && t >= o.expires) ids[n++] = o.offer_id;
        }
        sort_u64(ids, n);
        for (uint32_t i = 0; i < CAP_OFFER_SLOTS; ++i) {
            if (i >= n) break;
            int32_t k = offer_slot(s, ids[i]);
            if (k >= 0) close_offer(s, s.offers[k], O_EXPIRED);
        }
    }
    if (t % s.m.match_interval == 0) {
        // Expired ranked offers are closed and refunded on every matching
        // tick, even when no pass runs, in offer_id order.
        uint64_t ids[CAP_OFFER_SLOTS];
        uint32_t n = 0;
        for (uint32_t i = 0; i < CAP_OFFER_SLOTS; ++i) {
            const Offer& o = s.offers[i];
            if (o.used && o.status == O_OPEN && o.kind == K_RANKED && t >= o.expires) ids[n++] = o.offer_id;
        }
        sort_u64(ids, n);
        for (uint32_t i = 0; i < CAP_OFFER_SLOTS; ++i) {
            if (i >= n) break;
            int32_t k = offer_slot(s, ids[i]);
            if (k >= 0) close_offer(s, s.offers[k], O_EXPIRED);
        }
        uint32_t ranked = 0;
        for (uint32_t i = 0; i < CAP_OFFER_SLOTS; ++i) {
            const Offer& o = s.offers[i];
            if (o.used && o.status == O_OPEN && o.kind == K_RANKED) ++ranked;
        }
        if (ranked >= 2) matching(s, h, t);
    }
    {
        uint64_t ids[CAP_CUP_SLOTS];
        uint32_t n = 0;
        for (uint32_t i = 0; i < CAP_CUP_SLOTS; ++i)
            if (s.cups[i].used) ids[n++] = s.cups[i].cup_id;
        sort_u64(ids, n);
        for (uint32_t i = 0; i < CAP_CUP_SLOTS; ++i) {
            if (i >= n) break;
            int32_t k = cup_slot(s, ids[i]);
            if (k >= 0) cup_tick(s, s.cups[k], t);
        }
    }
    s.last_serviced = t;
}

// ============================================================ queries (read-only)

// Sum of every liability bucket: open-offer escrow, contest escrow, cup
// reserve, withdrawable credits (spec.md section 5). Must equal balance.
inline int64_t liabilities(const State& s) {
    int64_t sum = s.overflow_credit;
    for (uint32_t i = 0; i < CAP_OFFER_SLOTS; ++i)
        if (s.offers[i].used && s.offers[i].escrowed) sum += s.offers[i].amount;
    for (uint32_t i = 0; i < CAP_CONTEST_SLOTS; ++i)
        if (s.contests[i].used && s.contests[i].has_pot) sum += s.contests[i].pot_a + s.contests[i].pot_b;
    for (uint32_t i = 0; i < CAP_CUP_SLOTS; ++i) {
        const Cup& c = s.cups[i];
        if (!c.used || !c.has_pot) continue;
        sum += c.sponsorship;
        for (uint32_t k = 0; k < CAP_CUP_ENTRANTS; ++k)
            if (k < c.n_entries) sum += c.entries[k].amount;
    }
    for (uint32_t i = 0; i < CAP_ACCOUNTS; ++i)
        if (s.accounts[i].used) sum += s.accounts[i].credit;
    return sum;
}

struct ServiceView {
    uint64_t generation, last_serviced, last_observed, event_seq;
    uint8_t event_digest[32];
    int64_t balance, paid_out;
};
inline ServiceView query_service(const State& s) {
    ServiceView v;
    v.generation = s.generation;
    v.last_serviced = s.last_serviced;
    v.last_observed = s.last_observed;
    v.event_seq = s.event_seq;
    copy32(v.event_digest, s.event_digest);
    v.balance = s.balance;
    v.paid_out = s.paid_out;
    return v;
}

struct AccountView {
    int64_t credit;
    uint8_t has_nonce;
    uint64_t nonce;
};
inline AccountView query_account(const State& s, const Id& who) {
    AccountView v{0, 0, 0};
    for (uint32_t i = 0; i < CAP_ACCOUNTS; ++i) {
        const Account& a = s.accounts[i];
        if (a.used && id_eq(a.who, who)) {
            v.credit = a.credit;
            v.has_nonce = a.has_nonce;
            v.nonce = a.nonce;
        }
    }
    return v;
}

inline const Fighter* query_fighter(const State& s, const Id& fid) {
    for (uint32_t i = 0; i < CAP_FIGHTERS; ++i) {
        if (i >= s.n_fighters) break;
        if (id_eq(s.fighters[i].fighter_id, fid)) return &s.fighters[i];
    }
    return nullptr;
}
inline const Offer* query_offer(const State& s, uint64_t id) {
    for (uint32_t i = 0; i < CAP_OFFER_SLOTS; ++i)
        if (s.offers[i].used && s.offers[i].offer_id == id) return &s.offers[i];
    return nullptr;
}
inline const Fight* query_fight(const State& s, uint64_t id) {
    for (uint32_t i = 0; i < CAP_FIGHT_SLOTS; ++i)
        if (s.fights[i].used && s.fights[i].fight_id == id) return &s.fights[i];
    return nullptr;
}
inline const Contest* query_contest(const State& s, uint64_t id) {
    for (uint32_t i = 0; i < CAP_CONTEST_SLOTS; ++i)
        if (s.contests[i].used && s.contests[i].contest_id == id) return &s.contests[i];
    return nullptr;
}
inline const Cup* query_cup(const State& s, uint64_t id) {
    for (uint32_t i = 0; i < CAP_CUP_SLOTS; ++i)
        if (s.cups[i].used && s.cups[i].cup_id == id) return &s.cups[i];
    return nullptr;
}

// contract.py events_page: retained events with seq > after, at most 64.
struct EventPage {
    uint32_t n;
    Event events[64];
};
inline void query_events(const State& s, uint64_t after, uint32_t limit, EventPage& out) {
    out.n = 0;
    if (limit > 64) limit = 64;
    uint64_t oldest = s.event_seq > s.m.event_ring ? s.event_seq - s.m.event_ring + 1 : 1;
    uint64_t seq = after + 1 > oldest ? after + 1 : oldest;
    for (uint32_t i = 0; i < 64; ++i) {
        if (out.n >= limit || seq > s.event_seq) break;
        out.events[out.n++] = s.events[(seq - 1) % s.m.event_ring];
        ++seq;
    }
}

// contract.py season_standings, bounded: the season must be the current or
// the previous one (older seasons live in the exported history).
struct StandingRow {
    Id fighter_id;
    uint16_t rating;
    uint16_t defeated;
    uint32_t wins, fights;
    uint8_t qualified;
};
struct Standings {
    uint32_t season;
    uint8_t final;
    uint8_t status;  // 0 NO_CHAMPION, 1 CHAMPION, 2 PLAYOFF
    Id champion;
    uint32_t n_rows;  // all rows with stats
    uint32_t n_page;
    StandingRow page[STANDINGS_PAGE];  // best rows in standings order
    uint32_t n_playoff;
    Id playoff[STANDINGS_PAGE];
};

inline bool standing_before(const StandingRow& x, const StandingRow& y) {
    if (x.rating != y.rating) return x.rating > y.rating;
    if (x.defeated != y.defeated) return x.defeated > y.defeated;
    if (x.wins != y.wins) return x.wins > y.wins;
    return id_cmp(x.fighter_id, y.fighter_id) < 0;
}

inline bool standing_row(const State& s, const Fighter& f, uint32_t season, uint64_t t, StandingRow& row) {
    const SeasonSlot& sl = f.seasons[season % 2];
    if (season == 0 || sl.season != season || !sl.has_stats) return false;
    row.fighter_id = f.fighter_id;
    row.rating = sl.has_rating ? sl.rating : uint16_t(RATING_INITIAL);
    row.defeated = sl.defeated;
    row.wins = sl.wins;
    row.fights = sl.fights;
    row.qualified = (sl.fights >= 12 && sl.opponents >= 4 && sl.defeated >= 3 && sl.final_epoch_fights >= 3 &&
                     f.placement >= PLACEMENT_FIGHTS && f.suspended_epoch != detail::epoch_of(s, t))
                        ? 1
                        : 0;
    return true;
}

inline void query_standings(const State& s, uint32_t season, uint64_t t, Standings& out) {
    out = Standings{};
    out.season = season;
    int64_t first_next = s.m.season_start_epoch + int64_t(season) * s.m.season_epochs;
    int64_t closes = s.m.genesis_tick + (first_next - s.m.genesis_epoch) * s.m.ticks_per_epoch + s.m.season_closeout_ticks;
    out.final = int64_t(t) >= closes ? 1 : 0;
    // Page: repeated selection of the next row in standings order.
    bool have_prev = false;
    StandingRow prev{};
    for (uint32_t pass = 0; pass < STANDINGS_PAGE; ++pass) {
        bool found = false;
        StandingRow best{};
        for (uint32_t i = 0; i < CAP_FIGHTERS; ++i) {
            if (i >= s.n_fighters) break;
            StandingRow row;
            if (!standing_row(s, s.fighters[i], season, t, row)) continue;
            if (pass == 0) ++out.n_rows;
            if (have_prev && !standing_before(prev, row)) continue;
            if (!found || standing_before(row, best)) {
                best = row;
                found = true;
            }
        }
        if (!found) break;
        out.page[out.n_page++] = best;
        prev = best;
        have_prev = true;
    }
    // Champion: the unique qualified row with the best (rating, defeated, wins).
    bool any = false;
    StandingRow top{};
    for (uint32_t i = 0; i < CAP_FIGHTERS; ++i) {
        if (i >= s.n_fighters) break;
        StandingRow row;
        if (!standing_row(s, s.fighters[i], season, t, row) || !row.qualified) continue;
        if (!any || standing_before(row, top)) top = row;
        any = true;
    }
    if (!any) return;
    uint32_t tied = 0;
    for (uint32_t i = 0; i < CAP_FIGHTERS; ++i) {
        if (i >= s.n_fighters) break;
        StandingRow row;
        if (!standing_row(s, s.fighters[i], season, t, row) || !row.qualified) continue;
        if (row.rating == top.rating && row.defeated == top.defeated && row.wins == top.wins) {
            if (out.n_playoff < STANDINGS_PAGE) out.playoff[out.n_playoff++] = row.fighter_id;
            ++tied;
        }
    }
    if (tied == 1) {
        out.status = 1;
        out.champion = top.fighter_id;
        out.n_playoff = 0;
    } else {
        out.status = 2;
    }
}

}  // namespace qdojo_contract

#endif  // QDOJO_COMBAT_CONTRACT_H
