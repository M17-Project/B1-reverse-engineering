#!/usr/bin/env python3
"""Design SCT3258 RX EQUALIZER_FILTER (field 0x70) biquads that flatten the measured SD01 RX path.

  eqdesign.py stock.wav [--fmin 270] [--fmax 3500] [--maxboost 24] [--out dir]

Measured |H| = PSD(recorded RRC-4FSK audio) / |RRC(f)|^2, 0 dB at 1 kHz, smoothed.
Fits 3 RBJ biquads (low shelf + 2 peaking) at fs = 24 kHz to -|H| in [fmin, fmax],
quantises to Q2.14 (16-bit, 14 fractional bits), checks stability, and prints the
AT+SDKWRITE command for each filter (field 0x70 = 112, RX side, enabled).
"""
import argparse, os, sys, json
import numpy as np
from scipy import signal, optimize
from scipy.io import wavfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import analyze_rx as A

FS_EQ = 24000.0
ap = argparse.ArgumentParser()
ap.add_argument("wav")
ap.add_argument("--fmin", type=float, default=270)
ap.add_argument("--fmax", type=float, default=3500)
ap.add_argument("--maxboost", type=float, default=24.0, help="cap on EQ gain anywhere 0-12 kHz, dB")
ap.add_argument("--out", default="eq-out")
a = ap.parse_args()
os.makedirs(a.out, exist_ok=True)

fs, x = wavfile.read(a.wav)
x = x.astype(float) / 32768
if x.ndim == 2:
    x = x[:, 0]
x = x[int(fs):] - x[int(fs):].mean()
f, P = signal.welch(x, fs, nperseg=16384)
_, Hr = signal.freqz(A.RRC, 1, worN=f, fs=fs)
mag = 10 * np.log10(P / (np.abs(Hr) ** 2 + 1e-12) + 1e-30)
# smooth over ~1/12 octave (removes the comb of the repeated test pattern)
sm = np.copy(mag)
for i, fi in enumerate(f):
    if fi <= 0:
        continue
    m = (f > fi * 2 ** (-1 / 24)) & (f < fi * 2 ** (1 / 24))
    sm[i] = 10 * np.log10(np.mean(10 ** (mag[m] / 10)))
sm -= np.interp(1000, f, sm)
band = (f >= a.fmin) & (f <= a.fmax)
fb, target = f[band], -sm[band]          # EQ target = inverse of measured response


def rbj(kind, f0, gdb, q):
    A_ = 10 ** (gdb / 40); w = 2 * np.pi * f0 / FS_EQ; cw, sw = np.cos(w), np.sin(w); al = sw / (2 * q)
    if kind == "peak":
        b = [1 + al * A_, -2 * cw, 1 - al * A_]; aa = [1 + al / A_, -2 * cw, 1 - al / A_]
    elif kind == "lowshelf":
        s = 2 * np.sqrt(A_) * al
        b = [A_ * ((A_ + 1) - (A_ - 1) * cw + s), 2 * A_ * ((A_ - 1) - (A_ + 1) * cw), A_ * ((A_ + 1) - (A_ - 1) * cw - s)]
        aa = [(A_ + 1) + (A_ - 1) * cw + s, -2 * ((A_ - 1) + (A_ + 1) * cw), (A_ + 1) + (A_ - 1) * cw - s]
    else:  # highshelf
        s = 2 * np.sqrt(A_) * al
        b = [A_ * ((A_ + 1) + (A_ - 1) * cw + s), -2 * A_ * ((A_ - 1) + (A_ + 1) * cw), A_ * ((A_ + 1) + (A_ - 1) * cw - s)]
        aa = [(A_ + 1) - (A_ - 1) * cw + s, 2 * ((A_ - 1) - (A_ + 1) * cw), (A_ + 1) - (A_ - 1) * cw - s]
    b = np.array(b) / aa[0]; aa = np.array(aa) / aa[0]
    return b, aa


KINDS = ["peak", "peak", "peak"]   # HPF edge, mid-band tilt, LPF edge
fgrid = np.linspace(1, FS_EQ / 2 - 1, 2048)


def cascade(p):
    secs = [rbj(k, *p[3 * i:3 * i + 3]) for i, k in enumerate(KINDS)]
    return secs


def resp(secs, ff):
    h = np.ones(len(ff), complex)
    for b, aa in secs:
        h *= signal.freqz(b, aa, worN=ff, fs=FS_EQ)[1]
    return 20 * np.log10(np.abs(h) + 1e-12)


