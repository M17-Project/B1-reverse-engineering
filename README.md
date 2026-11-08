# RFinder B1(-Plus) - reverse engineering

Notes on the RFinder B1-Plus (Android phone with a built-in VHF/UHF DMR radio module), collected to judge whether an M17 encoder/decoder can run on it, as was done on the Unihertz Atom XL ([AtomXL-reverse-engineering](https://github.com/M17-Project/AtomXL-reverse-engineering), [AtoM17](https://github.com/sp5wwp/AtoM17)).

Status labels used throughout:

- **[device]**: observed on a real unit over adb.
- **[static]**: read from the binaries (app, JNI library, module firmware) without running them.
- **[unverified]**: inferred - not yet confirmed by either.

The radio module has been controlled from adb (read-only queries and reversible baseband settings, receive only). The B1-Plus has not transmitted.

## 1. Summary

- The phone talks to the radio module over a plain UART (`/dev/ttyS0`, 38400 8N1) and a small kernel driver (`/dev/intercom_device`). Both device nodes are world read/write on the tested unit. **[device]**
- The module is an **SD01** ("4WUAVASD01 136-174/400-470"). **[device]**
- The module MCU firmware is on the phone as a plain, unencrypted ARMv6-M (Cortex-M0 class) image. **[device]** The baseband is a Sicomm/CML **SCT3258-family** processor: the firmware frames its commands in the SCT3258 packet interface, and documented SCT3258 fields behave as documented when written. **[static] [device]**
- The firmware parses two control protocols **in parallel on the same UART**: the binary `55 AA` protocol (used by Android) and an AT text protocol. `AT+SDKWRITE` writes arbitrary SCT3258 packet fields. **[device]**
- **RX audio reaches the SoC only in "Intercom BT mode"** (ioctl `0x4905` = 1), on PMIC input IN_ADC1, and can be recorded at 48 kHz with tinyalsa. Normally the module drives the speaker amplifier directly. **[device]**
- **The stock analog RX path has a steep high-pass filter at about 300 Hz inside the SCT3258.** It cannot be switched off by any setting found, nor by changing the SD01 firmware. A plain M17 demodulator decodes nothing. **A receiver with an FEC-aided turbo equaliser decodes real M17 from another radio through this path**: all frames of a 25 s transmission, LSF CRC valid in every superframe, clean voice by ear apart from one frame. Transmissions of 7-9 s decode as well, with no per-unit training. See section 10. **[device]**
- **The module has a single audio output (codec HPL) that feeds both the speaker amplifier and the SoC ADC.** While the radio is receiving, the demodulated 4FSK cannot be kept off the speaker without also losing it on the SoC side. See section 10. **[device]**
- Root is not required to control the radio. The tested unit nevertheless has a root adb shell and SELinux in permissive mode. **[device]**

## 2. Device

| Item | Value | Source |
|---|---|---|
| `ro.product.model` | `RFinder-B1-plus` | [device] |
| `ro.custom.build.version` | `K608_DT865_RFinder-B1-plus_20230408_V11.4` | [device] |
| Android / kernel | Android 9, Linux 4.9.117 | [device] |
| SoC | MediaTek MT6765 (per XDA rooting thread), PMIC audio MT6357 (kernel symbols) | [unverified] on this unit |
| adb shell | uid 0 (root) | [device] |
| SELinux | Permissive (`avc: denied ... permissive=1` in dmesg) | [device] |
| Sound cards | one: `mt-snd-card`, 33 PCM devices, no tinyalsa tools on the ROM | [device] |
| Speaker amplifier | AW87329 at I2C 3-0058, with an intercom input mode (`aw87329_intercom_kspk`) | [device] |
| Module audio codec | register map of a TI TLV320AIC3204, see section 8 | [static] [device], part number unverified |
| Radio module | SD01, hardware ID 500 (`ptt_version` = 500) | [device] |
| Module SW version | `persist.intercom.softversion` = `230213` | [device] |
| OEM packages | `com.runbo.sdk_service` (`/system/app/RunboSdkService`), `com.hdqy.runbo.telephony` (`/system/priv-app/HdqyInfoManager`) | [device] |

The hardware platform is Runbo - the original RFinder B1 was a re-badged Runbo E81.

## 3. Rooting

The tested unit already has a root adb shell. For other units, an XDA thread describes rooting the B1-Plus (MediaTek) by patching the official `boot.img` with Magisk and flashing it with fastboot after unlocking the bootloader, and warns that the flash layout differs from a standard MT6765. Back up `nvram`, `nvdata`, `protect1/2` and `proinfo` first. Root is not needed to control the radio.

## 4. Software stack

```
Any Android app
  Java class com.android.walkietalkie.IntercomNative.Intercom   (exact name required)
    System.loadLibrary("intercomjni")
      /system/lib{,64}/libintercomjni.so      (OEM JNI library)
        /dev/intercom_device   ioctl: power, PTT, module ID, audio routing
        /dev/ttyS0             UART, 38400 8N1, binary 55 AA frames (AT text also accepted)
          SD01 module MCU (ARMv6-M) running SD01_UAVA_RFINDER.bin
            SCT3258-family DMR/dPMR/analog baseband (DSP code in its own flash)
            audio codec (TLV320AIC3204 register map), RF
```

- `libintercomjni.so` is listed in `/vendor/etc/public.libraries.txt`, so any app may load it. **[device]**
- The library registers its natives with `RegisterNatives` on the class `com/android/walkietalkie/IntercomNative/Intercom`. An app that declares a class with that name gets the radio API. This is how the RFinder app works, it does not bundle the library. **[static]**
- The library runs inside the calling app's process. On the tested unit `/dev/ttyS0` and `/dev/intercom_device` are `crwxrwxrwx`, so an app can also skip the library and talk to the module directly. **[device]**
- While the RFinder app runs it keeps `/dev/ttyS0` open but does not poll it when idle. It only talks to the module on user actions (channel change, volume knob). Its RSSI meter therefore never moves. **[device]**
- The module answered UART commands from adb only while the RFinder app was running with the module switched on (app ON/OFF button). With the app force-stopped, it did not answer. **[device]**
- The library logs to logcat (tag `Intercom_JNI`, plus `Intercom.java` from the app), including every channel set with its parameters and `nwrite`/`nread` byte counts. **[device]**

### Files

| File | Size | Hash | Notes |
|---|---|---|---|
| `/system/lib/libintercomjni.so` | 114,792 | md5 `dddc995351a5e1d30ff7ccb9ee466c14` | 32-bit ARM, stripped, `.gnu_debugdata` (MiniDebugInfo) intact, so internal function names are recoverable |
| `/system/lib64/libintercomjni.so` | 138,744 | - | 64-bit build, not analysed (assumed equivalent) |
| `/system/bin/SD01_UAVA_RFINDER.bin` | 146,736 | md5 `9276fc823526ad0c2cbd332a14a9d5cc`, sha256 `d7ae8976b94e136ee0ad606f3981c81a020dec7bb3dabddef47c512a6ed5ff0a` | SD01 module firmware, see section 8 |

`/system/etc/firmware/intercom/`, which the library references for other module types, does not exist on the tested unit. **[device]**

## 5. RFinder app (`com.w2cyk.android.rfinder`) [static]

Versions examined: RF1_1.21.M6 (versionCode 972), RF1 2.0 (1000), RF1 2.1d (1063).

- Ordinary third-party app: no `sharedUserId`, no platform signature.
- Detects the radio by checking for `/system/lib64/libintercomjni.so` and matches `Build.MODEL` against strings such as `RFinder-B1-plus`. Branches on module ID (`< 300`, `>= 300`, `>= 500`).
- Uses `setRunboTRXparameters` for channel setup, plus the AMBE data mode for DMR-over-IP.
- Receives PTT/squelch/knob broadcasts: `com.runbo.ptt.key.down/up`, `com.runbo.ptt.sq.start/end`, `com.runbo.knobkey.channel`, and others.
- Bundles `libserial_portdjj.so` / `libpttJni.so` with `/dev/ttyMT2` at 57600, but only for a different product ("S700"), not the B1-Plus.
- References `/sys/bus/i2c/drivers/es8374/3-0010/es8374_i2s_mode` for Bluetooth audio. That node does not exist on the B1-Plus. **[device]**
- RF1_1.21.M6 contains an M17-over-IP client (`ManagerM17`: UDP reflector, phone microphone and speaker, a C++ Codec2 port at 3200 bps). It never uses the radio module and was removed in later versions.

## 6. Kernel driver: `/dev/intercom_device` and sysfs

### ioctls [static], confirmed [device] where marked

| ioctl | Argument | Used by | Meaning |
|---|---|---|---|
| `0x4900` | 1 / 0 | intercomPowerOn / Off, getPowerStatus | module power |
| `0x4902` | 1 / 0 | pttTxStart / pttTxRelease | PTT (a GPIO, not a UART command) |
| `0x4905` | 1 / 0, by value | setBTMode | "Intercom BT mode". 1 routes the module RX audio to the SoC (PMIC input IN_ADC1) and takes the speaker amplifier out of intercom mode. 0 restores the speaker path. **[device]** |
| `0x4906` | `spk_mode`, 3 / 0 | module volume functions | speaker amplifier mode, 3 = "AMP_SPEAKER". The RFinder app issues `0x4906(3)` right before every UART exchange. **[device]** |
| `0x4907` | 1 / 0 | turnOnOffMicrophone | microphone switch |
| `0x4908` | `0x55AA01` | getIntercomVersion | returns module hardware ID (section 7) |
| `0x4909` | n | setPowerLevel, setVolume, others | RF power level and misc |
| `0x490a` | - | getModuleSoftwareVersion | firmware version |

### sysfs [device]

Path: `/sys/bus/platform/drivers/intercom_driver/intercom/`

| Node | Mode | Observed values |
|---|---|---|
| `bt_ptt` | rw-rw-rw- | 0 |
| `hw_pd` | rw-rw-rw- | 1 while the module is powered, 0 after the app powers it down (ioctl `0x4900` = 0, dmesg `Power_Down intercom!`) |
| `mic_power` | rwxrwxrwx | 0 |
| `mic_sw` | rw-rw-rw- | 0 |
| `headset_mic_only` | rw-rw- | 0 |
| `ptt_version` | rw-rw-rw- | 500 |
| `sys_wake_ptt` | rw-rw-rw- | 1 |
| `uart_sw` | rw-rw-rw- | 0 |
| `uart_BB_PC_sw` | rw-rw- | 0 |

The kernel exports `get_intercom_bt_mode`, `intercom_audio_out_ctr`, `intercom_audio_in_ctr`, `intercom_Speaker_Amp_Change` and `aw87329_intercom_kspk`. The driver logs every ioctl and every squelch-pin change to dmesg (`sq_pin 344 ... sq is Press` = squelch open). **[device]**

The device-tree node is `/proc/device-tree/intercom` (`compatible = "mediatek,mt6735-intercom"`). Its pinctrl states are `intercom_default`, `intercom_pdn_output0/1`, `intercom_bt_ptt_output0/1`, `intercom_mic_headset`, `intercom_mic_main`, `intercom_sq_as_eint` (squelch as an interrupt), `intercom_ptt_as_eint`, `intercom_external_uart0/1`, `sys_wake_ptt_pin0/1`, `intercom_dmr_msg_eint`, `uart_sw_pin_enable/disable` and `intercom_mic_power0/1`. **[device]**

The RFinder app also writes `bt_ptt:1` / `bt_ptt:0` to `bt_ptt` to key the radio from a Bluetooth PTT button, and reads the channel knob from `/sys/devices/platform/knob/channel`. **[static]**

### Speaker amplifier (AW87329) [device]

Path: `/sys/bus/i2c/drivers/aw87329/3-0058/`, nodes `hwen`, `mode` (0 off, 1 kspk, 2 drcv, 3 abrcv), `protect`, `reg`, `update`. The reset line is GPIO159 (pinctrl device `ext_amp`, states `aw_state_rst_output0/1`). The driver logs `aw87329 aw_rst level:%d, silent:%d` on every change.

- With the radio on, the RFinder app keeps the amplifier in intercom mode (`spk_mode` 3). Volume knob 0 puts the amplifier in reset.
- In BT mode the kernel holds the amplifier in reset, and Android playback does not wake it.
- Switching BT mode off also leaves the amplifier in reset until the next app event (for example a knob turn).
- **Pitfall:** writing `0` to `mode` latches a `silent` flag in the driver. Afterwards every playback starts with `silent:1` and nothing is heard, including ringtones, until a reboot. Restore `mode` to the value read before a test instead.

Android audio and the module audio are summed at the amplifier input. With the radio on, phone audio is audible only faintly under the module audio. With the radio powered down, phone audio plays normally.

The quick-settings tile "Speaker Mode" (SystemUI, `speaker` tile) only toggles `persist.sys.speaker.mode` ("External" 0, "Phone" 1). It changes no GPIO and no routing that was observed.

## 7. Module identification [static]

`ioctl(0x4908)` returns a hardware ID, the library uses it to pick a protocol and baud rate.

| ID | Module (from log strings) | Protocol, UART |
|---|---|---|
| 100-112 | 2W/3W "BK" modules | AT text, e.g. `AT+DMOGRP=...` |
| 200-202 | NT2209 | `55 AA` binary |
| 300-30x | DM101 | `55 AA` binary, 19200 8N1 |
| 310-317 | DM105 (UHF A-G, VHF A) | `55 AA` binary, 38400 8N1 |
| 400-405 | DM108 AMBE / VITAS | `7E` framed (looks like Spreadtrum diag), 460800 8N1 |
| 420-423 | ZD01AT | AT text, 460800 8N1 |
| 430-433 | ZD05 | 460800 8N1 |
| **500** | **SD01, "4WUAVASD01 136-174/400-470", dual band** | **`55 AA` binary, 38400 8N1** |
| 510 | SD02 (400-470) | `55 AA` binary, 38400 8N1 |
| 520 | LD01 (410-490) | `55 AA` binary |

The tested unit reports 500 (SD01) **[device]**, and `/dev/ttyS0` is already at 38400 baud **[device]**.

## 8. Module firmware: `SD01_UAVA_RFINDER.bin`

### Image [device] [static]

- Version string `SD01UAVA_V02.0_20230213`, also `V2.01.07PN`, `V2.01.07G1`.
- Cortex-M vector table: initial SP `0x20002C38`, reset handler `0x080030D1`. **Load address `0x08003000`** (55 string pointers resolve at that base, none at `0x08000000`). A boot loader presumably occupies `0x08000000-0x08002FFF`.
- ARMv6-M Thumb code: 16-bit instructions plus `bl` only (Cortex-M0 class), readable strings. No encryption or signature was found.
- Initialised RAM comes from a Keil scatter-load table at `0x08026CA4`: 0x20C bytes LZ-compressed at `0x08026CC4` -> RAM `0x200000C0` (decompressor at `0x08003BDC`), plus 0x296C zero-init bytes at `0x200002CC`.

### Baseband chip [static] [device]

Evidence:

- Vocoder name table: `AMBE+2`, `AMBE+2C`, `AMBE3000`, `RALCWI`, `TINGHUA`, `IFENGYU`, `ANDLOGY`. RALCWI is CML Microcircuits' proprietary vocoder.
- Board/vendor strings `Sicomm001`, `BOARD_EVM` (`AT+MODELNAME?` returns `BOARD_EVM`).
- dPMR support throughout (`+DPMRCC`, `digital_tx=dpmr_start`, ...).
- The strings `es8388s` and `eeprom` are device names of the `+CHIP` debug command. The `es8388s` branch is a stub (see below), and the codec register writes in the firmware match a TI TLV320AIC3204, not an ES8388.
- **The firmware builds SCT3258 packet-interface frames** (start bytes `84 A9 61`, field-length table at `0x08026280` with `[id, len+1]` entries matching the SCT3258 manual, for example `0x3C` ANALOG_CONFIG = 11 bytes, `0x70` EQUALIZER_FILTER = 11, `0x18` WORK_MODE = 3).
- Fields written with `AT+SDKWRITE` behave as the SCT3258 manual describes: the RX equaliser (0x70) produced the designed response within about 1 dB, and ANALOG_CONFIG `FILTER_BYPASS` changed the RX chain. **[device]**

So the baseband is an SCT3258-family part (SCT3258TD and SCT3268TD share the interface, the exact part is not confirmed). Per the SCT3258 manual, after reset the host downloads only a fixed 1024-word boot loader over HPI. **The DSP application, including the analog audio filters, runs from the SCT3258's own embedded flash**, not from the SD01 MCU image.

RX analog chain per the datasheet: HPF (pass 300 Hz, stop 255 Hz) -> de-emphasis (6 dB/oct, can be skipped) -> LPF 2.55 or 3 kHz. Documented controls:

- ANALOG_CONFIG (0x3C): mode bits `FILTER_BYPASS`, `BB_CH_SEL`, `SKIP_EMP`, `IF_CH_SEL`, `COMPANDER`, `DCS_HPF`, `ALT_LPF`, plus five gains.
- CTC_PARAM (0x3D): `HPF_CORNER`, 300 or 450 Hz only.
- `DCS_HPF` in ANALOG_CONFIG is documented as a DC-removal filter for DCS detection, not the voice HPF. Every analog RX signal flow in the datasheet passes through the same fixed voice HPF.
- EQUALIZER_FILTER (0x70): three RX or TX biquads at 24 kHz, coefficients in Q2.14.
- MISC_GAIN (0x6B): IQ and CTCSS/DCS gains plus the IF DC filter configuration (auto, or manual on/off). The firmware sends its own MISC_GAIN together with ANALOG_CONFIG.

**The last ANALOG_CONFIG gain is the RX volume (Q16.11).** The manual default 2048 (`0800`) is about 37 dB louder than the firmware's own value. 27 (`001B`) reproduced the stock level within 0.2 dB at knob 2. Any ANALOG_CONFIG write therefore has to carry `001B` (or the value for the current knob position), or the speaker gets very loud. **[device]** In `FILTER_BYPASS` mode the RX volume field has no effect at all.

RF chip: the SD01 firmware sets the DPMR_CALL_OPTION bits "SCT3258 controls the RF chip" and "IQ receive". The MCU never addresses an RF chip itself, its only I2C path is the host pass-through. The SCT3258 manual names the SCT3700 and the RDA1847 as RF partners. Together with the low-IF signal seen at the codec (below), this points to an IQ transceiver such as the SCT3700, with FM demodulation done in the SCT3258. An AT1846S-style chip that demodulates FM itself does not fit. Not confirmed visually. **[static]**

### Module audio codec [static], confirmed [device]

The SD01 MCU does not talk to the codec directly. The SCT3258 initialises it itself (its native codec support covers the TLV320AIC3204 and the WM8758B). The host can pass writes through the SCT3258: packets with TYPE 0x40 are forwarded to the codec over I2C.

- The MCU firmware sends a few adjustments this way, as `[page, register, value]`: page 0 registers 0x56/0x58 (left AGC), page 1 register 0x3B (left MICPGA volume), page 1 register 0x34 (left MICPGA input routing, values 0x80 / 0x40 / 0x20), page 1 register 0x10 (HPL driver gain, 0x40 = HPL muted). This matches the TLV320AIC3204 register map.
- From the host the same write is `AT+SDKWRITE=0,0,64,200,<page><reg><value>0000` (field 0, TYPE 0x40, the five bytes the firmware's own helpers send). **[device]**
- Codec register reads (SCT3258 field I2C_OPERATION, 0x6A, TYPE 0x20) are sent, but the reply never reaches the host. `+SDKWRITE` waits for an echo, a read reply does not match it, and the wait routine clears the received-field queue. The raw `84 A9 61` pass-through also returns no data. **[device]**
- Per the SCT3258 manual, with a stereo codec the left ADC is the microphone, the right ADC the RF chip's signal, the left DAC the RX audio line and the right DAC the VCTCXO port.

Findings with codec writes (all undone by an RF module OFF/ON) **[device]**:

- **HPL feeds both the SoC ADC and the speaker amplifier.** Muting HPL drops the captured signal by about 30 dB, and the speaker goes silent with the amplifier confirmed on.
- **The codec's right input carries the received RF signal at low IF**, one component of a near-zero-IF receiver, hard limited, not FM-demodulated audio. Routing it to HPL (page 1: 0x10 = 0x3A, 0x09 = 0x3D, 0x0C = 0x01, HPL from the right mixer amplifier MAR) shows the carrier at the tuning offset, moving one to one with the generator frequency. Narrow FM can be demodulated from it in software (37 dB SNR at 250 Hz deviation), but the RF chip's baseband filter is only about 4-5 kHz wide, so M17 does not fit in one real channel.

### UART input handling [static], confirmed [device]

The UART receive loop (`0x080076D4`) feeds every byte to two parsers in parallel:

- the `55 AA` frame parser (`0x0801F8A0`), and
- a byte state machine (`0x0800A710`) that recognises `84 A9 61` (raw SCT3258 packet pass-through) and `AT` (AT command line, terminated by `\r`, table walker `0x08013A9C`).

So **AT commands work without any mode switch**, alongside the `55 AA` traffic of the Android library. Replies end in `\r\nOK\r\n`. A reader on `/dev/ttyS0` must loop, because the port is raw with VMIN=0/VTIME=0 and a single `cat` returns end-of-file immediately.

`+UARTMODE=<name>` sets a mode byte (`baseband` -> 1, `character` -> 2, a third name from RAM -> 0). Its effect is not mapped.

### AT commands [static], tested [device] where marked

AT command table: `{name, handler}` pairs from `0x080258A8`.

| Command | Purpose |
|---|---|
| `+TXFREQ`, `+RXFREQ` | frequencies (`%u`, Hz) |
| `+TXPWR` | power, `high` / `low` |
| `+TXSUBAUD`, `+RXSUBAUD` | sub-audio: `tpl` (CTCSS), `+dpl` / `-dpl` (DCS), `csq` (none), both call a shared setter (`0x08006530`) |
| `+SLOT`, `+TDMA`, `+DMRCC`, `+DMRGID`, `+DMRCALLID`, `+DMROWNID` | DMR settings (dPMR equivalents also exist) |
| `+WAVE` | test waveform, arguments include `square` and `triangular` ("wave test" mode) |
| `+CARRIER` | carrier test - events `carrier=ready` / `carrier=lost` |
| `+BER` | bit-error-rate test - event `ber=%d.%d%%` |
| `+SDKWRITE=a,b,c,d,hex` | `a`=0: write SCT3258 packet field `b`, TYPE low bits `c` (0 = write, bit 5 = read request), wait `d` ms, payload = plain hex digits (no prefix/separators, max 100 bytes). Numbers are decimal. Example: `AT+SDKWRITE=0,112,0,200,<22 hex>` writes EQUALIZER_FILTER. **[device]** |
| `+SDKREAD=a,b,c,d` | `a`=2: copy `c` bytes of field `b` from the queue of fields **already reported** by the baseband (no request is sent). ANALOG_CONFIG is not readable per the manual. Replies `+SDKREAD_HEX:` / `_ASCII:` / `_FAIL:` |
| `+SDKIOCTRL=a,b,c,d` | four u16 arguments into a 44-case Sicomm SDK dispatcher (`0x08018F74`), prints `ioctrol_ret_val = %d` |
| `+CHIP=read\|write,<dev>,<hex addr>[,<hex value>]` | debug register access. `<dev>` = `eeprom` (implemented) or `es8388s` (stub, returns without doing anything) |
| `+REGINFO` | info |
| `+REGALL` | **not a register dump**: compares its argument with two strings and returns a status |
| `+MODELNAME?` | `+MODELNAME:BOARD_EVM` **[device]** |
| `+RSSIVAL?` | `+RSSIVAL:-3` with a strong signal (unit unknown) **[device]** |
| `+HELP`, `+REBOOT`, `+RSSILV`, `+VBATVAL`, `+CALLSTATE`, `+PTTCALL`, `+SCAN`, `+TALKAROUND`, `+VOXTHRESHOLD`, `+RMTCTRL`, `+PWRSAVE`, `+SENDSMS`, `+READSMS`, `+ZONE`, `+SVOL`, `+SQL` | misc |

The module also emits status events such as `analog_tx=start`, `digital_tx=dmr_start,call_type=...`, `rx_match=matched`, `carrier=ready`, `ber=...`.

The firmware re-sends ANALOG_CONFIG from its own RAM/EEPROM values during analog channel setup (callers of `0x08013B44`), so a channel reselect or RF module OFF/ON restores it.

### Firmware update

The JNI library contains YMODEM and other updaters for DM101/DM105/DM108/ZD01AT files under `/system/etc/firmware/intercom/`. None of those paths applies to the SD01. For SD01/SD02 the library only logs `UpdateFirmware SD01UAVA` and uses the `sys.update.firmware` property, so the actual SD01 flashing path is outside the library and not yet identified. **[static] [unverified]**

## 9. Binary `55 AA` protocol (SD01 / DM105 family) [static], confirmed [device]

This is what `libintercomjni.so` sends. No checksum was found.

```
Request : 55 AA  LL LL  CC  payload       LL LL = payload length, big-endian (excludes CC)
Response: 5A A5  CC  D0  [data]           D0 = success
```

- Each write is followed by a 300 ms (sometimes 500 ms) sleep and a read with a timeout. `getRSSI` sleeps 500 ms before the write and 100 ms after it. UART access is serialised with a pthread rwlock. The port is configured as plain 38400 8N1 raw.
- Frequencies are 32-bit big-endian. The JNI argument is multiplied by 10 before packing. Example: `18 6C 49 F0` = 409,750,000 Hz.
- On the device: getRSSI `55 AA 00 01 09 01` -> `5a a5 09 d0 ee 87 02 a4 a7 0e`. Analog channel set (20 bytes) and volume (6 bytes) each get a 4-byte reply. **[device]**

| CC | Len | Payload | Function | Sent for |
|---|---|---|---|---|
| `01` | 15 | TX f(4), RX f(4), TX CTCSS/DCS(2), RX CTCSS/DCS(2), bandwidth(1), power(1), squelch(1) | analog channel | DM105, SD01/02 |
| `02` | 17 | TX f(4), RX f(4), TX CC, RX CC, call type, call ID(4, BCD), timeslot, power | DMR channel | DM105, SD01/02 |
| `04` | 4 | radio ID | setUserID | DM105, SD01/02 |
| `05` | 1 | volume | volume | DM105, SD01/02 |
| `07` | 1 | `01` | getRepeaterConnected | DM105, SD01/02 |
| `09` | 1 | `01`, reply carries RSSI | getRSSI | SD01/02 |
| `13` | 2 | value | setFreqErrorReg | DM105 only |
| `15` | 4 | deviation "before"(2), "after"(2) | setAnalogDeviationReg | DM105 only |
| `1B` | 2 | level | setTxTimeoutLimit | DM105 only |
| `1D` | 1 | type 0-3 | setTxLimitMode | DM105 only |
| `21` | 2 | value | setDmrDeviationReg | DM105 only |
| `23` | 1 | 0 / 1 | setSineCarry | DM105 only |
| `27` | 1 | 0 / 1 | setPromiscuousMode | DM105, SD01 not fully decoded |
| `43` | 1 | register ID (`13`, `15`, `21`) | read register | DM105 only |
| `52` | 1 | AMBE data mode | setAMBEDataMode | ID >= 500 |
| `53` / `54` | - | module to host: AMBE stream from air / from mic | readAMBEData | ID >= 500 |

"DM105 only" means the library checks `(id - 310) <= 7` and returns -1 without sending anything on other modules, including the SD01. The SD01 firmware may still accept these opcodes. Sending them directly to `/dev/ttyS0` (read-only `43 xx` first) is untested. `setTxRxSuppress` and `setTxRxLedStatus` are stubs that send nothing.

### AMBE data mode

Used by RFinder's DMR-over-IP feature. Mode 2: the module encodes microphone audio to AMBE and streams it to the host. Mode 4: the host writes AMBE and the module decodes it to the speaker. RFinder moves 108-byte blocks (probably 4 x 27-byte DMR voice bursts) about every 240 ms. This exposes the hardware vocoder only and gives no baseband access, so it is not usable for M17 over RF.

## 10. Paths to M17 over RF

All require keeping transmissions within the operator's licence and testing into a dummy load first.

### A. Raw baseband access

`AT+SDKWRITE` gives direct write access to SCT3258 packet fields, and the firmware also passes raw `84 A9 61` packets through. This reaches the baseband's own features without changing any firmware.

### B. Analog FM path (the Atom XL approach) [device]

#### Recording the RX audio

1. `ioctl(/dev/intercom_device, 0x4905, 1)` (BT mode on).
2. `tinymix`: `Audio_ADC_1_Switch On`, `Audio_Preamp1_Switch IN_ADC1` (PGA1 default 18 dB).
3. `tinycap out.wav -D 0 -d 1 -c 2 -r 48000 -b 16`. Channel 0 carries the radio audio.
4. Restore the mixer (Preamp `OPEN`, ADC `Off`) and BT mode 0.

Without BT mode, every PMIC input carries only idle noise even with the squelch open. The phone's own uplink IIR is only a DC blocker (coefficients +/-0.9956). The volume knob is a gain stage in front of the recording, so keep it fixed while recording.

The module audio level after switching BT mode on is not always the same. It has come up muted, or about 10 dB low until the next volume command, and once a knob change during a recording left it about 40 dB low. A 5 s check recording of the open-squelch static before each capture catches this (about -73 dB/Hz in the 250-3000 Hz band at knob 2 when healthy). An RF module OFF/ON restores it.

#### Measured RX response

Stock path, with or without CTCSS (no difference):

- a **steep high-pass, about -30 dB below 260 Hz** (more than 20 dB/oct),
- a dip of about 5 dB at 1.5-2 kHz,
- an LPF edge at -6 dB at 3.0 kHz and -23 dB at 3.45 kHz,
- no de-emphasis tilt.

The 4FSK content below about 260 Hz ends up under the phone-path noise floor. With random RRC 4FSK at M17 deviation, linear or decision-feedback software equalisation caps at about **12 dB MER** (blind estimate).

Module-side settings tried, all receive only and reversible by an RF module OFF/ON:

| Setting | Result |
|---|---|
| EQUALIZER_FILTER (0x70), 3 RX biquads | works exactly as designed and flattens 290 Hz-3.4 kHz (std 4.4 -> 1.85 dB), but gives **no MER gain** (cannot restore content below 260 Hz) |
| WORK_MODE (0x18) audio decimator loop-back | no effect |
| ANALOG_CONFIG `FILTER_BYPASS` | **partial bypass**. Removes the mid-band droop and the 3 kHz LPF and adds about 38 dB of gain, but **the HPF stays** (response relative to 1 kHz: 100 Hz -40, 200 Hz -23, 300 Hz -12, 500 Hz +1, 2 kHz +2, 3 kHz +5 dB). The output clips in the module below about 1 kHz deviation, the RX volume gain has no effect, and the speaker plays near full scale even with BT mode on. |
| CTC_PARAM `HPF_CORNER` | 300 or 450 Hz only |
| ANALOG_CONFIG `DCS_HPF` off, normal mode (25 kHz IF, 3 kHz LPF, RX volume `001B`) | no change in the low band or in decode quality |
| MISC_GAIN IF DC filter off (manual mode) | no change in the low band or in decode quality. Open-squelch static drops by 21 dB (the uncancelled DC acts like a carrier) |
| Codec routing HPL from MAR | low-IF RF signal instead of audio, too narrow for M17 (section 8) |

#### Real M17

M17 voice from a Connect Systems CS7000 (callsign SP5WWP to @ALL), received through the BT-mode path with the in-chip RX equaliser boosting the low end (low shelf 250 Hz +24 dB, peaks at 1.7 kHz and 3.4 kHz), decoded offline on a PC. Frame counts for a 25 s transmission (about 617 frames):

| Receiver | Frame number consistent | LSF CRC valid | Voice |
|---|---|---|---|
| RRC matched filter, `m17-decoder-sym` | 0 | - | - |
| LS equaliser trained on the sync words | 503 | 0 of 2 assembled | - |
| LS equaliser retrained on re-encoded decoded frames | 588-589 | 58 / 69 | many Codec2 artifacts |
| + hard-decision interference cancellation | 596 | 109 / 117 | fewer artifacts |
| **+ turbo equaliser** | **616-617** | **100 / 100** | **clean by ear except one frame** |

How the receiver works:

- Clock recovery, RRC matched filter and a T/2-spaced linear equaliser. Every frame that decodes is re-encoded with the M17 transmit chain to give its exact 192 symbols, and the equaliser is retrained on those.
- With the symbols known, the channel is linear with a memory of about 100 symbols (20 ms), and a linear model explains the received signal to 19 dB. Nonlinear terms add nothing. The remaining limit is noise enhancement where the equaliser restores the weak band below 260 Hz.
- Turbo equaliser: soft MMSE interference cancellation driven by extrinsic information from a log-MAP (BCJR) decoder of the K=5 convolutional code. Hard re-encoded decisions instead lock about 11 % of frames into wrong decodes (simulation with the measured channel and known data: 33-35 % bad voice frames without cancellation, 11 % with hard decisions, 0 % with the turbo equaliser after 5 iterations).
- Frames with low decoder confidence (smallest payload LLR below 8) are concealed. A gap of one or two frames repeats the previous good Codec2 frame, which is inaudible. Longer gaps become silence with short fades. Codec2 frames of all-zero bits do not give silence, they give low-frequency noise. The confidence threshold matters: at 2, frames with residual bit errors slipped through and were heard as short chirps.

Short transmissions decode as well as long ones. Seven transmissions of 7-9 s, over four sessions, gave 1438 of 1440 frame numbers. Per transmission 0 to 8 frames (at most 4 %) were concealed, all as one- or two-frame repeats, none as silence. Played back on the phone they sounded clean, apart from one chirp heard with the earlier threshold of 2. Decoding takes about 15 s per 40 s recording on a PC.

- The capture level matters more than the transmission length. An earlier pair of 12-13 s transmissions was recorded about 14 dB too low (see the BT mode note above) and lost 8 % and 22 % of frames.
- Training does not need a known signal or a per-unit calibration. Every transmission is equalised from its own sync words and decoded frames. Starting from the equaliser of the previous transmission in the same session makes the first pass much better (151 instead of 58 good frames), but the final result is the same. An equaliser from another day was a worse start than none, because the channel changes. A second equaliser pass trained on the turbo output gains nothing. The remaining errors come from the channel (the HPF), not from too little training data.
- The weights of a plain least-squares equaliser are badly conditioned here, because the HPF leaves almost no signal energy in some directions. A small ridge (Tikhonov) term fixes this without changing the results.
- The equaliser output polarity is not known in advance. The receiver should try both signs.

#### Playing the decoded speech on the B1-Plus

While receiving, the 4FSK audio has to reach the SoC through HPL, and HPL also drives the speaker amplifier (section 8). In BT mode the amplifier is held in reset, and when forced on it plays the module audio. Decoded speech can be summed in from the phone side, but it is much weaker than the module audio, and the 4FSK buzz stays underneath while a signal is present. Muting HPL between transmissions (squelch closed) keeps the speaker silent then.

What works today is record, decode, play: record with the RF module on, switch it off, then play the decoded speech through the normal Android media player. With the module off, the speaker plays phone audio loud and clear.

Playing the speech while the radio stays on is still unsolved:

- With HPL muted the module's static disappears from the speaker almost completely, but the phone audio is then inaudible at media volume 6 and barely audible at maximum.
- During playback with the module on and with it off, the SoC mixer settings, the AW87329 registers and the Android output device (speaker) are identical. The attenuation is therefore not in any software-visible setting.
- Most likely it is analog. The phone and module outputs are summed at the amplifier input, and the powered module codec output loads the phone signal even when muted. Powering down the HPL driver (AIC3204 page 1 register 0x09) during playback might help. Not yet tried.

The TX direction (phone audio into the module's modulator) has not been examined yet.

### C. Modified SD01 firmware

The SD01 image appears unsigned, but changing it cannot remove the analog HPF, because the DSP application runs from the SCT3258's embedded flash. Firmware changes can only automate packet-field settings. The SD01 flashing path is still unidentified.

### D. The SCT3258's native 4FSK modem

DMR is also 4800 sym/s RRC 4FSK, but every digital mode of the SCT3258 found in the packet interface (DMR and dPMR layer 2, call reports, transparent data, BER test) works after the chip's own DMR/dPMR sync detection and FEC. No raw symbol or soft-bit output was found, so M17 symbols cannot be taken from the chip's modem without new DSP firmware.

## 11. Sources

- [M17-Project/AtomXL-reverse-engineering](https://github.com/M17-Project/AtomXL-reverse-engineering)
- [sp5wwp/AtoM17](https://github.com/sp5wwp/AtoM17)
- [M17-Project/M17_Implementations](https://github.com/M17-Project/M17_Implementations), [M17-Project/libm17](https://github.com/M17-Project/libm17)
- [OpenRTX external docs: SCT3258 datasheet, packet interface, analog setup, FAQ](https://github.com/OpenRTX/OpenRTX-external-docs/tree/main/Datasheets%20and%20refmans/SCT3258)
- [CT3258 packet interface](https://cdn.hackaday.io/files/1642237026116832/CT3258_Packet_Interface.pdf), [SCT3258 datasheet v2.0](https://cdn.hackaday.io/files/1642237026116832/SCT3258_datasheet_v2_0.pdf) (hackaday.io)
- [SignalDeck](https://gitlab.com/signaldeckradio-group/signaldeck)
- [XDA: RFinder B1 Classic, B1+ (14) rooting](https://xdaforums.com/t/rfinder-b1-classic-b1-14-rooting.4565191/)
- [Alister Chapman: RFinder B1 review (Runbo E81 base)](https://alisterchapman.com/ham-radio/rfinder-b1-handheld-dual-band-radio-and-phone)
- [CML Microcircuits: SCT3268TD DMR/dPMR processor](https://cmlmicro.com/products/digital-analogue-two-way-radio-products/product/sct3268td-dmr-dpmr-processor-with-analog-mode)
- [Electronic Specifier: CML Sicomm SCT3258TD announcement](https://www.electronicspecifier.com/products/design-automation/pmr-lmr-product-line-up-expanded-with-cml-s-sicomm)
