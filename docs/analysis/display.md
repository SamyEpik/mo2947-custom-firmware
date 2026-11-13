# Display (2.0" NV3030B LCD): config, controller, compositor, backlight

> [!summary]
> NV3030B 240×320 panel used as 320×240, **8-bit 8080 bus** on PC5-PC12 + PE1-PE4, reset **PB6**, backlight **PA6** (PWM). LCD controller SPR 0xA800, compositor 0xC800, rotation engine, frame flow, OSD layer, the init table, and raw sequences to drive the panel.

Topic agent: `display`. Sources: `analysis/export/all.asm` / `all.c`, `dumps/mo2947_flash_a.bin` (range `0x7C600`-`0x7DDFF`
only), app image. All addresses are RAM (`0x020xxxxx`) unless marked "flash". **V** = verified in code (address cited),
**I** = inferred / guess. The decompiler often misplaces arguments on this CPU; every argument below was taken from the asm.

Cross-check: `ext/appotech-sdk/research/display*.md` describes the same LCD controller (`a800`), compositor (`c800`) and
GPIO banks on a sibling JT5295 camera (ILI9225G panel) and has driven its panel with its own code. Its register values match
ours exactly where they overlap (`a808=6`, `a80c=0x44`, `a810=0x090000FF`, `a804=0x00809F00`, `c818=0x52081`, the 40-word
scaler table). Its board `silvergear-3222882` is also a 240x320 panel used as 320x240, clock divider 15, RS = PE2. Where I
lean on it, I say so.

## 1. Summary

| Item | Value | |
|---|---|---|
| Panel | NV3030B, 240x320 native portrait, used as 320x240 landscape | V (cfg) |
| Bus | MCU / 8080, 8-bit, RGB565 = 2 bytes per pixel | V (cfg +0x20/+0x21/+0x58, `FUN_0202f94c`) |
| Data pins | PC5-PC12 (port 2 mask `0x1FE0`) | V (configured); bit order I |
| Control pins | PE1, PE2, PE4 (port 4 mask `0x16`) as peripheral. **PE2 = RS (D/C)** | V for RS (`0202f120`); WR/CS split of PE1/PE4 unknown |
| TE (tearing effect) | PE3 (port 4 mask `0x08`) input + peripheral; TE IRQ used | V (`0202f94c`, `02033cd4`) |
| Reset | **PB6** (port 1 mask `0x40`): high, 20 ms, low, 50 ms, high, 50 ms | V (`0x02002C30`) |
| Backlight | **PA6** (port 0 mask `0x40`) = PWM channel 2 output, 4000 Hz, duty `brightness*10+20` % (clamped 99) | V (`lcd_ioctl`, `0x02028520`) |
| LCD bus clock | SPR `0x887C = (15-1)<<2 = 0x38` (divider 15) | V (`0x0202F4CC`); clock source I |
| Pixel path | YUV420 semi-planar buffers → rotation engine (90°) → compositor `c800` (YUV→RGB565, scaler, 2 OSD layers) → LCD controller `a800` (8080 DMA) → panel | V |
| Video format | Y plane + interleaved chroma plane (h/2 rows), stride rounded to 32 bytes. Chroma order V,U (NV21) | layout V; order I (SDK) |
| OSD format | 8 bpp palette index, palette 256 × u32 `(alpha5<<16)|RGB565` (resource 54) | V (`0x02034094`, `0x02005788`) |
| Frame sync | Panel TE → LCD IRQ (status bit 4) → start LCD DMA if compositor has a frame | V (`0x020329B4`) |

## 2. Call tree from `lcd_init`

```
lcd_init 0x02002804
  gpio_init(PA, 0x40, out, no pull) ; gpio_write(PA,0x40,0)      backlight pin low (off)
  lcd_cfg_load_and_init 0x02048D14
    lcd_cfg_load 0x02048BC0          reads flash 0x7C600 (hdr) and the LCD entry, init table
    lcd_display_init 0x02033860(cfg)
      frame_pool_init 0x0203C128     video buffers
      de_* (0x0202D164..0x0202DCB4)  compositor
      lcdc_pins_mcu 0x0202F94C, lcdc_* (0x0202F2E0..0x0202F648)  LCD controller
      lcd_panel_reset 0x02002C30     PB6
      lcd_send_init_table 0x020329E0 init commands from flash
      TE mode / IRQ callbacks, rot_queue_init 0x0203BEE8, csi callback 0x0202E18C(1, 0x020331E8)
```

