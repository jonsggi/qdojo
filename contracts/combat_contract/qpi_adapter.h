// QDOJO: QPI-shaped wrapper sketch for the combat contract.
//
// STATUS: NOT COMPILED. NOT RUN THROUGH THE CONTRACT VERIFIER.
//   Written against qubic/core commit e3ef766686e5d69a2bdd17a12213f1d21d145778
//   (2026-09-23): doc/contracts.md, src/qpi/qpi.h, qpi_types.h, qpi_context.h,
//   qpi_assets.h, qpi_containers.h, qpi_macros.h, src/qubic.cpp (tick
//   callbacks) and src/contracts/{QDuel,Pulse,Qswap}.h for idioms.
//   Every QPI name used below was checked against those headers. Nothing
//   here has been compiled inside Core, so signatures may still be wrong in
//   detail. See README.md, "What remains before a real Core build".
//
// WHAT THIS IS. The deployable contract must be written in Core's restricted
// dialect: no `#include`, no pointers, no `[` `]`, no `/` `%` (use div/mod),
// no string or char literals, no stack locals (use *_locals structs), no
// `...`, no `__`, no globals, and every global name prefixed QDOJO.
// combat_contract.h (the parity-tested state machine) uses all of those
// freely, so it cannot be dropped into Core. This file fixes the SHAPE the
// transliteration takes and writes out the parts that touch QPI for real:
//   - StateData with QPI containers at the compiled capacities
//   - Dispatch(Array<uint8,512>) as the single user procedure, its
//     prologue (originator check, attachment, service heartbeat, frame
//     header) and its epilogue (nonce record, refund)
//   - BEGIN_TICK / END_TICK
//   - the two host capabilities: asset owner (AssetOwnershipIterator) and
//     payout (qpi.transfer)
//   - read-only query functions
// Bodies marked "TRANSLITERATE detail::x" are to be carried over one to one
// from combat_contract.h, then the parity journals rerun against the result
// inside Core's GoogleTest harness (test/contract_qdojo.cpp, not written).
//
// Transliteration rules (mechanical):
//   x[i]            -> x.get(i) / x.set(i, v) on Array<T, 2^N>
//   a / b, a % b    -> div(a, b), mod(a, b)
//   local variables -> fields of the procedure's _locals struct
//   helper calls    -> PRIVATE_PROCEDURE_WITH_LOCALS + CALL(...); the Core
//                      nesting limit is 10 (doc/contracts.md), and the
//                      deepest reference path (END_TICK > fight_tick >
//                      resolve > end_fight > finish_contest >
//                      cup_pairing_done > pairing_event > emit > sha update >
//                      compress) is exactly 10 deep: flatten emit/sha first
//   id bytes        -> copyMemory(Array<uint8,32>, id); never m256i
//                      operator< (it orders by u64 words, not by bytes as
//                      the protocol's "smaller fighter ID" requires)
//   event strings   -> the canonical body's tag-2 ASCII strings ("COMBAT",
//                      "FORFEIT", ...) become QDOJO_STR_* byte constants,
//                      because string literals are forbidden
//   Host::owner_of  -> QDOJO::OwnerOf below
//   Host::transfer  -> QDOJO::PayOut below

using namespace QPI;

// ---- capacities (all powers of two, as Array<T, L> requires) ----------------
constexpr uint64 QDOJO_CAP_FIGHTERS = 1024;
constexpr uint64 QDOJO_CAP_ACCOUNTS = 2048;
constexpr uint64 QDOJO_CAP_ASSETS = 2048;
constexpr uint64 QDOJO_CAP_OFFER_SLOTS = 128;
constexpr uint64 QDOJO_CAP_CONTEST_SLOTS = 32;
constexpr uint64 QDOJO_CAP_FIGHT_SLOTS = 32;
constexpr uint64 QDOJO_CAP_CUP_SLOTS = 8;
constexpr uint64 QDOJO_CAP_CUP_ENTRANTS = 16;
constexpr uint64 QDOJO_CAP_PAIRINGS = 16;
constexpr uint64 QDOJO_CAP_PAIRS = 4096;
constexpr uint64 QDOJO_CAP_EVENTS = 2048;
constexpr uint64 QDOJO_EVENT_BODY_MAX = 128;
constexpr uint64 QDOJO_FRAME_LEN = 512;
constexpr uint64 QDOJO_MAX_BODY = 487;
constexpr uint8 QDOJO_FRAME_SENTINEL = 0xA5;

