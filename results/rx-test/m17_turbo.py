#!/usr/bin/env python3
"""Turbo equaliser for M17 stream frames (offline): soft MMSE interference cancellation + BCJR decoding.

  m17_turbo.py selftest
  m17_turbo.py sim  chan.npz [--frames 600] [--iters 8]
  m17_turbo.py real ic_prefix [--iters 8]     (uses <prefix>_ffe.f32, _starts.txt, _chan.npz from m17_ic.py)

Per iteration, for every frame on the 192-symbol grid:
  soft IC   z_k = (y_k - sum_{j!=0} c_j m_{k-j}) / c_0,  var_k = (s^2 + sum_{j!=0} c_j^2 v_{k-j}) / c_0^2
  demap     bit LLRs of the 4-PAM symbol (b1 b0: 00 +1, 01 +3, 10 -1, 11 -3)
  derandomise, deinterleave -> LICH (96, hard Golay via libm17) + 272 punctured conv bits
  BCJR (log-MAP, K=5, G1=1+D^3+D^4, G2=1+D+D^2+D^4, P2 puncturing, 4 tail bits, start/end state 0)
  extrinsic coded-bit LLRs -> re-puncture, interleave, randomise -> symbol means m and variances v
Only extrinsic information is fed back (no frame confirms itself). LLR convention: L = ln P(0)/P(1).
"""
import argparse, ctypes as C, os, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
L = C.CDLL("libm17.so")
INTRL = np.array((C.c_uint16 * 368).in_dll(L, "intrl_seq"), int)
RAND = np.array((C.c_uint8 * 46).in_dll(L, "rand_seq"), np.uint8)
RBITS = np.unpackbits(RAND).astype(int)        # bit 2i -> b1 XOR, bit 2i+1 -> b0 XOR (MSB first); int: 1-2*r must be -1, not uint8 255
PUNCT = [1] * 11 + [0]
KEEP = np.array([PUNCT[i % 12] for i in range(296)], bool)          # 296 -> 272
SYM = {0: 1.0, 1: 3.0, 2: -1.0, 3: -3.0}
LEV = np.array([SYM[0], SYM[1], SYM[2], SYM[3]])                   # index = b1*2 + b0
FRA, PLD = 192, 184
STR = np.array([-3, -3, -3, -3, 3, 3, -3, 3], float)

class LSF(C.Structure):
    _fields_ = [("dst", C.c_uint8 * 6), ("src", C.c_uint8 * 6), ("type", C.c_uint8 * 2), ("meta", C.c_uint8 * 14), ("crc", C.c_uint8 * 2)]
L.gen_frame.argtypes = [C.POINTER(C.c_float), C.POINTER(C.c_uint8), C.c_int, C.POINTER(LSF), C.c_uint8, C.c_uint16]
L.decode_str_frame.argtypes = [C.POINTER(C.c_uint8), C.POINTER(C.c_uint8), C.POINTER(C.c_uint16), C.POINTER(C.c_uint8), C.POINTER(C.c_float)]
L.encode_LICH.argtypes = [C.POINTER(C.c_uint8), C.POINTER(C.c_uint8)]
L.unpack_LICH.argtypes = [C.POINTER(C.c_uint8), C.POINTER(C.c_uint8)]

# ---- trellis -------------------------------------------------------------------
NS = 16
NXT = np.zeros((NS, 2), int); OUT = np.zeros((NS, 2, 2), int)
for s in range(NS):
    for b in range(2):
        g0 = b ^ ((s >> 2) & 1) ^ ((s >> 3) & 1)
        g1 = b ^ (s & 1) ^ ((s >> 1) & 1) ^ ((s >> 3) & 1)
        NXT[s, b] = ((s << 1) | b) & 0xF; OUT[s, b] = (g0, g1)


def conv_encode(bits144):
    sr = 0; out = []
    for b in list(bits144) + [0, 0, 0, 0]:
        out += list(OUT[sr, b]); sr = NXT[sr, b]
    return np.array(out)[KEEP]                    # 272


