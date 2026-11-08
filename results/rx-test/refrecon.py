#!/usr/bin/env python3
"""Reconstruct the transmitted symbol period from a recording of a periodic 4FSK pattern.

  refrecon.py rec.wav PERIOD out_ref.txt [--start s]

The noise is averaged out over all periods (coherent average on the recovered symbol clock).
Then symbols and channel are solved jointly on one circular period: fit FIR h (X(s) -> Y), invert
it, re-decide s, repeat. A wrong s cannot be explained by a short h, so the final fit SNR is
the acceptance test: it should be close to the SNR of the averaged waveform itself.
"""
import argparse, sys, os
import numpy as np
from scipy.io import wavfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import analyze_rx as A

ap = argparse.ArgumentParser()
ap.add_argument("wav"); ap.add_argument("period", type=int); ap.add_argument("out")
ap.add_argument("--start", type=float, default=0.5)
ap.add_argument("--taps", type=int, nargs=2, default=[160, 480], help="FIR lags pre post")
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
y = y[p:]                                   # symbol centres now at multiples of SPS
K = len(y) // N
seg = y[:K * N].reshape(K, N)
Y = seg.mean(0)
noise = seg - Y
avg_snr = 10 * np.log10(np.mean(Y ** 2) / (np.mean(noise ** 2) / K))
print(f"{K} periods averaged; per-period SNR {10*np.log10(np.mean(Y**2)/np.mean(noise**2)):.1f} dB, "
      f"averaged-waveform SNR {avg_snr:.1f} dB")

rrcF = np.fft.fft(np.roll(np.pad(A.RRC, (0, N - len(A.RRC))), -(len(A.RRC) // 2)))


def wave(s):
    imp = np.zeros(N); imp[::SPS] = s
    w = np.real(np.fft.ifft(np.fft.fft(imp) * rrcF))
    return w - w.mean()


def fit_h(X, Y, pre, post):
    """circular LS FIR: Y[n] = sum_k h_k X[n-k], k in -pre..post"""
    lags = np.arange(-pre, post + 1)
    M = np.stack([np.roll(X, k) for k in lags], 1)
    h, *_ = np.linalg.lstsq(M, Y, rcond=None)
    return h, lags, M @ h


def decide(Y, h, lags, eps):
    H = np.fft.fft(np.roll(np.pad(h, (0, N - len(h))), lags[0]))
    G = np.conj(H) / (np.abs(H) ** 2 + eps * np.max(np.abs(H) ** 2))
    Xh = np.real(np.fft.ifft(np.fft.fft(Y) * G * np.conj(rrcF)))   # inverse channel + matched filter
    v = Xh[::SPS]
    v = (v - v.mean()) / np.sqrt(np.mean((v - v.mean()) ** 2) / 5)
    return A.slice4(v), v


# initial decisions straight from the matched filter
v0 = np.real(np.fft.ifft(np.fft.fft(Y) * np.conj(rrcF)))[::SPS]
s = A.slice4((v0 - v0.mean()) / np.sqrt(np.mean((v0 - v0.mean()) ** 2) / 5))
pre, post = a.taps
best = None
for eps in (1e-1, 3e-2, 1e-2, 3e-3, 1e-3):
    for it in range(30):
        h, lags, Yh = fit_h(wave(s), Y, pre, post)
        fit = 10 * np.log10(np.mean(Y ** 2) / np.mean((Y - Yh) ** 2))
        s_new, v = decide(Y, h, lags, eps)
        ch = int(np.sum(s_new != s))
        s = s_new
        if ch == 0:
            break
    h, lags, Yh = fit_h(wave(s), Y, pre, post)
    fit = 10 * np.log10(np.mean(Y ** 2) / np.mean((Y - Yh) ** 2))
    print(f"eps {eps:g}: {it+1} iters, fit SNR {fit:.1f} dB, symbol counts "
          f"{dict(zip(*np.unique(s, return_counts=True)))}")
    if best is None or fit > best[0]:
        best = (fit, s.copy())
fit, s = best
np.savetxt(a.out, s[None, :], fmt="%+d")
print(f"best fit SNR {fit:.1f} dB vs averaged-waveform SNR {avg_snr:.1f} dB -> wrote {a.out}")
print("ACCEPT" if fit > avg_snr - 6 or fit > 25 else "DOUBTFUL: fit far below the averaged SNR")