The backlight is switched on later by `dev_ioctl(lcd, 0x20000004, 1)` (`lcd_ioctl` 0x02002AA0).

## 3. Hardware config block (flash 0x7C600)

### 3.1 Overall layout (V: readers `0x02048BC0` and `0x020485AC`)

| Flash | Size | Content | Reader |
|---|---|---|---|
| `0x7C600` | 0x38 | LCD header `{u32 0x19 (unused, type/id?), u32 entry_off=0x38, u32 entry_len=0x24C, 0...}` | `0x02048BC0` |
| `0x7C638` | 0x24C | LCD entry (section 3.2) | `0x02048BC0` → RAM `g_lcd_cfg` (`*0x02080AB4`) |
| `0x7C884` | 0x418 | LCD init table (entry `+0x48` offset, `+0x50` length, both relative to `0x7C600`) | `0x02048BC0` |
| `0x7CC9C` | 0x40 | Sensor header `{u32 entries_off=0x40, u32 entries_len=0x1F8, u32 entry_size=0x48, 0...}` | `0x020485AC` |
| `0x7CCDC` | 7 × 0x48 | Sensor probe entries (offsets relative to `0x7CC9C`) | `0x020485AC` |
| `0x7CED4`-`0x7D173` | 7 × 0x60 | Sensor config structs | |
| `0x7D174`-`0x7DCEE` | | Sensor init tables | |

All offsets are relative to the block's own base, not absolute. The LCD block and the sensor block are separate; the LCD
header does not point to the sensor block (the sensor code hard-codes `0x7CC9C`).

Sensor probe entry (for the sensor agent; V from `0x020485AC`): `+0x00 cfg_off, +0x04 cfg_len (0x60), +0x08 init_off,
+0x0C init_len, +0x2C name[20], +0x40 u8 expected ID, +0x41 u8 I2C write addr, +0x42 u8 read addr, +0x43 u8 register-address
bytes, +0x44 u8 data bytes, +0x46 u16 ID register`. The 7 entries: `3A/DC reg FC`, `A0/42 reg 00`, `0C/66 reg 01`,
`46/D0 reg F8 "030iot"`, `A6/DC reg FD "BF20A6"`, `A3/42 reg F0 "GC0310"`, `39/42 reg 01`. Entries with ID `C0`, write addr
`62`, ID reg 0 get a pre-write `0xFC=0x16`. If no entry matches, built-in tables at `0x02065B34`/`0x02065B7C` are used.

### 3.2 LCD entry `nv3030b` (flash `0x7C638`, RAM copy `*0x02080AB4`, pointer kept in `0x0207F220`)

