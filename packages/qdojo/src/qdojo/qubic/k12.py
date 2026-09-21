"""KangarooTwelve, as Qubic computes it.

Every hash in the protocol is this one: seed -> subseed -> private key, the
identity checksum, the transaction digest, the nonce inside a signature, the
transaction hash. Get it wrong for short inputs and every derived identity is
wrong, which is the loud failure. Get it wrong only for long inputs and you
sign the wrong transaction, which is not.

Ported from Qubic's reference C++ (`k12_and_key_utils.h`), not from the
published K12 specification, and the difference is deliberate. Qubic's single-block
path writes the 0x07 domain suffix at `byteIOIndex + 1`, one byte past where
the published K12 padding rule puts it:

    blockNumber = 0;
    if (++finalNode.byteIOIndex == K12_rateInBytes) { permute; state[0] ^= 0x07; }
    else                                            { state[finalNode.byteIOIndex] ^= 0x07; }

`SUFFIX_OFFSET` below carries that offset explicitly so it is a stated fact
with a test behind it (`tests/test_qubic.py` derives a real private key
and checks it against frozen reference vectors), not an accident of the
port.

INPUTS >= 8192 BYTES ARE REFUSED. Above one chunk K12 switches to tree
hashing, and nothing in Qubic reaches it: MAX_INPUT_SIZE is 1024, so the
largest thing ever hashed here is 80 + 1024 + 64 = 1168 bytes. An untested
tree path that silently returns a plausible 32 bytes is exactly the failure
shape a money path cannot absorb, so it raises instead.
"""

RATE = 168                  # (1600 - 2*128) / 8
CHUNK_SIZE = 8192
SUFFIX_OFFSET = 1           # see the module docstring: Qubic's off-by-one, on purpose

_MASK = (1 << 64) - 1

# Rounds 12..23 of Keccak-f[1600] -- the 12 that Keccak-p[1600,12] keeps.
_RC = (
    0x000000008000808B, 0x800000000000008B, 0x8000000000008089, 0x8000000000008003,
    0x8000000000008002, 0x8000000000000080, 0x000000000000800A, 0x800000008000000A,
    0x8000000080008081, 0x8000000000008080, 0x0000000080000001, 0x8000000080008008,
)

_ROT = (
    (0, 36, 3, 41, 18), (1, 44, 10, 45, 2), (62, 6, 43, 15, 61),
    (28, 55, 25, 21, 56), (27, 20, 39, 8, 14),
)


def _rol(v, n):
    if n == 0:
        return v
    return ((v << n) | (v >> (64 - n))) & _MASK


def _permute(lanes):
    """Keccak-p[1600,12] over lanes[x][y]."""
    for rc in _RC:
        # theta
        c = [lanes[x][0] ^ lanes[x][1] ^ lanes[x][2] ^ lanes[x][3] ^ lanes[x][4]
             for x in range(5)]
        d = [c[(x - 1) % 5] ^ _rol(c[(x + 1) % 5], 1) for x in range(5)]
        for x in range(5):
            for y in range(5):
                lanes[x][y] ^= d[x]
        # rho + pi
        b = [[0] * 5 for _ in range(5)]
        for x in range(5):
            for y in range(5):
                b[y][(2 * x + 3 * y) % 5] = _rol(lanes[x][y], _ROT[x][y])
        # chi
        for x in range(5):
            for y in range(5):
                lanes[x][y] = b[x][y] ^ ((~b[(x + 1) % 5][y]) & b[(x + 2) % 5][y] & _MASK)
        # iota
        lanes[0][0] ^= rc
    return lanes


def _state_to_bytes(lanes):
    out = bytearray(200)
    for i in range(25):
        out[8 * i:8 * i + 8] = lanes[i % 5][i // 5].to_bytes(8, "little")
    return out


def _bytes_to_state(buf):
    lanes = [[0] * 5 for _ in range(5)]
    for i in range(25):
        lanes[i % 5][i // 5] = int.from_bytes(buf[8 * i:8 * i + 8], "little")
    return lanes


def k12(data, outlen):
    """KangarooTwelve(data, outlen) with an empty customisation string.

    `outlen` must be <= RATE: the reference reads the digest straight out of
    the state after the final permutation and never squeezes again, and so
    does this. Qubic asks for 3, 32 and 64 bytes only.
    """
    data = bytes(data)
    if len(data) >= CHUNK_SIZE:
        raise ValueError(
            "k12: %d-byte input needs the tree path, which is untested here "
            "and unreachable in Qubic (MAX_INPUT_SIZE is 1024)" % len(data))
    if not 0 < outlen <= RATE:
        raise ValueError("k12: outlen must be in 1..%d, got %r" % (RATE, outlen))

    state = bytearray(200)
    off = 0
    while len(data) - off >= RATE:
        lanes = _bytes_to_state(state)
        blk = data[off:off + RATE]
        for i in range(RATE // 8):
            lanes[i % 5][i // 5] ^= int.from_bytes(blk[8 * i:8 * i + 8], "little")
        state = _state_to_bytes(_permute(lanes))
        off += RATE

    tail = data[off:]                       # strictly shorter than the rate
    for i, b in enumerate(tail):
        state[i] ^= b

    # Domain suffix 0x07, at Qubic's offset. idx == RATE means the byte would
    # land past the block, so the block is permuted first and the suffix goes
    # to state[0] -- which is what the reference does.
    idx = len(tail) + SUFFIX_OFFSET
    if idx == RATE:
        state = _state_to_bytes(_permute(_bytes_to_state(state)))
        state[0] ^= 0x07
    else:
        state[idx] ^= 0x07

    state[RATE - 1] ^= 0x80
    state = _state_to_bytes(_permute(_bytes_to_state(state)))
    return bytes(state[:outlen])
