import sys, numpy as np
from scipy.io import wavfile
sys.path.insert(0, "."); import analyze_rx as A
fs, x = wavfile.read(sys.argv[1]); x = x.astype(float) / 32768
x = x[int(0.5 * fs):]; x -= x.mean()
S, rate, jit, lsnr = A.clock_track(x)
y = A.resample_to_symbol_clock(x, S); y /= y.std()
z = np.convolve(y, A.RRC, "same"); p = A.best_phase(z)
s = z[p::A.SPS]; s = (s - s.mean()) / s.std()
print(f"rate {rate:.4f} Hz ({(rate/4800-1)*1e6:+.2f} ppm), clock-track resid {jit:.4f} sym, phase {p}, {len(s)} symbols")
n = 1 << int(np.ceil(np.log2(2 * len(s))))
F = np.fft.rfft(s, n); ac = np.fft.irfft(np.abs(F) ** 2, n)[:len(s) // 2]
ac /= (len(s) - np.arange(len(ac)))          # unbiased
ac /= ac[0]
top = np.argsort(ac[2:])[::-1][:12] + 2
for k in sorted(top): print(f"lag {k:7d}  r={ac[k]:.3f}")
np.save(sys.argv[2], s)
