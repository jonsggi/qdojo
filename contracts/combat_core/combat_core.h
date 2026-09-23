// qdojo combat-v1 (candidate 1) pure core.
//
// Independent C++ implementation of docs/combat.md sections 2-7 and the
// canonical state/plan encodings of docs/protocol.md section 2. Written from
// the spec for a later port into a Qubic smart contract, so the core follows
// contract restrictions:
//   - header-only, no heap allocation, no exceptions, no STL containers
//   - no floating point, no RNG, no clock
//   - fixed-width integer types only; every loop has a compile-time bound
//   - all ruleset constants compiled in (contracts cannot parse JSON);
//     test_combat_core.cpp asserts they equal docs/combat-v1.json and that
//     the file hashes to RULESET_DIGEST
//   - invalid input is rejected with an error code, never repaired/clamped
//
// Reason codes (SideTrace::reasons) are a descriptive bitmask with STABLE bit
// numbers. They are never used as hidden logic. Each bit is from the point
// of view of the fighter whose SideTrace carries it:
//   bit  0 HIT                 own computed damage > 0
//   bit  1 BLOCKED             own effective JAB/KICK met effective BLOCK
//   bit  2 EVADED              own effective JAB/THROW met effective DUCK
//   bit  3 THROW_INTERRUPTED   own effective THROW met effective JAB/KICK
//   bit  4 THROW_CLASH         both effective THROW
//   bit  5 INSUFFICIENT_STAMINA intended action unaffordable -> EXHAUSTED
//   bit  6 RECOVERY_PUNISHED   own effective RECOVER took computed damage > 0
//   bit  7 GUARD_STRAIN        own effective BLOCK met effective KICK
//                              (set even when the deducted strain is 0)
//   bit  8 OPENING_EARNED      new opening == 1
//   bit  9 OPENING_USED        pre-beat opening added its bonus
//   bit 10 OPENING_EXPIRED     pre-beat opening was 1 and was not used
//   bit 11 POWER_USED          designated power slot added its bonus
//   bit 12 POWER_WASTED        designated power slot added no bonus
//   bit 13 KO                  this fighter reached 0 HP, the other did not
//   bit 14 DOUBLE_KO           both fighters reached 0 HP on this beat
#ifndef QDOJO_COMBAT_CORE_H
#define QDOJO_COMBAT_CORE_H

#include <stdint.h>

