# Camera path: sensor, I2C, CSI, JPEG, photo, video (topic `camera`)

> [!summary]
> **7 sensor probe entries** in the config block (the fitted one is unknown), I²C on PD13/PD15, 8-bit DVP 640×480 YUV422, CSI SPR 0xB000, JPEG units 0xB800/0xC000, the photo and video paths, the internal photo store, and all sensor init tables.

Sources: `analysis/export/all.c` / `all.asm`, raw disassembly of code that Ghidra did not disassemble (my own scratch
disassembler on `dumps/mo2947_app_0x02000000.bin`), the config block in `dumps/mo2947_flash_a.bin` (`0x7C600`-`0x7DDFF`
only). Cross-checked with `analysis/research_registers.md`, `analysis/display.md`, `ext/appotech-sdk/research/camera.md`
and the DOOM SDK `camera.c` (a sibling board with the same SoC and stock SDK).

Tags: **V** = verified in our code (address given), **I** = inferred, **G** = guess.

## 1. Summary

- At boot, `app_init` calls `dev_ioctl(cmos-sensor, 0x2000000F)` -> `sensor_ioctl` `0x02002D0C`: sensor pins, then
  **`sensor_probe_and_init` `0x020485AC`**, then CSI init, then CSI enable. **V**
- The sensor block at flash **`0x7CC9C`** holds **7 probe entries** (not 3). The code tries them in order and uses the first
  whose ID register matches. **V** Entries with a name string: `030iot` (= SmartSens **SC030IOT**), `BF20A6`, `GC0310`.
  Four more entries have no name: BF3A03, GC0309, an unknown SETi(?) part and SP0A39 (IDs below). **V** (IDs), **I** (part names).
- Which sensor is fitted **cannot be told from the flash** (the same image probes all 7). See section 3 for how to find out.
- I2C = **hardware controller** SPR `0x9090`-`0x90A4` on **PD13/PD15**, **200 kHz** in the stock probe. **V**
- Sensor bus = 8-bit **DVP, YUV422** (`type 3` in every entry), **640x480**, MCLK on **PD10** = 288 MHz/(div+1):
  24 MHz (20.6 MHz for SC030IOT). **V**
- No SoC ISP is used: AE/AWB/gamma all run **inside the sensor** (set by the init table). The SoC "ISP" fields exist only for
  raw-Bayer types 0..2, which no entry uses. **V**
- Two hardware JPEG units: **`0xB800`** = camera encoder (fed by CSI or by a RAM frame, with a **hardware up/down scaler**),
  **`0xC000`** = second unit (`BACK_JP*` debug names; playback decode). Same register layout. **V**
- **All photo sizes are upscales of one 640x480 frame** done by the JPEG unit's scaler (`JPXSCALE/JPYSCALE` `0xB87C/0xB880`). **V**
- Photos: `PHOTO/PHOnnnnn.JPG`; file = main JPEG + thumbnail JPEG + trailing **APP9 `FF E9 00 0A "JRX\0" <BE offset>`**
  marker that points to the thumbnail. No `Exif` string or EXIF builder found in the app. **V** (trailer), **I** (no EXIF).
- Without SD card: one **320x240** JPEG (<= 40 KB, re-encoded with lower quality until it fits) per 40 KB slot in the
  internal store at flash `0x27E000` (index `0x27D000`, 38 slots). **V**
- Video: `VIDEO/MOVnnnnn.AVI`, **AVI (OpenDML) with MJPEG video at 30 fps** and **PCM audio 16 kHz mono**; cyclic recording
  by segment length from settings slot 22 (Off = 600 s segments). **V** (fps/rate/size), **I** (PCM format details).

## 2. Hardware config block: sensor part (flash `0x7CC9C`)

All offsets below are relative to `0x7CC9C` (the code hard-codes this base, `0x02048638`). **V** (`0x020485AC`)

Header (`0x7CC9C`, 0x40 bytes read): `{u32 entries_off = 0x40, u32 entries_len = 0x1F8, u32 entry_size = 0x48}` -> 7 entries at
`0x7CCDC`.

### Probe entry (0x48 bytes) **V** (field use in `0x020485AC`, `0x02047218`, `0x02047294`)

| Off | Size | Meaning |
|---|---|---|
| +0x00 | u32 | offset of the 0x60-byte **config struct** (0 = none) |
| +0x04 | u32 | its length (0x60) |
| +0x08 | u32 | offset of the **init table** (0 = no table) |
| +0x0C | u32 | init table length in bytes |
| +0x10..+0x2B | | zero in all entries (unused) |
| +0x2C | char[20] | name (may be empty) |
| +0x40 | u8 | expected **ID value** |
| +0x41 | u8 | I2C write address (8-bit form) |
| +0x42 | u8 | I2C read address |
| +0x43 | u8 | register address bytes (1 or 2; 2 = big-endian) |
| +0x44 | u8 | data bytes per register |
| +0x45 | u8 | 0 |
| +0x46 | u16 | **ID register** |

Special case in the probe: an entry with ID `0xC0`, ID reg 0 and address `0x62` first gets a write `reg 0xFC = 0x16` (none of
our entries). **V** (`0x020486B4`)

### The 7 entries **V** (values), names partly **I/G**

| # | Entry | Name field | Probable part | I2C wr/rd | ID reg -> value | MCLK | Init table (flash, bytes, writes) | Cfg `+0x2C/+0x30` (LDO codes) |
|---|---|---|---|---|---|---|---|---|
| 0 | `0x7CCDC` | — | BYD **BF3A03** (G) | `DC/DD` | `0xFC` -> `0x3A` | 24 MHz | `0x7D174`, 0x118, 139 | 0x14 / 0x14 |
| 1 | `0x7CD24` | — | GalaxyCore **GC0309** (I: `FE=80` soft reset, ID 0xA0 @0) | `42/43` | `0x00` -> `0xA0` | 24 MHz | `0x7D28C`, 0x18C, 197 | 0x0F / 0x03 |
| 2 | `0x7CD6C` | — | unknown; SETi SIV10x/12x-style (G) | `66/67` | `0x01` -> `0x0C` | 24 MHz | `0x7D418`, 0x198, 203 | 0x14 / 0x03 |
| 3 | `0x7CDB4` | `030iot` | SmartSens **SC030IOT** (I: SCCB 0x68 7-bit, PID 0x9A46 at 0xF7/0xF8, `F0` page reg) | `D0/D1` | `0xF8` -> `0x46` | **20 MHz** (actual 20.57) | `0x7D5B0`, 0x178, 187 | 0x0F / 0x03 |
| 4 | `0x7CDFC` | `BF20A6` | BYD **BF20A6** | `DC/DD` | `0xFD` -> `0xA6` | 24 MHz | `0x7D728`, 0x150, 167 | 0x14 / 0x06 |
| 5 | `0x7CE44` | `GC0310` | GalaxyCore **GC0310** | `42/43` | `0xF0` -> `0xA3` | 24 MHz | `0x7D878`, 0x21C, 269 | 0x10 / 0x03 |
| 6 | `0x7CE8C` | — | SuperPix **SP0A39** (I: identical start to the SP0A39 table in the DOOM/luxorparts cameras) | `42/43` | `0x01` -> `0x39` | 24 MHz | `0x7DA94`, 0x25A, 300 | 0x10 / 0x03 |

