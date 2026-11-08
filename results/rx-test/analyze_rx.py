#!/usr/bin/env python3
"""Analyse a recording of RRC-shaped 4FSK (M17-like) received through an analog FM path.

Usage:
  analyze_rx.py rec.wav [--ref symbols.txt] [--start s] [--dur s] [--out dir]

symbols.txt: one period of the transmitted pattern, symbols in {+3,+1,-1,-3}
separated by whitespace or commas. Without --ref the period is found blindly
(decision-directed, optimistic SER - say so when reporting).

Outputs (in --out): spectrum.png, channel.png, linearity.png, eye.png,
results.json, and a text summary on stdout.
"""
import argparse, json, os, sys
import numpy as np
from scipy import signal, linalg, optimize
from scipy.interpolate import CubicSpline
from scipy.io import wavfile
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

RS = 4800.0          # nominal symbol rate
FS = 48000.0         # working rate
SPS = 10             # samples/symbol at working rate
ALPHA = 0.5
SPAN = 8             # RRC span in symbols
DEV = {3: 2400.0, 1: 800.0}  # Hz per symbol level (M17)

# plot style: light surface, fixed categorical order (dataviz reference palette)
C1, C2, C3 = "#2a78d6", "#eb6834", "#1baf7a"
INK, MUTED, GRID = "#1f1f1e", "#6b6a64", "#e4e3de"
plt.rcParams.update({
    "figure.facecolor": "#fcfcfb", "axes.facecolor": "#fcfcfb",
    "axes.edgecolor": MUTED, "axes.labelcolor": INK, "xtick.color": MUTED,
    "ytick.color": MUTED, "axes.grid": True, "grid.color": GRID,
    "grid.linewidth": 0.8, "lines.linewidth": 2, "axes.spines.top": False,
    "axes.spines.right": False, "font.size": 10, "legend.frameon": False,
})