namespace qdojo_combat {

// ---------------------------------------------------------------- constants
// Mirrors docs/combat-v1.json (semantic_version "combat-v1-candidate-1").
static constexpr uint8_t ROUNDS = 3;
static constexpr uint8_t BEATS_PER_ROUND = 6;
static constexpr uint16_t INITIAL_HP = 100;
static constexpr uint16_t INITIAL_STAMINA = 60;
static constexpr uint8_t INITIAL_OPENING = 0;
static constexpr uint8_t INITIAL_GUARD_STREAK = 0;
static constexpr uint8_t INITIAL_POWER_AVAILABLE = 1;
static constexpr uint16_t LIMIT_HP = 100;
static constexpr uint16_t LIMIT_STAMINA = 60;
static constexpr uint8_t LIMIT_GUARD_STREAK = 3;
static constexpr uint16_t BLOCK_STREAK_COST = 3;
static constexpr uint16_t BLOCK_STRAIN = 6;
static constexpr uint16_t ORDINARY_RECOVERY = 2;
static constexpr uint16_t RECOVER_UNHIT = 18;
static constexpr uint16_t RECOVER_HIT = 6;
static constexpr uint16_t EXHAUSTED_RECOVERY = 6;
static constexpr uint16_t BREAK_RECOVERY = 10;
static constexpr uint16_t OPENING_DAMAGE = 4;
static constexpr uint16_t POWER_DAMAGE = 4;
static constexpr uint16_t POWER_COST = 4;

enum Action : uint8_t {
    JAB = 0, KICK = 1, BLOCK = 2, DUCK = 3, THROW = 4, RECOVER = 5,
    EXHAUSTED = 6,  // internal only; never legal in a submitted plan
};
static constexpr uint8_t ACTION_COUNT = 7;
static constexpr uint8_t SUBMITTED_ACTION_COUNT = 6;  // ids 0..5

static constexpr uint16_t BASE_COSTS[ACTION_COUNT] = {6, 12, 4, 4, 9, 0, 0};

// DAMAGE[attacker][defender], before opening/power bonuses.
static constexpr uint16_t DAMAGE[ACTION_COUNT][ACTION_COUNT] = {
    {8, 8, 0, 0, 8, 12, 12},
    {14, 14, 0, 18, 14, 18, 18},
    {0, 0, 0, 0, 0, 0, 0},
    {0, 0, 0, 0, 0, 0, 0},
    {0, 0, 14, 0, 0, 18, 18},
    {0, 0, 0, 0, 0, 0, 0},
    {0, 0, 0, 0, 0, 0, 0},
};

// SHA256("qdojo/combat/rules/v1\0" || canonical JSON of docs/combat-v1.json)
static constexpr uint8_t RULESET_DIGEST[32] = {
    0x12, 0x08, 0x5c, 0x86, 0xa6, 0x1f, 0xfd, 0x10, 0x64, 0x30, 0xb6, 0x69, 0x0a, 0xcb, 0xd5, 0x22,
    0xc5, 0xa9, 0x4f, 0x90, 0xed, 0x80, 0x24, 0x58, 0x58, 0x17, 0xf4, 0x93, 0x9f, 0xe4, 0x84, 0x2c,
};

static constexpr uint8_t NO_POWER_SLOT = 255;  // wire value for power_slot -1
static constexpr uint32_t STATE_BYTES = 8;
static constexpr uint32_t PLAN_BYTES = 7;

enum Reason : uint32_t {
    R_HIT = 1u << 0,
    R_BLOCKED = 1u << 1,
    R_EVADED = 1u << 2,
    R_THROW_INTERRUPTED = 1u << 3,
    R_THROW_CLASH = 1u << 4,
    R_INSUFFICIENT_STAMINA = 1u << 5,
    R_RECOVERY_PUNISHED = 1u << 6,
    R_GUARD_STRAIN = 1u << 7,
    R_OPENING_EARNED = 1u << 8,
    R_OPENING_USED = 1u << 9,
    R_OPENING_EXPIRED = 1u << 10,
    R_POWER_USED = 1u << 11,
    R_POWER_WASTED = 1u << 12,
    R_KO = 1u << 13,
    R_DOUBLE_KO = 1u << 14,
};

enum Outcome : uint8_t { OUTCOME_NONE = 0, OUTCOME_KO = 1, OUTCOME_DOUBLE_KO = 2, OUTCOME_HP = 3, OUTCOME_HP_TIE = 4 };
enum Winner : uint8_t { WINNER_NONE = 0, WINNER_A = 1, WINNER_B = 2 };

enum Error : uint8_t {
    OK = 0,
    BAD_STATE = 1,        // impossible fighter state or round index
    TERMINAL = 2,         // fight already over
    BAD_PLAN_A = 3,
    BAD_PLAN_B = 4,
    BAD_ACTION = 5,       // resolve_beat called with an illegal intent/power flag
    BAD_ENCODING = 6,     // decode of noncanonical bytes
};

// -------------------------------------------------------------------- types
struct Fighter {
    uint16_t hp;
    uint16_t stamina;
    uint8_t opening;
    uint8_t guard_streak;
    uint8_t power_available;
};

struct Plan {
    uint8_t actions[BEATS_PER_ROUND];
    uint8_t power_slot;  // 0..5 or NO_POWER_SLOT
};

struct FightState {
    Fighter a;
    Fighter b;
    uint8_t round_index;  // 0..2 while live
    uint8_t outcome;      // Outcome; OUTCOME_NONE while live
    uint8_t winner;       // Winner
};

struct SideTrace {
    Fighter before;
    Fighter after;
    uint8_t intended;
    uint8_t effective;
    uint8_t power;          // 1 when this beat is the designated power slot
    uint8_t cost;           // full cost of the intended action (incl. power)
    uint8_t cost_paid;      // stamina actually paid (0 when EXHAUSTED)
    uint8_t base;           // matrix damage dealt by own effective action
    uint8_t opening_bonus;  // 0 or OPENING_DAMAGE
    uint8_t power_bonus;    // 0 or POWER_DAMAGE
    uint8_t dealt;          // computed damage dealt to the opponent
    uint8_t lost;           // actual HP lost by this fighter
    uint8_t strain;         // block strain actually deducted from this fighter
    uint8_t recovered;      // stamina actually gained after the cap
    uint8_t new_opening;
    uint32_t reasons;       // Reason bitmask
};

struct BeatTrace {
    SideTrace a;
    SideTrace b;
    uint8_t terminal;  // 1 when either HP reached 0 on this beat
};

struct RoundResult {
    FightState end;          // new round-start state (after break recovery) or terminal state
    uint8_t executed;        // beats executed, 1..6
    uint8_t break_recovery;  // 1 when +BREAK_RECOVERY was applied
    BeatTrace beats[BEATS_PER_ROUND];
};

// ------------------------------------------------------------------ helpers
inline uint16_t min_u16(uint16_t x, uint16_t y) { return x < y ? x : y; }

inline bool is_attack(uint8_t a) { return a == JAB || a == KICK || a == THROW; }

inline bool valid_fighter(const Fighter& f) {
    return f.hp <= LIMIT_HP && f.stamina <= LIMIT_STAMINA && f.opening <= 1 &&
           f.guard_streak <= LIMIT_GUARD_STREAK && f.power_available <= 1;
}

inline Fighter initial_fighter() {
    Fighter f;
    f.hp = INITIAL_HP;
    f.stamina = INITIAL_STAMINA;
    f.opening = INITIAL_OPENING;
    f.guard_streak = INITIAL_GUARD_STREAK;
    f.power_available = INITIAL_POWER_AVAILABLE;
    return f;
}

inline FightState new_fight() {
    FightState s;
    s.a = initial_fighter();
    s.b = initial_fighter();
    s.round_index = 0;
    s.outcome = OUTCOME_NONE;
    s.winner = WINNER_NONE;
    return s;
}

// Full cost of an intended action from the pre-beat guard streak (step 1).
inline uint16_t action_cost(uint8_t intended, uint8_t guard_streak, bool power) {
    uint16_t c = BASE_COSTS[intended];
    if (intended == BLOCK) c = static_cast<uint16_t>(c + BLOCK_STREAK_COST * guard_streak);
    if (power) c = static_cast<uint16_t>(c + POWER_COST);
    return c;
}

// Plan validation against the round-start fighter (combat.md section 3).
inline bool validate_plan(const Plan& p, const Fighter& start) {
    for (uint8_t i = 0; i < BEATS_PER_ROUND; ++i)
        if (p.actions[i] >= SUBMITTED_ACTION_COUNT) return false;
    if (p.power_slot == NO_POWER_SLOT) return true;
    if (p.power_slot >= BEATS_PER_ROUND) return false;
    if (!is_attack(p.actions[p.power_slot])) return false;
    return start.power_available == 1;
}

// ------------------------------------------------------------- beat engine
namespace detail {

struct Half {  // first-pass result for one side, from snapshots only
    uint16_t cost;
    uint16_t paid;
    uint8_t effective;
    bool power;
};

inline Half choose(const Fighter& f, uint8_t intended, bool power) {
    Half h;
    h.power = power;
    h.cost = action_cost(intended, f.guard_streak, power);
    if (f.stamina >= h.cost) {
        h.effective = intended;
        h.paid = h.cost;
    } else {
        h.effective = EXHAUSTED;
        h.paid = 0;
    }
    return h;
}

inline void finish(const Fighter& before, uint8_t intended, const Half& me, const Half& them,
                   uint16_t my_base, uint16_t my_dealt, uint16_t incoming, SideTrace& t) {
    Fighter f = before;
    t.before = before;
    t.intended = intended;
    t.effective = me.effective;
    t.power = me.power ? 1 : 0;
    t.cost = static_cast<uint8_t>(me.cost);
    t.cost_paid = static_cast<uint8_t>(me.paid);
    t.base = static_cast<uint8_t>(my_base);
    t.opening_bonus = 0;
    t.power_bonus = 0;
    uint32_t r = 0;

    // step 2: power is spent on its designated slot whatever happens next
    if (me.power) f.power_available = 0;
    // step 3: pay
    f.stamina = static_cast<uint16_t>(f.stamina - me.paid);
    if (me.effective == EXHAUSTED) r |= R_INSUFFICIENT_STAMINA;
    // step 5 bookkeeping (dealt was computed by the caller)
    if (my_base > 0) {
        if (before.opening) t.opening_bonus = static_cast<uint8_t>(OPENING_DAMAGE);
        if (me.power && me.effective == intended) t.power_bonus = static_cast<uint8_t>(POWER_DAMAGE);
    }
    t.dealt = static_cast<uint8_t>(my_dealt);
    // step 6: damage from the snapshot-computed incoming value, clamped at 0 HP
    uint16_t lost = min_u16(f.hp, incoming);
    f.hp = static_cast<uint16_t>(f.hp - lost);
    t.lost = static_cast<uint8_t>(lost);
    // step 7: block strain
    uint16_t strain = 0;
    if (me.effective == BLOCK && them.effective == KICK) {
        strain = min_u16(f.stamina, BLOCK_STRAIN);
        f.stamina = static_cast<uint16_t>(f.stamina - strain);
        r |= R_GUARD_STRAIN;
    }
    t.strain = static_cast<uint8_t>(strain);
    // step 8: recovery (alternatives, capped)
    uint16_t gain;
    if (me.effective == RECOVER) gain = incoming == 0 ? RECOVER_UNHIT : RECOVER_HIT;
    else if (me.effective == EXHAUSTED) gain = EXHAUSTED_RECOVERY;
    else gain = ORDINARY_RECOVERY;
    uint16_t s = min_u16(static_cast<uint16_t>(f.stamina + gain), LIMIT_STAMINA);
    t.recovered = static_cast<uint8_t>(s - f.stamina);
    f.stamina = s;
    // step 9: replace opening
    bool duck_earn = me.effective == DUCK && (them.effective == JAB || them.effective == THROW);
    bool jab_earn = me.effective == JAB && my_dealt > 0 && incoming == 0;
    f.opening = (duck_earn || jab_earn) ? 1 : 0;
    t.new_opening = f.opening;
    // step 10: replace guard streak
    if (me.effective == BLOCK) {
        uint8_t g = static_cast<uint8_t>(before.guard_streak + 1);
        f.guard_streak = g > LIMIT_GUARD_STREAK ? LIMIT_GUARD_STREAK : g;
    } else {
        f.guard_streak = 0;
    }
    t.after = f;

    // descriptive reasons
    if (my_dealt > 0) r |= R_HIT;
    if ((me.effective == JAB || me.effective == KICK) && them.effective == BLOCK) r |= R_BLOCKED;
    if ((me.effective == JAB || me.effective == THROW) && them.effective == DUCK) r |= R_EVADED;
    if (me.effective == THROW && (them.effective == JAB || them.effective == KICK)) r |= R_THROW_INTERRUPTED;
    if (me.effective == THROW && them.effective == THROW) r |= R_THROW_CLASH;
    if (me.effective == RECOVER && incoming > 0) r |= R_RECOVERY_PUNISHED;
    if (f.opening) r |= R_OPENING_EARNED;
    if (before.opening) r |= t.opening_bonus ? R_OPENING_USED : R_OPENING_EXPIRED;
    if (me.power) r |= t.power_bonus ? R_POWER_USED : R_POWER_WASTED;
    t.reasons = r;
}

}  // namespace detail

// Resolves one beat from BOTH pre-beat snapshots (combat.md section 6).
// power_x is true when this beat is that fighter's designated power slot.
inline Error resolve_beat(const Fighter& a, const Fighter& b, uint8_t intent_a, uint8_t intent_b,
                          bool power_a, bool power_b, BeatTrace& out) {
    if (!valid_fighter(a) || !valid_fighter(b)) return BAD_STATE;
    if (intent_a >= SUBMITTED_ACTION_COUNT || intent_b >= SUBMITTED_ACTION_COUNT) return BAD_ACTION;
    if (power_a && (!is_attack(intent_a) || a.power_available != 1)) return BAD_ACTION;
    if (power_b && (!is_attack(intent_b) || b.power_available != 1)) return BAD_ACTION;

    // steps 1-3 from snapshots
    detail::Half ha = detail::choose(a, intent_a, power_a);
    detail::Half hb = detail::choose(b, intent_b, power_b);
    // step 4: both base damages from effective actions
    uint16_t base_a = DAMAGE[ha.effective][hb.effective];
    uint16_t base_b = DAMAGE[hb.effective][ha.effective];
    // step 5: bonuses only on positive base
    uint16_t dealt_a = 0, dealt_b = 0;
    if (base_a > 0) {
        dealt_a = base_a;
        if (a.opening) dealt_a = static_cast<uint16_t>(dealt_a + OPENING_DAMAGE);
        if (power_a && ha.effective == intent_a) dealt_a = static_cast<uint16_t>(dealt_a + POWER_DAMAGE);
    }
    if (base_b > 0) {
        dealt_b = base_b;
        if (b.opening) dealt_b = static_cast<uint16_t>(dealt_b + OPENING_DAMAGE);
        if (power_b && hb.effective == intent_b) dealt_b = static_cast<uint16_t>(dealt_b + POWER_DAMAGE);
    }
    // steps 6-10, each side reading only snapshots and the paired values
    detail::finish(a, intent_a, ha, hb, base_a, dealt_a, dealt_b, out.a);
    detail::finish(b, intent_b, hb, ha, base_b, dealt_b, dealt_a, out.b);
    // step 11
    bool ko_a = out.a.after.hp == 0, ko_b = out.b.after.hp == 0;
    out.terminal = (ko_a || ko_b) ? 1 : 0;
    if (ko_a && ko_b) {
        out.a.reasons |= R_DOUBLE_KO;
        out.b.reasons |= R_DOUBLE_KO;
    } else if (ko_a) {
        out.a.reasons |= R_KO;
    } else if (ko_b) {
        out.b.reasons |= R_KO;
    }
    return OK;
}

// ------------------------------------------------------------ round engine
inline void set_outcome_from_hp(FightState& s, bool final_round) {
    if (s.a.hp == 0 && s.b.hp == 0) {
        s.outcome = OUTCOME_DOUBLE_KO;
        s.winner = WINNER_NONE;
    } else if (s.a.hp == 0) {
        s.outcome = OUTCOME_KO;
        s.winner = WINNER_B;
    } else if (s.b.hp == 0) {
        s.outcome = OUTCOME_KO;
        s.winner = WINNER_A;
    } else if (final_round) {
        if (s.a.hp == s.b.hp) {
            s.outcome = OUTCOME_HP_TIE;
            s.winner = WINNER_NONE;
        } else {
            s.outcome = OUTCOME_HP;
            s.winner = s.a.hp > s.b.hp ? WINNER_A : WINNER_B;
        }
    }
}

// Inter-round recovery: +BREAK_RECOVERY stamina (capped) for both fighters
// and advance the round index. HP, opening, guard_streak and power carry.
inline void apply_break_recovery(FightState& s) {
    s.a.stamina = min_u16(static_cast<uint16_t>(s.a.stamina + BREAK_RECOVERY), LIMIT_STAMINA);
    s.b.stamina = min_u16(static_cast<uint16_t>(s.b.stamina + BREAK_RECOVERY), LIMIT_STAMINA);
    s.round_index = static_cast<uint8_t>(s.round_index + 1);
}

// Resolves one round (combat.md section 7). Both plans are validated in full
// before any beat runs. On error, out is unspecified and start is untouched.
inline Error resolve_round(const FightState& start, const Plan& plan_a, const Plan& plan_b, RoundResult& out) {
    if (!valid_fighter(start.a) || !valid_fighter(start.b) || start.round_index >= ROUNDS) return BAD_STATE;
    if (start.outcome != OUTCOME_NONE || start.a.hp == 0 || start.b.hp == 0) return TERMINAL;
    if (!validate_plan(plan_a, start.a)) return BAD_PLAN_A;
    if (!validate_plan(plan_b, start.b)) return BAD_PLAN_B;

    FightState s = start;
    out.executed = 0;
    out.break_recovery = 0;
    for (uint8_t beat = 0; beat < BEATS_PER_ROUND; ++beat) {
        BeatTrace& t = out.beats[beat];
        Error e = resolve_beat(s.a, s.b, plan_a.actions[beat], plan_b.actions[beat],
                               plan_a.power_slot == beat, plan_b.power_slot == beat, t);
        if (e != OK) return e;  // unreachable after validation
        s.a = t.a.after;
        s.b = t.b.after;
        out.executed = static_cast<uint8_t>(beat + 1);
        if (t.terminal) {
            set_outcome_from_hp(s, false);
            out.end = s;
            return OK;
        }
    }
    if (s.round_index == ROUNDS - 1) {
        set_outcome_from_hp(s, true);
        out.end = s;
        return OK;
    }
    apply_break_recovery(s);
    out.break_recovery = 1;
    out.end = s;
    return OK;
}

// ---------------------------------------------------------------- encoding
// Fighter state: hp u16 LE, stamina u16 LE, opening u8, guard_streak u8,
// power_available u8, reserved u8 = 0.
inline void encode_state(const Fighter& f, uint8_t out[STATE_BYTES]) {
    out[0] = static_cast<uint8_t>(f.hp & 0xff);
    out[1] = static_cast<uint8_t>(f.hp >> 8);
    out[2] = static_cast<uint8_t>(f.stamina & 0xff);
    out[3] = static_cast<uint8_t>(f.stamina >> 8);
    out[4] = f.opening;
    out[5] = f.guard_streak;
    out[6] = f.power_available;
    out[7] = 0;
}

inline Error decode_state(const uint8_t in[STATE_BYTES], Fighter& f) {
    f.hp = static_cast<uint16_t>(in[0] | (in[1] << 8));
    f.stamina = static_cast<uint16_t>(in[2] | (in[3] << 8));
    f.opening = in[4];
    f.guard_streak = in[5];
    f.power_available = in[6];
    if (in[7] != 0 || !valid_fighter(f)) return BAD_ENCODING;
    return OK;
}

// Plan: six action ids in beat order, then power_slot (0..5 or 255).
inline void encode_plan(const Plan& p, uint8_t out[PLAN_BYTES]) {
    for (uint8_t i = 0; i < BEATS_PER_ROUND; ++i) out[i] = p.actions[i];
    out[6] = p.power_slot;
}

// Decoding is purely structural; legality against a state is validate_plan.
inline void decode_plan(const uint8_t in[PLAN_BYTES], Plan& p) {
    for (uint8_t i = 0; i < BEATS_PER_ROUND; ++i) p.actions[i] = in[i];
    p.power_slot = in[6];
}

}  // namespace qdojo_combat

#endif  // QDOJO_COMBAT_CORE_H
