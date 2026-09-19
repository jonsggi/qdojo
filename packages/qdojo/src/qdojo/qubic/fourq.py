"""FourQ: the curve Qubic signs on, in plain Python integers.

This is a re-derivation of Qubic's reference C++ (`k12_and_key_utils.h`), not a
transliteration of it. The reference is ~1,500 lines of 4-dimensional GLV
decomposition, mLSB-set recoding and a 960-word fixed-base table, all of it
there to make one scalar multiplication fast and constant-time on a CPU. None
of that changes the answer, and a port of it would be ~1,500 lines of Python
in which a transcription slip could hide. What is reproduced here is the
mathematics -- the field, the curve, and k*G -- computed the obvious way and
checked byte-for-byte against the reference on real keys.

Speed is not a concern at our volume: one signature is a few milliseconds,
and the largest run this repo has ever done is 768 casts spread over hours.

  field   GF(p^2), p = 2^127 - 1, elements a0 + a1*i with i^2 = -1
  curve   -x^2 + y^2 = 1 + d*x^2*y^2   (twisted Edwards, a = -1)
  points  extended coordinates (X:Y:Z:T), x = X/Z, y = Y/Z, T = XY/Z

THE GENERATOR IS NOT A CONSTANT IN THE REFERENCE -- only a precomputed table
of its multiples is. `G` below was recovered from qubic-cli itself rather
than copied from a paper: `-showkeys` prints a (privateKey, publicKey) pair,
publicKey is privateKey*G, so G = (privateKey^-1 mod N) * decode(publicKey).
`tests/test_qubic.py` redoes exactly that and asserts the constant, so a
wrong G cannot survive a test run.
"""

P = (1 << 127) - 1

# Curve order (the prime subgroup order), CURVE_ORDER_{0..3} little-endian.
N = 0x0029CBC14E5E0A72F05397829CBC14E5DFBD004DFE0F79992FB2540EC7768CE7

# PARAMETER_d, same limb order: d = d_re + d_im*i
D = (
    (0xE4 << 64) | 0x142,
    (0x5E472F846657E0FC << 64) | 0xB3821488F1FC0C8D,
)

# Generator, recovered from the reference (see the module docstring).
G = (
    (0x1A3472237C2FB305286592AD7B3833AA, 0x1E1F553F2878AA9C96869FB360AC77F6),
    (0x0E3FEE9BA120785AB924A2462BCBB287, 0x6E1C4AF8630E024249A7C344844C8B5C),
)

ZERO = (0, 0)
ONE = (1, 0)


# ------------------------------------------------------------------ GF(p^2)

def f_add(a, b):
    return ((a[0] + b[0]) % P, (a[1] + b[1]) % P)


def f_sub(a, b):
    return ((a[0] - b[0]) % P, (a[1] - b[1]) % P)


def f_neg(a):
    return ((-a[0]) % P, (-a[1]) % P)


def f_mul(a, b):
    a0, a1 = a
    b0, b1 = b
    return ((a0 * b0 - a1 * b1) % P, (a0 * b1 + a1 * b0) % P)


def f_sqr(a):
    a0, a1 = a
    return ((a0 * a0 - a1 * a1) % P, (2 * a0 * a1) % P)


def f_inv(a):
    """1/a = conj(a) / norm(a), norm(a) = a0^2 + a1^2 in GF(p)."""
    a0, a1 = a
    n = (a0 * a0 + a1 * a1) % P
    if n == 0:
        raise ZeroDivisionError("fourq: inverse of zero")
    ninv = pow(n, P - 2, P)
    return ((a0 * ninv) % P, ((-a1) * ninv) % P)


def f_eq(a, b):
    return a[0] % P == b[0] % P and a[1] % P == b[1] % P