def lich_bits(lich5, cnt):
    l6 = (C.c_uint8 * 6)(*lich5, (cnt & 7) << 5); enc = (C.c_uint8 * 12)(); L.encode_LICH(enc, l6)
    u = (C.c_uint8 * 96)(); L.unpack_LICH(u, enc); return np.array(u[:], int)


def frame_bits_to_symbols(enc368):
    b1 = enc368[INTRL[0::2]] ^ RBITS[0::2][:184]; b0 = enc368[INTRL[1::2]] ^ RBITS[1::2][:184]
    return LEV[b1 * 2 + b0]


def encode_frame(data16, fn, lich5, cnt):
    bits = np.unpackbits(np.r_[np.array([fn >> 8, fn & 0xFF], np.uint8), np.asarray(data16, np.uint8)])
    return frame_bits_to_symbols(np.r_[lich_bits(lich5, cnt), conv_encode(bits)])


# ---- soft parts ------------------------------------------------------------------
def demap(z, var):
    """bit LLRs (b1, b0) for each symbol given z ~ N(s, var), uniform symbol priors."""
    d = -(z[:, None] - LEV[None, :]) ** 2 / (2 * var[:, None])
    def lse(ix): return np.logaddexp.reduce(d[:, ix], axis=1)
    L1 = lse([0, 1]) - lse([2, 3])                # b1 = 0 for idx 0,1
    L0 = lse([0, 2]) - lse([1, 3])                # b0 = 0 for idx 0,2
    return L1, L0


def symbol_stats(L1, L0):
    p1 = 1 / (1 + np.exp(np.clip(L1, -30, 30))); p0 = 1 / (1 + np.exp(np.clip(L0, -30, 30)))   # P(bit=1)
    P = np.stack([(1 - p1) * (1 - p0), (1 - p1) * p0, p1 * (1 - p0), p1 * p0], 1)
    m = P @ LEV; v = P @ LEV ** 2 - m ** 2
    return m, np.maximum(v, 1e-6)


def bcjr(Lc296):
    """log-MAP over F frames at once. Lc296: (F, 296) channel LLRs of coded bits (0 at punctured).
    Returns (posterior info LLRs (F,148), posterior coded LLRs (F,296))."""
    F = Lc296.shape[0]; T = 148; NEG = -1e9
    g = np.zeros((F, T, NS, 2))                   # branch metric (log)
    for s in range(NS):
        for b in range(2):
            c0, c1 = OUT[s, b]
            g[:, :, s, b] = ((1 - 2 * c0) * Lc296[:, 0::2] + (1 - 2 * c1) * Lc296[:, 1::2]) / 2
    g[:, 144:, :, 1] = NEG                         # tail bits are 0
    al = np.full((F, T + 1, NS), NEG); al[:, 0, 0] = 0
    for t in range(T):
        nxt = np.full((F, NS), NEG)
        for b in range(2):
            cand = al[:, t, :] + g[:, t, :, b]
            for s in range(NS):
                nxt[:, NXT[s, b]] = np.logaddexp(nxt[:, NXT[s, b]], cand[:, s])
        al[:, t + 1] = nxt - nxt.max(1, keepdims=True)
    be = np.full((F, T + 1, NS), NEG); be[:, T, 0] = 0
    for t in range(T - 1, -1, -1):
        cur = np.full((F, NS), NEG)
        for b in range(2):
            cur = np.logaddexp(cur, g[:, t, :, b] + be[:, t + 1, NXT[np.arange(NS), b]])
        be[:, t] = cur - cur.max(1, keepdims=True)
    # posteriors
    Linfo = np.zeros((F, T)); Lcod = np.zeros((F, 296))
    for t in range(T):
        tot = {}
        for b in range(2):
            tot[b] = al[:, t, :] + g[:, t, :, b] + be[:, t + 1, NXT[np.arange(NS), b]]       # (F, NS)
        Linfo[:, t] = np.logaddexp.reduce(tot[0], 1) - np.logaddexp.reduce(tot[1], 1)
        for k in range(2):
            num = np.full(F, NEG); den = np.full(F, NEG)
            for b in range(2):
                bit = OUT[:, b, k]                                                            # (NS,)
                num = np.logaddexp(num, np.logaddexp.reduce(np.where(bit[None, :] == 0, tot[b], NEG), 1))
                den = np.logaddexp(den, np.logaddexp.reduce(np.where(bit[None, :] == 1, tot[b], NEG), 1))
            Lcod[:, 2 * t + k] = num - den
    return Linfo, Lcod


