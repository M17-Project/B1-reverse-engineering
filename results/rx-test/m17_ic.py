#!/usr/bin/env python3
"""M17 receiver with FEC-aided interference cancellation (turbo-equalisation style), offline.

  m17_ic.py rec.wav [--taps 161] [--isi 16] [--rounds 5] [--thr 60] [--hpf 80] [--pol -1] [--out prefix]
            [--init earlier_prefix_w.npz] [--prior 3000]

Stage 1 (as m17_iter.py): clock recovery, RRC MF, T/2 LS equaliser retrained on re-encoded trusted frames.
Stage 2: residual-ISI model y_k = sum_j c_j a_{k-j} (j = -isi..isi) fitted on trusted frames, then per round:
  y_ic[k] = (y_k - sum_{j!=0} c_j a_hat[k-j]) / c_0
  with a_hat = re-encoded symbols of trusted frames from the previous round, hard decisions elsewhere;
  LS gain/offset normalisation to +-1/+-3 against the trusted references; decode + re-encode (m17_reenc).
Reports per round: FN-consistent frames, trusted frames, pre-FEC BER. Writes <out>_sym.f32 (best symbols).
"""
import argparse, os, subprocess, sys
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
ap.add_argument("wav"); ap.add_argument("--taps", type=int, default=161); ap.add_argument("--isi", type=int, default=16)
ap.add_argument("--rounds", type=int, default=5); ap.add_argument("--thr", type=int, default=60)
ap.add_argument("--hpf", type=float, default=80.0); ap.add_argument("--pol", type=int, default=-1)
ap.add_argument("--out", default=None)
ap.add_argument("--init", default=None, help="warm start: <prefix>_w.npz with FFE weights from an earlier recording")
ap.add_argument("--prior", type=float, default=3000.0, help="weight of the warm-start prior, in equivalent symbols")
ap.add_argument("--ridge", type=float, default=0.0, help="Tikhonov weight pulling the FFE weights to zero (conditioning)")
ap.add_argument("--seed", default=None, help="second pass: symbols (f32, e.g. <prefix>_turbo_sym.f32) whose decoded frames train the first FFE round")
a = ap.parse_args()
out = a.out or os.path.splitext(a.wav)[0] + "_ic"

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
Z2 = z[p::5]; N = len(Z2) // 2; Z2 = Z2[:2 * N]; Z2 /= Z2[::2].std()
L = a.taps; c0 = L // 2
idx = np.clip(2 * np.arange(N)[:, None] + np.arange(-c0, L - c0)[None, :], 0, 2 * N - 1)
D = np.c_[Z2[idx], np.ones(N)]
s0 = Z2[::2] / np.sqrt(np.mean(Z2[::2] ** 2) / 5)
cc = np.correlate(s0, STR, "valid") / np.sqrt(np.convolve(s0 ** 2, np.ones(8), "valid") * 72 + 1e-12)
g = int(np.argmax([cc[o::FRA][:N // FRA - 1].mean() for o in range(FRA)]))
starts = np.arange(g, N - FRA, FRA)
sync_idx = (starts[:, None] + np.arange(8)[None, :]).ravel(); sync_t = np.tile(STR, len(starts))
np.savetxt(out + "_starts.txt", starts, fmt="%d")


def run(sym):
    sym.astype(np.float32).tofile(out + "_tmp.f32")
    rep = subprocess.run([os.path.join(HERE, "m17_reenc"), out + "_tmp.f32", out + "_starts.txt", out + "_ref.f32"],
                         capture_output=True, text=True, check=True)
    rows = [l.split("\t") for l in rep.stdout.splitlines()[1:]]
    ref = np.fromfile(out + "_ref.f32", np.float32).reshape(-1, FRA)
    fn = np.array([int(r[2]) for r in rows]); be = np.array([int(r[5]) for r in rows])
    off = Counter((fn - np.arange(len(fn))) % 0x8000).most_common(1)[0][0]
    cons = ((fn - np.arange(len(fn))) % 0x8000) == off
    return fn, be, ref, cons


def frame_idx(fr):
    return (starts[fr][:, None] + np.arange(FRA)[None, :]).ravel()


def report(tag, be, cons, trusted):
    c = be[cons & (be >= 0)]
    print(f"{tag:10s} FN-consistent {cons.sum():4d}/{len(starts)}  trusted {trusted.sum():4d}  "
          f"pre-FEC BER (consistent) median {np.median(c)/3.68:5.2f} %  mean {c.mean()/3.68:5.2f} %  "
          f"frames >60 err {np.sum(c > 60):3d}  >30 err {np.sum(c > 30):3d}")


# ---- stage 1: FEC-aided linear equaliser ------------------------------------
w0 = None
if a.init:
    w0 = np.load(a.init)["w"]
    if len(w0) != D.shape[1]:
        sys.exit(f"--init has {len(w0)} weights, need {D.shape[1]} (same --taps)")


def fit(rows, tgt):
    # LS fit + a.ridge * |w|^2 (conditioning) + a.prior * |w - w0|^2 (warm start); bias column not penalised
    n = D.shape[1]; I = np.eye(n); I[-1, -1] = 0
    Ms, ts = [D[rows]], [tgt]
    if a.ridge > 0:
        Ms.append(np.sqrt(a.ridge) * I); ts.append(np.zeros(n))
    if w0 is not None:
        Ms.append(np.sqrt(a.prior) * I); ts.append(np.sqrt(a.prior) * w0 * np.diag(I))
    return np.linalg.lstsq(np.concatenate(Ms), np.concatenate(ts), rcond=1e-6)[0]


w = w0 if w0 is not None else fit(sync_idx, sync_t)
sym = D @ w
if a.seed:
    seed = np.fromfile(a.seed, np.float32).astype(float)
    if len(seed) != len(sym):
        sys.exit(f"--seed has {len(seed)} symbols, need {len(sym)}")
    sym = seed
for it in range(4):
    fn, be, ref, cons = run(sym); trusted = cons & (be >= 0) & (be <= a.thr)
    report(f"FFE it{it}", be, cons, trusted)
    tr = np.where(trusted)[0]; ti = frame_idx(tr)
    w = fit(np.r_[ti, sync_idx], np.r_[ref[tr].ravel(), sync_t])
    sym = D @ w
fn, be, ref, cons = run(sym); trusted = cons & (be >= 0) & (be <= a.thr)
report("FFE final", be, cons, trusted)
np.savez(out + "_w.npz", w=w, taps=L, ntrusted=int(trusted.sum()))
yffe = sym.copy()
yffe.astype(np.float32).tofile(out + "_ffe.f32")   # FFE output for the turbo equaliser
best = (np.median(be[cons & (be >= 0)]), sym.copy())

# ---- stage 2: interference cancellation with FEC-corrected decisions --------
J = a.isi
lags = np.arange(-J, J + 1)


def decisions(cur, ref, trusted):
    ah = A.slice4(cur).astype(float)
    tr = np.where(trusted)[0]
    ah[frame_idx(tr)] = ref[tr].ravel()
    ah[sync_idx] = sync_t
    return ah


def shifted(v):
    # M[k, j] = v[k - lags[j]] (zero outside)
    M = np.zeros((len(v), len(lags)))
    for jj, l in enumerate(lags):
        if l >= 0: M[l:, jj] = v[:len(v) - l]
        else: M[:l, jj] = v[-l:]
    return M


cur = yffe
for r in range(1, a.rounds + 1):
    ah = decisions(cur, ref, trusted)
    # fit residual ISI on trusted frames: yffe = A(ah) c
    tr_i = np.r_[frame_idx(np.where(trusted)[0]), sync_idx]
    M = shifted(ah)
    c, *_ = np.linalg.lstsq(np.c_[M[tr_i], np.ones(len(tr_i))], yffe[tr_i], rcond=None)
    cj, bias = c[:-1], c[-1]
    k0 = J
    others = M @ cj - M[:, k0] * cj[k0]
    yic = (yffe - bias - others) / cj[k0]
    # LS gain/offset against the trusted references
    G = np.c_[yic[tr_i], np.ones(len(tr_i))]; gg = np.linalg.lstsq(G, ah[tr_i], rcond=None)[0]
    yic = yic * gg[0] + gg[1]
    fn, be, ref, cons = run(yic); trusted = cons & (be >= 0) & (be <= a.thr)
    isi_db = 10 * np.log10(np.sum(np.delete(cj, k0) ** 2) / cj[k0] ** 2)
    if r == 1:   # channel model + noise for the simulation check
        resid = yffe[tr_i] - (np.c_[M[tr_i], np.ones(len(tr_i))] @ c)
        np.savez(out + "_chan.npz", c=cj, bias=bias, sigma=resid.std(), lags=lags)
    report(f"IC round{r}", be, cons, trusted)
    print(f"           residual ISI energy {isi_db:.1f} dB rel. main tap, c0 {cj[k0]:.3f}")
    m = np.median(be[cons & (be >= 0)])
    if m < best[0]:
        best = (m, yic.copy())
    cur = yic
best[1].astype(np.float32).tofile(out + "_sym.f32")
print(f"best median pre-FEC BER {best[0]/3.68:.2f} % -> {out}_sym.f32")