// Result codes (docs/protocol.md section 6); same numbers as combat_contract.h.
constexpr uint8 QDOJO_OK = 0;
constexpr uint8 QDOJO_DUPLICATE = 1;
constexpr uint8 QDOJO_BAD_FRAME = 2;
constexpr uint8 QDOJO_BAD_OPCODE = 3;
constexpr uint8 QDOJO_FULL = 12;
constexpr uint8 QDOJO_NONCE_CONFLICT = 13;
constexpr uint8 QDOJO_STALE = 14;
constexpr uint8 QDOJO_TRANSFER_FAILED = 29;
constexpr uint8 QDOJO_NOT_DIRECT = 30;   // PROPOSED: invocator != originator (protocol.md section 1); not in the reference

// Frame magic "QDC1" as a little-endian u32 (no char literals allowed).
constexpr uint32 QDOJO_MAGIC_QDC1 = 0x31434451;

struct QDOJO2
{
};

struct QDOJO : public ContractBase
{
    // ---- records: the combat_contract.h structs with id / Array fields ---------
    struct Account
    {
        sint64 credit;
        uint8 hasNonce;
        uint16 lastOp;
        uint64 nonce;
        id frameDigest;          // SHA-256 of the last accepted frame, stored as 32 bytes
        uint64 lastTarget;
    };

    struct FighterAsset
    {
        id fighterId;
        uint32 registryVersion;
        uint8 houseNpc;
        // OPEN (protocol gap): the Qubic asset behind fighterId. spec.md section 4
        // maps a fighter to (issuer, asset name, one unit), but
        // AdminRegisterAsset (opcode 100) carries only fighter_id,
        // registry_version and house_npc. The issuance must be added to the
        // admin descriptor before OwnerOf can be implemented for real.
        Asset issuance;
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
        uint32 recW, recD, recL, recFW, recFL;
        // two SeasonSlots (current, previous) as in combat_contract.h, each with
        // Array<uint64, 16> defeatedBits: TRANSLITERATE
    };

    struct Event
    {
        uint64 seq;
        uint64 tick;
        uint16 type;
        uint16 len;
        id digest;
        Array<uint8, QDOJO_EVENT_BODY_MAX> body;
    };

    // Offer, Participant, Contest, Fight, CupEntry, Pairing, Cup, PairRecord:
    // TRANSLITERATE from combat_contract.h (fixed arrays become Array<T, 2^N>;
    // Fight::commitment[2][32] becomes Array<id, 2>).

    struct StateData
    {
        // manifest (compiled-in release values; INITIALIZE writes them)
        id networkId;
        id contractId;
        id admin;
        id rulesetDigest;
        // ledger
        sint64 balance;
        sint64 paidOut;
        sint64 overflowCredit;
        uint32 creditCount;
        // service heartbeat (protocol.md section 5)
        uint64 generation;
        uint64 lastServiced;
        uint64 lastObserved;
        uint64 tick;
        // ids
        uint64 nextOffer, nextContest, nextFight, nextCup;
        uint8 rulesetRetired;
        uint32 nFighters;
        // records
        Array<Fighter, QDOJO_CAP_FIGHTERS> fighters;
        HashMap<id, Account, QDOJO_CAP_ACCOUNTS> accounts;   // id hash = first 8 bytes (qpi.h)
        HashMap<id, FighterAsset, QDOJO_CAP_ASSETS> assets;
        // Array<Offer, 128> offers; Array<Contest, 32> contests; Array<Fight, 32> fights;
        // Array<Cup, 8> cups; Array<PairRecord, 4096> pairs;  TRANSLITERATE
        // events
        uint64 eventSeq;
        id eventDigest;
        Array<Event, QDOJO_CAP_EVENTS> events;
    };

    // ---- Dispatch: the single user procedure ----------------------------------------
    struct Dispatch_input
    {
        Array<uint8, 512> frame;     // protocol.md section 1; runtime pads/truncates to 512
    };
    struct Dispatch_output
    {
        uint8 code;
        uint16 op;
        uint64 target;
        sint64 refunded;
    };

