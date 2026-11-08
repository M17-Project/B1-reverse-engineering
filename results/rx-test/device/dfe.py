import sys, numpy as np
from scipy.io import wavfile
sys.path.insert(0, "."); import analyze_rx as A
P, SPS = 1024, 10; N = P * SPS
fs, x = wavfile.read(sys.argv[1]); x = x.astype(float) / 32768; x = x[int(.5 * fs):]; x -= x.mean()
S, _, _, _ = A.clock_track(x); y = A.resample_to_symbol_clock(x, S); y /= y.std()
p = A.best_phase(np.convolve(y, A.RRC, "same")); y = y[p:]; K = len(y) // N
seg = y[:K * N].reshape(K, N); Y0 = seg.mean(0)
good = np.array([np.corrcoef(s, Y0)[0, 1] for s in seg]) > 0.99; Y = seg[good].mean(0)
rrcF = np.fft.fft(np.roll(np.pad(A.RRC, (0, N - 81)), -40))
def mf_t2(v):                       # MF + T/2 samples (circular for the averaged period)
    return np.real(np.fft.ifft(np.fft.fft(v) * np.conj(rrcF)))[::5]
Z2 = mf_t2(Y); sc = Z2.std(); Z2 /= sc
s = np.loadtxt(sys.argv[2])
FF, FB = int(sys.argv[3]), int(sys.argv[4])      # FF taps (T/2), FB taps (symbols)
c = FF // 2
def regress(Z, sdec, n):
    k = np.arange(n)
    ff = Z[(2 * k[:, None] + np.arange(-c, FF - c)[None, :]) % len(Z)]
    fb = sdec[(k[:, None] - np.arange(1, FB + 1)[None, :]) % len(sdec)]
    return np.c_[ff, fb, np.ones(n)]
for it in range(50):
    R = regress(Z2, s, P); w, *_ = np.linalg.lstsq(R, s, rcond=None)
    # true DFE run: sequential decisions feed back (circular: run 2 laps, keep the 2nd)
    sd = s.copy(); out = np.zeros(P)
    ffw, fbw, b0 = w[:FF], w[FF:FF + FB], w[-1]
    for lap in range(2):
        for k in range(P):
            ff = Z2[(2 * k + np.arange(-c, FF - c)) % (2 * P)]
            fb = sd[(k - np.arange(1, FB + 1)) % P]
            out[k] = ff @ ffw + fb @ fbw + b0; sd[k] = A.slice4(np.array([out[k]]))[0]
    ch = int(np.sum(sd != s)); s = sd
    if ch == 0: break
mer = 10 * np.log10(5 / np.mean((out - s) ** 2))
blk = (np.arange(P) // 64) % 2 == 0; cv = []
for tr in (blk, ~blk):
    w2, *_ = np.linalg.lstsq(R[tr], s[tr], rcond=None); cv.append(np.mean((R[~tr] @ w2 - s[~tr]) ** 2))
print(f"FF {FF} FB {FB}: {it+1} iters, DFE MER {mer:.1f} dB, cross-validated MER {10*np.log10(5/np.mean(cv)):.1f} dB, "
      f"counts {np.unique(s, return_counts=True)[1].tolist()}")
# apply to every individual (noisy) period, sequential decisions vs the reconstructed pattern
sers = []
for kk, sg in enumerate(seg):
    Zk = mf_t2(sg) / sc; sd = s.copy(); e = 0
    for lap in range(2):
        for k in range(P):
            o = Zk[(2 * k + np.arange(-c, FF - c)) % (2 * P)] @ ffw + sd[(k - np.arange(1, FB + 1)) % P] @ fbw + b0
            sd[k] = A.slice4(np.array([o]))[0]
    sers.append(np.mean(sd != s))
sers = np.array(sers)
print(f"per-period SER through DFE: median {np.median(sers):.4f}, mean {sers.mean():.4f}, good periods mean {sers[good].mean():.4f}")
np.savetxt(sys.argv[5], s[None, :], fmt="%+d")