| Off | Size | Value | Meaning | |
|---|---|---|---|---|
| +0x00 | 32 | `"nv3030b"` | name | V |
| +0x20 | u8 | 1 | interface: 1 = MCU/8080, else RGB (with 3-wire SPI init) | V `02033B84` |
| +0x21 | u8 | 8 | bus width (data-line mask `(1<<8)-1` into `a810`) | V `0202F428` |
| +0x22 | u8 | 0 | init-table word size: 0 = 8-bit cmd/data, else 16-bit | V `020329E0` |
| +0x23/24/25 | u8×3 | 5,6,5 | output R/G/B bits → compositor dither, `c818 |= 0x50000` | V `0202D384` |
| +0x26 | u8 | 4 | rotation: 0 none, 4 = 90° (swap W/H, stock default), 5 = 270°, 1-3 flips (I) | V `020334C0`, `0203C128` |
| +0x27 | u8 | 1 | TE mode: 0 = TE IRQ on, no callback; 1 = TE IRQ starts frames; 0xFF = free-running (no TE pin) | V `02033CAC` |
| +0x28 | u8 | 15 | LCD clock divider → SPR `0x887C = (n-1)<<2` | V `0202F4CC` |
| +0x2C | u32 | `0x82100008` | LCD output packing → SPR `a85c` (SDK: "packing word", their board `0x02100008`); bit meaning unknown | V write; I meaning |
| +0x30 | u32 | 0 | → SPR `a86c` | V |
| +0x34/+0x36 | u16 | 240, 320 | native width, height | V |
| +0x38..+0x3E | u16×4 | 0,0,320,240 | video window x,y,w,h (logical); 0 = full screen | V `02033860` |
| +0x40..+0x46 | u16×4 | 0,0,0,0 | OSD window x,y,w,h; 0 = copy video window (→ 0,0,320,240) | V `02033860` |
| +0x48 | u32 | `0x284` | init-table offset (from `0x7C600`); replaced by a RAM pointer after load | V `02048BC0` |
| +0x4C | u32 | 0 | 2nd table offset (unused here) | V |
| +0x50/+0x54 | u32 | `0x418`, 0 | lengths of the two tables | V |
| +0x58 | u8 | 2 | bytes per pixel on the bus; `a854 = w*h*bpp-1` | V `02033C70` |
| +0x59/+0x5A | u8 | 0,0 | packing selectors → `a868 = (b<<3)|a|(a!=b?0x40:0)` | V `0202F588` |
| +0x5B..+0x64 | u8 | 0 | RGB-mode only: sync widths, porches, polarities (→ `a80c/a810/a814-a838/a860`) | V (RGB branch `02033D18`) |
| +0x65..+0x68 | u8 | 0 | RGB-mode only: bit-banged 3-wire SPI (CS PC5, SCL PC6, SDA PC7): idle pol, edge, LSB-first, bits | V `0202EFAC` |
| +0x6C..+0xCB | | 7, -12, 7, 8, 3,3,3, 3x3 matrix identity (0x100 = 1.0) + 3 zero offsets, 5 × 0x40 | colour/gamma tuning. **No code reads it** in this firmware | V (no xref); meaning I |
| +0xCC | 0x60 | signed bytes, 8-tap rows summing to 64 | **sensor-preview scaler coefficients**, written to CSI SPRs `0xB18C-0xB1E8` by `0x0202E928` | V |
| +0x12C, +0x18C | 0x60 ×2 | identical copies of +0xCC | not referenced | V (no xref) |
| +0x1EC | 0x60 | 4-tap rows summing to 127 | copied to RAM `0x02082DB0` by `0x02048BC0`; no reader found in the export | V copy; use unknown |

There is no gamma LUT for the SoC in use: panel gamma is set by the init table (`E0`-`E5`).

### 3.3 Init table format and the NV3030B sequence

Table = little-endian u32 pairs `(op, value)`: op 0 = command byte, 1 = data byte, 2 = SPI word (RGB mode), 3 = delay
`value` ms (`0x02026340`), `0xFFFFFFFF` = end. V: `0x020329E0`. Decoded from flash `0x7C884` (complete, 0x418 bytes):

| Flash | Cmd | Data | Meaning |
|---|---|---|---|
| `0x7C884` | `FD` | 06 08 | NV3030B: unlock vendor command set (I) |
| `0x7C89C` | `61` | 07 07 | vendor: bias / power (I) |
| `0x7C8B4` | `73` | 70 | vendor (power sequencing?) (I) |
| `0x7C8C4` | `73` | 00 | vendor (I) |
| `0x7C8D4` | `61` | 07 07 | repeated |
| `0x7C8EC` | `62` | 00 44 40 | vendor: VGH/VGL (I) |
| `0x7C90C` | `65` | 08 10 21 | vendor: charge pump 1 / VSP (I) |
| `0x7C92C` | `66` | 08 10 21 | vendor: charge pump 2 / VSN (I) |
| `0x7C94C` | `67` | 21 40 | vendor: pump clock select (I) |
| `0x7C964` | `68` | 50 57 2A 15 | vendor: gamma reference voltages (I) |
| `0x7C98C` | `B1` | 0F 02 00 | frame-rate control (I) |
| `0x7C9AC` | `B4` | 01 | inversion control (I) |
| `0x7C9BC` | `B5` | 02 02 0A 14 | porches VFP/VBP/HFP/HBP (I) |
| `0x7C9E4` | `B6` | 44 01 9F 00 02 | display function; `0x9F` = 160 line pairs = 320 lines (I) |
| `0x7CA14` | `E6` | 00 FF | vendor: source output (I) |
| `0x7CA2C` | `E7` | 01 04 03 03 00 12 | vendor: source/gate timing (I) |
| `0x7CA64` | `E8` | 00 70 00 | vendor (I) |
| `0x7CA84` | `EC` | 52 | vendor (I) |
| `0x7CA94` | `DF` | 11 | gamma enable (I) |
| `0x7CAA4` | `E0` | 07 07 0A 13 0E 11 12 19 | gamma (positive) |
| `0x7CAEC` | `E3` | 12 0E 11 0E 10 09 05 06 | gamma (negative) |
| `0x7CB34` | `E1` | 27 71 | gamma |
| `0x7CB4C` | `E4` | 6B 27 | gamma |
| `0x7CB64` | `E2` | 00 09 0C 31 3B 3F | gamma |
| `0x7CB9C` | `E5` | 3F 3A 32 0C 0A 00 | gamma |
| `0x7CBD4` | `F6` | 01 30 00 00 | vendor: interface control (I) |
| `0x7CBFC` | `F1` | 01 41 20 | vendor (I) |
| `0x7CC1C` | `FD` | FA FC | lock vendor command set (I) |
| `0x7CC34` | `3A` | 55 | **COLMOD**: 16 bpp RGB565 |
| `0x7CC44` | `35` | 00 | **TEON**, V-blank only |
| `0x7CC54` | `36` | 00 | **MADCTL** = 0: no mirror, no row/column swap, RGB order (panel stays portrait) |
| `0x7CC64` | `21` | - | **INVON** (display inversion on) |
| `0x7CC6C` | `11` | - | **SLPOUT**, then 200 ms |
| `0x7CC7C` | `29` | - | **DISPON**, then 20 ms |
| `0x7CC8C` | `2C` | - | **RAMWR**, left open; end of table |