All entries: 1-byte register, 1-byte data. Tables are `{reg, val}` pairs ending in `FF FF`. The full tables are in the
appendix. Note: the ID is compared as **one byte** only, read from the single ID register.

### Config struct (0x60 bytes, at `0x7CED4 + n*0x60`) **V** for fields used in code, **I** for others

| Off | Value (all 7) | Meaning | Used by |
|---|---|---|---|
| +0x00 | 3 | input type: 3 = DVP YUV422; 0..2 = raw types (enable SoC ISP regs); 0xFF = no sensor/test pattern | `0x02038F10` |
| +0x04 | 24 000 000 (SC030IOT 20 000 000) | MCLK Hz | `0x0202E37C` |
| +0x08..+0x14 | 0 (entry 2: +0x14 = 9) | ISP/clock params for raw types only (`B000[29:26]`, `[25:22]`, bit3, `0x8854`) | `0x02038F10` |
| +0x18 / +0x1C | 640 / 480 | sensor output width/height | `sensor_get_size 0x02031C78` |
| +0x20 | 2 | YUV byte order -> `B000[9:8]` | `0x0202E4EC` |
| +0x24 / +0x28 | 1 / 1 | sync polarities -> `B000` bit 2 / bit 1 | `0x0202E488` |
| +0x2C | 0x0F..0x14 | LDO0 level -> `0x8868[4:0]`, enable bit 5 | `0x02026658(0,lvl,1)` |
| +0x30 | 3..0x14 | LDO1 level -> `0x8868[11:7]`, enable bit 12 | `0x02026658(1,lvl,1)` |
| +0x34 | 0x0F..0x14 | not read by the probe (I: third supply level) | — |
| +0x3C / +0x40 | 42 000 000 / 1120 (BF20A6: 12 000 000 / 500) | not read in the code paths found (G: pixel clock / line length for anti-flicker) | — |
| +0x4C / +0x50 | 0xFF / 25 (SP0A39: 20) | unknown (G: max gain / fps) | — |

The `0x8868` LDO meaning (sensor supply rails) is **I**; the DOOM board writes `0x8868[12:0] = 0x182E` for its SP0A39.

Fallback when nothing matches: entry `0x02065B34` (all zero: no I2C, no table) + config `0x02065B7C`
(`type 0xFF`, MCLK 16 MHz, 640x480, LDO 0x16/0x06, `+0x3C` 48 000 000). Type 0xFF puts the CSI in a built-in pattern mode
(`B000` bit 16, `B020/B024` timing via `0x0202E76C`). **V** (values), **I** (pattern meaning)

## 3. Probe sequence and how to find the fitted sensor

`sensor_ioctl(0x2000000F)` `0x02002D0C` (called from `app_init`) **V**:

1. `sensor_pins_init 0x02002CA8`: PD0 = output **low**, PD1 = output **high**. **V** Meaning **I**: PD0 = PWDN (active
   high), PD1 = RESET# (released). No reset pulse here (the SDK camera of the DOOM board pulses PD0 instead, other wiring).
2. `sensor_probe_and_init 0x020485AC` **V**:
   1. `sensor_set_mclk(16 000 000)`; `i2c_init_200k 0x0203222C`.
   2. Read header + 7 entries from flash. For each entry: copy I2C addr/widths to globals `0x02080AAC..AF`, wait 20 ms,
      `sensor_read_reg(&idreg)`; if `== entry+0x40` -> match.
   3. On match: copy entry to `0x02083420`, config to `0x020833C0`, init table to a stack buffer (max 4112 bytes).
   4. LDOs: `0x02026658(1, cfg+0x30, 1)`, 1 ms, `0x02026658(0, cfg+0x2C, 1)`, 1 ms; `sensor_set_mclk(cfg+4)`.
   5. Write the table pair by pair with `sensor_write_reg`; **10 ms delay after the first write** (soft reset).
   6. `sensor_set_active(cfg, entry) 0x02031C44` (stores `0x02082E24` / `0x02082E20`).
   7. If ID = 0x76 (an OmniVision entry, not present here): mirror/flip via `0x02048524`.
3. `csi_init_once 0x02039368` -> `csi_configure_from_params 0x02038F10`; `0x0202E2C4` (`B014 = 0x8002F818`);
   `csi_enable(1) 0x0202EE04`.

**Which one is fitted? SP0A39 (entry #6), verified on the device on 2026-11-12.** The stock `CB F2` read (CDB[1] = `F2`,
CDB[5] = register, 6-byte reply) returned reg `0x00` = `0x0A`, reg `0x01` = `0x39`: chip ID `0x0A39`. The other ID
registers did not match (`0xFC`=`0x50`, `0xF8`=`0x00`, `0xFD`=`0x00`, `0xF0`=`0xFF`). Module ribbon: `XS09B5-X100R`. Tool:
`tools/mo2947_probe.py sensor`. The DOOM/luxorparts cameras use the same sensor, so their SP0A39 code applies.

Earlier hints (kept for reference): the three entries with names were probably added for this product
(the four nameless ones look like SDK defaults); the build string `JPY-V3.0-0329-030A` contains "030A", but a GalaxyCore
GC030A (ID `0x030A` at `0xF0/0xF1`) would not match any entry and would end in the fallback test pattern, so the camera
working means one of the 7 is fitted. **G**

Ways to find out on the device, from least to most invasive:
1. Look at the sensor flex/module marking (needs opening).
2. **Stock USB vendor SCSI command** (mass-storage mode, `msc_vendor_scsi 0x0203F708`, **V** in code, untested):
   CDB `CB F2 .. .. 00 <reg> ...` with a 6-byte data-in phase reads one sensor register through the **detected** sensor's
   I2C address (`0x02080AAF`); the reply is `{CB, F2, v>>24, v>>16, v>>8, v}`. CDB byte 5 = register (8-bit register
   sensors; CDB bytes 4-5 for 16-bit). `CB F1` (no data) writes: CDB byte 5 = reg, byte 9 = value.
   Read `0xF0` (GC0310 -> `A3`), `0xFD` (BF20A6 -> `A6`), `0xF8` (SC030IOT -> `46`), `0x01` (SP0A39 -> `39`),
   `0x00` (GC0309 -> `A0`), `0xFC` (BF3A03 -> `3A`). Whichever answers with its own ID is the fitted one.
   (Exact CDB byte that holds `F2` is **I**: the handler compares a field `0x020832CC` that is filled from the CDB.)
3. Our own RAM code: run the probe loop below and print the result, or read RAM `0x02083460` (entry ID) after the stock
   probe if a RAM dump of the running firmware is possible.

## 4. I2C (sensor control bus) **V**

Hardware controller; pins PD13/PD15 (mux `0x8348[2:0] = 3`), set in `i2c_hw_init(freq) 0x0202A594`:
`0x8348` sel 0x12 = 3 (`0x020270B4`), PD13/PD15 configured (`0x8380`, `0x8100`, `0x8000` set; `0x8040` PD13 = 0, PD15 = 1;
pulls), `0x9090 = 144 000 000 / (5*freq) - 1` (200 kHz -> 143), `0x9094 |= 0x80` (enable).