def turbo(y, starts, c, sigma, iters, truth=None, log=print):
    """y: FFE-output symbol stream; c: residual ISI taps (lags -J..J); starts: frame grid."""
    J = (len(c) - 1) // 2; N = len(y); F = len(starts)
    m = np.zeros(N); v = np.full(N, 5.0)
    sync = (starts[:, None] + np.arange(8)[None, :]).ravel()
    m[sync] = np.tile(STR, F); v[sync] = 0.0
    pld = (starts[:, None] + 8 + np.arange(PLD)[None, :])                                  # (F, 184)
    results = []
    for it in range(iters):
        # soft MMSE IC (convolution with c excluding the centre tap)
        cm = c.copy(); cm[J] = 0
        isi = np.convolve(m, cm[::-1], "same") if False else np.convolve(m, cm, "same")
        isv = np.convolve(v, cm ** 2, "same")
        z = (y - isi) / c[J]; var = (sigma ** 2 + isv) / c[J] ** 2
        zf, vf = z[pld], var[pld]
        L1, L0 = demap(zf.ravel(), vf.ravel()); L1 = L1.reshape(F, PLD); L0 = L0.reshape(F, PLD)
        # derandomise: XOR with r flips the LLR sign
        L1 = L1 * (1 - 2 * RBITS[0::2][:PLD]); L0 = L0 * (1 - 2 * RBITS[1::2][:PLD])
        Lenc = np.zeros((F, 368)); Lenc[:, INTRL[0::2]] = L1; Lenc[:, INTRL[1::2]] = L0
        # LICH: hard decode with libm17 (from the current soft symbols) -> strong prior
        Llich = np.zeros((F, 96))
        hard_fn = np.zeros(F, int); lichs = []
        for f in range(F):
            s = np.ascontiguousarray(z[pld[f]], np.float32)
            fd = (C.c_uint8 * 16)(); li = (C.c_uint8 * 5)(); fnv = C.c_uint16(); lc = C.c_uint8()
            L.decode_str_frame(fd, li, C.byref(fnv), C.byref(lc), s.ctypes.data_as(C.POINTER(C.c_float)))
            lb = lich_bits(list(li), lc.value) if lc.value < 6 else None
            if lb is not None: Llich[f] = 8.0 * (1 - 2 * lb)
            lichs.append(lb)
        # conv part: depuncture, BCJR
        Lc = np.zeros((F, 296)); Lc[:, KEEP] = Lenc[:, 96:]
        Linfo, Lpost = bcjr(Lc)
        Lext = (Lpost - Lc)[:, KEEP]                                                       # extrinsic, 272
        # feed back: extrinsic coded LLRs (+ LICH prior) -> symbol LLRs -> means/variances
        E = np.zeros((F, 368)); E[:, :96] = Llich; E[:, 96:] = Lext
        E1 = E[:, INTRL[0::2]] * (1 - 2 * RBITS[0::2][:PLD]); E0 = E[:, INTRL[1::2]] * (1 - 2 * RBITS[1::2][:PLD])
        mf, vf2 = symbol_stats(E1.ravel(), E0.ravel())
        m[pld.ravel()] = mf; v[pld.ravel()] = vf2
        info = (Linfo[:, :144] < 0).astype(np.uint8)
        fn = np.packbits(info[:, :16], axis=1).astype(int); fn = fn[:, 0] * 256 + fn[:, 1]
        payload = np.packbits(info[:, 16:144], axis=1)
        msg = f"iter {it+1}: mean |extrinsic LLR| {np.mean(np.abs(Lext)):.1f}"
        if truth is not None:
            tdata, tfn = truth
            badf = np.sum(np.any(payload != tdata, axis=1)); pb = np.unpackbits(payload ^ tdata).sum()
            msg += f" | frames with payload errors {badf} ({100*badf/F:.1f} %), payload BER {pb/(F*128):.2e}, FN ok {np.sum((fn & 0x7FFF) == tfn)}"
        else:
            off = np.bincount(((fn & 0x7FFF) - np.arange(F)) % 0x8000).argmax()
            cons = ((fn & 0x7FFF) - np.arange(F)) % 0x8000 == off
            msg += f" | FN-consistent {cons.sum()}/{F}"
        log(msg)
        results.append((fn, payload, Linfo))
    return results, z


