#!/usr/bin/env python3
"""Render decoded M17 voice (Codec2 3200) from m17_turbo output, concealing bad frames: gaps of up to --repeat frames
repeat the previous good payload, longer gaps become PCM silence.
  m17_render.py turbo.npz out.wav [--minllr 8]   (8: histogram gap over 1907 real frames, 2 let a bird tweet through)
Each 16-byte M17 payload = two 8-byte Codec2 3200 frames = 320 samples at 8 kHz (40 ms). Missing or
low-confidence frames are decoded as zeros (to keep the stream aligned) and then replaced by silence
in the PCM domain, with 5 ms fades at the edges of every gap."""
import argparse, subprocess, tempfile, os, numpy as np
from scipy.io import wavfile
ap = argparse.ArgumentParser(); ap.add_argument("npz"); ap.add_argument("out"); ap.add_argument("--minllr", type=float, default=8.0)
ap.add_argument("--repeat", type=int, default=2, help="gaps up to this many frames: repeat the previous good payload (0 = silence only)")
a = ap.parse_args()
d = np.load(a.npz); fn = d["fn"] & 0x7FFF; pay = d["payload"]; conf = d["conf"]; F = len(fn)
off = np.bincount((fn - np.arange(F)) % 0x8000).argmax(); cons = (fn - np.arange(F)) % 0x8000 == off
good = {int(f): bytes(p) for f, p, c, q in zip(fn, pay, cons, conf) if c and q >= a.minllr}
lo, hi = min(good), max(good); slots = range(lo, hi + 1)
filled = dict(good); f = lo                          # short gaps: repeat the last good Codec2 payload
while f <= hi:
    if f not in good:
        g = f
        while g not in good:
            g += 1
        if g - f <= a.repeat:
            for k in range(f, g):
                filled[k] = good[f - 1]
        f = g
    f += 1
nrep = len(filled) - len(good)
with tempfile.TemporaryDirectory() as td:
    open(td + "/s.c2", "wb").write(b"".join(filled.get(f, bytes(16)) for f in slots))
    subprocess.run(["c2dec", "3200", td + "/s.c2", td + "/s.raw"], capture_output=True, check=True)
    x = np.fromfile(td + "/s.raw", np.int16).astype(float)
gain = np.ones(len(x)); R = 40                       # 5 ms ramp at 8 kHz
for i, f in enumerate(slots):
    if f not in filled:
        gain[i * 320:(i + 1) * 320] = 0.0
y = x * np.convolve(gain, np.ones(R) / R, "same")   # 5 ms fades into and out of every gap
y[gain == 0] = 0                                    # gaps fully silent
wavfile.write(a.out, 8000, y.astype(np.int16))
print(f"{os.path.basename(a.out)}: {len(good)}/{len(slots)} frames good, {nrep} repeated, {len(slots)-len(filled)} concealed as silence, {len(y)/8000:.1f} s")