| SPR | Use |
|---|---|
| `0x9090` | clock divider |
| `0x9094` | bit 7 enable |
| `0x9098` | received byte |
| `0x909C` | byte to send |
| `0x90A0` | command: `0x80` start, `0x40` stop, `0x10` send, `0x28` receive + NACK; write `|1` to clear done |
| `0x90A4` | status: bit 0 done, bit 7 = NACK |

| Address | Name | Signature / behaviour |
|---|---|---|
| `0x0202A594` | `i2c_hw_init` | `(u32 hz)` |
| `0x0203222C` | `i2c_init_200k` | `()` init at 200 kHz + stop |
| `0x0202A698` | `i2c_start` | `0x90A0 = 0x80` (no wait) |
| `0x0202A740` | `i2c_send_byte` | `(u8)`; waits done |
| `0x0202A6F4` | `i2c_get_ack` | returns 1 if ACK (`!(0x90A4 bit7)`) |
| `0x0202A790` | `i2c_recv_byte_nack` | returns byte |
| `0x0202A6B4` | `i2c_stop` | waits done |
| `0x020323CC` | `i2c_write_reg8` | `(u8 dev, u8 reg, u8 *buf, u8 n)`; busy flag `0x0207F1F4` |
| `0x0203248C` | `i2c_read_reg8` | `(u8 dev, u8 reg, u8 *buf, u8 n)`: start, dev, reg, stop, start, dev|1, n x recv, stop |
| `0x020326CC` / `0x02032798` | 16-bit register variants (I) | `(dev, u16 reg, buf, n)` |
| `0x02047218` | `sensor_write_reg` | `(u8 *p)`: `p = {reg, val}` (or `{regH, regL, val}`), uses detected address |
| `0x02047294` | `sensor_read_reg` | `(u8 *reg) -> u32` |

No timeouts in stock code (endless wait on `0x90A4` bit 0).

## 5. Sensor clock, power, pins **V**

- MCLK `sensor_set_mclk 0x02031C24` -> `0x0202E37C(hz)`: `0x8850` bit 26 off/on; mux `0x8348` sel 0xF = 2 (bits 11:10);
  PD10 function + output; `0x8848` bit 5 = 0; `0x884C[12:8] = 288 000 000/hz - 1`.
- DVP pins `0x0202E2F8`: PD10 output; PD `0x5BFC` input; `0x8100`(PD) `0x5FFC` set. CSI clock gate `0x8840` bit 27 cleared
  (`clk_gate_set(27,1) 0x0202683C`; `0x8840` is active-low).
- LDO/aux `0x8868`: `0x02026658(sel, level, on)`: sel 0 -> bits 4:0 + bit 5; sel 1 -> bits 11:7 + bit 12; sel 2 -> bits 20:16 +
  bit 15; sel 3 -> bits 14:13; sel 4 -> bit 21; sel 5 -> bit 10. Level > 0x16 on sel 0 also sets bit 6 and a PMU bit
  (`0x0202A1AC`).
- Interrupts: PICMR `0x4800` via `pic_irq_enable(n,on) 0x0202616C`: **14 = CSI**, **16 = JPEG `0xB800`**, 18 = mic ADC.

## 6. CSI (`0xB000` block) and preview scaler **V** (functions), meanings partly **I**

| SPR | Use (our code) |
|---|---|
| `0xB000` | ctrl: bit 0 enable; bit 1/2 sync polarity; bit 3; bits 7:6 / 11:10 input type; bits 9:8 YUV order; bit 5, bit 16 (pattern), bits 15:12; bits 29:22 raw params |
| `0xB004` | bit 4 (raw), 16 crop enable, 17 preview scaler, 18/19 decimation, 21 |
| `0xB008` | bit 19 scaler latch (`0x0202EDA0` returns 1 when cleared) |
| `0xB00C` | W1C status: bit 0 frame done (DMA B), 1 scaled done, 3 frame start, bits 0-9 have callbacks; 15; error mask `0x000E0970` |
| `0xB014` | IRQ enables, bit 31 master (`0x8006F839` DMA B, `0x80060B39` DMA A, `0x8008005A` scaled, bits 17/18 JPEG link) |
| `0xB018` | bit 16, 17, 18 one-shot scaled DMA, **19 frame DMA / JPEG link**, 20, 21 |
| `0xB01C` | `(h-1)<<16 | (w-1)` |
| `0xB020/0xB024` | pattern timing (type 0xFF) |
| `0xB028/0xB02C` | crop `x_end<<16|x_start`, `y_end<<16|y_start` (digital zoom) |
| `0xB030/0xB034` | preview crop ends |
| `0xB038/0xB03C` | decimation 1/2,1/3,1/4 (downscale path) |
| `0xB040..0xB04C` | DMA A: Y, UV, lines, lines*pitch |
| `0xB050..0xB05C` | DMA B: Y, UV, lines (11 bits), lines*align32(w) |
| `0xB060/0xB064` | scaled preview output Y / UV |
| `0xB068` | preview pitch |
| `0xB180..0xB188` | scaled `(h<<16)|w`, `(in<<16)/(out/2)` x and y |
| `0xB18C..0xB1E8` | 24 filter words, from the LCD entry `+0xCC` (`0x7C704`) |

Frame format: YUV 4:2:0 semi-planar, Y plane then interleaved chroma at `Y + w*h` (buffer `w*h*3/2`; NV21 per SDK). **V** (sizes), **I** (order)

CSI ISR `csi_isr 0x0202DEFC`: for each set bit 0..9 of `0xB00C` clear it and call `g_csi_irq_cb[i]` (`0x0207F188`,
set by `csi_set_irq_callback(i, fn) 0x0202E18C`); error bits restart DMA; >100 errors -> endless loop (hang).

Preview: `preview_start 0x02032E94(sensor_w, sensor_h, ?)` -> `csi_preview_scaler_setup 0x0202E928` (crop, size, ratios,
24 filter words from the LCD struct, pitch), `0xB018` bit 17 off / bit 21 on, `csi_set_scaled_dest(y,uv) 0x0202E81C`, wait
latch, `csi_scaled_dma_enable(1) 0x0202E848`. Output goes to the display layer buffers (see `display.md`).

## 7. JPEG encoder (`0xB800`) **V**

Layout = `BACK_JP*` names (found as a debug dump at `0x0202FC04` that prints `0xC000+off`): `+00 JPCON1, +04 CON2,
+08 CON3, +0C SIZE0, +10 OBAS, +14 OEND, +18 OPTR, +1C OLTA, +20 IYADR, +24 IUVADR, +28 IPTR, +2C UBIT, +30 HCNT,
+34 DRI, +38 BSHADDR, +3C INTCON, +40 FLG, +44 LS, +48 ES, +4C COM, +50 TINF, +54..+5C T0-2SIZE, +60..+68 T0-2POS,
+6C..+74 T0-2BASE, +78 SIZE1, +7C XSCALE, +80 YSCALE, +A4 ELINECNT, +A8/+AC DC crop, +B0 FLG_CLR, +B4 PAUSECNT,
+B8/+BC DC Y/UV base, +C0 DMAOUTX32, +144 DCTIMER, +148 DEBLOCK`. T0..T2 (`0xB850..0xB874`, also `0xC050..`) are
overlay layers (I: date stamp).

