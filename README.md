# RFinder B1(-Plus) - reverse engineering

Notes on the RFinder B1-Plus (Android phone with a built-in VHF/UHF DMR radio module), collected to judge whether an M17 encoder/decoder can run on it, as was done on the Unihertz Atom XL ([AtomXL-reverse-engineering](https://github.com/M17-Project/AtomXL-reverse-engineering), [AtoM17](https://github.com/sp5wwp/AtoM17)).

Status labels used throughout:

- **[device]**: observed on a real unit over adb.
- **[static]**: read from the binaries (app, JNI library, module firmware) without running them.
- **[unverified]**: inferred - not yet confirmed by either.

No command has been sent to the radio module yet, and nothing has been transmitted.

## 1. Summary

- The phone talks to the radio module over a plain UART (`/dev/ttyS0`, 38400 8N1) and a small kernel driver (`/dev/intercom_device`). Both device nodes are world read/write on the tested unit. **[device]**
- The module is an **SD01** ("4WUAVASD01 136-174/400-470"). **[device]**
- The module MCU firmware is on the phone as a plain, unencrypted Cortex-M image. **[device]** It contains a Sicomm (CML Microcircuits) DMR/dPMR baseband stack with an es8388 audio codec. **[static]**
- The firmware has two control protocols: a binary `55 AA` protocol (used by Android) and an AT text protocol. The AT protocol includes raw register access (`+SDKREAD`/`+SDKWRITE`/`+SDKIOCTRL`) and test modes (`+WAVE`, `+CARRIER`, `+BER`). **[static]**
- Root is not required to control the radio. The tested unit nevertheless has a root adb shell and SELinux in permissive mode. **[device]**

Main open question for M17: how to get a flat 4FSK baseband into and out of the modulator/demodulator. See section 10.

## 2. Device

| Item | Value | Source |
|---|---|---|
| `ro.product.model` | `RFinder-B1-plus` | [device] |
| Android / kernel | Android 9, Linux 4.9.117 | [device] |
| SoC | MediaTek MT6765 (per XDA rooting thread) | [unverified] on this unit |
| adb shell | uid 0 (root) | [device] |
| SELinux | Permissive (`avc: denied ... permissive=1` in dmesg) | [device] |
| Sound cards | one: `mt-snd-card` | [device] |
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
        /dev/intercom_device   ioctl: power, PTT, module ID, audio switches
        /dev/ttyS0             UART, 38400 8N1, binary 55 AA frames
          SD01 module MCU (Cortex-M) running SD01_UAVA_RFINDER.bin
            Sicomm DMR/dPMR baseband + es8388 codec + RF
```

- `libintercomjni.so` is listed in `/vendor/etc/public.libraries.txt`, so any app may load it. **[device]**
- The library registers its natives with `RegisterNatives` on the class `com/android/walkietalkie/IntercomNative/Intercom`. An app that declares a class with that name gets the radio API. This is how the RFinder app works, it does not bundle the library. **[static]**
- The library runs inside the calling app's process. On the tested unit `/dev/ttyS0` and `/dev/intercom_device` are `crwxrwxrwx`, so an app can also skip the library and talk to the module directly. **[device]**

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

### ioctls [static]

| ioctl | Argument | Used by | Meaning |
|---|---|---|---|
| `0x4900` | 1 / 0 | intercomPowerOn / Off, getPowerStatus | module power |
| `0x4902` | 1 / 0 | pttTxStart / pttTxRelease | PTT (a GPIO, not a UART command) |
| `0x4905` | n | setBTMode | "Intercom BT mode", probably audio routing between module and SoC [unverified] |
| `0x4906` | n | module volume functions | volume / audio amplifier |
| `0x4907` | 1 / 0 | turnOnOffMicrophone | microphone switch |
| `0x4908` | `0x55AA01` | getIntercomVersion | returns module hardware ID (section 7) |
| `0x4909` | n | setPowerLevel, setVolume, others | RF power level and misc |
| `0x490a` | - | getModuleSoftwareVersion | firmware version |

### sysfs [device]

Path: `/sys/bus/platform/drivers/intercom_driver/intercom/`

| Node | Mode | Idle value |
|---|---|---|
| `bt_ptt` | rw-rw-rw- | 0 |
| `hw_pd` | rw-rw-rw- | 0 (module powered down) |
| `mic_power` | rwxrwxrwx | |
| `mic_sw` | rw-rw-rw- | 0 |
| `headset_mic_only` | rw-rw- | |
| `ptt_version` | rw-rw-rw- | 500 |
| `sys_wake_ptt` | rw-rw-rw- | |
| `uart_sw` | rw-rw-rw- | 0 |
| `uart_BB_PC_sw` | rw-rw- | |

The device-tree node is `/proc/device-tree/intercom`. Pin names found there include `intercom_sq_as_eint` (squelch as an interrupt), `intercom_dmr_msg_eint`, `intercom_mic_headset`, `intercom_mic_main`, `intercom_external_uart0/1` and `uart_sw_pin_enable/disable`. **[device]**

The RFinder app also writes `bt_ptt:1` / `bt_ptt:0` to `bt_ptt` to key the radio from a Bluetooth PTT button, and reads the channel knob from `/sys/devices/platform/knob/channel`. **[static]**

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
- Cortex-M vector table: initial SP `0x20002C38`, reset handler `0x080030D1`. Loads at `0x08000000` (STM32-style flash base).
- Plain Thumb-2 code with readable strings. No encryption or signature was found.

### Baseband chip [static, part number unverified]

Evidence:

- Vocoder name table: `AMBE+2`, `AMBE+2C`, `AMBE3000`, `RALCWI`, `TINGHUA`, `IFENGYU`, `ANDLOGY`. RALCWI is CML Microcircuits' proprietary vocoder.
- Board/vendor strings `Sicomm001`, `BOARD_EVM`.
- dPMR support throughout (`+DPMRCC`, `digital_tx=dpmr_start`, ...).
- `es8388` / `es8388s` and `eeprom`: an Everest ES8388 audio codec on the module.

This matches CML's "Sicomm Technologies" DMR/dPMR/analog baseband processors (SCT3258TD / SCT3268TD). Per CML, these include an embedded AMBE+2/RALCWI vocoder, a 4FSK modem at 4800/9600, two-point modulation, analog audio processing (compander, CTCSS/DCS), and they use an external audio codec. The exact part number is not confirmed.

Relevance to M17: M17 is also 4FSK at 4800 symbols/s, so the module's RF and codec chain already carries a similar signal for DMR.

### Control protocols

The firmware contains both the binary `55 AA` protocol (section 9) and an AT text protocol. `+UARTMODE` probably switches between them, its argument format is unknown. **[static]**

### AT commands [static]

| Command | Purpose (inferred from strings) |
|---|---|
| `+TXFREQ`, `+RXFREQ` | frequencies (`%u`, Hz) |
| `+TXPWR` | power, `high` / `low` |
| `+TXSUBAUD`, `+RXSUBAUD` | sub-audio: `tpl` (CTCSS), `+dpl` / `-dpl` (DCS), `csq` (none) |
| `+SLOT`, `+TDMA`, `+DMRCC`, `+DMRGID`, `+DMRCALLID`, `+DMROWNID` | DMR settings (dPMR equivalents also exist) |
| `+WAVE` | test waveform, arguments include `square` and `triangular` ("wave test" mode) |
| `+CARRIER` | carrier test - events `carrier=ready` / `carrier=lost` |
| `+BER` | bit-error-rate test - event `ber=%d.%d%%` |
| `+SDKREAD`, `+SDKWRITE` | raw read/write - replies `+SDKREAD_HEX:`, `+SDKREAD_ASCII:`, `+SDKREAD_FAIL:` |
| `+SDKIOCTRL` | raw ioctl into the baseband (`ioctrol_ret_val = %d`) |
| `+CHIP`, `+REGALL`, `+REGINFO` | chip identity, register dump |
| `+HELP`, `+MODELNAME`, `+REBOOT`, `+RSSIVAL`, `+RSSILV`, `+VBATVAL`, `+CALLSTATE`, `+PTTCALL`, `+SCAN`, `+TALKAROUND`, `+VOXTHRESHOLD`, `+RMTCTRL`, `+PWRSAVE`, `+SENDSMS`, `+READSMS`, `+ZONE` | misc |

The module also emits status events such as `analog_tx=start`, `digital_tx=dmr_start,call_type=...`, `rx_match=matched`, `carrier=ready`, `ber=...`.

### Firmware update

The JNI library contains YMODEM and other updaters for DM101/DM105/DM108/ZD01AT files under `/system/etc/firmware/intercom/`. None of those paths applies to the SD01. For SD01/SD02 the library only logs `UpdateFirmware SD01UAVA` and uses the `sys.update.firmware` property, so the actual SD01 flashing path is outside the library and not yet identified. **[static] [unverified]**

## 9. Binary `55 AA` protocol (SD01 / DM105 family) [static]

This is what `libintercomjni.so` sends. No checksum was found.

```
Request : 55 AA  LL LL  CC  payload       LL LL = payload length, big-endian (excludes CC)
Response: 5A A5  CC  D0  [data]           D0 = success
```

- Each write is followed by a 300 ms (sometimes 500 ms) sleep and a read with a timeout. UART access is serialised with a pthread rwlock.
- Frequencies are 32-bit big-endian. The JNI argument is multiplied by 10 before packing. Example: `18 6C 49 F0` = 409,750,000 Hz.

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

**A. Drive the modulator through the module firmware's test/raw interfaces.** `+WAVE` shows the firmware can make the modulator emit a waveform without vocoder input. If `+SDKWRITE` / `+SDKIOCTRL` reach the modem or deviation registers, a direct 4FSK path may be possible. Next step: map these handlers in a full disassembly.

**B. Analog FM plus external baseband audio (the Atom XL approach).** Analog mode, wide bandwidth, no sub-audio, with 4FSK fed through the module's audio input and taken from its audio output. The risk is filtering and emphasis in the analog path. Unlike on the Atom, the firmware implementing that path is readable. Still unknown: how phone audio reaches the module (the `mic_sw` / BT-mode routing, ioctl `0x4905`).

**C. Native M17 mode in modified module firmware.** The image appears unsigned and the hardware already contains a 4FSK modem. This is the most work and needs the SD01 flashing path identified and full backups made first.

## 11. Sources

- [M17-Project/AtomXL-reverse-engineering](https://github.com/M17-Project/AtomXL-reverse-engineering)
- [sp5wwp/AtoM17](https://github.com/sp5wwp/AtoM17)
- [SignalDeck](https://gitlab.com/signaldeckradio-group/signaldeck)
- [XDA: RFinder B1 Classic, B1+ (14) rooting](https://xdaforums.com/t/rfinder-b1-classic-b1-14-rooting.4565191/)
- [Alister Chapman: RFinder B1 review (Runbo E81 base)](https://alisterchapman.com/ham-radio/rfinder-b1-handheld-dual-band-radio-and-phone)
- [CML Microcircuits: SCT3268TD DMR/dPMR processor](https://cmlmicro.com/products/digital-analogue-two-way-radio-products/product/sct3268td-dmr-dpmr-processor-with-analog-mode)
- [Electronic Specifier: CML Sicomm SCT3258TD announcement](https://www.electronicspecifier.com/products/design-automation/pmr-lmr-product-line-up-expanded-with-cml-s-sicomm)
