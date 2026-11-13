# Writing the MO2947 flash over USB: research from the reference projects

> [!summary]
> From the external repositories (nothing run on the camera): the boot ROM loader protocol (**0xDA**, **0xCB**), how each tool writes flash, the header check (**no CRC to fix**), running code from RAM, the toolchain, recovery, and the step plan for our camera (section 7).

Research only. Nothing in this file was run on the camera. Every claim gives its source. "Verified" means the source tested it
on its own hardware (or I read it in the boot ROM/our dump). "Inferred" means a conclusion that has not been tested.

## Sources (cloned read-only into `ext/`, nothing executed)

| Folder | Repository | What it gives us |
|---|---|---|
| `ext/Action_Digital_Kids_Camera_DOOM` | github.com/matu6968/Action_Digital_Kids_Camera_DOOM | Vendored copy of the SDK (`firmware/sdk`), `tools/` (launch/install/rescue scripts, older apxtool copy), stock flash + 64 KiB boot ROM of the JT5295 camera (`dumps/`) |
| `ext/appotech-sdk` | github.com/matu6968/appotech-sdk | **The current SDK** (MIT), `boot/flasher.c` (the flash payload), `research/*.md` (register evidence with stock addresses), a second board port (Silvergear printer camera, 4 MiB flash). Not named in the task; found through the DOOM README |
| `ext/apxtool` | github.com/matu6968/apxtool | Current host tool: `flash`, `rom-rescue`, `sdk launch`, SPI image packer (`spi_boot.py`, now multi-board) |
| `ext/ghidra-appotech-jt5295` | github.com/matu6968/ghidra-appotech-jt5295 | Ghidra language only. Standard OR1K SPR names; **no peripheral register data** |
| `ext/penguin-camera` | github.com/hidoba/penguin-camera | AX3295B printer camera (4 MiB ZB25VQ32, same as ours). Boot ROM (32 KiB) + stock dump, header analysis, boot ROM emulator for the header parser, a `0xCD` (stock firmware) flasher |
| `ext/luxorparts-kdc030d-re` | tbelbek (already present) | The `flstub` payload we already use for dumps, window-guarded write path, granule preflight |

Web search found **no datasheet** for AX3291/AX3292/AX3295B/JT5295 and no other "BLDR v1.00" documentation. The Habr article
(habr.com/ru/companies/ruvds/articles/779626) only documents `0xCD` (stock firmware) and names `0xCB`/`0xDA`; it adds the
callback semantics and the "read 8 KiB to flush the data cache" trick, nothing else.

## 1. The loader protocol

### 1.1 Transport

USB mass storage, Bulk-Only Transport. CBW = `'USBC', tag, data_len, flags (0x80 = IN, 0x00 = OUT), lun 0, cdb_len 16, CDB[16]`.
CSW = 13 bytes `'USBS', tag, residue, status`. Loader: `1908:3319`, interface 0, bulk OUT `0x01`, IN `0x81`.
Implementation: `ext/luxorparts-kdc030d-re/device/kdc_dump.py: Bot.cmd`, `kdc_run.py: cmd_out` (pyusb, what we use now);
apxtool uses Linux SG_IO on `/dev/sgN` instead (`apxtool/src/apxtool/transport.py`).

### 1.2 `0xDA` (stock firmware → boot ROM loader)

