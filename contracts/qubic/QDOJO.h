// QDOJO: the qdojo combat contract (combat-v1) in the Qubic Core contract dialect.
//
// This is a line-by-line transliteration of the parity-tested bounded port
// contracts/combat_contract/combat_contract.h (itself a port of the Python
// reference packages/qdojo/src/qdojo/combat/contract.py), including the pure
// engine (contracts/combat_core/combat_core.h) and SHA-256 with the combat-v1
// digests (contracts/combat_core/sha256.h). Semantics are meant to be
// identical: the same events, bodies, order, result codes and ledger moves.
// contracts/qubic/test_qdojo_core.cpp replays the reference journals through
// this file inside Core's GoogleTest harness and compares the event digest.
//
// How the dialect is met:
//   - no #include, no pointers, no [ ], no / or %, no string or char literals,
//     no floating point, no local variables, no globals other than constexpr
//     constants prefixed QDOJO;
//   - every table is a QPI Array<T, 2^N>; records are changed by copy, edit,
//     set (Array::get returns a const reference);
//   - helpers are static member functions (as in Pulse.h / QThirtyFour.h)
//     that take the StateData and a scratch struct Ctx by reference. Ctx holds
//     every helper's temporaries. The helper call graph has no recursion, so
//     one Ctx per entry point is enough; it lives in the entry point's locals;
//   - the only QPI calls are qpi.tick(), qpi.invocator(),
//     qpi.invocationReward() and qpi.transfer() (entry points only), and the
//     AssetOwnershipIterator (OwnerOf);
//   - SHA-256 is implemented here: QPI offers only K12 and the protocol
//     requires SHA-256.
//
// Deviations forced by the chain, not by the reference (see README.md):
//   - the manifest is compiled in (QDOJO_DEFAULT_*); a test may preload
//     StateData::m and set manifestLoaded before INITIALIZE;
//   - a fighter's registry asset is (issuer = fighter_id, name "QDOJOF"),
//     because AdminRegisterAsset carries no issuance (protocol gap);
//   - a refund payback or a withdrawal is a qpi.transfer made by Dispatch
//     itself; a negative return is the "transfer failed" path.

using namespace QPI;

// ---- capacities (combat_contract.h; all Array capacities are powers of two) ----
constexpr uint32 QDOJO_CAP_FIGHTERS = 1024;
constexpr uint32 QDOJO_CAP_ACCOUNTS = 2048;
constexpr uint32 QDOJO_CAP_ASSETS = 2048;
constexpr uint32 QDOJO_CAP_OPEN_OFFERS = 64;
constexpr uint32 QDOJO_CAP_OFFER_SLOTS = 128;
constexpr uint32 QDOJO_CAP_FIGHTS = 16;
constexpr uint32 QDOJO_CAP_FIGHT_SLOTS = 32;
constexpr uint32 QDOJO_CAP_CONTEST_SLOTS = 32;
constexpr uint32 QDOJO_CAP_CUPS = 4;
constexpr uint32 QDOJO_CAP_CUP_SLOTS = 8;
constexpr uint32 QDOJO_CAP_CUP_ENTRANTS = 16;
constexpr uint32 QDOJO_CAP_PAIRINGS = 16;
constexpr uint32 QDOJO_CAP_EVENTS = 2048;
constexpr uint32 QDOJO_CAP_PAIRS = 4096;
constexpr uint32 QDOJO_CAP_TIMING = 4;
constexpr uint32 QDOJO_CAP_FEES = 4;
constexpr uint32 QDOJO_CAP_TIERS = 8;
constexpr uint32 QDOJO_EVENT_BODY_MAX = 112;      // largest canonical body is REVEALED, 98 bytes
constexpr uint32 QDOJO_EVENT_BODY_CAP = 128;      // Array capacity for the retained body
constexpr uint32 QDOJO_BODY_CAP = 256;            // scratch body under construction
constexpr uint32 QDOJO_STANDINGS_PAGE = 16;
constexpr uint32 QDOJO_EVENTS_PAGE = 64;

// ---- protocol constants ----
constexpr uint32 QDOJO_FRAME_LEN = 512;
constexpr uint32 QDOJO_FRAME_HEADER = 24;
constexpr uint32 QDOJO_MAX_BODY = 487;            // FRAME_LEN - FRAME_HEADER - 1
constexpr uint8 QDOJO_FRAME_SENTINEL = 0xA5;
constexpr sint64 QDOJO_MAX_STAKE = 1000000000000LL;
constexpr sint64 QDOJO_I64_MAX = 0x7fffffffffffffffLL;
constexpr sint64 QDOJO_BPS = 10000;

// rating.py
constexpr sint64 QDOJO_RATING_INITIAL = 1000;
constexpr sint64 QDOJO_RATING_CEILING = 3000;
constexpr uint32 QDOJO_PLACEMENT_FIGHTS = 10;
constexpr sint64 QDOJO_SCORE_WIN = 2000;
constexpr sint64 QDOJO_SCORE_DRAW = 1000;
constexpr sint64 QDOJO_SCORE_LOSS = 0;

// matchmaking.py
constexpr uint64 QDOJO_BASE_WINDOW = 100;
constexpr uint64 QDOJO_WIDEN_STEP = 50;
constexpr uint64 QDOJO_WIDEN_TICKS = 40;
constexpr uint16 QDOJO_MAX_GAP_LO = 100;
constexpr uint16 QDOJO_MAX_GAP_HI = 200;
constexpr uint32 QDOJO_PASS_SNAPSHOT = 64;
constexpr uint32 QDOJO_PASS_MATCHES = 4;
constexpr uint32 QDOJO_PAIR_STARTS_PER_EPOCH = 2;
constexpr uint64 QDOJO_PAIR_REMATCH_TICKS = 120;

// Result codes (docs/protocol.md section 6). HOST_ERROR is not a protocol code.
constexpr uint8 QDOJO_OK = 0;
constexpr uint8 QDOJO_DUPLICATE = 1;
constexpr uint8 QDOJO_BAD_FRAME = 2;
constexpr uint8 QDOJO_BAD_OPCODE = 3;
constexpr uint8 QDOJO_BAD_BODY = 4;
constexpr uint8 QDOJO_BAD_AMOUNT = 5;
constexpr uint8 QDOJO_UNKNOWN_FIGHTER = 6;
constexpr uint8 QDOJO_NOT_OWNER = 7;
constexpr uint8 QDOJO_NOT_OPERATOR = 8;
constexpr uint8 QDOJO_STALE_AUTH = 9;
constexpr uint8 QDOJO_FIGHTER_BUSY = 10;
constexpr uint8 QDOJO_COOLDOWN = 11;
constexpr uint8 QDOJO_FULL = 12;
constexpr uint8 QDOJO_NONCE_CONFLICT = 13;
constexpr uint8 QDOJO_STALE = 14;
constexpr uint8 QDOJO_NOT_FOUND = 15;
constexpr uint8 QDOJO_EXPIRED = 16;
constexpr uint8 QDOJO_ALREADY_MATCHED = 17;
constexpr uint8 QDOJO_INCOMPATIBLE = 18;
constexpr uint8 QDOJO_RULESET_RETIRED = 19;
constexpr uint8 QDOJO_WRONG_PHASE = 20;
constexpr uint8 QDOJO_LATE = 21;
constexpr uint8 QDOJO_ALREADY_COMMITTED = 22;
constexpr uint8 QDOJO_BAD_STATE = 23;
constexpr uint8 QDOJO_BAD_COMMITMENT = 24;
constexpr uint8 QDOJO_BAD_PLAN = 25;
constexpr uint8 QDOJO_ALREADY_REVEALED = 26;
constexpr uint8 QDOJO_TERMINAL = 27;
constexpr uint8 QDOJO_SERVICE_VOID = 28;
constexpr uint8 QDOJO_TRANSFER_FAILED = 29;
constexpr uint8 QDOJO_HOST_ERROR = 255;

// Opcodes
constexpr uint16 QDOJO_OP_REGISTER_FIGHTER = 1;
constexpr uint16 QDOJO_OP_SET_OPERATOR = 2;
constexpr uint16 QDOJO_OP_QUEUE_ENTER = 3;
constexpr uint16 QDOJO_OP_QUEUE_CANCEL = 4;
constexpr uint16 QDOJO_OP_DUEL_OFFER = 5;
constexpr uint16 QDOJO_OP_DUEL_ACCEPT = 6;
constexpr uint16 QDOJO_OP_COMMIT = 7;
constexpr uint16 QDOJO_OP_REVEAL = 8;
constexpr uint16 QDOJO_OP_ADVANCE = 9;
constexpr uint16 QDOJO_OP_WITHDRAW = 10;
constexpr uint16 QDOJO_OP_CUP_REGISTER = 11;
constexpr uint16 QDOJO_OP_CUP_WITHDRAW = 12;
constexpr uint16 QDOJO_OP_CUP_CHECK_IN = 13;
constexpr uint16 QDOJO_OP_DUEL_CANCEL = 14;
constexpr uint16 QDOJO_OP_ADMIN_REGISTER_ASSET = 100;
constexpr uint16 QDOJO_OP_ADMIN_CREATE_CUP = 101;
constexpr uint16 QDOJO_OP_ADMIN_RETIRE_RULESET = 102;

// Event types (contract.py EVENT_TYPES)
constexpr uint16 QDOJO_EV_SERVICE_GAP = 1;
constexpr uint16 QDOJO_EV_FIGHTER_REGISTERED = 2;
constexpr uint16 QDOJO_EV_OPERATOR_SET = 3;
constexpr uint16 QDOJO_EV_OFFER_OPEN = 4;
constexpr uint16 QDOJO_EV_OFFER_CLOSED = 5;
constexpr uint16 QDOJO_EV_MATCHED = 6;
constexpr uint16 QDOJO_EV_DUEL_ACCEPTED = 7;
constexpr uint16 QDOJO_EV_FIGHT_CREATED = 8;
constexpr uint16 QDOJO_EV_COMMITTED = 9;
constexpr uint16 QDOJO_EV_REVEALED = 10;
constexpr uint16 QDOJO_EV_ROUND_RESOLVED = 11;
constexpr uint16 QDOJO_EV_FIGHT_ENDED = 12;
constexpr uint16 QDOJO_EV_CONTEST_SETTLED = 13;
constexpr uint16 QDOJO_EV_RATING = 14;
constexpr uint16 QDOJO_EV_FAULT = 15;
constexpr uint16 QDOJO_EV_WITHDRAWN = 16;
constexpr uint16 QDOJO_EV_WITHDRAW_FAILED = 17;
constexpr uint16 QDOJO_EV_CUP_CREATED = 18;
constexpr uint16 QDOJO_EV_CUP_ENTRY = 19;
constexpr uint16 QDOJO_EV_CUP_BRACKET = 20;
constexpr uint16 QDOJO_EV_CUP_LEVEL = 21;
constexpr uint16 QDOJO_EV_CUP_PAIRING = 22;
constexpr uint16 QDOJO_EV_CUP_FINISHED = 23;
constexpr uint16 QDOJO_EV_ASSET_REGISTERED = 24;
constexpr uint16 QDOJO_EV_RULESET_RETIRED = 25;
constexpr uint16 QDOJO_EV_REFUND_CREDIT = 26;
constexpr uint16 QDOJO_EV_CUP_WITHDRAWN = 27;
constexpr uint16 QDOJO_EV_CUP_CHECKED_IN = 28;
constexpr uint16 QDOJO_EV_CUP_REPLAY_SCHEDULED = 29;

// Enumerations
constexpr uint8 QDOJO_L_IDLE = 0;
constexpr uint8 QDOJO_L_QUEUED = 1;
constexpr uint8 QDOJO_L_DUEL_OFFER = 2;
constexpr uint8 QDOJO_L_CONTEST = 3;
constexpr uint8 QDOJO_L_TOURNAMENT = 4;
constexpr uint8 QDOJO_O_OPEN = 1;
constexpr uint8 QDOJO_O_MATCHED = 2;
constexpr uint8 QDOJO_O_CANCELLED = 3;
constexpr uint8 QDOJO_O_EXPIRED = 4;
constexpr uint8 QDOJO_O_INVALIDATED = 5;
constexpr uint8 QDOJO_K_RANKED = 0;
constexpr uint8 QDOJO_K_DUEL = 1;
constexpr uint8 QDOJO_M_RANKED = 0;
constexpr uint8 QDOJO_M_DUEL = 1;
constexpr uint8 QDOJO_M_CUP = 2;
constexpr uint8 QDOJO_F_SINGLE = 0;
constexpr uint8 QDOJO_F_BO3 = 1;
constexpr uint8 QDOJO_F_BO5 = 2;
constexpr uint8 QDOJO_P_COMMIT = 1;
constexpr uint8 QDOJO_P_REVEAL = 2;
constexpr uint8 QDOJO_P_DONE = 3;
constexpr uint8 QDOJO_R_NONE = 0;
constexpr uint8 QDOJO_R_COMBAT = 1;
constexpr uint8 QDOJO_R_FORFEIT = 2;
constexpr uint8 QDOJO_R_DOUBLE_FAULT = 3;
constexpr uint8 QDOJO_R_VOID = 4;
constexpr uint8 QDOJO_S_NONE = 0;
constexpr uint8 QDOJO_S_A = 1;
constexpr uint8 QDOJO_S_B = 2;
constexpr uint8 QDOJO_C_ACTIVE = 1;
constexpr uint8 QDOJO_C_DONE = 2;
constexpr uint8 QDOJO_CUP_REGISTRATION = 1;
constexpr uint8 QDOJO_CUP_RUNNING = 2;
constexpr uint8 QDOJO_CUP_COMPLETE = 3;
constexpr uint8 QDOJO_CUP_CANCELLED = 4;
constexpr uint8 QDOJO_CUP_ABORTED = 5;
constexpr uint8 QDOJO_PS_SCHEDULED = 1;
constexpr uint8 QDOJO_PS_PLAYING = 2;
constexpr uint8 QDOJO_PS_REPLAY_WAIT = 3;
constexpr uint8 QDOJO_PS_DONE = 4;
constexpr uint8 QDOJO_PS_UNRESOLVED = 5;
constexpr uint8 QDOJO_PS_EMPTY = 6;
constexpr uint8 QDOJO_AB_SERVICE_VOID = 1;
constexpr uint8 QDOJO_AB_EXPIRED = 2;
constexpr uint8 QDOJO_AB_CAPACITY = 3;
constexpr uint8 QDOJO_AB_NO_CHAMPION = 4;

// ---- combat-v1 engine constants (combat_core.h, docs/combat-v1.json) ----
constexpr uint8 QDOJO_ROUNDS = 3;
constexpr uint8 QDOJO_BEATS_PER_ROUND = 6;
constexpr uint16 QDOJO_INITIAL_HP = 100;
constexpr uint16 QDOJO_INITIAL_STAMINA = 60;
constexpr uint16 QDOJO_LIMIT_HP = 100;
constexpr uint16 QDOJO_LIMIT_STAMINA = 60;
constexpr uint8 QDOJO_LIMIT_GUARD_STREAK = 3;
constexpr uint16 QDOJO_BLOCK_STREAK_COST = 3;
constexpr uint16 QDOJO_BLOCK_STRAIN = 6;
constexpr uint16 QDOJO_ORDINARY_RECOVERY = 2;
constexpr uint16 QDOJO_RECOVER_UNHIT = 18;
constexpr uint16 QDOJO_RECOVER_HIT = 6;
constexpr uint16 QDOJO_EXHAUSTED_RECOVERY = 6;
constexpr uint16 QDOJO_BREAK_RECOVERY = 10;
constexpr uint16 QDOJO_OPENING_DAMAGE = 4;
constexpr uint16 QDOJO_POWER_DAMAGE = 4;
constexpr uint16 QDOJO_POWER_COST = 4;
constexpr uint8 QDOJO_JAB = 0;
constexpr uint8 QDOJO_KICK = 1;
constexpr uint8 QDOJO_BLOCK = 2;
constexpr uint8 QDOJO_DUCK = 3;
constexpr uint8 QDOJO_THROW = 4;
constexpr uint8 QDOJO_RECOVER = 5;
constexpr uint8 QDOJO_EXHAUSTED = 6;
constexpr uint8 QDOJO_SUBMITTED_ACTION_COUNT = 6;
constexpr uint8 QDOJO_NO_POWER_SLOT = 255;
constexpr uint8 QDOJO_OUTCOME_NONE = 0;
constexpr uint8 QDOJO_OUTCOME_KO = 1;
constexpr uint8 QDOJO_OUTCOME_DOUBLE_KO = 2;
constexpr uint8 QDOJO_OUTCOME_HP = 3;
constexpr uint8 QDOJO_OUTCOME_HP_TIE = 4;
constexpr uint8 QDOJO_WINNER_NONE = 0;
constexpr uint8 QDOJO_WINNER_A = 1;
constexpr uint8 QDOJO_WINNER_B = 2;
constexpr uint8 QDOJO_E_OK = 0;
constexpr uint8 QDOJO_E_BAD_STATE = 1;
constexpr uint8 QDOJO_E_TERMINAL = 2;
constexpr uint8 QDOJO_E_BAD_PLAN_A = 3;
constexpr uint8 QDOJO_E_BAD_PLAN_B = 4;
constexpr uint8 QDOJO_E_BAD_ACTION = 5;

// Frame magic "QDC1" byte by byte (no char literals).
constexpr uint8 QDOJO_MAGIC_0 = 0x51;
constexpr uint8 QDOJO_MAGIC_1 = 0x44;
constexpr uint8 QDOJO_MAGIC_2 = 0x43;
constexpr uint8 QDOJO_MAGIC_3 = 0x31;

// The registry asset behind a fighter: issuer = fighter_id, this asset name
// ("QDOJOF", little-endian), one indivisible unit. Interim binding until the
// AdminRegisterAsset descriptor carries the issuance (protocol gap).
constexpr uint64 QDOJO_FIGHTER_ASSET_NAME = 0x464f4a4f4451ULL;

// ---- event-body ASCII strings (contract.py _event_body tag 2) ------------------
constexpr uint8 QDOJO_STR_OPEN = 1;  // OPEN
constexpr uint8 QDOJO_STR_MATCHED = 2;  // MATCHED
constexpr uint8 QDOJO_STR_CANCELLED = 3;  // CANCELLED
constexpr uint8 QDOJO_STR_EXPIRED = 4;  // EXPIRED
constexpr uint8 QDOJO_STR_INVALIDATED = 5;  // INVALIDATED
constexpr uint8 QDOJO_STR_COMBAT = 6;  // COMBAT
constexpr uint8 QDOJO_STR_FORFEIT = 7;  // FORFEIT
constexpr uint8 QDOJO_STR_DOUBLE_FAULT = 8;  // DOUBLE_FAULT
constexpr uint8 QDOJO_STR_VOID = 9;  // VOID
constexpr uint8 QDOJO_STR_A = 10;  // A
constexpr uint8 QDOJO_STR_B = 11;  // B
constexpr uint8 QDOJO_STR_DASH = 12;  // -
constexpr uint8 QDOJO_STR_SCHEDULED = 13;  // SCHEDULED
constexpr uint8 QDOJO_STR_PLAYING = 14;  // PLAYING
constexpr uint8 QDOJO_STR_REPLAY_WAIT = 15;  // REPLAY_WAIT
constexpr uint8 QDOJO_STR_DONE = 16;  // DONE
constexpr uint8 QDOJO_STR_UNRESOLVED = 17;  // UNRESOLVED
constexpr uint8 QDOJO_STR_EMPTY = 18;  // EMPTY
constexpr uint8 QDOJO_STR_SERVICE_VOID = 19;  // SERVICE_VOID
constexpr uint8 QDOJO_STR_CAPACITY = 20;  // CAPACITY
constexpr uint8 QDOJO_STR_NO_CHAMPION = 21;  // NO_CHAMPION
constexpr uint8 QDOJO_STR_ABORTED = 22;  // ABORTED
constexpr uint8 QDOJO_STR_COMPLETE = 23;  // COMPLETE

// ---- SHA-256 domain tags (sha256.h), terminal zero byte included, packed LE ----
constexpr uint32 QDOJO_TAG_EVENT_LEN = 22;  // qdojo/combat/event/v1\0
constexpr uint64 QDOJO_TAG_EVENT_0 = 0x6f632f6f6a6f6471ULL;
constexpr uint64 QDOJO_TAG_EVENT_1 = 0x6576652f7461626dULL;
constexpr uint64 QDOJO_TAG_EVENT_2 = 0x00000031762f746eULL;
constexpr uint64 QDOJO_TAG_EVENT_3 = 0x0000000000000000ULL;
constexpr uint32 QDOJO_TAG_CONTEXT_LEN = 24;  // qdojo/combat/context/v1\0
constexpr uint64 QDOJO_TAG_CONTEXT_0 = 0x6f632f6f6a6f6471ULL;
constexpr uint64 QDOJO_TAG_CONTEXT_1 = 0x6e6f632f7461626dULL;
constexpr uint64 QDOJO_TAG_CONTEXT_2 = 0x0031762f74786574ULL;
constexpr uint64 QDOJO_TAG_CONTEXT_3 = 0x0000000000000000ULL;
constexpr uint32 QDOJO_TAG_STATE_LEN = 22;  // qdojo/combat/state/v1\0
constexpr uint64 QDOJO_TAG_STATE_0 = 0x6f632f6f6a6f6471ULL;
constexpr uint64 QDOJO_TAG_STATE_1 = 0x6174732f7461626dULL;
constexpr uint64 QDOJO_TAG_STATE_2 = 0x00000031762f6574ULL;
constexpr uint64 QDOJO_TAG_STATE_3 = 0x0000000000000000ULL;
constexpr uint32 QDOJO_TAG_COMMIT_LEN = 23;  // qdojo/combat/commit/v1\0
constexpr uint64 QDOJO_TAG_COMMIT_0 = 0x6f632f6f6a6f6471ULL;
constexpr uint64 QDOJO_TAG_COMMIT_1 = 0x6d6f632f7461626dULL;
constexpr uint64 QDOJO_TAG_COMMIT_2 = 0x000031762f74696dULL;
constexpr uint64 QDOJO_TAG_COMMIT_3 = 0x0000000000000000ULL;

// EVENT_TAG_GENESIS = SHA256("qdojo/combat/event/genesis/v1\0") as four LE words
constexpr uint64 QDOJO_GENESIS_0 = 0xa59641647518e7deULL;
constexpr uint64 QDOJO_GENESIS_1 = 0x2bf11b1d547c1e7aULL;
constexpr uint64 QDOJO_GENESIS_2 = 0x6c5e7186ccbff0a4ULL;
constexpr uint64 QDOJO_GENESIS_3 = 0x140aaceb1529c72dULL;

// qdojo_combat::RULESET_DIGEST (combat_core.h) as four LE words
constexpr uint64 QDOJO_RULESET_0 = 0x10fd1fa6865c0812ULL;
constexpr uint64 QDOJO_RULESET_1 = 0x22d5cb0a69b63064ULL;
constexpr uint64 QDOJO_RULESET_2 = 0x582480ed904fa9c5ULL;
constexpr uint64 QDOJO_RULESET_3 = 0x2c84e49f93f41758ULL;

struct QDOJO2
{
};

struct QDOJO : public ContractBase
{
    // =========================================================== records
    struct TimingProfile
    {
        uint32 profileId;
        uint16 commitTicks;
        uint16 revealTicks;
        uint8 used;
    };

    struct FeeProfile
    {
        uint32 profileId;
        uint16 rakeBps;
        uint16 houseBps;
        uint16 devBps;
        uint16 shareBps;
        id house;
        id dev;
        id share;
        uint8 used;
    };

    struct Tier
    {
        uint16 tierId;
        sint64 stake;
        uint8 used;
    };

    // Deployment values (contract.py Manifest).
    struct Manifest
    {
        id networkId;
        id contractId;
        id admin;
        id rulesetDigest;
        Array<TimingProfile, 4> timing;
        Array<FeeProfile, 4> fees;
        Array<Tier, 8> tiers;
        sint64 genesisTick;
        sint64 genesisEpoch;
        sint64 ticksPerEpoch;
        sint64 seasonStartEpoch;
        sint64 seasonEpochs;
        sint64 seasonCloseoutTicks;
        uint32 maxFighters;
        uint32 maxAccounts;
        uint32 maxOffers;
        uint32 maxFights;
        uint32 maxCups;
        uint32 maxCupEntrants;
        uint32 eventRing;
        uint32 matchInterval;
        uint64 offerLifetimeLo;
        uint64 offerLifetimeHi;
        uint64 cooldownTicks;
        uint32 faultsPerEpoch;
        uint32 pairStartsPerEpoch;      // matchmaking.md: 2
        uint64 pairRematchTicks;        // matchmaking.md: 120
    };

    struct SeasonSlot
    {
        uint32 season;              // 0 = unused
        uint8 hasRating;
        uint8 hasStats;
        uint16 rating;
        uint32 fights;
        uint32 wins;
        uint32 finalEpochFights;
        uint16 defeated;            // exact distinct defeated opponents
        uint8 opponents;            // distinct opponents, saturating at 4
        Array<uint16, 4> opponentIdx;
        Array<uint64, 16> defeatedBits;
    };

    struct Fighter
    {
        id fighterId;
        id owner;
        id op;
        uint32 authVersion;
        uint8 houseNpc;
        uint8 lock;
        uint64 lockRef;
        uint16 lifetime;
        uint32 placement;
        sint64 faultEpoch;
        uint32 faultCount;
        uint64 cooldownUntil;
        sint64 suspendedEpoch;
        uint32 recW;
        uint32 recD;
        uint32 recL;
        uint32 recFW;
        uint32 recFL;
        Array<SeasonSlot, 2> seasons;   // indexed by season % 2
    };

    struct RegistryAsset
    {
        id fighterId;
        uint32 registryVersion;
        uint8 houseNpc;
        uint8 used;
    };

    struct Account
    {
        id who;
        sint64 credit;
        uint8 used;
        uint8 slot;                 // holds an account slot; never released
        uint8 hasNonce;
        uint16 lastOp;
        uint64 nonce;
        id digest;                  // SHA-256 of the last accepted frame
        uint64 lastTarget;
    };

    struct Offer
    {
        uint64 offerId;
        uint16 fighterIdx;
        id fighterId;
        id owner;
        id op;
        id payer;
        id payout;
        uint32 authVersion;
        uint32 timingId;
        uint32 feeId;
        uint16 tierId;
        sint64 amount;
        uint16 rating;
        uint16 maxGap;
        uint64 created;
        uint64 expires;
        uint64 generation;
        uint8 status;
        uint8 kind;
        id opponentId;
        uint8 seriesFormat;
        uint64 contestId;
        uint8 escrowed;
        uint8 used;
    };

    struct Participant
    {
        id fighterId;
        id owner;
        id op;
        uint32 authVersion;
        id payout;
        uint16 lifetime;
        uint16 seasonRating;
    };

    struct Series
    {
        uint8 need;
        uint8 cap;
        uint8 winsA;
        uint8 winsB;
        uint8 fights;
    };

    struct Contest
    {
        uint64 contestId;
        uint8 mode;
        uint8 fmt;
        uint8 status;
        uint8 replay;
        Participant a;
        Participant b;
        uint16 aIdx;
        uint16 bIdx;
        id payerA;
        id payerB;
        sint64 potA;
        sint64 potB;
        uint8 hasPot;
        sint64 stake;
        uint32 feeId;
        uint32 timingId;
        uint64 generation;
        uint64 startTick;
        uint32 season;
        Series series;
        uint64 cupId;
        uint64 pairingId;
        uint64 currentFight;
        uint8 resultKind;
        uint8 resultWinner;
        uint8 hasStartsKey;
        sint64 startsEpoch;
        uint8 used;
    };

    // combat_core.h Fighter / FightState / Plan
    struct EFighter
    {
        uint16 hp;
        uint16 stamina;
        uint8 opening;
        uint8 guardStreak;
        uint8 powerAvailable;
    };

    struct EState
    {
        EFighter a;
        EFighter b;
        uint8 roundIndex;
        uint8 outcome;
        uint8 winner;
    };

    struct EPlan
    {
        Array<uint8, 8> actions;    // six used
        uint8 powerSlot;
    };

    struct Fight
    {
        uint64 fightId;
        uint64 contestId;
        uint8 phase;
        uint16 commitTicks;
        uint16 revealTicks;
        uint64 startTick;
        uint64 commitLast;
        uint64 revealLast;
        id contextDigest;
        id roundStateDigest;        // cached for the current round start
        EState st;
        Array<uint8, 2> committed;
        Array<id, 2> commitment;
        Array<uint8, 2> revealed;
        Array<id, 2> salt;
        Array<EPlan, 2> plan;
        uint8 resultKind;
        uint8 resultWinner;
        uint8 used;
    };

    struct CupEntry
    {
        id fighterId;
        id payer;
        id owner;
        id op;
        uint16 fighterIdx;
        sint64 amount;
    };

    struct Pairing
    {
        uint64 pairingId;
        uint8 level;
        id a;
        id b;
        uint8 hasA;
        uint8 hasB;
        uint8 checkedA;
        uint8 checkedB;
        uint64 contestId;
        id winner;
        uint8 hasWinner;
        uint8 status;
        uint64 replayAt;
        id finalOwner;
        uint8 hasFinalOwner;
    };

    struct CupDescriptor
    {
        uint32 timingId;
        uint32 feeId;
        sint64 entryFee;
        uint64 registrationClose;
        uint8 minEntrants;
        uint8 maxEntrants;
        uint16 levelTicks;
        uint16 firstLevelDelay;
        uint16 checkinTicks;
        uint16 replayDelay;
    };

    struct Cup
    {
        uint64 cupId;
        CupDescriptor d;
        id sponsor;
        sint64 sponsorship;
        uint64 generation;
        uint64 created;
        Array<CupEntry, 16> entries;
        uint8 nEntries;
        uint8 status;
        uint8 levels;
        uint8 level;
        uint64 levelStart;
        uint16 postponedMask;
        uint8 pendingReservation;
        uint32 reserved;
        Array<Pairing, 16> pairings;    // pairing_id - 1
        uint8 nPairings;
        Array<id, 16> slots;
        Array<uint8, 16> slotUsed;
        uint8 nSlots;
        id champion;
        uint32 combatFights;
        uint64 expiryTick;
        uint8 hasPot;
        uint8 used;
    };

    struct PairRecord
    {
        uint16 lo;
        uint16 hi;
        sint64 epoch;
        uint32 starts;
        uint64 last;
        uint8 hasLast;
        uint8 used;
    };

    struct Event
    {
        uint64 seq;
        uint64 tick;
        uint16 type;
        uint16 len;
        id digest;
        Array<uint8, 128> body;
    };

    struct Faults                   // must stay zero; the parity test asserts it
    {
        uint32 arithmetic;
        uint32 accountOverflow;
        uint32 pairOverflow;
        uint32 slotOverflow;
        uint32 engine;
    };

    struct StateData
    {
        Manifest m;
        uint8 manifestLoaded;       // set by a test that preloads m before INITIALIZE
        uint8 initOk;               // the manifest passed init's checks
        // ledger
        sint64 balance;
        sint64 paidOut;
        sint64 overflowCredit;
        uint32 creditCount;
        uint32 nSlots;
        // service heartbeat
        uint64 generation;
        uint64 lastServiced;
        uint64 lastObserved;
        uint64 tick;
        // ids
        uint64 nextOffer;
        uint64 nextContest;
        uint64 nextFight;
        uint64 nextCup;
        // registry
        uint8 rulesetRetired;
        uint32 nFighters;
        Array<Fighter, 1024> fighters;
        Array<RegistryAsset, 2048> assets;
        Array<Account, 2048> accounts;
        Array<Offer, 128> offers;
        Array<Contest, 32> contests;
        Array<Fight, 32> fights;
        Array<Cup, 8> cups;
        Array<PairRecord, 4096> pairs;
        // events
        uint64 eventSeq;
        id eventDigest;
        Array<Event, 2048> events;
        Faults faults;
    };