def cost(p):
    secs = cascade(p)
    err = resp(secs, fb) - target
    full = resp(secs, fgrid)
    pen = np.sum(np.maximum(full - a.maxboost, 0) ** 2) * 10
    # coefficient range for Q2.14: |c| < 2
    cr = sum(np.sum(np.maximum(np.abs(np.r_[b, aa[1:]]) - 1.99, 0) ** 2) for b, aa in secs) * 1e4
    return np.sum(err ** 2) / len(err) + pen + cr


p0 = [285, 12, 2.0, 1800, 4, 0.7, 3350, 15, 2.0]
lb = [255, 0, 0.5, 600, -8, 0.3, 2900, 0, 0.5]
ub = [400, 24, 8, 2600, 10, 3, 3600, 24, 6]
best = None
for trial in range(12):
    rng = np.random.default_rng(trial)
    x0 = np.clip(np.array(p0) * (1 + 0.2 * rng.normal(size=len(p0)) * (trial > 0)), lb, ub)
    r = optimize.minimize(cost, x0, method="L-BFGS-B", bounds=list(zip(lb, ub)))
    if best is None or r.fun < best.fun:
        best = r
p = best.x
secs = cascade(p)


def q14(v):
    return int(np.clip(np.round(v * 16384), -32768, 32767))


qsecs, cmds = [], []
for i, (b, aa) in enumerate(secs):
    vals = [aa[1], aa[2], b[0], b[1], b[2]]
    qi = [q14(v) for v in vals]
    qsecs.append((np.array(qi[2:]) / 16384, np.r_[1, np.array(qi[:2]) / 16384]))
    sel = 0x10 | (i + 1)                     # RX side (bit5 = 0), enabled (bit4), filter i+1
    payload = bytes([sel]) + b"".join(struct_v.to_bytes(2, "big", signed=True) for struct_v in qi)
    cmds.append(f"AT+SDKWRITE=0,112,0,200,{payload.hex().upper()}")
    poles = np.roots(qsecs[-1][1])
    print(f"filter {i+1} {KINDS[i]:9s} f0 {p[3*i]:7.1f} Hz gain {p[3*i+1]:+6.2f} dB Q {p[3*i+2]:.2f} | "
          f"a1 {vals[0]:+.5f} a2 {vals[1]:+.5f} b0 {vals[2]:+.5f} b1 {vals[3]:+.5f} b2 {vals[4]:+.5f} | "
          f"|pole| max {np.max(np.abs(poles)):.5f}")
    if np.max(np.abs(poles)) >= 1:
        sys.exit("unstable after quantisation")

eq_q = resp(qsecs, fb)
resid = sm[band] + eq_q
print(f"measured response ripple {fb[0]:.0f}-{fb[-1]:.0f} Hz: {np.ptp(sm[band]):.1f} dB p-p -> "
      f"after EQ {np.ptp(resid):.1f} dB p-p (rms {np.std(resid):.2f} dB)")
print(f"max EQ gain 0-12 kHz {resp(qsecs, fgrid).max():+.1f} dB at {fgrid[np.argmax(resp(qsecs, fgrid))]:.0f} Hz; "
      f"EQ gain at 100/200/260/300/1000/3000/3500 Hz: "
      + ", ".join(f"{v:+.1f}" for v in resp(qsecs, np.array([100, 200, 260, 300, 1000, 3000, 3500]))))
print("\n".join(cmds))
disable = [f"AT+SDKWRITE=0,112,0,200,{bytes([i + 1]).hex().upper()}" + "00" * 10 for i in range(3)]
print("disable:", *disable, sep="\n  ")
json.dump({"params": p.tolist(), "kinds": KINDS, "cmds": cmds, "disable": disable}, open(os.path.join(a.out, "eq.json"), "w"), indent=1)

import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
fig, ax = plt.subplots(figsize=(8, 4.2))
ff = f[(f > 50) & (f < 4500)]
ax.plot(ff, sm[(f > 50) & (f < 4500)], color=A.C1, label="measured RX path (smoothed)")
ax.plot(ff, resp(qsecs, ff), color=A.C2, ls="--", label="EQ (3 biquads, Q2.14)")
ax.plot(fb, resid, color=A.C3, label=f"predicted path with EQ ({a.fmin:.0f}-{a.fmax:.0f} Hz)")
ax.axvspan(0, a.fmin, color="#e4e3de", alpha=0.6, lw=0)
ax.set_xlim(0, 4500); ax.set_ylim(-40, 30); ax.set_xlabel("Frequency (Hz)"); ax.set_ylabel("dB (0 dB at 1 kHz)")
ax.set_title("SD01 RX path and SCT3258 RX equaliser design", loc="left"); ax.legend(loc="lower center", fontsize=8.5)
fig.tight_layout(); fig.savefig(os.path.join(a.out, "eq_design.png"), dpi=130)
