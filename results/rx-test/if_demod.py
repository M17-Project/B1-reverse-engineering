#!/usr/bin/env python3
"""Software FM demodulation of the low-IF signal tapped from the AIC3204 (HPL <- MAR).
  if_demod.py rec.wav tone_hz [--bw 2500] [--out demod.wav]
Finds the IF carrier, band-passes IF +/- bw, takes the instantaneous frequency of the analytic signal,
reports the recovered tone deviation, harmonics and SNR, optionally writes the demodulated audio (Hz)."""
import argparse, numpy as np
from scipy.io import wavfile
from scipy import signal
ap = argparse.ArgumentParser(); ap.add_argument("wav"); ap.add_argument("tone", type=float)
ap.add_argument("--bw", type=float, default=2500); ap.add_argument("--out")
a = ap.parse_args()
fs, x = wavfile.read(a.wav); v = (x[:, 0] if x.ndim == 2 else x)[int(.5 * fs):].astype(float) / 32768; v -= v.mean()
f, P = signal.welch(v, fs, nperseg=1 << 15, scaling="spectrum")
fif = f[np.argmax(P * (f > 300))]
lo, hi = max(fif - a.bw, 100), fif + a.bw
sos = signal.butter(8, [lo, hi], "band", fs=fs, output="sos"); y = signal.sosfiltfilt(sos, v)
fi = np.diff(np.unwrap(np.angle(signal.hilbert(y)))) * fs / (2 * np.pi)
fi = signal.sosfiltfilt(signal.butter(4, 4000, fs=fs, output="sos"), fi)[3000:-3000]; d = fi - fi.mean()
f2, P2 = signal.welch(d, fs, nperseg=1 << 15, scaling="spectrum")
pk = lambda fr: np.sqrt(2 * P2[(f2 > fr - 5) & (f2 < fr + 5)].max())
t = pk(a.tone)
m = (f2 > 50) & (f2 < 4000) & np.all([np.abs(f2 - k * a.tone) > 15 for k in (1, 2, 3)], axis=0)
print(f"{a.wav.split('/')[-1]}: IF carrier {fif:.1f} Hz (mean inst. freq {fi.mean():.1f}), raw rms {20*np.log10(v.std()):.1f} dBFS, "
      f"peak {np.abs(v).max():.3f} | demod tone {a.tone:.0f} Hz: {t:.1f} Hz deviation, "
      f"H2 {20*np.log10(pk(2*a.tone)/t):.1f} dBc, SNR(50-4000) {10*np.log10(t**2/2/P2[m].sum()):.1f} dB")
if a.out:
    wavfile.write(a.out, fs, (d / max(np.abs(d).max(), 1) * 0.9 * 32767).astype(np.int16))