CDB = `DA FF FF … FF` (16 bytes, no data). Sent to the stock mass-storage interface (our camera: `0219:3280`, interface 4).
The device usually drops off the bus before the CSW; tools ignore that error. (`apxtool/protocol.py: build_enter_loader_cdb`,
`kdc_run.py: enter_loader`.) Stock handler: `0x0203C1CC` in the JT5295 firmware; it clears SPR `0x18` bits 1, 2 and 14 and jumps
to ROM `0x0010385C` (`appotech-sdk/research/spi-boot-recovery.md`). Verified on our camera ([[FIRMWARE#USB modes]]: loader in 0.02 s).

### 1.3 `0xCB` (loader: memory transfer and call)

CDB layout (all little-endian, verified in the boot ROM by me, see 1.4):

| Bytes | Field | Normal value |
|---|---|---|
| 0 | opcode | `0xCB` |
| 1..4 | handler function (ROM state `0x4F74+0x6C`) | `0x00102620` (ROM transfer helper; same address in both known ROMs) |
| 5..8 | memory address (state `+0x70`) | RAM/SRAM address |
| 9..12 | callback (state `+0x74`) | `0xFFFFFFFF` = none, else address of code to call |
| 13..15 | padding (tools send `FF FF FF`; may land in state `+0x78`, passed as r5) | `FF FF FF` |

Direction and length come from the CBW, not from the CDB.

- **Read** (CBW IN, callback `0xFFFFFFFF`): returns `length` bytes from `address`.
- **Write** (CBW OUT, callback `0xFFFFFFFF`): stores the data at `address`.
- **Call**: CBW IN (any small length, tools use 16 or 24), callback = code entry, address = request block. The ROM calls
  `callback(r3 = address, r4 = length, r5 = state+0x78)` **before** it sends the data, then returns `length` bytes from `address`.
  So the payload's result can come back in the same transaction. With CBW OUT the ROM receives the data first, then calls the
  callback.
- Handler `0` (untested by anyone): the ROM sends the status first, then calls the callback if it is non-zero (fire and forget).

The call returns only when the payload returns (`l.jr r9`). Use a long host timeout (tbelbek uses 30 s for erase/program).

### 1.4 What I read in the boot ROM (penguin `soc_boot_rom.bin`, AX3295B, SHA `62d4dabe…`)

My own small disassembler (`scratchpad/research_ext/or1kdis.py`, not in the project). ROM addresses:

- `0x102308`: SCSI dispatch for `0xCB`: if handler ≠ 0, `jalr handler`.
- `0x102620`: tests the direction byte (state `+0x68`, signed): IN → `0x102530`, OUT → `0x102584`.
- `0x102530` (IN): `if callback != -1: callback(addr, len, state+0x78)`; then send `len` bytes from `addr` (`0x102254`).
- `0x102584` (OUT): receive into `addr` (`0x101F44`); then call the callback if ≠ -1.
- Other opcodes handled: `0x00`, `0x03`, `0x12` (INQUIRY data at ROM `0x105E08`, 49 bytes `BuildWinVideo050Loader  1.00.1.00 Thunder`).

### 1.5 Size limits (empirical, from the tools)

| Transfer | Size seen working | Source |
|---|---|---|
| 0xCB read of DDR (after `0xDA` from stock) | up to 64 KiB per command | apxtool `docs/loader-research.md` ("transfers up to 64 KiB completed") |
| 0xCB read of SRAM / small reads | 4 KiB (tbelbek ROM dump), 512 + header (matu rescue) | `kdc_run.py: bootrom`, `rom_rescue.py: _read` |
| 0xCB write | 256 B per command (tbelbek), 512 B (matu SRAM), 68 B..64 KiB to DDR (matu launcher uses `RAM_WRITE_CHUNK = 0x200`) | `kdc_run.py: sram_write`, `apxtool/ram.py` |
| penguin note | "Memory reads through it were bounded at 256 bytes in tests" | `penguin-camera/docs/STOCK-FIRMWARE.md` (their earlier tests) |

Recommendation: 256-512 B writes, ≤4 KiB reads in SRAM, ≤64 KiB reads in DDR. Always read back what you wrote.

### 1.6 Watchdog / keep-alive

- The loader arms the watchdog (SPR `0x880C`) with `0x5001D` = selector 5 ≈ **1.8 s**, and reloads it **only from its USB
  interrupt handler** (ROM `0x104878..0x104944` → `0x102EAC`). With no host traffic for ~2-3 s it resets and the camera boots
  the stock firmware again (forced loader: it re-enumerates in a loop). (`appotech-sdk/research/spi-boot-recovery.md`,
  `watchdog-power.md`; I also saw the `0x5001D` feed loop at ROM `0x1023A0..0x1023C0`.)
- Payloads therefore either write `0x880C = 0x5500` on every entry (disables it, reads back 0) — matu `boot/flasher.c`,
  tbelbek `flstub.py` — or feed it with `0x5001D` while busy, **but only if it still reads non-zero** (feeding a disabled
  watchdog would re-enable it). Both tools do both: disable on entry, conditional feed in poll loops.
- With the watchdog disabled the loader never times out by itself; a power cycle (or our own reset) is then needed. matu's
  `FLAG_KEEP_WDT` (request flags bit 0) leaves it armed so a stock camera reboots into its firmware after the session.
- Encoding of `0x880C` (verified by matu): `0x5500` disable; `0x0005_0000 | sel` = key 5 in bits 18:16 reloads + enables;
  readback bit 4 = enabled, bit 3 = reset enable, bits 2:0 = selector; `0x39` = immediate reset. Selector 4/5/6/7 ≈
  0.46/1.82/7.31/29.1 s. **Our firmware has the same routines**: `0x0202701C` (enable `0x50006` / disable `0x5500`) and
  `0x02027064` (feed if bit 4 set) — read in `analysis/export/all.asm`.

### 1.7 Payload environment (where code can run)

| Item | Value | Source |
|---|---|---|
| SRAM payload address | `0x2000` (≤ `0xF00` bytes for matu's flasher; tbelbek's stub is 2960 B) | `appotech-sdk/boot/flasher.ld`, `kdc_run.py` |
| Request block | `0x3400` (tbelbek, our dump tool) or `0x3900` (matu) | |
| Payload stack | **its own**, just below the request block (save area `r3-0x100`, stack top `r3-0x110`) | `boot/flasher.S`, `flstub.py` |
| ROM state / stack | ROM context at `0x4F74`; the callback is entered with `r1 ≈ 0x4F1C` (ROM stack). Using that stack from C **corrupted loader state** | apxtool `docs/loader-research.md` |
| Other SRAM used by ROM | header buffer `0x4A00` (boot), `0x4800-0x4C00`, USB buffers near `0x4440` and `0x8000` | my ROM reading, penguin STOCK-FIRMWARE.md |
| SRAM survives resets | yes (SDK boot marks at `0x2F00`, crash record `0x3400`) | `spi-boot-recovery.md` |
| DDR | usable only when the loader was entered from a running firmware (`0xDA`), not in a forced boot (DDR not calibrated) | apxtool README "Flashing" |
| Data cache | DDR writes can sit in the cache. Before calling code you uploaded to DDR, read ~8 KiB of other DDR (Habr, matu `launch`), or write back/invalidate with SPRs `0x181C/0x180C/0x1814` | `sdk.py: launch`, `runtime.c` |
| Branch slots | payload must be built without delay slots (`-fno-delayed-branch`, `.nodelay`), callee-saved regs restored, return `l.jr r9` | all |

## 2. How each tool writes flash

### 2.1 SPI controller (SPI0, the flash bus) — identical in all tools

Registers are **SPRs** (`l.mtspr`/`l.mfspr`), not memory. Same sequence in `appotech-sdk/boot/flasher.c`,
`firmware/sdk/src/spi.c`, `tools/rescue/rom-rescue.c`, tbelbek `tools/flstub.py` (and the ROM's driver `0x104AC4..0x104D20`).

Init (`command 0` with address bit 0 clear):

```
0x8850 = (0x8850 & ~0xF0000000) | 0x30000000   ; SPI clock source select (inferred)
0x8844 &= ~0x8                                  ; clock gate (index 35, active low, inferred)
0x8840 &= ~(1<<20)                              ; clock gate 20 (active low)
0x8344 = (0x8344 & ~(3<<20)) | (1<<20)          ; pin mux: SPI0 route 1
0x8100 |= 0xD00 ; 0x8040 &= ~0xD00 ; 0x8000 |= 0x400   ; PA8/PA10/PA11 peripheral, outputs, PA10 latch high
0x9000 = 0x01115005 ; 0x9004 = 0 ; 0x9008 = 0 ; 0x900C = 0
0x9244 = 0x03FF0000 ; 0x9248 = 0 ; 0x924C = 5            ; 0x924C = clock divider (boot header +0x40 also writes it)
0x9250..0x927C = 0
0x9260 = 0xFFFF ; 0x9264 = 0xFFFFFFFF ; 0x926C = 0x0FFFFFFF ; 0x9270 = 0x0FFFFFFF
```

Byte exchange (PIO): set/clear `0x9000` bit 7 (1 = receive), write the byte to `0x9250`, write `1` to `0x9244` (start),
poll `0x9248` bit 0 (done), read `0x9250`. Chip select = `0x9000` bit 14 (**0 = selected**). DMA (SDK only): `0x9000` bit 1,
`0x900C = 0x85` (rx) / `5` (tx), `0x9254 = len/4-1`, `0x9258 = address`, `0x925C = 0x06000000`, `0x9244 = 0x20000` then `2`,
poll `0x9248` bit 1. `0x9260` holds a hardware CRC of the data read (the boot ROM compares it, see 3).

Flash commands used: `9F` (JEDEC), `05` (read SR1), `06` (WREN, then require SR1 bit 1 WEL), `03` + 24-bit address (read),
`02` (page program, ≤256 B, never across a page), `20` (4 KiB sector erase). Wait for SR1 bit 0 (WIP) = 0 after program/erase.
No tool uses `D8`/`52`/`C7`/`01`/`50`. The stock firmware (ours too) uses `C7` chip erase in the SD updater.

### 2.2 tbelbek `flstub.py` + `kdc_run.py` (what we already run)

- Payload built in Python (`stub_build.Asm`), position fixed at `0x2000`, request at `0x3400`:
  `magic 0x52585041 'APXR', sequence, command, address, length, status, flags, data[]` (data at +28).
  Commands: 0 = SPI init + JEDEC, 1 = read, 2 = program page, 3 = erase sector. Status 1 = not done / refused, 2 = byte timeout,
  0 = ok.
- **Write window is compiled into the payload** (`build(window=(lo,hi))`): erase/program outside `[lo,hi)` is refused by the
  payload itself. The host re-uploads the payload per sector with a one-sector window (`kdc_run.py: _upload_payload`).
- Erase/program checks: 4 KiB alignment, length 1..256, no page crossing, WIP wait before and after, WEL check.
- Per sector (`_write_sector`): erase → read back must be all `FF` → program 16 pages → read back and compare. Exits on any error.
- Before the first real write: `_granule_preflight` proves `0x20` erases exactly 4 KiB using a blank 64 KiB scratch block at
  flash `0x200000` (refuses if that block holds data). **On our camera `0x200000` is inside the resource area**, so the preflight
  would refuse (safe, but blocks writing). Change `SCR` to a blank block, e.g. `0x3F0000` (see 6).
- Host gates: the live sector must equal the backup (or a known managed set of bytes) before it is overwritten; dry run unless
  the last argument is `WRITE`; JEDEC must be `5E4016` (host side, `JEDEC` constant). The payload itself does not check JEDEC.
- Proven on the KDC-030D (same `5E4016` chip): shutter, sound, AWB, JPEG patches. Our camera: reads proven (two dumps).

### 2.3 matu `appotech-sdk/boot/flasher.c` (+ `apxtool flash` / `rom-rescue`)

- C, position independent (linked at `0x2000` and `0x02180000`, build fails unless the bytes match). Same request layout
  (`magic, sequence, command, address, length, status, flags, data`), commands 0-3 as above plus 4 (read one SPR), 5 (read
  memory), 6 (8 diagnostic SPRs), 7 (apply PM-chip start-up sequence), 8 (read PM registers).
- Each flash command re-reads the JEDEC ID; reads accept capacity code `0x15`/`0x16`; **erase/program require exactly
  `5E4015`** (2 MiB). For our `5E4016` this is a one-line change (the Silvergear build variant shows how: `SILVERGEAR_BOOT_RESTORE`
  also refuses if SR1 protection bits `0xFC` are set).
- Two pools: SRAM `0x2000` (512 B transfers, forced loader, watchdog disabled) and DDR `0x02180000` (32 KiB transfers, loader
  entered from running firmware, watchdog left armed, **DDR pool only host-model tested**).
- Host (`apxtool sdk_flash.py: FlashClient.replace`, `rom_rescue.py: action_restore`): full-chip read → backup file (must be new,
  fsync, read back) → journal JSON before every destructive step → list of differing 4 KiB sectors, **sector 0 moved to the end** →
  per sector: erase, program non-`FF` pages, read back 4 KiB → finally a full-chip read and SHA-256 compare. Destructive SDK
  commands need an `APXF` marker in the payload. `--expect-current-sha256` refuses if the chip changed since the backup.
- `rom_rescue.check_boot_image`: image must have `u16 @2 == 2`, `BLDR @4`, `55 AA @0x1FE` (the ROM checks, see 3).
- Proven: Action camera 2 MiB (restore verified 2026-10-16); Silvergear 4 MiB `944016` through a special build.

### 2.4 matu SDK running from RAM (`apx_spi_*` in `firmware/sdk/src/spi.c`)

Same controller recipe with DMA reads. `apxtool debug flash install` uses it through the APXD USB link of a running SDK image.
This is the path matu now uses for ordinary re-flashing (no loader needed). Geometry and JEDEC come from `board.h`
(`APX_SPI_JEDEC`, `APX_SPI_FLASH_BYTES`).

### 2.5 penguin-camera (`tools/penguin_flash.py`, `camera_usb.py`)

Uses the **stock firmware's** `0xCD` command (not the loader): `CD | handler 0x0204109C | address | callback | 00 00 00`
(their firmware build; ours has different addresses). It calls the stock SPI routines (`0x39528` read etc.) and a generated
"sector bridge" that can erase/program only one reviewed sector. Changed sectors only; flash-guard sector first, loader sector
last; read back twice. Not reusable as is (all addresses are their build's), but the method works on any stock firmware if we
find our `0xCD` handler and SPI routines (we already know ours: `spi_flash_read 0x020360B4`, `spi_flash_write 0x020361FC`,
`spi_flash_sector_erase 0x02036298`).

## 3. Header checksum and CRC (what the boot ROM checks)

I disassembled the header parser at ROM `0x100478..0x10072C` (AX3295B ROM). The JT5295 ROM (`f5b68ff4…`) has the **same
parser**; it differs only in two ROM-internal addresses (script interpreter `0x1047AC` vs `0x104A68`, cleanup calls), which
are passed in registers. penguin's emulator (`tools/trace_boot_header.py`) and their `docs/STOCK-FIRMWARE.md` agree.

Steps (header = flash sector 0, read to SRAM `0x4A00`):

1. If byte 0 is `0xEB`/`0xE9` (x86 jump, e.g. an SD boot sector) the header starts later in the sector; else at 0.
2. `u16 @+0x02 == 0x0002` and `@+0x04 == "BLDR"`, else fail.
3. Bytes `@0x1FE..0x1FF == 55 AA`, or `u16 @+0x0E == 0xAA55`, else fail.
4. Flags byte `@+0x0A`: if **bit 2 is clear**, the 8-bit sum of all 512 bytes must be 0 (additive checksum). Bit 2 set = skipped.
5. If `u16 @+0x00 != 0`: jump straight into the header (not our case).
6. Load record at `+0x10*(byte@+0x09 + 1)` = `+0x20` for us (`byte @+0x09 = 1`):
   `+0x20` load address, `+0x24` start sector, `+0x28` sector count, `+0x2C` entry address (0 = SRAM 0),
   `+0x30` expected CRC (low 16 bits used), `+0x34/+0x38/+0x3C` (XORed into a ROM state word unless flags bit 1),
   `+0x38` → ROM SPI flag byte (byte `+0x39`), `+0x3C/+0x44/+0x48` → SPI parameters, `+0x40` → **SPR `0x924C` (SPI clock
   divider)**, `+0x4C` = first instruction of the **header hook** (called when flags bit 0 is set).
7. Header hook (our `+0x4C..+0x1D7`): code that calls ROM table interpreters (entry passed in `r3`, sub-entries `r3+8/12/16/24`)
   with inline data tables. The tables hold SPR/value-looking pairs (format not fully decoded, **guess**): `0x8864, 0x17D78400`
   (PLL2 400 MHz?), `0x9084, 0x4E1` (UART 115200 at 144 MHz), `0x9800, 0x701` (timer). Then (`r3+24`, data `0, 1, 0x10`) it
   loads **flash sectors 1..16 (`0x200..0x21FF`) into SRAM 0** (inferred from the data; matches matu's description) and jumps to
   SRAM `0xDD0` (in the bootstrap; matu: the DDR calibration runs from the hook, before the app is loaded).
   Our hook's table differs from the Action and penguin hooks (board-specific PLL/DDR/UART values). **Do not change it.**
8. ROM loads `count` sectors from `start` to the load address (our app: `0x3D2` sectors from `0x2200` to `0x02000000`).
9. CRC: compares SPR `0x9260` (hardware CRC of the SPI read) with `u16 @+0x30`. A mismatch fails **only if byte `+0x39` bit 7
   is set**. Otherwise ignored.
10. Jumps to the entry (`+0x2C`, 0 = SRAM 0 = the bootstrap at flash `0x200`), which calls the application.

Our header (`dumps/mo2947_flash_a.bin`):

| Offset | Ours | Meaning (from the parser) |
|---|---|---|
| `+0x00` | `00 00` | 0 → normal load path |
| `+0x02` | `0x0002` | required |
| `+0x04` | `BLDR` | required |
| `+0x09` | `0x01` | load record at `+0x20` |
| `+0x0A` | `0x05` | bit 0 run header hook, bit 2 **skip header sum** |
| `+0x10` | `"01234567"` | not read by the ROM |
| `+0x18/+0x1C` | `0x3EF`/`0xFEF` | resource area, read by the app only |
| `+0x20/24/28` | `0x02000000`, `0x11`, `0x3D2` | load address, start sector, count |
| `+0x2C` | 0 | entry = SRAM 0 |
| `+0x30` | `0x01234567` | expected CRC = `0x4567` (ignored, see `+0x39`) |
| `+0x38` | `0x00000800` | flag byte `+0x39 = 0x08` → **bit 7 clear → CRC not enforced** |
| `+0x3C` | `0x0313C00F` | SPI parameter (ROM state +28) |
| `+0x40` | `5` | SPI clock divider for loading (Action camera: 3) |
| `+0x44/+0x48` | `0x00080010`, `0x203` | SPI parameters |
| `+0x4C` | `0xD7E177F4` | `l.sw -12(r1),r14`: **first instruction of the header hook, not a checksum** |
| `+0x1FE` | `55 AA` | signature |

**Conclusion: no CRC or checksum must be fixed.** The header sum check is off (flags bit 2) and the CRC is not enforced (byte
`+0x39` bit 7 clear). This holds for our header and for both reference headers (all three have flags `0x05`, `+0x38 = 0x800`).
Our 512-byte sum is 199 (not 0), so **never clear flags bit 2**. If we keep the header sector unchanged, nothing changes.
The fields we may legitimately change are `+0x20` (load address) and `+0x28` (sector count), and only if the load block changes.
The app (`+0x18/+0x1C`) and the SD updater ([[FIRMWARE#SD card update (DestBin.bin)]]) also have no checksum. The "header CRC" mentioned in
the old family notes (from penguin's README) is this optional SPI CRC; penguin's build only checks the emulated parser still
accepts the image. No tool implements the CRC algorithm (it is in hardware: SPR `0x9260`, seeded `0xFFFF` by the SPI init;
polynomial unknown).

## 4. Running code from RAM without flashing

### 4.1 What matu's launcher does (`apxtool/src/apxtool/sdk.py: launch`, `tools/launch.sh`)

1. Stock firmware in mass-storage mode → `0xDA` → wait for `Video050Loader` INQUIRY.
2. Read every RAM reservation of the image (manifest) and require **all zero** (refuses otherwise; `--reclaim-jpeg-ram` backs up
   and zeroes only the JPEG arena).
3. Upload each ELF segment with `0xCB` writes, read each back.
4. Read 8 KiB at `0x02000000` (evicts the data cache, so the new code is in DDR).
5. `0xCB` read of 16 bytes from `0x02000000` with **callback = ELF entry**. This call never returns: the SDK takes over USB.
6. Wait for the SDK's own USB device (`1908:3319`, product "JT5295 SDK Debug", vendor class, APXD protocol) and check its build ID.

Load address `0x02180000` (runtime window 128 KiB), entry `_start` in `startup.S`. Two entries: `_start` (USB launch, sets r7 = 0)
and `apx_spi_entry` (cold boot, r7 = `'SPIB'`). Start-up saves r1/r2/r9 and SR(0x18) in `apx_boot_context`, clears SPR `0x18`
bit 1 (vendor external IRQ), sets its own stack, calls `apx_runtime_init`, then `main`.

### 4.2 What must be initialised (`firmware/sdk/src/runtime.c`, `spi_boot.c`, `clock.c`, `power.c`)

| Item | USB launch (loader running) | Cold SPI boot |
|---|---|---|
| Watchdog | inherited from loader (selector 5, 1.8 s, fed only by the ROM USB IRQ, which the SDK replaces) → feed at once (`0x880C = 0x5000x`) and keep feeding | still armed by the ROM: feed from the first instructions; clear big buffers with word stores, feeding every 64 KiB |
| Caches | stock/loader state | **off**: enable DC (`0x1808 = 0x02000000`, `0x1800 |= 1`) and IC (`0x2008 = 0`, `0x2000 |= 1`), else ~5 % speed |
| PLL | loader pair 96 MHz (`0x8858 = 0x1623`, `0x885C = 0x0B71B000`); switch to 144 MHz (`0x1123`/`0x112A8800`) only from code inside one I-cache line, **after detaching USB** (`0xA004 &= ~0x40`) | the bootstrap already left 144 MHz: do not switch |
| Timer `0x9800` | 0x721 | write 0x721 and retry until it reads back (accepted only ~70-340 ms after reset) |
| PM chip (power hold) | already on | run the stock sequence first (`apx_power_domain_enable`), else the camera switches off when POWER is released |
| ADC reference | on | set `0x8868` bit 15 |
| USB | ROM link is live | full PHY bring-up incl. `0x9840 |= 1`, `|= 4` |
| Return to loader | flush+invalidate DDR in the data cache, caches off, clear `0x18` bits `0x4006`, `0x4800` bit 15, PLL back to 96 MHz, jump ROM `0x10385C` with the saved ROM stack | same, using the stack page the bootstrap saved (Action SRAM `0x1E6C`) |

Exceptions: vectors are in SRAM at 0 with **16-byte slots** (`0x20` bus error … `0xE0` trap). Many faults (illegal opcode,
unmapped load, `l.sys`) do not reach a handler; the chip stalls and the watchdog resets it (`spi-boot-recovery.md`).

### 4.3 Cold boot of an SDK image (`apxtool spi_boot.py`)

Keep `0x000..0x21FF` (header + bootstrap) byte-identical; put the image at flash `0x2200`; patch header `+0x20` (= `0x02180000`),
`+0x28` (sector count) and the bootstrap's application call at flash `0x528/0x52C` (`l.movhi r2,hi(entry)` / `l.ori r2,r2,lo(entry)`)
to the SDK `apx_spi_entry`. The packer refuses any bootstrap whose SHA-256 is not on its list (Action and Silvergear only).

## 5. Toolchain

- matu: patched **GCC 16.2.1 + binutils 2.47 + picolibc 1.8.12**, target `or1k-appotech-elf`, option `-mappotech`
  (little-endian, never fill delay slots, `__OR1K_NODELAY__`, call link PC+4, soft mul/div/float). Pinned commits and patch hashes:
  `appotech-sdk/toolchain/sources.lock.json` (gcc `71b50793…` on branch `gcc16-openrisc-appotech`, binutils `6ce87bbc…` on
  branch `binutils-openrisc-appotech`, picolibc tag 1.8.12). Build: clone both GNU trees into `compilers/`, check out the two
  branches, then `python3 toolchain/build.py binutils|gcc|picolibc|libgcc`; output in `toolchain/install`. The builder only
  applies patches and runs configure/make (`--target=or1k-appotech-elf --disable-nls --disable-multilib --enable-languages=c,c++
  --without-headers --disable-shared --disable-threads …`). Flags: `-mappotech -fno-delayed-branch -fno-pic -ffunction-sections
  -fdata-sections`. Hardware `l.mul/l.div/l.divu` exist and work: link `src/hwmuldiv.S` before libgcc.
- Linker script: `appotech-sdk/linker/ram.ld` (RUNTIME `0x02180000` 128 K, STACK `0x02200000` 16 K, LCD_DMA `0x02210000` 64 K,
  EXTRA `0x02220000` 768 K, LOW_RAM `0x02080000` 512 K, CODEC `0x022E0000` 1152 K). Start-up: `src/startup.S` (shown in 4.1).
  The build writes an ELF, per-segment binaries and a `manifest.json` (segments, SHA-256, reservations, entry, `spi_entry`).
- Payload-only alternative without GCC: hand assemblers in Python (tbelbek `tools/stub_build.py: Asm`, penguin `tools/or1k_subset.py`
  with an emulator). Fine for stubs, not for a firmware.
- Alternative "or1kle" toolchain: none found in these repositories. Upstream `or1k-elf` GCC is big-endian only; penguin notes GNU
  objdump works on byte-swapped words. Building with upstream GCC and byte-swapping would still need no-delay-slot code and PC+4
  call links: not verified by anyone, do not rely on it.

## 6. Recovery procedures

1. **App still reaches USB mass storage**: use `0xDA` and the normal write path to undo the change. A patch that does not touch
   sector 0 or the bootstrap (`0x000..0x21FF`) never breaks the boot ROM path; it can only break the app. If the app no longer
   reaches its USB mode, use 3 (or 4 if the app still runs its SD updater).
2. **Boot ROM forces the loader by itself** if the header is invalid (sector 0 erased): the camera enumerates as `1908:3319`
   in a 2-3 s loop. Catch it, upload the SRAM payload, disable the watchdog, restore (matu `rom-rescue`, our `mo2947_dump.py forced`
   already handles the catching for reads). DDR is not calibrated in this mode: SRAM payload only, 512 B transfers.
3. **Valid header but app hangs**: force the loader by shorting flash pins 2 (DO) and 3 (/WP) during power-on and releasing the short
   as soon as `1908:3319` appears (matu `docs/FLASHING.md`; for a 25Q16 on the JT5295). Battery-powered forced entry was needed on
   the Silvergear (`apxtool/docs/silvergear-printer-backup.md`).
4. **SD card** (our firmware only, [[FIRMWARE#SD card update (DestBin.bin)]]): a full image as `DestBin.bin` is written by the stock updater on boot, header last. Works only while our stock app still runs.
5. **Last resort**: desolder the flash and use an external programmer (penguin `docs/RECOVERY.md`: Pico at 2 MHz; in-circuit reads
   were unreliable because the SoC reads the flash too).
6. **PM chip state**: its registers persist while USB or battery is connected. A wrong value (e.g. reg `0x5A` cleared) can cut USB
   power; matu `rom-rescue pm --apply` rewrites the stock sequence.

## 7. Recommended plan for our camera

### 7.1 Differences to expect (ours vs the matu/tbelbek references)

| Item | MO2947 | Reference | Effect |
|---|---|---|---|
| Flash | `5E4016`, 4 MiB | Action `5E4015` 2 MiB; KDC `5E4016` | matu flasher/SDK refuse writes; change `APX_SPI_JEDEC`/size; tbelbek host check already `5E4016` |
| DDR size | **2 MiB likely** (our bootstrap sets `r1 = 0x021FFFFC`; stale pointer `0x021FEC00` in flash; penguin AX3295B also 2 MiB) | JT5295 4 MiB | matu linker/manifests use `0x02200000..0x023FFFFF` (stack, LCD DMA, codec RAM): **must be moved below `0x02200000`** |
| Bootstrap `0x200..0x21FF` | SHA prefix `f77775869eb28b3a…` (whole `0..0x2200`) | Action `67d86cda…` | `spi_boot.py` refuses; add a board profile |
| Saved ROM stack page | SRAM `0x1A38` (our SPI `0x540`: `l.movhi r4,0 / l.ori r4,r4,0x1a38`) | Action `0x1E6C`, Silvergear `0x1C94` | set `APX_SPI_BOOT_SAVED_STACK = 0x1A38` |
| App call in bootstrap | SPI `0x528/0x52C` → `0x020004A8` (`app_main`) | Action same offset | patch site is the same as Action |
| UART/GPIO setup call | SRAM `0x6C8` (SPI `0x8C8`) | Action SRAM `0x760` | info only |
| Battery calibration word | SRAM `0x1E28` (our bootstrap helper SPI `0x96C`: `mv = 2*adc*cal/ref`) | Action `0x1FEC`, Silvergear `0x1E14` | set `APX_BATTERY_CALIBRATION_ADDRESS = 0x1E28` |
| Header SPI divider `+0x40` | 5 | Action 3 | none (keep header) |
| Panel | NV3030B 240×320 (config at flash `0x7C600`) | ILI9225G 176×220 | new init table; 240×320 like Silvergear's ST7789 path |
| Backlight | PA6 driven by PWM channel 2, 4 kHz ([[analysis/display#9. Backlight — V]]) | GPIO PA6 | same pin; PWM for brightness |
| Sensors | 7 probe entries (SC030IOT, BF20A6, GC0310, BF3A03, GC0309, SP0A39, one unknown); fitted one unknown ([[analysis/camera]]) | SP0A39 | new init tables; the probe tells which one |
| Key ladder | same centres 0/306/484/658/817, ADC channel 3 | same | same |
| LED | port 1 mask `0x20` (= PB5) | PB5 | same |
| Watchdog code | `0x0202701C`/`0x02027064`, same values | same | same |
| PM chip | SPR `0x88E0/0x88EC` used by our firmware | Action sequence | sequence values may differ (Silvergear differs): extract ours |
| Boot ROM | **AX3295B ROM**: 32 KiB, identical to penguin `soc_boot_rom.bin` (`62d4dabe…`) | two variants known | addresses in 1.4 apply; DDR not readable from the loader (7.5) |

### 7.2 Steps (each one read-only unless marked WRITE)

1. **Dump our boot ROM** (64 KiB at `0x00100000`, `0xCB` reads; `kdc_run.py bootrom` does 32 KiB). Compare with `f5b68ff4…`
   (JT5295) and `62d4dabe…` (AX3295B). Expected: one of them. Confirms `0x102620`, the parser and the watchdog behaviour.
2. **Confirm DDR size**, read-only: in the loader after `0xDA`, read 64 B at `0x02000000` and at `0x02200000`; aliasing (equal data,
   twice) means 2 MiB. Risk: an unmapped read may stall → watchdog reset → camera returns to stock (harmless).
3. **Prove "call"**: tbelbek `marker` (writes `0xCAFE`, touches no SPI). Already-proven pattern on KDC; zero flash risk.
4. **Prove write path in blank flash** (WRITE, harmless area): adapt tbelbek's granule preflight to the 64 KiB block
   `0x3F0000..0x3FFFFF` (all `FF` in both dumps, checked). `0x3F0000..0x3FEFFF` is the free tail of the internal photo store
   (`0x27D000 + 0x182000`), `0x3FF000` is outside it. The test leaves the block erased again, so the store sees no change, but
   do it with no photos stored in flash. Read SR1/SR2 (`05`/`35`) first; refuse if any block-protect bits are set.
5. **First real patch** (WRITE): one sector, not sector 0, with a tbelbek-style one-sector window, live==backup gate, erase → blank
   check → program → verify. A constant or an asset in the app area; a bad result still boots the boot ROM and `0xDA` stays
   reachable as long as the stock USB path works.
6. **RAM launch of our own code**: start with a tiny DDR payload through the `0xCB` callback (like matu's marker: upload to free DDR,
   read 8 KiB to flush, call). Then port the SDK with a 2 MiB memory map. Note: matu's launcher requires the reservations to be zero;
   on our camera the stock app's heap lives there, so either zero them after a backup or write our own launcher.
7. **Full replacement** (WRITE, later): our own payload or matu `flasher.c` with `5E4016` allowed; header sector last; full readback.
   Or the SD path (`DestBin.bin`) for a full image while the stock firmware still runs.

### 7.3 What to reuse

- tbelbek `flstub.py` + `kdc_run.py` write logic: already matches our chip and our working dump tool. Change: preflight scratch
  address, our own backup file names, and add a SR1 protection check.
- matu `flasher.c` (C, position independent, SRAM + DDR pools) and `sdk_flash.replace` (journal, header last, full readback):
  best structure for a full write; needs the JEDEC/capacity change and a 4 MiB `CAPACITY`.
- matu SDK as the base of our firmware; port with a new `boards/mo2947/board.h` (memory map, JEDEC, saved stack, battery
  address, panel, sensors, backlight, PM sequence).

### 7.4 Risks

- Sector 0 or the bootstrap (`0x000..0x21FF`) written wrong → no boot; recovery only through the forced loader (flash short).
  Write sector 0 last and only when it really changes (a patch normally does not need it).
- Interrupted power during a write → that sector is lost; keep the battery charged and USB connected.
- The DDR flasher pool is untested on hardware; use the SRAM pool for writes.
- PM chip writes persist across reboots; do not experiment with its registers.
- The internal photo store (`0x27D000..0x3FEFFF`) is live data for the stock firmware; do not use it as scratch while stock runs.

### 7.5 Results on our camera

All on 2026-11-12, unit A, tool `tools/mo2947_probe.py` (logs in `dumps/probe_20261112/`).

| Step | Result |
|---|---|
| Sensor ID (stock `CB F2`, no loader) | **SP0A39**, ID `0x0A39` ([[analysis/camera#3. Probe sequence and how to find the fitted sensor]]) |
| 1. Boot ROM | 32 KiB at `0x00100000`, **identical to the AX3295B ROM** (`62d4dabe…`). `0x00108000`-`0x0010FFFF` reads as a constant (not ROM) |
| 2. DDR size | **Failed**: `0xCB` read of `0x02000000` stalls the loader (tried 4 KiB and 256 B). Observed; cause **I**: the SDRAM is not usable after the `0xDA` path on this ROM/board. SRAM reads and writes work |
| 3. Marker | **OK**: `stub_marker.bin` at SRAM `0x2000`, call with r3 = `0x3900`, read back `0xCAFE` |
| 4. Write test (owner's "go") | **OK**: flstub with write window `0x3F0000`-`0x3F1FFF`. JEDEC `5E4016`; whole 64 KiB block blank before; 4 KiB pattern programmed and read back; `0x20` erased `0x3F0000` and left `0x3F1000` intact (**4 KiB granule confirmed**); both sectors erased again; block blank after; sector 0 equal to the backup before and after |

Behaviour seen:
- When the loader's watchdog fires, the camera does not reboot into the stock firmware. It fails to enumerate (USB error
  `-71`) and **switches off**. Switch it on again to get back to mass storage.
- After flstub runs, the watchdog is off, so a stalled loader stays hung until the camera is switched off.

Effect on the plan: step 6 (RAM launch in DDR, matu's launcher) **does not work as written** on this camera. Either run
small programs from SRAM (below `0x4400`, as the flash stub does), or have our program bring the SDRAM up first (the
bootstrap's SDRAM init in [[analysis/soc_core#9. Bootstrap (flash 0x200) and header hook]]), or load through flash/SD.