There is no `2A`/`2B`, so the panel window stays at its reset default (full 240x320). Because the table ends with `2C`,
the stock firmware never sends a per-frame command (no other `a858` writer exists): every DMA frame is exactly
240×320×2 bytes and the panel's write pointer wraps to the window start (I, standard DCS behaviour). For our own code it is
safer to send `2A 00 00 00 EF`, `2B 00 00 01 3F`, `2C` before each frame. Only the bracketed "I" names above come from
general NV3030B knowledge, not from a datasheet; the DCS ones are standard.

## 4. LCD controller (SPR `0xA800` block) — V unless marked

| SPR | Stock value | Meaning | Writer |
|---|---|---|---|
| `a800` CON | `0x31` final | bit0 enable, bit1 start frame DMA (`0x0202F6F4`), bit4 MCU mode, bit5 TE-sync (I), bit6 (0) | `0202F648`, `0202F600`, `0202F6AC` |
| `a804` STA/IE | `0x00809F00` at reset | bit31 = PIO byte done (poll). bits0-4 pending events, bits8-12 write 1 to clear, bits16-20 enables. Event 3 = frame done (enable bit19), event 4 = TE (bit20). Bit7 pending is cleared via bit15 | `0202F2E0`, `0202F32C`, ISR `0202F72C` |
| `a808` | 6 | `n-1` with n=7: bus pulse length (SDK) | `0202F374` |
| `a80c` | `0x44` | bus config: bit6, bit2 set in MCU mode; RGB mode packs sync/porch fields | `0202F390` |
| `a810` | `0x090000FF` | polarity bits 24-27 + data-line mask (8 bits) | `0202F390`, `0202F428` |
| `a814`-`a838` | 0 | RGB timings (unused in MCU mode) | `0202F4EC`/`F510`/`F534` |
| `a840`/`a844` | 240 / 320 | frame width / height | `0202F550` |
| `a848`/`a84c` | 239 / 319 | width-1 / height-1 | `0202F56C` |
| `a854` | `0x257FF` | bytes per frame − 1 (240·320·2−1) | `0202F5CC` |
| `a858` | | PIO byte write (command or data, RS = PE2 GPIO) | `0202F120`.. |
| `a85c`/`a86c`/`a868` | `0x82100008` / 0 / 0 | output packing (from cfg) | `0202F588` |
| `a860`/`a864` | 0 / 0 | RGB vertical timing | `0202F5E4` |
| `0x887C` | `0x38` | LCD clock divider `(15-1)<<2` | `0202F4CC` |
| `0x8840` bit 25 | cleared | LCD clock gate (active low: `clk_gate(0x19, 1)` clears it) | `0202F2E0` |
| PIC (SPR `0x4800`) bit 4 | set | LCD interrupt | `0202F648` |

The LCD DMA has no source address: it pulls its pixels from the compositor (`c800`). The SDK confirms this on the sibling chip
(completion = `a804` bits 31 and 3 plus `c80c` bit 0).

