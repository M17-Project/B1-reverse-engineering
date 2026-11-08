#!/usr/bin/env python3
"""M17 receive front end for recorded FM-demodulated audio -> symbol stream for m17-decoder-sym.

  m17_front.py rec.wav out.f32 [--eq none|sync|dd] [--taps 41] [--start s] [--report]

Clock recovery + RRC matched filter (analyze_rx), then:
  none : scale/polarity from the stream syncwords only (plain demodulator)
  sync : + T/2-spaced LS FIR equaliser trained on the known syncword symbols
  dd   : + decision-directed refinement of that equaliser over all symbols
Writes float32, one value per symbol, nominal +-1/+-3. --report prints sync statistics.
"""
import argparse, os, sys
import numpy as np
from scipy.io import wavfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import analyze_rx as A

SYNC = {"STR": [-3, -3, -3, -3, +3, +3, -3, +3],     # 0xFF5D
        "LSF": [+3, +3, +3, +3, -3, -3, +3, -3],     # 0x55F7
        "PKT": [+3, -3, +3, +3, -3, -3, -3, -3],     # 0x75FF
        "EOT": [+3, +3, +3, +3, +3, +3, -3, +3]}     # 0x555D
FRAME = 192

ap = argparse.ArgumentParser()
ap.add_argument("wav"); ap.add_argument("out")
ap.add_argument("--eq", default="none", choices=["none", "sync", "dd"])
ap.add_argument("--taps", type=int, default=41)
ap.add_argument("--start", type=float, default=0.3)
ap.add_argument("--report", action="store_true")
ap.add_argument("--pol", type=int, choices=[-1, 1], help="force polarity")
ap.add_argument("--hpf", type=float, default=0, help="software high-pass corner, Hz (0 = off)")
a = ap.parse_args()

fs, x = wavfile.read(a.wav)
x = x.astype(float) / 32768
if x.ndim == 2:
    x = x[:, 0]
x = x[int(a.start * fs):]; x -= x.mean()
if a.hpf > 0:
    from scipy import signal as _sg
    _b, _a = _sg.butter(2, a.hpf, "high", fs=fs); x = _sg.filtfilt(_b, _a, x)
S, rate, _, _ = A.clock_track(x)
y = A.resample_to_symbol_clock(x, S); y /= y.std()
z = np.convolve(y, A.RRC, "same")
p = A.best_phase(z)
s = z[p::A.SPS]
s = (s - s.mean()) / np.sqrt(np.mean((s - s.mean()) ** 2) / 5)


def find_syncs(s, pat):
    pat = np.array(pat, float)
    c = np.correlate(s, pat, "valid") / np.sqrt(np.convolve(s ** 2, np.ones(8), "valid") * np.sum(pat ** 2) + 1e-12)
    return c


# polarity + sync positions from the stream syncword (every 192 symbols)
c = find_syncs(s, SYNC["STR"])
pol = a.pol if a.pol else (1 if np.max(c) > -np.min(c) else -1)
s *= pol; c *= pol
cand = np.where(c > 0.8)[0]
# keep peaks on a consistent 192-symbol grid
best = np.bincount(cand % FRAME, minlength=FRAME).argmax() if len(cand) else 0
grid = np.arange(best, len(s) - 8, FRAME)
hits = grid[c[grid] > 0.6]
if a.report:
    print(f"rate {rate:.3f} Hz ({(rate/4800-1)*1e6:+.1f} ppm), polarity {pol:+d}, {len(s)} symbols, "
          f"stream-sync grid offset {best}, {len(hits)}/{len(grid)} grid slots with corr > 0.6, "
          f"median corr {np.median(c[grid]):.3f}")
# scale from the syncwords (LS gain against the known +-3 pattern)
if len(hits):
    X = np.concatenate([s[h:h + 8] for h in hits]); T = np.tile(SYNC["STR"], len(hits))
    g = np.dot(X, T) / np.dot(X, X); s *= g

out = s
if a.eq != "none" and len(hits) > 20:
    # T/2-spaced equaliser on the MF output, trained on the known sync symbols
    Z2 = z[p % 5::5] * pol
    L = a.taps; c0 = L // 2
    def rows(idx):
        k = np.asarray(idx)
        j = 2 * k[:, None] + np.arange(-c0, L - c0)[None, :] + (p // 5 - (p % 5 > 0) * 0)
        j = np.clip(j, 0, len(Z2) - 1)
        return np.c_[Z2[j], np.ones(len(k))]
    tr_idx = np.concatenate([np.arange(h, h + 8) for h in hits]); tr_t = np.tile(SYNC["STR"], len(hits))
    w, *_ = np.linalg.lstsq(rows(tr_idx), tr_t, rcond=1e-6)
    allk = np.arange(len(s))
    out = rows(allk) @ w
    if a.eq == "dd":
        for it in range(10):
            d = A.slice4(out); d[tr_idx] = tr_t
            w, *_ = np.linalg.lstsq(rows(allk), d, rcond=1e-6)
            new = rows(allk) @ w
            ch = np.sum(A.slice4(new) != A.slice4(out)); out = new
            if ch == 0:
                break
    if a.report:
        e = out[tr_idx] - tr_t
        print(f"equaliser {a.eq}: {L} T/2 taps, sync-symbol MER {10*np.log10(5/np.mean(e**2)):.1f} dB")
if a.report:
    sy = np.concatenate([out[h:h + 8] for h in hits]) if len(hits) else np.array([0.])
    T = np.tile(SYNC["STR"], max(len(hits), 1))
    print(f"sync-symbol MER after front end: {10*np.log10(5/np.mean((sy-T)**2)):.1f} dB; "
          f"overall MER vs own decisions {10*np.log10(5/np.mean((out-A.slice4(out))**2)):.1f} dB")
out.astype(np.float32).tofile(a.out)
