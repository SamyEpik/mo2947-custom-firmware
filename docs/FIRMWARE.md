# Stock firmware and flash

Facts about the device, the stock firmware `Y200-V1.1-20251020` and the 4 MiB flash. Organised by topic. Only verified
facts and clearly marked guesses are kept. Register-level details are in [[HARDWARE]] and `analysis/`.

> [!warning] Private data
> A flash dump (`dumps/mo2947_flash_a.bin`) holds the camera's stored photos from flash `0x27D000` on, and the whole
> vendor firmware. Keep dumps private: never commit, print or publish them, and never copy image data from that area.

## Device and board

| Part | Marking | Meaning |
|---|---|---|
| SoC | Jinrixin (JRX) logo, `2605T` | **AX3295B family** (app build target string `3295B_KIDS_CAM`). `2605T` is probably a date/lot code |
| Board | `Y200-DV04-VO1 2025.09.28` | board name and design date. `Y200` matches the firmware version |
| SPI flash | `C25VQ32ET HKZ2603` | 4 MiB SPI NOR. **JEDEC `5E 40 16`** (Zbit ZB25VQ32 or a rebadge) |
| LCD | `20086FN`, `IB 6749` | 2.0" panel, controller **NV3030B**, 240×320 (from the firmware) |
| Camera module | `XS09B5-X100R` (ribbon) | **SuperPix SP0A39** VGA sensor: chip ID `0x0A39` read on the device on 2026-11-12 ([[analysis/camera]]) |
| Charger | `CL4056D 5LD64V` | ChipLink 1 A linear Li-ion charger. The red and blue LEDs are probably its CHRG/STDBY outputs |
| Battery | `BJY602030` | 3.7 V 300 mAh 1S LiPo pouch |
| Other | `ZJ2511` | unknown. Which chip carries it is not recorded |
| I/O | USB-C, microSD, speaker, microphone, red + blue LED, 6 buttons | buttons: power (also back), shutter (also OK), up, down, left, right |

- Firmware version (Menu → Version): `Y200-V1. 1-20251020 European Union`. Resource 0 holds `Y200-V1.1-20251020`.
- Other build strings: `3295B_KIDS_CAM`, `JPY-V3.0-0329-030A`, USB SDK stamp `20160418V1.000`.
- The camera has **no radio** (the EU DoC does not list the Radio Equipment Directive).
- Opening: two Phillips screws at the bottom corners of the back. The LCD, sensor and battery cables are short. Do not
  short or bend the LiPo pouch.

## SoC family

- Names for the same chip line: **Jinrixin** (current maker), **Buildwin** (USB strings), **AppoTech** (SDK, "AX" names).
  **JT5295** is a marking on related cameras with the same firmware and boot ROM.
- CPU: OpenRISC 1000, **little-endian, no branch delay slots**, `l.jal` links PC+4. 144 MHz. `l.mul`/`l.div` work.
- The flash is **not memory-mapped**. The boot ROM copies the app into SDRAM, and all code runs from RAM.
- The boot ROM (at `0x00100000`) has a **USB loader** (`1908:3319`). It can read and write the flash without a programmer.
- The early guess "HX-Tech HX3302B" is wrong. HX330x material in old notes is background only.

## USB modes

| Mode | How to get it | USB ID | Notes |
|---|---|---|---|
| Webcam only | camera **off**, plug in USB. Yellow camera icon, charging | `1908:3282` | UVC + audio (interfaces 0-3). **No mass storage**, so `0xDA` cannot be sent |
| **Mass storage** | **SD card in, camera on first** (live view), then plug in USB | **`0219:3280`** | mass storage on **interface 4**. Vendor SCSI commands work here |
| Boot ROM loader | from mass storage, vendor SCSI `0xDA` | **`1908:3319`** | `BLDR v1.00`, INQUIRY `BuildWin Video050Loader`. Appears about 0.02 s after `0xDA`. When its watchdog fires (~2-3 s without traffic) the camera **switches off**; switch it on again for stock mode |
| Forced loader | flash pins 2-3 shorted at power-on, or an erased header | `1908:3319` | re-enumerates in a 2-3 s loop (watchdog). Not tried on this camera |

