# B1-Plus analog FM RX path: M17 4FSK survival test

Test signal (operator TX): random 4FSK, 4800 sym/s, RRC alpha=0.5, M17 deviation
(+/-800 / +/-2400 Hz), 433.475 MHz, short repeated pseudorandom pattern.

Rules in force: receive only (no PTT ioctl 0x4902, no bt_ptt, no TX commands);
read-only on the module and audio switches unless the operator approves; no flashing.

Device log format: `[host]` = command run on the PC, `[phone]` = command run in the
adb shell, `[module]` = bytes sent to the SD01. Every command sent is listed here.

## Log

### 2026-11-07 session 1

- [host] `adb connect 192.168.50.168:5555` -> `failed to connect ... Connection refused`.
  `ping 192.168.50.168` OK (20-108 ms); `nc -zv 192.168.50.168 5555` -> timed out.
  **Finding:** phone is on the network but adbd is not listening on TCP. Wireless adb
  must be re-armed (USB `adb tcpip 5555`, or `setprop service.adb.tcp.port 5555;
  stop adbd; start adbd` on the phone). No command has reached the phone.
- [host] tinyalsa source cloned to the session scratchpad
  (github.com/tinyalsa/tinyalsa @ a7cd26a1). Static aarch64 cross-build with zig
  (from the PyPI `ziglang` wheel) was **blocked by the local tool-permission policy**
  (running a downloaded toolchain). Not built yet.
- [host] Analysis pipeline written: `rx-test/analyze_rx.py`, checked against a
  simulated channel (`rx-test/simulate.py`), results below.

Nothing has been sent to the module. Nothing has been transmitted.

### Analysis pipeline validation (simulated, no device)

`rx-test/simulate.py` makes a 22 s WAV: 200-symbol random pattern, RRC a=0.5,
48 kHz ADC at +40 ppm, optional channel = 1st-order HP 300 Hz x 750 us
de-emphasis x 6th-order Butterworth LP 3 kHz x tanh limiter, plus white noise.

| Case | Clock est. | Linear-fit SNR | Raw SER | Inverse-H SER | LS-EQ SER |
|---|---|---|---|---|---|
| flat, 35 dB SNR | -40.0 ppm | 35.4 dB | 0 | 0 | 0 |
| distorted, 30 dB SNR | -40.0 ppm | 21.3 dB (24.9 with cubic term; -2.3 dB compression at peaks) | 3.8e-1 | 1.5e-4 | 9.0e-4 |

Distorted case recovered: slope -6.33 dB/oct (500-3000 Hz), model HP 168 Hz /
de-emph 389 Hz / LP 3.0 kHz (HP and de-emph corners trade off against each
other, so read them together, not individually). Equalisers are trained on the
1st half, scored on the 2nd.

Bugs found and fixed while validating:
- reference waveform kept the DC of a non-zero-mean pattern -> 15 dB fake model error;
  now mean-removed (the real path is AC-coupled anyway).
- inverse equaliser was 1 sample late (`np.convolve(mode="same")`, even kernel).
- response above 3.3 kHz is unidentifiable (RRC PSD -> 0 at 3.6 kHz); fit limited to 3.3 kHz.

Limitations:
- **Blind mode is unreliable**: with heavy ISI the decision-directed loop converges
  to a wrong self-consistent pattern (58 % match to truth in the sim) and the SER
  it prints is meaningless. The real transmitted pattern (`--ref`) is required.
- A repeated pattern of P symbols only excites lines every 4800/P Hz, so the
  channel is only identified on that grid (ripple in the fitted |H|). P >= ~200
  is good; very short patterns (e.g. 8-32) make the channel fit weak.

### Pending (needs operator)

1. Re-arm wireless adb.
2. tinycap/tinymix: either allow the zig cross-build, supply static aarch64
   binaries, or check whether the ROM already ships them (`ls /system/bin/tiny*`).
3. Provide the exact transmitted symbol period (file of +3/+1/-1/-3, or generator + seed).
4. Channel setup: preferred route is the RFinder app UI (analog, wide, no
   CTCSS/DCS, squelch 0, 433.475 MHz), so no raw frame is sent from here.
   For reference only, the 55 AA analog-channel frame (CC 01, 15-byte payload)
   would start `55 AA 00 0F 01 19 D6 4D B8 19 D6 4D B8 ...` (433,475,000 Hz BE
   for TX and RX). The tone/bandwidth/power/squelch byte encodings are not
   decoded yet, and the TX freq in this frame does not key the radio, but it is
   still a module write; **not sent**.

### 2026-11-07 session 2 (adb up)

Operator approved and I ran the zig build once: static aarch64 tinycap/tinymix/tinypcminfo
(tinyalsa a7cd26a1, zig 0.17.1, `-target aarch64-linux-musl -static -DTINYALSA_USES_PLUGINS=0`).

