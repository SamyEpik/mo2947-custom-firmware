# Hardware reference for our own firmware

Everything needed to program the MO2947 directly, decoded from the stock firmware on 2026-11-12 and then verified on
the device with our SDK port (`firmware/appotech-sdk`, board `mo2947`). Each topic links to its full report in
`analysis/`, which gives evidence, stock-code addresses and raw register sequences. For new programs, use the SDK APIs
first ([[#Writing and installing a program]]); the registers below matter when the SDK lacks something.

> [!important] Must know
> - **Power hold first.** Our code must latch PMU register `0x40` within milliseconds, or the camera switches off when
>   POWER is released ([[#Minimum start-up for our own code]]).
> - **Never write to the flash without the owner's explicit "go".** Back up the flash first (`./cam dump`).
> - **Keep sector 0 byte-identical and write it last.** Keep the bootstrap (`0x200`-`0x21FF`) unchanged.
> - Peripheral registers are **SPRs**, not memory.

## How to talk to the hardware

- **CPU:** OpenRISC 1000, little-endian, **no branch delay slots**, 144 MHz.
- **Registers:** every peripheral register is an **SPR**, reached with `l.mtspr`/`l.mfspr` (SPR number = `rA | K`).
  None of them is memory-mapped. Peripherals sit at `0x8000`-`0xFFFF` with a stride of 4.
- **Memory:**
  - SDRAM at `0x02000000`, **2 MiB** (stack top `0x021FFFFC`).
  - On-chip SRAM at `0x0000`-`0x43FFF`. The bootstrap and the exception vectors are in `0x0000`-`0x1FFF`.
- **Clock:** the bootstrap leaves PLL1 at 144 MHz (I) but with a register pair that differs from the JT5295 SDK's
  (`0x8858`/`0x885C`). Our SDK build keeps it as it is (`APX_CLOCK_INHERIT`).
- **Calling stock code:** the stock firmware's functions can be called directly (arguments in r3-r8, result in r11).
  Their addresses and signatures are in each report's "API for our firmware" section. Only valid while the stock app is
  still in flash and loaded; our installs replace it, so our firmware does not use this.

Full SPR map: [[analysis/soc_core#11. Full SPR map from code usage]]. Register research from the reference SDKs:
[[analysis/research_registers]].

## Components

| Component | Pins / registers | Key facts | Report |
|---|---|---|---|
| **Power hold** | PMU bus SPR `0x88E0`/`0x88EC`, PMU reg `0x40` | **The first thing our code must do** (sequence in the report). `0x0E` = hold, `0x02` = off | [[analysis/soc_core#3.2 What our firmware must do first to stay on]] |
| Power key | **PB0**, high = pressed | short = event `0x25`, long (~1.5-2 s) = `0x27` | [[analysis/soc_core#3.3 Power key]] |
| Watchdog | SPR `0x880C` | `0x5500` = off, `0x50006` = on (~7 s). The bootstrap leaves it on at `0x5001D` (~1.8 s) | [[analysis/soc_core]] |
| Clocks, timers, interrupts | gates `0x8840/44`, timers `0x9800+0x10·n`, IRQ `0x4800/0x480C` | 100 Hz system tick; `delay_ms` `0x0201F524` | [[analysis/soc_core]] |
| GPIO | `0x8000` data, `0x8040` direction (1 = in), `0x8080` pull-up, `0x80C0` pull-down, `0x8100` alt function; + 4·port (A-E) | full pin list in the report | [[analysis/soc_core#4.1 Every pin the firmware touches]] |
| **Buttons** | ADC channel 3 ladder (centres 0/306/484/658/817, ±29) | see the button map below | [[analysis/ui_input]] |
| LED | **PB5**, high = on | | [[analysis/soc_core#4.1 Every pin the firmware touches]] |
| **LCD** | NV3030B 240×320, **8080 8-bit bus** on PC5-PC12, control on PE1-PE4 (PE2 = D/C), TE on PE3, reset **PB6** | RGB565; init table in the config block at flash `0x7C600`; LCD controller SPR `0xA800`, compositor `0xC800` | [[analysis/display]] |
| LCD (verified on the device) | | The SDK drives it (`src/display_st7789.c`, table `boards/mo2947/panel.inc`). Native (0,0) = top right; landscape (X,Y) → row `319-X`, column `Y`. With PIO writes the stock INVON shows inverted colours: send INVOFF (`0x20`) | [[CONTINUE#Step 1 a one-sector test image (done, works on the device)]] |
| Backlight | **PA6**, PWM timer 2, 4 kHz | duty = brightness×10+20 % | [[analysis/display]] |
| **Camera sensor** | DVP 8-bit on PD2-PD14, MCLK on PD10, I²C on **PD13/PD15** (SPR `0x9090`), PD0/PD1 = power-down/reset | **SuperPix SP0A39** (VGA), I²C `0x42`/`0x43`, chip ID `0x0A39` at regs `0x00`/`0x01`. Read on the device with `CB F2`. Probe entry #6, init table at flash `0x7DA94` | [[analysis/camera]] |
| Capture + JPEG | CSI SPR `0xB000`, JPEG encoder `0xB800` (a second unit at `0xC000`) | VGA frame → hardware scaler → JPEG. Video = AVI MJPEG 30 fps + 16 kHz audio | [[analysis/camera]] |
| SPI flash | SPI0 SPR `0x9000`-`0x927C`, pins PA8/PA10/PA11 | the firmware never writes the status register, so the flash is unprotected | [[analysis/io_storage#2. SPI flash controller (SPI0, SPR 0x9000-0x927C)]] |
| SD card | SD0 SPR `0x9880`, PA0-PA3 + PE10/PE11 | `sd_rw_sector(buf, lba, write)` `0x0203546C`; FAT API `fs_*` | [[analysis/io_storage#3. SD card (SD0, SPR 0x9880-0x989C)]] |
| Speaker | DAC SPR `0x9140`-`0x9160` | `dac_play(rate, buf, len)` `0x02031DB4`, 8-48 kHz, 16-bit PCM | [[analysis/io_storage#4. Audio]] |
| Microphone | ADC SPR `0x9100`-`0x9120`, IRQ 18 | used by video recording | [[analysis/camera]] |
| USB | controller SPR `0xA000`+, PHY `0x9840`/`0xD804`; VBUS = SPR `0x88E0` bit 21 | USB 1.1. Stock: mass storage `0219:3280`, webcam `1908:3282` | [[analysis/io_storage#1. USB device (stock firmware)]] |
| Battery | ADC channel 9 (+ reference channel 11) | levels at 3500/3600/3750/3950/4000 mV; boot refused below ~3250 mV | [[FIRMWARE#Drivers and ioctl commands]] |
| Debug UART | **PA7 TX, 115200 8N1** (UART0 SPR `0x9080`) | `uart_printf` `0x02036E5C`. Needs a wire on PA7 (the case must be opened) | [[analysis/soc_core]] |

## Button map (confirmed on the device)

| Code | Button | Typical action |
|---|---|---|
| `0x1C` | **SHUTTER / OK** | take a photo, start/stop video, confirm |
| `0x1E` | **UP** | previous item, volume +, hold = zoom in |
| `0x1F` | **DOWN** | next item, volume −, hold = zoom out |
| `0x22` | **LEFT** | main menu −1, previous file |
| `0x23` | **RIGHT** | main menu +1, next file |
| `0x25` / `0x27` | **POWER** short / long | back to the main menu / power off |

The owner confirmed every action in this table on the device (2026-11-12).

Events are `value<<16 | code`, where value 0 = press, 1 = repeat, 2 = release. Holding the shutter gives `0x1D`. No stock
page uses `0x1D`, so our firmware is free to use it.

## Minimum start-up for our own code

1. Power hold (PMU sequence), **within milliseconds**.
2. Disable the watchdog (`0x880C = 0x5500`) or feed it regularly.
3. Keep the bootstrap in SRAM `0x0000`-`0x1FFF`: the vectors live there, and the ADC conversion uses its calibration word
   at `0x1E28`.
4. Then turn on only what you need: timer tick, LCD (reset PB6 → init table → backlight PA6), keys (ADC channel 3), and
   the rest.

Running from RAM without flashing is possible through the boot ROM loader (`0xCB` upload + call). **Tested 2026-11-12:**
code uploaded to SRAM `0x2000` runs and returns. **The SDRAM is not reachable in this loader**: any `0xCB` read at
`0x02000000` (256 B or 4 KiB) stalls it. So a RAM-launched program must live in SRAM, or bring the SDRAM up itself.
Details: [[analysis/research_usb_flashing#7.5 Results on our camera]] and
[[analysis/research_usb_flashing#4. Running code from RAM without flashing]].

## Flashing over USB

- **Path:** stock firmware → SCSI `0xDA` → boot ROM loader `1908:3319` → `0xCB` uploads a small SPI payload into SRAM →
  erase / program / verify. The stock firmware's own vendor commands only tune the sensor and cannot write flash.
- **Header:** no CRC needs fixing. The checksum is disabled by header flags, and the word at `+0x4C` is code, not a CRC
  ([[FIRMWARE#Header]]).
- **Keeping a way back in:**
  - Our firmware must also answer SCSI `0xDA`, or return 2 from its entry point. Otherwise later reflashing needs the
    forced loader, which means opening the case and shorting flash pins 2 and 3.
  - Keep the SD update (`DestBin.bin`) as a second way back in.
- **Tested 2026-11-12:** erase (`0x20`, exactly 4 KiB), page program and verify work through the loader with the tbelbek stub
  (owner's camera). The test block `0x3F0000` was left blank; sector 0 was unchanged before and after.
- **Step-by-step plan** (read-only steps first): [[analysis/research_usb_flashing#7.2 Steps (each one read-only unless marked WRITE)]]
- **Raw SPI sequences for the payload:** [[analysis/io_storage#Raw sequences (what a USB flashing payload must do)]]
- **How the dump was done** (the same USB setup): [[FIRMWARE#How the dump was done]]

> [!warning] Flash safety
> - Keep sector 0 byte-identical and write it **last**. A bad sector 0 or bootstrap means no boot; recovery then needs the
>   forced loader (case open, flash pins 2-3 short).
> - Do not use `0x27D000`-`0x3FEFFF` as scratch space: it is the stock photo store.
> - Keep the battery charged and USB connected during a write.

## Writing and installing a program

Verified on the owner's camera (2026-11-12). Code: `firmware/appotech-sdk`, branch `mo2947`; toolchain
`firmware/appotech-sdk/toolchain/install/bin/or1k-appotech-elf-gcc` (GCC 16.2.1, `-mappotech`). Both come from
`./setup.sh`. The step-by-step version for people is the repo's `README.md`.

1. **Write the program** as an SDK example: `examples/<name>/main.c` (copy `examples/mo2947-camera` or `mo2947-demo`).
   The SDK gives you `main()` after start-up (power hold, clocks, caches, SDRAM, watchdog are done). APIs in
   `include/appotech/`: `display.h` (320x240 landscape, RGB565 fill/blit, NV21 DMA), `buttons.h` (keys, LED),
   `camera.h`/`camera_files.h` (SP0A39 preview, capture), `jpeg.h`, `storage.h` (FatFs on the SD card), `audio.h`
   (speaker), `microphone.h`, `battery.h`, `usb*.h` (debug link, mass storage, webcam, USB microphone), `power.h`.
   Call `apx_debug_poll()` (or the module polls) often from the main loop; `printf` goes to the log.
   Optional USB classes: `examples/<name>/features.mk` (`APX_USB_MSC`, `APX_USB_UVC`, `APX_USB_UAC`).
   **Keep a way back in:** leave the SDK's start-up escape (SHUTTER held at power-on → loader) alone, and give the
   program a "hold a key → `apx_bootrom()`" path like the examples, so it can be reflashed without opening the case.
2. **Build** (with `.venv` active: `source .venv/bin/activate`):
   `cd firmware/appotech-sdk && make BOARD=mo2947 EXAMPLE=<name>` → `build/mo2947/<name>.bin`. Limits: the image must
   stay below 0x7A400 bytes (the stock header loads that much); all RAM is 2 MiB (`linker/mo2947.ld` asserts both).
   `boards/mo2947/panel.inc` is generated from `dumps/mo2947_flash_a.bin` (vendor data: keep private, not in git), so
   the camera must be backed up before the first build.
3. **Install** (needs the owner's "go"), camera on and connected over USB, from the repo root:
   ```sh
   ./cam flash plan IMAGE.bin                      # offline: sectors that change
   ./cam flash install IMAGE.bin WRITE             # first time: camera in stock mass-storage mode (SD in, on, then USB)
   ./cam apxd loader                               # later: running SDK firmware -> boot ROM loader ...
   ./cam flash install IMAGE.bin WRITE --loader    # ... and install through it
   ```
   Then disconnect the battery briefly (the loader keeps the camera on with its watchdog off) and switch on.
   Without a running SDK firmware: start the install with `--loader` and hold SHUTTER while switching on.
4. **Debug** over USB: `./cam apxd info|log|spr|mem|clock|sd|camera|photo|rec|tone|battery|cmd`.
   After a failed boot the SDK falls back to the loader; its breadcrumbs (SRAM `0x2F00`) are readable there.

**Ways back:** hold SHUTTER at power-on (runs before any SDK code) → loader; `./cam flash restore WRITE --loader`
→ stock app; last resort: forced loader (flash pins 2-3, [[FIRMWARE#Route B (forced loader, for recovery)]]).

## Still open (needs the device)

Done on 2026-11-12: button map confirmed, sensor = SP0A39, boot ROM = the AX3295B ROM, SRAM code run, flash write test,
own firmware with every component (see above).

- RAM size: 2 MiB works for everything so far (our images use up to `0x021EB400`); `0x02200000`+ is not tested.
- Speaker: not tested (disconnected on the owner's camera).
- A free pin for a UART receive line (wireless module option, [[CONTINUE#Next steps]]).
- Which of PE1 and PE4 is the LCD's WR line and which is CS; whether PD0 is power-down or reset (the board is open, so
  these can be traced with a meter).
