#!/usr/bin/env python3
"""Record -> decode -> play cycle for M17 reception on the RFinder B1-Plus (PC-side decoding).

  m17_cycle.py open   NAME          RF module must be ON. BT mode on + pre-check, 3 EQ writes, post-check.
  m17_cycle.py rec    NAME [SECS]   capture SECS (default 40) inside the open session, pull to the PC.
  m17_cycle.py close  NAME          RF module must be OFF (EQ cleared). Ends the BT session, mixer check.
  m17_cycle.py decode NAME          segment, m17_ic (warm start) -> m17_turbo -> m17_render, push to phone.
  m17_cycle.py play   NAME          RF module must be OFF. Plays NAME_all.wav on the phone speaker.

Every phone / module command is appended to NOTES-rx-test.md. Never sends PTT or TX commands.
Equaliser state carried across cycles: device/live/state_w.npz (updated after a good decode).
"""
import os, re, subprocess, sys, time
import numpy as np
from scipy import signal
from scipy.io import wavfile

HERE = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.join(HERE, "device", "live")
NOTES = os.path.join(HERE, "..", "NOTES-rx-test.md")
STATE = os.path.join(LIVE, "state_w.npz")
BASELINE_MIX = os.path.join(HERE, "device", "m17e", "tinymix-after-m17e.txt")
PH = "/data/local/tmp"
EQ = ["AT+SDKWRITE=0,112,0,200,1182FF3D12449E837F38F3",
      "AT+SDKWRITE=0,112,0,200,129420379143529420343F",
      "AT+SDKWRITE=0,112,0,200,13B1083D484AB9B108328F"]
os.makedirs(LIVE, exist_ok=True)


def log(line):
    with open(NOTES, "a") as f:
        f.write(f"- [cycle {time.strftime('%H:%M:%S')}] {line}\n")


def adb(cmd, timeout=120):
    r = subprocess.run(["adb", "shell", cmd], capture_output=True, text=True, timeout=timeout)
    return (r.stdout + r.stderr).strip()


def hw_pd():
    out = adb("cat /sys/bus/platform/drivers/intercom_driver/intercom/hw_pd")
    m = re.search(r"(\d)\s*$", out)
    return int(m.group(1)) if m else -1


def pull(remote, local):
    subprocess.run(["adb", "pull", remote, local], capture_output=True, check=True)


def levels(path):
    fs, x = wavfile.read(path)
    x = (x[:, 0] if x.ndim == 2 else x).astype(float) / 32768
    x = x[int(0.3 * fs):]
    fr, P = signal.welch(x, fs, nperseg=8192)
    band = lambda lo, hi: 10 * np.log10(np.mean(P[(fr >= lo) & (fr < hi)]) + 1e-30)
    return 20 * np.log10(x.std() + 1e-12), band(250, 3000)


def check(name):
    pull(f"{PH}/rx/{name}.wav", os.path.join(LIVE, name + ".wav"))
    rms, inband = levels(os.path.join(LIVE, name + ".wav"))
    return rms, inband


def cmd_open(name):
    if hw_pd() != 1:
        sys.exit("RF module is OFF (hw_pd 0): switch it ON first")
    out = adb(f"cd {PH} && sh sess_begin.sh {name}_pre 5", 60)
    rms, ib = check(name + "_pre")
    log(f"`sess_begin.sh {name}_pre 5` (BT mode 1, ADC1/IN_ADC1): {rms:.1f} dBFS, 250-3k {ib:.1f}")
    print(f"pre-check: {rms:.1f} dBFS, 250-3k {ib:.1f} dB")
    if ib < -90:
        log("pre-check too low (module audio muted?): EQ not written, session left open")
        sys.exit("pre-check too low: module audio looks muted. Session left open (BT mode on).")
    for c in EQ:
        r = adb(f"cd {PH} && sh atcmd.sh '{c}' 2", 30)
        ok = re.search(r"O\s+K", r) is not None
        log(f"[module] `{c}` -> {'OK' if ok else 'NO OK: ' + r[-60:]}")
        if not ok:
            sys.exit(f"EQ write failed: {r}")
    adb(f"cd {PH} && sh sess_cap.sh {name}_post 5", 60)
    rms2, ib2 = check(name + "_post")
    log(f"`sess_cap.sh {name}_post 5`: {rms2:.1f} dBFS, 250-3k {ib2:.1f}")
    print(f"EQ written (3x OK). post-check: {rms2:.1f} dBFS, 250-3k {ib2:.1f} dB")
    if ib2 < -90:
        sys.exit("post-check too low: module audio looks muted after the EQ writes.")
    print("READY")


def cmd_rec(name, secs):
    out = adb(f"cd {PH} && sh sess_cap.sh {name} {secs}", secs + 60)
    pull(f"{PH}/rx/{name}.wav", os.path.join(LIVE, name + ".wav"))
    rms, ib = levels(os.path.join(LIVE, name + ".wav"))
    log(f"`sess_cap.sh {name} {secs}` ({out.strip()}): {rms:.1f} dBFS, 250-3k {ib:.1f}")
    print(f"recorded {secs} s: {rms:.1f} dBFS, 250-3k {ib:.1f} dB")