PIO byte write (V `0x0202F120`/`0x0202F184`): RS low (cmd) or high (data) via GPIO data SPR `0x8010` bit 2; ~200-iteration
delay (`0x0202637C(0xC8)`); `a858 = byte`; poll until `a804` bit 31 is set; for a command, RS high again.

Pin setup (V `0x0202F94C`): pinmux SPR `0x8348[9:6] = 13` (`pinmux_select(0x10, 13)`); port 2 mask `0x1FE0` and port 4 mask
`0x16`: `0x8380|=`, direction output (`0x8040` clear), peripheral select (`0x8100|=`); if TE: port 4 mask 8 the same but as
input (`0x8040|=8`).

## 5. Compositor / display engine (SPR `0xC800` block) — V unless marked

| SPR | Stock | Meaning | Writer |
|---|---|---|---|
| `c800` | 3 | bit0 enable, bit1 start/frame pending (self-clearing, read by `0x0202D1E4`) | `0202D288`, `0202D1C0` |
| `c804`/`c808` | 15 / 0 | burst/config (SDK) | `0202D288` |
| `c80c` | | status: bit0 frame done (ISR `0x0202D208`, write 0 to clear), bit9 busy (I) | |
| `c810` | `(320-1)<<16|(240-1)` | output size (native) | `0202D288` |
| `c814` | 0 | background colour `R<<16|G<<8|B` | `0202D304` |
| `c818` | `0x52081` | bit0 video layer on, bit1/bit2 OSD layer 0/1 on, bit7 scaler on, bits8-10 video scan mode (0 normal, 1 V-flip, 2 H-flip, 3 both: I from offset maths), bit13 YUV→RGB on, bits15-18 output depth (565 = `0x50000`), bit21 + bits22-31 line number (set from the CSI callback, meaning I) | several |
| `c820` | `(h-1)<<16|(w-1)` | scaler source size | `0202DCB4` |
| `c824` | `y<<16|x` | video layer position | `0202D604` |
| `c828`/`c830` | | **video Y address / chroma address** | `0202D58C` |
| `c82c`/`c834` | stride/4 | Y / chroma stride in words | `0202D5A8` |
| `c838` | `0x4000` | YUV→RGB parameters (byte1 = 0x40, maybe gain 1.0: I) | `0202D424` |
| `c83c`/`c84c` | `(h-1)<<16|(w-1)` | OSD 0 / OSD 1 size | `0202DA4C` |
| `c840`/`c850` | `y<<16|x` | OSD 0 / 1 position | `0202DAA0` |
| `c844`/`c854` | | **OSD 0 / 1 buffer address** | `0202DB3C` |
| `c848`/`c858` | | OSD buffer length rounded up to 8, −1 | `0202DB3C` |
| `c85c` | 0 | per OSD layer 16-bit field (mask `0x2F`): alpha / key control (I) | `0202DC48` |
| `c87c` | | current read address (24 bits) | `0202D52C` |
| `c880`-`c91c` | 40 words from `0x02064360` | scaler coefficients (identical to the SDK's table) | `0202DCB4` |
| `c920`/`c924` | `(src<<16)/dst` | horizontal / vertical 16.16 step (`0x10000` = 1:1) | `0202DCB4` |
| `c928`/`c92c` | | scaler source / destination size | `0202DCB4` |
| palette RAM `0x00050000` | 256 × u32 | OSD 0 palette (memcpy 0x400 bytes); OSD 1 at `0x000507DE` (odd value, as decoded) | `0202DAF4` |
| `0x8840` bit 7 | cleared | compositor clock | `0202D288` |
| PIC bit 21 | set | compositor IRQ (callback `0x0207F180` is never set) | `0202D288` |

## 6. Rotation engine (SPR `0x898C` block) — V

`rot_hw_start 0x0202CBCC(ch, w, h, dstY, dstC, dst_stride, srcY, srcC, src_stride, irq_en)`: clock gate `0x22`
(`0x8844` bit 2), `898c = 1 | ch<<1 | irq_en<<2`, `89a8 = 1` (clear), `89a0 = ((h&~1)-1)<<16 | ((w&~1)-1)`, `8990/8994 =`
source Y/C `&~0x3F` (64-byte aligned), `8998/899c =` destination Y/C `&~0x1F`, `89a4 = (dst_stride/4)<<16 | src_stride/4`,
PIC bit 23, then `898c |= 0x80000000` (start; bit31 = busy, `0x0202CB60`). Done: `89a8` bit0 (ISR `0x0202CD38`, write 1 to
clear) → callback `0x0203BE04`. It always rotates by 90° (no angle field found); 270° is done by having the compositor read
the result flipped (scan mode 3).

## 7. Frame buffers and the stock frame flow — V

Frame pools at `0x02082EE0` (`frame_pool_init 0x0203C128`), pool header 0xA4 bytes, buffer descriptor 0x34 bytes:
`+0x00 next, +0x04 Y base, +0x08 chroma base (= Y + stride*h), +0x0C/+0x10 Y/chroma start for the compositor (base + scan
offset), +0x18 size, +0x20 w, +0x22 h, +0x28 x, +0x2A y, +0x2C stride (w rounded to 32), +0x2E scan mode (0-3, or 4 = still
landscape, needs rotation), +0x2F index, +0x31 in use, +0x32 pool id`. Size = `stride*h*3/2`.

With rotation 4: pool 0 = 2 × 320x240 landscape buffers (mode 4, 115,200 B each), pool 1 = 2 × 240x320 native buffers
(stride 256, 122,880 B each). Pools 2-4 have count 0.

```
camera/playback writes a landscape buffer (pool 0, mode 4)
 → disp_show_video 0x02032D3C(buf): mode 4 → get pool-1 buffer → rot_submit 0x0203BF3C(0, src, dst)
 → rotation engine → rot_done_cb 0x0203BE04 → frees src → 0x02032FD8(dst) → 0x02032D3C(dst):
      pending = dst (0x0207F214); in TE mode kick compositor (c800 bit1)
 → panel TE → LCD IRQ event 4 → lcd_te_cb 0x020329B4: if compositor pending (c800 bit1) → LCD start (a800 bit1)
 → LCD frame done (event 3) → lcd_frame_done_cb 0x02032878: if pending ≠ current: wait compositor idle, program
      c82c/c834, scan mode, c824, scaler, c828/c830 from the pending buffer, kick compositor, free the old buffer.
```

Camera preview: the CSI writes straight into a pool-0 buffer (CSI SPRs `0xB060`/`0xB064` = Y/chroma address, `0xB068` stride,
scaler `0xB180`-`0xB1E8` with the cfg `+0xCC` coefficients); the CSI frame callback `0x020331E8` submits it and arms the
next one. (Sensor/CSI details belong to the sensor agent.)

## 8. OSD (UI) layer — V

`disp_layer_init 0x02003AE8(1)` → loads palette resource 54 (`0x02005788`) and calls
`osd_layer_init 0x02034094(n=0, w=320, h=240, x=0, y=0, palette, rot=4)`: stores the layer at `0x0207F234 + n*0x20`
(`+0 w, +2 h, +4 native w, +6 native h, +8 rot, +0xC buf A, +0x10 size A, +0x14 buf B, +0x18 size B, +0x1C front buf`),
loads the palette, sets position and **native** size 240x320, allocates two 76,800-byte 8bpp buffers, fills them with index
`0xF9`, writes back the cache, sets `c844/c848`, kicks the compositor. Layer 1 is refused by the API (only OSD 0 is used).
`osd_layer_enable 0x02034430(0, en)` sets `c818` bit1.

The stock UI draws into a 320x240 logical canvas (`*0x02080AD8`, w `0x02080AD2`, h `0x02080AD0`, made by `0x020494D8`) that is
already stored rotated: for rotation 4, pixel (x, y) is at offset `(W-1-x)*H + y` (V `0x0201B76C`), i.e. native column = y,
native row = 319-x. `ui_flush 0x020495D4` copies the canvas into the back buffer (`0x02003DA0(1)` → `0x02034378`) with a
DMA copy (`0x0202693C`), shows it (`0x02003E58` → `0x020343C8`: `c844/c848`), and kicks the compositor (`0x0202D1C0`).

## 9. Backlight — V

`lcd_ioctl 0x02002AA0(priv, cmd, arg)`, cmd `0x20000004`:
- on: `gpio_set_func(PA, 0x40, 1)` (`0x8100` bit 6), `pwm_start(ch=2, pinmap=2, 4000 Hz, duty = settings_get_value(8)*10+20)`,
  `g_backlight_on = 1`.
- off: `pwm_stop(2)`, `g_backlight_on = 0`, `0x0200B820(0)`.

`pwm_start 0x02028520`, channel 2: `pinmux_select(9, 2)` (`0x8344[11:8]=2` → PA6), PA6 output, clock gate 12 on,
`9820 = 0x800`, `9828 = period = 144000000/freq/2 - 1` (17,999 at 4 kHz), `982c = duty*period/100` (duty clamped 1..99),
`9824 = 0`, `98b0 = 0x30`, then `9820 |= 2` (run). `pwm_stop 0x02028998(2)`: `9820 = 0`, clock gate 12 off, `0x8344[11:8]=0`.
Brightness 1-8 gives 30 %..99 %. `lcd_init` drives PA6 low first, so the light stays off during panel init.
**The `0x40` mask in `lcd_init` is the backlight (PA6), not reset or CS.** Reset is PB6 (`0x02002C30`).

## 10. API for our firmware

### 10.1 Stock functions we can call (r3.. = args, r11 = return)

| Address | Signature | Notes |
|---|---|---|
| `0x02002804` | `lcd_init()` | Everything: cfg from flash, compositor, LCD, reset, init table, pools, IRQ callbacks. Needs `mem_alloc` heap, `spi_flash_read`, and the stock IRQ dispatcher for TE-driven refresh |
| `0x02002AA0` | `lcd_ioctl(priv, 0x20000004, on)` | backlight; or `dev_ioctl(dev, cmd, arg)` `0x02002538` |
| `0x020369B0` / `0x020369DC` | `pwm_start(ch, pinmap, hz, duty%)` / `pwm_stop(ch)` | direct backlight control (ch 2, pinmap 2) |
| `0x02002C30` | `lcd_panel_reset()` | PB6 sequence |
| `0x0202F120` / `0x0202F184` | `lcd_write_cmd(u8)` / `lcd_write_data(u8)` | PIO, after LCD controller is set up |
| `0x020329E0` | `lcd_send_init_table(u8 *word16_flag, u32 *table)` | interpreter |
| `0x020334C0` | `disp_get_size(u16 *w, u16 *h)` | logical (320x240) |
| `0x02003D58` | `void *disp_get_buffer(layer)` | layer 0: free video buffer (pool 0, 320x240 landscape NV21-like); 1: OSD front buffer |
| `0x02003D14` | `disp_show_video(0, buf)` | rotate + display, buffer is freed by the driver |
| `0x02003DE0` | `disp_free_video(0, buf)` | return an unused buffer |
| `0x02032B40` | `disp_fill_video(buf, y, c)` | fill Y plane with `y`, chroma with `c` |
| `0x02003AE8` | `disp_layer_init(layer)` | 0 = video/preview, 1 = OSD (palette res 54) |
| `0x02003DA0` | `u8 *disp_get_back_buffer(1)` | OSD back buffer (native 240x320, 8bpp) |
| `0x02003E58` | `disp_show_osd(1, buf)` | flip; then call `de_kick` `0x0202D1C0` |
| `0x02003710` | `disp_layer_enable(layer, en)` | 1 → OSD on/off; 0 → stop preview |
| `0x020494D8` / `0x020495D4` | `ui_canvas_init(w, h)` / `ui_flush(force)` | stock UI canvas path |
| `0x02026340` | `delay_ms(ms)` | busy loop `ms*16000` |

### 10.2 Raw sequence: init (MCU, 8-bit, no IRQ)

```
// pins
gpio_init(PA,0x40,out); PA6=0                       // backlight off
SPR 0x8348 = (SPR 0x8348 & ~0x3C0) | (13<<6)        // LCD pin group
port2 mask 0x1FE0, port4 mask 0x16: 0x8380|=m; 0x8040&=~m; 0x8100|=m
port4 mask 0x08 (TE): 0x8380|=8; 0x8040|=8; 0x8100|=8 (optional)
// LCD controller
SPR 0x8840 &= ~(1<<25); delay 20 ms
a800=0; a804=0x00809F00; a800|=0x10                 // MCU mode
a808=6; a80c=0x44; a810=0x090000FF; 0x887C=0x38
a814..a838=0; a840=240; a844=320; a848=239; a84c=319
a85c=0x82100008; a86c=0; a868=0; a854=240*320*2-1; a860=a864=0
a800|=1                                             // enable
// panel
PB6=1; delay 20; PB6=0; delay 50; PB6=1; delay 50   // gpio_init(PB,0x40,out) first
send table 3.3 (cmd: PE2=0, a858=b, wait a804 bit31, PE2=1; data: PE2=1, a858=b, wait)
// backlight
SPR 0x8100 |= 0x40 (port 0); pwm_start(2,2,4000,99)  // or plain GPIO PA6=1 for full on (I)
```

### 10.3 Draw a full frame

(a) **PIO (simplest, RGB565, no compositor):** `2A 00 00 00 EF`, `2B 00 00 01 3F`, `2C`, then 153,600 data bytes, high byte
first (I), native portrait order (row 0..319, column 0..239). For landscape (x, y) use native column = y, row = 319-x (the
stock mapping), or set MADCTL `36` to swap rows/columns (MV bit `0x20`) and draw landscape directly (I, untested).
Slow: about 0.3-0.5 s per frame (I, from SDK timings).

(b) **DMA via the compositor (YUV source):** buffer = Y plane (stride `s`, multiple of 32, 32-byte aligned) + chroma plane
(V,U interleaved, h/2 rows), **native 240x320 orientation** (rotate yourself or use the rotation engine). Then (SDK-proven
order on the sibling chip):

```
SPR 0x8840 &= ~(1<<7)                               // compositor clock
c804=15; c808=0; c80c=0; c814=0; c824=0; c838=0x4000
c880..c91c = 40 words from 0x02064360
c810=c820=c928=c92c = (320-1)<<16 | (240-1); c920=c924=0x10000
c828=Y; c82c=s/4; c830=C; c834=s/4
c818 = 0x52081                                      // + bit1 to add OSD 0
(optional) PIO: 2A/2B/2C
a800 = 0x11; c800 = 3; a800 = 0x13                   // start compositor, then LCD
wait: (a804 & 0x80000008) == 0x80000008 and (c80c & 1)
a804 |= 0x800 (ack event 3); c80c = 0
```

Write back the data cache for the buffer before starting (stock: `0x0202642C(addr, len)`).

(c) **OSD as a palette framebuffer (likely the easiest full-screen RGB path):** 8bpp buffer 240x320 (76,800 B, native
orientation), palette 256 × `(alpha5<<16)|RGB565` copied to `0x00050000`, `c83c=(320-1)<<16|(240-1)`, `c840=0`,
`c844=buf`, `c848=((76800+7)&~7)-1`, `c85c=0`, `c818 |= 2`, then the start sequence above. Whether the OSD shows with the
video layer off (`c818` bit0 = 0, background `c814`) is not tested (I).

### 10.4 Use the stock OSD

After `lcd_init` and `disp_layer_init(1)`: `buf = disp_get_back_buffer(1)`; draw 8bpp indices (palette 54, index 0
transparent, `0xF9` = stock fill) at native offset `(319-x)*240 + y`; `0x0202642C(buf, 76800)`; `disp_show_osd(1, buf)`;
`0x0202D1C0()`. The TE IRQ then starts the transfer, so the stock interrupt handling must be running.

## 11. Cross-check with `analysis/research_registers.md` and the SDK

Everything in `research_registers.md` "Second SPI / LCD MCU bus / display" agrees with our code. Corrections for our board:
- Its board table first said the `lcd_init` mask `0x40` "driven low at init" is probably PB6 reset (corrected there since). **It is PA6 (port 0) =
  backlight**; reset is a separate PB6 sequence in `0x02002C30` (V, asm `0x02002804`, `0x02002C30`).
- LCD bus: our divider is 15 (like the Silvergear board), not 20; packing word `0x82100008`, not `0x02100008`.
- PWM period uses the constant 144,000,000 (`0x02028594`), matching the PLL1 144 MHz value listed there (I: PWM clock =
  system clock).
- The ack value `a804 = 0x00800800` (SDK) is consistent with our ISR: bit 11 clears event 3.

## 12. Open questions

- Which of PE1/PE4 is WR and which is CS; is RD wired; data-line order on PC5-PC12.
- Meaning of `a85c=0x82100008` (bit 31 differs from the SDK board's `0x02100008`) and of `a868`.
- Whether the compositor can take RGB (not YUV) on the video layer; whether OSD-only output works.
- Use of the cfg colour block `+0x6C..+0xCB` and of the copy at `0x02082DB0` (no reader in the export).
- OSD 1 palette address `0x000507DE` looks wrong (odd); only OSD 0 is used, so it does not matter for us.
- Physical orientation (which landscape edge is "up") is not confirmed on hardware.