    // =========================================================== scratch types
    struct Sha256
    {
        Array<uint32, 8> h;
        Array<uint8, 64> buf;
        uint32 bufLen;
        uint64 totalLen;
        Array<uint32, 64> w;
        uint32 a;
        uint32 b;
        uint32 c;
        uint32 d;
        uint32 e;
        uint32 f;
        uint32 g;
        uint32 hh;
        uint32 t1;
        uint32 t2;
        uint32 i;       // compress loop
        uint32 j;       // absorb loops
        uint64 bits;
    };

    struct Body
    {
        Array<uint8, 256> b;
        uint32 n;
    };

    struct Res
    {
        uint8 code;
        uint64 target;
    };

    struct Half                     // combat_core.h detail::Half
    {
        uint16 cost;
        uint16 paid;
        uint8 effective;
        uint8 power;
    };

    struct Ctx;                     // every helper's temporaries; defined below the helpers

    // =========================================================== checked arithmetic
    // A checked failure never wraps: it saturates and counts in faults.arithmetic.
    static sint64 addI64(StateData& s, sint64 x, sint64 y)
    {
        if ((y > 0 && x > QDOJO_I64_MAX - y) || (y < 0 && x < -QDOJO_I64_MAX - 1 - y))
        {
            s.faults.arithmetic += 1;
            return y > 0 ? QDOJO_I64_MAX : -QDOJO_I64_MAX - 1;
        }
        return x + y;
    }

    static sint64 subI64(StateData& s, sint64 x, sint64 y)
    {
        if (y == -QDOJO_I64_MAX - 1)
        {
            s.faults.arithmetic += 1;
            return QDOJO_I64_MAX;
        }
        return addI64(s, x, -y);
    }

    // Nonnegative operands only.
    static sint64 mulI64(StateData& s, sint64 x, sint64 y)
    {
        if (x < 0 || y < 0 || (x != 0 && y > div<sint64>(QDOJO_I64_MAX, x)))
        {
            s.faults.arithmetic += 1;
            return QDOJO_I64_MAX;
        }
        return x * y;
    }

    static uint64 addU64(StateData& s, uint64 x, uint64 y)
    {
        if (x > 0xffffffffffffffffULL - y)
        {
            s.faults.arithmetic += 1;
            return 0xffffffffffffffffULL;
        }
        return x + y;
    }

    // Floor division for y > 0 (Python //).
    static sint64 floorDiv(sint64 x, sint64 y)
    {
        return div<sint64>(x, y) - ((mod<sint64>(x, y) != 0 && x < 0) ? 1 : 0);
    }

    // =========================================================== time
    static sint64 epochOf(const StateData& s, uint64 t)
    {
        return s.m.genesisEpoch + floorDiv(sint64(t) - s.m.genesisTick, s.m.ticksPerEpoch);
    }

    static uint32 seasonOf(const StateData& s, uint64 t)
    {
        return epochOf(s, t) < s.m.seasonStartEpoch
            ? 0U
            : uint32(1 + floorDiv(epochOf(s, t) - s.m.seasonStartEpoch, s.m.seasonEpochs));
    }

    // =========================================================== identities
    // Byte i (0..31) of a 32-byte identity, in wire order.
    static uint8 idByte(const id& x, uint32 i)
    {
        return uint8(((i < 8) ? x.u64._0 : (i < 16) ? x.u64._1 : (i < 24) ? x.u64._2 : x.u64._3) >> (8 * (i & 7)));
    }

    static uint64 bswap64(uint64 v)
    {
        return ((v & 0xffULL) << 56) | ((v & 0xff00ULL) << 40) | ((v & 0xff0000ULL) << 24)
            | ((v & 0xff000000ULL) << 8) | ((v >> 8) & 0xff000000ULL) | ((v >> 24) & 0xff0000ULL)
            | ((v >> 40) & 0xff00ULL) | (v >> 56);
    }

    // Unsigned lexicographic byte order, as Python compares bytes (never m256i operator<).
    static sint32 idCmp(const id& x, const id& y)
    {
        if (x.u64._0 != y.u64._0)
        {
            return bswap64(x.u64._0) < bswap64(y.u64._0) ? -1 : 1;
        }
        if (x.u64._1 != y.u64._1)
        {
            return bswap64(x.u64._1) < bswap64(y.u64._1) ? -1 : 1;
        }
        if (x.u64._2 != y.u64._2)
        {
            return bswap64(x.u64._2) < bswap64(y.u64._2) ? -1 : 1;
        }
        if (x.u64._3 != y.u64._3)
        {
            return bswap64(x.u64._3) < bswap64(y.u64._3) ? -1 : 1;
        }
        return 0;
    }

    // Little-endian unsigned integer of `width` (1..8) bytes at frame offset `at`.
    static uint64 rdLe(const Array<uint8, 512>& fr, uint32 at, uint32 width)
    {
        return uint64(fr.get(at))
            | (width > 1 ? uint64(fr.get(at + 1)) << 8 : 0ULL)
            | (width > 2 ? uint64(fr.get(at + 2)) << 16 : 0ULL)
            | (width > 3 ? uint64(fr.get(at + 3)) << 24 : 0ULL)
            | (width > 4 ? uint64(fr.get(at + 4)) << 32 : 0ULL)
            | (width > 5 ? uint64(fr.get(at + 5)) << 40 : 0ULL)
            | (width > 6 ? uint64(fr.get(at + 6)) << 48 : 0ULL)
            | (width > 7 ? uint64(fr.get(at + 7)) << 56 : 0ULL);
    }

    // 32 frame bytes at `at` as an identity (the wire byte order is kept).
    static id idFromFrame(const Array<uint8, 512>& fr, uint32 at)
    {
        return id(rdLe(fr, at, 8), rdLe(fr, at + 8, 8), rdLe(fr, at + 16, 8), rdLe(fr, at + 24, 8));
    }

    // =========================================================== SHA-256 (FIPS 180-4)
    static uint32 rotr(uint32 x, uint32 n)
    {
        return (x >> n) | (x << (32 - n));
    }

    static uint32 shaK(uint32 i)
    {
        switch (i)
        {
        case 0: return 0x428a2f98U; case 1: return 0x71374491U; case 2: return 0xb5c0fbcfU; case 3: return 0xe9b5dba5U;
        case 4: return 0x3956c25bU; case 5: return 0x59f111f1U; case 6: return 0x923f82a4U; case 7: return 0xab1c5ed5U;
        case 8: return 0xd807aa98U; case 9: return 0x12835b01U; case 10: return 0x243185beU; case 11: return 0x550c7dc3U;
        case 12: return 0x72be5d74U; case 13: return 0x80deb1feU; case 14: return 0x9bdc06a7U; case 15: return 0xc19bf174U;
        case 16: return 0xe49b69c1U; case 17: return 0xefbe4786U; case 18: return 0x0fc19dc6U; case 19: return 0x240ca1ccU;
        case 20: return 0x2de92c6fU; case 21: return 0x4a7484aaU; case 22: return 0x5cb0a9dcU; case 23: return 0x76f988daU;
        case 24: return 0x983e5152U; case 25: return 0xa831c66dU; case 26: return 0xb00327c8U; case 27: return 0xbf597fc7U;
        case 28: return 0xc6e00bf3U; case 29: return 0xd5a79147U; case 30: return 0x06ca6351U; case 31: return 0x14292967U;
        case 32: return 0x27b70a85U; case 33: return 0x2e1b2138U; case 34: return 0x4d2c6dfcU; case 35: return 0x53380d13U;
        case 36: return 0x650a7354U; case 37: return 0x766a0abbU; case 38: return 0x81c2c92eU; case 39: return 0x92722c85U;
        case 40: return 0xa2bfe8a1U; case 41: return 0xa81a664bU; case 42: return 0xc24b8b70U; case 43: return 0xc76c51a3U;
        case 44: return 0xd192e819U; case 45: return 0xd6990624U; case 46: return 0xf40e3585U; case 47: return 0x106aa070U;
        case 48: return 0x19a4c116U; case 49: return 0x1e376c08U; case 50: return 0x2748774cU; case 51: return 0x34b0bcb5U;
        case 52: return 0x391c0cb3U; case 53: return 0x4ed8aa4aU; case 54: return 0x5b9cca4fU; case 55: return 0x682e6ff3U;
        case 56: return 0x748f82eeU; case 57: return 0x78a5636fU; case 58: return 0x84c87814U; case 59: return 0x8cc70208U;
        case 60: return 0x90befffaU; case 61: return 0xa4506cebU; case 62: return 0xbef9a3f7U; case 63: return 0xc67178f2U;
        default: return 0;
        }
    }

    static void shaInit(Sha256& s)
    {
        s.h.set(0, 0x6a09e667U);
        s.h.set(1, 0xbb67ae85U);
        s.h.set(2, 0x3c6ef372U);
        s.h.set(3, 0xa54ff53aU);
        s.h.set(4, 0x510e527fU);
        s.h.set(5, 0x9b05688cU);
        s.h.set(6, 0x1f83d9abU);
        s.h.set(7, 0x5be0cd19U);
        s.bufLen = 0;
        s.totalLen = 0;
    }

    static void shaCompress(Sha256& s)
    {
        for (s.i = 0; s.i < 16; s.i++)
        {
            s.w.set(s.i, (uint32(s.buf.get(4 * s.i)) << 24) | (uint32(s.buf.get(4 * s.i + 1)) << 16)
                | (uint32(s.buf.get(4 * s.i + 2)) << 8) | uint32(s.buf.get(4 * s.i + 3)));
        }
        for (s.i = 16; s.i < 64; s.i++)
        {
            s.t1 = rotr(s.w.get(s.i - 15), 7) ^ rotr(s.w.get(s.i - 15), 18) ^ (s.w.get(s.i - 15) >> 3);
            s.t2 = rotr(s.w.get(s.i - 2), 17) ^ rotr(s.w.get(s.i - 2), 19) ^ (s.w.get(s.i - 2) >> 10);
            s.w.set(s.i, s.w.get(s.i - 16) + s.t1 + s.w.get(s.i - 7) + s.t2);
        }
        s.a = s.h.get(0);
        s.b = s.h.get(1);
        s.c = s.h.get(2);
        s.d = s.h.get(3);
        s.e = s.h.get(4);
        s.f = s.h.get(5);
        s.g = s.h.get(6);
        s.hh = s.h.get(7);
        for (s.i = 0; s.i < 64; s.i++)
        {
            s.t1 = s.hh + (rotr(s.e, 6) ^ rotr(s.e, 11) ^ rotr(s.e, 25)) + ((s.e & s.f) ^ (~s.e & s.g))
                + shaK(s.i) + s.w.get(s.i);
            s.t2 = (rotr(s.a, 2) ^ rotr(s.a, 13) ^ rotr(s.a, 22)) + ((s.a & s.b) ^ (s.a & s.c) ^ (s.b & s.c));
            s.hh = s.g;
            s.g = s.f;
            s.f = s.e;
            s.e = s.d + s.t1;
            s.d = s.c;
            s.c = s.b;
            s.b = s.a;
            s.a = s.t1 + s.t2;
        }
        s.h.set(0, s.h.get(0) + s.a);
        s.h.set(1, s.h.get(1) + s.b);
        s.h.set(2, s.h.get(2) + s.c);
        s.h.set(3, s.h.get(3) + s.d);
        s.h.set(4, s.h.get(4) + s.e);
        s.h.set(5, s.h.get(5) + s.f);
        s.h.set(6, s.h.get(6) + s.g);
        s.h.set(7, s.h.get(7) + s.hh);
    }

    static void shaByte(Sha256& s, uint8 v)
    {
        s.buf.set(s.bufLen, v);
        s.bufLen += 1;
        s.totalLen += 1;
        if (s.bufLen == 64)
        {
            shaCompress(s);
            s.bufLen = 0;
        }
    }

    // `width` little-endian bytes of v.
    static void shaLe(Sha256& s, uint64 v, uint32 width)
    {
        for (s.j = 0; s.j < width; s.j++)
        {
            shaByte(s, uint8(v >> (8 * s.j)));
        }
    }

    static void shaId(Sha256& s, const id& x)
    {
        for (s.j = 0; s.j < 32; s.j++)
        {
            shaByte(s, idByte(x, s.j));
        }
    }

    // A domain tag packed little-endian into four words, `len` bytes long.
    static void shaTag(Sha256& s, uint64 w0, uint64 w1, uint64 w2, uint64 w3, uint32 len)
    {
        for (s.j = 0; s.j < len; s.j++)
        {
            shaByte(s, uint8(((s.j < 8) ? w0 : (s.j < 16) ? w1 : (s.j < 24) ? w2 : w3) >> (8 * (s.j & 7))));
        }
    }

    static uint64 bswap32w(uint32 v)
    {
        return uint64(((v & 0xffU) << 24) | ((v & 0xff00U) << 8) | ((v >> 8) & 0xff00U) | (v >> 24));
    }

    static id shaFinal(Sha256& s)
    {
        s.bits = s.totalLen * 8;
        s.buf.set(s.bufLen, 0x80);
        s.bufLen += 1;
        if (s.bufLen > 56)
        {
            while (s.bufLen < 64)
            {
                s.buf.set(s.bufLen, 0);
                s.bufLen += 1;
            }
            shaCompress(s);
            s.bufLen = 0;
        }
        while (s.bufLen < 56)
        {
            s.buf.set(s.bufLen, 0);
            s.bufLen += 1;
        }
        for (s.j = 0; s.j < 8; s.j++)
        {
            s.buf.set(56 + s.j, uint8(s.bits >> (56 - 8 * s.j)));
        }
        shaCompress(s);
        // Digest bytes are h[0..7] big-endian; pack them into the id's little-endian words.
        return id(bswap32w(s.h.get(0)) | (bswap32w(s.h.get(1)) << 32),
            bswap32w(s.h.get(2)) | (bswap32w(s.h.get(3)) << 32),
            bswap32w(s.h.get(4)) | (bswap32w(s.h.get(5)) << 32),
            bswap32w(s.h.get(6)) | (bswap32w(s.h.get(7)) << 32));
    }

    // =========================================================== event bodies (contract.py _event_body)
    // tag 0: u64 LE; tag 1: u16-length bytes; tag 2: u8-length ASCII.
    static void bReset(Ctx& c)
    {
        c.body.n = 0;
    }

    static void bByte(Ctx& c, uint8 v)
    {
        c.body.b.set(c.body.n, v);
        c.body.n += 1;
    }

    static void bU64(Ctx& c, uint64 v)
    {
        bByte(c, 0);
        for (c.bw_i = 0; c.bw_i < 8; c.bw_i++)
        {
            bByte(c, uint8(v >> (8 * c.bw_i)));
        }
    }

    static void bId(Ctx& c, const id& x)
    {
        bByte(c, 1);
        bByte(c, 32);
        bByte(c, 0);
        for (c.bw_i = 0; c.bw_i < 32; c.bw_i++)
        {
            bByte(c, idByte(x, c.bw_i));
        }
    }

    // `len` raw frame bytes at `at` as a tag-1 field.
    static void bFrameBytes(Ctx& c, const Array<uint8, 512>& fr, uint32 at, uint16 len)
    {
        bByte(c, 1);
        bByte(c, uint8(len & 0xff));
        bByte(c, uint8(len >> 8));
        for (c.bw_i = 0; c.bw_i < len; c.bw_i++)
        {
            bByte(c, fr.get(at + c.bw_i));
        }
    }

    // combat_core.h encode_state: hp u16 LE, stamina u16 LE, opening, guard_streak, power_available, 0.
    static void bState(Ctx& c, const EFighter& f)
    {
        bByte(c, uint8(f.hp & 0xff));
        bByte(c, uint8(f.hp >> 8));
        bByte(c, uint8(f.stamina & 0xff));
        bByte(c, uint8(f.stamina >> 8));
        bByte(c, f.opening);
        bByte(c, f.guardStreak);
        bByte(c, f.powerAvailable);
        bByte(c, 0);
    }

    static void bStr(Ctx& c, uint8 code)
    {
        strWords(code, c.bs_lo, c.bs_hi, c.bs_len);
        bByte(c, 2);
        bByte(c, c.bs_len);
        for (c.bw_i = 0; c.bw_i < c.bs_len; c.bw_i++)
        {
            bByte(c, uint8((c.bw_i < 8) ? (c.bs_lo >> (8 * c.bw_i)) : (c.bs_hi >> (8 * (c.bw_i - 8)))));
        }
    }

    // ASCII bytes of a QDOJO_STR_* string, packed little-endian (no string literals).
    static void strWords(uint8 code, uint64& lo, uint64& hi, uint8& len)
    {
        switch (code)
        {
        case QDOJO_STR_OPEN: lo = 0x000000004e45504fULL; hi = 0x0000000000000000ULL; len = 4; break;
        case QDOJO_STR_MATCHED: lo = 0x004445484354414dULL; hi = 0x0000000000000000ULL; len = 7; break;
        case QDOJO_STR_CANCELLED: lo = 0x454c4c45434e4143ULL; hi = 0x0000000000000044ULL; len = 9; break;
        case QDOJO_STR_EXPIRED: lo = 0x0044455249505845ULL; hi = 0x0000000000000000ULL; len = 7; break;
        case QDOJO_STR_INVALIDATED: lo = 0x4144494c41564e49ULL; hi = 0x0000000000444554ULL; len = 11; break;
        case QDOJO_STR_COMBAT: lo = 0x00005441424d4f43ULL; hi = 0x0000000000000000ULL; len = 6; break;
        case QDOJO_STR_FORFEIT: lo = 0x0054494546524f46ULL; hi = 0x0000000000000000ULL; len = 7; break;
        case QDOJO_STR_DOUBLE_FAULT: lo = 0x465f454c42554f44ULL; hi = 0x00000000544c5541ULL; len = 12; break;
        case QDOJO_STR_VOID: lo = 0x0000000044494f56ULL; hi = 0x0000000000000000ULL; len = 4; break;
        case QDOJO_STR_A: lo = 0x0000000000000041ULL; hi = 0x0000000000000000ULL; len = 1; break;
        case QDOJO_STR_B: lo = 0x0000000000000042ULL; hi = 0x0000000000000000ULL; len = 1; break;
        case QDOJO_STR_DASH: lo = 0x000000000000002dULL; hi = 0x0000000000000000ULL; len = 1; break;
        case QDOJO_STR_SCHEDULED: lo = 0x454c554445484353ULL; hi = 0x0000000000000044ULL; len = 9; break;
        case QDOJO_STR_PLAYING: lo = 0x00474e4959414c50ULL; hi = 0x0000000000000000ULL; len = 7; break;
        case QDOJO_STR_REPLAY_WAIT: lo = 0x575f59414c504552ULL; hi = 0x0000000000544941ULL; len = 11; break;
        case QDOJO_STR_DONE: lo = 0x00000000454e4f44ULL; hi = 0x0000000000000000ULL; len = 4; break;
        case QDOJO_STR_UNRESOLVED: lo = 0x564c4f5345524e55ULL; hi = 0x0000000000004445ULL; len = 10; break;
        case QDOJO_STR_EMPTY: lo = 0x0000005954504d45ULL; hi = 0x0000000000000000ULL; len = 5; break;
        case QDOJO_STR_SERVICE_VOID: lo = 0x5f45434956524553ULL; hi = 0x0000000044494f56ULL; len = 12; break;
        case QDOJO_STR_CAPACITY: lo = 0x5954494341504143ULL; hi = 0x0000000000000000ULL; len = 8; break;
        case QDOJO_STR_NO_CHAMPION: lo = 0x504d4148435f4f4eULL; hi = 0x00000000004e4f49ULL; len = 11; break;
        case QDOJO_STR_ABORTED: lo = 0x00444554524f4241ULL; hi = 0x0000000000000000ULL; len = 7; break;
        case QDOJO_STR_COMPLETE: lo = 0x4554454c504d4f43ULL; hi = 0x0000000000000000ULL; len = 8; break;
        default: lo = 0; hi = 0; len = 0; break;
        }
    }

    static uint8 offerStatusStr(uint8 st)
    {
        return st == QDOJO_O_OPEN ? QDOJO_STR_OPEN
            : st == QDOJO_O_MATCHED ? QDOJO_STR_MATCHED
            : st == QDOJO_O_CANCELLED ? QDOJO_STR_CANCELLED
            : st == QDOJO_O_EXPIRED ? QDOJO_STR_EXPIRED
            : QDOJO_STR_INVALIDATED;
    }

    static uint8 kindStr(uint8 k)
    {
        return k == QDOJO_R_COMBAT ? QDOJO_STR_COMBAT
            : k == QDOJO_R_FORFEIT ? QDOJO_STR_FORFEIT
            : k == QDOJO_R_DOUBLE_FAULT ? QDOJO_STR_DOUBLE_FAULT
            : QDOJO_STR_VOID;
    }

    static uint8 sideStr(uint8 w)
    {
        return w == QDOJO_S_A ? QDOJO_STR_A : w == QDOJO_S_B ? QDOJO_STR_B : QDOJO_STR_DASH;
    }

    static uint8 pairingStatusStr(uint8 st)
    {
        return st == QDOJO_PS_SCHEDULED ? QDOJO_STR_SCHEDULED
            : st == QDOJO_PS_PLAYING ? QDOJO_STR_PLAYING
            : st == QDOJO_PS_REPLAY_WAIT ? QDOJO_STR_REPLAY_WAIT
            : st == QDOJO_PS_DONE ? QDOJO_STR_DONE
            : st == QDOJO_PS_UNRESOLVED ? QDOJO_STR_UNRESOLVED
            : QDOJO_STR_EMPTY;
    }

    static uint8 abortStr(uint8 why)
    {
        return why == QDOJO_AB_SERVICE_VOID ? QDOJO_STR_SERVICE_VOID
            : why == QDOJO_AB_EXPIRED ? QDOJO_STR_EXPIRED
            : why == QDOJO_AB_CAPACITY ? QDOJO_STR_CAPACITY
            : QDOJO_STR_NO_CHAMPION;
    }

    // event_digest = SHA256("qdojo/combat/event/v1\0" || previous[32] || seq u64 || type u16 || body).
    // The body is the one built in c.body.
    static void emit(StateData& s, Ctx& c, uint16 type)
    {
        s.eventSeq += 1;
        shaInit(c.sha);
        shaTag(c.sha, QDOJO_TAG_EVENT_0, QDOJO_TAG_EVENT_1, QDOJO_TAG_EVENT_2, QDOJO_TAG_EVENT_3, QDOJO_TAG_EVENT_LEN);
        shaId(c.sha, s.eventDigest);
        shaLe(c.sha, s.eventSeq, 8);
        shaLe(c.sha, type, 2);
        for (c.em_i = 0; c.em_i < c.body.n; c.em_i++)
        {
            shaByte(c.sha, c.body.b.get(c.em_i));
        }
        s.eventDigest = shaFinal(c.sha);
        c.ev.seq = s.eventSeq;
        c.ev.tick = s.tick;
        c.ev.type = type;
        c.ev.len = uint16(c.body.n < QDOJO_EVENT_BODY_MAX ? c.body.n : QDOJO_EVENT_BODY_MAX);
        for (c.em_i = 0; c.em_i < QDOJO_EVENT_BODY_CAP; c.em_i++)
        {
            c.ev.body.set(c.em_i, c.em_i < c.ev.len ? c.body.b.get(c.em_i) : uint8(0));
        }
        c.ev.digest = s.eventDigest;
        s.events.set(mod<uint64>(s.eventSeq - 1, uint64(s.m.eventRing)), c.ev);
    }

    // =========================================================== lookups (leaves; they share c.lk_i)
    static sint32 fighterIndex(const StateData& s, Ctx& c, const id& fid)
    {
        for (c.lk_i = 0; c.lk_i < QDOJO_CAP_FIGHTERS; c.lk_i++)
        {
            if (c.lk_i >= s.nFighters)
            {
                break;
            }
            if (s.fighters.get(c.lk_i).fighterId == fid)
            {
                return sint32(c.lk_i);
            }
        }
        return -1;
    }

    static sint32 assetIndex(const StateData& s, Ctx& c, const id& fid)
    {
        for (c.lk_i = 0; c.lk_i < QDOJO_CAP_ASSETS; c.lk_i++)
        {
            if (s.assets.get(c.lk_i).used && s.assets.get(c.lk_i).fighterId == fid)
            {
                return sint32(c.lk_i);
            }
        }
        return -1;
    }

    static sint32 accountIndex(const StateData& s, Ctx& c, const id& who)
    {
        for (c.lk_i = 0; c.lk_i < QDOJO_CAP_ACCOUNTS; c.lk_i++)
        {
            if (s.accounts.get(c.lk_i).used && s.accounts.get(c.lk_i).who == who)
            {
                return sint32(c.lk_i);
            }
        }
        return -1;
    }

    // A table entry is reusable when it is not a slot holder and holds no credit.
    static sint32 accountFreeSlot(const StateData& s, Ctx& c)
    {
        for (c.lk_i = 0; c.lk_i < QDOJO_CAP_ACCOUNTS; c.lk_i++)
        {
            if (!s.accounts.get(c.lk_i).used || (!s.accounts.get(c.lk_i).slot && s.accounts.get(c.lk_i).credit == 0))
            {
                return sint32(c.lk_i);
            }
        }
        return -1;
    }

    static sint32 offerSlot(const StateData& s, Ctx& c, uint64 offerId)
    {
        for (c.lk_i = 0; c.lk_i < QDOJO_CAP_OFFER_SLOTS; c.lk_i++)
        {
            if (s.offers.get(c.lk_i).used && s.offers.get(c.lk_i).offerId == offerId)
            {
                return sint32(c.lk_i);
            }
        }
        return -1;
    }

    static sint32 contestSlot(const StateData& s, Ctx& c, uint64 contestId)
    {
        for (c.lk_i = 0; c.lk_i < QDOJO_CAP_CONTEST_SLOTS; c.lk_i++)
        {
            if (s.contests.get(c.lk_i).used && s.contests.get(c.lk_i).contestId == contestId)
            {
                return sint32(c.lk_i);
            }
        }
        return -1;
    }

    static sint32 fightSlot(const StateData& s, Ctx& c, uint64 fightId)
    {
        for (c.lk_i = 0; c.lk_i < QDOJO_CAP_FIGHT_SLOTS; c.lk_i++)
        {
            if (s.fights.get(c.lk_i).used && s.fights.get(c.lk_i).fightId == fightId)
            {
                return sint32(c.lk_i);
            }
        }
        return -1;
    }

    static sint32 cupSlot(const StateData& s, Ctx& c, uint64 cupId)
    {
        for (c.lk_i = 0; c.lk_i < QDOJO_CAP_CUP_SLOTS; c.lk_i++)
        {
            if (s.cups.get(c.lk_i).used && s.cups.get(c.lk_i).cupId == cupId)
            {
                return sint32(c.lk_i);
            }
        }
        return -1;
    }

    // New record slots: a free slot, else the lowest-id terminal record (no
    // liability, no lock) is evicted. -1 only if every slot is live.
    static sint32 newOfferSlot(StateData& s, Ctx& c)
    {
        c.ns_best = -1;
        for (c.lk_i = 0; c.lk_i < QDOJO_CAP_OFFER_SLOTS; c.lk_i++)
        {
            if (!s.offers.get(c.lk_i).used)
            {
                return sint32(c.lk_i);
            }
            if (s.offers.get(c.lk_i).status != QDOJO_O_OPEN && !s.offers.get(c.lk_i).escrowed
                && (c.ns_best < 0 || s.offers.get(c.lk_i).offerId < s.offers.get(c.ns_best).offerId))
            {
                c.ns_best = sint32(c.lk_i);
            }
        }
        if (c.ns_best < 0)
        {
            s.faults.slotOverflow += 1;
        }
        return c.ns_best;
    }

    static sint32 newContestSlot(StateData& s, Ctx& c)
    {
        c.ns_best = -1;
        for (c.lk_i = 0; c.lk_i < QDOJO_CAP_CONTEST_SLOTS; c.lk_i++)
        {
            if (!s.contests.get(c.lk_i).used)
            {
                return sint32(c.lk_i);
            }
            if (s.contests.get(c.lk_i).status == QDOJO_C_DONE && !s.contests.get(c.lk_i).hasPot
                && (c.ns_best < 0 || s.contests.get(c.lk_i).contestId < s.contests.get(c.ns_best).contestId))
            {
                c.ns_best = sint32(c.lk_i);
            }
        }
        if (c.ns_best < 0)
        {
            s.faults.slotOverflow += 1;
        }
        return c.ns_best;
    }

    static sint32 newFightSlot(StateData& s, Ctx& c)
    {
        c.ns_best = -1;
        for (c.lk_i = 0; c.lk_i < QDOJO_CAP_FIGHT_SLOTS; c.lk_i++)
        {
            if (!s.fights.get(c.lk_i).used)
            {
                return sint32(c.lk_i);
            }
            if (s.fights.get(c.lk_i).phase == QDOJO_P_DONE
                && (c.ns_best < 0 || s.fights.get(c.lk_i).fightId < s.fights.get(c.ns_best).fightId))
            {
                c.ns_best = sint32(c.lk_i);
            }
        }
        if (c.ns_best < 0)
        {
            s.faults.slotOverflow += 1;
        }
        return c.ns_best;
    }

    static sint32 newCupSlot(StateData& s, Ctx& c)
    {
        c.ns_best = -1;
        for (c.lk_i = 0; c.lk_i < QDOJO_CAP_CUP_SLOTS; c.lk_i++)
        {
            if (!s.cups.get(c.lk_i).used)
            {
                return sint32(c.lk_i);
            }
            if (s.cups.get(c.lk_i).status != QDOJO_CUP_REGISTRATION && s.cups.get(c.lk_i).status != QDOJO_CUP_RUNNING
                && !s.cups.get(c.lk_i).hasPot
                && (c.ns_best < 0 || s.cups.get(c.lk_i).cupId < s.cups.get(c.ns_best).cupId))
            {
                c.ns_best = sint32(c.lk_i);
            }
        }
        if (c.ns_best < 0)
        {
            s.faults.slotOverflow += 1;
        }
        return c.ns_best;
    }

    static sint32 timingIdx(const StateData& s, Ctx& c, uint32 profileId)
    {
        for (c.lk_i = 0; c.lk_i < QDOJO_CAP_TIMING; c.lk_i++)
        {
            if (s.m.timing.get(c.lk_i).used && s.m.timing.get(c.lk_i).profileId == profileId)
            {
                return sint32(c.lk_i);
            }
        }
        return -1;
    }

    static sint32 feeIdx(const StateData& s, Ctx& c, uint32 profileId)
    {
        for (c.lk_i = 0; c.lk_i < QDOJO_CAP_FEES; c.lk_i++)
        {
            if (s.m.fees.get(c.lk_i).used && s.m.fees.get(c.lk_i).profileId == profileId)
            {
                return sint32(c.lk_i);
            }
        }
        return -1;
    }

    static sint32 tierIdx(const StateData& s, Ctx& c, uint16 tierId)
    {
        for (c.lk_i = 0; c.lk_i < QDOJO_CAP_TIERS; c.lk_i++)
        {
            if (s.m.tiers.get(c.lk_i).used && s.m.tiers.get(c.lk_i).tierId == tierId)
            {
                return sint32(c.lk_i);
            }
        }
        return -1;
    }

    static sint64 minTierStake(const StateData& s, Ctx& c)
    {
        c.mts_best = QDOJO_I64_MAX;
        for (c.lk_i = 0; c.lk_i < QDOJO_CAP_TIERS; c.lk_i++)
        {
            if (s.m.tiers.get(c.lk_i).used && s.m.tiers.get(c.lk_i).stake < c.mts_best)
            {
                c.mts_best = s.m.tiers.get(c.lk_i).stake;
            }
        }
        return c.mts_best;
    }

