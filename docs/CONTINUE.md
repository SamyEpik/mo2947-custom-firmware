# Continue here

**State at the end of 2026-11-12:** **we can write any program for the camera.** Our SDK firmware runs on the owner's
camera ("unit A") with camera, SD, microphone, battery, display, keys and all USB modes. Guide:
[[HARDWARE#Writing and installing a program]]; install steps for people: the repo's `README.md`.
- **What we know:** [[HARDWARE]] covers pins, registers, the button map, start-up and the USB flashing path.
- **Stock firmware facts:** [[FIRMWARE]] (flash map, header, settings, SD update, how the dump was done).
- **Device test results:** [[analysis/research_usb_flashing#7.5 Results on our camera]].
- This file is the history of the port: what was tried, what broke, what fixed it. Read it before changing start-up,
  clocks, the linker script or the USB modes.

> [!warning] Rules
> - **No flash write without the owner's explicit "go"**, each time.
> - Back up the camera (`./cam dump stock dumps/mo2947_flash_a.bin`) before the first install. The dump holds the
>   owner's photos: keep it private.

## 1. Done on 2026-11-12

| Test | Result |
|---|---|
| Buttons | all actions confirmed by the owner ([[HARDWARE#Button map (confirmed on the device)]]) |
| Sensor | **SuperPix SP0A39** (chip ID `0x0A39`, read with the stock `CB F2` command). Ribbon `XS09B5-X100R` |
| Boot ROM | 32 KiB, identical to the known AX3295B ROM |
| Code from RAM | a small program in SRAM runs and returns through the loader |
| Flash write test | erase (exactly 4 KiB), program and verify work. `0x3F0000` left blank, sector 0 unchanged |
| RAM size | **not measured**: the loader stalls on any SDRAM read |

> [!note] Camera behaviour
> When the loader times out, the camera **switches off**. Switch it on again for storage mode. If it hangs in the loader
> (no USB, screen dark), switch it off with POWER or unplug it.

These tests used a probe tool that is not part of this repo (not needed for firmware work).

## 2. Firmware plan (decided 2026-11-12)

The owner chose: **port matu's SDK and flash our own firmware in place of the stock app**, booted by the stock bootstrap.
- **Sector 0 and the bootstrap never change.** The stock header already loads 0x7A400 bytes from flash `0x2200` to RAM
  `0x02000000`, and the bootstrap calls `0x020004A8`. Our image is linked there. (The SDK's own `spi_boot.py` patches
  sector 0; we do not use it.)
- **Way back in:** returning 2 from the entry enters the boot ROM USB loader (`1908:3319`), as the stock `0xDA` path does.
  Our images do this when SHUTTER is held at power-on. Last resort: the forced loader (flash pins 2-3).
- **Toolchain:** built from the vendored SDK copy (`firmware/appotech-sdk`, owner's exception to the `ext/` rule):
  `or1k-appotech-elf-gcc` 16.2.1. The three toolchain patches were reviewed: target support only.

### Step 1 a one-sector test image (done, works on the device)

The first image (3,584 bytes, only flash sector `0x2000`, not in this repo) proved the path: watchdog off, power hold
(stock sequence), **SHUTTER held at power-on → USB loader**, LED, NV3030B init with the stock table, all six keys. It was
installed from stock mass storage and later through the SHUTTER → loader path, and the stock app was restored with
`restore WRITE --loader`.
- **Colours:** the stock table ends with INVON, so every colour showed inverted; sending INVOFF (`0x20`) after the table
  fixes it (the SDK's `gen_panel.py` drops INVON instead).
- **Orientation:** native pixel (0,0) is the **top right** corner; landscape (X from left, Y from top) → native row
  `319-X`, column `Y` (the stock mapping, verified).

### Step 2 SDK port (done, works on the device)

Board `mo2947` in the vendored SDK (`firmware/appotech-sdk`). Build:
`make BOARD=mo2947 EXAMPLE=mo2947-demo` → `build/mo2947/mo2947-demo.bin` (about 50 KB, 13 flash sectors `0x2000`-`0xE000`).
- `boards/mo2947/`: `board.h` (Action pins; JEDEC `5E4016`/4 MiB; saved ROM stack `0x1A38`; battery calibration
  `0x1E28`; PMU hold `0x0E`; LCD divider 15), `board_memory.h` (2 MiB map), `entry.S` + `early.c` (call target
  `0x020004A8`: the SHUTTER escape from step 1 first, then `apx_spi_entry`), `gen_panel.py` → `panel.inc` (stock NV3030B table
  without INVON; generated from the dump, vendor data, keep private).
- `linker/mo2947.ld`: everything the ROM loads in `0x02000000`-`0x0207A3FF`; bss/heap from `0x0207A400`; LCD DMA
  `0x02100000`; buffers `0x02110000`; codec `0x02190000`; stack `0x021FC000`-`0x021FFFFF`.
- SDK changes: memory map and PMU hold value configurable; GPIO reset/backlight in `display_st7789.c`; Makefile board
  `mo2947` (flat `.bin`, no USB-launch manifest).
- Checked: the bootstrap's saved-stack routine (SRAM `0x340`) matches what the SDK expects; both PLL switch blocks are
  byte-identical to the accepted ones; every opcode also occurs in the stock firmware.
- `mo2947-demo`: colour bars, red square at logical (0,0), key square, LED blink, USB debug link (`1908:3319`
  "JT5295 SDK Debug"), hold SHUTTER 2 s → loader, hold POWER 2 s → off.
- Install: `./cam flash install firmware/appotech-sdk/build/mo2947/mo2947-demo.bin WRITE --loader`
  (writes every sector except `0x2000` first; `0x2000` last).

**Results 2026-11-12 (owner's "go" for both installs):**
- First build: the SDK started (breadcrumbs at SRAM `0x2F00`, read through the loader: `ENTRY`, `PM_AFTER 0x1E…`,
  `STACK_OK 0x4F34`) and then stopped with `FAIL_CLOCK_PREPARE`, code 1: **the AX3295B boot ROM leaves PLL1 at a pair the
  JT5295 SDK does not know.** The SDK then entered the loader, which reset after 3 s: a boot loop.
- Fix: board option `APX_CLOCK_INHERIT` (`src/clock.c`): keep the bootstrap's clock, never switch the PLL, hand it back
  unchanged. `early.c` stores the real values at SRAM `0x2E80` (`'CLK0'`, then `0x8858 0x885C 0x9800 0x9808 0x880C
  0x8840 0x8844 0x8864`); not read out yet.
- Second build: **everything works**: colours, orientation (rotation 3; logical (0,0) top left), all six keys, LED,
  hold SHUTTER → loader, hold POWER → off, start on battery. USB enumerates as **`1908:3319` "JT5295 SDK Debug"**
  (TinyUSB). After the loader times out the camera now restarts into our firmware (the PMU hold stays latched).
- When the camera hangs in the loader with the watchdog off (after an install), POWER does nothing: disconnect the
  battery briefly.

### Step 3 everything in one image (installed 2026-11-12, owner's "go")

`make BOARD=mo2947 EXAMPLE=mo2947-camera` → `build/mo2947/mo2947-camera.bin` (158 KB, 39 sectors `0x2000`-`0x28FFF`).
Changes needed: camera power as stock (PD0 low, PD1 reset pulse then high; LDO `0x8868[12:0]=0x11B0`), all NOLOAD buffers
packed after the image (`linker/mo2947.ld`), FatFs code page fixed to 437 (the dynamic CJK tables are 478 KB).
Keys: SHUTTER photo → SD `MO_nnnn.JPG`; UP tone; DOWN record 2 s + playback + `MO_nnnn.WAV`; RIGHT battery to the log;
hold LEFT 2 s loader; hold POWER 2 s off.

**Results (USB, `./cam apxd`):** all subsystems initialise with 0. Camera: SP0A39 found (ID `0x39`), preview
runs, no I2C errors; `photo` gives a valid 640x480 JPEG. SD: 1.9 GB FAT16, 48 MHz high speed, listing works. Speaker
tone plays. Microphone: 2 s recorded, peak 3490/32767. Battery 4242 mV, USB power detected.

Debug link tool `./cam apxd` (`tools/mo2947_apxd.py`): `info`, `log`, `spr`, `mem`, `clock`, `sd`, `camera`, `photo`,
`rec`, `tone`, `battery`, `cmd`, `loader`. Install without buttons: `./cam apxd loader`, then `./cam flash install IMG
WRITE --loader`; afterwards disconnect the battery briefly (the loader holds the camera with the watchdog off).

### Step 4 USB modes (installed and verified 2026-11-12, owner's "go")

Same image, 195 KB, 49 sectors `0x2000`-`0x32FFF`. UP cycles the USB mode:

| Mode | USB ID | What the PC sees | On the camera |
|---|---|---|---|
| debug link | `1908:3319` | "JT5295 SDK Debug" (`./cam apxd`) | preview, LED on |
| USB drive | `1908:3318` | the SD card, writable (eject before switching back) | preview + blue square, LED fast blink |
| webcam | `1908:3317` | UVC MJPEG 640x480/320x240 at 1-30 fps, USB microphone 32 kHz, SD card read-only | dark red screen, LED slow blink |

Verified: the drive mounts and the files open; webcam picture in a PC camera app; USB microphone records (peak
1457); back to the preview. The webcam buffers overlap the camera app's (`.uvc_ws` over `.jpeg_buffer`), because 2 MiB
does not hold both.

Code: branch `mo2947` of `firmware/appotech-sdk` (from `firmware/appotech-sdk-mo2947.patch`): the port, the USB modes,
and the macOS build fixes.

### Next steps
- Speaker: reconnect it, then test with `./cam apxd tone` (no reflash).
- A real camera app: on-screen text and menus, photos in `PHOTO/`, larger photo sizes, photo viewer, battery icon,
  auto power-off, later video.
- Wireless (the SoC has no radio), options discussed, nothing decided:
  1. Raspberry Pi Zero 2 W on the USB cable: webcam, drive, debug link and reflashing over Wi-Fi; no soldering, no
     firmware change.
  2. Wi-Fi SD card (ez Share): photo transfer only.
  3. ESP32-C3 on the UART (TX = PA7, RX pin still to find; PB1 is a candidate): Wi-Fi/BLE inside the camera; needs
     soldering, its own regulator and firmware on both sides.

## Reference

- Hardware and programming: [[HARDWARE]]
- Stock firmware and flash: [[FIRMWARE]]
- Reports: [[analysis/soc_core]] · [[analysis/display]] · [[analysis/camera]] · [[analysis/ui_input]] ·
  [[analysis/io_storage]] · [[analysis/research_usb_flashing]] · [[analysis/research_registers]]
- External repositories and tools: [[REFERENCES]]