    struct EnsureService_input
    {
        uint64 tick;
    };
    struct EnsureService_output
    {
        bit ok;
    };
    struct EnsureService_locals
    {
        uint64 zero;
    };

    struct Refund_input
    {
        id who;
        sint64 amount;
    };
    struct Refund_output
    {
        sint64 refunded;
    };
    struct Refund_locals
    {
        Account account;
        bit hasSlot;
        sint64 remaining;
    };

    struct PayOut_input
    {
        id to;
        sint64 amount;
    };
    struct PayOut_output
    {
        bit ok;
    };

    struct OwnerOf_input
    {
        id fighterId;
    };
    struct OwnerOf_output
    {
        bit found;
        id owner;
    };
    struct OwnerOf_locals
    {
        FighterAsset asset;
        AssetOwnershipIterator iter;
        sint64 shares;
    };

    struct Dispatch_locals
    {
        id invocator;
        sint64 amount;
        uint32 magic;
        uint16 opcode;
        uint16 flags;
        uint64 nonce;
        uint16 bodyLength;
        uint64 i;
        uint8 code;
        id frameDigest;
        Account account;
        bit haveAccount;
        EnsureService_input ensureIn;
        EnsureService_output ensureOut;
        Refund_input refundIn;
        Refund_output refundOut;
        // Handler inputs/outputs for the opcode switch: TRANSLITERATE
    };

    // protocol.md section 5: ensure_service(T). TRANSLITERATE detail::ensure_service;
    // the SERVICE_GAP event goes through the Emit procedure.
    PRIVATE_PROCEDURE_WITH_LOCALS(EnsureService)
    {
        output.ok = (input.tick >= state.get().lastObserved);
        if (!output.ok || input.tick == state.get().lastObserved)
        {
            return;
        }
        if (input.tick - 1 != state.get().lastServiced)
        {
            state.mut().generation = state.get().generation + 1;
            // CALL(Emit, SERVICE_GAP: generation, lastServiced, tick)  TRANSLITERATE
        }
        state.mut().lastObserved = input.tick;
        state.mut().tick = input.tick;
    }

    // Host::transfer. qpi.transfer returns the remaining balance, negative on
    // failure (qpi_context.h). UNVERIFIED: which recipients can fail at all,
    // and that a failed transfer leaves both balances untouched (spec.md
    // section 5 requires proof before relying on restore-on-failure).
    PRIVATE_PROCEDURE(PayOut)
    {
        output.ok = (qpi.transfer(input.to, input.amount) >= 0);
    }

    // Host::owner_of: the single owner of the fighter's one-unit asset.
    // UNVERIFIED: that a registry asset has exactly one ownership record with
    // one share, and how possession (as opposed to ownership) should count.
    PRIVATE_FUNCTION_WITH_LOCALS(OwnerOf)
    {
        output.found = state.get().assets.get(input.fighterId, locals.asset);
        if (!output.found)
        {
            return;
        }
        output.found = false;
        locals.iter.begin(locals.asset.issuance);
        while (!locals.iter.reachedEnd())
        {
            locals.shares = locals.iter.numberOfOwnedShares();
            if (locals.shares > 0)
            {
                if (output.found)
                {
                    output.found = false;       // more than one owner: not an indivisible asset
                    return;
                }
                output.found = true;
                output.owner = locals.iter.owner();
            }
            locals.iter.next();
        }
    }

    // contract.py _refund. TRANSLITERATE detail::refund (credit + REFUND_CREDIT
    // event, or a direct PayOut when the invocator has no slot and the credit
    // table is full).
    PRIVATE_PROCEDURE_WITH_LOCALS(Refund)
    {
        output.refunded = input.amount;
    }

