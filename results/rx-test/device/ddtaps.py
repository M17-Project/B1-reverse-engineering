import sys, numpy as np
from scipy.io import wavfile
from scipy import optimize
sys.path.insert(0, "."); import analyze_rx as A
P, SPS = 1024, 10; N = P * SPS
fs, x = wavfile.read(sys.argv[1]); x = x.astype(float) / 32768; x = x[int(.5 * fs):]; x -= x.mean()
S, _, _, _ = A.clock_track(x); y = A.resample_to_symbol_clock(x, S); y /= y.std()
p = A.best_phase(np.convolve(y, A.RRC, "same")); y = y[p:]; K = len(y) // N
seg = y[:K * N].reshape(K, N); Y0 = seg.mean(0)
good = np.array([np.corrcoef(s, Y0)[0, 1] for s in seg]) > 0.99; Y = seg[good].mean(0)
rrcF = np.fft.fft(np.roll(np.pad(A.RRC, (0, N - 81)), -40))
Z2 = np.real(np.fft.ifft(np.fft.fft(Y) * np.conj(rrcF)))[::5]; Z2 /= Z2.std()
s0 = np.loadtxt(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2] != "-" else None

def mat(L):
    c = L // 2
    idx = (2 * np.arange(P)[:, None] + np.arange(-c, L - c)[None, :]) % (2 * P)
    return np.c_[Z2[idx], np.ones(P)]

def cma_init(L, rng, restarts=8):
    D = mat(L)[:, :-1]; c = L // 2; best = None
    for t in range(restarts):
        w0 = np.zeros(L); w0[c] = 1; w0 += 0.05 * rng.normal(size=L) * (t > 0)
        def cost(w):
            o = D @ w; o = o / np.sqrt(np.mean(o ** 2) / 5); return np.mean((o ** 2 - 8.2) ** 2)
        r = optimize.minimize(cost, w0, method="L-BFGS-B", options={"maxiter": 3000})
        if best is None or r.fun < best[0]: best = (r.fun, D @ r.x)
    o = best[1]; o = (o - o.mean()) / np.sqrt(np.mean((o - o.mean()) ** 2) / 5)
    return A.slice4(o)

def dd(D, s):
    for it in range(200):
        w, *_ = np.linalg.lstsq(D, s, rcond=None); sn = A.slice4(D @ w)
        if np.array_equal(sn, s): break
        s = sn
    return s, w

rng = np.random.default_rng(0)
s = cma_init(81, rng) if s0 is None else s0
for L in [81, 121, 161, 241, 321, 401]:
    D = mat(L); s, w = dd(D, s)
    o = D @ w; mer_in = 10 * np.log10(5 / np.mean((o - s) ** 2))
    # 2-fold CV: fit on even-indexed blocks of 64 symbols, test on odd
    blk = (np.arange(P) // 64) % 2 == 0
    cv = []
    for tr in (blk, ~blk):
        w2, *_ = np.linalg.lstsq(D[tr], s[tr], rcond=None); o2 = D[~tr] @ w2
        cv.append(np.mean((o2 - s[~tr]) ** 2))
    o_cv_dec = None
    print(f"taps {L:3d}: in-sample MER {mer_in:5.1f} dB, cross-validated MER {10*np.log10(5/np.mean(cv)):5.1f} dB, "
          f"counts {np.unique(s, return_counts=True)[1].tolist()}")
np.savetxt(sys.argv[3] if len(sys.argv) > 3 else "/dev/null", s[None, :], fmt="%+d")
