// Bounded, self-contained SHA-256 (FIPS 180-4) plus the qdojo combat-v1
// digests of docs/protocol.md section 2. Same constraints as combat_core.h:
// header-only, no heap, no exceptions, no STL, fixed-width integers, and
// loops bounded by the (fixed) input length. The protocol requires SHA-256;
// never substitute K12.
#ifndef QDOJO_COMBAT_SHA256_H
#define QDOJO_COMBAT_SHA256_H

#include <stdint.h>

namespace qdojo_combat {

struct Sha256 {
    uint32_t h[8];
    uint8_t buf[64];
    uint32_t buf_len;
    uint64_t total_len;  // bytes
};

namespace sha_detail {

static constexpr uint32_t K[64] = {
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
};

inline uint32_t rotr(uint32_t x, uint32_t n) { return (x >> n) | (x << (32 - n)); }

inline void compress(uint32_t h[8], const uint8_t block[64]) {
    uint32_t w[64];
    for (uint32_t i = 0; i < 16; ++i)
        w[i] = (uint32_t(block[4 * i]) << 24) | (uint32_t(block[4 * i + 1]) << 16) |
               (uint32_t(block[4 * i + 2]) << 8) | uint32_t(block[4 * i + 3]);
    for (uint32_t i = 16; i < 64; ++i) {
        uint32_t s0 = rotr(w[i - 15], 7) ^ rotr(w[i - 15], 18) ^ (w[i - 15] >> 3);
        uint32_t s1 = rotr(w[i - 2], 17) ^ rotr(w[i - 2], 19) ^ (w[i - 2] >> 10);
        w[i] = w[i - 16] + s0 + w[i - 7] + s1;
    }
    uint32_t a = h[0], b = h[1], c = h[2], d = h[3], e = h[4], f = h[5], g = h[6], hh = h[7];
    for (uint32_t i = 0; i < 64; ++i) {
        uint32_t S1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25);
        uint32_t ch = (e & f) ^ (~e & g);
        uint32_t t1 = hh + S1 + ch + K[i] + w[i];
        uint32_t S0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22);
        uint32_t mj = (a & b) ^ (a & c) ^ (b & c);
        uint32_t t2 = S0 + mj;
        hh = g; g = f; f = e; e = d + t1; d = c; c = b; b = a; a = t1 + t2;
    }
    h[0] += a; h[1] += b; h[2] += c; h[3] += d; h[4] += e; h[5] += f; h[6] += g; h[7] += hh;
}

}  // namespace sha_detail

inline void sha256_init(Sha256& s) {
    static constexpr uint32_t IV[8] = {0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
                                       0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19};
    for (uint32_t i = 0; i < 8; ++i) s.h[i] = IV[i];
    s.buf_len = 0;
    s.total_len = 0;
}

// Loop bound: len iterations.
inline void sha256_update(Sha256& s, const uint8_t* data, uint32_t len) {
    for (uint32_t i = 0; i < len; ++i) {
        s.buf[s.buf_len++] = data[i];
        if (s.buf_len == 64) {
            sha_detail::compress(s.h, s.buf);
            s.buf_len = 0;
        }
    }
    s.total_len += len;
}

inline void sha256_final(Sha256& s, uint8_t out[32]) {
    uint64_t bits = s.total_len * 8;
    s.buf[s.buf_len++] = 0x80;
    if (s.buf_len > 56) {
        while (s.buf_len < 64) s.buf[s.buf_len++] = 0;  // at most 7 iterations
        sha_detail::compress(s.h, s.buf);
        s.buf_len = 0;
    }
    while (s.buf_len < 56) s.buf[s.buf_len++] = 0;  // at most 56 iterations
    for (uint32_t i = 0; i < 8; ++i) s.buf[56 + i] = uint8_t(bits >> (56 - 8 * i));
    sha_detail::compress(s.h, s.buf);
    for (uint32_t i = 0; i < 8; ++i) {
        out[4 * i] = uint8_t(s.h[i] >> 24);
        out[4 * i + 1] = uint8_t(s.h[i] >> 16);
        out[4 * i + 2] = uint8_t(s.h[i] >> 8);
        out[4 * i + 3] = uint8_t(s.h[i]);
    }
}

inline void sha256(const uint8_t* data, uint32_t len, uint8_t out[32]) {
    Sha256 s;
    sha256_init(s);
    sha256_update(s, data, len);
    sha256_final(s, out);
}

