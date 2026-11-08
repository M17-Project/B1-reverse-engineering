#!/usr/bin/env python3
"""Make a synthetic 'received audio' WAV to validate analyze_rx.py against a known channel.

  simulate.py out.wav ref.txt [--flat] [--ppm 40] [--snr 30] [--period 200]
"""
import argparse
import numpy as np
from scipy import signal
from scipy.io import wavfile
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analyze_rx import rrc_taps, FS, RS

ap = argparse.ArgumentParser()
ap.add_argument("wav"); ap.add_argument("ref")
ap.add_argument("--flat", action="store_true", help="ideal channel")
ap.add_argument("--ppm", type=float, default=40.0)
ap.add_argument("--snr", type=float, default=30.0, help="audio SNR dB")
ap.add_argument("--period", type=int, default=200)
ap.add_argument("--secs", type=float, default=20.0)
a = ap.parse_args()

rng = np.random.default_rng(17)
pattern = rng.choice([-3, -1, 1, 3], a.period)
np.savetxt(a.ref, pattern[None, :], fmt="%+d")
nsym = int(a.secs * RS)
sy = np.resize(pattern, nsym)

# TX baseband at an oversampled rate, then the RX ADC samples at 48 kHz * (1 + ppm)
up = 40
imp = np.zeros(nsym * up); imp[::up] = sy
bb = np.convolve(imp, rrc_taps(sps=up, span=8), mode="same")       # deviation-proportional audio
fs_tx = RS * up
t_rx = np.arange(int(len(bb) / fs_tx * FS)) / (FS * (1 + a.ppm * 1e-6))
x = np.interp(t_rx, np.arange(len(bb)) / fs_tx, bb)

if not a.flat:
    b, a_ = signal.butter(1, 300, "high", fs=FS); x = signal.lfilter(b, a_, x)           # HP 300 Hz
    b, a_ = signal.bilinear([1], [750e-6, 1], fs=FS); x = signal.lfilter(b, a_, x)      # 750 us de-emph
    b, a_ = signal.butter(6, 3000, "low", fs=FS); x = signal.lfilter(b, a_, x)          # top-end roll-off
    x = x / np.percentile(np.abs(x), 99.9)
    x = np.tanh(1.3 * x) / np.tanh(1.3)                                                  # soft limiter
x = x / np.max(np.abs(x)) * 0.5
x += rng.normal(0, np.sqrt(np.mean(x ** 2) / 10 ** (a.snr / 10)), len(x))
pad = rng.normal(0, np.sqrt(np.mean(x ** 2) / 10 ** (a.snr / 10)), int(FS))
out = np.r_[pad, x, pad]
wavfile.write(a.wav, int(FS), (out * 32767).astype(np.int16))
print(f"wrote {a.wav}: {len(out) / FS:.1f} s, period {a.period}, ppm {a.ppm}, flat={a.flat}")