    PUBLIC_PROCEDURE_WITH_LOCALS(Dispatch)
    {
        locals.invocator = qpi.invocator();
        locals.amount = qpi.invocationReward();
        output.op = 0;
        output.target = 0;
        output.refunded = 0;

        // The attachment arrives with the call (TransferType::procedureTransaction).
        // It is counted HERE ONLY; do not also count it in POST_INCOMING_TRANSFER
        // (protocol.md section 1: count an incoming transfer once).
        locals.ensureIn.tick = qpi.tick();
        CALL(EnsureService, locals.ensureIn, locals.ensureOut);
        state.mut().balance = sadd(state.get().balance, locals.amount);

        // PROPOSED, not in the reference: fighter actions only from direct
        // transactions (protocol.md section 1). A nested call is refunded to
        // the calling contract as credit.
        if (locals.invocator != qpi.originator())
        {
            locals.refundIn.who = locals.invocator;
            locals.refundIn.amount = locals.amount;
            CALL(Refund, locals.refundIn, locals.refundOut);
            output.code = QDOJO_NOT_DIRECT;
            output.refunded = locals.refundOut.refunded;
            return;
        }

        // ---- frame header (codec.py decode_frame) --------------------------------
        locals.code = QDOJO_OK;
        if (input.frame.get(QDOJO_FRAME_LEN - 1) != QDOJO_FRAME_SENTINEL)
        {
            locals.code = QDOJO_BAD_FRAME;
        }
        locals.magic = uint32(input.frame.get(0)) | (uint32(input.frame.get(1)) << 8)
            | (uint32(input.frame.get(2)) << 16) | (uint32(input.frame.get(3)) << 24);
        if (locals.magic != QDOJO_MAGIC_QDC1)
        {
            locals.code = QDOJO_BAD_FRAME;
        }
        locals.opcode = uint16(input.frame.get(4)) | uint16(uint16(input.frame.get(5)) << 8);
        locals.flags = uint16(input.frame.get(6)) | uint16(uint16(input.frame.get(7)) << 8);
        locals.nonce = 0;
        for (locals.i = 0; locals.i < 8; locals.i++)
        {
            locals.nonce |= uint64(input.frame.get(8 + locals.i)) << (8 * locals.i);
        }
        locals.bodyLength = uint16(input.frame.get(16)) | uint16(uint16(input.frame.get(17)) << 8);
        if (locals.flags != 0)
        {
            locals.code = QDOJO_BAD_FRAME;
        }
        for (locals.i = 18; locals.i < 24; locals.i++)
        {
            if (input.frame.get(locals.i) != 0)
            {
                locals.code = QDOJO_BAD_FRAME;
            }
        }
        if (locals.bodyLength > QDOJO_MAX_BODY)
        {
            locals.code = QDOJO_BAD_FRAME;
        }
        // Then: opcode table (BAD_OPCODE), zero padding after the body
        // (BAD_FRAME), exact body length per opcode (BAD_BODY), reveal plan shape
        // (BAD_PLAN): TRANSLITERATE detail::decode_frame. Keep the reference's
        // check order; it decides which code a malformed frame gets.
        if (locals.code != QDOJO_OK)
        {
            locals.refundIn.who = locals.invocator;
            locals.refundIn.amount = locals.amount;
            CALL(Refund, locals.refundIn, locals.refundOut);
            output.code = locals.code;
            output.refunded = locals.refundOut.refunded;
            return;
        }

        // ---- request digest and nonce (protocol.md section 3) ----------------------
        // locals.frameDigest = SHA-256(frame): the in-contract SHA-256 helper
        // (sha256.h TRANSLITERATED); QPI offers only K12, which the protocol
        // forbids substituting.
        locals.haveAccount = state.get().accounts.get(locals.invocator, locals.account);
        // Nonce checks, slot reservation, opcode switch to the handler
        // procedures, and the nonce record on success: TRANSLITERATE the body
        // of qdojo_contract::dispatch.
    }

    // ---- tick callbacks -------------------------------------------------------------
    // Both run for every tick while the fee reserve is positive and the
    // contract is not in an error state (src/qubic.cpp processTick). A tick
    // skipped for an empty reserve is exactly the gap ensure_service detects.
    // UNVERIFIED: the tick successor across an epoch boundary (the first tick
    // of epoch N+1 is initialTick, not necessarily lastTick+1), which would
    // open a spurious SERVICE_GAP every epoch; see README.md.
    struct BEGIN_TICK_locals
    {
        EnsureService_input ensureIn;
        EnsureService_output ensureOut;
    };
    BEGIN_TICK_WITH_LOCALS()
    {
        locals.ensureIn.tick = qpi.tick();
        CALL(EnsureService, locals.ensureIn, locals.ensureOut);
    }