| Function | Address | What it writes |
|---|---|---|
| `jpeg_enc_init(mode, qset)` | `0x02030860` | reset pulse `0x8880` bit 0; clock `0x8840` bit 26 on; tables; coefficients `0xB884..0xB8A0`, `0xB8C4..0xB940`; `JPCON1 = 0x0040E801`, bit 10 = mode; `INTCON = 0x80000055`; `B8A4 = 0`; `FLG_CLR = ~0`; `HCNT(0xB830) = 0x03000258` |
| `jpeg_enc_load_tables(qset)` | `0x0202B654` | quant luma -> SRAM `0x64000`, chroma -> `0x64040` (zigzag `0x02064230`); `0x02063970+0x80` (0x380 B) -> `0x64080`; `0x02063D70..` (0x440 B) -> `0x64800`. qset 0 = tables `0x020641B0/0x020641F0` (~IJG q50), 1 = `0x02063970/0x020639B0` (coarser) |
| `jpeg_enc_set_input(y, uv)` | `0x02030844` | `0xB820/0xB824` |
| `jpeg_enc_set_scale(sw, sh, dw, dh)` | `0x020305DC` | `SIZE0 = dw<<16|dh`, `SIZE1 = min<<16|min`, `XSCALE = (sw/dw)<<16 | ceil(frac)`, `YSCALE` same |
| `jpeg_enc_set_qindex(q)` | `0x02030684` | `JPCON1[26:23]` |
| `jpeg_enc_set_b800_20_19(n)` | `0x020307E0` | `JPCON1[20:19]` (1 = CSI line mode, 0 = from RAM; I) |
| `jpeg_enc_set_output(start, end)` | `0x020303B0` | `OBAS = start`, `OEND = end | 0x30000000` (cache flush first) |
| `jpeg_enc_get_out_ptr()` | `0x02030828` | reads `OLTA 0xB81C` |
| `jpeg_enc_link_csi(on)` | `0x020303FC` | on: `B014 |= 0x60000`, `B018 |= 0x80000`, `JPCON1 |= 0x100`, IRQ16 on. off: `JPCON1 |= 0x200`, `INTCON` bit 11 off, `B018 &= ~0x180000`, `FLG_CLR = ~0` |
| `jpeg_enc_start_frame()` | `0x02030A98` | `ELINECNT = 0`, `JPCON1 |= 0x100`, `ELINECNT = 8`, `= 0x320` |
| `jpeg_enc_wait_done()` | `0x02030140` | polls `JPFLG 0xB840` (bit 0 done, 0x40, 0x88 error), clears via `0xB8B0`; -1 on error/timeout |
| `jpeg_enc_isr` | `0x020300EC` | reads `0xB840`, calls `g_jpeg_cb` (`0x0207F1E0`, set by `0x02030324`), clears |
| `jpeg_quality_to_index(q)` | `0x02038754` | finds q in `{15,14,13,12,11,10,9,0,6,4,3}` (`0x02064928`) -> index 0..10 (default 10); also sets the output frame budget |
| `jpeg_enc_rate_control` | `0x020306FC` | video: index +/-1 by frame size |

Quality used: photos `q = 15` -> index 0 with table set A; video VGA/720P default q (-1 -> index 10), 1080P q = 15, set B
when width > 1280. Internal-store photos start at q = `0x020772EC[7] = 3`. **V** (values), absolute JPEG quality unknown.

## 8. Taking a photo (V, PhotoEncode task 3)

Shutter event `0x26` -> `PhotoEncode_on_shutter 0x02009228`: if SD present (`0x020818E9 != 0`) -> `photo_take_sd`,
else if free internal slots (`photostore_free_slots 0x020368AC`) -> `photo_take_internal`, else message 203 "SPI is full".

`photo_take_sd 0x02007604`:
1. `size = settings_get_value(26)` (W<<16|H, e.g. 7680x5760), `stamp = settings_get_value(16)` (Date Stamp).
2. `photo_open_new_file 0x020074FC`: next index, `PHOTO/PHO%05u.JPG` (`media_build_filename 0x02000F28`, digits
   `0x020005D8`; prefix `MOV`/`PHO`/`MIC`, `LOK` when locked; dirs `VIDEO/`, `PHOTO/`, `AUDIO/`).
3. Sizes 48M..12M -> `photo_encode_big_tiled 0x02046BA8` (four quadrant temp files `UL/UR/LL/LR`, then merged; I).
   Smaller -> `photo_encode_to_file 0x020444B8(fd, W, H, 15, stamp, flag)`.
4. close, update free space `0x0200C58C`, add to file list `0x02001724`.

`photo_encode_to_file 0x020444B8`:
1. `capture_set_frame_dims 0x02039458`, `capture_alloc_buffers(1) 0x020391C4`: frame `w*h*3/2` at `0x02081978` (Y) /
   `0x0208197C` (UV); bitstream buffer = most of the free heap (`0x02081998`, size `0x0208199C`).
2. `photo_capture_start(W, H, q, stamp, mode) 0x02039DE4` (upscale path, W>=640 and H>=480): `jpeg_enc_init(1, setA)`,
   input = frame buffer, **digital zoom crop** `crop = sensor * (100 - zoom*5/3) / 100` (zoom `0x020818EF`) via
   `csi_crop_scale_setup 0x0202EB04`, `jpeg_enc_set_scale(crop_w, crop_h, W, H)`, `csi_dma_b_setup(Y, UV, 480, crop_w)`,
   qindex, date stamp `0x02042C70`, output window 0x14000 B, CSI IRQ0 cb `0x020386D4`, JPEG cb `0x02038A80`,
   `B018 |= 0x80000`, `csi_enable(1)`.
3. Wait <= 1500 ms for `photo_capture_done 0x02039A4C` (one frame in RAM).
4. `csi_enable(0)`, shutter sound (`0x02005DD0(51)`), `photo_capture_post 0x02039A6C`, `jpeg_enc_start_frame`, IRQ16 on.
5. Loop <= 3000 ms: `jpeg_out_get_frame 0x0203A71C(...)` -> `fs_write 0x0205A838`, `jpeg_out_release_frame 0x0203A88C`;
   then writes the thumbnail chunks (`0x020394C0(i)`, sizes 0xC800/0x19000) and the 12-byte `JRX` trailer (`0x02039514`).
6. `csi_enable(1)` (back to preview), free (`0x020393CC`).

`photo_take_internal 0x02007828`: same capture at **sensor size**, then `0x0203B2FC(frame, 320, 240, q, &out, &len)`
re-encodes to 320x240, lowering the quality index until `len <= 0xA000`, then `photostore_add(out, len) 0x020363C4`.

### Internal photo store **V** (`0x020363C4`)