    // =========================================================== host: asset ownership
    // Host::owner_of: the single owner of the fighter's one-unit registry asset
    // (issuer = fighter_id, name QDOJO_FIGHTER_ASSET_NAME). No record, several
    // owners or a NULL_ID owner mean "unavailable"; the contract never guesses.
    static bit ownerOf(Ctx& c, const id& fid, id& out)
    {
        c.own_asset.issuer = fid;
        c.own_asset.assetName = QDOJO_FIGHTER_ASSET_NAME;
        c.own_count = 0;
        c.own_owner = NULL_ID;
        c.own_iter.begin(c.own_asset);
        while (!c.own_iter.reachedEnd())
        {
            if (c.own_iter.numberOfOwnedShares() > 0)
            {
                c.own_count += 1;
                c.own_owner = c.own_iter.owner();
            }
            c.own_iter.next();
        }
        if (c.own_count != 1 || isZero(c.own_owner))
        {
            return false;
        }
        out = c.own_owner;
        return true;
    }

    // =========================================================== ledger (ledger.py)
    static sint32 accountGetOrAlloc(StateData& s, Ctx& c, const id& who)
    {
        c.ga_i = accountIndex(s, c, who);
        if (c.ga_i >= 0)
        {
            return c.ga_i;
        }
        c.ga_i = accountFreeSlot(s, c);
        if (c.ga_i < 0)
        {
            return -1;
        }
        setMemory(c.ga_a, 0);
        c.ga_a.who = who;
        c.ga_a.used = 1;
        s.accounts.set(c.ga_i, c.ga_a);
        return c.ga_i;
    }

    static void credit(StateData& s, Ctx& c, const id& who, sint64 amount)
    {
        if (!amount)
        {
            return;
        }
        c.cr_i = accountGetOrAlloc(s, c, who);
        if (c.cr_i < 0)
        {
            // No slot: keep the liability rather than lose it.
            s.faults.accountOverflow += 1;
            s.overflowCredit = addI64(s, s.overflowCredit, amount);
            return;
        }
        c.cr_a = s.accounts.get(c.cr_i);
        if (c.cr_a.credit == 0)
        {
            s.creditCount += 1;
        }
        c.cr_a.credit = addI64(s, c.cr_a.credit, amount);
        s.accounts.set(c.cr_i, c.cr_a);
    }

    // =========================================================== seasons
    static uint16 ratingIn(const Fighter& f, uint32 season)
    {
        return (season != 0 && f.seasons.get(mod<uint32>(season, 2U)).season == season && f.seasons.get(mod<uint32>(season, 2U)).hasRating)
            ? f.seasons.get(mod<uint32>(season, 2U)).rating
            : uint16(QDOJO_RATING_INITIAL);
    }

    // season_claim: load the slot for `season` into sl, clearing an older season's data.
    // The caller edits sl and stores it with f.seasons.set(mod<uint32>(season, 2U), sl).
    static void seasonClaim(const Fighter& f, uint32 season, SeasonSlot& sl)
    {
        sl = f.seasons.get(mod<uint32>(season, 2U));
        if (sl.season != season)
        {
            setMemory(sl, 0);
            sl.season = season;
            sl.rating = uint16(QDOJO_RATING_INITIAL);
        }
    }

    // =========================================================== pair history
    // An entry is semantically absent once it can no longer affect matching.
    static bit pairStale(const PairRecord& p, sint64 epoch, uint64 t, uint64 rematchTicks)
    {
        return (p.starts == 0 || p.epoch != epoch) && (!p.hasLast || t - p.last >= rematchTicks);
    }

    static uint32 pairHash(uint16 lo, uint16 hi)
    {
        return mod<uint32>((uint32(lo) * 2654435761U) ^ (uint32(hi) * 40503U), QDOJO_CAP_PAIRS);
    }

    // Find (or, with create, claim) the record for fighter indices x, y.
    static sint32 pairFind(StateData& s, Ctx& c, uint16 x, uint16 y, bit create, sint64 epoch, uint64 t)
    {
        c.pf_lo = x < y ? x : y;
        c.pf_hi = x < y ? y : x;
        c.pf_start = pairHash(c.pf_lo, c.pf_hi);
        c.pf_reuse = -1;
        for (c.pf_k = 0; c.pf_k < QDOJO_CAP_PAIRS; c.pf_k++)
        {
            c.pf_i = mod<uint32>(c.pf_start + c.pf_k, QDOJO_CAP_PAIRS);
            if (!s.pairs.get(c.pf_i).used)
            {
                if (c.pf_reuse < 0)
                {
                    c.pf_reuse = sint32(c.pf_i);
                }
                break;  // end of the probe chain
            }
            if (s.pairs.get(c.pf_i).lo == c.pf_lo && s.pairs.get(c.pf_i).hi == c.pf_hi)
            {
                return sint32(c.pf_i);
            }
            if (c.pf_reuse < 0 && pairStale(s.pairs.get(c.pf_i), epoch, t, s.m.pairRematchTicks))
            {
                c.pf_reuse = sint32(c.pf_i);
            }
        }
        if (!create)
        {
            return -1;
        }
        if (c.pf_reuse < 0)
        {
            s.faults.pairOverflow += 1;
            return -1;
        }
        setMemory(c.pf_p, 0);
        c.pf_p.lo = c.pf_lo;
        c.pf_p.hi = c.pf_hi;
        c.pf_p.epoch = epoch;
        c.pf_p.used = 1;
        s.pairs.set(c.pf_reuse, c.pf_p);
        return c.pf_reuse;
    }

    // =========================================================== results
    static void setOk(Res& r, uint64 target)
    {
        r.code = QDOJO_OK;
        r.target = target;
    }

    static void setDup(Res& r, uint64 target)
    {
        r.code = QDOJO_DUPLICATE;
        r.target = target;
    }

    static void setRej(Res& r, uint8 code)
    {
        r.code = code;
        r.target = 0;
    }

    static bit accepted(const Res& r)
    {
        return r.code == QDOJO_OK || r.code == QDOJO_DUPLICATE;
    }

    // =========================================================== account slots
    static bit holdsSlot(const StateData& s, Ctx& c, const id& who)
    {
        c.hs_a = accountIndex(s, c, who);
        return c.hs_a >= 0 && s.accounts.get(c.hs_a).slot;
    }

    // Give `who` a slot, ignoring the manifest bound (construction seeding).
    static bit addSlot(StateData& s, Ctx& c, const id& who)
    {
        c.as_i = accountGetOrAlloc(s, c, who);
        if (c.as_i < 0)
        {
            s.faults.accountOverflow += 1;
            return false;
        }
        if (!s.accounts.get(c.as_i).slot)
        {
            c.as_a = s.accounts.get(c.as_i);
            c.as_a.slot = 1;
            s.accounts.set(c.as_i, c.as_a);
            s.nSlots += 1;
        }
        return true;
    }

    // contract.py _claim: reserve an account slot before accepting funds for `who`.
    static void claim(StateData& s, Ctx& c, const id& who, Res& r)
    {
        if (holdsSlot(s, c, who))
        {
            setOk(r, 0);
            return;
        }
        if (s.nSlots >= s.m.maxAccounts)
        {
            setRej(r, QDOJO_FULL);
            return;
        }
        if (addSlot(s, c, who))
        {
            setOk(r, 0);
        }
        else
        {
            setRej(r, QDOJO_FULL);
        }
    }

    // contract.py _eligible: account holders, owners/operators of registered
    // fighters, and the live owner registering a registry asset.
    static bit eligible(const StateData& s, Ctx& c, const id& who, uint16 op, const Array<uint8, 512>& fr)
    {
        if (holdsSlot(s, c, who))
        {
            return true;
        }
        for (c.el_i = 0; c.el_i < QDOJO_CAP_FIGHTERS; c.el_i++)
        {
            if (c.el_i >= s.nFighters)
            {
                break;
            }
            if (s.fighters.get(c.el_i).owner == who || s.fighters.get(c.el_i).op == who)
            {
                return true;
            }
        }
        if (op == QDOJO_OP_REGISTER_FIGHTER)
        {
            c.el_fid = idFromFrame(fr, QDOJO_FRAME_HEADER);
            if (assetIndex(s, c, c.el_fid) < 0)
            {
                return false;
            }
            return ownerOf(c, c.el_fid, c.el_owner) && c.el_owner == who;
        }
        return false;
    }

    // contract.py _refund, first half. Rejected attachments become withdrawal
    // credit for slot holders. Anyone else is paid straight back: this returns
    // true with the balance already debited, and the entry point then calls
    // qpi.transfer and, only if that fails, refundFailed.
    static bit refundBegin(StateData& s, Ctx& c, const id& who, sint64 amount)
    {
        if (!amount)
        {
            return false;
        }
        if (holdsSlot(s, c, who))
        {
            credit(s, c, who, amount);
            bReset(c);
            bId(c, who);
            bU64(c, uint64(amount));
            emit(s, c, QDOJO_EV_REFUND_CREDIT);
            return false;
        }
        s.balance = subI64(s, s.balance, amount);
        return true;
    }

    // The direct payback failed: the amount is still owed, as credit.
    static void refundFailed(StateData& s, Ctx& c, const id& who, sint64 amount)
    {
        s.balance = addI64(s, s.balance, amount);
        credit(s, c, who, amount);
        bReset(c);
        bId(c, who);
        bU64(c, uint64(amount));
        emit(s, c, QDOJO_EV_REFUND_CREDIT);
    }

    // =========================================================== authority
    static void authorize(const StateData& s, Ctx& c, uint32 fi, const id& inv, uint32 authVersion, Res& r)
    {
        if (!ownerOf(c, s.fighters.get(fi).fighterId, c.au_owner))
        {
            setRej(r, QDOJO_BAD_STATE);
            return;
        }
        if (c.au_owner != s.fighters.get(fi).owner)
        {
            setRej(r, QDOJO_NOT_OWNER);
            return;
        }
        if (authVersion != s.fighters.get(fi).authVersion)
        {
            setRej(r, QDOJO_STALE_AUTH);
            return;
        }
        if (inv != s.fighters.get(fi).op && inv != s.fighters.get(fi).owner)
        {
            setRej(r, QDOJO_NOT_OPERATOR);
            return;
        }
        setOk(r, 0);
    }

    static void profiles(const StateData& s, Ctx& c, const id& rulesetDigest, uint32 timingId, uint32 feeId, Res& r)
    {
        if (rulesetDigest != s.m.rulesetDigest)
        {
            setRej(r, QDOJO_INCOMPATIBLE);
            return;
        }
        if (s.rulesetRetired)
        {
            setRej(r, QDOJO_RULESET_RETIRED);
            return;
        }
        if (timingIdx(s, c, timingId) < 0 || feeIdx(s, c, feeId) < 0)
        {
            setRej(r, QDOJO_INCOMPATIBLE);
            return;
        }
        setOk(r, 0);
    }

    static uint32 openOffers(const StateData& s, Ctx& c)
    {
        c.cnt_n = 0;
        for (c.lk_i = 0; c.lk_i < QDOJO_CAP_OFFER_SLOTS; c.lk_i++)
        {
            if (s.offers.get(c.lk_i).used && s.offers.get(c.lk_i).status == QDOJO_O_OPEN)
            {
                c.cnt_n += 1;
            }
        }
        return c.cnt_n;
    }

    static uint32 liveCups(const StateData& s, Ctx& c)
    {
        c.cnt_n = 0;
        for (c.lk_i = 0; c.lk_i < QDOJO_CAP_CUP_SLOTS; c.lk_i++)
        {
            if (s.cups.get(c.lk_i).used
                && (s.cups.get(c.lk_i).status == QDOJO_CUP_REGISTRATION || s.cups.get(c.lk_i).status == QDOJO_CUP_RUNNING))
            {
                c.cnt_n += 1;
            }
        }
        return c.cnt_n;
    }

    // Slots held by non-cup fights plus every running cup's level reservation.
    static uint32 fightsInUse(const StateData& s, Ctx& c)
    {
        c.cnt_n = 0;
        for (c.lk_i = 0; c.lk_i < QDOJO_CAP_CONTEST_SLOTS; c.lk_i++)
        {
            if (s.contests.get(c.lk_i).used && s.contests.get(c.lk_i).status == QDOJO_C_ACTIVE
                && s.contests.get(c.lk_i).mode != QDOJO_M_CUP)
            {
                c.cnt_n += 1;
            }
        }
        for (c.lk_i = 0; c.lk_i < QDOJO_CAP_CUP_SLOTS; c.lk_i++)
        {
            if (s.cups.get(c.lk_i).used && s.cups.get(c.lk_i).status == QDOJO_CUP_RUNNING)
            {
                c.cnt_n += s.cups.get(c.lk_i).reserved;
            }
        }
        return c.cnt_n;
    }

    // Bounded insertion sort of v[0..n).
    static void sortU64(Array<uint64, 128>& v, uint32 n, Ctx& c)
    {
        for (c.so_i = 1; c.so_i < n; c.so_i++)
        {
            c.so_x = v.get(c.so_i);
            c.so_j = c.so_i;
            while (c.so_j > 0 && v.get(c.so_j - 1) > c.so_x)
            {
                v.set(c.so_j, v.get(c.so_j - 1));
                c.so_j -= 1;
            }
            v.set(c.so_j, c.so_x);
        }
    }

    // =========================================================== combat-v1 engine (combat_core.h)
    static bit validFighter(const EFighter& f)
    {
        return f.hp <= QDOJO_LIMIT_HP && f.stamina <= QDOJO_LIMIT_STAMINA && f.opening <= 1
            && f.guardStreak <= QDOJO_LIMIT_GUARD_STREAK && f.powerAvailable <= 1;
    }

    static bit isAttack(uint8 a)
    {
        return a == QDOJO_JAB || a == QDOJO_KICK || a == QDOJO_THROW;
    }

    static void initialFighter(EFighter& f)
    {
        f.hp = QDOJO_INITIAL_HP;
        f.stamina = QDOJO_INITIAL_STAMINA;
        f.opening = 0;
        f.guardStreak = 0;
        f.powerAvailable = 1;
    }

    static void newEState(EState& st)
    {
        initialFighter(st.a);
        initialFighter(st.b);
        st.roundIndex = 0;
        st.outcome = QDOJO_OUTCOME_NONE;
        st.winner = QDOJO_WINNER_NONE;
    }

    // BASE_COSTS = {6, 12, 4, 4, 9, 0, 0}
    static uint16 baseCost(uint8 a)
    {
        switch (a)
        {
        case QDOJO_JAB: return 6;
        case QDOJO_KICK: return 12;
        case QDOJO_BLOCK: return 4;
        case QDOJO_DUCK: return 4;
        case QDOJO_THROW: return 9;
        default: return 0;
        }
    }

    // DAMAGE[attacker][defender], before opening/power bonuses.
    static uint16 damage(uint8 att, uint8 def)
    {
        switch (att)
        {
        case QDOJO_JAB:
            return (def == QDOJO_JAB || def == QDOJO_KICK || def == QDOJO_THROW) ? 8
                : (def == QDOJO_RECOVER || def == QDOJO_EXHAUSTED) ? 12 : 0;
        case QDOJO_KICK:
            return (def == QDOJO_JAB || def == QDOJO_KICK || def == QDOJO_THROW) ? 14
                : (def == QDOJO_DUCK || def == QDOJO_RECOVER || def == QDOJO_EXHAUSTED) ? 18 : 0;
        case QDOJO_THROW:
            return def == QDOJO_BLOCK ? 14 : (def == QDOJO_RECOVER || def == QDOJO_EXHAUSTED) ? 18 : 0;
        default:
            return 0;
        }
    }

    // Full cost of an intended action from the pre-beat guard streak (step 1).
    static uint16 actionCost(uint8 intended, uint8 guardStreak, bit power)
    {
        return uint16(baseCost(intended) + (intended == QDOJO_BLOCK ? QDOJO_BLOCK_STREAK_COST * guardStreak : 0)
            + (power ? QDOJO_POWER_COST : 0));
    }

    // Plan validation against the round-start fighter (combat.md section 3).
    static bit validatePlan(const EPlan& p, const EFighter& start)
    {
        if (p.actions.get(0) >= QDOJO_SUBMITTED_ACTION_COUNT || p.actions.get(1) >= QDOJO_SUBMITTED_ACTION_COUNT
            || p.actions.get(2) >= QDOJO_SUBMITTED_ACTION_COUNT || p.actions.get(3) >= QDOJO_SUBMITTED_ACTION_COUNT
            || p.actions.get(4) >= QDOJO_SUBMITTED_ACTION_COUNT || p.actions.get(5) >= QDOJO_SUBMITTED_ACTION_COUNT)
        {
            return false;
        }
        if (p.powerSlot == QDOJO_NO_POWER_SLOT)
        {
            return true;
        }
        if (p.powerSlot >= QDOJO_BEATS_PER_ROUND)
        {
            return false;
        }
        if (!isAttack(p.actions.get(p.powerSlot)))
        {
            return false;
        }
        return start.powerAvailable == 1;
    }

    static void choose(const EFighter& f, uint8 intended, bit power, Half& h)
    {
        h.power = power ? 1 : 0;
        h.cost = actionCost(intended, f.guardStreak, power);
        if (f.stamina >= h.cost)
        {
            h.effective = intended;
            h.paid = h.cost;
        }
        else
        {
            h.effective = QDOJO_EXHAUSTED;
            h.paid = 0;
        }
    }

    // Steps 2-10 for one side (combat_core.h detail::finish, state part only).
    static void finishSide(Ctx& c, const EFighter& before, const Half& me, const Half& them, uint16 myDealt,
        uint16 incoming, EFighter& out)
    {
        out = before;
        if (me.power)
        {
            out.powerAvailable = 0;
        }
        out.stamina = uint16(out.stamina - me.paid);
        c.fs_lost = out.hp < incoming ? out.hp : incoming;
        out.hp = uint16(out.hp - c.fs_lost);
        if (me.effective == QDOJO_BLOCK && them.effective == QDOJO_KICK)
        {
            c.fs_strain = out.stamina < QDOJO_BLOCK_STRAIN ? out.stamina : QDOJO_BLOCK_STRAIN;
            out.stamina = uint16(out.stamina - c.fs_strain);
        }
        if (me.effective == QDOJO_RECOVER)
        {
            c.fs_gain = incoming == 0 ? QDOJO_RECOVER_UNHIT : QDOJO_RECOVER_HIT;
        }
        else if (me.effective == QDOJO_EXHAUSTED)
        {
            c.fs_gain = QDOJO_EXHAUSTED_RECOVERY;
        }
        else
        {
            c.fs_gain = QDOJO_ORDINARY_RECOVERY;
        }
        c.fs_st = uint16(out.stamina + c.fs_gain);
        out.stamina = c.fs_st < QDOJO_LIMIT_STAMINA ? c.fs_st : QDOJO_LIMIT_STAMINA;
        out.opening = ((me.effective == QDOJO_DUCK && (them.effective == QDOJO_JAB || them.effective == QDOJO_THROW))
                          || (me.effective == QDOJO_JAB && myDealt > 0 && incoming == 0))
            ? 1
            : 0;
        if (me.effective == QDOJO_BLOCK)
        {
            out.guardStreak = uint8(before.guardStreak + 1) > QDOJO_LIMIT_GUARD_STREAK ? QDOJO_LIMIT_GUARD_STREAK
                                                                                     : uint8(before.guardStreak + 1);
        }
        else
        {
            out.guardStreak = 0;
        }
    }

    // Resolves one beat from both pre-beat snapshots (combat.md section 6).
    // Results: c.eg_na, c.eg_nb, c.eg_terminal.
    static uint8 resolveBeat(Ctx& c, const EFighter& a, const EFighter& b, uint8 ia, uint8 ib, bit pa, bit pb)
    {
        if (!validFighter(a) || !validFighter(b))
        {
            return QDOJO_E_BAD_STATE;
        }
        if (ia >= QDOJO_SUBMITTED_ACTION_COUNT || ib >= QDOJO_SUBMITTED_ACTION_COUNT)
        {
            return QDOJO_E_BAD_ACTION;
        }
        if (pa && (!isAttack(ia) || a.powerAvailable != 1))
        {
            return QDOJO_E_BAD_ACTION;
        }
        if (pb && (!isAttack(ib) || b.powerAvailable != 1))
        {
            return QDOJO_E_BAD_ACTION;
        }
        choose(a, ia, pa, c.eg_ha);
        choose(b, ib, pb, c.eg_hb);
        c.eg_baseA = damage(c.eg_ha.effective, c.eg_hb.effective);
        c.eg_baseB = damage(c.eg_hb.effective, c.eg_ha.effective);
        c.eg_dealtA = 0;
        c.eg_dealtB = 0;
        if (c.eg_baseA > 0)
        {
            c.eg_dealtA = uint16(c.eg_baseA + (a.opening ? QDOJO_OPENING_DAMAGE : 0)
                + ((pa && c.eg_ha.effective == ia) ? QDOJO_POWER_DAMAGE : 0));
        }
        if (c.eg_baseB > 0)
        {
            c.eg_dealtB = uint16(c.eg_baseB + (b.opening ? QDOJO_OPENING_DAMAGE : 0)
                + ((pb && c.eg_hb.effective == ib) ? QDOJO_POWER_DAMAGE : 0));
        }
        finishSide(c, a, c.eg_ha, c.eg_hb, c.eg_dealtA, c.eg_dealtB, c.eg_na);
        finishSide(c, b, c.eg_hb, c.eg_ha, c.eg_dealtB, c.eg_dealtA, c.eg_nb);
        c.eg_terminal = (c.eg_na.hp == 0 || c.eg_nb.hp == 0) ? 1 : 0;
        return QDOJO_E_OK;
    }

    static void setOutcomeFromHp(EState& st, bit finalRound)
    {
        if (st.a.hp == 0 && st.b.hp == 0)
        {
            st.outcome = QDOJO_OUTCOME_DOUBLE_KO;
            st.winner = QDOJO_WINNER_NONE;
        }
        else if (st.a.hp == 0)
        {
            st.outcome = QDOJO_OUTCOME_KO;
            st.winner = QDOJO_WINNER_B;
        }
        else if (st.b.hp == 0)
        {
            st.outcome = QDOJO_OUTCOME_KO;
            st.winner = QDOJO_WINNER_A;
        }
        else if (finalRound)
        {
            if (st.a.hp == st.b.hp)
            {
                st.outcome = QDOJO_OUTCOME_HP_TIE;
                st.winner = QDOJO_WINNER_NONE;
            }
            else
            {
                st.outcome = QDOJO_OUTCOME_HP;
                st.winner = st.a.hp > st.b.hp ? QDOJO_WINNER_A : QDOJO_WINNER_B;
            }
        }
    }

    // Resolves one round (combat.md section 7). Results: c.eg_end, c.eg_executed.
    static uint8 resolveRound(Ctx& c, const EState& start, const EPlan& pa, const EPlan& pb)
    {
        if (!validFighter(start.a) || !validFighter(start.b) || start.roundIndex >= QDOJO_ROUNDS)
        {
            return QDOJO_E_BAD_STATE;
        }
        if (start.outcome != QDOJO_OUTCOME_NONE || start.a.hp == 0 || start.b.hp == 0)
        {
            return QDOJO_E_TERMINAL;
        }
        if (!validatePlan(pa, start.a))
        {
            return QDOJO_E_BAD_PLAN_A;
        }
        if (!validatePlan(pb, start.b))
        {
            return QDOJO_E_BAD_PLAN_B;
        }
        c.eg_s = start;
        c.eg_executed = 0;
        for (c.eg_beat = 0; c.eg_beat < QDOJO_BEATS_PER_ROUND; c.eg_beat++)
        {
            c.eg_err = resolveBeat(c, c.eg_s.a, c.eg_s.b, pa.actions.get(c.eg_beat), pb.actions.get(c.eg_beat),
                pa.powerSlot == c.eg_beat, pb.powerSlot == c.eg_beat);
            if (c.eg_err != QDOJO_E_OK)
            {
                return c.eg_err;  // unreachable after validation
            }
            c.eg_s.a = c.eg_na;
            c.eg_s.b = c.eg_nb;
            c.eg_executed = uint8(c.eg_beat + 1);
            if (c.eg_terminal)
            {
                setOutcomeFromHp(c.eg_s, false);
                c.eg_end = c.eg_s;
                return QDOJO_E_OK;
            }
        }
        if (c.eg_s.roundIndex == QDOJO_ROUNDS - 1)
        {
            setOutcomeFromHp(c.eg_s, true);
            c.eg_end = c.eg_s;
            return QDOJO_E_OK;
        }
        // Inter-round recovery: +BREAK_RECOVERY stamina (capped), next round.
        c.eg_s.a.stamina = uint16(c.eg_s.a.stamina + QDOJO_BREAK_RECOVERY) < QDOJO_LIMIT_STAMINA
            ? uint16(c.eg_s.a.stamina + QDOJO_BREAK_RECOVERY)
            : QDOJO_LIMIT_STAMINA;
        c.eg_s.b.stamina = uint16(c.eg_s.b.stamina + QDOJO_BREAK_RECOVERY) < QDOJO_LIMIT_STAMINA
            ? uint16(c.eg_s.b.stamina + QDOJO_BREAK_RECOVERY)
            : QDOJO_LIMIT_STAMINA;
        c.eg_s.roundIndex = uint8(c.eg_s.roundIndex + 1);
        c.eg_end = c.eg_s;
        return QDOJO_E_OK;
    }

    // =========================================================== fight digests (sha256.h)
    static void shaParticipant(Sha256& h, const Participant& p)
    {
        shaId(h, p.fighterId);
        shaId(h, p.owner);
        shaId(h, p.op);
        shaLe(h, p.authVersion, 4);
        shaId(h, p.payout);
        shaLe(h, p.lifetime, 2);
        shaLe(h, p.seasonRating, 2);
    }

    // context_digest = SHA256("qdojo/combat/context/v1\0" || context_bytes), 526 context bytes.
    static id contextDigest(const StateData& s, Ctx& c, const Contest& con, uint64 fightId, uint64 t, uint32 ti,
        uint32 fe)
    {
        shaInit(c.sha);
        shaTag(c.sha, QDOJO_TAG_CONTEXT_0, QDOJO_TAG_CONTEXT_1, QDOJO_TAG_CONTEXT_2, QDOJO_TAG_CONTEXT_3,
            QDOJO_TAG_CONTEXT_LEN);
        shaId(c.sha, s.m.networkId);
        shaId(c.sha, s.m.contractId);
        shaLe(c.sha, con.contestId, 8);
        shaLe(c.sha, fightId, 8);
        shaLe(c.sha, con.mode, 1);
        shaLe(c.sha, con.fmt, 1);
        shaLe(c.sha, con.cupId, 8);
        shaLe(c.sha, con.season, 4);
        shaLe(c.sha, t, 8);
        shaId(c.sha, s.m.rulesetDigest);
        shaLe(c.sha, s.m.timing.get(ti).commitTicks, 2);
        shaLe(c.sha, s.m.timing.get(ti).revealTicks, 2);
        shaLe(c.sha, s.m.fees.get(fe).profileId, 4);
        shaLe(c.sha, uint64(con.stake), 8);
        shaLe(c.sha, s.m.fees.get(fe).rakeBps, 2);
        shaLe(c.sha, s.m.fees.get(fe).houseBps, 2);
        shaLe(c.sha, s.m.fees.get(fe).devBps, 2);
        shaLe(c.sha, s.m.fees.get(fe).shareBps, 2);
        shaId(c.sha, s.m.fees.get(fe).house);
        shaId(c.sha, s.m.fees.get(fe).dev);
        shaId(c.sha, s.m.fees.get(fe).share);
        shaParticipant(c.sha, con.a);
        shaParticipant(c.sha, con.b);
        return shaFinal(c.sha);
    }

    static void shaEFighter(Sha256& h, const EFighter& f)
    {
        shaLe(h, f.hp, 2);
        shaLe(h, f.stamina, 2);
        shaByte(h, f.opening);
        shaByte(h, f.guardStreak);
        shaByte(h, f.powerAvailable);
        shaByte(h, 0);
    }

    // round_state_digest = SHA256("qdojo/combat/state/v1\0" || context_digest || round_index u8 || state_A || state_B)
    static id roundStateDigest(Ctx& c, const id& ctxDigest, const EState& st)
    {
        shaInit(c.sha);
        shaTag(c.sha, QDOJO_TAG_STATE_0, QDOJO_TAG_STATE_1, QDOJO_TAG_STATE_2, QDOJO_TAG_STATE_3, QDOJO_TAG_STATE_LEN);
        shaId(c.sha, ctxDigest);
        shaByte(c.sha, st.roundIndex);
        shaEFighter(c.sha, st.a);
        shaEFighter(c.sha, st.b);
        return shaFinal(c.sha);
    }

    // =========================================================== fights and contests
    // new_fight: the contest `con` is the caller's working copy; the caller stores it.
    static void newFight(StateData& s, Ctx& c, Contest& con, uint64 t)
    {
        c.nf_fid = s.nextFight;
        s.nextFight += 1;
        c.nf_ti = timingIdx(s, c, con.timingId);
        c.nf_fe = feeIdx(s, c, con.feeId);
        c.nf_slot = newFightSlot(s, c);
        if (c.nf_slot < 0 || c.nf_ti < 0 || c.nf_fe < 0)
        {
            return;  // counted in faults; admission capacities prevent it
        }
        setMemory(c.nf_f, 0);
        c.nf_f.used = 1;
        c.nf_f.fightId = c.nf_fid;
        c.nf_f.contestId = con.contestId;
        c.nf_f.phase = QDOJO_P_COMMIT;
        c.nf_f.commitTicks = s.m.timing.get(c.nf_ti).commitTicks;
        c.nf_f.revealTicks = s.m.timing.get(c.nf_ti).revealTicks;
        c.nf_f.startTick = t;
        c.nf_f.commitLast = addU64(s, t, c.nf_f.commitTicks);
        c.nf_f.revealLast = addU64(s, c.nf_f.commitLast, c.nf_f.revealTicks);
        c.nf_f.contextDigest = contextDigest(s, c, con, c.nf_fid, t, uint32(c.nf_ti), uint32(c.nf_fe));
        newEState(c.nf_f.st);
        c.nf_f.roundStateDigest = roundStateDigest(c, c.nf_f.contextDigest, c.nf_f.st);
        s.fights.set(c.nf_slot, c.nf_f);
        con.currentFight = c.nf_fid;
        bReset(c);
        bU64(c, c.nf_fid);
        bU64(c, con.contestId);
        bU64(c, t);
        bU64(c, c.nf_f.commitLast);
        bU64(c, c.nf_f.revealLast);
        emit(s, c, QDOJO_EV_FIGHT_CREATED);
    }

    static void participantOf(const StateData& s, const Offer& o, uint32 season, Participant& p)
    {
        p.fighterId = o.fighterId;
        p.owner = o.owner;
        p.op = o.op;
        p.authVersion = o.authVersion;
        p.payout = o.payout;
        p.lifetime = s.fighters.get(o.fighterIdx).lifetime;
        p.seasonRating = ratingIn(s.fighters.get(o.fighterIdx), season);
    }

    static void seriesOf(uint8 fmt, Series& se)
    {
        setMemory(se, 0);
        if (fmt == QDOJO_F_BO3)
        {
            se.need = 2;
            se.cap = 5;
        }
        else if (fmt == QDOJO_F_BO5)
        {
            se.need = 3;
            se.cap = 7;
        }
        else
        {
            se.need = 1;
            se.cap = 1;
        }
    }

    static bit seriesDone(const Series& se)
    {
        return se.winsA >= se.need || se.winsB >= se.need || se.fights >= se.cap;
    }

    static uint8 seriesWinner(const Series& se)
    {
        if (!seriesDone(se) || se.winsA == se.winsB)
        {
            return QDOJO_S_NONE;
        }
        return se.winsA > se.winsB ? QDOJO_S_A : QDOJO_S_B;
    }

    static void lockFighter(StateData& s, Ctx& c, uint32 fi, uint8 lock, uint64 ref)
    {
        c.lf_f = s.fighters.get(fi);
        c.lf_f.lock = lock;
        c.lf_f.lockRef = ref;
        s.fighters.set(fi, c.lf_f);
    }

