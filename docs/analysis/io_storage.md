# I/O and storage: USB, SPI flash, SD card, audio

> [!summary]
> Stock USB modes and SCSI commands (including **0xDA → boot ROM loader**), the SPI flash controller with the raw sequences a flashing payload needs, the SD card, audio (DAC and microphone) and the UART.

Source: the stock firmware (`Y200-V1.1-20251020`), decoded from `analysis/export/all.asm` + `all.c` and the raw app image.
Everything here is **verified in code** unless marked *inferred*. SPR = special-purpose register (`l.mtspr`/`l.mfspr`).
The register bases agree with `research_registers.md` (from matu6968's SDK).

## 1. USB device (stock firmware)

USB 1.1 full speed (`bcdUSB 0x0110`, EP0 size 64). Three device descriptors in the app image:

| Address | VID:PID | Class | Used for |
|---|---|---|---|
| `0x02064CC0` | `0219:3280` | per interface (`00 00 00`) | mass storage (camera on, SD card in) |
| `0x02064CAC` | `1908:3282` | composite (`EF 02 01`) | webcam + audio (camera off, plugged in) |
| `0x02064C98` | `1908:3283` | composite (`EF 02 01`) | MSC + webcam (other SDK builds; not seen on our unit) |

SCSI INQUIRY vendor/product text: `BuildwinMedia-Player    1.00` (`0x02064CE8`).

USB controller SPRs: `0xA000`-`0xA064` (`0xA038` endpoint index, `0xA048` CSR, `0xA058` FIFO count, …), PHY/power at
`0x9840` and `0xD804`. The MSC loop runs in the **usb device task** (ID 9): `UsbDevice_service` → `usb_msc_poll`
(`0x0203D764`) → `msc_poll` (`0x0203FD4C`) → `msc_scsi_dispatch` (`0x0203F708`).

### SCSI commands handled by the stock firmware (`msc_scsi_dispatch` 0x0203F708)

Standard: `00` TEST UNIT READY, `03` REQUEST SENSE, `12` INQUIRY, `1A` MODE SENSE(6), `1B` START STOP, `1E` PREVENT
REMOVAL, `23` READ FORMAT CAPACITIES, `25` READ CAPACITY, `28` READ(10), `2A` WRITE(10), `2F` VERIFY (ignored).
Anything else → CHECK CONDITION.

Vendor commands:

| CDB[0] | Sub (CDB[1]) | Direction | What it does (verified) |
|---|---|---|---|
| `0xDA` | — | none | **Reboot into the boot ROM loader**, see below |
| `0xCD` | — | any | Calls a hook function pointer (`*0x020832EC`) with the CBW and CSW. The hook is set at run time (*inferred*: UVC/ISP tuning). |
| `0xCB` | `0xF0` | none | Calls `0x02034FC0(u32)` with big-endian CDB[4..7] (*inferred*: ISP/sensor tuning value) |
| `0xCB` | `0xF1` | none | **Sensor I²C register write**: register in CDB[4..5], value in CDB[6..7]; width from the sensor entry (+0x43 register width, +0x44 value width). Calls `sensor_i2c_write` (`0x02047218`) |
| `0xCB` | `0xF2` | in, 6 bytes | **Sensor I²C register read**: returns `CB F2 v3 v2 v1 v0` |

This is the PC-side tuning interface of the SDK (sensor registers over USB). It does **not** give RAM or flash access.
RAM/flash access is only through the boot ROM loader (next point).

### How `0xDA` reaches the boot ROM loader (`usb_vendor_reboot_loader` 0x0203F578)

1. Watchdog off (`wdt_enable(0)` = `0x0202701C`), send the CSW.
2. USB PHY off: SPR `0x9840` clear bits 0, 2, 18, 19 (D+ pull-up off → the PC sees a disconnect). Set SPR `0xD804` bit 3
   and wait until it reads back as set.
3. Wait 2 × 500 ms; disable 15 interrupt sources with `irq_enable(n, 0)` (`0x0202616C`; `n` = 0-8, 0xE, 0xF, 0x12, 0x15,
   0x16, 0x1D) and clear bit 14 of SPR `0x18`.
4. Return 0 → `UsbDevice_service` switches the backlight off and calls `task_switch(10)` → `task_run_loop` ends →
   **`app_main` returns 2** to the code that called it (the bootstrap/boot ROM hook; `app_main` is the hook target at
   SRAM bootstrap offset `0x528`, see `research_usb_flashing.md`). *Inferred*: return value 2 tells the boot code to enter
   the USB loader `1908:3319`. (Observed on the device: it does.)

Consequence for custom firmware: **our firmware must implement `0xDA` the same way** (or simply return 2 from the app entry)
if we want "reflash over USB without opening the case" to keep working. Otherwise recovery needs the forced-loader trick
(flash pins 2/3 short).

USB detect: `usb_ioctl(0x20000002)` → `0x02029F00` (VBUS / `USB power` bit, see `soc_core.md`). `usb_init` →
`0x02029E90(1)`.

## 2. SPI flash controller (SPI0, SPR 0x9000-0x927C)

### Registers (verified from `spi0_init` 0x02028EB4, `spi_tx_byte`, `spi_rx_byte`, `spi_dma_*`)

| SPR | Name (ours) | Meaning |
|---|---|---|
| `0x9000` | `SPI0_CON` | init `0x01115005 \| ((mode-1)&3)<<8`. **bit 14 = CS (1 = high/idle, 0 = selected)**, bit 7 = RX direction (1 = receive, 0 = transmit), bit 1 = DMA mode |
| `0x9004`, `0x9008` | — | 0 at init |
| `0x900C` | `SPI0_CON2` | `\|= 5` during DMA, then `&= 0xFFF3FF00` |
| `0x9244` | `SPI0_KICK` | write 1 = start one-byte transfer; write `0x20000` then 2 = start DMA; `0x3FF0000` at init (clear flags) |
| `0x9248` | `SPI0_STAT` | bit 0 = byte done, bit 1 = DMA done |
| `0x924C` | `SPI0_BAUD` | `36000000 / f_spi - 1` |
| `0x9250` | `SPI0_DATA` | TX byte (write) / RX byte (read) |
| `0x9254` | `SPI0_DMA_CNT` | number of 32-bit words − 1 |
| `0x9258` | `SPI0_DMA_ADR` | RAM address (16-byte aligned) |
| `0x925C` | `SPI0_DMA_CFG` | `0x06000000` for both directions |
| `0x9260`-`0x927C` | — | init values `0xFFFF`, `-1`, 0, `0x0FFFFFFF`… (CRC/ALU unit; `0x9260` = the hardware CRC the boot ROM can check, see research report) |

Pins: the flash bus is on **PA8, PA10, PA11** (masks `0x100/0x400/0x800`; `spi0_init` uses mask variants `0xC00`, `0x3C0`,
`0x300` depending on the mode). See the pin table in `soc_core.md` section 4.1. PA6 is the LCD backlight, not flash.

### Raw sequences (what a USB flashing payload must do)

```
one byte:      CON &= ~0x80 (TX); DATA = b; KICK = 1; while (!(STAT & 1)); 
read byte:     CON |= 0x80 (RX);  DATA = 0xFF; KICK = 1; while (!(STAT & 1)); b = DATA & 0xFF
CS low/high:   CON &= ~0x4000 / CON |= 0x4000
DMA RX n bytes (n multiple of 4, buf 16-aligned):
               CON |= 0x80|0x02; CON2 |= 5; DMA_CNT = n/4-1; DMA_ADR = buf; DMA_CFG = 0x06000000;
               dcache_invalidate(buf, n); KICK = 0x20000; KICK = 2; while (!(STAT & 2)); CON &= ~2; CON2 &= 0xFFF3FF00
```

### Flash commands the firmware uses (all of them)

`0x9F` JEDEC (`spi_flash_read_jedec` 0x02035F24), `0x03` read, `0x06` write enable, `0x05` status poll (bit 0 = busy,
timeout 16,000,000 polls → -1), `0x02` page program (256 B), `0x20` sector erase 4 KiB, `0xD8` block erase 64 KiB
(`0x02036304`, not auto-disassembled before), `0xC7` chip erase.

**The firmware never sends `0x01`/`0x31` (write status register).** It never changes the block-protect bits, so the chip
is unprotected in normal use (both dumps were writable by the update path). A flashing payload does not need to unlock it,
but should read status (`0x05`, `0x35`) first and stop if any BP bit is set.

### Stock functions (signatures verified)

| Address | Function |
|---|---|
| `0x02028EB4` | `spi0_init(mode, freq_hz)` |
| `0x020292EC` | `spi_cs(level)` (0 = select) |
| `0x020290D4` | `spi_tx_byte(b)` |
| `0x02029128` | `spi_rx_byte()` |
| `0x0202917C` | `spi_tx_dma(buf, len)` (len ≥ 8) |
| `0x02029234` | `spi_rx_dma(buf, len)` |
| `0x02035F24` | `spi_flash_read_jedec()` |
| `0x02035F84` | `spi_flash_write_enable()` |
| `0x02035FB8` | `spi_flash_wait_busy()` → 0 / -1 |
| `0x0203603C` | `spi_flash_read_page(addr, buf)` (256 B) |
| `0x020360B4` | `spi_flash_read(addr, buf, len)` |
| `0x0203617C` | `spi_flash_page_program(addr, buf, len≤256)` |
| `0x020361FC` | `spi_flash_write(addr, buf, len)` |
| `0x02036298` | `spi_flash_sector_erase(addr)` |
| `0x02036304` | `spi_flash_block_erase(addr)` (64 KiB) |
| `0x02036368` | `spi_flash_chip_erase()` |
| `0x0202642C` | `dcache_writeback(addr, len)` (SPR `0x181C` = line count − 1, `0x180C` = address; 16-byte lines) |
| `0x020264A8` | `dcache_invalidate(addr, len)` |

## 3. SD card (SD0, SPR 0x9880-0x989C)

| Address | Function |
|---|---|
| `0x02035678` | `sd_init(arg)` (card identification; called by `upgrade_DestBin` with 1 when the mount fails) |
| `0x0203546C` | `sd_rw_sector(buf, lba, write)` — one 512-byte sector. Unaligned buffers are bounced through `0x0207F2B0`. Keeps a multi-block stream open (state `0x0207F4B2`: 1 = reading, 2 = writing, 3 = stopped; next LBA `0x0207F4BC`; card size `0x0207F4B4`) |
| `0x020353E8` | `sd_stop()` (CMD12, then wait) |
| `0x0203534C` | `sd_wait_ready()` (CMD13 until state = tran) |
| `0x02035B98` | `sd_present()` (used by `sdcard_ioctl 0x20000001`) |
| `0x02056B60` | `sdc_cmd(index, arg)` (SPR `0x9880/84/8C/98/9C`) |
| `0x02056E80` | `sdc_resp()` (SPR `0x989C`) |
| `0x02056CF0` | `sdc_data(buf, len)` (SPR `0x9890/94` = DMA) |
| `0x020569A0` | `sdc_set_clock(...)` (*inferred*, SPR `0x9888`) |

The FAT layer on top is the `fs_*` API already named (`fs_mount` `0x0205A5A8`, `fs_open` `0x0205A680`, …). Card detect
is by command response, not by a pin (no GPIO read in `sd_present`).

## 4. Audio

### DAC / speaker (SPR `0x9140`-`0x9160`, analog/clock `0x8848`, `0x884C`, `0x886C`-`0x8874`)

| Address | Function |
|---|---|
| `0x0202AF28` | `dac_init()` — clock gates `0x8848/0x884C`, analog `0x886C`, `0x8870 = 0x124`, `0x8874 = 0x2BB`, DAC regs to 0 |
| `0x02031DB4` | **`dac_play(rate_hz, buf, len)`** — rate must be one of 48000, 44100, 32000, 24000, 22050, 16000, 12000, 11025, 8000 (table `0x020648DC`, index → SPR `0x915C` bits 4-7); sets volume `(vol% × 0x7FFF)/100` (`0x0202AC0C`, volume byte `0x0207F1F0`); starts DMA |
| `0x0202ACE8` | `dac_start_dma(buf, len)` — `0x9140 = 0x202C`, `0x914C = 7`, `0x9148/0x9144 = buffer`, `0x9158 = length`, `irq_enable(6,1)` |
| `0x0202AC84` | `dac_queue_next(buf, len)` — writes `0x9148`/`0x9158` (one-deep next-block queue) |
| `0x0202AB18` | `dac_set_rate(index)` |
| `0x0202AA44` | DAC IRQ handler: status bits 1/2/4 → callback `*0x0207F158(event)` |

Format: 16-bit PCM (*inferred* from the SDK; mono vs stereo not checked). Volume comes from settings slot 30.

### Microphone ADC (SPR `0x9100`-`0x9120`)

Functions `0x0202B254`, `0x0202B34C`, `0x0202B3DC`, `0x0202B458`, `0x0202B55C`, `0x0202B184` (used by video recording and
the webcam's audio interface). Not decoded in detail.

### UART (SPR `0x9080`-`0x908C`)

`0x02027FAC` (init: `0x9080/0x9084/0x908C`), `0x02027EBC` / `0x02028020` (TX via `0x9088`, status `0x908C`). This is the
debug UART; pins and baud: see `soc_core.md`.

## 5. Code that the auto-analysis missed

These blocks were never disassembled. Create them as functions in Ghidra (done by `MO2947ApplyNames.java` with
`io_storage_names.tsv`): `0x0203603C`, `0x02036304`, `0x0203D224`, `0x0203D250`, `0x0203EF68`-`0x0203F1D8` (MSC helpers),
`0x02035D84`, `0x0202C108`.

## 6. What this means for USB flashing

- Flashing does **not** go through the stock firmware: `0xDA` → loader → `0xCB` RAM write + call (see
  `research_usb_flashing.md`). The stock vendor commands only tune the sensor.
- The payload needs exactly the SPI0 sequences in section 2 (PIO is enough; DMA is optional). Write enable before every
  program/erase, poll `0x05` bit 0, page size 256, sector 4 KiB.
- The flash is unprotected (no status-register writes anywhere in the firmware).
- Keep the header sector (`0x000`-`0xFFF`) byte-identical; write it last, as `upgrade_DestBin` does.