RAM copy of the index at `0x0207F4C0` (= flash `0x27D000`, 4016 bytes): `{u32 base 0x27D000, u32 size 0x182000,
u32 max 0x26, u32 count, {u32 flash_addr, u32 number} [count]}`. Slots are 40 KB (`0xA000`) from `0x27E000`; a photo is
written as whole 4 KB sectors (erase + 256-byte page writes), then the index sector is erased and rewritten. Numbers wrap
after 9999. Leftover bytes in a sector come from the RAM buffer (explains the non-erased tail seen in the dumps).

## 9. Video recording **V** (`VideoRecord` task 2)

- `VideoRecord_enter 0x0200D308` builds a config and calls `record_config 0x02042D08`: fps **30**, date stamp (slot 16),
  audio on/off (slot 23, hidden, "On"), cyclic length (slot 22; Off -> 600 s and no cycling), size (slot 14), quality 15
  for 1080P else default, file callback `0x0200CCF4`. `record_set_param(key, val) 0x02043D50` changes single fields
  (2 length, 4 stamp, 5 audio, 6 size, 7 quality, 8 hi-res-disable flag `0x0208337C` read by `settings_get_value`,
  9 fps).
- `record_start 0x0204329C`: open file + AVI header (`0x02042EEC` -> `0x02057228(avi, fd, w, h, fps, 1 ch, 16000 Hz)`),
  audio ring `0x020368D8`, `0x0203941C(w,h)`, `capture_alloc_buffers(0)`, **`mjpeg_stream_start(w, h, q, stamp)
  0x0203A1E0`**, `mic_record_start(16000, ...) 0x02037FE4`.
- `mjpeg_stream_start`: if the target is smaller than the sensor -> CSI decimation + DMA A + `jpeg_enc_init(1,1)`;
  else (VGA/720P/1080P) -> crop (digital zoom), DMA B line mode, `jpeg_enc_init(0, w>1280)`, scaler upscales to w x h.
  JPEG callback `0x02038840` queues each frame.
- `record_service 0x02043628` (from `VideoRecord_service`): takes JPEG frames (`0x0203A71C`) and audio blocks
  (`0x02038108`), writes `00dc`/`01wb` chunks + index (`0x020573A8`), `JUNK` padding to 32 KB clusters; restarts a new
  file (`record_restart_segment 0x0204353C`) when the segment length is reached or space is low (cyclic delete via the
  file callback; I).
- AVI writer `0x02057xxx-0x02059xxx` (fourccs built with `l.movhi/l.ori`: `RIFF`, `movi`, `vids`, `auds`, `00dc`,
  `JUNK`, OpenDML `odml` strings). **V** (fourccs present), codec fourcc `MJPG` **I**.
- Microphone ADC `0x9100`-`0x9120`, IRQ 18: `mic_set_samplerate 0x0202B55C` (16000/32000/8000 cases on `0x9100`,
  `0x9104 = 0x007C0002`), `0x0202B3DC(7,7,7)` gains (`0x9110 = 0x780A00xx`, `0x9118` bits 31:20), `0x0202B34C`
  (`0x911C = 0x40003000`, `0x9120 = 0x01007800`), DMA `mic_set_dma 0x0202B458(buf, len)` (`0x9108` addr,
  `0x910C` = len/4-1), `mic_enable 0x0202B254`. Details belong to the audio report.

USB webcam mode uses the same engine: `uvc_mjpeg_start(w, h, q=15) 0x02039AD4` with sizes `{640x480, 320x240, 160x120}`
(`0x02064D0C`).

## 10. Other sensor control **V**

- `sensor_set_effect(mode) 0x0204756C` (modes 0..5, normal/colour effects): per-ID register writes for IDs
  `0xA0/0x9B, 0x36, 0xC0, 0x76, 0x0C, 0x3A, 0x46, 0x39, 0xA6`; **no case for GC0310 (0xA3)** -> no effect on it.
- No AE/AWB/exposure code on the SoC side was found: the sensor runs its own ISP.

## 11. API for our firmware

### Stock functions (call with OR1K ABI, args r3..r8, RAM image must be the stock one)

| Address | Call | Notes |
|---|---|---|
| `0x02002D0C` | `sensor_ioctl(0x2000000F, 0)` | full bring-up: pins, probe, table, CSI init + enable |
| `0x020485AC` | `sensor_probe_and_init()` | needs heap (`mem_alloc`) and ~5 KB stack |
| `0x02047218` / `0x02047294` | `sensor_write_reg(u8 p[2])`, `u32 sensor_read_reg(u8 *reg)` | after the probe |
| `0x020323CC` / `0x0203248C` | `i2c_write_reg8(dev, reg, buf, n)`, `i2c_read_reg8(dev, reg, buf, n)` | any device |
| `0x02031C78` | `int sensor_get_size(u16 *w, u16 *h)` | |
| `0x0202EE04` | `csi_enable(on)` | |
| `0x02032E94` | `preview_start(w, h, ?)` | needs the display layer globals |
| `0x02039DE4` + `0x02039A4C` + `0x02039A6C` + `0x02030A98` + `0x0203A71C` | capture one frame and JPEG-encode it | as in `photo_encode_to_file` |
| `0x020444B8` | `int photo_encode_to_file(int fd, u16 w, u16 h, u8 q, u8 stamp, u8 flag)` | complete photo to an open file |
| `0x02007604` | `photo_take_sd()` | everything, uses settings |
| `0x020363C4` | `photostore_add(void *jpg, u32 len)` | internal flash store |

### Raw sequence to do it ourselves (640x480 frame to RAM)

Stock values; the DOOM SDK `camera.c` uses the same registers and works on its board.

```
// clocks, MCLK 24 MHz on PD10
0x8850 &= ~(1<<26); 0x8850 |= 1<<26
0x8348 = (0x8348 & ~0xC00) | 0x800          // PD10 = MCLK, DVP group
PD10: 0x810C |= 0x400; 0x804C &= ~0x400
0x8848 &= ~0x20; 0x884C = (0x884C & ~0x1F00) | (11<<8)
// sensor power pins (stock): PD0 = 0, PD1 = 1 (outputs: latch 0x800C, then clear 0x804C bits)
// LDOs from the cfg struct: 0x8868 = (0x8868 & ~0x1FFF) | (l1<<7)|(1<<12)|l0|(1<<5)   e.g. GC0310 l0=0x10 l1=3
// I2C on PD13/PD15
0x8348 = (0x8348 & ~7) | 3
0x838C |= 0xA000; 0x810C |= 0xA000; 0x800C |= 0xA000; 0x804C = (0x804C & ~0xA000) | 0x8000; 0x808C |= 0xA000
0x9090 = 143 (200 kHz) or 71 (400 kHz); 0x9094 |= 0x80
// write reg: 0x90A0=0x80; send(dev); send(reg); send(val); 0x90A0=0x40, wait
//   send(b): 0x909C=b; 0x90A0|=0x10; wait(0x90A4 bit0); 0x90A0|=1; NACK = 0x90A4 bit7
// read reg: start,dev,reg,stop; start,dev|1; 0x90A0|=0x28; wait; byte=0x9098; stop
// probe: for each entry read ID reg, compare; then write the table (10 ms after the 1st pair)
// CSI
0x8840 &= ~(1<<27)                           // CSI clock on
PD: 0x804C = (0x804C & ~0x5FFC) | 0x5BFC; 0x810C |= 0x5FFC; 0x81CC/0x820C &= ~0xFFFF (SDK)
0xB000 = 0x286                               // type 3 (bits 7:6 = 2), order 2 (bits 9:8), polarity bits 1,2
0xB004 = 0; 0xB01C = (479<<16)|639
0xB050 = Y; 0xB054 = Y + 640*480; 0xB058 = 480; 0xB05C = 640*480
0xB00C = 0xFFFFFFFF; 0xB014 = 0x8006F839; 0xB018 = 1<<19; 0xB000 |= 1
wait 0xB00C bit 0 (frame done; error mask 0x000E0970); then 0xB000 &= ~1, 0xB018 = 0
```