def _sqrt_p(a):
    """Square root in GF(p). p = 3 mod 4, so it is a^((p+1)/4). None if none."""
    r = pow(a, (P + 1) // 4, P)
    return r if (r * r) % P == a % P else None


def f_sqrt(a):
    """Square root in GF(p^2), or None. Complex method, p = 3 mod 4."""
    a0, a1 = a[0] % P, a[1] % P
    if a1 == 0:
        r = _sqrt_p(a0)
        if r is not None:
            return (r, 0)
        r = _sqrt_p((-a0) % P)
        return None if r is None else (0, r)
    norm = _sqrt_p((a0 * a0 + a1 * a1) % P)
    if norm is None:
        return None
    inv2 = pow(2, P - 2, P)
    for s in ((a0 + norm) % P, (a0 - norm) % P):
        t = (s * inv2) % P
        x0 = _sqrt_p(t)
        if x0 is None or x0 == 0:
            continue
        x1 = (a1 * pow(2 * x0, P - 2, P)) % P
        cand = (x0, x1)
        if f_eq(f_sqr(cand), a):
            return cand
    return None


# ------------------------------------------------------------------- points
# Extended twisted Edwards, a = -1: (X, Y, Z, T) with T = X*Y/Z.

IDENTITY = (ZERO, ONE, ONE, ZERO)


def pt_double(p):
    x1, y1, z1, _ = p
    a = f_sqr(x1)
    b = f_sqr(y1)
    c = f_add(f_sqr(z1), f_sqr(z1))
    d = f_neg(a)                                   # a = -1
    e = f_sub(f_sub(f_sqr(f_add(x1, y1)), a), b)
    g = f_add(d, b)
    f = f_sub(g, c)
    h = f_sub(d, b)
    return (f_mul(e, f), f_mul(g, h), f_mul(f, g), f_mul(e, h))


def pt_add(p, q):
    x1, y1, z1, t1 = p
    x2, y2, z2, t2 = q
    a = f_mul(f_sub(y1, x1), f_sub(y2, x2))
    b = f_mul(f_add(y1, x1), f_add(y2, x2))
    c = f_mul(f_mul(f_add(D, D), t1), t2)
    d = f_add(f_mul(z1, z2), f_mul(z1, z2))
    e = f_sub(b, a)
    f = f_sub(d, c)
    g = f_add(d, c)
    h = f_add(b, a)
    return (f_mul(e, f), f_mul(g, h), f_mul(f, g), f_mul(e, h))


def pt_affine(p):
    """(x, y) in GF(p^2), canonical."""
    x, y, z, _ = p
    zi = f_inv(z)
    return (f_mul(x, zi), f_mul(y, zi))


def pt_from_affine(x, y):
    return (x, y, ONE, f_mul(x, y))


def pt_eq(p, q):
    return pt_affine(p) == pt_affine(q)


def on_curve(x, y):
    """-x^2 + y^2 == 1 + d*x^2*y^2"""
    x2, y2 = f_sqr(x), f_sqr(y)
    lhs = f_sub(y2, x2)
    rhs = f_add(ONE, f_mul(D, f_mul(x2, y2)))
    return f_eq(lhs, rhs)


def scalar_mul(k, p=None):
    """k*P, left-to-right double-and-add. k is reduced mod N first.

    The reference reduces the scalar the same way before recoding it
    (`ecc_mul_fixed` runs it through Montgomery_multiply_mod_order twice),
    so k and k mod N must give the same point -- and do, since G has order N.
    """
    if p is None:
        p = pt_from_affine(*G)
    k %= N
    if k == 0:
        return IDENTITY
    r = IDENTITY
    for bit in bin(k)[2:]:
        r = pt_double(r)
        if bit == "1":
            r = pt_add(r, p)
    return r


# ---------------------------------------------------------------- encodings

def encode(p):
    """32 bytes: y little-endian, with the sign of x in the top bit.

    Mirrors `encode()` in the reference: the sign bit is bit 126 of x's real
    part, or of its imaginary part when the real part is zero.
    """
    x, y = pt_affine(p)
    out = bytearray(y[0].to_bytes(16, "little") + y[1].to_bytes(16, "little"))
    sign_src = x[1] if x[0] == 0 else x[0]
    out[31] |= ((sign_src >> 126) & 1) << 7
    return bytes(out)


def decode(enc):
    """Inverse of encode(). Returns a point, or None if it is not on the curve.

    x^2 = (y^2 - 1) / (d*y^2 + 1), then the stored bit picks which root.
    """
    if len(enc) != 32:
        raise ValueError("fourq.decode: need 32 bytes, got %d" % len(enc))
    sign = enc[31] >> 7
    buf = bytearray(enc)
    buf[31] &= 0x7F
    y = (int.from_bytes(buf[0:16], "little"), int.from_bytes(buf[16:32], "little"))
    if y[0] >= P or y[1] >= P:
        return None

    y2 = f_sqr(y)
    u = f_sub(y2, ONE)
    v = f_add(f_mul(D, y2), ONE)
    try:
        x2 = f_mul(u, f_inv(v))
    except ZeroDivisionError:
        return None
    x = f_sqrt(x2)
    if x is None:
        return None
    if not on_curve(x, y):
        return None

    sign_src = x[1] if x[0] == 0 else x[0]
    if ((sign_src >> 126) & 1) != sign:
        x = f_neg(x)
    return pt_from_affine(x, y)