def cmd_close(name):
    if hw_pd() != 0:
        sys.exit("RF module is still ON: switch it OFF first (clears the EQ, keeps the session end quiet)")
    out = adb(f"cd {PH} && sh sess_end.sh {name}", 60)
    mix = os.path.join(LIVE, f"tinymix-after-{name}.txt")
    pull(f"{PH}/rx/tinymix-after-{name}.txt", mix)
    norm = lambda p: [l.split("\t", 3)[-1] for l in open(p) if not re.search("DcTrim|ImpeDance|AUD_CLK_BUF", l)]
    same = norm(mix) == norm(BASELINE_MIX)
    log(f"RF module OFF (hw_pd 0 verified). `sess_end.sh {name}` ({out}): mixer "
        f"{'== baseline' if same else 'DIFFERS from baseline'}")
    print(f"session closed, mixer {'== baseline' if same else 'DIFFERS from baseline'}")


def run(args, **kw):
    return subprocess.run(args, capture_output=True, text=True, cwd=HERE, **kw).stdout


def decode_seg(seg):
    pre = seg[:-4] + "_ic"
    def ic(pol):
        args = ["python3", "m17_ic.py", seg, "--rounds", "1", "--ridge", "10", "--pol", str(pol), "--out", pre]
        if os.path.exists(STATE):
            args += ["--init", STATE, "--prior", "300"]
        out = run(args)
        m = re.search(r"IC round1\s+FN-consistent\s+(\d+)/(\d+)", out)
        return (int(m.group(1)) / int(m.group(2)) if m else 0.0), pol, out

    best = ic(-1)                       # -1 = polarity seen on this unit so far
    if best[0] <= 0.5:                  # try the other sign, keep the better one
        alt = ic(+1)
        if alt[0] > best[0]:
            best = alt
        else:
            ic(-1)                      # rerun so the files on disk match the better polarity
    if best[0] == 0.0:
        return None
    t = run(["python3", "m17_turbo.py", "real", pre, "--iters", "12"])
    last = [l for l in t.splitlines() if "FN-consistent" in l][-1]
    r = run(["python3", "m17_render.py", pre + "_turbo.npz", seg[:-4] + "_clean.wav"]).strip().splitlines()[-1]
    ffe = re.search(r"FFE final.*?median\s+([\d.]+) %", best[2]).group(1)
    return best, last, r, ffe, pre


def cmd_decode(name):
    t0 = time.time()
    rec = os.path.join(LIVE, name + ".wav")
    seg_out = run(["python3", "m17_segment.py", rec, os.path.join(LIVE, name)])
    print(seg_out.strip() or "no transmissions found")
    segs = [l.split() for l in seg_out.splitlines() if re.match(r"\d+ ", l)]
    clean = []
    for n, s, e in segs:
        seg = os.path.join(LIVE, f"{name}_seg{n}.wav")
        res = decode_seg(seg)
        if res is None:
            print(f"seg{n} {s}-{e} s: decode failed"); log(f"decode {name} seg{n}: failed"); continue
        (frac, pol, _), last, r, ffe, pre = res
        msg = f"seg{n} {s}-{e} s: pol {pol:+d}, FFE {ffe} %, turbo {last.split('|')[-1].strip()}, {r}"
        print(msg); log(f"decode {name} {msg}")
        if frac > 0.8:
            w = np.load(pre + "_w.npz"); np.savez(STATE, **w)
        clean.append(seg[:-4] + "_clean.wav")
    if not clean:
        return
    parts = []
    for c in clean:
        fs, y = wavfile.read(c); parts += [y, np.zeros(int(0.7 * fs), y.dtype)]
    out = os.path.join(LIVE, name + "_all.wav")
    wavfile.write(out, fs, np.concatenate(parts))
    p = subprocess.run(["adb", "push", out, "/sdcard/Download/"], capture_output=True, text=True)
    if p.returncode:
        print(f"decoded in {time.time() - t0:.0f} s, PUSH FAILED ({p.stderr.strip()}): adb down? rerun decode later")
        return
    log(f"pushed {name}_all.wav to /sdcard/Download ({time.time() - t0:.0f} s decode)")
    print(f"decoded in {time.time() - t0:.0f} s -> /sdcard/Download/{name}_all.wav")


def cmd_play(name):
    if hw_pd() != 0:
        sys.exit("RF module is ON: phone audio would be buried under the module audio. Switch it OFF first.")
    vol = adb("media volume --stream 3 --get 2>/dev/null | tail -1")
    adb(f"am start -a android.intent.action.VIEW -d file:///sdcard/Download/{name}_all.wav -t audio/wav")
    log(f"played /sdcard/Download/{name}_all.wav via the media player ({vol})")
    print(f"playing ({vol})")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    op, name = sys.argv[1], sys.argv[2]
    {"open": lambda: cmd_open(name), "rec": lambda: cmd_rec(name, int(sys.argv[3]) if len(sys.argv) > 3 else 40),
     "close": lambda: cmd_close(name), "decode": lambda: cmd_decode(name), "play": lambda: cmd_play(name)}[op]()
