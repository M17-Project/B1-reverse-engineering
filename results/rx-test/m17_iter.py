#!/usr/bin/env python3
"""Iterative, FEC-aided M17 receiver for recorded FM-demodulated audio.

  m17_iter.py rec.wav [--taps 161] [--iters 6] [--thr 60] [--hpf 80] [--pol -1] [--out prefix]

1. Clock recovery, RRC matched filter, T/2-spaced samples (analyze_rx).
2. Equaliser trained on the stream syncwords only.
3. Repeat: decode + re-encode every frame slot with libm17 (./m17_reenc). Frames whose FN fits the
   192-symbol grid and whose pre-FEC bit errors are <= thr become trusted references; the equaliser
   is retrained on all 192 symbols of every trusted frame (+ all syncwords).
4. LSF: majority vote of each LICH chunk over the FN-consistent frames, CRC check (libm17).
Prints per-iteration statistics; writes <out>_sym.f32 (final symbols) and <out>_report.tsv.
"""
import argparse, os, subprocess, sys, ctypes as C
from collections import Counter
import numpy as np
from scipy import signal
from scipy.io import wavfile
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import analyze_rx as A

STR = np.array([-3, -3, -3, -3, +3, +3, -3, +3], float)
FRA = 192

ap = argparse.ArgumentParser()
ap.add_argument("wav")
ap.add_argument("--taps", type=int, default=161)
ap.add_argument("--iters", type=int, default=6)
ap.add_argument("--thr", type=int, default=60, help="max pre-FEC bit errors (of 368) for a trusted frame")
ap.add_argument("--hpf", type=float, default=80.0)
ap.add_argument("--pol", type=int, default=-1)
ap.add_argument("--out", default=None)
a = ap.parse_args()
out = a.out or os.path.splitext(a.wav)[0] + "_iter"

# ---- front end -------------------------------------------------------------
fs, x = wavfile.read(a.wav)
x = (x[:, 0] if x.ndim == 2 else x).astype(float) / 32768
x = x[int(0.3 * fs):]; x -= x.mean()
if a.hpf > 0:
    b, aa = signal.butter(2, a.hpf, "high", fs=fs); x = signal.filtfilt(b, aa, x)
S, rate, _, _ = A.clock_track(x)
y = A.resample_to_symbol_clock(x, S); y /= y.std()
z = np.convolve(y, A.RRC, "same") * a.pol
p = A.best_phase(z)
Z2 = z[p::5]                                  # T/2 samples, symbol k at Z2[2k]
N = len(Z2) // 2
Z2 = Z2[:2 * N]; Z2 = Z2 / Z2[::2].std()
L = a.taps; c0 = L // 2
idx = 2 * np.arange(N)[:, None] + np.arange(-c0, L - c0)[None, :]
idx = np.clip(idx, 0, 2 * N - 1)
D = np.c_[Z2[idx], np.ones(N)]               # one row per symbol

# syncword grid
s0 = Z2[::2] / np.sqrt(np.mean(Z2[::2] ** 2) / 5)
cc = np.correlate(s0, STR, "valid") / np.sqrt(np.convolve(s0 ** 2, np.ones(8), "valid") * 72 + 1e-12)
g = int(np.argmax([cc[o::FRA][:N // FRA - 1].mean() for o in range(FRA)]))
starts = np.arange(g, N - FRA, FRA)
sync_idx = (starts[:, None] + np.arange(8)[None, :]).ravel()
sync_t = np.tile(STR, len(starts))
print(f"{a.wav}: rate {rate:.3f} Hz, {N} symbols, grid offset {g}, {len(starts)} frame slots, "
      f"mean sync corr {cc[starts].mean():.3f}")

lib = C.CDLL("libm17.so")
lib.CRC_M17.restype = C.c_uint16
tmp_s, tmp_t, tmp_r = out + "_sym.f32", out + "_starts.txt", out + "_ref.f32"
np.savetxt(tmp_t, starts, fmt="%d")


def run(sym):
    sym.astype(np.float32).tofile(tmp_s)
    rep = subprocess.run([os.path.join(HERE, "m17_reenc"), tmp_s, tmp_t, tmp_r], capture_output=True, text=True, check=True)
    rows = [l.split("\t") for l in rep.stdout.splitlines()[1:]]
    ref = np.fromfile(tmp_r, np.float32).reshape(-1, FRA)
    fn = np.array([int(r[2]) for r in rows]); cnt = np.array([int(r[3]) for r in rows])
    e = np.array([float(r[4]) for r in rows]); be = np.array([int(r[5]) for r in rows])
    lich = [r[6] for r in rows]
    off = Counter((fn - np.arange(len(fn))) % 0x8000).most_common(1)[0][0]
    cons = ((fn - np.arange(len(fn))) % 0x8000) == off
    return fn, cnt, e, be, lich, ref, cons, rep.stdout


def fit(train_idx, train_t):
    w, *_ = np.linalg.lstsq(D[train_idx], train_t, rcond=1e-6)
    return D @ w


sym = fit(sync_idx, sync_t)
hist = []
for it in range(a.iters + 1):
    fn, cnt, e, be, lich, ref, cons, rep = run(sym)
    trusted = cons & (be >= 0) & (be <= a.thr)
    ber_c = be[cons & (be >= 0)]
    mer = 10 * np.log10(5 / np.mean((sym[sync_idx] - sync_t) ** 2))
    print(f"iter {it}: FN-consistent {cons.sum():4d}/{len(starts)}  trusted {trusted.sum():4d}  "
          f"pre-FEC BER (consistent frames) median {np.median(ber_c)/368*100:5.2f} %  mean {ber_c.mean()/368*100:5.2f} %  "
          f"| sync MER {mer:5.1f} dB  e median {np.median(e[cons]):.1f}")
    hist.append((it, int(cons.sum()), int(trusted.sum()), float(np.median(ber_c) / 368)))
    if it == a.iters:
        break
    tr_frames = np.where(trusted)[0]
    ti = (starts[tr_frames][:, None] + np.arange(FRA)[None, :]).ravel()
    tt = ref[tr_frames].ravel()
    sym = fit(np.r_[ti, sync_idx], np.r_[tt, sync_t])

# ---- LSF by LICH majority vote ---------------------------------------------
chunks = {}
for k in np.where(cons)[0]:
    if cnt[k] < 6:
        chunks.setdefault(cnt[k], Counter())[lich[k]] += 1
lsf = bytearray(30); votes = []
for k in range(6):
    if k in chunks:
        v, nvote = chunks[k].most_common(1)[0]
        lsf[5 * k:5 * k + 5] = bytes.fromhex(v); votes.append(f"{k}:{nvote}/{sum(chunks[k].values())}")
    else:
        votes.append(f"{k}:0")
buf = (C.c_uint8 * 30)(*lsf)
crc_ok = lib.CRC_M17(buf, 30) == 0
dst = C.create_string_buffer(12); src = C.create_string_buffer(12)
lib.decode_callsign_bytes(dst, (C.c_uint8 * 6)(*lsf[0:6])); lib.decode_callsign_bytes(src, (C.c_uint8 * 6)(*lsf[6:12]))
print(f"LSF by LICH vote ({' '.join(votes)}): DST {dst.value.decode(errors='replace')} SRC {src.value.decode(errors='replace')} "
      f"TYPE {lsf[12]:02X}{lsf[13]:02X} META {bytes(lsf[14:28]).hex()} -> CRC {'OK' if crc_ok else 'ERR'}")
open(out + "_report.tsv", "w").write(rep)