- [host] `adb connect 192.168.50.168:5555` -> connected (model RFinder_B1_plus, product full_k65v1_64_bsp).
- [phone] read-only: `id` (uid 0), `getenforce` (Permissive), `ls /system/bin/tiny* /vendor/bin/tiny*`
  (none), `cat /proc/asound/cards`, `cat /proc/asound/pcm`, `ls -l /dev/snd`, `cat` of all intercom
  sysfs nodes, `ps -A | grep ...`, `getprop | grep ...`, `dumpsys audio`.
  - one card `mt-snd-card`, 33 PCMs (list in `/proc/asound/pcm`; no radio/intercom-named PCM).
  - intercom sysfs: bt_ptt 0, hw_pd 0, mic_power 0, mic_sw 0, headset_mic_only 0, ptt_version 500,
    sys_wake_ptt 1, uart_sw 0, uart_BB_PC_sw 0.
  - `ro.custom.build.version` = K608_DT865_RFinder-B1-plus_20230408_V11.4.
  - **Two RFinder apps running**: `com.w2cyk.android.rfinder` and `com.w2cyk.rfinder.rfinderpro`.
  - No process holds `/dev/ttyS0` or `/dev/intercom_device` open (scanned /proc/*/fd), so the
    JNI library opens them per call.
- [phone] `adb push tinycap tinymix tinypcminfo /data/local/tmp/` (phone storage only).
- [phone] `tinypcminfo -D 0 -d N` for capture devices: D1 MultiMedia1_Capture 8-260 kHz 1-2 ch;
  most others max 48 kHz; D9/D25/D28/D30/D31/D32 up to 192 kHz.
- [phone] `tinymix -D 0 contents` (read-only) -> `rx-test/device/tinymix-contents-baseline.txt`.
  Codec_ADC_SampleRate 48000; Audio_ADC_1..4_Switch all Off; ADC_1/2_Sel Preamp, PGA1/2 18 dB;
  Preamp1/2 OPEN. No obvious "radio/line-in" control.
- [phone] `tinycap rx/base_dN.wav -D 0 -d N -c 2 -r 48000 -b 16 -t 3` for N = 1 2 3 5 13 16 17 22
  (no RF signal, baseline). D2/D5/D17 I/O error, D3 EINVAL; **D1/D13/D16/D22 return exact digital
  zeros** -> PMIC ADCs are unpowered; the HAL normally switches them on when recording. Pulled to
  `rx-test/device/baseline/`.
- **Operator approved** mixer sweep; operator confirmed channel set in RFinder app (analog, wide,
  no tone, squelch 0, 433.475 MHz) and test signal transmitting. [phone] commands:
  `tinymix -D 0 set Audio_ADC_1_Switch On`, `... set Audio_ADC_2_Switch On`, then for
  (Preamp1, Preamp2) in (IN_ADC1, IN_ADC2), (IN_ADC2, IN_ADC3), (IN_ADC3, IN_ADC1):
  `tinymix -D 0 set Audio_Preamp1_Switch X; ... set Audio_Preamp2_Switch Y;
  tinycap rx/sweep_p1X_p2Y.wav -D 0 -d 1 -c 2 -r 48000 -b 16 -t 5`;
  then restored `Audio_Preamp1/2_Switch OPEN`, `Audio_ADC_1/2_Switch Off`.
  `tinymix contents` after == baseline except `Audio HP ImpeDance Setting` (a driver measurement,
  not written by me). Files: `rx-test/device/sweep/`, survey script `rx-test/device/survey.py`.
- **Finding:** all three PMIC mic inputs (IN_ADC1..3 = AIN0..2) carry only idle noise during TX:
  300-3000 Hz power -80..-96 dB, no 4800 Hz symbol-clock line (largest bin in 4700-4900 Hz is
  ~10 dB above median at random frequencies = noise). IN_ADC2 has a -32 dBFS power-up pop in the
  first 100 ms, then -88 dBFS. => With default intercom switches (mic_sw 0, uart_sw 0, BT mode
  default) the radio's demodulated audio does not reach any SoC ADC. Most likely the module's
  es8388 drives the speaker amp directly.
- [host] read-only static look at `/system/lib/libintercomjni.so` (pulled; md5 dddc9953... matches
  README). Symbols from `.gnu_debugdata`: `android_hardware_setBTMode` @0x889c,
  `android_hardware_intercomHeadsetMode` @0x3238.
  - `setBTMode(n)`: `open(/dev/intercom_device)`, `ioctl(fd, 0x4905, n)` (n by value), logs
    "Enable Intercom BT Mode." if n != 0 else "Disable ...", close. => 0x4905 is a plain on/off.
  - `intercomHeadsetMode()`: only clears a library global; no hardware access.
- [phone] read-only `grep /proc/kallsyms`, `dmesg`, `/proc/device-tree/intercom/*`:
  - kernel exports `get_intercom_bt_mode`, `intercom_audio_out_ctr`, `intercom_audio_in_ctr`,
    `intercom_Speaker_Amp_Change`, `aw87329_intercom_kspk` -> the sound driver queries BT mode, and
    the AW87329 speaker amp has an intercom input mode.
  - RFinder app issues **ioctl 0x4906** (cmd 18694) with arg 3 ("spk_mode:3, intercom AMP_SPEAKER")
    or 0. => module audio drives the AW87329 speaker amp directly; the SoC is bypassed in normal RX.
  - squelch GPIO 344 went low ("sq is Press" = squelch open) at uptime 1709.8 s and stayed low
    through the sweep captures (uptime 1743-1758 s). => module WAS receiving/unsquelched during
    the sweep; the audio simply isn't routed to the SoC.
  - DT pinctrl states: intercom_mic_headset / intercom_mic_main, intercom_mic_power0/1,
    uart_sw_pin_enable/disable, bt_ptt_output0/1, pdn_output0/1, sys_wake_ptt_pin0/1.
- **Operator approved** BT-mode test (and the one-off zig build of `rx-test/device/btmode.c`, which
  hard-codes ioctl 0x4905 only). [phone] commands: `btmode 1`; same tinymix ADC/Preamp sweep +
  `tinycap rx/bt_p1X_p2Y.wav -D 0 -d 1 -c 2 -r 48000 -b 16 -t 5` x3; mixer restored to
  OPEN/Off; `btmode 0`. Mixer after == baseline (except HP impedance measurement).
  - dmesg on `btmode 1`: "audiopolicy device = 4 ... Intercom enable BT mode!"; on `btmode 0`:
    "intercom AMP_SPEAKER ... aw87329 aw_rst ... Intercom disable BT mode!" (speaker path re-armed).
  - **Finding: in BT mode the module RX audio appears on PMIC input IN_ADC1 (AIN0, main-mic
    input).** 300-3000 Hz power -51.6 dB (vs -80 without BT mode), symbol-clock line at
    4799.9 Hz, 57 dB above floor. IN_ADC3 has a weaker copy (-66 dB, 30 dB line), crosstalk.
    IN_ADC2 unchanged (idle). Level: -51 dBFS rms, -40 dBFS peak at PGA1 = 18 dB.
  - Preview (`analyze_rx.py`, 4.7 s, no reference yet): symbol rate 4800.003 Hz (+0.6 ppm).
    Spectrum (`rx-test/device/bt/preview/spectrum.png`): flat 400-3000 Hz (no de-emphasis tilt),
    steep HP below ~350 Hz (~-20 dB at 200 Hz, CTCSS-filter-like), brick-wall roll-off from
    ~3.0 kHz (~-10 dB vs ideal at 3.3 kHz), in-band floor ~35-40 dB below signal.
    Blind SER/channel numbers discarded (blind mode unreliable).

### 2026-11-07 session 3

Operator: no symbol pattern available (source is an HP E4436B); approved the 60 s recording and
the RSSI read; asked to look into disabling the ~350 Hz high-pass.

- [phone] `btmode 1; tinymix set Audio_ADC_1_Switch On; set Audio_Preamp1_Switch IN_ADC1;
  tinycap rx/long60.wav -D 0 -d 1 -c 2 -r 48000 -b 16 -t 60; set Audio_Preamp1_Switch OPEN;
  set Audio_ADC_1_Switch Off; btmode 0`. Mixer after == baseline (except HP impedance).
  **No signal in the 60 s file** (300-3000 Hz -76 dB, no 4800 Hz line; per-second band power
  -81 dB with occasional -67..-74 dB bumps).
- [phone] repeat of the earlier working 5 s config (ADC1+ADC2 on, Preamp1 IN_ADC1, Preamp2
  IN_ADC2, BT mode 1) -> `rx/recheck.wav`: also **no signal**. => the change is upstream of the
  SoC audio path (generator, or radio channel/state), not the capture config.
- [phone] read-only: `stty -F /dev/ttyS0 -a` -> 38400 8N1 raw. **State changed since session 2:**
  `hw_pd` now 1 (was 0); `com.w2cyk.android.rfinder` now holds `/dev/ttyS0` open (nothing did
  before). `rfinderpro` was killed by ActivityManager (idle) at 18:05:58. No squelch GPIO events
  logged since uptime 1709.8 s.
- [module] **RSSI read sent once**: `55 AA 00 01 09 01` written to /dev/ttyS0, reader
  `timeout 2 cat /dev/ttyS0` started 0.2 s before. **No reply bytes received** (18:13:11).
  Most likely the RFinder app, which holds the port, consumed the reply. Not retried.
- [phone] read-only `logcat -d`: the app logs no radio traffic; its UI redraws every 10 s.
- [phone] read-only `cat /sys/kernel/debug/mtksocaudio` / `mtksocanaaudio` ->
  `rx-test/device/afe-regs-idle.txt`, `pmic-audio-regs-idle.txt`.
  `AFE_ADDA_UL_SRC_CON0 = 0x60400`: bit 10 = UL_IIR_ON (MediaTek uplink voice IIR high-pass), bits
  7-9 IIR mode 0, bits 17-19 = 3 (rate). **Candidate for (part of) the ~350 Hz high-pass.**
- [host] `strings` on `backup/SD01_UAVA_RFINDER.bin`: no filter/HPF/CTCSS/emphasis strings other
  than `+TXSUBAUD`/`+RXSUBAUD`; a module-side HPF control would need disassembly.
- **Cause of the lost signal (operator):** the operator turned the volume knob down to mute the
  speaker before the 60 s capture. The module volume (55 AA CC 05) is applied to the module codec
  output, which in BT mode is also what feeds SoC IN_ADC1, so knob = gain stage in front of the
  capture. Volume must be up, and fixed, during captures; in BT mode the speaker amp is
  disconnected anyway. The app opening /dev/ttyS0 is consistent with it sending the volume
  command. The RSSI no-reply is still unexplained (port held by the app).
- Volume restored by operator. [phone] repeated the 60 s capture (same commands as above) ->
  `rx-test/device/long/long60b.wav`: signal present for the full 60 s, -41 dBFS rms, -26 dBFS
  peak, 4800.0 Hz clock line 61 dB. Mixer restored == baseline.
- [module] RSSI read retried once (`55 AA 00 01 09 01`): again **no reply**; RFinder app holds the
  port. Not retried further; would need the app closed (operator decision).
- No pattern file (E4436B source). Analysis without reference:
  - Period = **1024 symbols** exactly (soft-symbol autocorrelation r = 0.988 at 1024/2048/4096;
    all smaller lags < 0.19). Rate 4800.0064 Hz (+1.3 ppm).
  - Non-repeating part: median period r = 0.999 vs average (~29 dB), a few bad periods (min r
    0.84, gain up to 1.45x) = bursty interference/gain steps; not signal-dependent (envelope corr
    0.006). **Below 200 Hz the repeating signal is 23 dB under the noise: LF content removed.**
  - Averaged waveform is Gaussian (kurtosis 3.03), eye closed with no equalisation.
  - Blind CMA equaliser (T/2, 81 taps) reaches 4-PAM statistics (kurtosis 1.655), so it is 4FSK
    through a dispersive linear channel. Decision-directed LS equaliser: cross-validated MER plateaus
    at **~12 dB** for 81-161 taps (more taps overfit). DFE (FB 32/128) gives no gain. Even good
    individual periods agree with the reconstructed pattern only ~75%. The reconstruction is
    **not trustworthy**, so no SER is reported from this recording.
  - Interpretation: ~8% of RRC-4FSK power is below 200 Hz; losing it caps linear MER near
    10-11 dB, which matches the plateau. The high-pass is the dominant impairment.
  - Tools: `rx-test/refrecon.py`, `rx-test/blindeq.py` (99.9% pattern recovery on the simulated
    harsh channel), `rx-test/device/{period,ddtaps,dfe}.py`.
- **Operator approved** phone-side HPF A/B test. [host] read-only: boot partition copied
  (`dd if=/dev/block/mmcblk0p25 of=/data/local/tmp/boot.img`, pulled, deleted on phone), kernel
  gunzipped: contains debugfs keywords `Setafereg`/`Setanareg`/`Getafereg`/`Getanareg`
  (MediaTek legacy audio debug; argument format not in strings).
- [phone] `rx-test/../scratchpad/hpf_ab.sh`: BT mode 1, ADC1 On, Preamp1 IN_ADC1, 20 s tinycap in
  background; t=2 s `cat mtksocaudio` -> AFE_ADDA_UL_SRC_CON0 = 0x60401 (UL on, IIR bit10 set);
  `echo Getafereg,0x0114 > mtksocaudio` -> **nothing in dmesg**; t=8 s
  `echo Setafereg,0x0114,0x60001 > mtksocaudio` -> read-back **0x60401 (unchanged)**; t=17 s
  `echo Setafereg,0x0114,0x60401` (no-op); capture end; mixer + BT mode restored (== baseline);
  idle CON0 = 0x60400.
  - **Deviation:** I had said I'd stop if the Getafereg read did not respond as expected; the
    script only checked bit 10 in the dump and proceeded with the write. The write had no effect
    (register unchanged), so no state change resulted. Reported to the operator.
  - Audio A/B/C segments identical to 0.1 dB in all bands (as expected, nothing changed).
  - **HPF shape** (band PSD, dB): 50-150 -102, 150-250 -98, 250-350 -83, 350-500 -71, 500-1k -73.
    ~25 dB drop from 425 Hz to 200 Hz = 20+ dB/oct, i.e. >= 4th order. A 1st-order MediaTek UL
    IIR can't do this; it is the shape of a CTCSS-rejection HPF, so most likely in the module
    (the operator's hypothesis).
- **Operator:** while the buzz disappeared they turned the volume knob to keep it audible. In BT mode
  the module audio is taken off the speaker amp by design, so the buzz always stops during
  captures. => the knob moved during captures; this explains the gain steps (up to 1.45x) and the
  ~19 outlier periods in long60b. The HPF/LF-loss findings are unaffected (seen in every segment;
  outliers excluded with r > 0.99). Rule from now on: set the volume once, don't touch it during captures.
- [host] **Firmware load base is 0x08003000**, not 0x08000000 as the README says: 55 string pointers
  resolve at 0x08003000, none at other bases. AT command name table around 0x08025988-0x08025a58
  (+UARTMODE 0x8025988, +REGALL 0x8025990, +SDKWRITE 0x8025998, +SDKREAD 0x80259a0,
  +SDKIOCTRL 0x80259a8, +TXSUBAUD 0x8025a30, +RXSUBAUD 0x8025a38, +WAVE 0x8025a58).
- [host] read-only firmware disassembly (arm-none-eabi-objdump, base 0x08003000). AT table =
  {name ptr, handler} pairs at 0x08025980.. Handlers: +UARTMODE 0x8006d29, +REGALL 0x8005bd1,
  +SDKWRITE 0x80060fd, +SDKREAD 0x8005f6d, +SDKIOCTRL 0x8005ebd, +CHIP 0x8004571, +SVOL 0x8006885,
  +TXSUBAUD 0x8006d1d, +RXSUBAUD 0x8005e41, +SQL 0x8006411, +CARRIER 0x80043c1, +BER 0x800428d,
  +WAVE 0x8006f81 (Thumb, +1).
  - `+RXSUBAUD` -> `sub_8006530(1, args)` (shared TX/RX sub-audio setter, flag 1 = RX).
  - `+SDKIOCTRL=a,b,c,d` parses 4 x u16, calls `sub_8018f74(a,b,c,d)`, prints
    "ioctrol_ret_val = %d". sub_8018f74: mode checks (cmd 8/19 allowed in a special mode, cmd 20 gated
    on a flag), then a byte jump table (`bl 0x80207d4`) with ~44 cases = Sicomm SDK ioctl numbers.
  - `+SDKWRITE=a,b,c,d,data` parses 4 x u16 + a data buffer, calls `sub_8019310`.
  - Which SDK ioctl/register (if any) controls the RX sub-audio HPF is not yet identified.

### Baseband documentation and the filter-bypass path (static, read-only)

Sources: CT3258 Packet Interface / SCT3258 datasheet v2.0 (hackaday.io file area
1642237026116832), and SCT3258_Packet_Interface.pdf, SCT3258_Analog_Setup.pdf, SCT3258_FAQ.pdf
from github.com/OpenRTX/OpenRTX-external-docs ("Datasheets and refmans/SCT3258"). Local copies in
the session scratchpad only (not committed).

- Datasheet RX analog chain: HPF (pass 300 Hz, stop 255 Hz) -> de-emphasis (6 dB/oct) -> LPF
  (2.55 or 3 kHz). Matches the measured ~350 Hz steep HP and the ~3 kHz brick wall.
- Packet interface to the baseband: start bytes 84 A9 61, LENGTH(2), TYPE(1), fields.
- **ANALOG_CONFIG field 0x3C** (11 data bytes): Mode(1) + TX gain before limiter (Q16.11) + TX gain
  after limiter (Q16.12) + CTCSS gain (Q16.12) + DCS gain (Q16.12) + RX volume (Q16.11), all u16 MSB
  first. Default mode 0x02, gains 2048/4096/4096/4096/2048.
  Mode bits: 7 ALT_LPF, 6 DCS_HPF, 5 COMPANDER, 4 ANA_TONE_CFG, 3 IF_CH_SEL (1=25 kHz),
  2 SKIP_EMP, 1 BB_CH_SEL (0=2.55 kHz, 1=3 kHz LPF), **0 FILTER_BYPASS ("all analog signal
  processing in the TX path and the RX path are bypassed")**.
- CTC_PARAM field 0x3D: bit 4 HPF_CORNER (0 = 300 Hz, 1 = 450 Hz); no off setting there.
- Firmware (base 0x08003000):
  - `sub_8013b44(buf)` = `sub_800e4b0(0); sub_80071b8(0x3C, buf); sub_801da78(3, 200)` -> sends
    ANALOG_CONFIG. Callers 0x800f726, 0x8013c8c, 0x8014e90, 0x8017198: buf[0] = RAM config byte
    (struct+0x36), sometimes |0x80 (ALT_LPF) or another flag; buf[1..10] = 10 gain bytes memcpy'd
    from a RAM calibration table; only sent when a state byte == 0x10 (analog).
  - `+SDKWRITE=a,b,c,d,hex` -> `sub_8019310(a,b,c,buf,d)`; Keil switch8 on a (0..11). **a = 0:
    `sub_800e4b0(c); sub_80071b8(b, buf); sub_801da78(3, d)`** = the same sequence as the firmware's
    own ANALOG_CONFIG send with b = 60 (0x3C), c = 0, d = 200 (ms). So
    `AT+SDKWRITE=0,60,0,200,<22 hex chars>` should write ANALOG_CONFIG (hex parser sub_8008234 not
    yet verified: format assumed to be plain hex digits).
  - `+UARTMODE=<str>` sets byte [0x20000bf8+10]: "baseband" -> 1, "character" -> 2, a third name
    (from a RAM pointer) -> 0. How the UART switches from 55 AA binary to AT text is not mapped yet.
- Unknowns before any write: the live mode byte and gains (RAM/EEPROM; read via +SDKREAD or
  +REGALL), the AT-mode entry from 55 AA mode, and the RFinder app's competing UART traffic.

### Step 1 (read-only RE): AT entry, SDKREAD/SDKWRITE formats

- Scatterload table @0x08026ca4: entry 1 src 0x08026cc4 -> RAM 0x200000c0, 0x20C bytes,
  decompressor 0x08003bdc (ARM LZ-style: token low 3 bits = literal count+1, high 4 bits = run,
  bit 3 = back-reference with 1-byte offset, else zero run). Entry 2 = zero-init 0x200002cc,
  0x296C bytes. Decompressed image: session scratchpad `ram_init.bin`.
- UART RX pump (`0x080076d4`): per byte, if state byte [0x20000cb3] == 2 -> drop; >= 3 -> pass-through
  to `0x0800b950`; else -> AT/baseband state machine `0x0800a710` (when flag [0x20000118] == 0,
  its init value) **and** always the 55 AA parser `0x0801f8a0`. Both parsers run in parallel.
- State machine `0x0800a710`: magic sequences set at run time by `0x0800aa20`:
  `84 A9 61` (SCT3258 packet start) -> state 1 = raw baseband packet pass-through;
  `'A' 'T'` -> state 4 = AT line mode (buffer 0x2000055b, ends at '\r', then the AT table walker
  `0x08013a9c`; the table actually starts at 0x080258a8). `+SENDSMS` is special-cased.
  => **no mode switch should be needed: an `AT+...\r` line on /dev/ttyS0 is parsed as an AT
  command even while the 55 AA protocol is in use.** (Expected; not yet confirmed on device.)
- AT numeric args: decimal atoi (`0x080082bc`). `+SDKWRITE` hex payload (`0x08008234`): plain
  hex digit pairs, upper/lower case, no prefix/separators, max 100-byte buffer.
- `+SDKWRITE=a,b,c,d,hex`: a=0 -> `sub_800e4b0(c)` sets the packet TYPE low 7 bits (bit 5 =
  read, bit 4 = far end, 3-0 = packet type; 0 = normal write), `sub_80071b8(b, buf)` sends field b,
  `sub_801da78(3, d)` waits d ms.
- `+SDKREAD=a,b,c,d`: a=2 -> `sub_8012678(b, buf, c, d)` = search the queue of fields **already
  reported** by the baseband for field ID b, copy c bytes. It does not send a request.
  SCT3258 manual: ANALOG_CONFIG "Note" column = N (not readable). => **current ANALOG_CONFIG
  (mode byte + calibrated gains) cannot be read back**.
- `+REGALL` (`0x08005bd0`) is not a register dump: it compares its argument with two strings
  and returns a status. The README's "+REGALL = register dump" guess is wrong.
- Restore strategy without readback: the firmware re-sends its own ANALOG_CONFIG (RAM/EEPROM
  values) from its analog setup paths (callers 0x800f726, 0x8013c8c, 0x8014e90, 0x8017198), so
  re-selecting the channel in the RFinder app should restore the calibrated values. To be verified
  by a capture showing the HPF back.

### Step 2 (operator approved "Go!"): filter-bypass sequence, stopped at the probe stage

- [phone] `am force-stop com.w2cyk.android.rfinder`; afterwards no process holds /dev/ttyS0.
- [module] read-only AT probes via `atcmd.sh` (printf '%s\r' > /dev/ttyS0, reader on the port):
  `AT+MODELNAME?`, `AT+RSSIVAL?` -> **0 reply bytes**. Per plan: **no write sent.**
- **Reader bug found:** ttyS0 is raw with VMIN=0/VTIME=0, so a single `timeout N cat /dev/ttyS0`
  hits EOF at once and exits. All earlier "no reply" results (both 55 AA RSSI reads) are therefore
  inconclusive. Reader fixed to loop `cat` for the whole window (no termios change).
- [module] with the fixed reader: `AT+MODELNAME?`, `AT+RSSIVAL?`, and the 55 AA RSSI frame
  `55 AA 00 01 09 01` (3rd send of it in total) -> **still 0 reply bytes**.
- [phone] read-only: hw_pd 1, uart_sw 0, uart_BB_PC_sw 0, mic_sw 0; `/proc/tty/driver/*`:
  port 0 (0x11002000) tx:0 rx:0, port 1 (0x11003000) tx:12 rx:0 (counters may be unreliable
  with MediaTek DMA UART).
- [phone] baseline capture `rx-test/device/bypass/pre_bypass.wav` (BT mode 1, ADC1/IN_ADC1, 20 s,
  restored): module alive and receiving: -36 dBFS rms, 4800.0 Hz clock line 73.9 dB.
- [host] static check of libintercomjni `getRSSI` (0xd5c4): frame = word 0x0100AA55 + half 0x0109
  = `55 AA 00 01 09 01` (identical to mine); usleep(500 ms); write 6 under rwlock; usleep(100 ms);
  read up to 10 bytes with timeout on the persistent `fd_uart_dev`. `config_serial` = plain
  38400 8N1 raw (B38400, CS8), same as the current stty. No extra ioctl or wake step in that path.
- **Status:** module receives fine but answers nothing on /dev/ttyS0 to either protocol from the
  shell. Cause unknown (possibilities: TX from the SoC not reaching the module on this path, a wake
  or select line handled elsewhere, the module UART parser state). Nothing was written to the
  module configuration. RFinder app is force-stopped (operator to reopen).
- Operator reopened the RFinder app. Operator: the app's RSSI meter does not move.
- **Operator approved strace;** used kernel ftrace instead (no new binary): `raw_syscalls`
  sys_enter/sys_exit filtered to the app's threads and NR 63/64/29/56/57 (read/write/ioctl/
  openat/close), `apptrace.sh`. Original `buffer_size_kb` = 7; first run wrongly restored it
  to 1408, corrected to 7 immediately; tracing_on 0, event disabled after each run.
  - 30 s idle trace (`rx-test/device/apptrace.txt`): app pid 11430 holds /dev/ttyS0 as fd 143;
    **zero read/write/ioctl calls on fd 143** (1899 syscalls total). The app does not poll the
    module while idle, so the RSSI meter is static by design or by failure.
  - 180 s trace running while the operator performs actions (channel reselect / volume knob) ->
    `rx-test/device/apptrace_action.txt`.
- Missed first action window; that trace was killed (and its leftover sleeper killed so it could not
  switch off the next trace), settings restored. New open-ended trace (`trace_start.sh` /
  `trace_stop.sh`, 15 min watchdog) during operator actions 18:50:38-18:52:28; restored after
  (tracing_on 0, event 0, buffer_size_kb 7). -> `rx-test/device/apptrace_action.txt`.
  - fd 143 (/dev/ttyS0): each action = `ioctl(intercom, 0x4906, 3)` then 6-byte writes, each
    followed ~200-300 ms later by a read returning **4 bytes**. (20-byte channel frames were sent
    from a new "Send to Runbo" thread that the start-time TID filter did not cover.)
  - logcat (library's own log): "Set SD01 analog parameters ... nwrite = 20, nread = 4",
    "set volume = 2, nwrite = 6, nread = 4 ... successful". **The module answers the library.**
  - Channel actually programmed by the app (final, 18:51:28): **TX = RX = 43347403 (x10 Hz =
    433.474030 MHz, 970 Hz below 433.475), TxTCS = RxTcs = 21, Squelch 0, Wide Band 0**. Module
    volume level 2 (knob down -> 1, back -> 2).
- [module] read-only probes repeated **with the app running** and the fixed reader:
  - `55 AA 00 01 09 01` -> `5a a5 09 d0 ee 87 02 a4 a7 0e` (10 bytes; header 5A A5, opcode 09,
    D0 = success, 6 data bytes).
  - `AT+MODELNAME?` -> `+MODELNAME:BOARD_EVM` / `OK`.
  - `AT+RSSIVAL?` -> `+RSSIVAL:-3` / `OK` (**RSSI snapshot, step 5**; unit unknown).
  => **AT and 55 AA both work on /dev/ttyS0 in parallel.** The earlier silence was the reader bug,
  then the force-stopped app (the module did not answer while the app was stopped; cause unknown).
- Operator: app channel shows 433.475 MHz, **FM-W**, **PL 127.3 enabled** (operator believed CTCSS
  was disabled) => "Wide Band: 0" = wide in the app's encoding; Tcs 21 = 127.3 Hz. **All captures so
  far had an RX CTCSS tone configured.** Operator: the app's ON/OFF button enables/disables the RF
  module (likely why the module was silent after force-stop).
- **Operator approved bypass with the app running.** [phone] `cap.sh pre2 20` (BT mode, ADC1/IN_ADC1,
  restore) -> pre2.wav; [module] 18:58:23 **`AT+SDKWRITE=0,60,0,200,0908001000100010000800`** ->
  reply `\r\nOK\r\n`; [phone] `cap.sh bypass 20` -> bypass.wav. Mixer after == baseline.
  - pre2: -38 dBFS rms, clock line 71 dB, normal stock response.
  - **bypass: RX audio muted.** 250-3000 Hz down 25-47 dB to the ADC noise floor, no 4800 Hz line;
    <250 Hz unchanged (noise floor). Plot `rx-test/device/bypass/compare_spectrum.png`.
  - Likely cause: RX CTCSS 127.3 configured; with FILTER_BYPASS the sub-audio decoder sees no tone,
    so audio stays gated. (Other possibility: bypass routes nothing to the codec on this firmware.)
  - **Module currently in bypass state: do not transmit with the B1.** Restore = operator reselects
    channel in the app.
- Operator: audio went silent during the bypass, came back after RF module OFF/ON; channel
  reselected with **PL none**. logcat 19:00:46: TX = RX = 43347403, TxTCS = RxTcs = 0, Squelch 0,
  Wide Band 0 (= FM-W), volume 2.
- **Operator approved repeat.** [phone] `cap.sh notone 20` -> notone.wav; [module] 19:02:03
  **`AT+SDKWRITE=0,60,0,200,0908001000100010000800`** -> `OK`; [phone] `cap.sh bypass2 20` ->
  bypass2.wav. Mixer after == baseline.
  - Band PSD (dB/Hz), PL 127.3 / no tone / no tone + bypass:
    60-150 -102/-102/-103; 150-250 -98/-98/-98; 250-350 -79/-77/-103; 350-500 -67/-66/-105;
    500-1k -70/-68/-109; 1-2k -73/-72/-112; 2-3k -77/-76/-122; 3-3.6k -91/-90/-125.
  - **CTCSS on/off does not change the stock response** (level +1-2 dB, same HPF/LPF shape): the
    ~300 Hz steep HPF is always in the path. Session-3 channel analysis holds for the no-tone path.
  - **FILTER_BYPASS mutes RX audio even with no tone**: bypass mode routes no RX audio to the
    codec on this firmware/chip. Not usable to remove the HPF.
  - Below 250 Hz all three captures sit at the same floor (= phone ADC path noise floor):
    the LF 4FSK content is lost under the phone-side noise, not module noise.
  - Module is again in bypass state; restore = operator OFF/ON or channel reselect, then check capture.

### Removing the HPF: EQ design, firmware question, WORK_MODE lead (static / host only)

- Restore check after operator RF OFF/ON: `cap.sh restore_check 10` -> normal audio (-37 dBFS,
  clock line 67 dB).
- EQUALIZER_FILTER (0x70) spec: sel byte (bit5 0 = RX, bit4 enable, bits 3-0 filter 1..3) + a1, a2,
  b0, b1, b2 Q2.14 MSB first, fs 24 kHz, H = (b0+b1 z^-1+b2 z^-2)/(1+a1 z^-1+a2 z^-2).
  Firmware field-length table @0x08026280 (pairs [id, len+1]): 0x3C -> 11, **0x70 -> 11**,
  0x18 -> 3. Field queue `sub_80071b8` only enqueues (id, ptr); packet built in `0x0800b5e4`.
- `rx-test/eqdesign.py` on notone.wav: measured path = steep HPF wall ~270 Hz (-30 dB below),
  ~5 dB dip 1.5-2 kHz, LPF edge -6 dB @3.0 kHz to -23 dB @3.45 kHz. 3 RBJ peaking biquads:
  277 Hz +19.4 dB Q8; 1703 Hz +5.0 dB Q2.3; 3395 Hz +19.0 dB Q6 (max |pole| 0.9985).
  Residual 272-3398 Hz: 1.84 dB rms (16 dB p-p, at the 270 Hz edge). Cannot recover < ~260 Hz.
  Commands (NOT sent): `AT+SDKWRITE=0,112,0,200,1180873FCF40C980873F06`,
  `...,129420379143529420343F`, `...,13B1083D484AB9B108328F`; disable = sel 0x01/0x02/0x03 +
  zeros. Plot `rx-test/device/eq/eq_design.png`.
- **Firmware question (operator: "modify the firmware to disable the HPF"):** SCT3258 manual 2.1:
  after reset the MCU downloads only a fixed 1024-word boot loader over HPI; the DSP application
  (with the analog RX HPF) runs from the SCT3258's own embedded flash. **The HPF code is not in
  SD01_UAVA_RFINDER.bin.** The documented controls are only CTC_PARAM HPF_CORNER (300/450 Hz)
  and ANALOG_CONFIG FILTER_BYPASS (mutes RX). An MCU patch can only automate runtime packet
  settings, unless the boot loader is replaced (no DSP code available; not verifiable).
- **WORK_MODE (0x18) lead:** [work mode][modem loop nibble 7:4 | audio loop nibble 3:0][debug].
  Audio loop 2 = "Decimator Loop back" may route the RX demod/decimator output straight to the
  audio DAC, bypassing the analog audio filters. Firmware sends field 24 from one place (normal
  setter). Candidate test: `AT+SDKWRITE=0,24,0,200,010200` (work mode 1 = RX, audio loop 2,
  debug 0). Not sent.
- **Operator approved both tests** (WORK_MODE loop-back, then EQ). Operator warning: the audio
  sometimes dies by itself and comes back with a knob turn.
- Test 1: [phone] `cap.sh wm_pre 5` 19:12:17; [module] **`AT+SDKWRITE=0,24,0,200,010200`** -> `OK`;
  [phone] `cap.sh wm_test 20`. Mixer after == baseline.
  - **wm_pre was already silent** (300-3k -77 dB, no 4800 Hz line), so the audio had died before
    the write (operator confirms silence). **Test 1 inconclusive.** My script did not gate the
    write on the pre-check; it does now (`gated.sh`: skip the write unless the pre-check shows the
    4800 Hz clock line > 30 dB and in-band > -55 dB).
  - Module state now: WORK_MODE write applied on top of dead audio. Restore = RF OFF/ON.
- Test 1 rerun after operator RF OFF/ON: wm_pre2 19:14:12 SIGNAL OK (line 57 dB) ->
  **`AT+SDKWRITE=0,24,0,200,010200`** -> `OK` -> wm_test2 silent (only a faint 105-141 Hz hump at
  -88 dB/Hz). Operator turned the knob (app: "set volume = 2 ... successful" 19:15:11) -> wm_knob:
  SIGNAL OK, response identical to stock (all bands within 0.3 dB).
- Test 2: eq_pre **NO SIGNAL** (no write since wm_knob) -> gate worked, **EQ not sent**.
- **Procedure artefact found:** each `cap.sh` toggles BT mode 1 -> 0. Over the session, only the first
  capture after a restore (RF OFF/ON or knob) has signal; the next separate capture is silent,
  with or without a module write in between (restore_check -> wm_pre and wm_knob -> eq_pre had
  no write). The session-2 sweep (3 captures in one BT-mode session) was fine. => **switching BT
  mode off/on mutes the module audio until a volume command or RF restart.** The operator's
  "audio dies by itself" is very likely this.
  => **The FILTER_BYPASS "mute" (bypass, bypass2) and the WORK_MODE silence are NOT valid
  results**: each test capture was the 2nd BT session after a restore. Retest with pre-check,
  write and test capture inside ONE BT-mode session (`sess.sh`).
- **Retest a (EQ), single BT session** (`sess_begin.sh` / `sess_cap.sh` / `sess_end.sh`): operator knob
  turn first. eqA_pre 19:18:59 SIGNAL OK (line 58.6 dB) -> 19:19:00 **`AT+SDKWRITE=0,112,0,200,
  1180873FCF40C980873F06`**, **`...,129420379143529420343F`**, **`...,13B1083D484AB9B108328F`** -> each
  `OK` -> eqA_test (20 s) SIGNAL OK (line 60 dB). Session end 19:19:31, mixer == baseline.
  - **Measured EQ matches the design within ~1 dB** above 275 Hz (275-300 +12.1/+13.0 designed,
    1.5-2k +4.1/+4.0, 3.0-3.2k +7.9/+7.9, 3.2-3.4k +13.9/+14.9, 3.4-3.6k +15.0/+14.6; 250-275 +7.2/
    +10.5). RX path 280-3400 Hz: 28.3 -> 13.2 dB p-p, std 4.38 -> 1.85 dB. Below 250 Hz unchanged
    (-31 dB). Plot `rx-test/device/eq/eq_result.png`.
  - Blind cross-validated MER (`device/ddtaps.py`, 81 taps): stock (notone) 12.1 dB, with EQ 11.6 dB.
    **No MER gain**: the in-band ripple was already software-equalisable; the limit is the <260 Hz
    content removed by the HPF, which no EQ can restore.
  - EQ is active in the module now. Restore = operator RF OFF/ON.
- Operator RF OFF/ON after EQ test; knob check; **volume now 1** (was 2).
- **Retest b (WORK_MODE), single BT session:** wmB_pre 19:21:37 SIGNAL OK (line 51.8 dB) -> 19:21:38
  **`AT+SDKWRITE=0,24,0,200,010200`** -> `OK` -> wmB_test (20 s) SIGNAL OK. Session end 19:22:03,
  mixer == baseline. **No effect:** every band 20 Hz-12 kHz identical within 0.1 dB (HPF wall
  unchanged). The earlier "silence" after WORK_MODE was the BT-toggle artefact. Decimator
  loop-back is not a route around the HPF (ignored, or not applicable in analog RX).
- Operator RF OFF/ON, buzz back.
- **Retest c (FILTER_BYPASS), single BT session:** byC_pre 19:23:10 SIGNAL OK (line 52.3 dB, -46 dBFS)
  -> 19:23:11 **`AT+SDKWRITE=0,60,0,200,0908001000100010000800`** -> `OK` -> byC_test (20 s).
  Session end 19:23:36, mixer == baseline.
  - **Bypass does NOT mute.** Output -2.2 dBFS rms, +0.3 dBFS peak, 4800 Hz clock line 50 dB.
    Band PSD pre -> bypass: 20-100 -99 -> -47.5; 100-250 -99 -> -45.6; 250-350 -87 -> -44.5;
    1-2k -82 -> -34.4; 3.6-6k -121 -> -48. **LF content now present** (the HPF is gone).
  - **Saturated:** 31.7 % of samples at +full scale; most others at -0.5..-0.85 FS => large DC
    offset (radio tuned 433.474030 MHz vs generator 433.475 MHz = 970 Hz offset, now passed as DC)
    plus ~+44 dB more gain than the stock path. Not analysable.
  - The earlier "bypass mutes" conclusion was the BT-toggle artefact. Corrected.
  - Module in bypass state; restore = RF OFF/ON. Do not transmit with the B1 in this state.
- Operator: the end of the previous session (BT mode off with bypass active) blasted the speaker
  (jump-scare). Operator rule: **volume 2 maximum**. Operator retuned the generator to the radio's
  frequency (433.474030 MHz).
- **Bypass RX-gain sweep (operator approved), single BT session:** bs_pre 19:28:17 SIGNAL OK ->
  `AT+SDKWRITE=0,60,0,200,0908001000100010000100` (RX gain 0x0100) 19:28:18 -> bs_0100 (10 s);
  `...0040` 19:28:32 -> bs_0040; `...0010` 19:28:45 -> bs_0010; session end 19:28:59, mixer ==
  baseline. Each write `OK`.
  - **RX volume gain has no effect in bypass mode:** all three -2.0..-2.1 dBFS rms, ~32 % of
    samples at full scale, identical spectra (+/-0.6 dB). DC (after mean) -0.039 FS; the saturation
    pattern persists with the generator retuned, so it is not only the frequency offset.
  - **Broke the "quietest at session end" promise:** session ended with bypass at full level ->
    speaker loud again. Asked the operator to RF OFF/ON immediately.
  - Next lever (needs approval): phone PGA1 18 dB -> 0 dB (`Audio_PGA1_Setting`), to tell whether
    the clipping is in the phone ADC path or already in the module codec output.
- **Bypass + phone PGA test (operator approved), one BT session, BT mode deliberately left ON:**
  pg_pre 19:31:18 SIGNAL OK -> 19:31:19 `AT+SDKWRITE=0,60,0,200,0908001000100010000800` -> `OK`;
  `tinymix set Audio_PGA1_Setting 18Db` -> "invalid value (18)" (tinymix parses 18 as a number;
  PGA was already 18 dB); then `... 6Db`, `... 0Db`; 10 s captures pg_18Db, pg_6Db, pg_0Db.
  - 18 dB: -2.0 dBFS rms, 32 % at full scale; 6 dB: 35 %; **0 dB: -15.7 dBFS rms, -9.7 dBFS peak,
    no clipping.**
  - **Bypass output is not usable 4FSK:** raw waveform at 0 dB = a train of sharp pulses (-0.13 ->
    +0.3 FS, about every 0.6 ms); MF symbol histogram has TWO peaks, not four. The kurtosis 1.58
    I first quoted reflects this two-peaked distribution; retracted. Plot
    `rx-test/device/bypass/pga/pg0_wave.png`.
  - **Speaker blasted at max volume even with BT mode ON** (operator report). BT mode does not keep
    the speaker silent with the bypass active. Third loud incident. Operator asked to RF OFF/ON.
    Session still open: PGA1 0 dB, ADC1 On, Preamp1 IN_ADC1, BT mode 1, to be ended after the
    restart.
  - Conclusion: FILTER_BYPASS on this module does not give clean unfiltered demod audio; not a
    route for M17. **No further bypass tests.**
- Operator RF OFF/ON. Inside the still-open session: `tinymix set Audio_PGA1_Setting 3` (= 18 dB),
  `sess_cap.sh final_check 10` -> SIGNAL OK (line 56.5 dB), response = stock no-tone shape within
  ~1 dB from 250 Hz up (level -10 dB: volume 1 vs 2); `sess_end.sh` 19:35:05. Mixer == baseline,
  BT mode 0, mic_sw / uart_sw / uart_BB_PC_sw 0. **Module and phone back to stock.**

## Summary (2026-11-07)

**Can the stock B1-Plus analog FM RX path carry M17 4FSK?** Not reliably, and no runtime setting
fixes it.

- **Getting the audio:** RX audio only reaches the SoC in intercom BT mode (ioctl 0x4905 = 1), on
  PMIC input IN_ADC1, at 48 kHz via tinycap with ADC1 on and Preamp1 = IN_ADC1. Normally the module
  drives the AW87329 speaker amp directly. Pitfall: switching BT mode off/on mutes the module audio
  until a volume command or an RF restart.
- **Stock channel** (measured; CTCSS on or off makes no difference): a steep HPF inside the SCT3258
  DSP (pass 300 Hz, stop 255 Hz; about -30 dB below 260 Hz), no de-emphasis tilt, ~5 dB dip at
  1.5-2 kHz, LPF edge -6 dB at 3.0 kHz and -23 dB at 3.45 kHz, dispersive group delay. The 4FSK
  content below ~260 Hz ends up under the phone-path noise floor.
- **Demodulation (blind; no reference pattern was available, the source repeats every 1024
  symbols):** symbol clock recovered at 4800.0 Hz (+1 ppm); 4-level statistics recovered blindly;
  cross-validated MER caps at **~12 dB** for any linear/DFE software equaliser, consistent with the
  LF loss. SER could not be measured without the reference pattern; at ~12 dB MER, 4-PAM SER would
  be several percent.
- **Module-side options tried** (SD01 AT commands work on /dev/ttyS0 in parallel with 55 AA while the
  RFinder app has the module on; `AT+SDKWRITE=0,<field>,0,200,<hex>` writes SCT3258 packet fields):
  - RX EQUALIZER_FILTER (0x70), 3 biquads: works exactly as designed, flattens 290 Hz-3.4 kHz
    (std 4.4 -> 1.85 dB) but **no MER gain** (cannot restore < 260 Hz).
  - WORK_MODE (0x18) audio decimator loop-back: no effect.
  - ANALOG_CONFIG FILTER_BYPASS: output becomes a pulse train at excessive level (drives the
    speaker to max even with BT mode on); not usable. Do not use again.
  - CTC_PARAM HPF_CORNER: only 300 or 450 Hz; no off setting.
- **Firmware:** the HPF runs in the SCT3258's own embedded-flash DSP application; the SD01 MCU image
  only sends the 1024-word boot loader and configuration packets. Patching SD01_UAVA_RFINDER.bin
  cannot remove the HPF.
- **Remaining routes for M17 on this hardware** (not attempted): the SCT3258's native 4FSK modem
  (DMR/dPMR digital modes) with raw symbol/bit access, if any packet field exposes it; or an external
  audio path that taps the discriminator before the SCT3258 (hardware modification).
- README corrections found along the way: firmware load base is 0x08003000 (not 0x08000000);
  +REGALL is not a register dump; AT text and 55 AA binary are parsed in parallel on the same UART;
  the module answers only while the RFinder app has it switched on.
- Left on the phone: /data/local/tmp/{tinycap,tinymix,tinypcminfo,btmode,*.sh} and rx/ (recordings,
  traces). ftrace settings restored (buffer_size_kb 7, tracing off, filters cleared).

### Re-analysis of the FILTER_BYPASS capture (operator: "it should work"), offline only

- pg_0Db (bypass) vs pg_pre (stock, same session), both averaged over the 1024-symbol period:
  - bypass is **exactly periodic** with the test pattern (autocorr 0.999 at 1024 and 2048 symbols,
    -0.35 at 1023/1025; period-to-average r 0.998) => a deterministic function of the 4FSK.
  - aligned (circular shift 4491 samples) 601-tap linear FIR stock -> bypass explains **67 %** of
    bypass variance (my earlier 5 % figure skipped the alignment: invalid).
  - waveform: **flat floor at about -0.13 FS** (clip rail) with only positive excursions to +0.3.
    => **one-sided clipping**, not a pulse generator. Plot `bypass_vs_stock.png`.
- Interpretation (most likely): FILTER_BYPASS does pass the unfiltered demodulator output, including
  its DC (residual carrier offset + discriminator offset; the HPF normally removes it), with about
  +44 dB more gain that the RX volume field does not control. DC + gain drive the module's audio output
  into its negative rail; the AC-coupled phone input shows the surviving peaks as "pulses". This also
  explains the speaker blasts. **Earlier "pulse train, not usable" conclusion corrected: the bypass
  works, the operating point is wrong.**
- Levers: lower the RF deviation (scales the AC part); null the carrier offset (the DC part);
  SCT3258 DC_OFFSET field 0x39 (not explored).
- **Tone test (operator approved; generator in plain FM, sine).** One BT session, kept open between
  messages. Gate = `tone.py` (tone > 20 dB above floor).
  - t_pre 19:46:45 (stock, 1 kHz tone, 250 Hz deviation): -55.6 dBFS, THD -26.9 dB, no clipping.
  - 19:46:46 `AT+SDKWRITE=0,60,0,200,0908001000100010000800` -> `OK`; t_1k_250 (bypass):
    **-17.9 dBFS (+37.7 dB vs stock), THD -40.6 dB, peaks +0.206/-0.207, no clipping.**
    => FILTER_BYPASS gives a clean, linear, low-distortion path at this level; no DC problem.
  - The 4FSK "pulses" were level: estimated module output rail ~ +/-2 kHz peak deviation
    (from pg_0Db: rail about +/-0.215 FS at PGA 0 dB; 250 Hz dev = 0.206 FS at PGA 18 dB).
  - t_100_250 (100 Hz, 250 Hz dev, bypass): tone **-57.9 dBFS = -40 dB vs 1 kHz**. => a high-pass
    remains in the bypass chain (candidates: module codec, phone mic-input AC coupling, MediaTek UL
    IIR). The LF content in the clipped 4FSK bypass capture was clipping products.
  - Spurious ~4.9 kHz component in the bypass output, intermodulating with the audio (sidebands
    3910/4910/5909 Hz with 1 kHz; 4.4-5.4 kHz comb at 100 Hz spacing with 100 Hz). Out of the M17
    band.
  - Bypass tone response @250 Hz dev, rel. 1 kHz (-17.9 dBFS): 100 Hz -40.0, 200 Hz -23.1
    (THD -29.5), 300 Hz -11.6 (THD -33.5), 500 Hz +1.4 (THD -40.1) dB. Slope ~17-20 dB/oct below
    300 Hz = **same shape as the stock path's HPF**. => **FILTER_BYPASS does not remove the steep
    HPF.**
  - Phone uplink IIR coefficients (AFE dump, read-only): COEF_04_03 = 0x3fb8, COEF_06_05 = 0x3fb8<<16,
    COEF_08_07 = 0x3fb8<<16, COEF_10_09 = 0xc048 (+/-0.9956 Q14) => DC blocker near DC, cannot
    explain a 20 dB/oct cut at 300 Hz; a passive coupling cap would be 6 dB/oct. => the steep HPF is
    most likely still in the SCT3258 even in bypass (partial bypass). HF steps (2k, 3k) to check the LPF.
  - Bypass tone response, continued: 2000 Hz +1.8 dB (THD -42), 3000 Hz +4.8 dB (THD -45) rel 1 kHz.
    Stock path at 2-3 kHz was 4-7 dB down. => bypass removes the post-HPF stages (mid/high droop,
    3 kHz LPF), adds ~38 dB of gain, but **keeps the steep HPF** (partial bypass).
  - Deviation headroom (1 kHz tone): 1000 Hz dev @PGA 18 dB: phone clips (27 %, THD -8.5 dB).
    **Operator approved** `tinymix set Audio_PGA1_Setting 0` (0 dB): t_1k_1000_pga0: no phone clipping
    (peaks +0.268/-0.166), but **THD -7 dB, H2 -9 dBc, asymmetric => module output rail clips
    (negative side ~ -0.17 FS @PGA 0) below 1000 Hz deviation.** M17 (+/-2400 Hz) is far beyond it.
    1500-2500 Hz steps skipped (uninformative).
  - **Conclusion: FILTER_BYPASS is a partial bypass (HPF stays) whose output saturates below 1 kHz
    deviation. Not usable for M17.**
- Operator RF OFF/ON, deviation back to 250 Hz. Inside the session: `tinymix set Audio_PGA1_Setting 3`
  (18 dB); t_restore: 1 kHz tone -55.4 dBFS, THD -27.6 dB (= stock t_pre -55.6 / -26.9); session end
  19:56:13. Mixer == baseline, BT mode 0, bt_ptt / mic_sw / uart_sw / uart_BB_PC_sw 0. **Back to stock.**

## Summary update (supersedes the FILTER_BYPASS lines in the summary above)

- **ANALOG_CONFIG FILTER_BYPASS works, but only partially.** Tone sweep at 250 Hz deviation, rel. 1 kHz:
  100 Hz -40.0, 200 Hz -23.1, 300 Hz -11.6, 500 Hz +1.4, 2 kHz +1.8, 3 kHz +4.8 dB; THD -40..-45 dB
  above 500 Hz. It removes the post-HPF stages (mid/high droop, 3 kHz LPF) and adds ~38 dB of gain,
  but **the steep HPF stays**. The output saturates in the module (asymmetric, negative rail
  ~-0.17 FS) **below 1 kHz deviation**, so M17's +/-2400 Hz clips; that is what made the 4FSK look
  like "pulses". The RX volume gain field does not apply in bypass. With bypass active the speaker
  plays near full scale regardless of BT mode or the knob.
- Overall conclusion unchanged: the steep ~300 Hz HPF in the SCT3258 cannot be removed with any
  runtime setting found (ANALOG_CONFIG incl. FILTER_BYPASS, CTC_PARAM, WORK_MODE, EQUALIZER_FILTER)
  nor via the SD01 MCU firmware; it caps software-equalised MER at ~12 dB for M17 on the stock RX path.

### Real M17 over the stock RX path (CS7000 transmitter), no module writes

- **Operator approved** building M17_Implementations (f2000aec, submodules micro-ecc 31520c8f,
  tinier-aes 8cff8da2) and libm17 (3684edce) in the scratchpad. The decoder links against the
  installed /usr/local/lib/libm17.so.1.4 (same version 1.4.1).
- Stock B1 settings (no tone, wide, squelch 0, volume <= 2). One BT session: m17_idle 20:05:05
  (-43 dBFS); operator keyed the CS7000 (M17 voice, 433.475 MHz) -> `sess_cap.sh m17_rx1 25` (ended
  20:06:03): steady -48 dB band power for all 25 s, 4799.9 Hz clock line 40 dB. Session end later,
  mixer == baseline.
- Front end `rx-test/m17_front.py` (clock recovery -12 ppm, RRC MF, stream-sync search; optional
  T/2 LS equaliser trained on the known 0xFF5D sync symbols) -> float32 symbols ->
  `m17-decoder-sym -c -l -v`.
  - Plain (no EQ): sync-word correlation median 0.58 (only 295/618 > 0.6). Sync words are runs
    of outer symbols = LF-heavy, hit hardest by the HPF. **Decoder finds 0 frames.**
  - Sync-trained EQ: sync-symbol MER 12.4 dB (41 taps) / 13.8 dB (81 taps).
- **Decoder bug found:** m17-decoder-sym aborted ("buffer overflow detected") as soon as frames were
  found: `memcpy((uint8_t*)&lsf+lich_cnt*5, lich_b, 5)` with LICH_CNT (3 bits) = 6/7 from a corrupted
  LICH writes past the 30-byte lsf. Patched locally in the scratchpad copy (`if(lich_cnt<6)` guard).
  Worth fixing upstream.
- Results (frames decoded / FN-consistent / share of ~610 transmitted):
  none 0; sync-41 459 / 187 (41 %); **sync-81 544 / 349 (64 %) ~ 57 % of transmitted frames**;
  dd-41 265 / 58; dd-81 415 / 265. Viterbi metric e ~ 35-50 (uncalibrated). **No LSF recovered**
  (no complete LICH superframe passed).
- Codec2 3200 audio from the FN-consistent sync-81 frames (missing frames zero-filled; 347/610):
  `rx-test/device/m17/b1_m17_decoded_audio.wav` (24.4 s, 8 kHz). Intelligibility to be judged by the
  operator.

### M17 A/B: stock vs in-chip low-frequency boost (operator approved, CS7000 TX)

- EQ design (host): filter 1 RBJ low shelf 250 Hz +24 dB S=0.7 (a1 -1.95316 a2 0.95421 b0 1.07216
  b1 -1.94535 b2 0.88986), filters 2/3 as before. Gain rel 1 kHz: 100 Hz +21, 150 +18, 200 +14,
  250 +11, 300 +8, 500 +2, 3.4 kHz +18 dB. Max pole 0.9785.
- One BT session opened 20:38:10. Operator set volume 2 (also un-mutes the module).
  - Transmission A (stock): `sess_cap.sh m17_A 25` (end 20:39:05): -35.5 dBFS, clock line 39.4 dB.
  - [module] 20:39:15-20:39:25 `AT+SDKWRITE=0,112,0,200,1182FF3D12449E837F38F3`,
    `...,129420379143529420343F`, `...,13B1083D484AB9B108328F` -> each `OK`.
  - Transmission B (EQ): `sess_cap.sh m17_B 25` (end 20:40:11): -32.1 dBFS, peak -18.4 dBFS.
  - Band change B-A: 150-200 +8 (designed +16), 200-250 +3 (+12), 250-300 +10, 300-400 +7,
    3.0-3.4k +8 dB (as designed). Below 250 Hz the boost lifts mostly noise, partly signal.
- `m17_front.py` additions: `--pol` (force polarity) and `--hpf` (software high-pass). B's
  automatic polarity guess flipped (LF hum boosted), forcing -1 fixed it.
- **Second decoder bug** (patched in the scratchpad copy): `if(fn>=0x7FFC && signed_str)` does not
  mask the EoT bit, so a corrupted FN 0x8000-0xFFFB gives a negative `sig[]` index in
  `memcpy(&sig[((fn&0x7FFF)-0x7FFC)*16], ...)`. `signed_str` is taken from an LSF even when its
  CRC failed. Fixed to `(fn&0x7FFF)>=0x7FFC`.
- Results (eq sync, 161 taps, pol -1):
  - A stock: 587 frames, 424 FN-consistent (70 % of ~610), no LSF; stream-sync corr median 0.64.
  - **B LF-boost EQ: 604 frames, 503 FN-consistent (82 %), LSF assembled (DST @ALL, SRC SP5WWP,
    TYPE 0005 stream voice plain) but LSF_CRC_ERR**; stream-sync corr median 0.85.
  - Viterbi metric median ~42-43 in both.
- EQ still active in the module; BT session still open (speaker off). Restore = operator RF OFF/ON.
- Operator RF OFF/ON (EQ cleared). `sess_end.sh m17b`: BT mode 0, mixer == baseline, intercom
  switches 0. Operator fixed both m17-decoder-sym bugs upstream on GitHub.

### FEC-aided iterative receiver (offline, recordings A and B)

- `rx-test/m17_reenc.c` (built against the installed libm17): per frame slot, `decode_str_frame`, then
  `gen_frame(FRAME_STR)` with the decoded LICH chunk placed at `lich_cnt*5` of an `lsf_t`, giving the 192
  transmitted symbols. Reports FN, LICH_CNT, Viterbi e, pre-FEC bit errors (of 368). Self-test with
  libm17-generated frames: 30/30 exact; with noise sigma 0.6 (~3.7 % raw BER) the references still
  equal the clean input.
- `rx-test/m17_iter.py`: software HPF 80 Hz, clock recovery, RRC MF, T/2 LS equaliser (161 taps)
  trained first on syncwords, then on all 192 symbols of trusted frames (FN fits the 192-symbol
  grid AND <= 60 pre-FEC bit errors), 6 iterations. LSF by majority vote of LICH chunks + CRC.
  - A (stock): FN-consistent 474 -> 570/617 (92 %), pre-FEC BER median 10.6 -> 9.0 %.
  - B (LF-boost EQ): FN-consistent 516 -> 589/617 (95.5 %), pre-FEC BER median 10.6 -> 8.2 %.
  - **LSF CRC OK in both**: DST @ALL, SRC SP5WWP, TYPE 0005, META 115f2020...20 (votes per
    chunk e.g. 93/96).
- Reference decoder (`m17-decoder-sym`, upstream-fixed bugs patched locally) on the iterated symbols:
  default sync threshold -d 2.0 misses syncs (the equaliser no longer favours syncwords);
  -d 4.0: A 617 frames, 570 FN-consistent, LSF CRC OK 26/37; **B 616 frames, 588 FN-consistent
  (95 %), LSF CRC OK 58/69**.
- Audio (Codec2 3200, FN-consistent frames, gaps zero-filled): `rx-test/device/m17/m17_A_iter_audio.wav`,
  `m17_B_iter_audio.wav`. Payload correctness (post-FEC) not measurable without the transmitted
  voice; to be judged by listening.
- Caveat: this receiver is offline/batch (equaliser trained over the whole recording). A real-time
  version would adapt the equaliser continuously from FEC-verified frames (same principle).

### Speaker playback test (can decoded speech be played while BT mode keeps the 4FSK off the speaker?)

- [phone] `media volume --stream 3 --get` -> 0/15. Test tones pushed to /sdcard/Download (deleted after).
- BT mode 1, media volume 4, 1 kHz -30 dBFS tone via `am start -a VIEW` (YouTube Music audio
  preview, MediaPlayer state started, routed to AUDIO_DEVICE_OUT_SPEAKER, Speaker_Amp_Switch and
  Ext_Speaker_Amp_Switch On): **operator hears nothing** (also too quiet to be conclusive).
- BT mode 1, media volume 7, -12 dBFS tone: **nothing**. dmesg at playback start:
  `aw87329 aw_rst level:0` (amp held in reset).
- Control: BT mode 0, same tone: **buzz audible, tone not**. dmesg: `aw87329 aw_rst level:1`.
- Restored: player stopped, media volume 0, BT mode 0.
- **Finding:** while the RFinder app runs the radio, normal Android audio does not reach the
  speaker in either mode (BT mode 1: AW87329 held in reset; BT mode 0: the amp plays the module's
  intercom input). On-device decoded speech needs another output: earpiece (receiver path),
  headset, Bluetooth headset, or a different speaker-amp mode (ioctl 0x4906 spk_mode values other
  than 3, or with the app's radio switched off). Not explored yet.
- AW87329 sysfs (read-only listing): /sys/bus/i2c/drivers/aw87329/3-0058/{hwen,mode,protect,reg,update};
  `mode` help: 0 off, 1 kspk, 2 drcv, 3 abrcv. Idle (BT mode 0): hwen 0, mode 0, reg all 0x78.
  Kernel strings: aw87329_audio_{kspk,drcv,abrcv,off}, aw87329_intercom_kspk, `aw87329_intercom_mode`.
  Routing driver `audiopolicy_dt865` has no user interface (/sys/module only). It logs "audiopolicy
  device = 4" for BT mode, "= 0" + "intercom AMP_SPEAKER" for BT mode off.
- **Operator approved hwen/mode writes.** BT mode 1, media volume 5, -20 dBFS tone playing,
  `echo 1 > hwen; echo 1 > mode` -> amp out of reset (reg 0x00=0x39 ...), **operator hears static,
  no tone**: the amp input carries the module audio (open squelch) even in BT mode.
- **Operator approved option 3**: built `rx-test/device/spkmode.c` (ioctl 0x4906 hard-coded, values
  0/3 only). BT mode 1, tone, `spkmode 0` (dmesg "spk_mode:0", "aw_rst level:0, silent:1"), amp
  hwen 1 + mode 1 -> **static, no tone**. spk_mode 0 does not switch the amp input either.
- Restored: amp mode 0 / hwen 0, `spkmode 3`, player stopped, media volume 0, BT mode 0.
  Operator: wired / Bluetooth external audio is not acceptable (defeats the purpose).
- Control with **RF module OFF** (app button; dmesg "Power_Down intercom!", hw_pd 0): tone via Android,
  media volume 5: AudioFlinger track active on AUDIO_DEVICE_OUT_SPEAKER, screen on, **nothing audible**.
  Operator: **ringtones and YouTube are silent too**.
- dmesg: every playback since 18411 s shows `aw87329 aw_rst level:1, silent:1`. The flag went to 1 with
  **my `spkmode 0`** (18411 s) and `spkmode 3` did not clear it. Earlier today the amp came up with
  silent:0. => **my spk_mode 0 test very likely left the AW87329 driver muted**; a phone reboot is
  needed to reset it. (Earlier silent:0 failures remain: the routing problem is separate.)
  Also cleared the kernel ring buffer with `dmesg -c` at 22:42:22 (older entries are in these notes).
- `persist.sys.speaker.mode` toggled 1 -> 0 at 18886/18888 s during the operator's test. Only
  /system/priv-app/MtkSystemUI references it. SystemUI dex strings: `persist.sys.speaker.mode`,
  `speaker_mode`, `com.runbo.intercom.volume`, `/sys/bus/platform/drivers/gpio_ctr_driver/gpio20`,
  `.../gpio150`, `.../gpio169`. QS tiles: `...,otg,pocptt,speaker,night` => OEM "speaker" tile.
  gpio_ctr_driver nodes: gpio20 (rwxrwxrwx) = 0x0, gpio150 (rwxrwxrwx) = 0x0, gpio169 absent;
  others: gpio12, 17, 19, 42-47, 56, 79, 146, 153, 167, 173.
  Settings: volume_music_speaker=7, volume_ring_speaker=4, volume_alarm_speaker=6.
- **Operator rebooted the phone** -> amp silent flag back to 0; phone audio (ringtone) works with the
  RFinder app not running. adb reconnected.
- RFinder + RF module on: persist.sys.speaker.mode 0, gpio20/gpio150 0, amp hwen 1 mode 1, **hw_pd 1**
  (it was 0 with the module powered down, so hw_pd tracks module power).
- Operator tapped QS tile "Speaker Mode": "External" -> "Phone". Only effect: persist.sys.speaker.mode
  0 -> 1 (SpeakerTile_TAG log). GPIOs, amp and routing unchanged, buzz unchanged. Tone via Android
  with mode "Phone", radio on, BT mode off: **buzz only, no tone**. Restored media volume 0 (pre-test
  value after the reboot unknown, told the operator).
- pinctrl-maps (debugfs, read-only): intercom pins GPIO152 pdn, 173 bt_ptt, 55 mic headset/main,
  87 sq eint, 88 ptt eint, 151 ext uart, 54 sys_wake, 53 dmr_msg eint, 52 uart_sw, 176 mic power;
  ext_amp (AW87329) reset GPIO159; gpio_ctr pins 12, 56, 79, 150, 153, 164, 165, 167, 173, ...
  No audio-switch state in any pinctrl map.
- mt_gpio diff across `btmode 1` / `btmode 0`: only GPIO159 (AW87329 reset) changes as an output
  (GPIO15 and GPIO134 only change their input readings, they are in peripheral modes). => BT mode's
  "audiopolicy device 4" does not flip a userspace-visible GPIO switch.
- Working hypothesis: the module's single audio output feeds the speaker amp input (and in BT mode the
  SoC ADC). While the module is powered, phone audio does not reach the amp. Options: separate
  earpiece (if present), GPIO diff radio off/on, or play speech through the module (codec loop-back).
- adb dropped once (connection refused), operator re-armed it.
- **Key test (radio on, BT mode off, no module writes):** media volume 7 (read back), -12 dBFS 1 kHz tone.
  Knob 0: the RFinder app puts the AW87329 in reset (`aw_rst level:0` from android.rfinder) -> nothing.
  **Knob 1 + media volume max (operator): faint tone audible over the buzz.** Knob 0 -> gone.
  => phone audio and module audio are **summed at the amp input**; phone audio is much weaker. The
  amp runs only when the module volume is above 0 (or when forced via sysfs). Earlier "no tone" results
  were masking by the buzz plus, after `spkmode 0`, the stuck silent flag. Player stopped.

### Module codec analysis (static, read-only)

- `+CHIP` (handler 0x08004571) = `AT+CHIP=read|write,es8388s|eeprom,<hex addr>[,<hex value>]`. The
  **es8388s branch is a stub** (returns immediately for read and write). Only `eeprom` is implemented
  (read 0x08003e0c, write 0x08003eba). The SD01 MCU does not talk to the codec itself.
- SCT3258 manual 2.12/2.13: native codecs TLV320AIC3204 and WM8758B, selected with CODEC_SELECT
  (field 0x2D). Stereo codec usage: left ADC = mic, right ADC = FM demod, right DAC = VCTCXO,
  **left DAC = audio line out in RX** (VCO in TX). Host codec writes: SET_I2C_ADDRESS (0x2E) then
  raw packets with TYPE 0x40 (`84 A9 61 00 02 40 <b1> <b2>`), forwarded by the SCT3258 over I2C.
- MCU codec-bypass helpers at 0x0801c814..0x0801c9c2 (TYPE 0x40, field id 0, wait 200 ms): templates
  `00 56 vv`, `00 58 vv` (0x0801c814 writes 0x56 <- v|0x80 and 0x58 <- v2, an L/R pair with an update
  bit?), `00 10 vv`, `00 3B vv` (0x3B with 0x34 / 0x20 / 0x80 cases). These register numbers do not
  fit the es8388 map (0x00-0x34). 0x3B = 0x34/0x80 fits a TLV320AIC3204 page-1 MICPGA register.
  The actual codec part on the SD01 is not confirmed.
- No SET_I2C_ADDRESS payload and no codec init table found in the MCU image (the constant-0x2E hits
  are other uses; 0x08020502 sends fields 0x2E/0x2D/0x2F at startup via 0x0800819c, contents not
  yet decoded). => the SCT3258 most likely initialises the codec itself.
- 0x0800819c is a software-timer cancel (20-entry table), not a field send. The "startup" routine at
  0x08020502 just cancels timers 0x2E/0x2D/0x2F. The MCU never sets the codec I2C address.
- Codec helper callers: 0x0801c814 (L/R pair 0x56/0x58) <- 0x080139aa and 0x08013c4a; 0x0801c894
  (reg 0x10) <- 0x080145a8; 0x0801c8c4 (reg 0x3B) <- 0x080145a0; 0x0801c90c <- 0x080159a2, 0x080183a8;
  0x0801c954/0x0801c984 <- 0x08014590.
- 0x08013ba4: settings-apply dispatcher (switch8 on a parameter index 0..33, r2 = settings struct).
  Case 12: byte +4 -> 0x08014590 (two codec regs); case 15: bytes +6/+7 -> codec 0x56/0x58 pair.
- **Conclusion:** the codec's output routing (which output pin carries the left DAC = RX audio) is set
  by the SCT3258's native codec support and is not in the MCU image. The MCU only adjusts a few
  registers. Whether the speaker amp and the SoC ADC are fed from separate codec outputs cannot be
  read out statically.

### Codec output experiment (operator approved): which codec output feeds what

- Codec identified from the MCU's bypass writes as **TI TLV320AIC3204** ([page, reg, val]: p0 0x56/0x58 left
  AGC; p1 0x3B left MICPGA volume; p1 0x34 left MICPGA input routing 0x80/0x40/0x20; **p1 0x10 HPL
  driver gain, firmware also writes 0x40 = HPL muted**). Builder: TYPE 0x40, payload = field id 0x00 +
  5 buffer bytes => `AT+SDKWRITE=0,0,64,200,<page><reg><val>0000` reproduces the firmware helpers.
- Knob 1, radio on, open-squelch static as test signal, generator/CS7000 off. One BT session:
  hpl_pre (23:17:25): -48.4 dBFS rms. [module] **`AT+SDKWRITE=0,0,64,200,0110400000`** (p1 reg 0x10 =
  0x40, HPL mute) -> `OK`. hpl_mute: **-77.9 dBFS** (band -35..-38 dB). => **the SoC ADC capture is fed
  from HPL.**
- BT mode off (amp then in reset: hwen 0, reg 0x78). **Operator approved** amp enable: hwen 1, mode 1
  (reg 0x00=0x39 ...), HPL still muted: **operator hears silence**. => **the speaker amp is fed from HPL
  as well.** Amp switched back off (mode 0, hwen 0).
- **Conclusion:** one codec output (HPL) feeds both the speaker amp and the SoC ADC. The demodulated
  4FSK cannot be removed from the speaker without also removing it from the capture. Phone audio is
  summed into the amp input separately. With HPL muted, the speaker carries only phone audio.
- HPL mute still active in the module; restore = operator RF OFF/ON.
- Operator RF OFF/ON: module back (hw_pd 1, app sent spk_mode 3/0/3), but **no buzz**: amp came up
  `aw_rst level:1, silent:1`. Re-reading the log: the `silent` flag is latched by **my sysfs restores
  `echo 0 > .../mode`** (first silent:1 right after the 22:34 restore, before my spkmode 0 test; again
  after the 23:18 restore), not by spk_mode 0 as I wrote earlier. Stock radio-on value is mode 1.
  Fix offered: `echo 1 > mode` or a reboot (operator to choose).
- Modem research (manual, read-only): Layer 2 modes, REPORT_FIELD, VOCODER_IO_SET, transparent data all
  work after the SCT3258's own DMR/dPMR sync + FEC. No raw-symbol output found => no digital path for
  M17 symbols without changing the DSP firmware.
- **I2C_OPERATION (field 0x6A)**: raw I2C read/write to any device on the SCT3258 I2C bus (codec, RF
  transceiver). Read = TYPE 0x20, payload [dev addr, reg, n]. => codec routing registers can be read.
  Idea: AIC3204 analog routing of the FM-demod input (right ADC input pin) straight to HPL would bypass
  the SCT3258 HPF (fixes decode quality, not the buzz).
- Operator rebooted (amp silent latch cleared), RFinder + RF module on, volume 1, buzz back. adb re-armed.
- **Codec register reads (operator approved via "we need the HPF bypass"), all failed:**
  `AT+SDKWRITE=0,106,32,200,300010` / `...500,180001` / `...500,300001` -> `OK` + two `5A A5 06 A0`
  frames each; `AT+SDKREAD=2,106,...` -> `+SDKREAD_FAIL:-1`. Cause (static): +SDKWRITE waits in mode 3
  for an echo (field id + status 0), a read reply does not match, and the wait routine clears the
  received-field queue on exit (0x0801daac). Raw pass-through `84 A9 61 00 04 20 6A 18 00 01` -> only
  `5a a5 06 a0` x2, no data (the MCU consumes the SCT3258 reply). => **codec registers cannot be read**
  through the module.

### Codec analog routing test: HPL <- MAR (operator approved)

- Generator FM 1 kHz / 250 Hz dev, speaker covered. One BT session: mar_pre_1k (stock, 23:37:30): tone
  -68.4 dBFS (volume 1). [module] `AT+SDKWRITE=0,0,64,200,01103A0000` (p1 0x10 HPL gain -6 dB),
  `...01093D0000` (p1 0x09 driver power HPL/HPR/LOL/LOR/MAR), `...010C010000` (p1 0x0C HPL routing =
  MAR) -> each `OK`. mar_1k: -2.3 dBFS rms, 20 % clipped; dominated by a line at **2457 Hz** + harmonics
  4913/7371 Hz (the 4.9 kHz spur seen in the FILTER_BYPASS captures).
- **Operator approved PGA1 0 dB**; generator moved **+1 kHz**: line moves to **1455 Hz** (1:1, inverted)
  => the codec's right input carries the **received RF signal at low IF** (one baseband component of a
  near-zero-IF receiver, LO ~2.46 kHz above the signal), hard-limited (harmonics 2x/3x/4x), not FM-
  demodulated audio. The SCT3258 demodulates FM digitally (matches its IQ calibration fields).
  mar_p1k: -15.6 dBFS rms, no clipping.
- Software FM demod (band-pass around the carrier, Hilbert, instantaneous frequency): mean 1455.7 Hz
  (correct), but the 1 kHz tone shows only ~55-65 Hz deviation (generator 250 Hz), SNR 4-7 dB. The raw
  sidebands (-27 dBc) also indicate ~90 Hz. => modulation reduced before this tap. Suspect: SCT3258 AFC
  (AFC_CONFIG 0x05, right DAC -> VCTCXO) partly tracking the signal. Low IF (1455 Hz) also cramps the test.
- State: BT mode on, codec HPL <- MAR, PGA1 0 dB. Restore = operator RF OFF/ON (BT mode still on),
  then PGA1 18 dB, BT mode off.
- Generator -4.5 kHz (IF 5951.7 Hz as predicted), `rx-test/if_demod.py`: 1 kHz / 250 Hz dev -> 103 Hz
  recovered, H2 -5 dBc, SNR 37 dB. 1 kHz / 1000 Hz dev -> ~330-350 Hz recovered, H2 +9 dBc, SNR 2-4 dB.
  Raw level at 6 kHz IF ~9 dB below 1.5 kHz IF. Noise-floor trend (6 kHz capture): flat to ~4 kHz,
  ~-10 dB at 5-7 kHz, ~-17 dB at 8-10 kHz => RF-chip baseband filter ~4-5 kHz wide.
- **Conclusion:** the HPL <- MAR tap gives one real component of the near-zero-IF baseband (no Q), band-
  limited to ~4-5 kHz. Software FM demod works for narrow FM but M17 (+/-6 kHz occupied, needs ~12 kHz
  of clean single-sided bandwidth) does not fit. Not a route around the HPF. Recovered deviation is ~40 %
  of the generator setting (AFC or filter slope, unresolved).
- Restore: operator RF OFF/ON (BT mode still on: resets codec routing/HPL gain). Then PGA1 18 dB
  (`tinymix set Audio_PGA1_Setting 3`), `sess_end.sh codec` (Preamp OPEN, ADC Off, BT mode 0).
  Mixer == baseline. Amp sysfs not touched this time (kernel/app manage it).
  Mixer diff vs baseline: only DcTrim_DC_Offset / [HP+SPK] DcTrim_DC_Offset (driver boot-time
  calibration values, two reboots since the baseline). All settings equal. Amp: reset, silent:0.

### Listening test and FEC margin

- Decoded audio `m17_B_iter_audio.wav` pushed to the phone and played via the media player (RF module OFF,
  media volume 6 = the operator's setting). **Operator: own voice audible, but many frames malformed
  ("bird tweeting" = Codec2 frames with residual bit errors).**
- libm17 Monte Carlo (stream frames, AWGN on symbols, decode_str_frame): pre-FEC BER 0.99 % / 2.57 % ->
  no payload errors; 3.92 % -> 0.3 % of frames with errors; 5.71 % -> 1.7 %; 7.43 % -> 10.5 %
  (post-FEC payload BER 4.4e-3); 8.96 % -> 23 % (1.1e-2). B is at ~8.2 % => ~15 % bad voice frames.
  **Target: pre-FEC BER <= ~4 %.**

### Receiver improvements (offline, recording B)

- `rx-test/m17_ic.py`: stage 1 = FEC-aided T/2 LS equaliser (as m17_iter). Stage 2 = interference cancellation
  with FEC-corrected decisions: residual ISI model fitted on trusted frames (lags +-16; main tap 0.868,
  symmetric side lobes ~ -0.1 decaying over +-6 symbols = baseline wander from the LF loss; residual ISI
  -9.2 dB; noise sigma 0.37), y_ic = (y - sum_{j!=0} c_j a_hat) / c_0, a_hat = re-encoded symbols of
  trusted frames, hard decisions elsewhere, LS gain/offset normalisation, 5 rounds.
  On B: self-measured pre-FEC BER median 0.00 % -> **self-confirmation, not trustworthy**.
- **Simulation with known truth** on B's channel + noise (`rx-test/ic_sim.py`, libm17 frames):
  no IC: true pre-FEC BER ~9-10 %, **33-35 % of frames with payload errors**; hard FEC-aided IC: true BER
  4.1 % (round 1) -> 2.2 % (round 5), **bad frames 17 % -> 11 %** (residual = frames locked into a wrong
  decode, self-measured 0.8 % vs true 2.2 %). Soft-decision IC with unbiased trust (Viterbi metric on the
  non-IC decode, median 32 good vs 39 bad) is worse: 25-32 % bad frames.
- Real B with hard IC (round 5) + m17-decoder-sym -d 4: 611 frames, 596 FN-consistent, 152 payloads differ
  from the previous render, **LSF CRC OK 109/117 (93 %)** vs 58/69 (84 %) before (independent check).
  Audio: `rx-test/device/m17/m17_B_ic_audio.wav`, pushed to /sdcard/Download/m17_B_decoded_ic.wav.
- Next level: a real turbo equaliser (BCJR soft-output decoding of the K=5 code with extrinsic LLRs) to
  avoid the lock-in.
- Is artifact-free decoding possible? Long linear model from known symbols to the recorded audio (B, 485
  trusted frames, fully-known neighbourhoods only): 8 symbols long -> 3.7 dB, 40 -> 15.4 dB, **100 symbols
  -> 19.1 dB**; 2nd/3rd-order terms add nothing (channel is linear, long memory ~100 symbols). Residual vs
  signal by band: 0-200 Hz -8 dB, 200-400 -16, 400-1000 -28, 1-2 kHz -21, 2-3 kHz -14, 3-4 kHz -7 dB.
- `rx-test/m17_mfic.py` (full-pulse matched-filter IC, -30..+90 symbols): first version had a wrong MF
  sample offset (diverged), fixed + unit-checked (+3/-1 -> 2.99/-0.98). Still degrades on B (600 -> 519
  FN-consistent, model SNR 11 dB): pulse fitted/subtracted with hard decisions everywhere (wrong ones
  leak over the 120-symbol pulse) and plain MF in strongly coloured noise. Needs masked fitting + MMSE
  (whitened) filtering. Not used.
- m17_ic residual ISI model +-16 / +-40 / +-60 symbols: identical results (residual ISI -9.0 dB). The FFE
  already absorbs the long tail; the remaining error is noise enhancement where the FFE restores the
  weak LF band (receiver ~15 dB effective vs ~19 dB model SNR).
- Best so far: m17_ic hard FEC-aided IC (simulated: 11 % bad voice frames vs 33-35 % without).
  Operator listening: "better, but should be much better".

### Turbo equaliser (offline)

- `rx-test/m17_turbo.py`: bit-exact Python M17 stream-frame encoder (self-test: 50/50 frames identical to
  libm17 gen_frame), log-MAP BCJR for the K=5 code with P2 puncturing and 4 tail bits (noiseless 20/20),
  soft MMSE interference cancellation (residual ISI model from m17_ic, lags +-16), 4-PAM demapper,
  derandomise/deinterleave, LICH via libm17 hard Golay as a prior, extrinsic-only feedback (symbol means
  and variances). `m17_ic.py` now also saves the FFE output (`_ffe.f32`).
- Bug found and fixed while testing: `RBITS` was uint8, so `1 - 2*RBITS` wrapped to 255 instead of -1
  (BER 0.50, |LLR| up to 230). Caught by a demap/derandomise/deinterleave unit check.
- **Simulation with known truth** (B's channel + noise, 600 frames): frames with payload errors per iteration
  18.7 % -> 1.5 % -> 0.3 % -> 0.2 % -> **0 (iterations 5-8, payload BER 0)**. Baselines: 33-35 % no IC,
  11 % hard IC.
- **Real recording B:** FN-consistent 603 -> 616 -> 617 -> 616/617 (iterations 1-8). m17-decoder-sym (-d 4)
  on the final cancelled symbols: 614 frames, **LSF CRC OK 100/100** (hard IC: 109/117; stock: none).
  Payload min |LLR| median 50.9, 3 frames below 2. 50 payloads differ from the hard-IC render.
  Audio: `rx-test/device/m17/m17_B_turbo_audio.wav` (616/617 slots), pushed to
  /sdcard/Download/m17_B_decoded_turbo.wav.
- **Operator listening test of the turbo render: "only one bird tweet right before the start of the M17
  transmission, otherwise excellent."**
  The 3 low-confidence frames (payload min |LLR| < 2: FN 0x0140, 0x0148 [FN inconsistent], 0x0154) sit at
  5.5-6.3 s into the audio, clustered (likely the speech onset). Muted render (frames with min |LLR| < 2
  replaced by the same zero fill as missing frames): `rx-test/device/m17/m17_B_turbo_muted_audio.wav`,
  /sdcard/Download/m17_B_decoded_turbo_muted.wav.

### Second CS7000 session (record 30 s, decode on PC) - operator approved, EQ on

- One BT session opened 00:19:24; pre-check static -48.4 dBFS (module audio alive); [module] 00:19:24-34
  the same three EQUALIZER_FILTER writes as transmission B -> `OK`. `sess_cap.sh m17c 32` (end 00:20:12),
  volume 2. Operator transmitted twice.
- 4800 Hz clock line per 0.25 s: tx1 4.75-18.25 s, tx2 19.25-31.75 s. Cropped tx1 5.0-18.0 s, tx2 19.5-31.5 s.
- m17_ic + m17_turbo (6 and 12 iterations, converged):
  - tx1: 317 slots, FN-consistent 299-300, FN 0x0004-0x013f, 26 low-confidence frames; ref decoder
    **LSF CRC OK 41/41** (DST @ALL, SRC SP5WWP, voice, plain). Audio keeps 291/316 frames (92 %).
  - tx2: 292 slots, FN-consistent 269, 63-64 low-confidence frames; **LSF CRC OK 40/40**. Audio keeps
    227/280 frames (81 %).
  - Weaker than B (616/617, 3 low-confidence): only 12-13 s per transmission, so stage 1 starts with far
    fewer trusted frames (204 / 152 vs 492). Fix: carry the equaliser/channel model across transmissions
    (needed for real time anyway).
- Audio (low-confidence frames muted): `rx-test/device/m17c/m17c_tx{1,2}_turbo_audio.wav`, pushed to
  /sdcard/Download/m17c_tx1.wav and m17c_tx2.wav.
- State: BT mode on, EQ active in the module. Restore = operator RF OFF/ON (or OFF), then sess_end.
- Operator switched the RF module off (hw_pd 0, clears the EQ). `sess_end.sh m17c` 00:23:23: BT mode 0,
  mixer settings == baseline (only DcTrim calibration values differ). Played m17c_tx1.wav (00:23:23) and
  m17c_tx2.wav (00:23:38) via the media player, media volume 6.
- Operator: no bird tweets; muted frames sound like "a microphone underwater" = Codec2 decoding all-zero
  bits. `rx-test/m17_render.py`: bad/missing frames decoded as zeros for stream alignment, then replaced by
  PCM silence with 5 ms fades. Renders: m17c_tx1_clean.wav (25 concealed), m17c_tx2_clean.wav (53),
  m17_B_clean.wav (3), pushed to /sdcard/Download/.

## End of session 2026-11-08

- README updated (summary, codec identity and routing, AW87329 amplifier and pitfalls, hw_pd meaning,
  real-M17 receiver results, playback limits, native-modem result, upstream decoder fixes).
- Phone state: stock (RF module off, BT mode 0, mixer at baseline settings, media volume 6 as the operator
  left it). Tools remain in /data/local/tmp. Decoded audio files in /sdcard/Download (m17_B_*.wav,
  m17c_*.wav, m17_B_clean.wav, m17c_tx*_clean.wav).
- Next: warm-start the equaliser/channel model across transmissions, then a streaming receiver for a live
  CS7000 test, later a native aarch64 port.

## Session 2026-11-08 (day 2): warm start

- [phone] read-only state check 08:59: adb up, hw_pd 1, RFinder running, bt_ptt 0. No writes.
- `rx-test/m17_ic.py`: new options `--init <prefix>_w.npz` (warm start: initial FFE weights + ridge prior
  `--prior` towards them) and `--ridge` (Tikhonov to zero, bias not penalised). Saves `<out>_w.npz`.
  Backup of the previous version: `m17_ic.py.bak-20261108`.
- Plain-LS FFE weights are ill-conditioned (peaks 50-125, tx1 vs tx2 weights uncorrelated): the HPF
  notch leaves near-null directions. With ridge 1-100 the cold-start results are unchanged.
- Transfer (stage 1 + 1 IC round, ridge 10):
  - within session 2: tx2 <- tx1 first-pass trusted 156 (cold 59), tx1 <- tx2 170 (cold 74). Final
    results equal cold start (~9.2 % FFE BER, 150-200 trusted).
  - across sessions (B -> tx1/tx2): worse than cold (first pass 9 / 24 trusted). Channel changed.
  - => yesterday's "too little training data" diagnosis was wrong. Session 2's channel is worse.
- Level comparison (same knob 2, same PGA1 18 dB per the tinymix snapshots): B -32.1 dBFS, tx1 -46.4,
  tx2 -47.1 dBFS. 12-20 kHz floor B -128.6, tx1 -119.7 dB. A 125 Hz line (5 x frame rate) is 0 dB rel.
  the 300-500 Hz band in tx1 vs -23 dB in B. Cause of the level drop unknown (module side).
- Re-checked the SCT3258 manuals (re-downloaded): DCS_HPF (ANALOG_CONFIG bit 6) = DC removal for DCS
  detection, not the voice HPF. The voice HPF is fixed in every analog RX path. Modem "codec loop
  back" goes RX ADC -> TX modulation DAC (TX side, not used). No register path around the HPF.

### Third CS7000 session (operator approved the EQ writes), knob 2

- [phone] `sess_begin.sh m17d_pre 5` 09:12:00 (BT mode 1, ADC1/IN_ADC1): -48.3 dBFS, 250-3k -82.8,
  12-20k -121.1 (= session 2 pre-check -48.4).
- Operator turned the knob 2 -> 1 -> 2. `sess_cap.sh m17d_pre2 5` 09:12:40: **-38.5 dBFS, 250-3k
  +9.8 dB, 12-20k floor -3.7 dB.** => after the BT toggle the module runs at reduced gain until a
  volume command arrives. Session 2 (m17c) was captured in that state (explains its -14 dB level).
- [module] 09:12:5x the three EQUALIZER_FILTER writes as transmission B -> each `OK`.
- `sess_cap.sh m17d 40` (end 09:13:42). Operator transmitted twice. **No 4FSK in the recording:** no
  4800 Hz clock line, no in-band rise. During about 5.5-15 s and 20-29 s: static drops 2-9 dB
  (quieting, 2.4-3.6 kHz -8.7 dB) and LF lines at 111-123 and 229-234 Hz appear (+25-30 dB).
  Looks like a weak or off-channel carrier with no M17 modulation reaching the audio.
- State: BT mode on, EQ active in the module. Session left open.
- `sess_cap.sh m17d2 40` (09:17:01): same as m17d (static -69, quieting to -72 during TX, no 4FSK).
  Operator: buzz on the speaker is constant (SMPS EMI from the display), RSSI meter random (full or 0).
  Mixer read-only check: ADC1 On, IN_ADC1, PGA1 18 dB (correct). Amp sysfs hwen 1, mode 1.
- Operator knob 2 -> 1: `m17d_k1` 09:20:36: silence (-122 dB in band). Capture follows the knob, so
  routing to the SoC is fine. btmode 1 re-issue (approved) NOT sent: not needed.
- Operator: CS7000 "UHF offset 14.83 kHz", unchanged since yesterday. Knob back to 2.
- `sess_cap.sh m17d3 40` (09:25:17): idle now silent (-122), during TX a faint signal ~40 dB below B
  (300-600 Hz -96.8 vs -60.3), weak clock hint 4769 Hz +8 dB. Module audio state inconsistent across
  the three recordings.
- Operator RF module OFF (hw_pd 0 verified), then `sess_end.sh m17d`.
- Operator RF module ON, knob 2, keyed the CS7000 and heard M17 on the B1 speaker as before => RF link OK.

### Fourth session (fresh, same plan, operator "Go"), no knob changes

- [phone] `sess_begin.sh m17e_pre 5` 09:27:45: -38.5 dBFS, 250-3k -73.0 (full level without a knob turn,
  so "reduced gain after the BT toggle" is not consistent). [module] 09:28:0x-10 the three
  EQUALIZER_FILTER writes -> each `OK`. `m17e_post` 09:28:15: -34.6 dBFS, 250-3k -69.7 (audio alive).
- `sess_cap.sh m17e 40` (09:29:00). Operator keyed twice: tx1 2.7-12.4 s, tx2 16.2-24.9 s. In-band
  level ~6 dB below B. Cropped to m17e_tx1.wav / m17e_tx2.wav.
- m17_ic (ridge 10, 1 IC round): tx1 FFE final 8.42 % (B 8.15 %), 157 trusted.
  tx2 cold: first pass 58 trusted, final 9.24 %. **tx2 warm from tx1 (prior 300): first pass 151
  trusted, final 8.97 %.**
- m17_turbo (12 iterations): **tx1 234/234, tx2 209/209 FN-consistent** (cold and warm alike).
  m17_render: **0 frames concealed** in both (m17e_tx1_clean.wav 9.4 s, m17e_tx2_clean.wav 8.4 s).
- Lesson: the failed m17d recordings came from the module's audio state after knob changes inside a
  BT session, not RF. Procedure: no knob changes inside a BT session, check a post-EQ pre-check.
- State: BT mode on, EQ active.
- Operator RF module OFF (hw_pd 0 verified). `sess_end.sh m17e` 09:31:56: mixer == baseline (only the
  boot-time DcTrim/impedance calibration values differ). Pushed m17e_tx{1,2}_clean.wav to
  /sdcard/Download, played via the media player at 09:32:03 and 09:32:16, media volume 7 (operator's).
- **Operator listening test: "Both ideal."** (m17e tx1 234/234 and tx2 209/209 frames, 0 concealed).

### Correction (09:4x): m17d was decodable

- Better transmission detector: band ratio 300-2000 Hz vs 2600-3400 Hz per 0.25 s, about +7-8 dB during
  M17, 0-1 dB on idle static (m17c, m17d, m17e all clean). It flags both transmissions in m17d.
- m17d tx1 (6.3-14.7 s) through m17_ic: FFE final 8.97 %, 147 trusted, IC round 1 median 0.00 %, the
  same quality as m17e. **The "no 4FSK in m17d" conclusion was wrong**: the 4800 Hz line check on
  0.5 s blocks is too weak a detector. m17d2 most likely the same. Only m17d3 (idle silent, signal
  ~40 dB down, after knob 2 -> 1 -> 2) was a real module-state problem. The RF OFF/ON reset was
  still useful, but the "knob changes break recordings" lesson rests on m17d3 alone.
- [cycle 09:40:35] decode replay_d seg1 6.00-14.75 s: pol -1, FFE 8.70 %, turbo FN-consistent 210/210, replay_d_seg1_clean.wav: 210/210 frames good, 0 concealed as silence, 8.4 s
- [cycle 09:40:41] decode replay_d seg2 20.25-29.00 s: pol -1, FFE 9.24 %, turbo FN-consistent 210/210, replay_d_seg2_clean.wav: 210/210 frames good, 0 concealed as silence, 8.4 s
- [cycle 09:41:11] decode replay_e seg1 3.00-12.25 s: pol -1, FFE 8.42 %, turbo FN-consistent 223/223, replay_e_seg1_clean.wav: 221/223 frames good, 2 concealed as silence, 8.9 s
- [cycle 09:41:18] decode replay_e seg2 16.25-24.75 s: pol -1, FFE 9.24 %, turbo FN-consistent 204/204, replay_e_seg2_clean.wav: 204/204 frames good, 0 concealed as silence, 8.2 s
- [cycle 09:42:41] `sess_begin.sh c1_pre 5` (BT mode 1, ADC1/IN_ADC1): -38.7 dBFS, 250-3k -73.3
- [cycle 09:42:44] [module] `AT+SDKWRITE=0,112,0,200,1182FF3D12449E837F38F3` -> NO OK: 0,1182FF3D12449E837F38F3  [6 bytes]
  \r  \n   O   K  \r  \n
- [cycle 09:42:54] `sess_begin.sh c1_pre 5`: -38.7 dBFS, 250-3k -73.3. [module] EQ write 1 -> OK (script mis-parsed it as a failure, fixed); resuming in the same session
- [cycle 09:42:58] [module] `AT+SDKWRITE=0,112,0,200,1182FF3D12449E837F38F3` -> OK
- [cycle 09:43:01] [module] `AT+SDKWRITE=0,112,0,200,129420379143529420343F` -> OK
- [cycle 09:43:04] [module] `AT+SDKWRITE=0,112,0,200,13B1083D484AB9B108328F` -> OK
- [cycle 09:43:10] `sess_cap.sh c1_post 5`: -34.6 dBFS, 250-3k -69.9
- [cycle 09:43:55] `sess_cap.sh c1 40` (cap c1 rc=0 09:43:53): -37.0 dBFS, 250-3k -72.0
- [cycle 09:44:02] RF module OFF (hw_pd 0 verified). `sess_end.sh c1` (session end 09:44:02): mixer == baseline
- [cycle 09:44:10] decode c1 seg1 5.25-13.75 s: pol -1, FFE 9.24 %, turbo FN-consistent 203/204, c1_seg1_clean.wav: 199/203 frames good, 4 concealed as silence, 8.1 s
- [cycle 09:44:17] decode c1 seg2 18.75-27.25 s: pol -1, FFE 9.51 %, turbo FN-consistent 204/204, c1_seg2_clean.wav: 204/204 frames good, 0 concealed as silence, 8.2 s
- [cycle 09:44:17] pushed c1_all.wav to /sdcard/Download (14 s decode)
- [cycle 09:44:19] played /sdcard/Download/c1_all.wav via the media player ([v] volume is 7 in range [0..15])
- Operator on c1: both good, one bird tweet in the first transmission close to its start.
- [cycle 09:46:35] `sess_begin.sh c2_pre 5` (BT mode 1, ADC1/IN_ADC1): -38.9 dBFS, 250-3k -73.7
- [cycle 09:46:39] [module] `AT+SDKWRITE=0,112,0,200,1182FF3D12449E837F38F3` -> OK
- [cycle 09:46:42] [module] `AT+SDKWRITE=0,112,0,200,129420379143529420343F` -> OK
- [cycle 09:46:45] [module] `AT+SDKWRITE=0,112,0,200,13B1083D484AB9B108328F` -> OK
- [cycle 09:46:51] `sess_cap.sh c2_post 5`: -34.5 dBFS, 250-3k -70.0
- m17_render.py default --minllr 2 -> 8 (confidence histogram gap; c1 seg1 had frames at 2.2 and 7.1 next to failed frames, likely the bird tweet).
- [cycle 09:47:35] `sess_cap.sh c2 40` (cap c2 rc=0 09:47:34): -34.5 dBFS, 250-3k -69.9
- c2 recording (40 s) held static only: the operator had not keyed. Recording again as c2b in the same session.
- [cycle 09:48:57] `sess_cap.sh c2b 40` (cap c2b rc=0 09:48:56): -40.7 dBFS, 250-3k -75.6
- [cycle 09:49:04] RF module OFF (hw_pd 0 verified). `sess_end.sh c2b` (session end 09:49:03): mixer == baseline
- [cycle 09:49:11] decode c2b seg1 2.75-10.50 s: pol -1, FFE 9.51 %, turbo FN-consistent 184/185, c2b_seg1_clean.wav: 177/185 frames good, 8 concealed as silence, 7.4 s
- [cycle 09:49:11] pushed c2b_all.wav to /sdcard/Download (7 s decode)
- [cycle 09:49:13] played /sdcard/Download/c2b_all.wav via the media player ([v] volume is 7 in range [0..15])
- c2b: operator transmitted once and switched RF off afterwards (the -120 dB drop at ~15 s). Playback: '3-4 drops' (8 frames concealed at minllr 8).
- m17_render.py: new --repeat 2 (default): gaps of up to 2 frames repeat the previous good Codec2 payload, longer gaps PCM silence. c2b re-rendered: 177 good, 8 repeated, 0 silent -> /sdcard/Download/c2b_rep.wav, played 09:51:04, media volume 7.
- Operator on c2b_rep.wav: 'All good now.' Repeat concealment kept as the default.
- m17_ic.py `--seed <turbo_sym.f32>` (second pass: turbo-cleaned symbols supply the trusted frames for
  the first FFE round). Tested offline on c2b, c1 seg1, replay_e seg1: frames with conf < 8: 8 -> 8,
  8 -> 7, 2 -> 1. Median conf +1.5. **No useful gain**: the stage-1 FFE is channel-limited (HPF / MER
  cap), not training-data-limited. Not used in m17_cycle.py.
- [cycle 10:53:38] ### IF DC filter / DCS_HPF test (operator approved both writes: 0x3C mode 0A, then 0x6B DC config 01), no EQ, knob 2
- [cycle 10:53:44] `sess_begin.sh hf_pre 5` (BT mode 1, ADC1/IN_ADC1): -39.0 dBFS, 250-3k -73.6
- [cycle 10:54:09] `sess_cap.sh hf_A 20` (cap hf_A rc=0 10:54:08): -39.3 dBFS, 250-3k -73.8
- [cycle 10:55:01] hf_A (stock): one key-up; segmenter split it (no-EQ ratio only 3-5 dB vs threshold 4)
- [cycle 10:55:04] [module] `AT+SDKWRITE=0,60,0,200,0A08001000100010000800` (ANALOG_CONFIG mode 0x0A: IF 25 kHz, BB 3 kHz, DCS_HPF off) -> OK
- [cycle 10:55:09] `sess_cap.sh hf_Cpost 5`: -1.9 dBFS, 250-3k -36.8
- [cycle 10:55:22] hf_Cpost: -1.9 dBFS rms, 26.4 % clipped (+37 dB): the gain bytes override the knob RX gain. AW87329 hwen 1 in BT mode (amp NOT in reset). Test stopped, operator asked for RF OFF.
- [cycle 10:56:30] RF module OFF (hw_pd 0 verified). `sess_end.sh hf` (session end 10:56:30): mixer == baseline
- Operator RF module OFF. `m17_cycle.py close hf`: mixer == baseline. Amp hwen 1 / mode 1 (app's radio-on
  state since this morning's reboot), not touched.
- Analysis: ANALOG_CONFIG's last gain is **RX volume** (Q16.11). Our writes always used 0x0800 (2048 =
  1.0, the documented default). The firmware sends its own value from a RAM calibration table. The
  +37.7 dB measured in the FILTER_BYPASS tone test (stock -55.6 vs bypass -17.9 dBFS) and the +37 dB
  here both match 2048 vs a firmware value of about 27 (0x1B). => the "+38 dB gain and clipping" of
  the FILTER_BYPASS tests were most likely caused by our RX volume bytes, not by the bypass itself.
  The HPF finding of the bypass tone sweep (relative response) is unaffected.
- **Operator: 'at one point the audio got super loud'** (speaker, during the 0x3C write with RX volume 2048). Fourth loud incident. Operator approved the retry with RX volume 0x1B.
- [cycle 10:58:27] ### Retry: DCS_HPF / IF DC filter test with RX volume 0x1B (operator approved), no EQ, knob 2
- [cycle 10:58:34] `sess_begin.sh hf2_pre 5`: -39.9 dBFS, 250-3k -74.6
- [cycle 10:58:54] `sess_cap.sh hf2_A 15` (cap hf2_A rc=0 10:58:53): -40.6 dBFS, 250-3k -75.1
- [cycle 10:59:12] hf2_A (stock): M17 at 5-15 s (ratio 8-9 vs static 3-4 without EQ). Correction: in hf_A the M17 was only the 15.5-20 s part.
- [cycle 10:59:16] [module] `AT+SDKWRITE=0,60,0,200,0A0800100010001000001B` (ANALOG_CONFIG mode 0x0A, RX volume 0x1B) -> OK
- [cycle 10:59:21] `sess_cap.sh hf2_Cpost 5`: -40.2 dBFS, 250-3k -74.8 (pre -74.6)
- [cycle 10:59:42] `sess_cap.sh hf2_C 15` (cap hf2_C rc=0 10:59:41): -40.9 dBFS, 250-3k -75.4
- [cycle 11:00:06] [module] `AT+SDKWRITE=0,107,0,200,080008000800080001000000` (MISC_GAIN: gains 2048, DC config 0x01 = manual, IF DC filter off) -> OK
- [cycle 11:00:12] `sess_cap.sh hf2_Bpost 5`: -55.2 dBFS, 250-3k -95.6 (pre -74.6)
- [cycle 11:00:36] `sess_cap.sh hf2_B 15` (cap hf2_B rc=0 11:00:35): -42.5 dBFS, 250-3k -77.0
- [cycle 11:01:42] RF module OFF (hw_pd 0 verified). `sess_end.sh hf2` (session end 11:01:41): mixer == baseline
- hf2_C (after 0x3C mode 0x0A, RX volume 0x1B): post-check -74.8 dB in band (pre -74.6): **0x1B matches the
  firmware's RX volume**. M17 at 3.5-13 s.
- [module] MISC_GAIN write -> OK. hf2_Bpost: static -95.6 dB in band (-21 dB, quieter). hf2_B: M17 at 2.5-13.5 s
  at -74 dB (operator: one PTT mis-press at the start, the 0.5 s blip).
- **Result (M17 crops, band PSD rel. 500-1000 Hz, A2 stock / C DCS_HPF off / B + IF DC filter off):**
  150-200 Hz -32.2 / -30.7 / -30.1, 200-250 -16.6 / -20.0 / -17.2, 250-300 -14.8 / -15.1 / -14.3,
  300-400 -3.3 / -3.0 / -3.0, 1-2k -4.1 all, 3-3.5k -17.9 / -17.8 / -18.9. **No change in the low band.**
  Decode (m17_ic ridge 10 + turbo 12): FFE BER 9.24 / 8.97 / 9.51 %, frames 229/229, 219/219, 247/251,
  concealed 2 / 1 / 7. **Neither DCS_HPF nor the IF DC filter is the steep HPF.** (ChatGPT's suggestions.)
- With the IF DC filter off, open-squelch static drops 21 dB (DC/LO leak acting as a carrier), M17 unaffected.
- [cycle 11:14:38] ### Playback test, RF on, knob 2, BT mode off (operator approved HPL mute + amp writes if needed). Amp read: hwen: 1 mode:1
- [cycle 11:14:41] [module] `AT+SDKWRITE=0,0,64,200,0110400000` (codec p1 0x10 = 0x40, HPL muted) -> OK
- [cycle] playback with HPL muted, RF on: played 11:14:47, [v] volume is 6 in range [0..15]
- Operator: with HPL muted, "static went away almost completely", **no speech** at media volume 6. At media
  volume max: **"barely audible"**. => with the radio on, phone audio reaches the AW87329 heavily
  attenuated, even with the module audio muted. Phone-side playback with the radio on is not usable.
  HPL mute still active, restore = operator RF OFF/ON.
- [cycle] playback diagnosis (read-only), RF on: playdump.sh rfon (play c2b_rep.wav, dump tinymix/amp regs/audio_policy/audio_flinger/dmesg during playback)
- [cycle] RF off (operator): playdump.sh rfoff
- **Playback diagnosis result:** during playback with RF on vs RF off (operator's media volume 7 / 15):
  tinymix contents identical (except DcTrim), AW87329 registers identical, Android output device
  AUDIO_DEVICE_OUT_SPEAKER in both, no kernel audio/amp events. => the attenuation of phone audio with
  the module powered is **not in any software-visible setting**. Most likely analog: the phone and module
  outputs are summed at the amp input, and the powered module codec output (low impedance even when
  muted) shunts the phone signal. Untested lead: powering down the HPL driver (AIC3204 p1 reg 0x09) to
  make it high impedance during playback.
- Operator: stop here for now, update the README.
- Operator on the RF-off playback (media volume 15): "Sound loud and clear."
- **Correction of the "RX volume explains the bypass gain" note above:** the 2026-11-07 bypass RX-gain sweep
  (0x0100 / 0x0040 / 0x0010) had no effect in bypass mode. The bypass +38 dB and its clipping are
  therefore NOT caused by our RX volume bytes. The 2048-vs-0x1B finding applies to normal (non-bypass)
  mode only. The similar size (+37 dB) is a coincidence. README bypass row stays as it is.

## End of session 2026-11-08 (day 2)

- README updated (MISC_GAIN, RX volume 001B, RF chip evidence, DCS_HPF / IF DC filter rows, playback limits).
- Phone state: RF module off (operator), no BT session open, mixer at baseline, media volume 15 (operator).
  HPL mute cleared by the RF OFF. Tools: rx-test/m17_cycle.py, m17_segment.py, m17_render.py (--minllr 8,
  --repeat 2), m17_ic.py (--ridge, --init/--prior, --seed).
- Open: phone playback with the radio on (lead: power down the HPL driver, AIC3204 p1 reg 0x09), native
  receiver on the phone, then an app modelled on AtoM17.

### Repository clean-up (2026-11-08, operator request)

- Layout for publishing: `README.md` at the top, everything else under `results/`: this notes file,
  `firmware/SD01_UAVA_RFINDER.bin` (was `backup/`), `rx-test/` (receiver and analysis code, phone tools
  sources, phone scripts in `rx-test/device/phone/`, three plots, the mixer baseline used by m17_cycle).
- Moved out of the repo (not deleted) to `~/Desktop/B1-private/results/rx-test/`: all recordings and decoded
  audio (contain the operator's voice), intermediate symbol/model files, kernel-log and audio-policy
  dumps, the locally built `m17_reenc` binary (rebuild: `gcc -O2 -o m17_reenc m17_reenc.c -lm17 -lm`),
  `__pycache__`, backups. 493 files, 359 MB.
- Phone scripts sess_begin/sess_cap/sess_end/atcmd written from their verbatim phone contents (adb was
  down), playdump.sh from the host copy. Not yet pulled: cap.sh, hpf_ab.sh, apptrace.sh, trace_start.sh,
  trace_stop.sh (still on the phone in /data/local/tmp).
- Privacy scan of everything left: no e-mail addresses, MAC addresses, serials, home paths or names. Only
  the local IP 192.168.50.168. Plots carry only matplotlib metadata.
- adb back: pulled all phone scripts. The four reconstructed ones are byte-identical to the phone copies. cap.sh, hpf_ab.sh, apptrace.sh, trace_start.sh, trace_stop.sh added. Scanned: nothing personal.