    // Release fighter fi's lock if it is `lock` held for `ref`.
    static void releaseFighter(StateData& s, Ctx& c, uint32 fi, uint8 lock, uint64 ref)
    {
        if (s.fighters.get(fi).lock == lock && s.fighters.get(fi).lockRef == ref)
        {
            lockFighter(s, c, fi, QDOJO_L_IDLE, 0);
        }
    }

    // contract.py _start_contest. The offer snapshots are c.sc_x and c.sc_y; offers
    // with a nonzero id have their escrow moved into the contest pot.
    static sint32 startContest(StateData& s, Ctx& c, uint8 mode, uint8 fmt, uint64 t, bit hasKey, sint64 keyEpoch,
        uint64 cupId, uint64 pairingId)
    {
        if (idCmp(c.sc_x.fighterId, c.sc_y.fighterId) > 0)
        {
            c.sc_tmp = c.sc_x;
            c.sc_x = c.sc_y;
            c.sc_y = c.sc_tmp;
        }
        c.sc_season = mode == QDOJO_M_RANKED ? seasonOf(s, t) : 0;
        c.sc_cid = s.nextContest;
        s.nextContest += 1;
        c.sc_slot = newContestSlot(s, c);
        if (c.sc_slot < 0)
        {
            return -1;
        }
        setMemory(c.sc_con, 0);
        c.sc_con.used = 1;
        c.sc_con.contestId = c.sc_cid;
        c.sc_con.mode = mode;
        c.sc_con.fmt = fmt;
        c.sc_con.status = QDOJO_C_ACTIVE;
        participantOf(s, c.sc_x, c.sc_season, c.sc_con.a);
        participantOf(s, c.sc_y, c.sc_season, c.sc_con.b);
        c.sc_con.aIdx = c.sc_x.fighterIdx;
        c.sc_con.bIdx = c.sc_y.fighterIdx;
        c.sc_con.payerA = c.sc_x.payer;
        c.sc_con.payerB = c.sc_y.payer;
        c.sc_con.stake = c.sc_x.amount;
        c.sc_con.feeId = c.sc_x.feeId;
        c.sc_con.timingId = c.sc_x.timingId;
        c.sc_con.generation = s.generation;
        c.sc_con.startTick = t;
        c.sc_con.season = c.sc_season;
        seriesOf(fmt, c.sc_con.series);
        c.sc_con.cupId = cupId;
        c.sc_con.pairingId = pairingId;
        c.sc_con.hasStartsKey = hasKey ? 1 : 0;
        c.sc_con.startsEpoch = keyEpoch;
        if (c.sc_x.offerId && c.sc_y.offerId)
        {
            c.sc_con.hasPot = 1;
            c.sc_sx = offerSlot(s, c, c.sc_x.offerId);
            c.sc_sy = offerSlot(s, c, c.sc_y.offerId);
            if (c.sc_sx >= 0 && s.offers.get(c.sc_sx).escrowed)
            {
                c.sc_o = s.offers.get(c.sc_sx);
                c.sc_o.escrowed = 0;
                c.sc_o.contestId = c.sc_cid;
                s.offers.set(c.sc_sx, c.sc_o);
                c.sc_con.potA = c.sc_o.amount;
            }
            if (c.sc_sy >= 0 && s.offers.get(c.sc_sy).escrowed)
            {
                c.sc_o = s.offers.get(c.sc_sy);
                c.sc_o.escrowed = 0;
                c.sc_o.contestId = c.sc_cid;
                s.offers.set(c.sc_sy, c.sc_o);
                c.sc_con.potB = c.sc_o.amount;
            }
        }
        if (mode != QDOJO_M_CUP)
        {
            lockFighter(s, c, c.sc_x.fighterIdx, QDOJO_L_CONTEST, c.sc_cid);
            lockFighter(s, c, c.sc_y.fighterIdx, QDOJO_L_CONTEST, c.sc_cid);
        }
        s.contests.set(c.sc_slot, c.sc_con);
        newFight(s, c, c.sc_con, t);
        s.contests.set(c.sc_slot, c.sc_con);
        return c.sc_slot;
    }

    // =========================================================== settlement
    static void fault(StateData& s, Ctx& c, uint32 fi, uint64 t)
    {
        c.fa_e = epochOf(s, t);
        c.fa_f = s.fighters.get(fi);
        if (c.fa_f.faultEpoch != c.fa_e)
        {
            c.fa_f.faultEpoch = c.fa_e;
            c.fa_f.faultCount = 0;
        }
        c.fa_f.faultCount += 1;
        c.fa_until = addU64(s, t, s.m.cooldownTicks);
        if (c.fa_until > c.fa_f.cooldownUntil)
        {
            c.fa_f.cooldownUntil = c.fa_until;
        }
        if (c.fa_f.faultCount >= s.m.faultsPerEpoch)
        {
            c.fa_f.suspendedEpoch = c.fa_e;
        }
        s.fighters.set(fi, c.fa_f);
        bReset(c);
        bId(c, c.fa_f.fighterId);
        bU64(c, c.fa_f.faultCount);
        emit(s, c, QDOJO_EV_FAULT);
    }

    // rating.py delta: zero-sum from both OLD ratings.
    static sint64 ratingDelta(Ctx& c, sint64 ra, sint64 rb, sint64 scoreA)
    {
        c.rd_exp = 1000 + 2 * (ra - rb);
        if (c.rd_exp < 100)
        {
            c.rd_exp = 100;
        }
        if (c.rd_exp > 1900)
        {
            c.rd_exp = 1900;
        }
        c.rd_raw = 32 * (scoreA - c.rd_exp);
        c.rd_mag = div<sint64>(c.rd_raw < 0 ? -c.rd_raw : c.rd_raw, sint64(2000));
        c.rd_d = c.rd_raw > 0 ? c.rd_mag : c.rd_raw < 0 ? -c.rd_mag : 0;
        if (c.rd_d > 0)
        {
            if (c.rd_d > rb)
            {
                c.rd_d = rb;
            }
            if (c.rd_d > QDOJO_RATING_CEILING - ra)
            {
                c.rd_d = QDOJO_RATING_CEILING - ra;
            }
        }
        else if (c.rd_d < 0)
        {
            c.rd_m = -c.rd_d;
            if (c.rd_m > ra)
            {
                c.rd_m = ra;
            }
            if (c.rd_m > QDOJO_RATING_CEILING - rb)
            {
                c.rd_m = QDOJO_RATING_CEILING - rb;
            }
            c.rd_d = -c.rd_m;
        }
        return c.rd_d;
    }

    static void addOpponent(Ctx& c, SeasonSlot& sl, uint16 opp)
    {
        for (c.ao_i = 0; c.ao_i < 4; c.ao_i++)
        {
            if (c.ao_i < sl.opponents && sl.opponentIdx.get(c.ao_i) == opp)
            {
                return;
            }
        }
        if (sl.opponents < 4)
        {
            sl.opponentIdx.set(sl.opponents, opp);
            sl.opponents = uint8(sl.opponents + 1);
        }
    }

    static void addDefeated(SeasonSlot& sl, uint16 opp)
    {
        if (!(sl.defeatedBits.get(opp >> 6) & (1ULL << (opp & 63))))
        {
            sl.defeatedBits.set(opp >> 6, sl.defeatedBits.get(opp >> 6) | (1ULL << (opp & 63)));
            sl.defeated = uint16(sl.defeated + 1);
        }
    }

    // One side of rate(): record, placement and season stats of `me` (a working copy).
    static void rateSide(const StateData& s, Ctx& c, Fighter& me, uint16 oppIdx, uint8 mine, uint8 winner, bit combat,
        uint32 se, uint64 startTick)
    {
        if (combat)
        {
            me.placement += 1;
            if (winner == mine)
            {
                me.recW += 1;
            }
            else if (winner == QDOJO_S_NONE)
            {
                me.recD += 1;
            }
            else
            {
                me.recL += 1;
            }
        }
        else
        {
            if (winner == mine)
            {
                me.recFW += 1;
            }
            else
            {
                me.recFL += 1;
            }
        }
        if (se && combat)
        {
            seasonClaim(me, se, c.rs_sl);
            c.rs_sl.hasStats = 1;
            c.rs_sl.fights += 1;
            addOpponent(c, c.rs_sl, oppIdx);
            if (winner == mine)
            {
                c.rs_sl.wins += 1;
                addDefeated(c.rs_sl, oppIdx);
            }
            if (epochOf(s, startTick) == s.m.seasonStartEpoch + sint64(se) * s.m.seasonEpochs - 1)
            {
                c.rs_sl.finalEpochFights += 1;
            }
            me.seasons.set(mod<uint32>(se, 2U), c.rs_sl);
        }
    }

    // rating.py update, plus records and season stats; RATING event.
    static void rate(StateData& s, Ctx& c, const Contest& con, uint8 kind, uint8 winner)
    {
        if (kind != QDOJO_R_COMBAT && kind != QDOJO_R_FORFEIT)
        {
            return;
        }
        c.rt_fa = s.fighters.get(con.aIdx);
        c.rt_fb = s.fighters.get(con.bIdx);
        c.rt_score = winner == QDOJO_S_NONE ? QDOJO_SCORE_DRAW : winner == QDOJO_S_A ? QDOJO_SCORE_WIN : QDOJO_SCORE_LOSS;
        c.rt_d = ratingDelta(c, con.a.lifetime, con.b.lifetime, c.rt_score);
        c.rt_fa.lifetime = uint16(con.a.lifetime + c.rt_d);
        c.rt_fb.lifetime = uint16(con.b.lifetime - c.rt_d);
        if (con.season)
        {
            c.rt_d = ratingDelta(c, con.a.seasonRating, con.b.seasonRating, c.rt_score);
            seasonClaim(c.rt_fa, con.season, c.rt_sl);
            c.rt_sl.rating = uint16(con.a.seasonRating + c.rt_d);
            c.rt_sl.hasRating = 1;
            c.rt_fa.seasons.set(mod<uint32>(con.season, 2U), c.rt_sl);
            seasonClaim(c.rt_fb, con.season, c.rt_sl);
            c.rt_sl.rating = uint16(con.b.seasonRating - c.rt_d);
            c.rt_sl.hasRating = 1;
            c.rt_fb.seasons.set(mod<uint32>(con.season, 2U), c.rt_sl);
        }
        rateSide(s, c, c.rt_fa, con.bIdx, QDOJO_S_A, winner, kind == QDOJO_R_COMBAT, con.season, con.startTick);
        rateSide(s, c, c.rt_fb, con.aIdx, QDOJO_S_B, winner, kind == QDOJO_R_COMBAT, con.season, con.startTick);
        s.fighters.set(con.aIdx, c.rt_fa);
        s.fighters.set(con.bIdx, c.rt_fb);
        bReset(c);
        bId(c, c.rt_fa.fighterId);
        bU64(c, c.rt_fa.lifetime);
        bId(c, c.rt_fb.fighterId);
        bU64(c, c.rt_fb.lifetime);
        emit(s, c, QDOJO_EV_RATING);
    }

    static void settleWin(StateData& s, Ctx& c, Contest& con, const id& winner, uint32 fe)
    {
        c.sw_fp = s.m.fees.get(fe);
        c.sw_gross = addI64(s, con.potA, con.potB);
        c.sw_rake = div<sint64>(mulI64(s, c.sw_gross, sint64(c.sw_fp.rakeBps)), QDOJO_BPS);
        c.sw_dev = div<sint64>(mulI64(s, c.sw_rake, sint64(c.sw_fp.devBps)), QDOJO_BPS);
        c.sw_share = div<sint64>(mulI64(s, c.sw_rake, sint64(c.sw_fp.shareBps)), QDOJO_BPS);
        con.hasPot = 0;
        con.potA = 0;
        con.potB = 0;
        credit(s, c, winner, subI64(s, c.sw_gross, c.sw_rake));
        credit(s, c, c.sw_fp.house, subI64(s, subI64(s, c.sw_rake, c.sw_dev), c.sw_share));
        credit(s, c, c.sw_fp.dev, c.sw_dev);
        credit(s, c, c.sw_fp.share, c.sw_share);
    }

    static void settleRefund(StateData& s, Ctx& c, Contest& con)
    {
        if (!con.hasPot)
        {
            return;
        }
        c.sr_a = con.potA;
        c.sr_b = con.potB;
        con.hasPot = 0;
        con.potA = 0;
        con.potB = 0;
        credit(s, c, con.payerA, c.sr_a);
        credit(s, c, con.payerB, c.sr_b);
    }

    // `con` is the caller's working copy; the caller stores it afterwards.
    static void finishContest(StateData& s, Ctx& c, Contest& con, uint64 t, uint8 kind, uint8 winner)
    {
        con.status = QDOJO_C_DONE;
        con.resultKind = kind;
        con.resultWinner = winner;
        if (kind == QDOJO_R_DOUBLE_FAULT)
        {
            fault(s, c, con.aIdx, t);
            fault(s, c, con.bIdx, t);
        }
        else if (kind == QDOJO_R_FORFEIT)
        {
            fault(s, c, winner == QDOJO_S_A ? con.bIdx : con.aIdx, t);
        }
        if (con.mode == QDOJO_M_RANKED || con.mode == QDOJO_M_DUEL)
        {
            c.fc_fe = feeIdx(s, c, con.feeId);
            if ((kind == QDOJO_R_COMBAT || kind == QDOJO_R_FORFEIT) && winner != QDOJO_S_NONE && c.fc_fe >= 0)
            {
                settleWin(s, c, con, winner == QDOJO_S_A ? con.a.payout : con.b.payout, uint32(c.fc_fe));
            }
            else
            {
                settleRefund(s, c, con);
            }
        }
        if (con.mode == QDOJO_M_RANKED)
        {
            rate(s, c, con, kind, winner);
            c.fc_p = pairFind(s, c, con.aIdx, con.bIdx, true, epochOf(s, t), t);
            if (c.fc_p >= 0)
            {
                c.fc_pr = s.pairs.get(c.fc_p);
                c.fc_pr.last = t;
                c.fc_pr.hasLast = 1;
                s.pairs.set(c.fc_p, c.fc_pr);
            }
        }
        if (con.mode != QDOJO_M_CUP)
        {
            releaseFighter(s, c, con.aIdx, QDOJO_L_CONTEST, con.contestId);
            releaseFighter(s, c, con.bIdx, QDOJO_L_CONTEST, con.contestId);
        }
        bReset(c);
        bU64(c, con.contestId);
        bStr(c, kindStr(kind));
        bStr(c, sideStr(winner));
        emit(s, c, QDOJO_EV_CONTEST_SETTLED);
        if (con.mode == QDOJO_M_CUP)
        {
            cupPairingDone(s, c, con, t);
        }
    }

    // Objective service void: refund, no rating, no fault; reverse the pair start once.
    static void voidContest(StateData& s, Ctx& c, Contest& con, uint64 t)
    {
        c.vc_fs = fightSlot(s, c, con.currentFight);
        if (c.vc_fs >= 0 && s.fights.get(c.vc_fs).phase != QDOJO_P_DONE)
        {
            c.vc_f = s.fights.get(c.vc_fs);
            c.vc_f.phase = QDOJO_P_DONE;
            c.vc_f.resultKind = QDOJO_R_VOID;
            c.vc_f.resultWinner = QDOJO_S_NONE;
            s.fights.set(c.vc_fs, c.vc_f);
        }
        con.status = QDOJO_C_DONE;
        con.resultKind = QDOJO_R_VOID;
        con.resultWinner = QDOJO_S_NONE;
        if (con.mode == QDOJO_M_RANKED || con.mode == QDOJO_M_DUEL)
        {
            settleRefund(s, c, con);
        }
        if (con.hasStartsKey)
        {
            c.vc_p = pairFind(s, c, con.aIdx, con.bIdx, false, epochOf(s, t), t);
            if (c.vc_p >= 0 && s.pairs.get(c.vc_p).epoch == con.startsEpoch && s.pairs.get(c.vc_p).starts > 0)
            {
                c.vc_pr = s.pairs.get(c.vc_p);
                c.vc_pr.starts -= 1;
                s.pairs.set(c.vc_p, c.vc_pr);
            }
        }
        releaseFighter(s, c, con.aIdx, QDOJO_L_CONTEST, con.contestId);
        releaseFighter(s, c, con.bIdx, QDOJO_L_CONTEST, con.contestId);
        bReset(c);
        bU64(c, con.contestId);
        bStr(c, QDOJO_STR_VOID);
        bStr(c, QDOJO_STR_DASH);
        emit(s, c, QDOJO_EV_CONTEST_SETTLED);
    }

    // `f` is the caller's working copy of fight slot fs. It is stored here,
    // before anything can evict the slot; the caller must not store it again.
    static void endFight(StateData& s, Ctx& c, uint32 fs, Fight& f, uint64 t, uint8 kind, uint8 winner)
    {
        f.phase = QDOJO_P_DONE;
        f.resultKind = kind;
        f.resultWinner = winner;
        s.fights.set(fs, f);
        bReset(c);
        bU64(c, f.fightId);
        bStr(c, kindStr(kind));
        bStr(c, sideStr(winner));
        emit(s, c, QDOJO_EV_FIGHT_ENDED);
        c.ef_cs = contestSlot(s, c, f.contestId);
        if (c.ef_cs < 0)
        {
            s.faults.slotOverflow += 1;
            return;
        }
        c.ef_con = s.contests.get(c.ef_cs);
        if (kind == QDOJO_R_COMBAT)
        {
            if (c.ef_con.mode == QDOJO_M_CUP)
            {
                c.ef_k = cupSlot(s, c, c.ef_con.cupId);
                if (c.ef_k >= 0)
                {
                    c.cupA = s.cups.get(c.ef_k);
                    c.cupA.combatFights += 1;
                    s.cups.set(c.ef_k, c.cupA);
                }
            }
            c.ef_con.series.fights = uint8(c.ef_con.series.fights + 1);
            if (winner == QDOJO_S_A)
            {
                c.ef_con.series.winsA = uint8(c.ef_con.series.winsA + 1);
            }
            else if (winner == QDOJO_S_B)
            {
                c.ef_con.series.winsB = uint8(c.ef_con.series.winsB + 1);
            }
            if (!seriesDone(c.ef_con.series))
            {
                newFight(s, c, c.ef_con, t);
                s.contests.set(c.ef_cs, c.ef_con);
                return;
            }
            finishContest(s, c, c.ef_con, t, QDOJO_R_COMBAT, seriesWinner(c.ef_con.series));
        }
        else
        {
            finishContest(s, c, c.ef_con, t, kind, winner);
        }
        s.contests.set(c.ef_cs, c.ef_con);
    }

    // `f` is the caller's working copy of fight slot fs.
    static void resolve(StateData& s, Ctx& c, uint32 fs, Fight& f, uint64 t)
    {
        if (resolveRound(c, f.st, f.plan.get(0), f.plan.get(1)) != QDOJO_E_OK)
        {
            s.faults.engine += 1;  // unreachable: both plans were validated at reveal
            return;
        }
        bReset(c);
        bU64(c, f.fightId);
        bU64(c, f.st.roundIndex);
        bU64(c, c.eg_executed);
        bByte(c, 1);
        bByte(c, 16);
        bByte(c, 0);
        bState(c, c.eg_end.a);
        bState(c, c.eg_end.b);
        emit(s, c, QDOJO_EV_ROUND_RESOLVED);
        f.st = c.eg_end;
        f.committed.set(0, 0);
        f.committed.set(1, 0);
        f.revealed.set(0, 0);
        f.revealed.set(1, 0);
        if (c.eg_end.outcome != QDOJO_OUTCOME_NONE)
        {
            endFight(s, c, fs, f, t, QDOJO_R_COMBAT,
                c.eg_end.winner == QDOJO_WINNER_A ? QDOJO_S_A : c.eg_end.winner == QDOJO_WINNER_B ? QDOJO_S_B : QDOJO_S_NONE);
            return;
        }
        f.phase = QDOJO_P_COMMIT;
        f.startTick = t;
        f.commitLast = addU64(s, t, f.commitTicks);
        f.revealLast = addU64(s, f.commitLast, f.revealTicks);
        f.roundStateDigest = roundStateDigest(c, f.contextDigest, f.st);
        s.fights.set(fs, f);
    }

    static void fightTick(StateData& s, Ctx& c, uint32 fs, uint64 t)
    {
        c.ft_f = s.fights.get(fs);
        if (c.ft_f.phase == QDOJO_P_COMMIT && t == c.ft_f.commitLast)
        {
            if (c.ft_f.committed.get(0) && c.ft_f.committed.get(1))
            {
                c.ft_f.phase = QDOJO_P_REVEAL;
                s.fights.set(fs, c.ft_f);
            }
            else if (c.ft_f.committed.get(0) || c.ft_f.committed.get(1))
            {
                endFight(s, c, fs, c.ft_f, t, QDOJO_R_FORFEIT, c.ft_f.committed.get(0) ? QDOJO_S_A : QDOJO_S_B);
            }
            else
            {
                endFight(s, c, fs, c.ft_f, t, QDOJO_R_DOUBLE_FAULT, QDOJO_S_NONE);
            }
            return;
        }
        if (c.ft_f.phase != QDOJO_P_REVEAL)
        {
            return;
        }
        if (c.ft_f.revealed.get(0) && c.ft_f.revealed.get(1))
        {
            resolve(s, c, fs, c.ft_f, t);
        }
        else if (t == c.ft_f.revealLast)
        {
            if (c.ft_f.revealed.get(0) || c.ft_f.revealed.get(1))
            {
                endFight(s, c, fs, c.ft_f, t, QDOJO_R_FORFEIT, c.ft_f.revealed.get(0) ? QDOJO_S_A : QDOJO_S_B);
            }
            else
            {
                endFight(s, c, fs, c.ft_f, t, QDOJO_R_DOUBLE_FAULT, QDOJO_S_NONE);
            }
        }
    }

    // =========================================================== cups
    // Cup helpers take the cup by reference: the caller's working copy, which
    // the caller stores back into s.cups. scheduleLevel stores it before it
    // reads fightsInUse, which counts every running cup's reservation.
    static bit cupHasEntry(const Cup& cup, Ctx& c, const id& fid)
    {
        for (c.ch_i = 0; c.ch_i < QDOJO_CAP_CUP_ENTRANTS; c.ch_i++)
        {
            if (c.ch_i < cup.nEntries && cup.entries.get(c.ch_i).fighterId == fid)
            {
                return true;
            }
        }
        return false;
    }

    static bit cupInSlots(const Cup& cup, Ctx& c, const id& fid)
    {
        for (c.ci_i = 0; c.ci_i < QDOJO_CAP_CUP_ENTRANTS; c.ci_i++)
        {
            if (c.ci_i < cup.nSlots && cup.slotUsed.get(c.ci_i) && cup.slots.get(c.ci_i) == fid)
            {
                return true;
            }
        }
        return false;
    }

    static bit aliveInCup(const Cup& cup, Ctx& c, const id& fid)
    {
        if (cup.status == QDOJO_CUP_REGISTRATION)
        {
            return cupHasEntry(cup, c, fid);
        }
        return cupInSlots(cup, c, fid);
    }

    static bit represented(const StateData& s, Ctx& c, const Cup& cup, const id& owner, const id& op, bit hasExclude,
        const id& exclude)
    {
        for (c.rp_i = 0; c.rp_i < QDOJO_CAP_CUP_ENTRANTS; c.rp_i++)
        {
            if (c.rp_i >= cup.nEntries)
            {
                break;
            }
            if ((hasExclude && cup.entries.get(c.rp_i).fighterId == exclude)
                || !aliveInCup(cup, c, cup.entries.get(c.rp_i).fighterId))
            {
                continue;
            }
            c.rp_fi = cup.entries.get(c.rp_i).fighterIdx;
            if (owner == s.fighters.get(c.rp_fi).owner || owner == s.fighters.get(c.rp_fi).op
                || op == s.fighters.get(c.rp_fi).owner || op == s.fighters.get(c.rp_fi).op)
            {
                return true;
            }
        }
        return false;
    }

    static bit betweenPairings(const Cup& cup, Ctx& c, const id& fid)
    {
        if (cup.status == QDOJO_CUP_REGISTRATION)
        {
            return true;
        }
        for (c.bp_i = 0; c.bp_i < QDOJO_CAP_PAIRINGS; c.bp_i++)
        {
            if (c.bp_i >= cup.nPairings)
            {
                break;
            }
            c.bp_isA = cup.pairings.get(c.bp_i).hasA && cup.pairings.get(c.bp_i).a == fid;
            c.bp_isB = cup.pairings.get(c.bp_i).hasB && cup.pairings.get(c.bp_i).b == fid;
            if (!c.bp_isA && !c.bp_isB)
            {
                continue;
            }
            if (cup.pairings.get(c.bp_i).status == QDOJO_PS_PLAYING || cup.pairings.get(c.bp_i).status == QDOJO_PS_REPLAY_WAIT)
            {
                return false;
            }
            if (cup.pairings.get(c.bp_i).status == QDOJO_PS_SCHEDULED
                && ((c.bp_isA && cup.pairings.get(c.bp_i).checkedA) || (c.bp_isB && cup.pairings.get(c.bp_i).checkedB)))
            {
                return false;
            }
        }
        return true;
    }

    static void releaseCupLocks(StateData& s, Ctx& c, const Cup& cup)
    {
        for (c.rl_i = 0; c.rl_i < QDOJO_CAP_CUP_ENTRANTS; c.rl_i++)
        {
            if (c.rl_i >= cup.nEntries)
            {
                break;
            }
            releaseFighter(s, c, cup.entries.get(c.rl_i).fighterIdx, QDOJO_L_TOURNAMENT, cup.cupId);
        }
    }

    static void refundCup(StateData& s, Ctx& c, Cup& cup)
    {
        if (!cup.hasPot)
        {
            return;
        }
        cup.hasPot = 0;
        credit(s, c, cup.sponsor, cup.sponsorship);
        for (c.rc_i = 0; c.rc_i < QDOJO_CAP_CUP_ENTRANTS; c.rc_i++)
        {
            if (c.rc_i >= cup.nEntries)
            {
                break;
            }
            credit(s, c, cup.entries.get(c.rc_i).payer, cup.entries.get(c.rc_i).amount);
        }
    }

    // CUP_FINISHED body: cup_id, what, [champion], [why]. why == 0 means absent.
    static void finishedEvent(StateData& s, Ctx& c, const Cup& cup, uint8 what, bit hasChampion, const id& champion,
        uint8 why)
    {
        bReset(c);
        bU64(c, cup.cupId);
        bStr(c, what);
        if (hasChampion)
        {
            bId(c, champion);
        }
        if (why)
        {
            bStr(c, why);
        }
        emit(s, c, QDOJO_EV_CUP_FINISHED);
    }

    // Whole-event abort: every entry and the sponsorship go back, no rake, no trophy.
    static void abortCup(StateData& s, Ctx& c, Cup& cup, uint8 why)
    {
        for (c.ab_i = 0; c.ab_i < QDOJO_CAP_CONTEST_SLOTS; c.ab_i++)
        {
            if (!s.contests.get(c.ab_i).used || s.contests.get(c.ab_i).cupId != cup.cupId
                || s.contests.get(c.ab_i).status != QDOJO_C_ACTIVE)
            {
                continue;
            }
            c.ab_con = s.contests.get(c.ab_i);
            c.ab_fs = fightSlot(s, c, c.ab_con.currentFight);
            if (c.ab_fs >= 0 && s.fights.get(c.ab_fs).phase != QDOJO_P_DONE)
            {
                c.ab_f = s.fights.get(c.ab_fs);
                c.ab_f.phase = QDOJO_P_DONE;
                c.ab_f.resultKind = QDOJO_R_VOID;
                c.ab_f.resultWinner = QDOJO_S_NONE;
                s.fights.set(c.ab_fs, c.ab_f);
            }
            c.ab_con.status = QDOJO_C_DONE;
            c.ab_con.resultKind = QDOJO_R_VOID;
            c.ab_con.resultWinner = QDOJO_S_NONE;
            s.contests.set(c.ab_i, c.ab_con);
        }
        refundCup(s, c, cup);
        cup.status = QDOJO_CUP_ABORTED;
        cup.reserved = 0;
        releaseCupLocks(s, c, cup);
        finishedEvent(s, c, cup, QDOJO_STR_ABORTED, false, NULL_ID, abortStr(why));
    }

    static void cupLevelEvent(StateData& s, Ctx& c, const Cup& cup, uint64 postponed)
    {
        bReset(c);
        bU64(c, cup.cupId);
        bU64(c, cup.level);
        bU64(c, cup.levelStart);
        bU64(c, postponed);
        emit(s, c, QDOJO_EV_CUP_LEVEL);
    }

    static void scheduleLevel(StateData& s, Ctx& c, Cup& cup, uint32 k)
    {
        c.sl_need = 0;
        for (c.sl_i = 0; c.sl_i + 1 < QDOJO_CAP_CUP_ENTRANTS; c.sl_i += 2)
        {
            if (c.sl_i >= cup.nSlots)
            {
                break;
            }
            if (cup.slotUsed.get(c.sl_i) && cup.slotUsed.get(c.sl_i + 1))
            {
                c.sl_need += 1;
            }
        }
        s.cups.set(k, cup);  // fightsInUse reads this cup's status and reservation from state
        c.sl_inUse = fightsInUse(s, c);
        c.sl_free = s.m.maxFights > c.sl_inUse ? s.m.maxFights - c.sl_inUse : 0;
        if (c.sl_need > c.sl_free)
        {
            c.sl_bit = uint16(1U << cup.level);
            if (cup.postponedMask & c.sl_bit)
            {
                abortCup(s, c, cup, QDOJO_AB_CAPACITY);
                return;
            }
            cup.postponedMask = uint16(cup.postponedMask | c.sl_bit);
            cup.levelStart = addU64(s, cup.levelStart, cup.d.levelTicks);
            cup.expiryTick = addU64(s, cup.expiryTick, cup.d.levelTicks);
            cupLevelEvent(s, c, cup, 1);
            cup.pendingReservation = 1;
            return;
        }
        cup.pendingReservation = 0;
        cup.reserved = c.sl_need;
        for (c.sl_i = 0; c.sl_i + 1 < QDOJO_CAP_CUP_ENTRANTS; c.sl_i += 2)
        {
            if (c.sl_i >= cup.nSlots)
            {
                break;
            }
            if (cup.nPairings >= QDOJO_CAP_PAIRINGS)
            {
                s.faults.slotOverflow += 1;
                break;
            }
            setMemory(c.sl_p, 0);
            c.sl_p.pairingId = uint64(cup.nPairings) + 1;
            c.sl_p.level = cup.level;
            c.sl_p.hasA = cup.slotUsed.get(c.sl_i);
            c.sl_p.hasB = cup.slotUsed.get(c.sl_i + 1);
            if (c.sl_p.hasA)
            {
                c.sl_p.a = cup.slots.get(c.sl_i);
            }
            if (c.sl_p.hasB)
            {
                c.sl_p.b = cup.slots.get(c.sl_i + 1);
            }
            c.sl_p.status = QDOJO_PS_SCHEDULED;
            if (!c.sl_p.hasA || !c.sl_p.hasB)
            {
                if (c.sl_p.hasA)
                {
                    c.sl_p.winner = c.sl_p.a;
                    c.sl_p.hasWinner = 1;
                }
                else if (c.sl_p.hasB)
                {
                    c.sl_p.winner = c.sl_p.b;
                    c.sl_p.hasWinner = 1;
                }
                c.sl_p.status = c.sl_p.hasWinner ? QDOJO_PS_DONE : QDOJO_PS_EMPTY;
            }
            cup.pairings.set(cup.nPairings, c.sl_p);
            cup.nPairings = uint8(cup.nPairings + 1);
        }
        cupLevelEvent(s, c, cup, 0);
    }