def rrc_taps(sps=SPS, alpha=ALPHA, span=SPAN):
    t = np.arange(-span * sps // 2, span * sps // 2 + 1) / sps
    h = np.zeros_like(t)
    for i, ti in enumerate(t):
        if abs(ti) < 1e-12:
            h[i] = 1 - alpha + 4 * alpha / np.pi
        elif abs(abs(ti) - 1 / (4 * alpha)) < 1e-9:
            h[i] = alpha / np.sqrt(2) * ((1 + 2 / np.pi) * np.sin(np.pi / (4 * alpha))
                                         + (1 - 2 / np.pi) * np.cos(np.pi / (4 * alpha)))
        else:
            h[i] = (np.sin(np.pi * ti * (1 - alpha)) + 4 * alpha * ti * np.cos(np.pi * ti * (1 + alpha))) \
                   / (np.pi * ti * (1 - (4 * alpha * ti) ** 2))
    return h / np.sqrt(np.sum(h ** 2))


RRC = rrc_taps()


def load(path, start, dur):
    fs, x = wavfile.read(path)
    info = {"file": path, "fs_native": int(fs), "dtype": str(x.dtype)}
    full = {np.dtype("int16"): 32768.0, np.dtype("int32"): 2147483648.0, np.dtype("uint8"): 128.0}
    if x.dtype in full:
        scale = full[x.dtype]
        x = (x.astype(np.float64) - (128.0 if x.dtype == np.uint8 else 0)) / scale
    else:
        x = x.astype(np.float64)
    if x.ndim == 2:
        rms = np.sqrt(np.mean(x ** 2, axis=0))
        info["channel_rms"] = rms.tolist()
        x = x[:, int(np.argmax(rms))]
    info["fullscale_fraction"] = float(np.mean(np.abs(x) > 0.99))
    info["peak_dbfs"] = float(20 * np.log10(np.max(np.abs(x)) + 1e-12))
    if fs != FS:
        g = np.gcd(int(fs), int(FS))
        x = signal.resample_poly(x, int(FS) // g, int(fs) // g)
    a = int(start * FS)
    b = len(x) if dur is None else a + int(dur * FS)
    return x[a:b], info


def active_region(x):
    """Longest stretch where the 4FSK band carries energy well above the quietest part."""
    b, a = signal.butter(4, [500, 2500], btype="band", fs=FS)
    e = signal.filtfilt(b, a, x) ** 2
    blk = int(0.05 * FS)
    n = len(e) // blk
    p = 10 * np.log10(e[:n * blk].reshape(n, blk).mean(1) + 1e-20)
    thr = np.percentile(p, 5) + 0.5 * (np.percentile(p, 95) - np.percentile(p, 5))
    on = p > thr
    best, cur, bs = (0, 0), 0, 0
    for i, v in enumerate(np.append(on, False)):
        if v:
            if cur == 0:
                bs = i
            cur += 1
        else:
            if cur > best[1] - best[0]:
                best = (bs, bs + cur)
            cur = 0
    a0, b0 = (best[0] + 1) * blk, (best[1] - 1) * blk  # trim edges
    noise = x[~np.repeat(on, blk)[:len(x)]] if (~on).any() else None
    return a0, b0, noise


def clock_track(x):
    """Track the symbol clock from the 4800 Hz line in |MF out|^2. Returns symbol count S(n)."""
    z = np.convolve(x, RRC, mode="same")
    c = (z ** 2 - np.mean(z ** 2)) * np.exp(-2j * np.pi * RS * np.arange(len(z)) / FS)
    blk = int(0.1 * FS)
    nb = len(c) // blk
    cb = c[:nb * blk].reshape(nb, blk).mean(1)
    ph = np.unwrap(np.angle(cb))
    tc = (np.arange(nb) + 0.5) * blk
    deg = 2 if nb > 20 else 1
    poly = np.polyfit(tc, ph, deg)
    resid = ph - np.polyval(poly, tc)
    n = np.arange(len(x))
    S = RS * n / FS + np.polyval(poly, n) / (2 * np.pi)
    rate = RS + np.polyval(np.polyder(poly), len(x) / 2) * FS / (2 * np.pi)
    line_snr = float(20 * np.log10(np.abs(cb).mean() / (np.abs(c).std() / np.sqrt(blk) + 1e-20)))
    return S, float(rate), float(np.std(resid) / (2 * np.pi)), line_snr


def resample_to_symbol_clock(x, S):
    """Resample x so there are exactly SPS samples per symbol."""
    m = np.arange(int(np.ceil(S[0] * SPS)) + 1, int(np.floor(S[-1] * SPS)))
    idx = np.interp(m / SPS, S, np.arange(len(x)))
    return CubicSpline(np.arange(len(x)), x)(idx)


def slice4(v):
    return np.where(v > 2, 3, np.where(v > 0, 1, np.where(v > -2, -1, -3)))


def symbols_at(z, p):
    return z[p::SPS]


def best_phase(z):
    return int(np.argmax([np.mean(z[p::SPS] ** 2) for p in range(SPS)]))


def normalise(sy, ref=None):
    """Gain/offset so ideal points land on +-1,+-3. With ref: LS fit; else moment-based."""
    if ref is not None:
        A = np.c_[ref, np.ones_like(ref)]
        g, c = np.linalg.lstsq(A, sy, rcond=None)[0]
        return (sy - c) / g
    sy = sy - np.mean(sy)
    return sy / np.sqrt(np.mean(sy ** 2) / 5.0)  # E[s^2]=5 for equiprobable 4-level


def mer_db(sn, ref):
    return float(10 * np.log10(np.mean(ref ** 2) / np.mean((sn - ref) ** 2)))


def find_period(d, pmin=8, pmax=8192):
    pmax = min(pmax, len(d) // 4)
    score = [np.mean(d[P:] == d[:-P]) for P in range(pmin, pmax)]
    k = int(np.argmax(score))
    # smallest period whose score is close to the best (avoid picking multiples)
    best = score[k]
    for i, s in enumerate(score):
        if s > best - 0.02:
            k = i
            break
    return k + pmin, float(score[k])


def align_ref(sy, pattern):
    """Circular lag and polarity aligning the received symbol stream with the repeated pattern."""
    P = len(pattern)
    n = (len(sy) // P) * P
    avg = sy[:n].reshape(-1, P).mean(0)  # coherent average over periods
    xc = np.real(np.fft.ifft(np.fft.fft(avg) * np.conj(np.fft.fft(pattern))))
    lag = int(np.argmax(np.abs(xc)))
    pol = 1 if xc[lag] > 0 else -1
    peak_ratio = float(np.abs(xc[lag]) / np.sort(np.abs(xc))[-2]) if P > 1 else np.inf
    ref = pol * np.roll(pattern, lag)
    return np.resize(ref, len(sy)), lag, pol, peak_ratio


def ls_fir(x, y, pre, post, ridge=1e-4):
    """FIR h with lags -pre..post minimising |y - h*x|^2 (Toeplitz normal equations)."""
    L = pre + post + 1
    N = len(x)
    nf = 1 << int(np.ceil(np.log2(2 * N)))
    X = np.fft.rfft(x, nf)
    Y = np.fft.rfft(y, nf)
    rxx = np.fft.irfft(np.abs(X) ** 2, nf)[:L]
    rxy_full = np.fft.irfft(Y * np.conj(X), nf)  # rxy[k] = sum y[n] x[n-k]
    k = np.arange(-pre, post + 1)
    rxy = rxy_full[k % nf]
    rxx = rxx.copy()
    rxx[0] *= 1 + ridge
    h = linalg.solve_toeplitz(rxx, rxy)
    return h, k


def apply_fir(h, k, x):
    """y[n] = sum_j h[j] x[n - k[j]]  (k may be negative)."""
    pre = -k[0]
    y = np.convolve(x, h, mode="full")
    return y[pre:pre + len(x)]


def freq_resp(h, k, nfft=1 << 14):
    w = np.fft.rfftfreq(nfft, 1 / FS)
    H = np.fft.rfft(np.roll(np.pad(h, (0, nfft - len(h))), k[0]), nfft)
    return w, H


def group_delay(w, H):
    ph = np.unwrap(np.angle(H))
    return -np.gradient(ph, 2 * np.pi * w)


def param_model(f, fhp, fde, flp, nlp, g):
    s = 1j * f
    hp = s / (s + fhp)                      # 1st-order high-pass
    de = 1 / (1 + s / fde)                  # 1st-order de-emphasis (-6 dB/oct above fde)
    lp = 1 / np.sqrt(1 + (f / flp) ** (2 * nlp))  # Butterworth-like top-end roll-off
    return g * np.abs(hp * de) * lp


def fit_param(f, magdb):
    def res(p):
        fhp, fde, flp, nlp, gdb = p
        return 20 * np.log10(param_model(f, fhp, fde, flp, nlp, 10 ** (gdb / 20)) + 1e-12) - magdb
    p0 = [150, 1000, 3000, 4, magdb.max()]
    lb = [1, 50, 1000, 0.5, -200]
    ub = [2000, 1e6, 20000, 12, 200]
    r = optimize.least_squares(res, p0, bounds=(lb, ub))
    fhp, fde, flp, nlp, gdb = r.x
    return {"hp_corner_hz": fhp, "deemph_corner_hz": fde, "lp_corner_hz": flp, "lp_order": nlp,
            "gain_db": gdb, "rms_err_db": float(np.sqrt(np.mean(r.fun ** 2)))}


def build_ref_wave(ref_sy, p, n):
    imp = np.zeros(n)
    pos = p + SPS * np.arange(len(ref_sy))
    ok = pos < n
    imp[pos[ok]] = ref_sy[ok]
    w = np.convolve(imp, RRC, mode="same")
    return w - np.mean(w)   # AC-coupled path: a non-zero-mean pattern's DC never reaches the audio


def eval_symbols(y, p_hint=None, ref_full=None, sl=slice(None)):
    z = np.convolve(y, RRC, mode="same")
    p = best_phase(z) if p_hint is None else p_hint
    sy = symbols_at(z, p)
    return z, p, sy


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("wav")
    ap.add_argument("--ref")
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--dur", type=float)
    ap.add_argument("--out", default="rx-out")
    ap.add_argument("--no-auto-region", action="store_true")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    R = {}

    x, info = load(a.wav, a.start, a.dur)
    R["input"] = info
    if not a.no_auto_region:
        a0, b0, noise = active_region(x)
    else:
        a0, b0, noise = 0, len(x), None
    R["region_s"] = [a0 / FS + a.start, b0 / FS + a.start]
    x = x[a0:b0]
    x = x - np.mean(x)
    if len(x) < FS:
        sys.exit("signal region shorter than 1 s - check the recording / --start/--dur")

    # ---- spectrum vs theory -------------------------------------------------
    f, Pxx = signal.welch(x, FS, nperseg=8192)
    # theoretical PSD of RRC-shaped equiprobable 4-level symbols = const * |RRC(f)|^2
    _, Hr = signal.freqz(RRC, 1, worN=f, fs=FS)
    Pth = np.abs(Hr) ** 2
    band = (f > 600) & (f < 1800)
    Pth *= np.mean(Pxx[band]) / np.mean(Pth[band])
    fig, ax = plt.subplots(figsize=(8, 4.2))
    ax.plot(f, 10 * np.log10(Pxx + 1e-20), color=C1, label="received audio")
    ax.plot(f, 10 * np.log10(Pth + 1e-20), color=C2, ls="--", label="ideal RRC 4FSK (matched 600-1800 Hz)")
    if noise is not None and len(noise) > 8192:
        fn, Pn = signal.welch(noise - noise.mean(), FS, nperseg=8192)
        ax.plot(fn, 10 * np.log10(Pn + 1e-20), color=C3, lw=1.2, label="no-signal segment")
    ax.set_xlim(0, 8000)
    ax.set_ylim(10 * np.log10(Pxx[f < 8000].max()) - 70, 10 * np.log10(Pxx.max()) + 5)
    ax.set_xlabel("Frequency (Hz)"); ax.set_ylabel("PSD (dB/Hz, rel. full scale)")
    ax.set_title("Received audio spectrum vs ideal", loc="left", color=INK)
    ax.legend(loc="upper right")
    fig.tight_layout(); fig.savefig(os.path.join(a.out, "spectrum.png"), dpi=130); plt.close(fig)

    # ---- symbol clock -------------------------------------------------------
    S, rate, jitter, line_snr = clock_track(x)
    R["symbol_rate_hz"] = rate
    R["clock_offset_ppm"] = (rate / RS - 1) * 1e6
    R["clock_track_resid_sym"] = jitter
    R["clock_line_snr_db"] = line_snr
    y = resample_to_symbol_clock(x, S)
    y = y / np.sqrt(np.mean(y ** 2))

    # ---- raw (no equalisation) ---------------------------------------------
    z, p, sy = eval_symbols(y)
    sy = sy[SPAN:-SPAN]
    sn0 = normalise(sy)
    d0 = slice4(sn0)

    # ---- reference ----------------------------------------------------------
    if a.ref:
        txt = open(a.ref).read().replace(",", " ").split()
        pattern = np.array([int(float(t)) for t in txt])
        if not set(np.unique(pattern)) <= {-3, -1, 1, 3}:
            sys.exit("ref symbols must be in {+3,+1,-1,-3}")
        R["ref_source"] = a.ref
    else:
        P, sc = find_period(d0)
        n = (len(d0) // P) * P
        pattern = slice4(normalise(sy[:n].reshape(-1, P).mean(0)))
        R["ref_source"] = ("BLIND - UNRELIABLE: on a channel with heavy ISI this converges to a wrong, "
                           "self-consistent pattern and the SER is meaningless. Use --ref.")
        R["blind_period"] = P
        R["blind_period_match"] = sc
    ref_sy, lag, pol, pk = align_ref(sn0, pattern)
    if not a.ref:
        # ISI is deterministic per pattern position, so voting alone repeats ISI errors.
        # Refine decision-directed: LS-equalise to the current pattern, re-decide, repeat.
        for it in range(8):
            xr_ = build_ref_wave(np.r_[np.zeros(SPAN), ref_sy], p, len(y))
            ge_, ke_ = ls_fir(y, xr_, 256, 256, ridge=1e-3)
            _, _, s_ = eval_symbols(apply_fir(ge_, ke_, y), p)
            s_ = normalise(s_[SPAN:SPAN + len(ref_sy)])
            n = (len(s_) // len(pattern)) * len(pattern)
            new = slice4(normalise(s_[:n].reshape(-1, len(pattern)).mean(0)))
            ref_new, lag, pol, pk = align_ref(s_, new)
            changed = int(np.sum(ref_new[:len(pattern)] != ref_sy[:len(pattern)]))
            pattern, ref_sy = new, ref_new
            if changed == 0:
                break
        R["blind_refine_iterations"] = it + 1
        np.savetxt(os.path.join(a.out, "blind_pattern.txt"), pattern[None, :], fmt="%+d")
    R.update({"pattern_len": int(len(pattern)), "align_lag": lag, "polarity": pol,
              "align_peak_ratio": pk})

    def ser_report(sy_, name, sl=slice(None)):
        sn = normalise(sy_[sl], ref_sy[sl])
        d = slice4(sn)
        ser = float(np.mean(d != ref_sy[sl]))
        return {"name": name, "ser": ser, "errors": int(np.sum(d != ref_sy[sl])),
                "symbols": int(len(d)), "mer_db": mer_db(sn, ref_sy[sl])}, sn

    half = slice(len(ref_sy) // 2, None)
    raw_all, sn_raw = ser_report(sy, "raw")
    raw_test, _ = ser_report(sy, "raw (2nd half)", half)

    # if blind and raw decisions were poor, refine the pattern decision-directed with an equaliser
    # (done below once the channel is fitted)

    # ---- channel fit: ideal demodulated audio -> received audio -------------
    # symbol k of ref_sy sits at y index p + SPS*(k+SPAN)
    xref = build_ref_wave(np.r_[np.zeros(SPAN), ref_sy], p, len(y))
    n_tr = len(y) // 2
    pre, post = 160, 480   # -3.3 ms .. +10 ms
    h, k = ls_fir(xref[:n_tr], y[:n_tr], pre, post)
    yhat = apply_fir(h, k, xref)
    seg = slice(SPAN * SPS + post, len(y) - SPAN * SPS - pre)
    resid = y[seg] - yhat[seg]
    R["linear_fit_snr_db"] = float(10 * np.log10(np.mean(y[seg] ** 2) / np.mean(resid ** 2)))
    # compression check: y ~ a*yhat + b*yhat^3
    A = np.c_[yhat[seg], yhat[seg] ** 3]
    ab = np.linalg.lstsq(A, y[seg], rcond=None)[0]
    pk_ = np.percentile(np.abs(yhat[seg]), 99.9)
    R["cubic_coeff"] = {"a": float(ab[0]), "b": float(ab[1]),
                        "gain_loss_at_peak_db": float(20 * np.log10((ab[0] + ab[1] * pk_ ** 2) / ab[0]))}
    lin_snr_cubic = 10 * np.log10(np.mean(y[seg] ** 2) / np.mean((y[seg] - A @ ab) ** 2))
    R["cubic_fit_snr_db"] = float(lin_snr_cubic)

    w, H = freq_resp(h, k)
    # RRC PSD is -14 dB at 3.3 kHz and zero at 3.6 kHz; above ~3.3 kHz the fit is noise
    inband = (w >= 100) & (w <= 3300)
    magdb = 20 * np.log10(np.abs(H) + 1e-12)
    ref_lvl = np.median(magdb[(w > 900) & (w < 1100)])
    magdb -= ref_lvl
    gd = group_delay(w, H) * 1e3
    gd_ib = gd[inband]
    R["group_delay_ms"] = {"median": float(np.median(gd_ib)), "ptp_100_3600": float(np.ptp(gd_ib)),
                          "ptp_300_3000": float(np.ptp(gd[(w >= 300) & (w <= 3000)]))}
    fit_f = (w >= 60) & (w <= 3300)
    PF = fit_param(w[fit_f], magdb[fit_f])
    R["param_fit"] = PF
    sl_f = (w >= 500) & (w <= 3000)
    slope = np.polyfit(np.log2(w[sl_f]), magdb[sl_f], 1)[0]
    R["slope_500_3000_db_per_oct"] = float(slope)
    R["mag_db_at"] = {str(fq): float(np.interp(fq, w, magdb))
                      for fq in [100, 200, 300, 500, 1000, 2000, 2400, 3000, 3300]}

    fig, axs = plt.subplots(2, 1, figsize=(8, 7), sharex=True)
    ax = axs[0]
    oob = ~inband
    ax.plot(w[inband], magdb[inband], color=C1, label="fitted FIR (100-3300 Hz)")
    ax.plot(w[oob & (w < 6000)], magdb[oob & (w < 6000)], color=C1, lw=1, alpha=0.35,
            label="outside signal band (poorly determined)")
    pm = 20 * np.log10(param_model(w[1:], PF["hp_corner_hz"], PF["deemph_corner_hz"],
                                   PF["lp_corner_hz"], PF["lp_order"], 10 ** (PF["gain_db"] / 20)))
    ax.plot(w[1:], pm, color=C2, ls="--", label="HP x de-emph x LP model")
    ax.plot([500, 3000], [0, -6 * np.log2(3000 / 500)], color=MUTED, lw=1, ls=":", label="-6 dB/oct guide")
    ax.set_ylim(max(magdb[inband].min() - 10, -60), magdb[inband].max() + 6)
    ax.set_ylabel("Magnitude (dB, 0 dB at 1 kHz)")
    ax.set_title("Fitted RX channel: ideal FM-demodulated audio to recorded audio", loc="left", color=INK)
    ax.legend(loc="lower left", fontsize=8.5)
    ax = axs[1]
    ax.plot(w[inband], gd[inband], color=C1)
    ax.set_xlim(0, 6000)
    lo, hi = np.percentile(gd_ib, [1, 99])
    ax.set_ylim(lo - 0.3 * (hi - lo + 0.1), hi + 0.3 * (hi - lo + 0.1))
    ax.set_xlabel("Frequency (Hz)"); ax.set_ylabel("Group delay (ms)")
    ax.set_title("Group delay (in signal band)", loc="left", color=INK)
    fig.tight_layout(); fig.savefig(os.path.join(a.out, "channel.png"), dpi=130); plt.close(fig)

    fig, ax = plt.subplots(figsize=(5.5, 5))
    ax.hist2d(yhat[seg], y[seg], bins=200, cmap="Blues", cmin=1)
    lim = np.percentile(np.abs(np.r_[yhat[seg], y[seg]]), 99.99)
    ax.plot([-lim, lim], [-lim, lim], color=C2, lw=1, ls="--", label="y = linear prediction")
    ax.set_xlabel("Linear-model prediction"); ax.set_ylabel("Recorded sample")
    ax.set_title("Linearity (limiter/clipping check)", loc="left", color=INK)
    ax.legend(loc="upper left")
    fig.tight_layout(); fig.savefig(os.path.join(a.out, "linearity.png"), dpi=130); plt.close(fig)

    # ---- equalisation (trained on 1st half, scored on 2nd half) -------------
    # (a) regularised inverse of the fitted channel, applied in the frequency domain, in band only
    nfft = 1 << 13
    wf = np.fft.rfftfreq(nfft, 1 / FS)
    Hf = np.fft.rfft(np.roll(np.pad(h, (0, nfft - len(h))), k[0]), nfft)
    eps = 1e-3 * np.max(np.abs(Hf) ** 2)
    G = np.conj(Hf) / (np.abs(Hf) ** 2 + eps)
    G[wf > 4500] = 0
    g_inv = np.roll(np.fft.irfft(G, nfft), nfft // 2)
    g_inv *= signal.windows.hann(nfft)
    y_inv = apply_fir(g_inv, np.arange(-nfft // 2, nfft // 2), y)
    _, _, sy_inv = eval_symbols(y_inv, p)
    # (b) direct least-squares equaliser recorded audio -> ideal audio
    ge, ke = ls_fir(y[:n_tr], xref[:n_tr], 256, 256, ridge=1e-3)
    y_ls = apply_fir(ge, ke, y)
    _, _, sy_ls = eval_symbols(y_ls, p)
    sy_inv, sy_ls = sy_inv[SPAN:SPAN + len(ref_sy)], sy_ls[SPAN:SPAN + len(ref_sy)]
    inv_test, sn_inv = ser_report(sy_inv, "inverse of fitted channel (2nd half)", half)
    ls_test, sn_ls = ser_report(sy_ls, "LS FIR equaliser (2nd half)", half)
    R["ser"] = [raw_all, raw_test, inv_test, ls_test]

    # ---- eye diagrams + histograms -----------------------------------------
    def eye(ax, yy, title, color):
        zz = np.convolve(yy, RRC, mode="same")
        zz = (zz - np.mean(zz))
        s = symbols_at(zz, p)[SPAN:SPAN + len(ref_sy)]
        A_ = np.c_[ref_sy, np.ones_like(ref_sy)]
        gg, cc = np.linalg.lstsq(A_, s, rcond=None)[0]
        zz = (zz - cc) / gg
        st = p + SPS * (SPAN + len(ref_sy) // 2)
        nseg = min(600, (len(zz) - st) // SPS - 3)
        for i in range(nseg):
            b = st + i * SPS - SPS
            ax.plot(np.arange(2 * SPS + 1) / SPS - 1, zz[b:b + 2 * SPS + 1], color=color, lw=0.4, alpha=0.08)
        for lvl in (-3, -1, 1, 3):
            ax.axhline(lvl, color=MUTED, lw=0.8, ls=":")
        ax.set_ylim(-5, 5); ax.set_xlim(-1, 1)
        ax.set_title(title, loc="left", color=INK, fontsize=9.5)
        ax.set_xlabel("Time (symbols)")

    fig, axs = plt.subplots(2, 3, figsize=(12, 7))
    for j, (yy, nm, c, sn) in enumerate([(y, "Raw", C1, sn_raw[len(sn_raw) // 2:]),
                                         (y_inv, "Inverse of fitted channel", C2, sn_inv),
                                         (y_ls, "LS FIR equaliser", C3, sn_ls)]):
        eye(axs[0, j], yy, f"Eye: {nm}", c)
        axs[1, j].hist(sn, bins=300, range=(-5, 5), color=c)
        for lvl in (-2, 0, 2):
            axs[1, j].axvline(lvl, color=MUTED, lw=0.8, ls=":")
        axs[1, j].set_title(f"Symbol histogram: {nm}", loc="left", color=INK, fontsize=9.5)
        axs[1, j].set_xlabel("Normalised symbol value (ideal +-1, +-3)")
    axs[0, 0].set_ylabel("Normalised MF output"); axs[1, 0].set_ylabel("Count")
    fig.tight_layout(); fig.savefig(os.path.join(a.out, "eye.png"), dpi=130); plt.close(fig)

    with open(os.path.join(a.out, "results.json"), "w") as fh:
        json.dump(R, fh, indent=2, default=float)

    # ---- summary ------------------------------------------------------------
    print(f"region {R['region_s'][0]:.2f}-{R['region_s'][1]:.2f} s, peak {info['peak_dbfs']:.1f} dBFS, "
          f"full-scale samples {info['fullscale_fraction'] * 100:.3f}%")
    print(f"symbol rate {rate:.3f} Hz ({R['clock_offset_ppm']:+.1f} ppm), clock line SNR {line_snr:.1f} dB")
    print(f"reference: {R['ref_source']}, period {len(pattern)}, lag {lag}, polarity {pol:+d}, "
          f"peak ratio {pk:.2f}")
    print(f"linear channel model SNR {R['linear_fit_snr_db']:.1f} dB, with cubic term "
          f"{R['cubic_fit_snr_db']:.1f} dB, compression at peaks {R['cubic_coeff']['gain_loss_at_peak_db']:+.2f} dB")
    print("channel |H| (dB rel 1 kHz): " + ", ".join(f"{k_}:{v:+.1f}" for k_, v in R["mag_db_at"].items()))
    print(f"slope 500-3000 Hz {slope:+.2f} dB/oct; model: HP {PF['hp_corner_hz']:.0f} Hz, de-emph corner "
          f"{PF['deemph_corner_hz']:.0f} Hz, LP {PF['lp_corner_hz']:.0f} Hz order {PF['lp_order']:.1f} "
          f"(fit rms {PF['rms_err_db']:.2f} dB)")
    print(f"group delay ptp 300-3000 Hz {R['group_delay_ms']['ptp_300_3000']:.3f} ms, "
          f"100-3600 Hz {R['group_delay_ms']['ptp_100_3600']:.3f} ms")
    for s in R["ser"]:
        print(f"  {s['name']:<40} SER {s['ser']:.2e} ({s['errors']}/{s['symbols']}), MER {s['mer_db']:.1f} dB")


if __name__ == "__main__":
    main()
