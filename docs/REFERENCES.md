# References

External sources, the product data, and the tools this project needs.

## Our SoC family (AX3295B / JT5295)

`./setup.sh` fetches two of them: the SDK (into `firmware/appotech-sdk`, plus our port) and the tbelbek tools (into
`ext/`, read-only; only the dump/flash code runs, through `tools/mo2947_dump.py`). The others are background reading:
clone them elsewhere if needed, and do not run their code without the owner's permission.

| Repository | Where | What it gives us |
|---|---|---|
| **matu6968/appotech-sdk** — https://github.com/matu6968/appotech-sdk | `firmware/appotech-sdk` (fetched + patched) | **The current MIT SDK**: runtime, display, SD, audio, keys, SPI flash, USB debug link (APXD). `boot/flasher.c` (flash payload), `research/*.md` (register evidence with stock addresses), board ports (Action camera, Silvergear) |
| **matu6968/Action_Digital_Kids_Camera_DOOM** — https://github.com/matu6968/Action_Digital_Kids_Camera_DOOM | not fetched | JT5295 Action camera: older SDK copy, launch/install/rescue scripts, stock flash + 64 KiB boot ROM. Docs: `SOC_IDENTIFICATION.md`, `FLASHING.md` (forced loader), `HARDWARE.md`, `TOOLCHAIN.md` |
| **matu6968/apxtool** — https://github.com/matu6968/apxtool | not fetched | host tool: `flash`, `rom-rescue`, `sdk launch` (run from RAM), SPI image packer |
| **matu6968/ghidra-appotech-jt5295** — https://github.com/matu6968/ghidra-appotech-jt5295 | not fetched | Ghidra language (LE, no delay slots), for disassembling the stock firmware |
| **tbelbek/luxorparts-kdc030d-re** — https://github.com/tbelbek/luxorparts-kdc030d-re | `ext/luxorparts-kdc030d-re` | **What our dump/flash tools use**: `kdc_dump.py`, `kdc_run.py`, `flstub.py` (build-independent SPI payload), window-guarded write path, `or1k_dis.py` |
| **hidoba/penguin-camera** — https://github.com/hidoba/penguin-camera | not fetched | AX3295B print camera with the same 4 MiB flash. Boot ROM + stock dump, header parser emulator, `STOCK-FIRMWARE.md`, `RECOVERY.md` (Pi Pico) |

Toolchain: matu's patched GCC 16.2.1 + binutils 2.47 + picolibc as `or1k-appotech-elf-gcc -mappotech`. Build notes:
[[analysis/research_usb_flashing#5. Toolchain]].

Other family sources:

- Habr article that first documented the Buildwin vendor SCSI commands (`0xCD`, names `0xCB`/`0xDA`):
  https://habr.com/ru/companies/ruvds/articles/779626/
- Jinrixin product pages (did not load during research): AX3291/3292 https://en.jrxchip.com/product/9.html,
  AX3295B https://en.jrxchip.com/product/10.html
- kc02-fw-mod PR about `1908:3282` (webcam only) vs `1908:3283`: https://github.com/6uan/kc02-fw-mod/pull/2
- No datasheet for AX3291/AX3292/AX3295B/JT5295 exists in public.

## This product

| Field | Value |
|---|---|
| Item | **MOB/MO2947** (colour MO2947-13, beige), sold by Mid Ocean Brands B.V., Ede, NL (a reseller; the OEM is not named) |
| Page | https://www.momanual.com/momanual/us/eur/technology/phone-accessories/others/mo2947-13-zid10245960 |
| Advertised | F2.4 lens, 2.0" LCD, "12 MP" photos, "FHD" video, USB-C, 300 mAh battery, microSD (not included) |
| Reality | VGA sensor; every larger photo and video size is upscaled ([[FIRMWARE#Photos and video]]) |
| EAN / HS code | 8719941095540 / 8525 8900 |
| Size / weight | 8.8 × 6.0 × 3.2 cm / 0.14 kg |
| EU DoC | F0094601, batch PO 4100117248, dated 2026-01-01. EMC, RoHS, GPSR, batteries, REACH. **No Radio Equipment Directive, so no Wi-Fi or Bluetooth.** Open it from the product page (signed URL) |

## Related cameras (background only)

Before the teardown, the SoC was thought to be an HX-Tech HX3302B. That is wrong. These sources are still useful for
general methods.

- HX3302B "X9S" camera (OR1K-LE, SD update, toolchain, Doom): https://github.com/andrewspode/hx3302b-x9s-camera,
  article https://spodesabode.com/articles/reverse-engineering-a-childrens-camera/
- Sprite_tm, "Kid-cam firmware modding" (EXIF memory-dump trick): https://spritesmods.com/?art=kid_cam
- Ghidra OR1K-LE for HX330x: https://github.com/Spritetm/ghidra-or1k-le-hack
- JieLi KC02 camera (SFAT asset tools, `DestBin.bin` name): https://github.com/austinpresley/kc02-fw-mod
- timmedia, kids camera teardowns (AX3295B and Spreadtrum variants):
  https://timmedia.de/2023/10/16/TeardownInexpensiveChildrenCamera.html
- fpdoom (Spreadtrum SC6531 cameras): https://github.com/ilyakurdyukov/fpdoom
- doomgeneric (a good first big program to port): https://github.com/ozkl/doomgeneric
- ChipLink CL4056D charger: https://jlcpcb.com/partdetail/ChipLinkTech-CL4056D/C2920852

## Tools and parts

| Item | Use |
|---|---|
| USB-A/USB-C **data** cable, direct to the PC | dump, flashing, RAM launch |
| microSD card (FAT32) | mass-storage mode, SD update |
| pyusb + libusb | USB tools; `./setup.sh` installs them ([[FIRMWARE#Preparation (once)]]) |
| `or1k-appotech-elf-gcc` (matu toolchain, built by `./setup.sh`) | building our own code |
| Phillips PH00 screwdriver, plastic pry tool | opening the case |
| Fine tweezers | forced loader (flash pins 2-3), recovery only |
| 3.3 V USB-UART adapter + soldered wire on PA7 | debug UART, 115200 8N1 (optional) |
| Logic analyser (optional) | I²C, LCD bus, UART |
| SPI programmer + hot air (last resort) | recovery with the flash desoldered |
