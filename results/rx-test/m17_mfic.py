#!/usr/bin/env python3
"""Full-channel matched-filter interference cancellation for M17 (offline).

Real data:  m17_mfic.py real rec.wav ic_prefix [--rounds 6] [--pre 300] [--post 900]
            (ic_prefix = output prefix of m17_ic.py: uses <prefix>_starts.txt and <prefix>_sym.f32 as start)
Simulation: m17_mfic.py sim chan.npz [--frames 600]
            (chan.npz written by the real run: pulse g, residual PSD)

Model (10 samples/symbol, symbol k at sample 10k):  y[n] = sum_k a_k g[n - 10k] + v[n]
Round:  y_hat = sum_k ah_k g[n - 10k];  r = y - y_hat
        soft_k = ah_k + <r, g(. - 10k)> / <g, g>          (MF over the full pulse, own symbol added back)
        LS gain/offset to +-1/+-3 on trusted symbols; decode + re-encode (m17_reenc);
        ah = re-encoded symbols of trusted frames (FN fits grid, <= thr pre-FEC bit errors), hard decisions elsewhere.
"""
import argparse, os, subprocess, sys
from collections import Counter
import numpy as np
from scipy import signal
from scipy.io import wavfile
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import analyze_rx as A

FRA = 192
STR = np.array([-3, -3, -3, -3, +3, +3, -3, +3], float)
SPS = 10
ap = argparse.ArgumentParser()
ap.add_argument("mode", choices=["real", "sim"]); ap.add_argument("arg1"); ap.add_argument("arg2", nargs="?")
ap.add_argument("--rounds", type=int, default=6); ap.add_argument("--thr", type=int, default=60)
ap.add_argument("--pre", type=int, default=300); ap.add_argument("--post", type=int, default=900)
ap.add_argument("--frames", type=int, default=600); ap.add_argument("--out", default=None)
a = ap.parse_args()


def reenc(sym, starts, prefix):
    sym.astype(np.float32).tofile(prefix + "_mf_tmp.f32"); np.savetxt(prefix + "_mf_starts.txt", starts, fmt="%d")
    rep = subprocess.run([os.path.join(HERE, "m17_reenc"), prefix + "_mf_tmp.f32", prefix + "_mf_starts.txt", prefix + "_mf_ref.f32"],
                         capture_output=True, text=True, check=True)
    rows = [l.split("\t") for l in rep.stdout.splitlines()[1:]]
    ref = np.fromfile(prefix + "_mf_ref.f32", np.float32).reshape(-1, FRA)
    fn = np.array([int(r[2]) for r in rows]); be = np.array([int(r[5]) for r in rows])
    off = Counter((fn - np.arange(len(fn))) % 0x8000).most_common(1)[0][0]
    return fn, be, ref, ((fn - np.arange(len(fn))) % 0x8000) == off


def synth(sym_vals, g, n_samp):
    imp = np.zeros(n_samp); imp[::SPS][:len(sym_vals)] = sym_vals
    full = np.convolve(imp, g)             # g index 0 <-> lag -pre
    return full[a.pre:a.pre + n_samp]


def mf(r, g, nsym):
    # <r, g(. - 10k)> for every k: correlate r with g, sample at symbol instants
    # pulse of symbol k: p_k[n] = g[n - 10k + pre];  with R = [0]*P + r + [0]*P (P = pre+post),
    # c[m] = sum_i R[m+i] g[i] = sum_i r[m+i-P] g[i]  ->  <r, p_k> = c[10k + post]
    P = a.pre + a.post
    c = np.correlate(np.r_[np.zeros(P), r, np.zeros(P)], g, "valid")
    return c[a.post:a.post + SPS * nsym:SPS][:nsym]


def fit_pulse(y, ah, n_samp):
    imp = np.zeros(n_samp); imp[::SPS][:len(ah)] = ah
    h, k = A.ls_fir(imp, y, a.pre, a.post, ridge=1e-6)
    return h                                # h[j] at lag k[j] = j - pre


def rounds(y, ah, starts, trusted, ref, prefix, nsym, truth=None, data_check=None):
    g = fit_pulse(y, ah, len(y)); Eg = np.dot(g, g)
    hist = []
    for r in range(1, a.rounds + 1):
        yh = synth(ah, g, len(y)); res = y - yh
        soft = ah + mf(res, g, nsym) / Eg
        tr_i = np.concatenate([np.arange(s, s + FRA) for s in starts[trusted]]) if trusted.any() else np.arange(nsym)
        G = np.c_[soft[tr_i], np.ones(len(tr_i))]; gg = np.linalg.lstsq(G, ah[tr_i], rcond=None)[0]
        soft = soft * gg[0] + gg[1]
        fn, be, ref, cons = reenc(soft, starts, prefix)
        trusted = cons & (be >= 0) & (be <= a.thr)
        c = be[cons & (be >= 0)]
        line = (f"MF-IC round {r}: FN-consistent {cons.sum():4d}/{len(starts)}  trusted {trusted.sum():4d}  "
                f"self-measured BER median {np.median(c)/3.68:5.2f} %")
        if truth is not None:
            line += data_check(soft, fn)
        print(line)
        ah = A.slice4(soft).astype(float)
        for i in np.where(trusted)[0]: ah[starts[i]:starts[i] + FRA] = ref[i]
        g = fit_pulse(y, ah, len(y)) if truth is None else g   # refine the pulse on real data
        Eg = np.dot(g, g)
        hist.append(soft)
    return soft, g