    // Seeding order: lifetime rating descending, then fighter id ascending.
    static bit seedsBefore(const StateData& s, const Cup& cup, uint8 x, uint8 y)
    {
        return s.fighters.get(cup.entries.get(x).fighterIdx).lifetime > s.fighters.get(cup.entries.get(y).fighterIdx).lifetime
            || (s.fighters.get(cup.entries.get(x).fighterIdx).lifetime == s.fighters.get(cup.entries.get(y).fighterIdx).lifetime
                && idCmp(cup.entries.get(x).fighterId, cup.entries.get(y).fighterId) < 0);
    }

    // bracket(): rating descending, then ID ascending; standard seed order; an empty slot is a bye.
    static void lockRoster(StateData& s, Ctx& c, Cup& cup, uint32 k, uint64 t)
    {
        if (cup.nEntries < cup.d.minEntrants)
        {
            releaseCupLocks(s, c, cup);
            refundCup(s, c, cup);
            cup.status = QDOJO_CUP_CANCELLED;
            finishedEvent(s, c, cup, QDOJO_STR_CANCELLED, false, NULL_ID, 0);
            return;
        }
        c.lr_n = cup.nEntries;
        for (c.lr_i = 0; c.lr_i < QDOJO_CAP_CUP_ENTRANTS; c.lr_i++)
        {
            c.lr_order.set(c.lr_i, uint8(c.lr_i));
        }
        for (c.lr_i = 1; c.lr_i < QDOJO_CAP_CUP_ENTRANTS; c.lr_i++)
        {
            if (c.lr_i >= c.lr_n)
            {
                break;
            }
            c.lr_x = c.lr_order.get(c.lr_i);
            c.lr_j = c.lr_i;
            while (c.lr_j > 0)
            {
                if (!seedsBefore(s, cup, c.lr_x, c.lr_order.get(c.lr_j - 1)))
                {
                    break;
                }
                c.lr_order.set(c.lr_j, c.lr_order.get(c.lr_j - 1));
                c.lr_j -= 1;
            }
            c.lr_order.set(c.lr_j, c.lr_x);
        }
        c.lr_size = 2;
        while (c.lr_size < c.lr_n)
        {
            c.lr_size *= 2;
        }
        c.lr_len = 2;
        c.lr_pos.set(0, 1);
        c.lr_pos.set(1, 2);
        while (c.lr_len < c.lr_size)  // at most three doublings for 16
        {
            c.lr_m = 2 * c.lr_len + 1;
            for (c.lr_i = 0; c.lr_i < c.lr_len; c.lr_i++)
            {
                c.lr_next.set(2 * c.lr_i, c.lr_pos.get(c.lr_i));
                c.lr_next.set(2 * c.lr_i + 1, uint8(c.lr_m - c.lr_pos.get(c.lr_i)));
            }
            c.lr_len *= 2;
            for (c.lr_i = 0; c.lr_i < c.lr_len; c.lr_i++)
            {
                c.lr_pos.set(c.lr_i, c.lr_next.get(c.lr_i));
            }
        }
        cup.nSlots = uint8(c.lr_size);
        shaInit(c.sha);
        for (c.lr_i = 0; c.lr_i < QDOJO_CAP_CUP_ENTRANTS; c.lr_i++)
        {
            if (c.lr_i >= c.lr_size)
            {
                break;
            }
            c.lr_seed = c.lr_pos.get(c.lr_i);
            if (c.lr_seed <= c.lr_n)
            {
                cup.slots.set(c.lr_i, cup.entries.get(c.lr_order.get(c.lr_seed - 1)).fighterId);
                cup.slotUsed.set(c.lr_i, 1);
            }
            else
            {
                cup.slots.set(c.lr_i, NULL_ID);
                cup.slotUsed.set(c.lr_i, 0);
            }
            shaId(c.sha, cup.slots.get(c.lr_i));
        }
        c.lr_levels = 0;
        while ((1U << (c.lr_levels + 1)) <= c.lr_size)
        {
            c.lr_levels += 1;
        }
        cup.levels = uint8(c.lr_levels);
        cup.status = QDOJO_CUP_RUNNING;
        cup.level = 0;
        cup.levelStart = addU64(s, t, cup.d.firstLevelDelay);
        cup.expiryTick = addU64(s, cup.levelStart, uint64(cup.levels + 1) * cup.d.levelTicks + cup.d.levelTicks);
        c.lr_digest = shaFinal(c.sha);
        bReset(c);
        bU64(c, cup.cupId);
        bId(c, c.lr_digest);
        emit(s, c, QDOJO_EV_CUP_BRACKET);
        scheduleLevel(s, c, cup, k);
    }

    // The offer snapshot a cup pairing's contest starts from (no escrow, payout = owner).
    static void pairingOffer(const StateData& s, Ctx& c, const Cup& cup, const id& fid, uint64 t, Offer& o)
    {
        c.po_fi = fighterIndex(s, c, fid);
        if (c.po_fi < 0)
        {
            c.po_fi = 0;
        }
        setMemory(o, 0);
        o.offerId = 0;
        o.fighterIdx = uint16(c.po_fi);
        o.fighterId = fid;
        o.owner = s.fighters.get(c.po_fi).owner;
        o.op = s.fighters.get(c.po_fi).op;
        o.authVersion = s.fighters.get(c.po_fi).authVersion;
        o.payer = NULL_ID;
        o.payout = s.fighters.get(c.po_fi).owner;
        o.timingId = cup.d.timingId;
        o.feeId = cup.d.feeId;
        o.amount = 0;
        o.rating = s.fighters.get(c.po_fi).lifetime;
        o.created = t;
        o.expires = t;
        o.generation = s.generation;
    }

    static void startPairingContest(StateData& s, Ctx& c, Cup& cup, uint32 pi, uint64 t, bit replay)
    {
        c.spc_final = sint32(cup.level) == sint32(cup.levels) - 1;
        c.spc_p = cup.pairings.get(pi);
        pairingOffer(s, c, cup, c.spc_p.a, t, c.sc_x);
        pairingOffer(s, c, cup, c.spc_p.b, t, c.sc_y);
        c.spc_cs = startContest(s, c, QDOJO_M_CUP, c.spc_final ? QDOJO_F_BO5 : QDOJO_F_BO3, t, false, 0, cup.cupId,
            c.spc_p.pairingId);
        if (c.spc_cs < 0)
        {
            return;
        }
        if (replay)
        {
            c.spc_con = s.contests.get(c.spc_cs);
            c.spc_con.series.need = 1;
            c.spc_con.series.cap = 3;
            c.spc_con.series.winsA = 0;
            c.spc_con.series.winsB = 0;
            c.spc_con.series.fights = 0;
            c.spc_con.replay = 1;
            s.contests.set(c.spc_cs, c.spc_con);
        }
        if (c.spc_final)
        {
            c.spc_p.hasFinalOwner = 0;
        }
        c.spc_p.contestId = s.contests.get(c.spc_cs).contestId;
        c.spc_p.status = QDOJO_PS_PLAYING;
        cup.pairings.set(pi, c.spc_p);
    }

    static void pairingEvent(StateData& s, Ctx& c, const Cup& cup, const Pairing& p)
    {
        bReset(c);
        bU64(c, cup.cupId);
        bU64(c, p.pairingId);
        bStr(c, pairingStatusStr(p.status));
        emit(s, c, QDOJO_EV_CUP_PAIRING);
    }

    static void startLevelPairings(StateData& s, Ctx& c, Cup& cup, uint64 t)
    {
        for (c.slp_i = 0; c.slp_i < QDOJO_CAP_PAIRINGS; c.slp_i++)
        {
            if (c.slp_i >= cup.nPairings)
            {
                break;
            }
            if (cup.pairings.get(c.slp_i).level != cup.level || cup.pairings.get(c.slp_i).status != QDOJO_PS_SCHEDULED)
            {
                continue;
            }
            if (cup.pairings.get(c.slp_i).checkedA && cup.pairings.get(c.slp_i).checkedB)
            {
                startPairingContest(s, c, cup, c.slp_i, t, false);
            }
            else if (cup.pairings.get(c.slp_i).checkedA || cup.pairings.get(c.slp_i).checkedB)
            {
                // The absent fighter forfeits; a missed check-in is not a
                // commit/reveal fault, so no cooldown is added.
                c.slp_p = cup.pairings.get(c.slp_i);
                c.slp_p.winner = c.slp_p.checkedA ? c.slp_p.a : c.slp_p.b;
                c.slp_p.hasWinner = 1;
                c.slp_p.status = QDOJO_PS_DONE;
                cup.pairings.set(c.slp_i, c.slp_p);
                cup.reserved -= 1;
            }
            else
            {
                c.slp_p = cup.pairings.get(c.slp_i);
                c.slp_p.status = QDOJO_PS_UNRESOLVED;
                cup.pairings.set(c.slp_i, c.slp_p);
                cup.reserved -= 1;
            }
            pairingEvent(s, c, cup, cup.pairings.get(c.slp_i));
        }
    }

    // A cup contest finished (from finishContest; no cup working copy is live then).
    static void cupPairingDone(StateData& s, Ctx& c, const Contest& con, uint64 t)
    {
        c.pd_k = cupSlot(s, c, con.cupId);
        if (c.pd_k < 0)
        {
            return;
        }
        c.cupA = s.cups.get(c.pd_k);
        if (con.pairingId < 1 || con.pairingId > c.cupA.nPairings)
        {
            return;
        }
        c.pd_p = c.cupA.pairings.get(con.pairingId - 1);
        if ((con.resultKind == QDOJO_R_COMBAT || con.resultKind == QDOJO_R_FORFEIT) && con.resultWinner != QDOJO_S_NONE)
        {
            c.pd_p.winner = con.resultWinner == QDOJO_S_A ? con.a.fighterId : con.b.fighterId;
            c.pd_p.hasWinner = 1;
            c.pd_p.finalOwner = con.resultWinner == QDOJO_S_A ? con.a.payout : con.b.payout;
            c.pd_p.hasFinalOwner = 1;
            c.pd_p.status = QDOJO_PS_DONE;
        }
        else if (con.resultKind == QDOJO_R_COMBAT && !con.replay)
        {
            c.pd_p.status = QDOJO_PS_REPLAY_WAIT;
            c.pd_p.replayAt = addU64(s, t, c.cupA.d.replayDelay);
            c.cupA.pairings.set(con.pairingId - 1, c.pd_p);
            s.cups.set(c.pd_k, c.cupA);
            bReset(c);
            bU64(c, c.cupA.cupId);
            bU64(c, c.pd_p.pairingId);
            bU64(c, c.pd_p.replayAt);
            emit(s, c, QDOJO_EV_CUP_REPLAY_SCHEDULED);
            return;
        }
        else
        {
            c.pd_p.status = QDOJO_PS_UNRESOLVED;
        }
        c.cupA.pairings.set(con.pairingId - 1, c.pd_p);
        c.cupA.reserved -= 1;
        s.cups.set(c.pd_k, c.cupA);
        pairingEvent(s, c, c.cupA, c.pd_p);
    }

    static void payCup(StateData& s, Ctx& c, Cup& cup, const Pairing& fin)
    {
        c.pc_entryGross = 0;
        for (c.pc_i = 0; c.pc_i < QDOJO_CAP_CUP_ENTRANTS; c.pc_i++)
        {
            if (c.pc_i < cup.nEntries)
            {
                c.pc_entryGross = addI64(s, c.pc_entryGross, cup.entries.get(c.pc_i).amount);
            }
        }
        if (fin.hasFinalOwner)
        {
            c.pc_recipient = fin.finalOwner;
        }
        else
        {
            c.pc_fi = fighterIndex(s, c, fin.winner);
            c.pc_recipient = c.pc_fi >= 0 ? s.fighters.get(c.pc_fi).owner : fin.winner;
        }
        c.pc_fe = feeIdx(s, c, cup.d.feeId);
        c.pc_gross = addI64(s, cup.sponsorship, c.pc_entryGross);
        c.pc_rake = 0;
        c.pc_dev = 0;
        c.pc_share = 0;
        if (c.pc_fe >= 0)
        {
            c.pc_fp = s.m.fees.get(c.pc_fe);
            c.pc_rake = div<sint64>(mulI64(s, c.pc_entryGross, sint64(c.pc_fp.rakeBps)), QDOJO_BPS);
            c.pc_dev = div<sint64>(mulI64(s, c.pc_rake, sint64(c.pc_fp.devBps)), QDOJO_BPS);
            c.pc_share = div<sint64>(mulI64(s, c.pc_rake, sint64(c.pc_fp.shareBps)), QDOJO_BPS);
        }
        cup.hasPot = 0;
        credit(s, c, c.pc_recipient, subI64(s, c.pc_gross, c.pc_rake));
        if (c.pc_fe >= 0)
        {
            credit(s, c, c.pc_fp.house, subI64(s, subI64(s, c.pc_rake, c.pc_dev), c.pc_share));
            credit(s, c, c.pc_fp.dev, c.pc_dev);
            credit(s, c, c.pc_fp.share, c.pc_share);
        }
        cup.status = QDOJO_CUP_COMPLETE;
        cup.champion = fin.winner;
        releaseCupLocks(s, c, cup);
        finishedEvent(s, c, cup, QDOJO_STR_COMPLETE, true, fin.winner, 0);
    }

    static void advanceLevel(StateData& s, Ctx& c, Cup& cup, uint32 k, uint64 t)
    {
        c.al_ns = 0;
        c.al_first = -1;
        for (c.al_i = 0; c.al_i < QDOJO_CAP_PAIRINGS; c.al_i++)
        {
            if (c.al_i >= cup.nPairings)
            {
                break;
            }
            c.al_p = cup.pairings.get(c.al_i);
            if (c.al_p.level != cup.level)
            {
                continue;
            }
            if (c.al_first < 0)
            {
                c.al_first = sint32(c.al_i);
            }
            c.al_alive = (c.al_p.status == QDOJO_PS_DONE && c.al_p.hasWinner) ? 1 : 0;
            c.al_survivors.set(c.al_ns, c.al_alive ? c.al_p.winner : NULL_ID);
            c.al_aliveFlags.set(c.al_ns, c.al_alive);
            c.al_ns += 1;
            for (c.al_side = 0; c.al_side < 2; c.al_side++)
            {
                c.al_has = c.al_side == 0 ? c.al_p.hasA : c.al_p.hasB;
                c.al_fid = c.al_side == 0 ? c.al_p.a : c.al_p.b;
                if (!c.al_has || (c.al_p.hasWinner && c.al_fid == c.al_p.winner) || !cupHasEntry(cup, c, c.al_fid))
                {
                    continue;
                }
                c.al_fi = fighterIndex(s, c, c.al_fid);
                if (c.al_fi < 0)
                {
                    continue;
                }
                releaseFighter(s, c, uint32(c.al_fi), QDOJO_L_TOURNAMENT, cup.cupId);
            }
        }
        cup.reserved = 0;
        if (sint32(cup.level) == sint32(cup.levels) - 1)
        {
            if (c.al_first >= 0)
            {
                c.al_fin = cup.pairings.get(c.al_first);
                if (c.al_fin.status == QDOJO_PS_DONE && c.al_fin.hasWinner && cup.combatFights > 0)
                {
                    payCup(s, c, cup, c.al_fin);
                    return;
                }
            }
            abortCup(s, c, cup, QDOJO_AB_NO_CHAMPION);
            return;
        }
        for (c.al_i = 0; c.al_i < QDOJO_CAP_CUP_ENTRANTS; c.al_i++)
        {
            if (c.al_i >= c.al_ns)
            {
                break;
            }
            cup.slots.set(c.al_i, c.al_survivors.get(c.al_i));
            cup.slotUsed.set(c.al_i, c.al_aliveFlags.get(c.al_i));
        }
        cup.nSlots = uint8(c.al_ns);
        cup.level = uint8(cup.level + 1);
        cup.levelStart = addU64(s, cup.levelStart, cup.d.levelTicks);
        if (t >= cup.levelStart)
        {
            cup.levelStart = addU64(s, t, 1);
        }
        scheduleLevel(s, c, cup, k);
    }

    static void cupTick(StateData& s, Ctx& c, uint32 k, uint64 t)
    {
        c.cupW = s.cups.get(k);
        if (c.cupW.status == QDOJO_CUP_REGISTRATION && t >= c.cupW.d.registrationClose)
        {
            lockRoster(s, c, c.cupW, k, t);
            s.cups.set(k, c.cupW);
            return;
        }
        if (c.cupW.status != QDOJO_CUP_RUNNING)
        {
            return;
        }
        if (t >= c.cupW.expiryTick)
        {
            abortCup(s, c, c.cupW, QDOJO_AB_EXPIRED);
            s.cups.set(k, c.cupW);
            return;
        }
        if (c.cupW.pendingReservation)
        {
            // A postponed level retries its reservation just before its check-in opens.
            if (t + 1 == c.cupW.levelStart)
            {
                scheduleLevel(s, c, c.cupW, k);
                s.cups.set(k, c.cupW);
            }
            return;
        }
        c.ct_checkinEnd = c.cupW.levelStart + c.cupW.d.checkinTicks - 1;
        if (t == c.ct_checkinEnd)
        {
            startLevelPairings(s, c, c.cupW, t);
        }
        for (c.ct_i = 0; c.ct_i < QDOJO_CAP_PAIRINGS; c.ct_i++)
        {
            if (c.ct_i >= c.cupW.nPairings)
            {
                break;
            }
            if (c.cupW.pairings.get(c.ct_i).level == c.cupW.level && c.cupW.pairings.get(c.ct_i).status == QDOJO_PS_REPLAY_WAIT
                && t >= c.cupW.pairings.get(c.ct_i).replayAt)
            {
                startPairingContest(s, c, c.cupW, c.ct_i, t, true);
            }
        }
        if (t > c.ct_checkinEnd)
        {
            c.ct_all = 1;
            for (c.ct_i = 0; c.ct_i < QDOJO_CAP_PAIRINGS; c.ct_i++)
            {
                if (c.ct_i >= c.cupW.nPairings)
                {
                    break;
                }
                if (c.cupW.pairings.get(c.ct_i).level == c.cupW.level && c.cupW.pairings.get(c.ct_i).status != QDOJO_PS_DONE
                    && c.cupW.pairings.get(c.ct_i).status != QDOJO_PS_UNRESOLVED
                    && c.cupW.pairings.get(c.ct_i).status != QDOJO_PS_EMPTY)
                {
                    c.ct_all = 0;
                }
            }
            if (c.ct_all)
            {
                advanceLevel(s, c, c.cupW, k, t);
            }
        }
        s.cups.set(k, c.cupW);
    }

    // =========================================================== matching (matchmaking.py matching_pass)
    static uint64 windowOf(const Offer& o, uint64 t)
    {
        return uint64(o.maxGap) < QDOJO_BASE_WINDOW + QDOJO_WIDEN_STEP * div<uint64>(t - o.created, QDOJO_WIDEN_TICKS)
            ? uint64(o.maxGap)
            : QDOJO_BASE_WINDOW + QDOJO_WIDEN_STEP * div<uint64>(t - o.created, QDOJO_WIDEN_TICKS);
    }

    static bit inCooldown(const Fighter& f, uint64 t, sint64 epoch)
    {
        return t < f.cooldownUntil || f.suspendedEpoch == epoch;
    }

    static bit offerLive(const StateData& s, const Offer& o, uint64 t)
    {
        return o.status == QDOJO_O_OPEN && t < o.expires && o.generation == s.generation;
    }

    static bit compatible(StateData& s, Ctx& c, uint32 kx, uint32 ky, uint64 t, sint64 epoch)
    {
        if (!offerLive(s, s.offers.get(kx), t) || !offerLive(s, s.offers.get(ky), t))
        {
            return false;
        }
        if (s.offers.get(kx).fighterId == s.offers.get(ky).fighterId || s.offers.get(kx).owner == s.offers.get(ky).owner
            || s.offers.get(kx).op == s.offers.get(ky).op)
        {
            return false;
        }
        if (s.fighters.get(s.offers.get(kx).fighterIdx).houseNpc || s.fighters.get(s.offers.get(ky).fighterIdx).houseNpc)
        {
            return false;
        }
        if (s.offers.get(kx).timingId != s.offers.get(ky).timingId || s.offers.get(kx).feeId != s.offers.get(ky).feeId
            || s.offers.get(kx).tierId != s.offers.get(ky).tierId || s.offers.get(kx).amount != s.offers.get(ky).amount)
        {
            return false;
        }
        c.cp_gap = s.offers.get(kx).rating > s.offers.get(ky).rating
            ? uint64(s.offers.get(kx).rating - s.offers.get(ky).rating)
            : uint64(s.offers.get(ky).rating - s.offers.get(kx).rating);
        if (c.cp_gap > windowOf(s.offers.get(kx), t) || c.cp_gap > windowOf(s.offers.get(ky), t))
        {
            return false;
        }
        c.cp_p = pairFind(s, c, s.offers.get(kx).fighterIdx, s.offers.get(ky).fighterIdx, false, epoch, t);
        if (c.cp_p >= 0)
        {
            if (s.pairs.get(c.cp_p).epoch == epoch && s.pairs.get(c.cp_p).starts >= s.m.pairStartsPerEpoch)
            {
                return false;
            }
            if (s.pairs.get(c.cp_p).hasLast && t - s.pairs.get(c.cp_p).last < s.m.pairRematchTicks)
            {
                return false;
            }
        }
        if (inCooldown(s.fighters.get(s.offers.get(kx).fighterIdx), t, epoch)
            || inCooldown(s.fighters.get(s.offers.get(ky).fighterIdx), t, epoch))
        {
            return false;
        }
        return s.m.maxFights > fightsInUse(s, c);
    }

    static bit stillValid(const StateData& s, Ctx& c, uint32 k)
    {
        if (!ownerOf(c, s.offers.get(k).fighterId, c.sv_owner))
        {
            return false;
        }
        return c.sv_owner == s.offers.get(k).owner && s.offers.get(k).owner == s.fighters.get(s.offers.get(k).fighterIdx).owner
            && s.fighters.get(s.offers.get(k).fighterIdx).op == s.offers.get(k).op
            && s.fighters.get(s.offers.get(k).fighterIdx).authVersion == s.offers.get(k).authVersion
            && s.fighters.get(s.offers.get(k).fighterIdx).lockRef == s.offers.get(k).offerId;
    }

    static void closeOffer(StateData& s, Ctx& c, uint32 k, uint8 status)
    {
        c.co_o = s.offers.get(k);
        c.co_o.status = status;
        c.co_wasEscrowed = c.co_o.escrowed;
        c.co_o.escrowed = 0;
        s.offers.set(k, c.co_o);
        if (c.co_wasEscrowed)
        {
            credit(s, c, c.co_o.payer, c.co_o.amount);
        }
        if ((s.fighters.get(c.co_o.fighterIdx).lock == QDOJO_L_QUEUED || s.fighters.get(c.co_o.fighterIdx).lock == QDOJO_L_DUEL_OFFER)
            && s.fighters.get(c.co_o.fighterIdx).lockRef == c.co_o.offerId)
        {
            lockFighter(s, c, c.co_o.fighterIdx, QDOJO_L_IDLE, 0);
        }
        bReset(c);
        bU64(c, c.co_o.offerId);
        bStr(c, offerStatusStr(status));
        emit(s, c, QDOJO_EV_OFFER_CLOSED);
    }

    static void matching(StateData& s, Ctx& c, uint64 t)
    {
        c.mt_epoch = epochOf(s, t);
        c.mt_n = 0;
        for (c.mt_i = 0; c.mt_i < QDOJO_CAP_OFFER_SLOTS; c.mt_i++)
        {
            if (s.offers.get(c.mt_i).used && s.offers.get(c.mt_i).status == QDOJO_O_OPEN
                && s.offers.get(c.mt_i).kind == QDOJO_K_RANKED)
            {
                c.mt_ids.set(c.mt_n, s.offers.get(c.mt_i).offerId);
                c.mt_n += 1;
            }
        }
        sortU64(c.mt_ids, c.mt_n, c);
        if (c.mt_n > QDOJO_PASS_SNAPSHOT)
        {
            c.mt_n = QDOJO_PASS_SNAPSHOT;
        }
        c.mt_nl = 0;
        for (c.mt_i = 0; c.mt_i < QDOJO_PASS_SNAPSHOT; c.mt_i++)
        {
            if (c.mt_i >= c.mt_n)
            {
                break;
            }
            c.mt_k = offerSlot(s, c, c.mt_ids.get(c.mt_i));
            if (c.mt_k < 0)
            {
                continue;
            }
            if (t >= s.offers.get(c.mt_k).expires || s.offers.get(c.mt_k).generation != s.generation
                || !stillValid(s, c, uint32(c.mt_k)))
            {
                closeOffer(s, c, uint32(c.mt_k), t >= s.offers.get(c.mt_k).expires ? QDOJO_O_EXPIRED : QDOJO_O_INVALIDATED);
            }
            else
            {
                c.mt_live.set(c.mt_nl, uint32(c.mt_k));
                c.mt_nl += 1;
            }
        }
        if (c.mt_nl < 2)
        {
            return;
        }
        c.mt_matched = 0;
        setMemory(c.mt_taken, 0);
        for (c.mt_i = 0; c.mt_i < QDOJO_PASS_SNAPSHOT; c.mt_i++)
        {
            if (c.mt_i >= c.mt_nl)
            {
                break;
            }
            if (c.mt_matched >= QDOJO_PASS_MATCHES)
            {
                break;
            }
            if (c.mt_taken.get(c.mt_i))
            {
                continue;
            }
            for (c.mt_j = c.mt_i + 1; c.mt_j < QDOJO_PASS_SNAPSHOT; c.mt_j++)
            {
                if (c.mt_j >= c.mt_nl)
                {
                    break;
                }
                if (c.mt_taken.get(c.mt_j))
                {
                    continue;
                }
                if (!compatible(s, c, c.mt_live.get(c.mt_i), c.mt_live.get(c.mt_j), t, c.mt_epoch))
                {
                    continue;
                }
                c.mt_taken.set(c.mt_i, 1);
                c.mt_taken.set(c.mt_j, 1);
                c.mt_o = s.offers.get(c.mt_live.get(c.mt_i));
                c.mt_o.status = QDOJO_O_MATCHED;
                s.offers.set(c.mt_live.get(c.mt_i), c.mt_o);
                c.mt_o = s.offers.get(c.mt_live.get(c.mt_j));
                c.mt_o.status = QDOJO_O_MATCHED;
                s.offers.set(c.mt_live.get(c.mt_j), c.mt_o);
                c.mt_p = pairFind(s, c, s.offers.get(c.mt_live.get(c.mt_i)).fighterIdx,
                    s.offers.get(c.mt_live.get(c.mt_j)).fighterIdx, true, c.mt_epoch, t);
                if (c.mt_p >= 0)
                {
                    c.mt_pr = s.pairs.get(c.mt_p);
                    if (c.mt_pr.epoch != c.mt_epoch)
                    {
                        c.mt_pr.epoch = c.mt_epoch;
                        c.mt_pr.starts = 0;
                    }
                    c.mt_pr.starts += 1;
                    s.pairs.set(c.mt_p, c.mt_pr);
                }
                bReset(c);
                bU64(c, s.offers.get(c.mt_live.get(c.mt_i)).offerId);
                bU64(c, s.offers.get(c.mt_live.get(c.mt_j)).offerId);
                emit(s, c, QDOJO_EV_MATCHED);
                c.sc_x = s.offers.get(c.mt_live.get(c.mt_i));
                c.sc_y = s.offers.get(c.mt_live.get(c.mt_j));
                startContest(s, c, QDOJO_M_RANKED, QDOJO_F_SINGLE, t, true, c.mt_epoch, 0, 0);
                c.mt_matched += 1;
                break;
            }
        }
    }

    // =========================================================== frames (codec.py decode_frame)
    static sint32 bodyLen(uint16 op)
    {
        switch (op)
        {
        case QDOJO_OP_REGISTER_FIGHTER: return 32 + 4;
        case QDOJO_OP_SET_OPERATOR: return 32 + 32 + 4;
        case QDOJO_OP_QUEUE_ENTER: return 32 + 4 + 32 + 4 + 4 + 2 + 2 + 8;
        case QDOJO_OP_QUEUE_CANCEL: return 8;
        case QDOJO_OP_DUEL_OFFER: return 32 + 4 + 32 + 32 + 4 + 4 + 8 + 1 + 8;
        case QDOJO_OP_DUEL_ACCEPT: return 8 + 32 + 4;
        case QDOJO_OP_COMMIT: return 8 + 1 + 32 + 4 + 32 + 32;
        case QDOJO_OP_REVEAL: return 8 + 1 + 32 + 4 + 32 + 32 + 7;
        case QDOJO_OP_ADVANCE: return 1 + 8;
        case QDOJO_OP_WITHDRAW: return 0;
        case QDOJO_OP_CUP_REGISTER: return 8 + 32 + 4;
        case QDOJO_OP_CUP_WITHDRAW: return 8 + 32;
        case QDOJO_OP_CUP_CHECK_IN: return 8 + 8 + 32 + 4;
        case QDOJO_OP_DUEL_CANCEL: return 8;
        case QDOJO_OP_ADMIN_REGISTER_ASSET: return 32 + 4 + 1;
        case QDOJO_OP_ADMIN_CREATE_CUP: return 32 + 4 + 4 + 8 + 8 + 1 + 1 + 2 + 2 + 2 + 2;
        case QDOJO_OP_ADMIN_RETIRE_RULESET: return 32;
        default: return -1;
        }
    }

    // Structural plan check at decode (codec.decode_plan + Plan.of): BAD_PLAN.
    static bit planShapeOk(const Array<uint8, 512>& fr, uint32 at)
    {
        if (fr.get(at) > 5 || fr.get(at + 1) > 5 || fr.get(at + 2) > 5 || fr.get(at + 3) > 5 || fr.get(at + 4) > 5
            || fr.get(at + 5) > 5)
        {
            return false;
        }
        if (fr.get(at + 6) == QDOJO_NO_POWER_SLOT)
        {
            return true;
        }
        if (fr.get(at + 6) > 5)
        {
            return false;
        }
        return isAttack(fr.get(at + fr.get(at + 6)));
    }

    // Results: c.fr_op, c.fr_nonce, c.fr_len. Keeps the reference's check order.
    static uint8 decodeFrame(const Array<uint8, 512>& fr, Ctx& c)
    {
        if (fr.get(QDOJO_FRAME_LEN - 1) != QDOJO_FRAME_SENTINEL)
        {
            return QDOJO_BAD_FRAME;
        }
        if (fr.get(0) != QDOJO_MAGIC_0 || fr.get(1) != QDOJO_MAGIC_1 || fr.get(2) != QDOJO_MAGIC_2 || fr.get(3) != QDOJO_MAGIC_3)
        {
            return QDOJO_BAD_FRAME;
        }
        c.fr_op = uint16(rdLe(fr, 4, 2));
        c.fr_flags = uint16(rdLe(fr, 6, 2));
        c.fr_nonce = rdLe(fr, 8, 8);
        c.fr_len = uint16(rdLe(fr, 16, 2));
        if (c.fr_flags)
        {
            return QDOJO_BAD_FRAME;
        }
        for (c.df_i = 18; c.df_i < 24; c.df_i++)
        {
            if (fr.get(c.df_i))
            {
                return QDOJO_BAD_FRAME;
            }
        }
        if (c.fr_len > QDOJO_MAX_BODY)
        {
            return QDOJO_BAD_FRAME;
        }
        c.fr_want = bodyLen(c.fr_op);
        if (c.fr_want < 0)
        {
            return QDOJO_BAD_OPCODE;
        }
        for (c.df_i = QDOJO_FRAME_HEADER; c.df_i < QDOJO_FRAME_LEN - 1; c.df_i++)
        {
            if (c.df_i >= QDOJO_FRAME_HEADER + uint32(c.fr_len) && fr.get(c.df_i))
            {
                return QDOJO_BAD_FRAME;
            }
        }
        if (sint32(c.fr_len) != c.fr_want)
        {
            return QDOJO_BAD_BODY;
        }
        if (c.fr_op == QDOJO_OP_REVEAL && !planShapeOk(fr, QDOJO_FRAME_HEADER + 8 + 1 + 32 + 4 + 32 + 32))
        {
            return QDOJO_BAD_PLAN;
        }
        return QDOJO_OK;
    }