    struct END_TICK_locals
    {
        EnsureService_input ensureIn;
        EnsureService_output ensureOut;
    };
    END_TICK_WITH_LOCALS()
    {
        locals.ensureIn.tick = qpi.tick();
        CALL(EnsureService, locals.ensureIn, locals.ensureOut);
        if (!locals.ensureOut.ok)
        {
            return;
        }
        // Service voids, fight deadlines (at most 16, by fight_id), duel expiry,
        // matching every match_interval ticks, cups by cup_id:
        // TRANSLITERATE qdojo_contract::end_tick.
        //
        // COST NOTE: this write marks the whole state dirty every tick, so Core
        // rehashes all of StateData each tick (doc/contracts.md: the digest of
        // dirty states is recomputed at the end of each tick). At
        // sizeof(State) ~1.37 MB that is the dominant recurring cost; see
        // README.md.
        state.mut().lastServiced = qpi.tick();
    }

    // ---- read-only queries -----------------------------------------------------------
    struct GetService_input
    {
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
    };
    struct GetAccount_locals
    {
        Account account;
    };
    PUBLIC_FUNCTION_WITH_LOCALS(GetAccount)
    {
        if (state.get().accounts.get(input.who, locals.account))
        {
            output.credit = locals.account.credit;
            output.hasNonce = locals.account.hasNonce;
            output.nonce = locals.account.nonce;
        }
    }

    // Retained events with seq > after, at most 64 per page (64 x ~180 bytes,
    // under the 65535-byte output limit).
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
        uint64 i;
    };
    PUBLIC_FUNCTION_WITH_LOCALS(GetEvents)
    {
        locals.oldest = 1;
        if (state.get().eventSeq > QDOJO_CAP_EVENTS)
        {
            locals.oldest = state.get().eventSeq - QDOJO_CAP_EVENTS + 1;
        }
        locals.seq = input.after + 1;
        if (locals.seq < locals.oldest)
        {
            locals.seq = locals.oldest;
        }
        output.count = 0;
        for (locals.i = 0; locals.i < 64; locals.i++)
        {
            if (output.count >= input.limit || locals.seq > state.get().eventSeq)
            {
                break;
            }
            output.events.set(output.count, state.get().events.get(mod(locals.seq - 1, QDOJO_CAP_EVENTS)));
            output.count = output.count + 1;
            locals.seq = locals.seq + 1;
        }
    }

    // GetFighter, GetOffer, GetFight, GetContest, GetCup, GetStandings:
    // TRANSLITERATE qdojo_contract::query_* (bounded record copies).

    REGISTER_USER_FUNCTIONS_AND_PROCEDURES()
    {
        // The numeric procedure/function IDs are DEPLOYMENT VALUES from the
        // reviewed release manifest (protocol.md section 1), not these
        // placeholders, and never the legacy riddle inputType 0x444F.
        REGISTER_USER_PROCEDURE(Dispatch, 1);
        REGISTER_USER_FUNCTION(GetService, 1);
        REGISTER_USER_FUNCTION(GetAccount, 2);
        REGISTER_USER_FUNCTION(GetEvents, 3);
    }

    struct INITIALIZE_locals
    {
        uint64 zero;
    };
    INITIALIZE_WITH_LOCALS()
    {
        // State arrives zeroed. Write the release manifest constants, then
        // generation = 1, lastServiced = lastObserved = tick = qpi.tick()
        // (the construction tick is exempt from the predecessor check),
        // next ids = 1, and eventDigest = SHA-256("qdojo/combat/event/genesis/v1\0")
        // as a precomputed id constant: TRANSLITERATE qdojo_contract::init.
        state.mut().generation = 1;
        state.mut().lastServiced = qpi.tick();
        state.mut().lastObserved = qpi.tick();
        state.mut().tick = qpi.tick();
        state.mut().nextOffer = 1;
        state.mut().nextContest = 1;
        state.mut().nextFight = 1;
        state.mut().nextCup = 1;
    }
};
