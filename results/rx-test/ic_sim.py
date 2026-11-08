#!/usr/bin/env python3
"""Simulation check of IC variants on the channel measured from a recording (ground truth known).
  ic_sim.py chan.npz [--frames 600] [--etrust 30] [--rounds 5]"""
import argparse, ctypes as C, numpy as np, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import analyze_rx as A
ap = argparse.ArgumentParser(); ap.add_argument("chan"); ap.add_argument("--frames", type=int, default=600)
ap.add_argument("--etrust", type=float, default=30.0); ap.add_argument("--rounds", type=int, default=5)
a_ = ap.parse_args()
L = C.CDLL("/usr/local/lib/libm17.so")
class LSF(C.Structure): _fields_ = [("dst", C.c_uint8 * 6), ("src", C.c_uint8 * 6), ("type", C.c_uint8 * 2), ("meta", C.c_uint8 * 14), ("crc", C.c_uint8 * 2)]
L.gen_frame.argtypes = [C.POINTER(C.c_float), C.POINTER(C.c_uint8), C.c_int, C.POINTER(LSF), C.c_uint8, C.c_uint16]
L.decode_str_frame.argtypes = [C.POINTER(C.c_uint8), C.POINTER(C.c_uint8), C.POINTER(C.c_uint16), C.POINTER(C.c_uint8), C.POINTER(C.c_float)]
L.decode_str_frame.restype = C.c_uint32
ch = np.load(a_.chan); c = ch["c"]; sig = float(ch["sigma"]); lags = ch["lags"]; J = int(lags.max()); k0 = J
lsf = LSF(); L.encode_callsign_bytes(lsf.dst, b"@ALL"); L.encode_callsign_bytes(lsf.src, b"SP5WWP"); lsf.type[1] = 5; L.update_LSF_CRC(C.byref(lsf))
NF = a_.frames; rng = np.random.default_rng(7)
data = rng.integers(0, 256, (NF, 16)).astype(np.uint8); a = np.zeros(NF * 192, np.float32)
for k in range(NF):
    o = (C.c_float * 192)(); L.gen_frame(o, (C.c_uint8 * 16)(*data[k]), 1, C.byref(lsf), k % 6, k); a[k * 192:(k + 1) * 192] = o
def shifted(v):
    M = np.zeros((len(v), len(lags)))
    for jj, l in enumerate(lags):
        if l >= 0: M[l:, jj] = v[:len(v) - l]
        else: M[:l, jj] = v[-l:]
    return M
y = shifted(a) @ c + rng.normal(0, sig, len(a))
dib = lambda s: np.where(s >= 2, 1, np.where(s >= 0, 0, np.where(s >= -2, 2, 3)))
LEV = np.array([-3., -1., 1., 3.])
def soft(v, s):
    w = np.exp(-(v[:, None] - LEV[None, :]) ** 2 / (2 * s * s)); return (w @ LEV) / w.sum(1)
def decode_all(sym):
    ref = np.zeros_like(sym); fnok = np.zeros(NF, bool); pay = np.zeros(NF, int); e = np.zeros(NF)
    for k in range(NF):
        s = np.ascontiguousarray(sym[k * 192 + 8:(k + 1) * 192], np.float32)
        fd = (C.c_uint8 * 16)(); li = (C.c_uint8 * 5)(); fn = C.c_uint16(); lc = C.c_uint8()
        e[k] = L.decode_str_frame(fd, li, C.byref(fn), C.byref(lc), s.ctypes.data_as(C.POINTER(C.c_float))) / 0xFFFF
        fnok[k] = (fn.value & 0x7fff) == k; pay[k] = np.unpackbits(np.frombuffer(bytes(fd), np.uint8) ^ data[k]).sum()
        if lc.value < 6:
            l2 = LSF(); C.memmove(C.addressof(l2) + lc.value * 5, li, 5); o = (C.c_float * 192)()
            if L.gen_frame(o, fd, 1, C.byref(l2), lc.value, fn.value) == 0: ref[k * 192:(k + 1) * 192] = o
    return ref, fnok, pay, e
def tber(sym):
    x = dib(sym); t = dib(a); return 100 * (np.sum((x ^ t) & 1 > 0) + np.sum((x ^ t) & 2 > 0)) / (2 * len(a))
def st(tag, sym, fnok, pay):
    print(f"{tag:22s} true pre-FEC BER {tber(sym):5.2f} %  FN ok {fnok.sum()}/{NF}  bad frames {np.sum(pay > 0):3d} ({100 * np.mean(pay > 0):4.1f} %)")
y0 = y / c[k0]
ref0, fnok0, pay0, e0 = decode_all(y0); st("no IC", y0, fnok0, pay0)
print(f"   Viterbi e: correct frames median {np.median(e0[pay0 == 0]):.1f}, wrong frames median {np.median(e0[pay0 > 0]):.1f}")
for et in sorted({a_.etrust, 25.0, 35.0}):
    trusted = fnok0 & (e0 <= et)
    wrong_trusted = np.sum(trusted & (pay0 > 0))
    cur = y0; ref = ref0
    for r in range(1, a_.rounds + 1):
        ah = soft(cur, sig / c[k0])
        for k in np.where(trusted)[0]: ah[k * 192:(k + 1) * 192] = ref0[k * 192:(k + 1) * 192]
        M = shifted(ah); others = M @ c - M[:, k0] * c[k0]; cur = (y - others) / c[k0]
        ref, fnok, pay, e = decode_all(cur)
    st(f"soft IC, e<={et:g} ({trusted.sum()} trusted, {wrong_trusted} wrongly)", cur, fnok, pay)
