# ToyCamera docs: MO2947 toy camera

Reverse engineering of the **MOB/MO2947** promotional digital camera, and custom firmware for it. Install and flash
steps for people are in the repo's `README.md`; this folder is the technical reference.

## Status (2026-11-12)

> [!success] Milestone
> **We can write any program for the camera.** Our own firmware (matu's SDK, ported as board `mo2947`) is built with
> our toolchain, installed over USB in place of the stock app (sector 0 untouched) and drives every part of the camera.
> How to write and install a program: [[HARDWARE#Writing and installing a program]].

- **SoC:** Jinrixin / Buildwin / AppoTech **AX3295B family**. OpenRISC 1000, little-endian, no delay slots, 144 MHz,
  **2 MiB SDRAM**, 4 MiB SPI flash.
- **Working in our firmware:** display, keys, LED, power, camera preview and photos (SP0A39, 640x480 JPEG), SD card,
  microphone, battery, USB debug link, USB drive, webcam + USB microphone. Speaker not tested (disconnected).
- **Not done yet:** a full camera app (menus, viewer, video); wireless (options in [[CONTINUE#Next steps]]).

> [!important] Must know
> - **Never write to the flash without the owner's explicit "go".**
> - Back up the camera first (`./cam dump stock dumps/mo2947_flash_a.bin`). Restore and every install depend on it.
> - Keep **sector 0** (header) byte-identical. The install tool never touches it.
> - Our code must do the **power hold first** (PMU register `0x40`), within milliseconds. The SDK start-up does it.
> - Dumps hold the owner's photos and the vendor firmware: keep them private, never commit them.

## Read in this order

| File | Contents |
|---|---|
| [[HARDWARE]] | **Programmer's reference**: pins, registers, button map, start-up, writing and installing a program |
| [[CONTINUE]] | History of the port: what was tried and verified on the device, what broke and why; next steps |
| [[FIRMWARE]] | Stock firmware and flash: USB modes, **how the dump works**, recovery routes, flash map, header, settings, SD update |
| [[REFERENCES]] | External repositories, product data, tools and parts |
| `analysis/*.md` | The full reports with the evidence: [[analysis/soc_core]], [[analysis/display]], [[analysis/camera]], [[analysis/ui_input]], [[analysis/io_storage]], [[analysis/research_usb_flashing]], [[analysis/research_registers]] |

> [!note] About the reports
> They were written while decoding the stock firmware. Addresses like `0x0201xxxx` and names like `lcd_init` refer to
> the stock app (a Ghidra project that is not in this repo). They are evidence for the register sequences, not code
> to call: our firmware replaces the stock app.

Paths such as `tools/…`, `firmware/…`, `dumps/…` are relative to the repo root. Links `[[…]]` are Obsidian links inside
`docs/`.