JPEG from RAM (sketch, from `photo_encode_to_file` + `jpeg_enc_init`): `0x8840 &= ~(1<<26)`; pulse `0x8880` bit 0;
load tables to SRAM `0x64000`; coefficient SPRs as in `0x02030860`; `0xB800 = 0x0040E801 | (bit10 if mode)`;
`0xB83C = 0x80000055`; `0xB820/0xB824 = Y/UV`; `jpeg_enc_set_scale(640,480,W,H)` registers; `0xB800[26:23] = qidx`;
`0xB800[20:19] = 0`; `0xB810 = out; 0xB814 = end | 0x30000000`; `0xB8B0 = ~0`; `0xB8A4 = 0; 0xB800 |= 0x100;
0xB8A4 = 8; 0xB8A4 = 0x320`; poll `0xB840` bit 0; length = `0xB81C - out`. The produced stream probably needs the header
(SOI/DQT/DHT/SOF) added by software (I: the stock `0x0203A71C` frame queue was not fully decoded).

## 12. Open questions

- Which sensor is fitted (section 3). Is the SCSI `CB F2` read available in the MSC mode of our unit?
- Exact role of `0x8868` levels (voltages) and of cfg `+0x34..+0x50`.
- PD0/PD1 polarity meaning (PWDN vs RESET).
- Whether the JPEG unit writes the JFIF headers itself or software prepends them (`0x0203A71C`, `0x0203B6F0`, `0x0203B7E8`).
- Big-photo quadrant merge (`0x02046BA8`, `0x02045908`, `0x02045E44`) not decoded.
- No EXIF builder found. This agrees with the real file `PHOTO/PHO00000.JPG`: it has no EXIF block, and its 7680x5760 size
  is in the JPEG frame header ([[FIRMWARE#Photos and video]]).
- Functions not disassembled by Ghidra used here: `0x020074FC`, `0x02007604`, `0x02007828`, `0x0200725C`, `0x02009228`,
  `0x02039A4C`, `0x02039A6C`, `0x02039DE4`, `0x0203B2FC`, `0x020363C4`, `0x020368AC`, `0x020444B8`, `0x02046BA8`,
  `0x020407A8` (UVC start), `0x020394C0..0x02039514`.

## Appendix: sensor init tables (reg=val, 8-bit reg / 8-bit data, written in order, end marker FF FF not shown)

### #0 BF3A03 (guess; ID 0x3A @0xFC, I2C 0xDC) flash 0x7D174 - 139 writes

```
12=80 09=78 15=32 1e=70 06=78 21=00 3e=37 29=2b 27=98 16=2f 20=64 d2=18 11=1c 2f=4e 1b=09 3a=00 4a=98 12=00 13=08 01=1a
02=15 8c=02 8d=4c 87=16 13=07 35=46 65=38 66=42 70=0f 3b=00 71=0c 73=27 75=88 76=d8 77=0a 78=ff 79=14 7a=64 9e=04 7d=2a
39=a0 3f=a0 90=20 5f=04 40=22 41=23 42=28 43=25 44=1d 45=17 46=13 47=12 48=10 49=0d 4b=0b 4c=0b 4e=09 4f=07 50=06 13=07
24=60 97=40 25=88 81=ff 82=18 83=30 84=20 85=38 86=90 94=62 80=92 98=8a 89=2d 8a=73 8b=60 8e=2c 8f=82 5a=ec 51=90 52=10
53=8d 54=88 57=82 58=8d 5a=7c 51=80 52=04 53=8d 54=88 57=82 58=8d 5a=6c 51=93 52=04 53=8a 54=88 57=02 58=8d b0=a0 b1=26
b2=1c b4=fd b0=40 b1=e0 b2=c2 b4=f1 3c=40 56=52 4d=40 59=40 b4=f1 6a=d1 23=33 a1=3f a2=0b a3=2b a4=08 a5=26 a7=1e a8=13
a9=20 aa=15 ab=16 ac=3c ad=f0 ae=57 c5=66 c7=38 c8=0d c9=18 d3=09 d4=15 d0=00 35=38 65=38 66=38 96=b5 9f=64 d1=00
```

### #1 GC0309 (guess; ID 0xA0 @0x00, I2C 0x42) flash 0x7D28C - 197 writes

```
fe=80 fe=00 1a=26 d2=10 22=55 5a=56 5b=40 5c=4a 22=57 e2=00 e3=64 03=01 04=2c e4=02 e5=8f e6=02 e7=8f e8=02 e9=8f ea=05
eb=dc 05=00 06=00 07=00 08=00 09=01 0a=e8 0b=02 0c=88 0d=02 0e=02 10=26 11=0d 12=2a 13=00 14=13 15=0a 16=05 17=01 1b=03
1c=49 1d=98 1e=20 1f=16 20=ff 21=f8 24=a2 25=0f 26=03 2f=01 30=f7 31=60 32=00 39=04 3a=20 3b=20 3c=02 3d=02 3e=02 3f=02
50=24 53=82 54=80 55=80 56=82 8b=22 8c=20 8d=20 8e=10 8f=10 90=10 91=3c 92=50 5d=12 5e=1a 5f=24 60=07 61=0e 62=0c 64=03
66=e8 67=86 68=a2 69=20 6a=0f 6b=00 6c=53 6d=83 6e=ac 6f=ac 70=15 71=43 72=dc 73=80 74=02 75=3f 76=02 77=54 78=88 79=81
7a=81 7b=22 7c=ff 93=48 94=00 95=05 96=e8 97=40 98=f8 9c=00 9d=00 9e=00 b1=40 b2=40 b8=20 be=36 bf=00 d0=cb d1=10 d3=50
d5=f2 d6=16 db=92 dc=a5 df=23 d9=00 da=00 e0=09 ec=20 ed=04 ee=a0 ef=40 9f=0e a0=1c a1=34 a2=48 a3=5a a4=6b a5=7b a6=95
a7=ab a8=bf a9=ce aa=d9 ab=e4 ac=ec ad=f7 ae=fd af=ff c0=00 c1=0b c2=15 c3=27 c4=39 c5=49 c6=5a c7=6a c8=89 c9=a8 ca=c6
cb=e3 cc=ff f0=02 f1=01 f2=00 f3=30 f7=04 f8=02 f9=9f fa=78 fe=01 00=f5 02=1a 0a=a0 0b=60 0c=08 0e=4c 0f=39 11=3f 12=72
13=13 14=42 15=43 16=c2 17=a8 18=18 19=40 1a=d0 1b=f5 70=40 71=58 72=30 73=48 74=20 75=60 fe=00 d2=90
```

### #2 unknown (ID 0x0C @0x01, I2C 0x66) flash 0x7D418 - 203 writes

```
03=02 04=03 05=07 06=00 07=00 08=00 09=00 0a=00 0b=00 0c=00 0d=00 0e=00 0f=00 10=13 11=04 12=0a 13=1f 14=17 15=00 16=89
17=60 18=16 19=00 1a=00 1b=90 1c=00 1d=00 1e=00 1f=52 20=00 21=a0 22=7c 23=00 24=a0 25=7d 34=7d 33=05 35=7d 36=7d 37=7d
38=00 39=00 3a=00 3b=00 3c=00 3d=00 3e=00 3f=00 40=81 41=78 42=78 43=c0 44=38 45=28 46=08 47=15 48=1e 49=13 4a=63 4b=c4
4c=3c 4e=17 4f=8a 50=94 5a=00 60=c0 61=88 62=01 63=80 64=80 65=d0 66=8c 67=e8 68=8b 69=8a 6a=73 6b=a0 6c=70 6d=88 6e=77
6f=46 70=ea 71=60 72=05 73=02 74=0a 75=0f 76=20 77=b7 78=b5 80=af 81=19 82=3d 83=00 84=ff 85=00 86=a1 87=00 88=24 89=0f
8a=80 8b=80 8c=80 8d=80 8e=00 8f=00 90=00 91=00 92=44 93=10 94=20 95=18 96=10 97=20 98=20 99=18 9a=50 9b=00 9c=0d 9d=0d
9e=0d 9f=0d a0=10 a1=10 a2=10 a3=10 a4=cc a5=cc a6=cc a7=cb a8=a9 a9=43 aa=45 ab=11 ac=13 ad=00 ae=00 af=98 b0=90 b1=00
b2=0d b3=16 b4=2a b5=48 b6=64 b7=79 b8=8c b9=9c ba=aa bb=b6 bc=cb bd=de be=f0 bf=f8 c0=ff c1=3a c2=cb c3=fb c4=10 c5=21
c6=10 c7=f3 c8=bd c9=50 ca=90 cf=20 d0=20 d1=28 d2=86 d3=00 cb=40 cc=28 cd=06 ce=06 d4=12 d5=16 d6=18 d7=04 d8=00 d9=00
da=00 db=ff dc=00 dd=ff de=00 df=ff e0=00 e1=27 e2=8a e3=00 e4=00 e5=00 e6=44 f0=24 f1=00 f2=80 f3=00 f4=e0 03=c5 7a=a8
7b=b0 7c=80 40=80
```

### #3 SC030IOT (name "030iot"; ID 0x46 @0xF8, I2C 0xD0) flash 0x7D5B0 - 187 writes

```
f0=30 01=ff 02=ff 22=07 19=ff 3f=82 30=02 f0=01 70=00 71=80 72=20 73=00 74=e0 75=10 76=81 77=8c 78=e1 79=31 7a=06 f5=01
f4=0a f0=36 37=79 31=82 3e=60 30=f0 33=33 f0=32 48=02 f0=33 02=12 7c=02 7d=0e a2=04 5e=06 5f=0a 0b=58 06=38 f0=32 0e=04
0f=18 48=02 f0=39 02=70 f0=45 09=1c f0=37 22=0d f0=33 33=10 b1=80 34=40 0b=54 b2=78 f0=36 11=80 f0=30 38=44 f0=33 b3=51
01=10 0b=6c 06=24 f0=36 31=82 3e=60 30=f0 33=33 f0=34 9f=02 a6=40 a7=47 e8=5f a8=51 a9=44 e9=36 f0=33 b3=51 64=17 90=01
91=03 92=07 01=10 93=10 94=10 95=10 96=01 97=07 98=1f 99=10 9a=20 9b=28 9c=28 f0=36 70=54 b6=40 b7=41 b8=43 b9=47 ba=4f
b0=8b b1=8b b2=8b b3=9b b4=b8 b5=f0 7e=41 7f=47 77=80 78=84 79=8a a0=47 a1=5f 96=43 97=44 98=54 f0=00 f0=01 73=00 74=e0
70=00 71=80 f0=36 37=74 f0=3f 03=8d f0=36 11=80 f0=01 79=c1 f0=37 24=21 f0=36 41=61 f0=00 72=3a 7a=80 7e=25 85=18 9b=35
9e=20 d0=6b d1=34 d3=55 d5=38 d6=55 d8=40 b0=41 b2=48 b3=f4 b4=0b b5=78 ba=ff bb=c0 bc=90 bd=3a c1=67 f0=01 20=10 23=90
24=16 25=88 bc=9f bd=3a 48=e6 49=c0 4a=d0 4b=52 f0=00 71=92 7c=03 84=b4 f0=33 14=95 f0=32 21=00 f0=32 0c=04 0d=84 0e=03
0f=52 f0=00 87=65 7c=c4 7e=45 f0=36 77=83
```

### #4 BF20A6 (ID 0xA6 @0xFD, I2C 0xDC) flash 0x7D728 - 167 writes

```
f2=01 12=20 3a=00 e1=92 e3=02 e0=00 2a=98 0e=47 0f=60 10=57 11=60 30=61 62=cd 63=1a 64=38 65=52 66=68 67=c2 68=a7 69=ab
6a=ad 6b=a9 6c=c4 6d=c5 6e=18 c0=20 c1=24 c2=29 c3=25 c4=28 c5=2a c6=41 ca=23 cd=34 ce=32 cf=35 d0=6c d1=6e d2=cb e2=09
e4=73 e5=22 e6=24 e7=64 e8=a2 4a=0c 00=03 1f=02 22=02 0c=31 00=00 60=81 61=81 a0=08 01=1a 01=1a 01=1a 02=15 02=15 02=15
13=08 8a=85 8b=06 87=18 34=48 35=40 36=40 70=1f 71=44 72=56 73=6b 74=6a 75=a9 78=45 79=a0 7a=94 7c=97 40=30 41=28 42=20
43=1a 44=18 45=14 46=12 47=10 48=0f 49=0e 4b=0d 4c=0c 4e=0b 4f=0a 50=09 5f=29 23=33 a1=10 a2=0d a3=23 a4=07 a5=26 a6=5f
a7=18 a8=1a a9=12 aa=12 ab=16 ac=b1 ba=12 bb=12 ad=12 ae=56 af=0a 3b=30 3c=12 3d=22 3e=3f 3f=28 b8=c3 b9=a3 39=47 26=0b
27=12 28=09 29=16 ee=08 13=05 24=48 81=20 82=40 83=30 84=40 85=30 92=08 86=70 91=ff 94=42 95=fd 9a=28 9e=bc f0=4a 51=0c
52=05 53=3d 54=47 55=86 56=26 7e=17 57=36 58=2a 59=aa 5a=a8 5b=43 5c=10 5d=00 7d=36 5e=10 d6=80 d5=20 b0=24 b5=0c b1=b0
b2=b0 b3=b0 b4=b0 32=10 a0=09 00=03 0b=02
```

### #5 GC0310 (ID 0xA3 @0xF0, I2C 0x42) flash 0x7D878 - 269 writes

```
fe=f0 fe=f0 fe=00 fe=00 fe=00 fe=00 fe=00 fe=00 fe=00 fe=00 fe=00 fe=00 fc=0e fc=0e f2=07 f3=ff f7=1b f8=03 f9=0e fa=11
00=2f 01=0f 02=04 03=03 04=50 09=00 0a=00 0b=00 0c=04 0d=01 0e=e8 0f=02 10=88 16=00 17=14 18=1a 19=14 1b=48 1c=1c 1e=6b
1f=28 20=8b 21=49 22=b0 23=04 24=16 34=20 26=23 28=ff 29=00 32=00 33=10 37=20 38=10 47=80 4e=66 a8=02 a9=80 40=ff 41=21
42=cf 44=02 45=a8 46=03 4a=11 4b=01 4c=20 4d=05 4f=01 50=01 55=01 56=e0 57=02 58=80 5a=84 5b=c9 5c=ed 42=00 77=70 78=40
79=58 82=14 83=0b 89=f0 8f=aa 90=8c 91=90 92=03 93=03 94=05 95=88 96=f0 d0=40 d1=34 d2=34 d3=40 d6=f2 d7=1b d8=18 dd=03
fe=01 05=30 06=75 07=40 08=b0 0a=c5 0b=11 0c=00 12=52 13=3a 18=95 19=96 1f=30 20=c0 3e=40 3f=57 40=7d 03=60 44=02 fe=01
1c=91 21=15 50=80 56=04 59=08 5b=02 61=8d 62=a7 63=d0 65=06 66=06 67=84 69=08 6a=25 6b=01 6c=00 6d=02 6e=f0 6f=80 76=80
78=af 79=75 7a=40 7b=50 7c=0c 90=c9 91=be 92=e2 93=c9 95=1b 96=e2 97=49 98=1b 9a=49 9b=1b 9c=c3 9d=49 9f=c7 a0=c8 a1=00
a2=00 86=00 87=00 88=00 89=00 a4=b9 a5=a0 a6=ba a7=92 a9=ba aa=80 ab=9d ac=7f ae=bb af=9d b0=c8 b1=97 b3=b7 b4=7f b5=00
b6=00 8b=00 8c=00 8d=00 8e=00 94=55 99=a6 9e=aa a3=0a 8a=00 a8=55 ad=55 b2=55 b7=05 8f=00 b8=cb b9=9b fe=01 d0=38 d1=00
d2=00 d3=08 d4=40 d5=12 fe=01 c1=3c c2=50 c3=00 c4=40 c5=30 c6=30 c7=10 c8=00 c9=00 dc=20 dd=10 df=00 de=00 01=10 0b=31
0e=50 0f=0f 10=6e 12=a0 15=60 16=60 17=e0 cc=0c cd=10 ce=a0 cf=e6 45=f7 46=ff 47=15 48=03 4f=60 fe=00 05=01 06=d1 07=00
08=22 fe=01 25=00 26=6a 27=02 28=12 29=02 2a=12 2b=02 2c=12 2d=02 2e=12 3c=20 fe=00 fe=03 01=00 02=00 10=00 15=00 fe=00
f3=ff fe=00 00=2f 00=2f 00=2f 1f=28 1f=28 1f=28 fe=00
```

### #6 SP0A39 (guess; ID 0x39 @0x01, I2C 0x42) flash 0x7DA94 - 300 writes

```
fd=00 1d=25 31=06 32=01 30=01 fd=00 f0=ff f1=ff f2=ff f3=ff fc=50 fd=01 5d=01 34=e3 35=10 fd=00 03=03 04=6c 24=10 ef=40
06=00 09=01 0a=80 10=0a 11=02 16=01 19=22 1e=60 29=60 13=37 14=01 25=01 2a=06 27=00 54=00 55=10 58=28 5d=12 63=00 64=00
66=2a 68=28 72=32 73=0a 75=30 76=0a 1f=99 20=09 fb=16 fd=01 f2=69 f7=97 02=04 03=01 06=8a 08=04 fd=02 b8=50 b9=ff ba=40
bb=45 bc=c0 bd=50 be=b8 bf=04 d0=b8 d1=04 fd=01 c0=1f c1=18 c2=15 c3=13 c4=13 c5=12 c6=12 c7=11 c8=11 c9=11 ca=10 f3=10
f4=10 fd=01 04=d0 05=10 0a=30 0b=10 fd=01 cb=38 cc=35 cd=03 ce=05 fd=00 fb=16 35=aa fd=01 1e=00 20=00 84=25 85=25 86=1f
87=23 88=1a 89=1c 8a=15 8b=15 8c=15 8d=1a 8e=0a 8f=13 90=13 91=00 92=0a 93=02 94=12 95=00 96=0a 97=08 98=15 99=05 9a=0a
9b=09 e8=20 e9=0f ea=00 bd=1e be=00 fd=01 a4=00 0e=80 18=40 0f=20 10=80 11=80 12=80 13=80 14=80 15=80 16=80 17=80 6e=00
6f=03 70=07 71=0d 72=17 73=29 74=3d 75=4f 76=5f 77=79 78=8c 79=9d 7a=a9 7b=b3 7c=be 7d=c7 7e=d0 7f=d6 80=de 81=e4 82=e9
83=ee fd=02 09=06 0d=1a 1c=09 1d=03 1e=10 1f=06 fd=01 32=00 fd=02 26=cb 27=c2 10=00 11=00 18=17 19=36 2a=01 2b=10 28=f8
29=08 66=5f 67=7f 68=e0 69=10 6a=a6 7c=4a 7d=80 7e=00 7f=30 80=aa 70=32 71=60 72=30 73=5a 74=aa 6b=ff 6c=50 6d=40 6e=60
6f=6a 61=ff 62=27 63=51 64=7f 65=6a 75=80 76=09 77=02 0e=12 3b=09 48=ea 49=fc 4a=05 02=00 03=88 f5=fe 22=fe 20=d8 23=a8
f7=fe fd=02 de=0f cf=0a d7=0a d8=12 d9=14 da=1a dc=07 e8=60 e9=40 ea=40 eb=30 ec=60 ed=50 ee=40 ef=30 d3=30 d4=30 d5=50
d6=0b f0=7f fd=01 b1=f0 fd=02 dc=07 05=08 fd=01 26=33 27=99 62=f0 63=80 64=80 65=20 fd=02 dd=ff fd=01 a8=09 a9=09 aa=09
ab=0c d3=09 d4=09 d5=09 d6=0c cf=ff d0=f0 d1=80 d2=80 df=ff e0=f0 e1=d0 e2=80 e3=ff e4=f0 e5=d0 e6=80 fd=02 30=38 31=40
32=40 33=d0 34=10 35=60 36=28 37=07 38=08 e6=8f fd=01 1b=15 1c=1a 1d=0c fd=01 32=15 33=ef 36=10 f6=b0 f5=10 fd=00 1c=00
```
