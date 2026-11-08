#!/usr/bin/env python3
"""Blind reconstruction of a periodic 4FSK symbol pattern through an unknown linear channel.

  blindeq.py rec.wav PERIOD out_ref.txt [--taps 81] [--start 0.5]

1. Recover the symbol clock, coherently average all good periods (bad ones, r<0.99, dropped).
2. Matched-filter, take T/2 samples of the circular averaged period.
3. Blind T/2-spaced FIR equaliser minimising the Godard/CMA cost for 4-PAM (dispersion constant
   R2 = E[s^4]/E[s^2] = 8.2), several random/centre-spike starts; keep the best.
4. Decisions -> decision-directed refinement (circular LS channel fit + regularised inverse)
   -> acceptance test: fit SNR of a short linear channel vs the averaged-waveform SNR.
"""
import argparse, os, sys
import numpy as np
from scipy import optimize
from scipy.io import wavfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import analyze_rx as A

ap = argparse.ArgumentParser()
ap.add_argument("wav"); ap.add_argument("period", type=int); ap.add_argument("out")
ap.add_argument("--taps", type=int, default=81)
ap.add_argument("--start", type=float, default=0.5)
ap.add_argument("--restarts", type=int, default=12)
a = ap.parse_args()
P, SPS = a.period, A.SPS
N = P * SPS

fs, x = wavfile.read(a.wav)
x = x.astype(float) / (32768 if x.dtype == np.int16 else 1)
if x.ndim == 2:
    x = x[:, np.argmax(x.std(0))]
x = x[int(a.start * fs):]; x -= x.mean()
S, rate, _, _ = A.clock_track(x)
y = A.resample_to_symbol_clock(x, S); y /= y.std()
z = np.convolve(y, A.RRC, "same"); p = A.best_phase(z)
y = y[p:]
K = len(y) // N
seg = y[:K * N].reshape(K, N)
Y0 = seg.mean(0)
r = np.array([np.corrcoef(s, Y0)[0, 1] for s in seg])
good = r > 0.99
Y = seg[good].mean(0)
noise = seg[good] - Y
per_snr = 10 * np.log10(np.mean(Y ** 2) / np.mean(noise ** 2))
avg_snr = per_snr + 10 * np.log10(good.sum())
print(f"{K} periods, {good.sum()} kept (r>0.99); per-period SNR {per_snr:.1f} dB, averaged {avg_snr:.1f} dB")

rrcF = np.fft.fft(np.roll(np.pad(A.RRC, (0, N - len(A.RRC))), -(len(A.RRC) // 2)))
Z = np.real(np.fft.ifft(np.fft.fft(Y) * np.conj(rrcF)))     # MF output, circular
H2 = SPS // 2
Z2 = Z[::H2]                                                # T/2 samples, 2P long
Z2 = Z2 / Z2.std()
L = a.taps
c = L // 2
# data matrix: row k = T/2 samples around symbol k (circular), so out_k = D[k] @ w
idx = (2 * np.arange(P)[:, None] + np.arange(-c, L - c)[None, :]) % (2 * P)
D = Z2[idx]
R2 = 8.2


def cost(w):
    o = D @ w
    o = o / np.sqrt(np.mean(o ** 2) / 5)          # fix scale: E[s^2] = 5
    return np.mean((o ** 2 - R2) ** 2)


def kurt(o):
    return np.mean(o ** 4) / np.mean(o ** 2) ** 2


rng = np.random.default_rng(1)
best = None
for t in range(a.restarts):
    w0 = np.zeros(L)
    w0[c + (rng.integers(-6, 7) * 2 if t else 0)] = 1.0
    w0 += 0.05 * rng.normal(size=L) * (t > 0)
    res = optimize.minimize(cost, w0, method="L-BFGS-B", options={"maxiter": 3000})
    o = D @ res.x
    o = (o - o.mean()) / np.sqrt(np.mean((o - o.mean()) ** 2) / 5)
    k = kurt(o)
    print(f"start {t:2d}: CMA cost {res.fun:.3f}, kurtosis {k:.3f} (4-PAM ideal 1.64, Gaussian 3.0)")
    if best is None or res.fun < best[0]:
        best = (res.fun, o)
o = best[1]
s = A.slice4(o)
print(f"blind decisions: counts {dict(zip(*np.unique(s, return_counts=True)))}")

# stage 2: decision-directed LS on the same short equaliser (+DC); few DOF so wrong decisions
# cannot be absorbed the way a long channel model absorbs them
D1 = np.c_[D, np.ones(P)]
for it in range(100):
    w, *_ = np.linalg.lstsq(D1, s, rcond=None)
    o = D1 @ w
    s_new = A.slice4(o)
    ch = int(np.sum(s_new != s))
    s = s_new
    if ch == 0:
        break
mer = 10 * np.log10(np.mean(s ** 2) / np.mean((o - s) ** 2))
print(f"DD-LS equaliser: {it+1} iters, MER {mer:.1f} dB, counts {dict(zip(*np.unique(s, return_counts=True)))}")


# --- decision-directed refinement with acceptance test (as refrecon.py) ---
def wave(s):
    imp = np.zeros(N); imp[::SPS] = s
    w = np.real(np.fft.ifft(np.fft.fft(imp) * rrcF))
    return w - w.mean()


def fit_h(X, Y, pre=160, post=480):
    lags = np.arange(-pre, post + 1)
    M = np.stack([np.roll(X, k) for k in lags], 1)
    h, *_ = np.linalg.lstsq(M, Y, rcond=None)
    return h, lags, M @ h


def fit_snr(s):
    h, lags, Yh = fit_h(wave(s), Y)
    return 10 * np.log10(np.mean(Y ** 2) / np.mean((Y - Yh) ** 2)), h, lags


for it in range(40):
    f, h, lags = fit_snr(s)
    Hf = np.fft.fft(np.roll(np.pad(h, (0, N - len(h))), lags[0]))
    G = np.conj(Hf) / (np.abs(Hf) ** 2 + 1e-3 * np.max(np.abs(Hf) ** 2))
    v = np.real(np.fft.ifft(np.fft.fft(Y) * G * np.conj(rrcF)))[::SPS]
    v = (v - v.mean()) / np.sqrt(np.mean((v - v.mean()) ** 2) / 5)
    s_new = A.slice4(v)
    ch = int(np.sum(s_new != s))
    print(f"DD iter {it}: fit SNR {f:.1f} dB, {ch} symbols changed")
    s = s_new
    if ch == 0:
        break
f, h, lags = fit_snr(s)
np.savetxt(a.out, s[None, :], fmt="%+d")
print(f"final fit SNR {f:.1f} dB vs averaged-waveform SNR {avg_snr:.1f} dB -> {a.out}")
print("ACCEPT" if f > min(avg_snr - 6, 30) else "DOUBTFUL")