def selftest():
    rng = np.random.default_rng(5); lsf = LSF()
    L.encode_callsign_bytes(lsf.dst, b"@ALL"); L.encode_callsign_bytes(lsf.src, b"SP5WWP"); lsf.type[1] = 5; L.update_LSF_CRC(C.byref(lsf))
    ok = 0
    for k in range(50):
        d = rng.integers(0, 256, 16).astype(np.uint8); o = (C.c_float * 192)()
        L.gen_frame(o, (C.c_uint8 * 16)(*d), 1, C.byref(lsf), k % 6, k)
        mine = encode_frame(d, k, bytes(lsf)[(k % 6) * 5:(k % 6) * 5 + 5], k % 6)
        ok += np.array_equal(np.array(o[8:]), mine)
    print(f"encoder self-test: {ok}/50 frames identical to libm17 gen_frame")
    # noiseless decode
    d = rng.integers(0, 256, (20, 16)).astype(np.uint8)
    Lc = np.zeros((20, 296))
    for f in range(20):
        bits = np.unpackbits(np.r_[np.array([0, f], np.uint8), d[f]]); cb = conv_encode(bits)
        Lc[f, KEEP] = 4.0 * (1 - 2 * cb)
    Linfo, _ = bcjr(Lc); info = (Linfo[:, :144] < 0).astype(np.uint8)
    print(f"BCJR noiseless: {np.sum(np.all(np.packbits(info[:,16:144],axis=1)==d,axis=1))}/20 payloads correct")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("mode", choices=["selftest", "sim", "real"]); ap.add_argument("arg", nargs="?")
    ap.add_argument("--frames", type=int, default=600); ap.add_argument("--iters", type=int, default=8)
    a = ap.parse_args()
    if a.mode == "selftest":
        selftest(); sys.exit()
    ch = np.load(a.arg if a.mode == "sim" else a.arg + "_chan.npz"); c = ch["c"]; sigma = float(ch["sigma"])
    if a.mode == "sim":
        rng = np.random.default_rng(7); lsf = LSF()
        L.encode_callsign_bytes(lsf.dst, b"@ALL"); L.encode_callsign_bytes(lsf.src, b"SP5WWP"); lsf.type[1] = 5; L.update_LSF_CRC(C.byref(lsf))
        NF = a.frames; data = rng.integers(0, 256, (NF, 16)).astype(np.uint8); a_ = np.zeros(NF * FRA)
        for k in range(NF):
            o = (C.c_float * 192)(); L.gen_frame(o, (C.c_uint8 * 16)(*data[k]), 1, C.byref(lsf), k % 6, k); a_[k * FRA:(k + 1) * FRA] = o
        J = (len(c) - 1) // 2
        y = np.convolve(a_, c, "same") + rng.normal(0, sigma, len(a_))
        starts = np.arange(0, len(a_), FRA)
        print(f"sim: {NF} frames, residual ISI {10*np.log10(np.sum(np.delete(c, J)**2)/c[J]**2):.1f} dB, sigma {sigma:.3f}")
        turbo(y, starts, c, sigma, a.iters, truth=(data, np.arange(NF)))
    else:
        y = np.fromfile(a.arg + "_ffe.f32", np.float32).astype(float)
        starts = np.loadtxt(a.arg + "_starts.txt").astype(int); starts = starts[starts + FRA <= len(y)]
        res, z = turbo(y, starts, c, sigma, a.iters)
        fn, payload, Linfo = res[-1]
        np.savez(a.arg + "_turbo.npz", fn=fn, payload=payload, conf=np.min(np.abs(Linfo[:, 16:144]), axis=1))
        z.astype(np.float32).tofile(a.arg + "_turbo_sym.f32")
        print(f"wrote {a.arg}_turbo.npz")
