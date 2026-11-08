#!/usr/bin/env python3
"""Find M17 transmissions in a B1 RX recording and crop each one to its own wav.

  m17_segment.py rec.wav outprefix [--thr 4] [--min 1.5]

Detector: per 0.25 s block, band power 300-2000 Hz minus 2600-3400 Hz (dB). M17 4FSK through the stock
RX path gives about +7-8 dB (its spectrum falls off above ~2.5 kHz), open-squelch static 0-1 dB.
Blocks above --thr are merged into segments (gaps of one block are bridged); segments shorter than
--min seconds are dropped. Blocks below --floor (300-2000 Hz PSD) never count: a muted module. One block is trimmed at each edge (key-up / key-down transients).
Writes <outprefix>_seg<N>.wav and prints "N start end" per segment (seconds).
"""
import argparse
import numpy as np
from scipy import signal
from scipy.io import wavfile

ap = argparse.ArgumentParser()
ap.add_argument("wav"); ap.add_argument("out")
ap.add_argument("--thr", type=float, default=4.0); ap.add_argument("--min", type=float, default=1.5)
ap.add_argument("--floor", type=float, default=-95.0, help="min 300-2000 Hz PSD (dB) for a block to count")
a = ap.parse_args()

fs, x = wavfile.read(a.wav)
mono = (x[:, 0] if x.ndim == 2 else x).astype(float) / 32768
B = fs // 4
ratio, level = [], []
for i in range(0, len(mono) - B + 1, B):
    fr, P = signal.welch(mono[i:i + B], fs, nperseg=2048)
    band = lambda lo, hi: 10 * np.log10(np.mean(P[(fr >= lo) & (fr < hi)]) + 1e-30)
    ratio.append(band(300, 2000) - band(2600, 3400)); level.append(band(300, 2000))
on = (np.array(ratio) > a.thr) & (np.array(level) > a.floor)
if np.median(level) < a.floor:
    print(f"WARNING: audio level too low (median 300-2000 Hz {np.median(level):.1f} dB, floor {a.floor}): module muted?")
for k in range(1, len(on) - 1):          # bridge single-block dropouts
    if not on[k] and on[k - 1] and on[k + 1]:
        on[k] = True
segs, k = [], 0
while k < len(on):
    if on[k]:
        j = k
        while j + 1 < len(on) and on[j + 1]:
            j += 1
        s, e = (k + 1) * B, j * B          # trim one block at each edge
        if (e - s) / fs >= a.min:
            segs.append((s, e))
        k = j + 1
    else:
        k += 1
for n, (s, e) in enumerate(segs, 1):
    wavfile.write(f"{a.out}_seg{n}.wav", fs, x[s:e])
    print(n, f"{s / fs:.2f}", f"{e / fs:.2f}")