    // SHA-256 of the whole 512-byte frame (the request digest).
    static id frameDigest(const Array<uint8, 512>& fr, Ctx& c)
    {
        shaInit(c.sha);
        for (c.df_i = 0; c.df_i < QDOJO_FRAME_LEN; c.df_i++)
        {
            shaByte(c.sha, fr.get(c.df_i));
        }
        return shaFinal(c.sha);
    }

    // Sequential little-endian body reader over the frame (c.rAt).
    static uint64 rdU(const Array<uint8, 512>& fr, Ctx& c, uint32 width)
    {
        c.rAt += width;
        return rdLe(fr, c.rAt - width, width);
    }

    static id rdId(const Array<uint8, 512>& fr, Ctx& c)
    {
        c.rAt += 32;
        return idFromFrame(fr, c.rAt - 32);
    }

    // Offset of the next `width` raw bytes.
    static uint32 rdRaw(Ctx& c, uint32 width)
    {
        c.rAt += width;
        return c.rAt - width;
    }

    // Live records are never evicted, so an id that was issued but is no longer
    // retained belonged to a terminal record.
    static bit archived(uint64 recordId, uint64 next)
    {
        return recordId >= 1 && recordId < next;
    }

    // =========================================================== handlers (contract.py _op_*)
    static void opAdminRegisterAsset(StateData& s, Ctx& c, const id& inv, const Array<uint8, 512>& fr, sint64 amount,
        Res& r)
    {
        if (amount)
        {
            setRej(r, QDOJO_BAD_AMOUNT);
            return;
        }
        c.h_fid = rdId(fr, c);
        c.h_version = uint32(rdU(fr, c, 4));
        c.h_npc = uint8(rdU(fr, c, 1));
        if (inv != s.m.admin)
        {
            setRej(r, QDOJO_NOT_OWNER);
            return;
        }
        if (c.h_npc > 1)
        {
            setRej(r, QDOJO_BAD_BODY);
            return;
        }
        c.h_a = assetIndex(s, c, c.h_fid);
        if (c.h_a < 0)
        {
            for (c.h_i = 0; c.h_i < QDOJO_CAP_ASSETS; c.h_i++)
            {
                if (!s.assets.get(c.h_i).used)
                {
                    c.h_a = sint32(c.h_i);
                    break;
                }
            }
            if (c.h_a < 0)
            {
                setRej(r, QDOJO_FULL);  // the reference registry is unbounded
                return;
            }
        }
        c.h_asset.used = 1;
        c.h_asset.fighterId = c.h_fid;
        c.h_asset.registryVersion = c.h_version;
        c.h_asset.houseNpc = c.h_npc;
        s.assets.set(c.h_a, c.h_asset);
        bReset(c);
        bId(c, c.h_fid);
        bU64(c, c.h_version);
        bU64(c, c.h_npc);
        emit(s, c, QDOJO_EV_ASSET_REGISTERED);
        setOk(r, 0);
    }

    static void opAdminRetireRuleset(StateData& s, Ctx& c, const id& inv, const Array<uint8, 512>& fr, sint64 amount,
        Res& r)
    {
        if (amount)
        {
            setRej(r, QDOJO_BAD_AMOUNT);
            return;
        }
        c.h_at = rdRaw(c, 32);
        if (inv != s.m.admin)
        {
            setRej(r, QDOJO_NOT_OWNER);
            return;
        }
        // Only the manifest's ruleset can ever be admitted, so only its
        // retirement changes behaviour; the event records any digest.
        if (idFromFrame(fr, c.h_at) == s.m.rulesetDigest)
        {
            s.rulesetRetired = 1;
        }
        bReset(c);
        bFrameBytes(c, fr, c.h_at, 32);
        emit(s, c, QDOJO_EV_RULESET_RETIRED);
        setOk(r, 0);
    }

    static void opRegisterFighter(StateData& s, Ctx& c, const id& inv, const Array<uint8, 512>& fr, sint64 amount,
        Res& r)
    {
        if (amount)
        {
            setRej(r, QDOJO_BAD_AMOUNT);
            return;
        }
        c.h_fid = rdId(fr, c);
        c.h_version = uint32(rdU(fr, c, 4));
        c.h_a = assetIndex(s, c, c.h_fid);
        if (c.h_a < 0 || s.assets.get(c.h_a).registryVersion != c.h_version)
        {
            setRej(r, QDOJO_UNKNOWN_FIGHTER);
            return;
        }
        if (!ownerOf(c, c.h_fid, c.h_owner))
        {
            setRej(r, QDOJO_BAD_STATE);
            return;
        }
        if (c.h_owner != inv)
        {
            setRej(r, QDOJO_NOT_OWNER);
            return;
        }
        c.h_fi = fighterIndex(s, c, c.h_fid);
        if (c.h_fi < 0)
        {
            if (s.nFighters >= s.m.maxFighters || s.nFighters >= QDOJO_CAP_FIGHTERS)
            {
                setRej(r, QDOJO_FULL);
                return;
            }
            c.h_fi = sint32(s.nFighters);
            s.nFighters += 1;
            setMemory(c.h_f, 0);
            c.h_f.fighterId = c.h_fid;
            c.h_f.owner = c.h_owner;
            c.h_f.op = c.h_owner;
            c.h_f.authVersion = 1;
            c.h_f.houseNpc = s.assets.get(c.h_a).houseNpc;
            c.h_f.lock = QDOJO_L_IDLE;
            c.h_f.lifetime = uint16(QDOJO_RATING_INITIAL);
            s.fighters.set(c.h_fi, c.h_f);
        }
        else if (s.fighters.get(c.h_fi).owner != c.h_owner)
        {
            c.h_f = s.fighters.get(c.h_fi);
            if (c.h_f.lock != QDOJO_L_IDLE && c.h_f.lock != QDOJO_L_TOURNAMENT)
            {
                setRej(r, QDOJO_FIGHTER_BUSY);
                return;
            }
            // The buyer binds the asset; rating, history and faults follow the fighter.
            c.h_f.owner = c.h_owner;
            c.h_f.op = c.h_owner;
            c.h_f.authVersion += 1;
            s.fighters.set(c.h_fi, c.h_f);
        }
        else
        {
            setDup(r, 0);
            return;
        }
        bReset(c);
        bId(c, c.h_fid);
        bId(c, c.h_owner);
        bU64(c, s.fighters.get(c.h_fi).authVersion);
        emit(s, c, QDOJO_EV_FIGHTER_REGISTERED);
        setOk(r, 0);
    }

    static void opSetOperator(StateData& s, Ctx& c, const id& inv, const Array<uint8, 512>& fr, sint64 amount, Res& r)
    {
        if (amount)
        {
            setRej(r, QDOJO_BAD_AMOUNT);
            return;
        }
        c.h_fid = rdId(fr, c);
        c.h_newOp = rdId(fr, c);
        c.h_version = uint32(rdU(fr, c, 4));
        c.h_fi = fighterIndex(s, c, c.h_fid);
        if (c.h_fi < 0)
        {
            setRej(r, QDOJO_UNKNOWN_FIGHTER);
            return;
        }
        c.h_f = s.fighters.get(c.h_fi);
        if (!ownerOf(c, c.h_fid, c.h_owner))
        {
            setRej(r, QDOJO_BAD_STATE);
            return;
        }
        if (inv != c.h_owner || c.h_owner != c.h_f.owner)
        {
            setRej(r, QDOJO_NOT_OWNER);
            return;
        }
        if (c.h_version != c.h_f.authVersion)
        {
            setRej(r, QDOJO_STALE_AUTH);
            return;
        }
        if (c.h_f.lock == QDOJO_L_TOURNAMENT)
        {
            c.h_k = cupSlot(s, c, c.h_f.lockRef);
            if (c.h_k < 0 || !betweenPairings(s.cups.get(c.h_k), c, c.h_f.fighterId))
            {
                setRej(r, QDOJO_FIGHTER_BUSY);
                return;
            }
        }
        else if (c.h_f.lock != QDOJO_L_IDLE)
        {
            setRej(r, QDOJO_FIGHTER_BUSY);
            return;
        }
        c.h_f.op = c.h_newOp;
        c.h_f.authVersion += 1;
        s.fighters.set(c.h_fi, c.h_f);
        bReset(c);
        bId(c, c.h_f.fighterId);
        bId(c, c.h_f.op);
        bU64(c, c.h_f.authVersion);
        emit(s, c, QDOJO_EV_OPERATOR_SET);
        setOk(r, 0);
    }

    static bit lifetimeOk(const StateData& s, uint64 expires, uint64 t)
    {
        if (expires < t)
        {
            return false;  // negative lifetime
        }
        return s.m.offerLifetimeLo <= expires - t && expires - t <= s.m.offerLifetimeHi;
    }

    static void openOffer(StateData& s, Ctx& c, uint32 fi, const id& inv, sint64 amount, uint32 timingId, uint32 feeId,
        uint16 tierId, uint16 maxGap, uint64 t, uint64 expires, uint8 kind, const id& opponent, uint8 fmt, uint8 lock,
        Res& r)
    {
        c.oo_k = newOfferSlot(s, c);
        if (c.oo_k < 0)
        {
            setRej(r, QDOJO_FULL);
            return;
        }
        c.oo_oid = s.nextOffer;
        s.nextOffer += 1;
        setMemory(c.oo_o, 0);
        c.oo_o.used = 1;
        c.oo_o.offerId = c.oo_oid;
        c.oo_o.fighterIdx = uint16(fi);
        c.oo_o.fighterId = s.fighters.get(fi).fighterId;
        c.oo_o.owner = s.fighters.get(fi).owner;
        c.oo_o.op = s.fighters.get(fi).op;
        c.oo_o.authVersion = s.fighters.get(fi).authVersion;
        c.oo_o.payer = inv;
        c.oo_o.payout = s.fighters.get(fi).owner;
        c.oo_o.timingId = timingId;
        c.oo_o.feeId = feeId;
        c.oo_o.tierId = tierId;
        c.oo_o.amount = amount;
        c.oo_o.rating = s.fighters.get(fi).lifetime;
        c.oo_o.maxGap = maxGap;
        c.oo_o.created = t;
        c.oo_o.expires = expires;
        c.oo_o.generation = s.generation;
        c.oo_o.status = QDOJO_O_OPEN;
        c.oo_o.kind = kind;
        c.oo_o.opponentId = opponent;
        c.oo_o.seriesFormat = fmt;
        c.oo_o.escrowed = 1;
        s.offers.set(c.oo_k, c.oo_o);
        lockFighter(s, c, fi, lock, c.oo_oid);
        bReset(c);
        bU64(c, c.oo_oid);
        bId(c, c.oo_o.fighterId);
        bU64(c, uint64(amount));
        bU64(c, expires);
        emit(s, c, QDOJO_EV_OFFER_OPEN);
        setOk(r, c.oo_oid);
    }

    static void opQueueEnter(StateData& s, Ctx& c, const id& inv, const Array<uint8, 512>& fr, sint64 amount, uint64 t,
        Res& r)
    {
        c.h_fid = rdId(fr, c);
        c.h_version = uint32(rdU(fr, c, 4));
        c.h_ruleset = rdId(fr, c);
        c.h_timingId = uint32(rdU(fr, c, 4));
        c.h_feeId = uint32(rdU(fr, c, 4));
        c.h_tierId = uint16(rdU(fr, c, 2));
        c.h_maxGap = uint16(rdU(fr, c, 2));
        c.h_expires = rdU(fr, c, 8);
        c.h_fi = fighterIndex(s, c, c.h_fid);
        if (c.h_fi < 0)
        {
            setRej(r, QDOJO_UNKNOWN_FIGHTER);
            return;
        }
        authorize(s, c, c.h_fi, inv, c.h_version, r);
        if (!accepted(r))
        {
            return;
        }
        profiles(s, c, c.h_ruleset, c.h_timingId, c.h_feeId, r);
        if (!accepted(r))
        {
            return;
        }
        c.h_t = tierIdx(s, c, c.h_tierId);
        if (c.h_t < 0)
        {
            setRej(r, QDOJO_INCOMPATIBLE);
            return;
        }
        if (amount != s.m.tiers.get(c.h_t).stake)
        {
            setRej(r, QDOJO_BAD_AMOUNT);
            return;
        }
        if (c.h_maxGap < QDOJO_MAX_GAP_LO || c.h_maxGap > QDOJO_MAX_GAP_HI)
        {
            setRej(r, QDOJO_BAD_BODY);
            return;
        }
        if (!lifetimeOk(s, c.h_expires, t))
        {
            setRej(r, QDOJO_BAD_BODY);
            return;
        }
        if (s.fighters.get(c.h_fi).lock != QDOJO_L_IDLE)
        {
            setRej(r, QDOJO_FIGHTER_BUSY);
            return;
        }
        if (s.fighters.get(c.h_fi).houseNpc)
        {
            setRej(r, QDOJO_INCOMPATIBLE);
            return;
        }
        if (t < s.fighters.get(c.h_fi).cooldownUntil)
        {
            setRej(r, QDOJO_COOLDOWN);
            return;
        }
        if (s.fighters.get(c.h_fi).suspendedEpoch == epochOf(s, t))
        {
            setRej(r, QDOJO_COOLDOWN);
            return;
        }
        if (openOffers(s, c) >= s.m.maxOffers)
        {
            setRej(r, QDOJO_FULL);
            return;
        }
        claim(s, c, s.fighters.get(c.h_fi).owner, r);  // the payout recipient needs a credit slot
        if (!accepted(r))
        {
            return;
        }
        openOffer(s, c, uint32(c.h_fi), inv, amount, c.h_timingId, c.h_feeId, c.h_tierId, c.h_maxGap, t, c.h_expires,
            QDOJO_K_RANKED, NULL_ID, 0, QDOJO_L_QUEUED, r);
    }

    static void cancel(StateData& s, Ctx& c, const id& inv, uint64 offerId, uint8 kind, Res& r)
    {
        c.h_k = offerSlot(s, c, offerId);
        if (c.h_k < 0 || s.offers.get(c.h_k).kind != kind)
        {
            setRej(r, QDOJO_NOT_FOUND);
            return;
        }
        c.h_have = ownerOf(c, s.offers.get(c.h_k).fighterId, c.h_owner);
        if (inv != s.offers.get(c.h_k).owner && inv != s.offers.get(c.h_k).op && !(c.h_have && inv == c.h_owner))
        {
            setRej(r, QDOJO_NOT_OWNER);
            return;
        }
        if (s.offers.get(c.h_k).status == QDOJO_O_MATCHED)
        {
            setRej(r, QDOJO_ALREADY_MATCHED);
            return;
        }
        if (s.offers.get(c.h_k).status != QDOJO_O_OPEN)
        {
            setDup(r, offerId);
            return;
        }
        closeOffer(s, c, uint32(c.h_k), QDOJO_O_CANCELLED);
        setOk(r, offerId);
    }

    static void opDuelOffer(StateData& s, Ctx& c, const id& inv, const Array<uint8, 512>& fr, sint64 amount, uint64 t,
        Res& r)
    {
        c.h_fid = rdId(fr, c);
        c.h_version = uint32(rdU(fr, c, 4));
        c.h_oppId = rdId(fr, c);
        c.h_ruleset = rdId(fr, c);
        c.h_timingId = uint32(rdU(fr, c, 4));
        c.h_feeId = uint32(rdU(fr, c, 4));
        c.h_stake = rdU(fr, c, 8);
        c.h_fmt = uint8(rdU(fr, c, 1));
        c.h_expires = rdU(fr, c, 8);
        c.h_fi = fighterIndex(s, c, c.h_fid);
        if (c.h_fi < 0)
        {
            setRej(r, QDOJO_UNKNOWN_FIGHTER);
            return;
        }
        authorize(s, c, c.h_fi, inv, c.h_version, r);
        if (!accepted(r))
        {
            return;
        }
        profiles(s, c, c.h_ruleset, c.h_timingId, c.h_feeId, r);
        if (!accepted(r))
        {
            return;
        }
        c.h_oi = fighterIndex(s, c, c.h_oppId);
        if (c.h_oi < 0)
        {
            setRej(r, QDOJO_UNKNOWN_FIGHTER);
            return;
        }
        if (c.h_oi == c.h_fi)
        {
            setRej(r, QDOJO_INCOMPATIBLE);
            return;
        }
        if (c.h_fmt > 2)
        {
            setRej(r, QDOJO_BAD_BODY);
            return;
        }
        if (c.h_stake < uint64(minTierStake(s, c)) || c.h_stake > uint64(QDOJO_MAX_STAKE))
        {
            setRej(r, QDOJO_BAD_AMOUNT);
            return;
        }
        if (uint64(amount) != c.h_stake)
        {
            setRej(r, QDOJO_BAD_AMOUNT);
            return;
        }
        if (!lifetimeOk(s, c.h_expires, t))
        {
            setRej(r, QDOJO_BAD_BODY);
            return;
        }
        if (s.fighters.get(c.h_fi).lock != QDOJO_L_IDLE)
        {
            setRej(r, QDOJO_FIGHTER_BUSY);
            return;
        }
        if (t < s.fighters.get(c.h_fi).cooldownUntil)
        {
            setRej(r, QDOJO_COOLDOWN);
            return;
        }
        if (openOffers(s, c) >= s.m.maxOffers)
        {
            setRej(r, QDOJO_FULL);
            return;
        }
        claim(s, c, s.fighters.get(c.h_fi).owner, r);  // the payout recipient needs a credit slot
        if (!accepted(r))
        {
            return;
        }
        openOffer(s, c, uint32(c.h_fi), inv, amount, c.h_timingId, c.h_feeId, 0, 0, t, c.h_expires, QDOJO_K_DUEL,
            s.fighters.get(c.h_oi).fighterId, c.h_fmt, QDOJO_L_DUEL_OFFER, r);
    }

    static void opDuelAccept(StateData& s, Ctx& c, const id& inv, const Array<uint8, 512>& fr, sint64 amount, uint64 t,
        Res& r)
    {
        c.h_offerId = rdU(fr, c, 8);
        c.h_fid = rdId(fr, c);
        c.h_version = uint32(rdU(fr, c, 4));
        c.h_k = offerSlot(s, c, c.h_offerId);
        if (c.h_k < 0 || s.offers.get(c.h_k).kind != QDOJO_K_DUEL)
        {
            setRej(r, QDOJO_NOT_FOUND);
            return;
        }
        if (s.offers.get(c.h_k).status == QDOJO_O_MATCHED)
        {
            setRej(r, QDOJO_ALREADY_MATCHED);
            return;
        }
        if (s.offers.get(c.h_k).status != QDOJO_O_OPEN)
        {
            setRej(r, QDOJO_EXPIRED);
            return;
        }
        if (t >= s.offers.get(c.h_k).expires || s.offers.get(c.h_k).generation != s.generation)
        {
            closeOffer(s, c, uint32(c.h_k), t >= s.offers.get(c.h_k).expires ? QDOJO_O_EXPIRED : QDOJO_O_INVALIDATED);
            setRej(r, QDOJO_EXPIRED);
            return;
        }
        if (!stillValid(s, c, uint32(c.h_k)))
        {
            closeOffer(s, c, uint32(c.h_k), QDOJO_O_INVALIDATED);
            setRej(r, QDOJO_INCOMPATIBLE);
            return;
        }
        if (c.h_fid != s.offers.get(c.h_k).opponentId)
        {
            setRej(r, QDOJO_INCOMPATIBLE);
            return;
        }
        c.h_di = fighterIndex(s, c, c.h_fid);
        if (c.h_di < 0)
        {
            setRej(r, QDOJO_UNKNOWN_FIGHTER);
            return;
        }
        authorize(s, c, c.h_di, inv, c.h_version, r);
        if (!accepted(r))
        {
            return;
        }
        if (s.fighters.get(c.h_di).lock != QDOJO_L_IDLE)
        {
            setRej(r, QDOJO_FIGHTER_BUSY);
            return;
        }
        if (t < s.fighters.get(c.h_di).cooldownUntil)
        {
            setRej(r, QDOJO_COOLDOWN);
            return;
        }
        if (amount != s.offers.get(c.h_k).amount)
        {
            setRej(r, QDOJO_BAD_AMOUNT);
            return;
        }
        if (fightsInUse(s, c) >= s.m.maxFights)
        {
            setRej(r, QDOJO_FULL);
            return;
        }
        claim(s, c, s.fighters.get(c.h_di).owner, r);
        if (!accepted(r))
        {
            return;
        }
        c.h_mk = newOfferSlot(s, c);
        if (c.h_mk < 0)
        {
            setRej(r, QDOJO_FULL);
            return;
        }
        c.h_mine = s.nextOffer;
        s.nextOffer += 1;
        setMemory(c.sc_y, 0);
        c.sc_y.used = 1;
        c.sc_y.offerId = c.h_mine;
        c.sc_y.fighterIdx = uint16(c.h_di);
        c.sc_y.fighterId = s.fighters.get(c.h_di).fighterId;
        c.sc_y.owner = s.fighters.get(c.h_di).owner;
        c.sc_y.op = s.fighters.get(c.h_di).op;
        c.sc_y.authVersion = s.fighters.get(c.h_di).authVersion;
        c.sc_y.payer = inv;
        c.sc_y.payout = s.fighters.get(c.h_di).owner;
        c.sc_y.timingId = s.offers.get(c.h_k).timingId;
        c.sc_y.feeId = s.offers.get(c.h_k).feeId;
        c.sc_y.amount = amount;
        c.sc_y.rating = s.fighters.get(c.h_di).lifetime;
        c.sc_y.created = t;
        c.sc_y.expires = s.offers.get(c.h_k).expires;
        c.sc_y.generation = s.generation;
        c.sc_y.status = QDOJO_O_MATCHED;
        c.sc_y.kind = QDOJO_K_DUEL;
        c.sc_y.escrowed = 1;
        s.offers.set(c.h_mk, c.sc_y);
        c.sc_x = s.offers.get(c.h_k);
        c.sc_x.status = QDOJO_O_MATCHED;
        s.offers.set(c.h_k, c.sc_x);
        c.h_offerId = c.sc_x.offerId;
        c.h_fmt = c.sc_x.seriesFormat;
        c.h_cs = startContest(s, c, QDOJO_M_DUEL, c.h_fmt, t, false, 0, 0, 0);
        c.h_cid = c.h_cs >= 0 ? s.contests.get(c.h_cs).contestId : 0;
        bReset(c);
        bU64(c, c.h_offerId);
        bU64(c, c.h_cid);
        emit(s, c, QDOJO_EV_DUEL_ACCEPTED);
        setOk(r, c.h_cid);
    }

    // fight_for: results c.ff_k (fight slot) and c.ff_side (0 = A, 1 = B).
    static void fightFor(const StateData& s, Ctx& c, const id& inv, uint64 fightId, uint8 roundIndex, const id& fid,
        uint32 auth, const id& rsd, Res& r)
    {
        c.ff_k = fightSlot(s, c, fightId);
        if (c.ff_k < 0)
        {
            setRej(r, archived(fightId, s.nextFight) ? QDOJO_TERMINAL : QDOJO_NOT_FOUND);
            return;
        }
        if (s.fights.get(c.ff_k).phase == QDOJO_P_DONE)
        {
            setRej(r, QDOJO_TERMINAL);
            return;
        }
        c.ff_cs = contestSlot(s, c, s.fights.get(c.ff_k).contestId);
        if (c.ff_cs < 0)
        {
            setRej(r, QDOJO_NOT_FOUND);
            return;
        }
        if (fid == s.contests.get(c.ff_cs).a.fighterId)
        {
            c.ff_side = 0;
            c.ff_part = s.contests.get(c.ff_cs).a;
        }
        else if (fid == s.contests.get(c.ff_cs).b.fighterId)
        {
            c.ff_side = 1;
            c.ff_part = s.contests.get(c.ff_cs).b;
        }
        else
        {
            setRej(r, QDOJO_UNKNOWN_FIGHTER);
            return;
        }
        if (inv != c.ff_part.op)
        {
            setRej(r, QDOJO_NOT_OPERATOR);
            return;
        }
        if (auth != c.ff_part.authVersion)
        {
            setRej(r, QDOJO_STALE_AUTH);
            return;
        }
        if (roundIndex != s.fights.get(c.ff_k).st.roundIndex)
        {
            setRej(r, QDOJO_BAD_STATE);
            return;
        }
        if (rsd != s.fights.get(c.ff_k).roundStateDigest)
        {
            setRej(r, QDOJO_BAD_STATE);
            return;
        }
        setOk(r, 0);
    }

    static void opCommit(StateData& s, Ctx& c, const id& inv, const Array<uint8, 512>& fr, sint64 amount, uint64 t, Res& r)
    {
        if (amount)
        {
            setRej(r, QDOJO_BAD_AMOUNT);
            return;
        }
        c.h_fightId = rdU(fr, c, 8);
        c.h_round = uint8(rdU(fr, c, 1));
        c.h_fid = rdId(fr, c);
        c.h_version = uint32(rdU(fr, c, 4));
        c.h_rsd = rdId(fr, c);
        c.h_commitment = rdId(fr, c);
        fightFor(s, c, inv, c.h_fightId, c.h_round, c.h_fid, c.h_version, c.h_rsd, r);
        if (!accepted(r))
        {
            return;
        }
        c.h_fight = s.fights.get(c.ff_k);
        if (c.h_fight.phase != QDOJO_P_COMMIT || t <= c.h_fight.startTick)
        {
            setRej(r, QDOJO_WRONG_PHASE);
            return;
        }
        if (t > c.h_fight.commitLast)
        {
            setRej(r, QDOJO_LATE);
            return;
        }
        if (c.h_fight.committed.get(c.ff_side))
        {
            if (c.h_fight.commitment.get(c.ff_side) == c.h_commitment)
            {
                setDup(r, c.h_fight.fightId);
                return;
            }
            setRej(r, QDOJO_ALREADY_COMMITTED);
            return;
        }
        c.h_fight.committed.set(c.ff_side, 1);
        c.h_fight.commitment.set(c.ff_side, c.h_commitment);
        s.fights.set(c.ff_k, c.h_fight);
        bReset(c);
        bU64(c, c.h_fight.fightId);
        bU64(c, c.h_fight.st.roundIndex);
        bId(c, c.h_fid);
        bId(c, c.h_commitment);
        emit(s, c, QDOJO_EV_COMMITTED);
        setOk(r, c.h_fight.fightId);
    }

    // Commitment = SHA256("qdojo/combat/commit/v1\0" || network_id || contract_id || fight_id u64 ||
    //   round_index u8 || context_digest || round_state_digest || fighter_id || operator ||
    //   auth_version u32 || salt[32] || plan[7])
    static id commitmentOf(const StateData& s, Ctx& c, const Fight& f, const Participant& p, const Array<uint8, 512>& fr,
        uint32 saltAt, uint32 planAt)
    {
        shaInit(c.sha);
        shaTag(c.sha, QDOJO_TAG_COMMIT_0, QDOJO_TAG_COMMIT_1, QDOJO_TAG_COMMIT_2, QDOJO_TAG_COMMIT_3, QDOJO_TAG_COMMIT_LEN);
        shaId(c.sha, s.m.networkId);
        shaId(c.sha, s.m.contractId);
        shaLe(c.sha, f.fightId, 8);
        shaByte(c.sha, f.st.roundIndex);
        shaId(c.sha, f.contextDigest);
        shaId(c.sha, f.roundStateDigest);
        shaId(c.sha, p.fighterId);
        shaId(c.sha, p.op);
        shaLe(c.sha, p.authVersion, 4);
        for (c.cm_i = 0; c.cm_i < 32; c.cm_i++)
        {
            shaByte(c.sha, fr.get(saltAt + c.cm_i));
        }
        for (c.cm_i = 0; c.cm_i < 7; c.cm_i++)
        {
            shaByte(c.sha, fr.get(planAt + c.cm_i));
        }
        return shaFinal(c.sha);
    }

    static void opReveal(StateData& s, Ctx& c, const id& inv, const Array<uint8, 512>& fr, sint64 amount, uint64 t, Res& r)
    {
        if (amount)
        {
            setRej(r, QDOJO_BAD_AMOUNT);
            return;
        }
        c.h_fightId = rdU(fr, c, 8);
        c.h_round = uint8(rdU(fr, c, 1));
        c.h_fid = rdId(fr, c);
        c.h_version = uint32(rdU(fr, c, 4));
        c.h_rsd = rdId(fr, c);
        c.h_saltAt = rdRaw(c, 32);
        c.h_planAt = rdRaw(c, 7);
        fightFor(s, c, inv, c.h_fightId, c.h_round, c.h_fid, c.h_version, c.h_rsd, r);
        if (!accepted(r))
        {
            return;
        }
        c.h_fight = s.fights.get(c.ff_k);
        if (c.h_fight.phase == QDOJO_P_COMMIT && t <= c.h_fight.commitLast)
        {
            setRej(r, QDOJO_WRONG_PHASE);
            return;
        }
        if (c.h_fight.phase != QDOJO_P_REVEAL)
        {
            setRej(r, QDOJO_WRONG_PHASE);
            return;
        }
        if (t > c.h_fight.revealLast)
        {
            setRej(r, QDOJO_LATE);
            return;
        }
        c.h_expected = commitmentOf(s, c, c.h_fight, c.ff_part, fr, c.h_saltAt, c.h_planAt);
        if (!c.h_fight.committed.get(c.ff_side) || c.h_fight.commitment.get(c.ff_side) != c.h_expected)
        {
            setRej(r, QDOJO_BAD_COMMITMENT);
            return;
        }
        setMemory(c.h_plan, 0);
        for (c.h_i = 0; c.h_i < 6; c.h_i++)
        {
            c.h_plan.actions.set(c.h_i, fr.get(c.h_planAt + c.h_i));
        }
        c.h_plan.powerSlot = fr.get(c.h_planAt + 6);
        if (!validatePlan(c.h_plan, c.ff_side == 0 ? c.h_fight.st.a : c.h_fight.st.b))
        {
            setRej(r, QDOJO_BAD_PLAN);
            return;
        }
        c.h_salt = idFromFrame(fr, c.h_saltAt);
        if (c.h_fight.revealed.get(c.ff_side))
        {
            c.h_same = c.h_fight.salt.get(c.ff_side) == c.h_salt && c.h_fight.plan.get(c.ff_side).powerSlot == c.h_plan.powerSlot;
            for (c.h_i = 0; c.h_i < 6; c.h_i++)
            {
                if (c.h_fight.plan.get(c.ff_side).actions.get(c.h_i) != c.h_plan.actions.get(c.h_i))
                {
                    c.h_same = 0;
                }
            }
            if (c.h_same)
            {
                setDup(r, c.h_fight.fightId);
            }
            else
            {
                setRej(r, QDOJO_ALREADY_REVEALED);
            }
            return;
        }
        c.h_fight.revealed.set(c.ff_side, 1);
        c.h_fight.salt.set(c.ff_side, c.h_salt);
        c.h_fight.plan.set(c.ff_side, c.h_plan);
        s.fights.set(c.ff_k, c.h_fight);
        bReset(c);
        bU64(c, c.h_fight.fightId);
        bU64(c, c.h_fight.st.roundIndex);
        bId(c, c.ff_part.fighterId);
        bFrameBytes(c, fr, c.h_saltAt, 32);
        bFrameBytes(c, fr, c.h_planAt, 7);
        emit(s, c, QDOJO_EV_REVEALED);
        setOk(r, c.h_fight.fightId);
    }