if a.mode == "real":
    wav, prefix = a.arg1, a.arg2
    fs, x = wavfile.read(wav); x = (x[:, 0] if x.ndim == 2 else x).astype(float) / 32768
    x = x[int(0.3 * fs):]; x -= x.mean()
    b, aa = signal.butter(2, 80, "high", fs=fs); x = signal.filtfilt(b, aa, x)
    S, rate, _, _ = A.clock_track(x); y = A.resample_to_symbol_clock(x, S); y /= y.std()
    z = np.convolve(y, A.RRC, "same") * -1; p = A.best_phase(z); y = -y[p:]
    nsym = len(y) // SPS; y = y[:SPS * nsym]
    starts = np.loadtxt(prefix + "_starts.txt").astype(int)
    sym0 = np.fromfile(prefix + "_sym.f32", np.float32)[:nsym]
    fn, be, ref, cons = reenc(sym0, starts, prefix); trusted = cons & (be >= 0) & (be <= a.thr)
    print(f"start (m17_ic output): FN-consistent {cons.sum()}  trusted {trusted.sum()}")
    ah = A.slice4(sym0).astype(float)
    for i in np.where(trusted)[0]: ah[starts[i]:starts[i] + FRA] = ref[i]
    soft, g = rounds(y, ah, starts, trusted, ref, prefix, nsym)
    soft.astype(np.float32).tofile(prefix + "_mfic_sym.f32")
    # channel + residual spectrum for the simulation
    yh = synth(ah, g, len(y)); f, Pr = signal.welch(y - yh, 48000, nperseg=4096)
    np.savez(prefix + "_mfic_chan.npz", g=g, pre=a.pre, post=a.post, f=f, Pr=Pr)
    print(f"model SNR {10*np.log10(np.var(y)/np.var(y-yh)):.1f} dB; wrote {prefix}_mfic_sym.f32 and _mfic_chan.npz")

else:
    import ctypes as C
    ch = np.load(a.arg1); g = ch["g"]; f, Pr = ch["f"], ch["Pr"]
    L = C.CDLL("libm17.so")
    class LSF(C.Structure): _fields_ = [("dst", C.c_uint8 * 6), ("src", C.c_uint8 * 6), ("type", C.c_uint8 * 2), ("meta", C.c_uint8 * 14), ("crc", C.c_uint8 * 2)]
    L.gen_frame.argtypes = [C.POINTER(C.c_float), C.POINTER(C.c_uint8), C.c_int, C.POINTER(LSF), C.c_uint8, C.c_uint16]
    lsf = LSF(); L.encode_callsign_bytes(lsf.dst, b"@ALL"); L.encode_callsign_bytes(lsf.src, b"SP5WWP"); lsf.type[1] = 5; L.update_LSF_CRC(C.byref(lsf))
    rng = np.random.default_rng(11); NF = a.frames
    data = rng.integers(0, 256, (NF, 16)).astype(np.uint8); truth = np.zeros(NF * FRA)
    for k in range(NF):
        o = (C.c_float * 192)(); L.gen_frame(o, (C.c_uint8 * 16)(*data[k]), 1, C.byref(lsf), k % 6, k); truth[k * FRA:(k + 1) * FRA] = o
    nsym = len(truth); n = SPS * nsym
    y = synth(truth, g, n)
    # coloured noise with the measured residual PSD
    wn = rng.normal(0, 1, n); W = np.fft.rfft(wn); fr = np.fft.rfftfreq(n, 1 / 48000)
    W *= np.sqrt(np.interp(fr, f, Pr)); v = np.fft.irfft(W, n)
    v *= np.sqrt(np.mean(Pr) * 48000 / 2) / v.std() if v.std() > 0 else 1
    y = y + v
    print(f"sim: {NF} frames, signal/noise {10*np.log10(np.var(y - v)/np.var(v)):.1f} dB")
    starts = np.arange(0, nsym, FRA)
    dib = lambda s: np.where(s >= 2, 1, np.where(s >= 0, 0, np.where(s >= -2, 2, 3)))
    def check(soft, fn):
        x_ = dib(soft); t_ = dib(truth); ber = (np.sum((x_ ^ t_) & 1 > 0) + np.sum((x_ ^ t_) & 2 > 0)) / (2 * nsym)
        # payload check via re-decode: compare re-encoded refs with truth per frame
        ref = np.fromfile(prefix + "_mf_ref.f32", np.float32).reshape(-1, FRA)
        bad = np.sum([not np.array_equal(ref[i], truth[i * FRA:(i + 1) * FRA]) for i in range(NF)])
        return f" | TRUE pre-FEC BER {100*ber:5.2f} %  frames decoded wrong {bad} ({100*bad/NF:.1f} %)"
    prefix = os.path.splitext(a.arg1)[0] + "_sim"
    # initial estimate: plain MF (no IC) then hard decisions
    Eg = np.dot(g, g); soft0 = mf(y, g, nsym) / Eg
    G = np.c_[soft0, np.ones(nsym)]; gg = np.linalg.lstsq(G, truth, rcond=None)[0]; soft0 = soft0 * gg[0] + gg[1]
    fn, be, ref, cons = reenc(soft0, starts, prefix); print("plain MF (no IC):" + check(soft0, fn))
    trusted = cons & (be >= 0) & (be <= a.thr)
    ah = A.slice4(soft0).astype(float)
    for i in np.where(trusted)[0]: ah[starts[i]:starts[i] + FRA] = ref[i]
    rounds(y, ah, starts, trusted, ref, prefix, nsym, truth=truth, data_check=check)