- USB strings in both stock modes: `Generic` / `GENERAL - AUDIO` / `20160418V1.000`. INQUIRY: `BuildwinMedia-Player 1.00`.
- `1908:3283` (mass storage + webcam) exists in the firmware but is used only by other SDK builds.
- The stock vendor commands (`0xCB F0/F1/F2`, `0xCD`) only tune the sensor. They do not give RAM or flash access.
  Details: [[analysis/io_storage#1. USB device (stock firmware)]].
- Loader protocol (`0xCB` read, write, call): [[analysis/research_usb_flashing#1. The loader protocol]].

## How the dump was done

The owner's two dumps were made over USB with route A. Nothing was written to the camera. Use the same setup for the
USB flashing work.

### Preparation (once)

`./setup.sh` installs everything (pyusb in `.venv`, `ext/luxorparts-kdc030d-re`, on Linux the udev rule). Run the tools
through `./cam` (`./cam dump …` = `tools/mo2947_dump.py`); on macOS it adds the sudo that libusb needs to detach the
mass-storage driver.

Charge the camera. Use a USB **data** cable, directly on the PC (no hub).

### Route A (used)

1. SD card in, camera on, then plug in USB. Check with `./cam dump info` (sends nothing): it must show
   `0219:3280` with a mass-storage interface.
2. Unmount the camera's SD volume if the desktop mounted it (Linux: `udisksctl unmount -b /dev/sdX1`; macOS:
   `diskutil unmountDisk /dev/diskN`, see `diskutil list`).
3. Run:
   ```sh
   ./cam dump stock dumps/mo2947_flash_a.bin
   ```
4. The tool sends INQUIRY (must be `Buildwin Media-Player`), then `0xDA`. It checks the loader against the known boot ROMs,
   uploads the read-only SPI payload (tbelbek `flstub`, 2960 bytes, SRAM `0x2000`, request block `0x3400`), reads the
   JEDEC ID, and reads the chip **twice** (`OUT.bin` and `OUT.bin.pass2`). It takes a few minutes.
5. Check: `shasum -a 256` (or `sha256sum`) of both passes must be equal, and `xxd OUT.bin | head -1` must show `BLDR` at offset 4.

`tools/mo2947_dump.py` wraps tbelbek's `kdc_dump.py`/`kdc_run.py`/`flstub.py` (set `KDC_REPO` if the clone is elsewhere).
It only sends SPI `0x9F` (JEDEC) and `0x03` (read). A power cycle always returns the camera to the stock firmware.

### Route B (forced loader, for recovery)

Use this only if the stock firmware no longer reaches its mass-storage mode. It needs the case open.

```
        +----u----+
 /CS  1 |o        | 8  VCC        SOIC-8, pin 1 = dot
 DO   2 |         | 7  /HOLD      check: pin 4 = GND, pin 8 = 3.3 V when on
 /WP  3 |         | 6  CLK
 GND  4 |         | 5  DI
        +---------+
```

1. Camera off, USB unplugged. Start `./cam dump forced OUT.bin` (waits up to 2 min).
2. Short **pin 2 (DO) to pin 3 (/WP)** with fine tweezers and hold.
3. Plug in USB (press power for about 1 s if needed). Watch for it (Linux: `watch -n0.3 'lsusb | grep 1908'`; macOS: `system_profiler SPUSBDataType`).
4. When `1908:3319` appears, **remove the short at once**. The tool retries the JEDEC ID until the short is gone.

In a forced boot the SDRAM is not calibrated: use SRAM payloads only, 512-byte transfers.
Source: matu6968 `docs/FLASHING.md`. Full recovery list: [[analysis/research_usb_flashing#6. Recovery procedures]].

### Route C (last resort)

Desolder the flash and read it with an SPI programmer. In-circuit reads are unreliable on this family, because the SoC
also drives the flash bus.

### Results (the owner's two cameras)

| | Unit A | Unit B (a second camera) |
|---|---|---|
| File | `dumps/mo2947_flash_a.bin` (+ `.pass2`) | `dumps/mo2947_flash_b.bin` (+ `.pass2`) |
| Date | 2026-11-11 | 2026-11-12 |
| SHA-256 | `3e5642dc50ef16198e28a4bad1de36f133875865f114f0183bb1a6b39d80a240` | `d20631bb855b6ee5f89e4f4d4e2c13aa96726d40fc22a92c712b5b0d4a3ec4b1` |
| Pass 1 = pass 2 | yes | yes |
| JEDEC ID | `5E 40 16`, status `0x0` | `5E 40 16`, status `0x0` |

Both units are identical in `0x0`-`0x27BFFF`; only settings and stored photos differ. Another camera's dump should match
there too; if its header or bootstrap differs, stop and check before installing anything.

> [!todo] Backup
> Copy your dump off the computer. It is the only way back to the stock firmware.

> [!note] Unit A since 2026-11-12
> Unit A no longer runs the stock app: flash `0x2000`-`0x32FFF` holds our firmware (`mo2947-camera`). Sector 0, the
> bootstrap tail, the config block, resources and settings are unchanged. `tools/mo2947_flash.py restore WRITE` writes
> the stock app area back from `dumps/mo2947_flash_a.bin`.

## Two-unit comparison

**7,919 bytes differ, all in `0x27C000`-`0x27FFFF`.** `0x000000`-`0x27BFFF` is byte-identical on both units.

| Range | Same? | Content |
|---|---|---|
| `0x000000`-`0x27BFFF` | **yes** | header, bootstrap, app, config block, resources |
| `0x27C000`-`0x27C1FF` | no (4 words) | settings block |
| `0x27D000`-`0x27DFFF` | no (7 bytes) | photo store index: A has 1 entry, B has 0 |
| `0x27E000`-`0x27FFFF` | no | A: its stored 320×240 JPEG. B: erased |
| `0x280000`-`0x3FFFFF` | yes | `0xFF` on both |

- The read path is confirmed: two chips gave the same 2.5 MiB firmware area bit for bit.
- The image is not per-unit: no serial number, calibration data or unique ID in the flash.
- **Either dump can restore the firmware part of either camera.** For an exact restore, use the camera's own dump.
- Analysis and patches apply to both units. The dumps cannot tell if both units have the same sensor.

## Flash map

| Flash range | Content | RAM address |
|---|---|---|
| `0x000000`-`0x0001FF` | **header** (sector 0), with the header hook code from `+0x4C` | — |
| `0x000200`-`0x0021FF` | **bootstrap**: vectors, IRQ entry, SDRAM init, `adc_to_mv`, `SFAT` table at SRAM `0x100` | SRAM `0x0000`-`0x1FFF` |
| `0x002200`-`0x07C5FF` | **application** (`0x7A400` bytes) | `0x02000000`-`0x0207A3FF` (RAM = flash + `0x01FFDE00`) |
| `0x07C600`-`0x07DDFF` | **hardware config block**: LCD entry `nv3030b` at `0x7C600`, sensor block at `0x7CC9C` (7 probe entries + init tables) | read at run time |
| `0x07DE00`-`0x27BB2F` | **resource area**: 74-entry directory, then the assets (UI images, fonts, sounds). `0x27BB30`-`0x27BBFF` = `0x00` padding | — |
| `0x27C000`-`0x27C1FF` | **settings block** (128 u32, word 127 = checksum) | RAM copy `0x0207A3A0` |
| `0x27D000`-`0x27DFFF` | **internal photo store index** | RAM copy `0x0207F4C0` |
| `0x27E000`-`0x3FEFFF` | **internal photo store** slots (40 KB each). Mostly blank, but it is live store space | — |
| `0x3FF000`-`0x3FFFFF` | blank, outside the store | — |

> [!warning] Blank is not free
> `0x280000`-`0x3FFFFF` is blank on both units, but most of it is the free part of the photo store. Do not use it for our
> own data while the stock firmware runs. The planned write test uses `0x3F0000` and leaves it erased again.

Config block details: [[analysis/display#3. Hardware config block (flash 0x7C600)]] and
[[analysis/camera#3. Probe sequence and how to find the fitted sensor]].

## Header

Decoded from the boot ROM's header parser. Full table: [[analysis/research_usb_flashing#3. Header checksum and CRC (what the boot ROM checks)]].

| Offset | Value | Meaning |
|---|---|---|
| `+0x02` / `+0x04` | `0x0002` / `BLDR` | required magic |
| `+0x09` | `0x01` | load record at `+0x20` |
| `+0x0A` | `0x05` | flags: bit 0 = run the header hook, **bit 2 = skip the header sum** |
| `+0x10` | `"01234567"` | not read by the ROM |
| `+0x18` / `+0x1C` | `0x3EF` / `0xFEF` sectors | resource area start `0x7DE00`, length `0x1FDE00` (read by the app only) |
| `+0x20` / `+0x24` / `+0x28` | `0x02000000`, `0x11`, `0x3D2` | app load address, start sector (`0x2200`), sector count (`0x7A400` bytes) |
| `+0x2C` | 0 | entry = SRAM 0 (the bootstrap) |
| `+0x30` | `0x01234567` | expected SPI CRC, **not enforced** (byte `+0x39` bit 7 is clear) |
| `+0x38` | `0x800` | ROM SPI flag byte `+0x39 = 0x08` |
| `+0x3C`-`+0x48` | `0x0313C00F`, `5`, `0x00080010`, `0x203` | SPI parameters; `+0x40` = SPI clock divider |
| `+0x4C`-`+0x1D7` | code | **header hook**: PLL, UART, timer setup, loads the bootstrap, SDRAM init. Do not change |
| `+0x1FE` | `55 AA` | signature |

> [!important] No checksum to fix
> The header sum check is off and the CRC is not enforced. The word at `+0x4C` (`0xD7E177F4`) is the first instruction of
> the header hook, not a checksum. Our header sum is 199, so **never clear flags bit 2**. Keep sector 0 byte-identical.

Bootstrap and header hook in detail: [[analysis/soc_core#9. Bootstrap (flash 0x200) and header hook]].

## Application

### Start-up and task system

| Address | Name | What it does |
|---|---|---|
| `0x020004A8` | `app_main` | `app_init()` → settings → **`upgrade_DestBin()`** → `task_switch(6 Main menu, or 9 USB if USB is connected)` → `task_run_loop()`. Returns 2 to the bootstrap after task ID 10 (this enters the USB loader) |
| `0x020000BC` | `app_init` | power hold first, then system init, tasks, timers, drivers ([[analysis/soc_core#2. Start-up path (who runs what)]]) |
| `0x02000000` | `task_register_all` | 10 × `task_register` |
| `0x02006DC0` | `task_init` | clears the table; current = 0, requested = previous = `0xE` |
| `0x02006E48` | `task_register(id, desc)` | `id <= 13` → `table[id] = desc`, table `0x0207E74C` (14 slots) |
| `0x02006EE0` | `task_switch(id, arg)` | `desc->arg = arg`; previous = current; requested = id. Refused while requested == 1 |
| `0x02006F74` | `task_run_loop` | until requested == 10: `exit()` old task, `enter(arg)` new task (unknown ID → task 1), then `service(arg)` in a loop |
| `0x0207E748` | `g_task_active` | pointer to the running descriptor |

`0xE` = "no request". **ID 10 = leave the task loop.** Task 1 (Power Off) is the fallback.
Descriptor = 20 bytes `{char *name, u32 arg, enter, exit, service}`.

| ID | Name | Descriptor | enter | exit | service |
|---|---|---|---|---|---|
| 1 | `Power Off` | `0x020778D8` | `0x0200B5C4` | — | — |
| 2 | `Video Recorde` | `0x02077948` | `0x0200D308` | `0x0200CB90` | `0x0200C980` |
| 3 | `Photo Encode` | `0x020772D8` | `0x02007C34` | `0x020070E0` | `0x020071AC` |
| 4 | `Play Back` | `0x02077614` | `0x0200998C` | `0x020093C0` | `0x02009BA8` |
| 5 | `Audio Player` | `0x020788EC` | `0x02012320` | `0x0201237C` | `0x020123A0` |
| 6 | `Main menu` | `0x02078C28` | `0x02013F90` | `0x0201404C` | `0x02013F7C` |
| 7 | `Game menu` | `0x02078DC0` | `0x0201CA9C` | `0x0201CB18` | `0x0201CA88` |
| 8 | `setting menu` | `0x02078CFC` | `0x020148F0` | `0x020148DC` | `0x020148C8` |
| 9 | `usb device` | `0x02077934` | `0x0200C740` | `0x0200C680` | `0x0200C6A8` |
| 11 | `Game` | `0x02078DAC` | `0x0201C5B4` | `0x0201B0A0` | `0x0201C27C` |

What each task does and its key handlers: [[analysis/ui_input#4. Task flow (V)]].

### Drivers and ioctl commands

Device table pointer `g_dev_table` at `0x02076D80`. Entry = 24 bytes `{char name[12], init, ioctl, priv}`.
`dev_ioctl(dev, cmd, arg)` `0x02002538` calls `g_dev_table[dev-1].ioctl`.

| Entry | Name | init | ioctl |
|---|---|---|---|
| `0x02076D90` | `battery` | `0x02002B74` | `0x020028A8` |
| `0x02076DA8` | `sd-card` | `0x0200267C` (empty) | `0x0200284C` |
| `0x02076DC0` | `lcd` | `0x02002804` | `0x02002AA0` |
| `0x02076DD8` | `usb` | `0x020027DC` | `0x02002794` |
| `0x02076DF0` | `led` | `0x02002750` | `0x02002A50` |
| `0x02076E08` | `cmos-sensor` | — | `0x02002D0C` |
| `0x02076E20` | `ad-key` | `0x02002694` | `0x02003058` |

| Cmd | Device | Meaning |
|---|---|---|
| `0x20000001` | sd-card | card present → `*arg` 0/1 |
| `0x20000002` | usb | USB (VBUS) connected → `*arg` |
| `0x20000003` | battery | level 0-5 → `*arg` |
| `0x20000004` | lcd | backlight on/off (PA6, PWM channel 2, 4 kHz, duty `brightness*10+20` %, brightness = settings slot 8) |
| `0x20000013` | lcd | read the backlight state |
| `9` | ad-key | read a key event |
| `0x2000000D` | ad-key | raw power key (PB0) |
| `0x2000000F` | cmos-sensor | probe the sensor and start the capture pipeline |
| `0x20000015` | led | LED on/off (PB5) |

- **Battery:** 16-sample average of ADC channel 9 (battery) and channel 11 (reference), converted to mV, +20 mV. Levels
  from `battery_mv_thresholds` (`0x02062C94`): **3500, 3600, 3750, 3950, 4000 mV** → level 0-5, 30 mV hysteresis. At boot,
  `battery_init` fails below about **3250 mV** without USB power, and the camera switches off.
- **Buttons:** one ADC ladder on channel 3 plus the power key on PB0. Map: [[HARDWARE#Button map (confirmed on the device)]].

### Useful stock functions

| Address | Name | Notes |
|---|---|---|
| `0x020360B4` | `spi_flash_read(addr, buf, len)` | SPI `0x03` |
| `0x020361FC` | `spi_flash_write(addr, buf, len)` | 256-byte pages via `spi_flash_page_program` `0x0203617C` |
| `0x02036298` | `spi_flash_sector_erase(addr)` | SPI `0x20`, 4 KiB |
| `0x02036368` | `spi_flash_chip_erase()` | SPI `0xC7` |
| `0x02048F84` | `res_get_flash_addr(index)` | flash address of resource *n* |
| `0x02006114` | `get_fw_version_string()` | resource 0, fallback `3295B_KIDS_CAM` |
| `0x0205A5A8`… | `fs_mount`, `fs_open` `0x0205A680`, `fs_read` `0x0205A7C0`, `fs_seek` `0x0205A8B0`, `fs_size` `0x0205ABAC`, `fs_close` `0x0205A748` | FAT file API (handles) |
| `0x0203785C` / `0x0203792C` | `mem_alloc(size, align)` / `mem_free` | heap, at most 32 blocks |
| `0x020033B8` | `settings_get_label(slot)` | the stored `0x81000000 \| n` value |
| `0x02005868` | `settings_get_value(slot)` | label → number: "1"-"8" → 1-8, "1 Min" → 60 s, sizes → `W<<16 \| H` |

More: the "API for our firmware" section of each report in `analysis/`.

## Settings block

Flash `0x27C000`, 128 little-endian u32 words. The rest of the sector is `0xFF`.
Write path: [[analysis/ui_input#5. Settings write path (V)]].

| Word | Content |
|---|---|
| 0-3 | `2025, 1, 1, 4`: the default date. The date/time editor sets only the RTC, so these never change |
| 4-6 | 0 |
| 7-32 | setting values, each `0x81000000 \| n`, where **`n` = string-table index of the chosen option** (resource 59) |
| 33-126 | 0 |
| 127 | **checksum = 32-bit sum of words 0-126** (if the sum is 0, the firmware uses `0xAA55AA55`). Unit A `0x1A000BD8`, unit B `0x1A000BFD` |

On a bad checksum the firmware loads the defaults and saves them. The defaults are exactly unit B's values.

> [!important] Editing settings in flash
> Write the option's label ID (`0x81000000 | string index`) into its word, then fix word 127. Erase the sector and program
> 512 bytes.

| Word | Menu item | Options (menu order) | Unit A | Unit B |
|---|---|---|---|---|
| 7 | Language | 14 languages | English | English |
| 8 | Brightness | 1-8 | **4** | **8** |
| 9 | Auto Power Off | Off, 1 Min, 3 Min | Off | Off |
| 10 | Screen Savers | Off, 1 Min, 3 Min | Off | Off |
| 14 | Video Size | VGA, 720P, 1080P | 1080P | 1080P |
| 15 | Self-Timer | Off, 3S, 5S, 10S | Off | Off |
| 16 | Date Stamp | Off, On | On | On |
| 22 | Cyclic Record | Off, 3 Min, 5 Min, 10 Min | **Off** | **3 Min** |
| 26 | Image Quality (photo size) | 48M, 40M, 24M, 20M, 18M, 16M, 12M, 10M, 8M, 5M, 3M, 2M, 1M | **16M** | **18M** |
| 30 | Volume | 1-8 | 8 | 8 |

Hidden words (no menu item; fixed values, the same on both units):

| Word | Value | Meaning |
|---|---|---|
| 11 | 50Hz | light frequency (guess) |
| 12, 13, 17, 18, 21, 27 | Off | unknown on/off settings |
| 19 | Mid | Low/Mid/High (guess: JPEG quality or sharpness) |
| **20** | On | **key beep on/off** (verified) |
| **23** | On | **record audio with video** (verified) |
| 28, 31, 32 | On | unknown on/off settings |
| 24, 29 | "0" (string 45) | probably exposure compensation |
| 25 | Auto (string 169) | white balance or anti-shake (guess) |

Settings menu table (app):

| Address | Layout |
|---|---|
| `0x02076EC0` | `{0, count = 1, ptr}` → the one menu at `0x02076ECC` |
| `0x02076ECC` | menu `{0, 0, label, item count = 14, items ptr}`. The label is string 65 "Video" (unexplained) |
| `0x02076EE0` | 14 items × `{u32 slot, u32 0, u32 label, u32 option count, u32 ptr}`. With count 0, `ptr` is a handler (Date/Time `0x02006360`, Version `0x0200638C`). Format and Default Setting use slots 33/34 as OK/Cancel actions |
| `0x02077000`-`0x0207722F` | option lists `{u32 0, u32 label}` |

## Internal photo store

Used when no SD card is in. Index at `0x27D000` (RAM copy `0x0207F4C0`):
`{u32 base 0x27D000, u32 size 0x182000, u32 max 0x26 (38 slots), u32 count, {u32 flash_addr, u32 number}[count]}`.

- Slots are 40 KB (`0xA000`) from `0x27E000`. One photo = one **320×240 JPEG ≤ 40 KB** (the firmware lowers the quality until
  it fits). "SPI is full" (string 203) when no slot is free.
- A photo is written as whole 4 KiB sectors from a RAM buffer, so the sector tail holds leftover bytes. The index sector is
  then erased and rewritten.
- `photostore_add` `0x020363C4`, `photostore_free_slots` `0x020368AC`. Details: [[analysis/camera#8. Taking a photo (V, PhotoEncode task 3)]].

## SD card update (DestBin.bin)

`upgrade_DestBin` `0x020162B4` runs **on every boot**, from `app_main`, before the menu.

1. Needs an SD card. Mounts it and opens **`DestBin.bin`** in the card root.
2. Seeks to `0x7DE00` (resource 0 in the current flash), reads 15 bytes, and compares them with the installed version
   string (18 characters). Equal → skip. With 18 characters this compare can practically never match (inferred), so
   **the update runs on every boot while the file is on the card**. Delete the file after an update.
3. Shows "Upgrade, please wait…" (string 18) and a progress bar. The watchdog is off during the rewrite.
4. **Erases the whole chip** (`0xC7`). Only if that fails: 4 KiB sector erases up to the file size. Settings and the photo
   store are wiped too.
5. Writes the file from `0x200` to the end first, then **the 512-byte header at `0x000` last**.
6. Verifies by reading back in 2 KiB chunks. Returns 0 ok, -1 no card/file or skipped, -2 write error, -3 verify error.

**No CRC, signature, size, model or battery check.** The file is a raw flash image (a dump is the right format).

- It is a **second flashing path that needs no PC**: save a modified full image as `DestBin.bin`.
- Use a full 4 MiB image. A short file leaves the rest of the chip erased. An erased settings block makes the firmware load
  the defaults.
- Power loss during the update leaves an erased header, so the boot ROM should force its USB loader (not tested).
- The path exists only while the app reaches `app_main`. Firmware of our own must keep its own way back in
  ([[HARDWARE#Flashing over USB]]).

## Photos and video

- Photo files: `PHOTO/PHOnnnnn.JPG` = main JPEG + thumbnail JPEG + a trailing APP9 marker `FF E9 00 0A "JRX\0" <offset>`
  that points to the thumbnail. **No EXIF block.**
- **Every photo size is an upscale of one 640×480 frame** by the JPEG unit's hardware scaler. Sizes: 48M 7680×5760,
  40M 7040×5280, 24M 5760×4320, 20M 5120×3840, 18M 4800×3600, 16M 4480×3360, 12M 3840×2880, 10M 3520×2460, 8M 3200×2400,
  5M 2560×1920, 3M 1920×1440, 2M 1440×1080, 1M 1280×960.
- Video: `VIDEO/MOVnnnnn.AVI`, AVI (OpenDML), MJPEG 30 fps, PCM 16 kHz mono audio. VGA 640×480, 720P 1280×720,
  1080P 1920×1080 (upscaled). Both HD sizes fall back to 640×480 when the hi-res-disable flag `0x0208337C` is set.
- Other folders: `AUDIO/`. File prefixes `MOV`, `PHO`, `MIC`, and `LOK` for locked files.
- Details: [[analysis/camera]].

## Corrections to earlier notes

The old session notes had these statements. The 2026-11-12 code analysis replaced them.

| Earlier statement | Now known |
|---|---|
| Two or three sensor drivers (BF20A6, GC0310, `…030iot`) | **7 probe entries** in the config block ([[analysis/camera]]) |
| Header `+0x3C`-`+0x4C` "probably a checksum"; family notes said "the boot ROM checks a header CRC, fix it" | no checksum to fix; `+0x4C` is code ([[#Header]]) |
| Vendor commands need mode `1908:3283` | our camera uses `0219:3280` |
| `lcd_init` GPIO mask `0x40` is "reset or chip select" | that is **PA6 = backlight**; LCD reset is **PB6** |
| ad-key ioctl `0x2000000D` = "a second input?" | raw power key on **PB0** |
| Physical button for each ADC code unknown | map decoded ([[HARDWARE#Button map (confirmed on the device)]]) |
| Sound 49 = power-on, 50 = power-off (guess) | **50 = power-on, 49 = power-off**; 51 = shutter (verified) |
| 2 MiB RAM "a guess from stack pointers" | the code assumes 2 MiB (stack top `0x021FFFFC`); a hardware test is still open |
| HX3302B, JieLi or Spreadtrum SoC | AX3295B family |