    static void opAdvance(StateData& s, Ctx& c, const Array<uint8, 512>& fr, sint64 amount, uint64 t, Res& r)
    {
        if (amount)
        {
            setRej(r, QDOJO_BAD_AMOUNT);
            return;
        }
        c.h_kind = uint8(rdU(fr, c, 1));
        c.h_target = rdU(fr, c, 8);
        if (c.h_kind == 1)
        {
            c.h_k = offerSlot(s, c, c.h_target);
            if (c.h_k < 0)
            {
                if (archived(c.h_target, s.nextOffer))
                {
                    setOk(r, c.h_target);
                }
                else
                {
                    setRej(r, QDOJO_NOT_FOUND);
                }
                return;
            }
            if (s.offers.get(c.h_k).status == QDOJO_O_OPEN
                && (t >= s.offers.get(c.h_k).expires || s.offers.get(c.h_k).generation != s.generation))
            {
                closeOffer(s, c, uint32(c.h_k), t >= s.offers.get(c.h_k).expires ? QDOJO_O_EXPIRED : QDOJO_O_INVALIDATED);
            }
            setOk(r, c.h_target);
            return;
        }
        if (c.h_kind == 2)
        {
            if (fightSlot(s, c, c.h_target) >= 0 || archived(c.h_target, s.nextFight))
            {
                setOk(r, c.h_target);
            }
            else
            {
                setRej(r, QDOJO_NOT_FOUND);
            }
            return;
        }
        if (c.h_kind == 3)
        {
            if (cupSlot(s, c, c.h_target) >= 0 || archived(c.h_target, s.nextCup))
            {
                setOk(r, c.h_target);
            }
            else
            {
                setRej(r, QDOJO_NOT_FOUND);
            }
            return;
        }
        setRej(r, QDOJO_BAD_BODY);
    }

    // op_withdraw, first half: debit first (spec.md section 5). When
    // c.wd_pending is set, the entry point transfers c.wd_value and then calls
    // withdrawEnd with the outcome.
    static void withdrawBegin(StateData& s, Ctx& c, const id& inv, sint64 amount, Res& r)
    {
        c.wd_pending = 0;
        if (amount)
        {
            setRej(r, QDOJO_BAD_AMOUNT);
            return;
        }
        c.wd_a = accountIndex(s, c, inv);
        c.wd_value = c.wd_a >= 0 ? s.accounts.get(c.wd_a).credit : 0;
        if (!c.wd_value)
        {
            setOk(r, 0);
            return;
        }
        c.wd_acct = s.accounts.get(c.wd_a);
        c.wd_acct.credit = 0;
        s.accounts.set(c.wd_a, c.wd_acct);
        s.creditCount -= 1;
        s.balance = subI64(s, s.balance, c.wd_value);
        s.paidOut = addI64(s, s.paidOut, c.wd_value);
        c.wd_pending = 1;
        setOk(r, 0);
    }

    static void withdrawEnd(StateData& s, Ctx& c, const id& inv, bit transferred, Res& r)
    {
        if (!transferred)
        {
            // Restore on a reported failure.
            s.balance = addI64(s, s.balance, c.wd_value);
            s.paidOut = subI64(s, s.paidOut, c.wd_value);
            credit(s, c, inv, c.wd_value);
            bReset(c);
            bId(c, inv);
            bU64(c, uint64(c.wd_value));
            emit(s, c, QDOJO_EV_WITHDRAW_FAILED);
            setRej(r, QDOJO_TRANSFER_FAILED);
            return;
        }
        bReset(c);
        bId(c, inv);
        bU64(c, uint64(c.wd_value));
        emit(s, c, QDOJO_EV_WITHDRAWN);
        setOk(r, 0);
    }

    static void opAdminCreateCup(StateData& s, Ctx& c, const id& inv, const Array<uint8, 512>& fr, sint64 amount,
        uint64 t, Res& r)
    {
        c.h_ruleset = rdId(fr, c);
        setMemory(c.h_d, 0);
        c.h_d.timingId = uint32(rdU(fr, c, 4));
        c.h_d.feeId = uint32(rdU(fr, c, 4));
        c.h_entryFee = rdU(fr, c, 8);
        c.h_d.registrationClose = rdU(fr, c, 8);
        c.h_d.minEntrants = uint8(rdU(fr, c, 1));
        c.h_d.maxEntrants = uint8(rdU(fr, c, 1));
        c.h_d.levelTicks = uint16(rdU(fr, c, 2));
        c.h_d.firstLevelDelay = uint16(rdU(fr, c, 2));
        c.h_d.checkinTicks = uint16(rdU(fr, c, 2));
        c.h_d.replayDelay = uint16(rdU(fr, c, 2));
        if (inv != s.m.admin)
        {
            setRej(r, QDOJO_NOT_OWNER);
            return;
        }
        profiles(s, c, c.h_ruleset, c.h_d.timingId, c.h_d.feeId, r);
        if (!accepted(r))
        {
            return;
        }
        if (liveCups(s, c) >= s.m.maxCups)
        {
            setRej(r, QDOJO_FULL);
            return;
        }
        if (!(4 <= c.h_d.minEntrants && c.h_d.minEntrants <= c.h_d.maxEntrants && c.h_d.maxEntrants <= s.m.maxCupEntrants))
        {
            setRej(r, QDOJO_BAD_BODY);
            return;
        }
        if (!(0 < c.h_entryFee && c.h_entryFee <= uint64(QDOJO_MAX_STAKE)) || c.h_d.registrationClose <= t)
        {
            setRej(r, QDOJO_BAD_BODY);
            return;
        }
        // Every scheduled boundary must fall on a tick END_TICK examines.
        if (c.h_d.checkinTicks < 1 || c.h_d.firstLevelDelay < 2 || c.h_d.replayDelay < 1)
        {
            setRej(r, QDOJO_BAD_BODY);
            return;
        }
        c.h_d.entryFee = sint64(c.h_entryFee);
        c.h_t = timingIdx(s, c, c.h_d.timingId);
        c.h_cr = uint64(s.m.timing.get(c.h_t).commitTicks) + s.m.timing.get(c.h_t).revealTicks;
        if (uint64(c.h_d.checkinTicks) + 7 * 3 * c.h_cr + c.h_d.replayDelay + 3 * 3 * c.h_cr + 2 > c.h_d.levelTicks)
        {
            setRej(r, QDOJO_INCOMPATIBLE);
            return;
        }
        c.h_k = newCupSlot(s, c);
        if (c.h_k < 0)
        {
            setRej(r, QDOJO_FULL);
            return;
        }
        c.h_cid = s.nextCup;
        s.nextCup += 1;
        setMemory(c.cupW, 0);
        c.cupW.used = 1;
        c.cupW.cupId = c.h_cid;
        c.cupW.d = c.h_d;
        c.cupW.sponsor = inv;
        c.cupW.sponsorship = amount;
        c.cupW.generation = s.generation;
        c.cupW.created = t;
        c.cupW.status = QDOJO_CUP_REGISTRATION;
        c.cupW.hasPot = amount ? 1 : 0;
        s.cups.set(c.h_k, c.cupW);
        bReset(c);
        bU64(c, c.h_cid);
        bU64(c, c.h_entryFee);
        bU64(c, uint64(amount));
        bU64(c, c.h_d.registrationClose);
        emit(s, c, QDOJO_EV_CUP_CREATED);
        setOk(r, c.h_cid);
    }

    static void opCupRegister(StateData& s, Ctx& c, const id& inv, const Array<uint8, 512>& fr, sint64 amount, uint64 t,
        Res& r)
    {
        c.h_cupId = rdU(fr, c, 8);
        c.h_fid = rdId(fr, c);
        c.h_version = uint32(rdU(fr, c, 4));
        c.h_k = cupSlot(s, c, c.h_cupId);
        if (c.h_k < 0)
        {
            setRej(r, archived(c.h_cupId, s.nextCup) ? QDOJO_WRONG_PHASE : QDOJO_NOT_FOUND);
            return;
        }
        c.cupW = s.cups.get(c.h_k);
        if (c.cupW.status != QDOJO_CUP_REGISTRATION || t >= c.cupW.d.registrationClose)
        {
            setRej(r, QDOJO_WRONG_PHASE);
            return;
        }
        c.h_fi = fighterIndex(s, c, c.h_fid);
        if (c.h_fi < 0)
        {
            setRej(r, QDOJO_UNKNOWN_FIGHTER);
            return;
        }
        authorize(s, c, c.h_fi, inv, c.h_version, r);
        if (!accepted(r))
        {
            return;
        }
        c.h_f = s.fighters.get(c.h_fi);
        if (c.h_f.houseNpc)
        {
            setRej(r, QDOJO_INCOMPATIBLE);
            return;
        }
        if (amount != c.cupW.d.entryFee)
        {
            setRej(r, QDOJO_BAD_AMOUNT);
            return;
        }
        if (c.h_f.lock != QDOJO_L_IDLE)
        {
            setRej(r, QDOJO_FIGHTER_BUSY);
            return;
        }
        if (t < c.h_f.cooldownUntil)
        {
            setRej(r, QDOJO_COOLDOWN);
            return;
        }
        if (c.cupW.nEntries >= c.cupW.d.maxEntrants || c.cupW.nEntries >= QDOJO_CAP_CUP_ENTRANTS)
        {
            setRej(r, QDOJO_FULL);
            return;
        }
        if (represented(s, c, c.cupW, c.h_f.owner, c.h_f.op, false, NULL_ID))
        {
            setRej(r, QDOJO_INCOMPATIBLE);
            return;
        }
        claim(s, c, c.h_f.owner, r);
        if (!accepted(r))
        {
            return;
        }
        c.h_entry.fighterId = c.h_f.fighterId;
        c.h_entry.payer = inv;
        c.h_entry.owner = c.h_f.owner;
        c.h_entry.op = c.h_f.op;
        c.h_entry.fighterIdx = uint16(c.h_fi);
        c.h_entry.amount = amount;
        c.cupW.entries.set(c.cupW.nEntries, c.h_entry);
        c.cupW.nEntries = uint8(c.cupW.nEntries + 1);
        c.cupW.hasPot = 1;
        s.cups.set(c.h_k, c.cupW);
        lockFighter(s, c, uint32(c.h_fi), QDOJO_L_TOURNAMENT, c.cupW.cupId);
        bReset(c);
        bU64(c, c.cupW.cupId);
        bId(c, c.h_f.fighterId);
        bU64(c, uint64(amount));
        emit(s, c, QDOJO_EV_CUP_ENTRY);
        setOk(r, c.cupW.cupId);
    }

    static void opCupWithdraw(StateData& s, Ctx& c, const id& inv, const Array<uint8, 512>& fr, sint64 amount, uint64 t,
        Res& r)
    {
        if (amount)
        {
            setRej(r, QDOJO_BAD_AMOUNT);
            return;
        }
        c.h_cupId = rdU(fr, c, 8);
        c.h_fid = rdId(fr, c);
        c.h_k = cupSlot(s, c, c.h_cupId);
        if (c.h_k < 0)
        {
            setRej(r, archived(c.h_cupId, s.nextCup) ? QDOJO_WRONG_PHASE : QDOJO_NOT_FOUND);
            return;
        }
        c.cupW = s.cups.get(c.h_k);
        if (c.cupW.status != QDOJO_CUP_REGISTRATION || t >= c.cupW.d.registrationClose)
        {
            setRej(r, QDOJO_WRONG_PHASE);
            return;
        }
        c.h_ei = -1;
        for (c.h_i = 0; c.h_i < QDOJO_CAP_CUP_ENTRANTS; c.h_i++)
        {
            if (c.h_i < c.cupW.nEntries && c.cupW.entries.get(c.h_i).fighterId == c.h_fid)
            {
                c.h_ei = sint32(c.h_i);
            }
        }
        if (c.h_ei < 0)
        {
            setRej(r, QDOJO_NOT_FOUND);
            return;
        }
        c.h_entry = c.cupW.entries.get(c.h_ei);
        if (inv != s.fighters.get(c.h_entry.fighterIdx).owner && inv != s.fighters.get(c.h_entry.fighterIdx).op
            && inv != c.h_entry.payer)
        {
            setRej(r, QDOJO_NOT_OWNER);
            return;
        }
        for (c.h_i = 0; c.h_i + 1 < QDOJO_CAP_CUP_ENTRANTS; c.h_i++)
        {
            if (sint32(c.h_i) >= c.h_ei && c.h_i + 1 < c.cupW.nEntries)
            {
                c.cupW.entries.set(c.h_i, c.cupW.entries.get(c.h_i + 1));
            }
        }
        c.cupW.nEntries = uint8(c.cupW.nEntries - 1);
        credit(s, c, c.h_entry.payer, c.h_entry.amount);
        if (c.cupW.nEntries == 0 && c.cupW.sponsorship == 0)
        {
            c.cupW.hasPot = 0;
        }
        s.cups.set(c.h_k, c.cupW);
        lockFighter(s, c, c.h_entry.fighterIdx, QDOJO_L_IDLE, 0);
        bReset(c);
        bU64(c, c.cupW.cupId);
        bId(c, c.h_entry.fighterId);
        bId(c, c.h_entry.payer);
        bU64(c, uint64(c.h_entry.amount));
        emit(s, c, QDOJO_EV_CUP_WITHDRAWN);
        setOk(r, c.cupW.cupId);
    }

    static void opCupCheckIn(StateData& s, Ctx& c, const id& inv, const Array<uint8, 512>& fr, sint64 amount, uint64 t,
        Res& r)
    {
        if (amount)
        {
            setRej(r, QDOJO_BAD_AMOUNT);
            return;
        }
        c.h_cupId = rdU(fr, c, 8);
        c.h_pairingId = rdU(fr, c, 8);
        c.h_fid = rdId(fr, c);
        c.h_version = uint32(rdU(fr, c, 4));
        c.h_k = cupSlot(s, c, c.h_cupId);
        if (c.h_k < 0)
        {
            setRej(r, archived(c.h_cupId, s.nextCup) ? QDOJO_WRONG_PHASE : QDOJO_NOT_FOUND);
            return;
        }
        c.cupW = s.cups.get(c.h_k);
        if (c.cupW.status != QDOJO_CUP_RUNNING || !(c.h_pairingId >= 1 && c.h_pairingId <= c.cupW.nPairings))
        {
            setRej(r, QDOJO_WRONG_PHASE);
            return;
        }
        c.h_p = c.cupW.pairings.get(c.h_pairingId - 1);
        if (c.h_p.status != QDOJO_PS_SCHEDULED)
        {
            setRej(r, QDOJO_WRONG_PHASE);
            return;
        }
        if (!(c.cupW.levelStart <= t && t < c.cupW.levelStart + c.cupW.d.checkinTicks) || c.h_p.level != c.cupW.level)
        {
            setRej(r, QDOJO_WRONG_PHASE);
            return;
        }
        c.h_isA = c.h_p.hasA && c.h_p.a == c.h_fid;
        c.h_isB = c.h_p.hasB && c.h_p.b == c.h_fid;
        if (!c.h_isA && !c.h_isB)
        {
            setRej(r, QDOJO_UNKNOWN_FIGHTER);
            return;
        }
        c.h_fi = fighterIndex(s, c, c.h_fid);
        if (c.h_fi < 0)
        {
            setRej(r, QDOJO_UNKNOWN_FIGHTER);
            return;
        }
        authorize(s, c, c.h_fi, inv, c.h_version, r);
        if (!accepted(r))
        {
            return;
        }
        if (represented(s, c, c.cupW, s.fighters.get(c.h_fi).owner, s.fighters.get(c.h_fi).op, true, c.h_fid))
        {
            setRej(r, QDOJO_INCOMPATIBLE);
            return;
        }
        if ((c.h_isA && c.h_p.checkedA) || (c.h_isB && c.h_p.checkedB))
        {
            setDup(r, c.h_p.pairingId);
            return;
        }
        if (t < s.fighters.get(c.h_fi).cooldownUntil)
        {
            setRej(r, QDOJO_COOLDOWN);  // check-in observes the fault cooldown
            return;
        }
        claim(s, c, s.fighters.get(c.h_fi).owner, r);  // a transferred finalist's owner may be new
        if (!accepted(r))
        {
            return;
        }
        if (c.h_isA)
        {
            c.h_p.checkedA = 1;
        }
        else
        {
            c.h_p.checkedB = 1;
        }
        c.cupW.pairings.set(c.h_pairingId - 1, c.h_p);
        s.cups.set(c.h_k, c.cupW);
        bReset(c);
        bU64(c, c.cupW.cupId);
        bU64(c, c.h_p.pairingId);
        bId(c, c.h_fid);
        emit(s, c, QDOJO_EV_CUP_CHECKED_IN);
        setOk(r, c.h_p.pairingId);
    }

    // Every handler except Withdraw (which needs a transfer, see Dispatch).
    static void runHandler(StateData& s, Ctx& c, const id& inv, const Array<uint8, 512>& fr, uint16 op, sint64 amount,
        uint64 t, Res& r)
    {
        c.rAt = QDOJO_FRAME_HEADER;
        switch (op)
        {
        case QDOJO_OP_REGISTER_FIGHTER:
            opRegisterFighter(s, c, inv, fr, amount, r);
            break;
        case QDOJO_OP_SET_OPERATOR:
            opSetOperator(s, c, inv, fr, amount, r);
            break;
        case QDOJO_OP_QUEUE_ENTER:
            opQueueEnter(s, c, inv, fr, amount, t, r);
            break;
        case QDOJO_OP_QUEUE_CANCEL:
            if (amount)
            {
                setRej(r, QDOJO_BAD_AMOUNT);
            }
            else
            {
                cancel(s, c, inv, rdU(fr, c, 8), QDOJO_K_RANKED, r);
            }
            break;
        case QDOJO_OP_DUEL_OFFER:
            opDuelOffer(s, c, inv, fr, amount, t, r);
            break;
        case QDOJO_OP_DUEL_ACCEPT:
            opDuelAccept(s, c, inv, fr, amount, t, r);
            break;
        case QDOJO_OP_COMMIT:
            opCommit(s, c, inv, fr, amount, t, r);
            break;
        case QDOJO_OP_REVEAL:
            opReveal(s, c, inv, fr, amount, t, r);
            break;
        case QDOJO_OP_ADVANCE:
            opAdvance(s, c, fr, amount, t, r);
            break;
        case QDOJO_OP_CUP_REGISTER:
            opCupRegister(s, c, inv, fr, amount, t, r);
            break;
        case QDOJO_OP_CUP_WITHDRAW:
            opCupWithdraw(s, c, inv, fr, amount, t, r);
            break;
        case QDOJO_OP_CUP_CHECK_IN:
            opCupCheckIn(s, c, inv, fr, amount, t, r);
            break;
        case QDOJO_OP_DUEL_CANCEL:
            if (amount)
            {
                setRej(r, QDOJO_BAD_AMOUNT);
            }
            else
            {
                cancel(s, c, inv, rdU(fr, c, 8), QDOJO_K_DUEL, r);
            }
            break;
        case QDOJO_OP_ADMIN_REGISTER_ASSET:
            opAdminRegisterAsset(s, c, inv, fr, amount, r);
            break;
        case QDOJO_OP_ADMIN_CREATE_CUP:
            opAdminCreateCup(s, c, inv, fr, amount, t, r);
            break;
        case QDOJO_OP_ADMIN_RETIRE_RULESET:
            opAdminRetireRuleset(s, c, inv, fr, amount, r);
            break;
        default:
            setRej(r, QDOJO_BAD_OPCODE);
            break;
        }
    }

    // protocol.md section 5: ensure_service(T). Returns false if ticks run backwards.
    static bit ensureService(StateData& s, Ctx& c, uint64 t)
    {
        if (t < s.lastObserved)
        {
            return false;
        }
        if (t == s.lastObserved)
        {
            return true;
        }
        if (t - 1 != s.lastServiced)
        {
            s.generation += 1;
            bReset(c);
            bU64(c, s.generation);
            bU64(c, s.lastServiced);
            bU64(c, t);
            emit(s, c, QDOJO_EV_SERVICE_GAP);
        }
        s.lastObserved = t;
        s.tick = t;
        return true;
    }

    // =========================================================== entry-point plumbing
    struct Dispatch_output
    {
        uint8 code;
        uint16 op;
        uint64 target;
        sint64 refunded;
    };

    // After a rejection: refunded = the attachment (contract.py _refund), and
    // c.dp_refund tells the entry point whether a direct payback transfer is due.
    static void dispatchReject(StateData& s, Ctx& c, const id& inv, sint64 amount, uint8 code, uint16 op, uint64 target,
        Dispatch_output& out)
    {
        out.code = code;
        out.op = op;
        out.target = target;
        out.refunded = amount;
        c.dp_refund = refundBegin(s, c, inv, amount);
    }

    static void dispatchFinish(StateData& s, Ctx& c, const id& inv, sint64 amount, Dispatch_output& out)
    {
        c.dp_stage = 0;
        if (!accepted(c.dp_r))
        {
            dispatchReject(s, c, inv, amount, c.dp_r.code, c.fr_op, 0, out);
            return;
        }
        if (c.fr_op != QDOJO_OP_ADVANCE)
        {
            c.dp_acct = accountGetOrAlloc(s, c, inv);
            if (c.dp_acct >= 0)
            {
                c.dp_a = s.accounts.get(c.dp_acct);
                c.dp_a.hasNonce = 1;
                c.dp_a.nonce = c.fr_nonce;
                c.dp_a.digest = c.dp_digest;
                c.dp_a.lastTarget = c.dp_r.target;
                c.dp_a.lastOp = c.fr_op;
                s.accounts.set(c.dp_acct, c.dp_a);
            }
            else
            {
                s.faults.accountOverflow += 1;
            }
        }
        out.code = c.dp_r.code;
        out.op = c.fr_op;
        out.target = c.dp_r.target;
        out.refunded = 0;
    }

    // combat_contract.h dispatch(), up to the first transfer. Leaves c.dp_stage = 1
    // when a withdrawal transfer is due, and c.dp_refund = 1 when a refund payback is due.
    static void dispatchBegin(StateData& s, Ctx& c, const Array<uint8, 512>& fr, const id& inv, sint64 amount, uint64 t,
        Dispatch_output& out)
    {
        c.dp_stage = 0;
        c.dp_refund = 0;
        out.code = QDOJO_HOST_ERROR;
        out.op = 0;
        out.target = 0;
        out.refunded = 0;
        if (amount < 0 || s.balance > QDOJO_I64_MAX - amount || t < s.lastObserved)
        {
            return;
        }
        ensureService(s, c, t);
        s.balance += amount;
        c.dp_code = decodeFrame(fr, c);
        if (c.dp_code != QDOJO_OK)
        {
            dispatchReject(s, c, inv, amount, c.dp_code, 0, 0, out);
            return;
        }
        c.dp_digest = frameDigest(fr, c);
        if (c.fr_op == QDOJO_OP_ADVANCE && c.fr_nonce != 0)
        {
            dispatchReject(s, c, inv, amount, QDOJO_BAD_BODY, c.fr_op, 0, out);
            return;
        }
        if (c.fr_op != QDOJO_OP_ADVANCE)
        {
            // Only registry-backed users and account holders get state slots (protocol.md section 3).
            if (!eligible(s, c, inv, c.fr_op, fr))
            {
                dispatchReject(s, c, inv, amount, QDOJO_NOT_OWNER, c.fr_op, 0, out);
                return;
            }
            claim(s, c, inv, c.dp_r);
            if (!accepted(c.dp_r))
            {
                dispatchReject(s, c, inv, amount, c.dp_r.code, c.fr_op, 0, out);
                return;
            }
            c.dp_acct = accountIndex(s, c, inv);
            if (c.dp_acct >= 0 && s.accounts.get(c.dp_acct).hasNonce)
            {
                if (c.fr_nonce == s.accounts.get(c.dp_acct).nonce)
                {
                    if (s.accounts.get(c.dp_acct).digest == c.dp_digest)
                    {
                        dispatchReject(s, c, inv, amount, QDOJO_DUPLICATE, c.fr_op, s.accounts.get(c.dp_acct).lastTarget, out);
                        return;
                    }
                    dispatchReject(s, c, inv, amount, QDOJO_NONCE_CONFLICT, c.fr_op, 0, out);
                    return;
                }
                if (c.fr_nonce < s.accounts.get(c.dp_acct).nonce)
                {
                    dispatchReject(s, c, inv, amount, QDOJO_STALE, c.fr_op, 0, out);
                    return;
                }
            }
            if (c.fr_nonce == 0)
            {
                dispatchReject(s, c, inv, amount, QDOJO_STALE, c.fr_op, 0, out);
                return;
            }
        }
        if (c.fr_op == QDOJO_OP_WITHDRAW)
        {
            withdrawBegin(s, c, inv, amount, c.dp_r);
            if (c.wd_pending)
            {
                c.dp_stage = 1;
                return;
            }
        }
        else
        {
            runHandler(s, c, inv, fr, c.fr_op, amount, t, c.dp_r);
        }
        dispatchFinish(s, c, inv, amount, out);
    }

    struct EndTickVars
    {
        Array<uint64, 128> ids;
        uint32 n;
        uint32 i;
        sint32 k;
        uint32 ranked;
        Contest con;
    };

    // END_TICK: service voids, deadlines and resolution, duel expiry, matching, cups.
    static void endTick(StateData& s, Ctx& c, EndTickVars& e, uint64 t)
    {
        if (!ensureService(s, c, t))
        {
            return;
        }
        // Objective service gaps void unfinished work captured under an older generation.
        e.n = 0;
        for (e.i = 0; e.i < QDOJO_CAP_CONTEST_SLOTS; e.i++)
        {
            if (s.contests.get(e.i).used && s.contests.get(e.i).status == QDOJO_C_ACTIVE
                && s.contests.get(e.i).generation != s.generation && s.contests.get(e.i).mode != QDOJO_M_CUP)
            {
                e.ids.set(e.n, s.contests.get(e.i).contestId);
                e.n += 1;
            }
        }
        sortU64(e.ids, e.n, c);
        for (e.i = 0; e.i < QDOJO_CAP_CONTEST_SLOTS; e.i++)
        {
            if (e.i >= e.n)
            {
                break;
            }
            e.k = contestSlot(s, c, e.ids.get(e.i));
            if (e.k >= 0)
            {
                e.con = s.contests.get(e.k);
                voidContest(s, c, e.con, t);
                s.contests.set(e.k, e.con);
            }
        }
        e.n = 0;
        for (e.i = 0; e.i < QDOJO_CAP_OFFER_SLOTS; e.i++)
        {
            if (s.offers.get(e.i).used && s.offers.get(e.i).status == QDOJO_O_OPEN && s.offers.get(e.i).generation != s.generation)
            {
                e.ids.set(e.n, s.offers.get(e.i).offerId);
                e.n += 1;
            }
        }
        sortU64(e.ids, e.n, c);
        for (e.i = 0; e.i < QDOJO_CAP_OFFER_SLOTS; e.i++)
        {
            if (e.i >= e.n)
            {
                break;
            }
            e.k = offerSlot(s, c, e.ids.get(e.i));
            if (e.k >= 0)
            {
                closeOffer(s, c, uint32(e.k), QDOJO_O_INVALIDATED);
            }
        }
        e.n = 0;
        for (e.i = 0; e.i < QDOJO_CAP_CUP_SLOTS; e.i++)
        {
            if (s.cups.get(e.i).used
                && (s.cups.get(e.i).status == QDOJO_CUP_REGISTRATION || s.cups.get(e.i).status == QDOJO_CUP_RUNNING)
                && s.cups.get(e.i).generation != s.generation)
            {
                e.ids.set(e.n, s.cups.get(e.i).cupId);
                e.n += 1;
            }
        }
        sortU64(e.ids, e.n, c);
        for (e.i = 0; e.i < QDOJO_CAP_CUP_SLOTS; e.i++)
        {
            if (e.i >= e.n)
            {
                break;
            }
            e.k = cupSlot(s, c, e.ids.get(e.i));
            if (e.k >= 0)
            {
                c.cupW = s.cups.get(e.k);
                abortCup(s, c, c.cupW, QDOJO_AB_SERVICE_VOID);
                s.cups.set(e.k, c.cupW);
            }
        }
        // Deadlines and resolution, at most max_fights, in fight_id order. The
        // set is fixed before processing: fights created now start next tick.
        e.n = 0;
        for (e.i = 0; e.i < QDOJO_CAP_FIGHT_SLOTS; e.i++)
        {
            if (s.fights.get(e.i).used && s.fights.get(e.i).phase != QDOJO_P_DONE)
            {
                e.ids.set(e.n, s.fights.get(e.i).fightId);
                e.n += 1;
            }
        }
        sortU64(e.ids, e.n, c);
        for (e.i = 0; e.i < QDOJO_CAP_FIGHT_SLOTS; e.i++)
        {
            if (e.i >= e.n || e.i >= s.m.maxFights)
            {
                break;
            }
            e.k = fightSlot(s, c, e.ids.get(e.i));
            if (e.k >= 0 && s.fights.get(e.k).phase != QDOJO_P_DONE)
            {
                fightTick(s, c, uint32(e.k), t);
            }
        }
        e.n = 0;
        for (e.i = 0; e.i < QDOJO_CAP_OFFER_SLOTS; e.i++)
        {
            if (s.offers.get(e.i).used && s.offers.get(e.i).status == QDOJO_O_OPEN && s.offers.get(e.i).kind == QDOJO_K_DUEL
                && t >= s.offers.get(e.i).expires)
            {
                e.ids.set(e.n, s.offers.get(e.i).offerId);
                e.n += 1;
            }
        }
        sortU64(e.ids, e.n, c);
        for (e.i = 0; e.i < QDOJO_CAP_OFFER_SLOTS; e.i++)
        {
            if (e.i >= e.n)
            {
                break;
            }
            e.k = offerSlot(s, c, e.ids.get(e.i));
            if (e.k >= 0)
            {
                closeOffer(s, c, uint32(e.k), QDOJO_O_EXPIRED);
            }
        }
        if (mod<uint64>(t, uint64(s.m.matchInterval)) == 0)
        {
            // Expired ranked offers are closed and refunded on every matching
            // tick, even when no pass runs, in offer_id order.
            e.n = 0;
            for (e.i = 0; e.i < QDOJO_CAP_OFFER_SLOTS; e.i++)
            {
                if (s.offers.get(e.i).used && s.offers.get(e.i).status == QDOJO_O_OPEN
                    && s.offers.get(e.i).kind == QDOJO_K_RANKED && t >= s.offers.get(e.i).expires)
                {
                    e.ids.set(e.n, s.offers.get(e.i).offerId);
                    e.n += 1;
                }
            }
            sortU64(e.ids, e.n, c);
            for (e.i = 0; e.i < QDOJO_CAP_OFFER_SLOTS; e.i++)
            {
                if (e.i >= e.n)
                {
                    break;
                }
                e.k = offerSlot(s, c, e.ids.get(e.i));
                if (e.k >= 0)
                {
                    closeOffer(s, c, uint32(e.k), QDOJO_O_EXPIRED);
                }
            }
            e.ranked = 0;
            for (e.i = 0; e.i < QDOJO_CAP_OFFER_SLOTS; e.i++)
            {
                if (s.offers.get(e.i).used && s.offers.get(e.i).status == QDOJO_O_OPEN && s.offers.get(e.i).kind == QDOJO_K_RANKED)
                {
                    e.ranked += 1;
                }
            }
            if (e.ranked >= 2)
            {
                matching(s, c, t);
            }
        }
        e.n = 0;
        for (e.i = 0; e.i < QDOJO_CAP_CUP_SLOTS; e.i++)
        {
            if (s.cups.get(e.i).used)
            {
                e.ids.set(e.n, s.cups.get(e.i).cupId);
                e.n += 1;
            }
        }
        sortU64(e.ids, e.n, c);
        for (e.i = 0; e.i < QDOJO_CAP_CUP_SLOTS; e.i++)
        {
            if (e.i >= e.n)
            {
                break;
            }
            e.k = cupSlot(s, c, e.ids.get(e.i));
            if (e.k >= 0)
            {
                cupTick(s, c, uint32(e.k), t);
            }
        }
        s.lastServiced = t;
    }