// ------------------------------------------------ combat-v1 domain hashes
// Domain tags include their terminal zero byte (sizeof includes it).
static constexpr char TAG_CONTEXT[] = "qdojo/combat/context/v1";
static constexpr char TAG_STATE[] = "qdojo/combat/state/v1";
static constexpr char TAG_COMMIT[] = "qdojo/combat/commit/v1";
static constexpr char TAG_RULES[] = "qdojo/combat/rules/v1";

// Participant record: fighter_id[32] owner[32] operator[32] auth_version u32
// payout_recipient[32] lifetime_rating u16 season_rating u16.
static constexpr uint32_t PARTICIPANT_BYTES = 32 + 32 + 32 + 4 + 32 + 2 + 2;
// Fight context bytes (protocol.md section 2), both participants included.
static constexpr uint32_t CONTEXT_BYTES = 32 + 32 + 8 + 8 + 1 + 1 + 8 + 4 + 8 + 32 + 2 + 2 + 4 + 8 +
                                          2 + 2 + 2 + 2 + 32 + 32 + 32 + 2 * PARTICIPANT_BYTES;
static_assert(CONTEXT_BYTES == 526, "context layout");

inline void sha256_update_tag(Sha256& s, const char* tag, uint32_t size_with_nul) {
    sha256_update(s, reinterpret_cast<const uint8_t*>(tag), size_with_nul);
}

inline void put_u64le(Sha256& s, uint64_t v) {
    uint8_t b[8];
    for (uint32_t i = 0; i < 8; ++i) b[i] = uint8_t(v >> (8 * i));
    sha256_update(s, b, 8);
}

inline void put_u32le(Sha256& s, uint32_t v) {
    uint8_t b[4];
    for (uint32_t i = 0; i < 4; ++i) b[i] = uint8_t(v >> (8 * i));
    sha256_update(s, b, 4);
}

// context_digest = SHA256("qdojo/combat/context/v1\0" || context_bytes)
inline void context_digest(const uint8_t context[CONTEXT_BYTES], uint8_t out[32]) {
    Sha256 s;
    sha256_init(s);
    sha256_update_tag(s, TAG_CONTEXT, sizeof(TAG_CONTEXT));
    sha256_update(s, context, CONTEXT_BYTES);
    sha256_final(s, out);
}

// round_state_digest = SHA256("qdojo/combat/state/v1\0" || context_digest ||
//                             round_index u8 || state_A[8] || state_B[8])
inline void round_state_digest(const uint8_t ctx_digest[32], uint8_t round_index, const uint8_t state_a[8],
                               const uint8_t state_b[8], uint8_t out[32]) {
    Sha256 s;
    sha256_init(s);
    sha256_update_tag(s, TAG_STATE, sizeof(TAG_STATE));
    sha256_update(s, ctx_digest, 32);
    sha256_update(s, &round_index, 1);
    sha256_update(s, state_a, 8);
    sha256_update(s, state_b, 8);
    sha256_final(s, out);
}

// Commitment = SHA256("qdojo/combat/commit/v1\0" || network_id[32] ||
//   contract_id[32] || fight_id u64 || round_index u8 || context_digest[32] ||
//   round_state_digest[32] || fighter_id[32] || operator[32] ||
//   auth_version u32 || salt[32] || plan[7])
inline void commitment(const uint8_t network_id[32], const uint8_t contract_id[32], uint64_t fight_id,
                       uint8_t round_index, const uint8_t ctx_digest[32], const uint8_t state_digest[32],
                       const uint8_t fighter_id[32], const uint8_t operator_id[32], uint32_t auth_version,
                       const uint8_t salt[32], const uint8_t plan[7], uint8_t out[32]) {
    Sha256 s;
    sha256_init(s);
    sha256_update_tag(s, TAG_COMMIT, sizeof(TAG_COMMIT));
    sha256_update(s, network_id, 32);
    sha256_update(s, contract_id, 32);
    put_u64le(s, fight_id);
    sha256_update(s, &round_index, 1);
    sha256_update(s, ctx_digest, 32);
    sha256_update(s, state_digest, 32);
    sha256_update(s, fighter_id, 32);
    sha256_update(s, operator_id, 32);
    put_u32le(s, auth_version);
    sha256_update(s, salt, 32);
    sha256_update(s, plan, 7);
    sha256_final(s, out);
}

}  // namespace qdojo_combat

#endif  // QDOJO_COMBAT_SHA256_H