    // Compiled-in manifest. TEST PROFILE ONLY: the identities are the synthetic
    // test keys of the committed journals (fuzz-1 header), not release values.
    // The reviewed release manifest replaces this before any proposal.
    static void loadDefaultManifest(StateData& s, Ctx& c, const id& self)
    {
        setMemory(s.m, 0);
        s.m.networkId = id(0xd0d0d0d0d0d0d0d0ULL, 0xd0d0d0d0d0d0d0d0ULL, 0xd0d0d0d0d0d0d0d0ULL, 0xd0d0d0d0d0d0d0d0ULL);
        s.m.contractId = self;
        s.m.admin = id(0x012fe519b42f69e5ULL, 0x8e842cbf92770eceULL, 0x7261f994e78c6b9eULL, 0x1f22bba056878139ULL);
        s.m.rulesetDigest = id(QDOJO_RULESET_0, QDOJO_RULESET_1, QDOJO_RULESET_2, QDOJO_RULESET_3);
        setMemory(c.in_tp, 0);
        c.in_tp.profileId = 1;
        c.in_tp.commitTicks = 24;
        c.in_tp.revealTicks = 12;
        c.in_tp.used = 1;
        s.m.timing.set(0, c.in_tp);
        setMemory(c.in_fp, 0);
        c.in_fp.profileId = 1;
        c.in_fp.rakeBps = 500;
        c.in_fp.houseBps = 6000;
        c.in_fp.devBps = 1000;
        c.in_fp.shareBps = 3000;
        c.in_fp.house = id(0x4e9c8feedeb2fc1aULL, 0x43ba12519e9c4835ULL, 0xb0c6e36824626962ULL, 0xfa1e4aa6aafca645ULL);
        c.in_fp.dev = id(0x4c3beb15ecc0b84eULL, 0xc00fd4a3d672919dULL, 0x37897f8070728769ULL, 0xf93e0e05d6e58816ULL);
        c.in_fp.share = id(0xfd881c815fefcd1eULL, 0xc4b92cca7ff61183ULL, 0x3b4caa1e7b03042aULL, 0x48eb438782b99763ULL);
        c.in_fp.used = 1;
        s.m.fees.set(0, c.in_fp);
        setMemory(c.in_tier, 0);
        c.in_tier.tierId = 1;
        c.in_tier.stake = 1000;
        c.in_tier.used = 1;
        s.m.tiers.set(0, c.in_tier);
        s.m.genesisTick = 0;
        s.m.genesisEpoch = 1;
        s.m.ticksPerEpoch = 10000;
        s.m.seasonStartEpoch = 1;
        s.m.seasonEpochs = 4;
        s.m.seasonCloseoutTicks = 1200;
        s.m.maxFighters = 1024;
        s.m.maxAccounts = 2048;
        s.m.maxOffers = 64;
        s.m.maxFights = 16;
        s.m.maxCups = 4;
        s.m.maxCupEntrants = 16;
        s.m.eventRing = 2048;
        s.m.matchInterval = 4;
        s.m.offerLifetimeLo = 40;
        s.m.offerLifetimeHi = 1200;
        s.m.cooldownTicks = 240;
        s.m.faultsPerEpoch = 3;
        s.m.pairStartsPerEpoch = QDOJO_PAIR_STARTS_PER_EPOCH;
        s.m.pairRematchTicks = QDOJO_PAIR_REMATCH_TICKS;
    }

    // combat_contract.h init(). initOk stays 0 for a manifest the compiled
    // capacities or ruleset cannot serve; every entry point is then inert.
    static void initialize(StateData& s, Ctx& c, uint64 constructionTick, const id& self)
    {
        if (!s.manifestLoaded)
        {
            loadDefaultManifest(s, c, self);
        }
        s.initOk = 0;
        if (s.m.rulesetDigest != id(QDOJO_RULESET_0, QDOJO_RULESET_1, QDOJO_RULESET_2, QDOJO_RULESET_3))
        {
            return;
        }
        if (s.m.maxFighters > QDOJO_CAP_FIGHTERS || s.m.maxAccounts > QDOJO_CAP_ACCOUNTS
            || s.m.maxOffers > QDOJO_CAP_OPEN_OFFERS || s.m.maxFights > QDOJO_CAP_FIGHTS || s.m.maxCups > QDOJO_CAP_CUPS
            || s.m.maxCupEntrants > QDOJO_CAP_CUP_ENTRANTS || s.m.eventRing > QDOJO_CAP_EVENTS || s.m.eventRing == 0
            || s.m.ticksPerEpoch <= 0 || s.m.seasonEpochs <= 0 || s.m.matchInterval == 0 || s.m.faultsPerEpoch == 0)
        {
            return;
        }
        c.in_any = 0;
        for (c.in_i = 0; c.in_i < QDOJO_CAP_TIERS; c.in_i++)
        {
            if (s.m.tiers.get(c.in_i).used)
            {
                c.in_any = 1;
            }
        }
        if (!c.in_any)
        {
            return;
        }
        for (c.in_i = 0; c.in_i < QDOJO_CAP_FEES; c.in_i++)
        {
            if (!s.m.fees.get(c.in_i).used)
            {
                continue;
            }
            if (s.m.fees.get(c.in_i).rakeBps > QDOJO_BPS
                || uint32(s.m.fees.get(c.in_i).houseBps) + s.m.fees.get(c.in_i).devBps + s.m.fees.get(c.in_i).shareBps
                    != uint32(QDOJO_BPS))
            {
                return;
            }
        }
        s.generation = 1;
        s.lastServiced = constructionTick;
        s.lastObserved = constructionTick;
        s.tick = constructionTick;
        s.nextOffer = 1;
        s.nextContest = 1;
        s.nextFight = 1;
        s.nextCup = 1;
        // The admin and the fee recipients hold account slots from construction.
        addSlot(s, c, s.m.admin);
        for (c.in_i = 0; c.in_i < QDOJO_CAP_FEES; c.in_i++)
        {
            if (!s.m.fees.get(c.in_i).used)
            {
                continue;
            }
            addSlot(s, c, s.m.fees.get(c.in_i).house);
            addSlot(s, c, s.m.fees.get(c.in_i).dev);
            addSlot(s, c, s.m.fees.get(c.in_i).share);
        }
        s.eventDigest = id(QDOJO_GENESIS_0, QDOJO_GENESIS_1, QDOJO_GENESIS_2, QDOJO_GENESIS_3);
        s.initOk = 1;
    }

    // =========================================================== scratch for every helper
    // One instance per entry point (in its locals). Fields are grouped by the
    // helper that owns them; the call graph has no recursion, so no helper is
    // live twice. Shared by leaves: lk_i (lookups), bw_i (body writers).
    struct Ctx
    {
        Sha256 sha;
        Body body;
        Event ev;
        uint32 bw_i;
        uint64 bs_lo;
        uint64 bs_hi;
        uint8 bs_len;
        uint32 em_i;
        uint32 lk_i;
        sint32 ns_best;
        sint64 mts_best;
        Asset own_asset;
        AssetOwnershipIterator own_iter;
        uint32 own_count;
        id own_owner;
        sint32 ga_i;
        Account ga_a;
        sint32 cr_i;
        Account cr_a;
        uint16 pf_lo;
        uint16 pf_hi;
        uint32 pf_start;
        sint32 pf_reuse;
        uint32 pf_k;
        uint32 pf_i;
        PairRecord pf_p;
        sint32 hs_a;
        sint32 as_i;
        Account as_a;
        uint32 el_i;
        id el_fid;
        id el_owner;
        id au_owner;
        uint32 cnt_n;
        uint32 so_i;
        uint32 so_j;
        uint64 so_x;
        // engine
        uint16 fs_lost;
        uint16 fs_strain;
        uint16 fs_gain;
        uint16 fs_st;
        Half eg_ha;
        Half eg_hb;
        uint16 eg_baseA;
        uint16 eg_baseB;
        uint16 eg_dealtA;
        uint16 eg_dealtB;
        EFighter eg_na;
        EFighter eg_nb;
        uint8 eg_terminal;
        EState eg_s;
        EState eg_end;
        uint8 eg_executed;
        uint8 eg_beat;
        uint8 eg_err;
        // fights, contests, settlement
        uint64 nf_fid;
        sint32 nf_ti;
        sint32 nf_fe;
        sint32 nf_slot;
        Fight nf_f;
        Fighter lf_f;
        Offer sc_x;
        Offer sc_y;
        Offer sc_tmp;
        Offer sc_o;
        uint32 sc_season;
        uint64 sc_cid;
        sint32 sc_slot;
        sint32 sc_sx;
        sint32 sc_sy;
        Contest sc_con;
        sint64 fa_e;
        Fighter fa_f;
        uint64 fa_until;
        sint64 rd_exp;
        sint64 rd_raw;
        sint64 rd_mag;
        sint64 rd_d;
        sint64 rd_m;
        uint32 ao_i;
        SeasonSlot rs_sl;
        Fighter rt_fa;
        Fighter rt_fb;
        sint64 rt_score;
        sint64 rt_d;
        SeasonSlot rt_sl;
        FeeProfile sw_fp;
        sint64 sw_gross;
        sint64 sw_rake;
        sint64 sw_dev;
        sint64 sw_share;
        sint64 sr_a;
        sint64 sr_b;
        sint32 fc_fe;
        sint32 fc_p;
        PairRecord fc_pr;
        sint32 vc_fs;
        sint32 vc_p;
        Fight vc_f;
        PairRecord vc_pr;
        sint32 ef_cs;
        sint32 ef_k;
        Contest ef_con;
        Fight ft_f;
        // cups
        Cup cupA;       // short get/edit/set of a cup (endFight, cupPairingDone)
        Cup cupW;       // working copy of the cup being processed (cupTick, aborts, cup handlers)
        uint32 ch_i;
        uint32 ci_i;
        uint32 rp_i;
        uint16 rp_fi;
        uint32 bp_i;
        bit bp_isA;
        bit bp_isB;
        uint32 rl_i;
        uint32 rc_i;
        uint32 ab_i;
        Contest ab_con;
        sint32 ab_fs;
        Fight ab_f;
        uint32 sl_need;
        uint32 sl_i;
        uint32 sl_inUse;
        uint32 sl_free;
        uint16 sl_bit;
        Pairing sl_p;
        uint32 lr_n;
        uint32 lr_i;
        uint32 lr_j;
        uint8 lr_x;
        uint32 lr_size;
        uint32 lr_len;
        uint32 lr_m;
        uint32 lr_seed;
        uint32 lr_levels;
        Array<uint8, 16> lr_order;
        Array<uint8, 16> lr_pos;
        Array<uint8, 16> lr_next;
        id lr_digest;
        sint32 po_fi;
        bit spc_final;
        Pairing spc_p;
        sint32 spc_cs;
        Contest spc_con;
        uint32 slp_i;
        Pairing slp_p;
        sint32 pd_k;
        Pairing pd_p;
        sint64 pc_entryGross;
        sint64 pc_gross;
        sint64 pc_rake;
        sint64 pc_dev;
        sint64 pc_share;
        uint32 pc_i;
        id pc_recipient;
        sint32 pc_fi;
        sint32 pc_fe;
        FeeProfile pc_fp;
        uint32 al_ns;
        uint32 al_i;
        uint32 al_side;
        sint32 al_first;
        Pairing al_p;
        Pairing al_fin;
        uint8 al_alive;
        Array<id, 16> al_survivors;
        Array<uint8, 16> al_aliveFlags;
        uint8 al_has;
        id al_fid;
        sint32 al_fi;
        uint64 ct_checkinEnd;
        uint32 ct_i;
        uint8 ct_all;
        // matching
        uint64 cp_gap;
        sint32 cp_p;
        id sv_owner;
        Offer co_o;
        uint8 co_wasEscrowed;
        sint64 mt_epoch;
        uint32 mt_n;
        uint32 mt_i;
        uint32 mt_j;
        uint32 mt_nl;
        uint32 mt_matched;
        sint32 mt_k;
        Array<uint64, 128> mt_ids;
        Array<uint32, 64> mt_live;
        Array<uint8, 64> mt_taken;
        Offer mt_o;
        sint32 mt_p;
        PairRecord mt_pr;
        // frames and handlers
        uint16 fr_op;
        uint16 fr_flags;
        uint16 fr_len;
        uint64 fr_nonce;
        sint32 fr_want;
        uint32 df_i;
        uint32 rAt;
        id h_fid;
        id h_owner;
        id h_newOp;
        id h_ruleset;
        id h_oppId;
        id h_rsd;
        id h_commitment;
        id h_expected;
        id h_salt;
        uint32 h_version;
        uint8 h_npc;
        sint32 h_a;
        uint32 h_i;
        RegistryAsset h_asset;
        uint32 h_at;
        sint32 h_fi;
        sint32 h_k;
        sint32 h_t;
        sint32 h_oi;
        sint32 h_di;
        sint32 h_mk;
        sint32 h_cs;
        sint32 h_ei;
        Fighter h_f;
        uint32 h_timingId;
        uint32 h_feeId;
        uint16 h_tierId;
        uint16 h_maxGap;
        uint64 h_expires;
        bit h_have;
        uint64 h_stake;
        uint8 h_fmt;
        uint64 h_offerId;
        uint64 h_mine;
        uint64 h_cid;
        sint32 ff_k;
        sint32 ff_cs;
        uint32 ff_side;
        Participant ff_part;
        uint64 h_fightId;
        uint8 h_round;
        Fight h_fight;
        uint32 cm_i;
        sint32 oo_k;
        uint64 oo_oid;
        Offer oo_o;
        uint32 h_saltAt;
        uint32 h_planAt;
        EPlan h_plan;
        uint8 h_same;
        uint8 h_kind;
        uint64 h_target;
        uint8 wd_pending;
        sint32 wd_a;
        sint64 wd_value;
        Account wd_acct;
        CupDescriptor h_d;
        uint64 h_entryFee;
        uint64 h_cr;
        uint64 h_cupId;
        uint64 h_pairingId;
        CupEntry h_entry;
        Pairing h_p;
        bit h_isA;
        bit h_isB;
        // dispatch and init
        uint8 dp_stage;
        uint8 dp_refund;
        uint8 dp_code;
        id dp_digest;
        sint32 dp_acct;
        Account dp_a;
        Res dp_r;
        uint8 in_any;
        uint32 in_i;
        TimingProfile in_tp;
        FeeProfile in_fp;
        Tier in_tier;
    };

    // =========================================================== the single user procedure
    struct Dispatch_input
    {
        Array<uint8, 512> frame;    // protocol.md section 1; the runtime pads/truncates to 512
    };

    struct Dispatch_locals
    {
        Ctx c;
        id inv;
        sint64 amount;
        bit transferred;
    };

    // One confirmed transaction: the invocator, the attachment (counted here
    // only; there is no POST_INCOMING_TRANSFER), and one 512-byte frame.
    PUBLIC_PROCEDURE_WITH_LOCALS(Dispatch)
    {
        locals.inv = qpi.invocator();
        locals.amount = qpi.invocationReward();
        if (!state.get().initOk)
        {
            // An unusable manifest: hand the attachment straight back.
            output.code = QDOJO_HOST_ERROR;
            if (locals.amount > 0)
            {
                qpi.transfer(locals.inv, locals.amount);
            }
            return;
        }
        dispatchBegin(state.mut(), locals.c, input.frame, locals.inv, locals.amount, qpi.tick(), output);
        if (locals.c.dp_stage == 1)
        {
            // Host::transfer for a withdrawal; a negative result is a reported failure.
            locals.transferred = qpi.transfer(locals.inv, locals.c.wd_value) >= 0;
            withdrawEnd(state.mut(), locals.c, locals.inv, locals.transferred, locals.c.dp_r);
            dispatchFinish(state.mut(), locals.c, locals.inv, locals.amount, output);
        }
        if (locals.c.dp_refund)
        {
            // Direct payback of a rejected attachment to an identity without a slot.
            if (qpi.transfer(locals.inv, locals.amount) < 0)
            {
                refundFailed(state.mut(), locals.c, locals.inv, locals.amount);
            }
        }
    }

    // =========================================================== tick callbacks
    struct BEGIN_TICK_locals
    {
        Ctx c;
    };

    BEGIN_TICK_WITH_LOCALS()
    {
        if (!state.get().initOk)
        {
            return;
        }
        ensureService(state.mut(), locals.c, qpi.tick());
    }

    struct END_TICK_locals
    {
        Ctx c;
        EndTickVars e;
    };

    // COST NOTE: END_TICK writes lastServiced every tick, so Core rehashes the
    // whole state every tick (sizeof(StateData) ~1.4 MB); see README.md.
    END_TICK_WITH_LOCALS()
    {
        if (!state.get().initOk)
        {
            return;
        }
        endTick(state.mut(), locals.c, locals.e, qpi.tick());
    }

    struct INITIALIZE_locals
    {
        Ctx c;
    };

    INITIALIZE_WITH_LOCALS()
    {
        initialize(state.mut(), locals.c, qpi.tick(), SELF);
    }

    // =========================================================== read-only queries
    struct GetService_input
    {
        uint8 unused;
    };
    struct GetService_output
    {
        uint64 generation;
        uint64 lastServiced;
        uint64 lastObserved;
        uint64 eventSeq;
        id eventDigest;
        sint64 balance;
        sint64 paidOut;
        uint8 initOk;
    };
    PUBLIC_FUNCTION(GetService)
    {
        output.generation = state.get().generation;
        output.lastServiced = state.get().lastServiced;
        output.lastObserved = state.get().lastObserved;
        output.eventSeq = state.get().eventSeq;
        output.eventDigest = state.get().eventDigest;
        output.balance = state.get().balance;
        output.paidOut = state.get().paidOut;
        output.initOk = state.get().initOk;
    }

    // Sum of every liability bucket (spec.md section 5): open-offer escrow,
    // contest escrow, cup reserve, withdrawable credits. Must equal balance.
    struct GetLedger_input
    {
        uint8 unused;
    };
    struct GetLedger_output
    {
        sint64 balance;
        sint64 liabilities;
        sint64 overflowCredit;
        uint32 creditCount;
        uint32 nSlots;
        uint32 negativeCredits;
        Faults faults;
    };
    struct GetLedger_locals
    {
        uint32 i;
        uint32 k;
    };
    PUBLIC_FUNCTION_WITH_LOCALS(GetLedger)
    {
        output.balance = state.get().balance;
        output.overflowCredit = state.get().overflowCredit;
        output.creditCount = state.get().creditCount;
        output.nSlots = state.get().nSlots;
        output.faults = state.get().faults;
        output.liabilities = state.get().overflowCredit;
        for (locals.i = 0; locals.i < QDOJO_CAP_OFFER_SLOTS; locals.i++)
        {
            if (state.get().offers.get(locals.i).used && state.get().offers.get(locals.i).escrowed)
            {
                output.liabilities += state.get().offers.get(locals.i).amount;
            }
        }
        for (locals.i = 0; locals.i < QDOJO_CAP_CONTEST_SLOTS; locals.i++)
        {
            if (state.get().contests.get(locals.i).used && state.get().contests.get(locals.i).hasPot)
            {
                output.liabilities += state.get().contests.get(locals.i).potA + state.get().contests.get(locals.i).potB;
            }
        }
        for (locals.i = 0; locals.i < QDOJO_CAP_CUP_SLOTS; locals.i++)
        {
            if (!state.get().cups.get(locals.i).used || !state.get().cups.get(locals.i).hasPot)
            {
                continue;
            }
            output.liabilities += state.get().cups.get(locals.i).sponsorship;
            for (locals.k = 0; locals.k < QDOJO_CAP_CUP_ENTRANTS; locals.k++)
            {
                if (locals.k < state.get().cups.get(locals.i).nEntries)
                {
                    output.liabilities += state.get().cups.get(locals.i).entries.get(locals.k).amount;
                }
            }
        }
        for (locals.i = 0; locals.i < QDOJO_CAP_ACCOUNTS; locals.i++)
        {
            if (state.get().accounts.get(locals.i).used)
            {
                output.liabilities += state.get().accounts.get(locals.i).credit;
                if (state.get().accounts.get(locals.i).credit < 0)
                {
                    output.negativeCredits += 1;
                }
            }
        }
    }

    struct GetAccount_input
    {
        id who;
    };
    struct GetAccount_output
    {
        sint64 credit;
        uint8 hasNonce;
        uint64 nonce;
        uint8 slot;
    };
    struct GetAccount_locals
    {
        uint32 i;
    };
    PUBLIC_FUNCTION_WITH_LOCALS(GetAccount)
    {
        for (locals.i = 0; locals.i < QDOJO_CAP_ACCOUNTS; locals.i++)
        {
            if (state.get().accounts.get(locals.i).used && state.get().accounts.get(locals.i).who == input.who)
            {
                output.credit = state.get().accounts.get(locals.i).credit;
                output.hasNonce = state.get().accounts.get(locals.i).hasNonce;
                output.nonce = state.get().accounts.get(locals.i).nonce;
                output.slot = state.get().accounts.get(locals.i).slot;
            }
        }
    }

    // contract.py events_page: retained events with seq > after, at most 64.
    struct GetEvents_input
    {
        uint64 after;
        uint32 limit;
    };
    struct GetEvents_output
    {
        uint32 count;
        Array<Event, 64> events;
    };
    struct GetEvents_locals
    {
        uint64 oldest;
        uint64 seq;
        uint32 i;
        uint32 limit;
    };
    PUBLIC_FUNCTION_WITH_LOCALS(GetEvents)
    {
        locals.limit = input.limit > QDOJO_EVENTS_PAGE ? QDOJO_EVENTS_PAGE : input.limit;
        locals.oldest = state.get().eventSeq > state.get().m.eventRing ? state.get().eventSeq - state.get().m.eventRing + 1 : 1;
        locals.seq = input.after + 1 > locals.oldest ? input.after + 1 : locals.oldest;
        for (locals.i = 0; locals.i < QDOJO_EVENTS_PAGE; locals.i++)
        {
            if (output.count >= locals.limit || locals.seq > state.get().eventSeq)
            {
                break;
            }
            output.events.set(output.count, state.get().events.get(mod<uint64>(locals.seq - 1, uint64(state.get().m.eventRing))));
            output.count += 1;
            locals.seq += 1;
        }
    }

    struct GetFighter_input
    {
        id fighterId;
    };
    struct GetFighter_output
    {
        uint8 found;
        Fighter fighter;
    };
    struct GetFighter_locals
    {
        uint32 i;
    };
    PUBLIC_FUNCTION_WITH_LOCALS(GetFighter)
    {
        for (locals.i = 0; locals.i < QDOJO_CAP_FIGHTERS; locals.i++)
        {
            if (locals.i >= state.get().nFighters)
            {
                break;
            }
            if (state.get().fighters.get(locals.i).fighterId == input.fighterId)
            {
                output.found = 1;
                output.fighter = state.get().fighters.get(locals.i);
                return;
            }
        }
    }

    struct GetOffer_input
    {
        uint64 offerId;
    };
    struct GetOffer_output
    {
        uint8 found;
        Offer offer;
    };
    struct GetOffer_locals
    {
        uint32 i;
    };
    PUBLIC_FUNCTION_WITH_LOCALS(GetOffer)
    {
        for (locals.i = 0; locals.i < QDOJO_CAP_OFFER_SLOTS; locals.i++)
        {
            if (state.get().offers.get(locals.i).used && state.get().offers.get(locals.i).offerId == input.offerId)
            {
                output.found = 1;
                output.offer = state.get().offers.get(locals.i);
                return;
            }
        }
    }

    struct GetFight_input
    {
        uint64 fightId;
    };
    struct GetFight_output
    {
        uint8 found;
        Fight fight;
    };
    struct GetFight_locals
    {
        uint32 i;
    };
    PUBLIC_FUNCTION_WITH_LOCALS(GetFight)
    {
        for (locals.i = 0; locals.i < QDOJO_CAP_FIGHT_SLOTS; locals.i++)
        {
            if (state.get().fights.get(locals.i).used && state.get().fights.get(locals.i).fightId == input.fightId)
            {
                output.found = 1;
                output.fight = state.get().fights.get(locals.i);
                return;
            }
        }
    }

    struct GetContest_input
    {
        uint64 contestId;
    };
    struct GetContest_output
    {
        uint8 found;
        Contest contest;
    };
    struct GetContest_locals
    {
        uint32 i;
    };
    PUBLIC_FUNCTION_WITH_LOCALS(GetContest)
    {
        for (locals.i = 0; locals.i < QDOJO_CAP_CONTEST_SLOTS; locals.i++)
        {
            if (state.get().contests.get(locals.i).used && state.get().contests.get(locals.i).contestId == input.contestId)
            {
                output.found = 1;
                output.contest = state.get().contests.get(locals.i);
                return;
            }
        }
    }

    struct GetCup_input
    {
        uint64 cupId;
    };
    struct GetCup_output
    {
        uint8 found;
        Cup cup;
    };
    struct GetCup_locals
    {
        uint32 i;
    };
    PUBLIC_FUNCTION_WITH_LOCALS(GetCup)
    {
        for (locals.i = 0; locals.i < QDOJO_CAP_CUP_SLOTS; locals.i++)
        {
            if (state.get().cups.get(locals.i).used && state.get().cups.get(locals.i).cupId == input.cupId)
            {
                output.found = 1;
                output.cup = state.get().cups.get(locals.i);
                return;
            }
        }
    }

    // contract.py season_standings, bounded: the season must be the current or
    // the previous one (older seasons live in the exported history).
    struct StandingRow
    {
        id fighterId;
        uint16 rating;
        uint16 defeated;
        uint32 wins;
        uint32 fights;
        uint8 qualified;
    };

    static bit standingBefore(const StandingRow& x, const StandingRow& y)
    {
        if (x.rating != y.rating)
        {
            return x.rating > y.rating;
        }
        if (x.defeated != y.defeated)
        {
            return x.defeated > y.defeated;
        }
        if (x.wins != y.wins)
        {
            return x.wins > y.wins;
        }
        return idCmp(x.fighterId, y.fighterId) < 0;
    }

    static bit standingRow(const StateData& s, const Fighter& f, uint32 season, uint64 t, StandingRow& row)
    {
        if (season == 0 || f.seasons.get(mod<uint32>(season, 2U)).season != season || !f.seasons.get(mod<uint32>(season, 2U)).hasStats)
        {
            return false;
        }
        row.fighterId = f.fighterId;
        row.rating = f.seasons.get(mod<uint32>(season, 2U)).hasRating ? f.seasons.get(mod<uint32>(season, 2U)).rating
                                                              : uint16(QDOJO_RATING_INITIAL);
        row.defeated = f.seasons.get(mod<uint32>(season, 2U)).defeated;
        row.wins = f.seasons.get(mod<uint32>(season, 2U)).wins;
        row.fights = f.seasons.get(mod<uint32>(season, 2U)).fights;
        row.qualified = (f.seasons.get(mod<uint32>(season, 2U)).fights >= 12 && f.seasons.get(mod<uint32>(season, 2U)).opponents >= 4
                            && f.seasons.get(mod<uint32>(season, 2U)).defeated >= 3
                            && f.seasons.get(mod<uint32>(season, 2U)).finalEpochFights >= 3 && f.placement >= QDOJO_PLACEMENT_FIGHTS
                            && f.suspendedEpoch != epochOf(s, t))
            ? 1
            : 0;
        return true;
    }

    struct GetStandings_input
    {
        uint32 season;
    };
    struct GetStandings_output
    {
        uint32 season;
        uint8 isFinal;
        uint8 status;       // 0 NO_CHAMPION, 1 CHAMPION, 2 PLAYOFF
        id champion;
        uint32 nRows;       // all rows with stats
        uint32 nPage;
        Array<StandingRow, 16> page;
        uint32 nPlayoff;
        Array<id, 16> playoff;
    };
    struct GetStandings_locals
    {
        uint64 t;
        sint64 firstNext;
        sint64 closes;
        bit havePrev;
        bit found;
        bit any;
        StandingRow prev;
        StandingRow best;
        StandingRow row;
        StandingRow top;
        uint32 pass;
        uint32 i;
        uint32 tied;
    };
    PUBLIC_FUNCTION_WITH_LOCALS(GetStandings)
    {
        locals.t = qpi.tick();
        output.season = input.season;
        locals.firstNext = state.get().m.seasonStartEpoch + sint64(input.season) * state.get().m.seasonEpochs;
        locals.closes = state.get().m.genesisTick + (locals.firstNext - state.get().m.genesisEpoch) * state.get().m.ticksPerEpoch
            + state.get().m.seasonCloseoutTicks;
        output.isFinal = sint64(locals.t) >= locals.closes ? 1 : 0;
        // Page: repeated selection of the next row in standings order.
        for (locals.pass = 0; locals.pass < QDOJO_STANDINGS_PAGE; locals.pass++)
        {
            locals.found = false;
            for (locals.i = 0; locals.i < QDOJO_CAP_FIGHTERS; locals.i++)
            {
                if (locals.i >= state.get().nFighters)
                {
                    break;
                }
                if (!standingRow(state.get(), state.get().fighters.get(locals.i), input.season, locals.t, locals.row))
                {
                    continue;
                }
                if (locals.pass == 0)
                {
                    output.nRows += 1;
                }
                if (locals.havePrev && !standingBefore(locals.prev, locals.row))
                {
                    continue;
                }
                if (!locals.found || standingBefore(locals.row, locals.best))
                {
                    locals.best = locals.row;
                    locals.found = true;
                }
            }
            if (!locals.found)
            {
                break;
            }
            output.page.set(output.nPage, locals.best);
            output.nPage += 1;
            locals.prev = locals.best;
            locals.havePrev = true;
        }
        // Champion: the unique qualified row with the best (rating, defeated, wins).
        for (locals.i = 0; locals.i < QDOJO_CAP_FIGHTERS; locals.i++)
        {
            if (locals.i >= state.get().nFighters)
            {
                break;
            }
            if (!standingRow(state.get(), state.get().fighters.get(locals.i), input.season, locals.t, locals.row)
                || !locals.row.qualified)
            {
                continue;
            }
            if (!locals.any || standingBefore(locals.row, locals.top))
            {
                locals.top = locals.row;
            }
            locals.any = true;
        }
        if (!locals.any)
        {
            return;
        }
        for (locals.i = 0; locals.i < QDOJO_CAP_FIGHTERS; locals.i++)
        {
            if (locals.i >= state.get().nFighters)
            {
                break;
            }
            if (!standingRow(state.get(), state.get().fighters.get(locals.i), input.season, locals.t, locals.row)
                || !locals.row.qualified)
            {
                continue;
            }
            if (locals.row.rating == locals.top.rating && locals.row.defeated == locals.top.defeated
                && locals.row.wins == locals.top.wins)
            {
                if (output.nPlayoff < QDOJO_STANDINGS_PAGE)
                {
                    output.playoff.set(output.nPlayoff, locals.row.fighterId);
                    output.nPlayoff += 1;
                }
                locals.tied += 1;
            }
        }
        if (locals.tied == 1)
        {
            output.status = 1;
            output.champion = locals.top.fighterId;
            output.nPlayoff = 0;
        }
        else
        {
            output.status = 2;
        }
    }

    REGISTER_USER_FUNCTIONS_AND_PROCEDURES()
    {
        // Placeholder IDs: the real numbers are deployment values from the
        // reviewed release manifest (protocol.md section 1).
        REGISTER_USER_PROCEDURE(Dispatch, 1);
        REGISTER_USER_FUNCTION(GetService, 1);
        REGISTER_USER_FUNCTION(GetAccount, 2);
        REGISTER_USER_FUNCTION(GetEvents, 3);
        REGISTER_USER_FUNCTION(GetFighter, 4);
        REGISTER_USER_FUNCTION(GetOffer, 5);
        REGISTER_USER_FUNCTION(GetFight, 6);
        REGISTER_USER_FUNCTION(GetContest, 7);
        REGISTER_USER_FUNCTION(GetCup, 8);
        REGISTER_USER_FUNCTION(GetStandings, 9);
        REGISTER_USER_FUNCTION(GetLedger, 10);
    }
};
