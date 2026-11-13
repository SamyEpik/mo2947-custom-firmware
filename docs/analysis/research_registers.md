# AX3295B / JT5295 family: hardware register map from external sources

> [!summary]
> Register map of the AX3295B / JT5295 family from matu6968's SDK and the other repositories. The SPR numbers match our firmware. The last table compares the boards; the code reports in this folder are the newer source for our board.

Research only; compiled from the cloned repositories in `ext/`. No hardware was touched.

## How registers are accessed

- **All peripheral registers are OpenRISC SPRs**, reached with `l.mtspr rA,rB,K` / `l.mfspr rD,rA,K`
  (SPR number = `rA | K`). They are **not memory-mapped**. Source: matu `docs/HARDWARE.md` ("all peripheral registers are
  reached through l.mfspr/l.mtspr"), every driver in `firmware/sdk/src/*.c` (`apx_spr_read/apx_spr_write` in `soc.h`).
- Peripheral SPRs use the custom range `0x8000..0xFFFF` (OR1K groups 16-31), **stride 4** between registers.
- Standard OR1K SPRs used: group 0 (`0x0002` CPUCFGR, `0x0011` SR, `0x0020/0x0030/0x0040` exception PC/EA/SR — role not
  fully confirmed), group 3/4 (data/instruction cache, **vendor layout**), group 9 (`0x4800` PIC mask). Plus vendor SPR `0x0018`.
- A few things *are* memory: SRAM `0x00000000..` (bootstrap, vector table, USB setup FIFO at `0x8000`, SD long-response at
  `0x2000`, JPEG Huffman/quant tables at `0x66400`), boot ROM `0x00100000`, DDR `0x02000000`.
- In Ghidra decompiles, an access like `*(uint *)0xa038` or `*(uint *)((port+0x70)*4+0x8000)` is an SPR, not memory
  (the Ghidra text export, not in this repo).

Tags: **[src: file]** = written in that source (most of matu's are hardware-verified, with the stock address that proves
them in `ext/appotech-sdk/research/*.md`); **[ROM]** = I read it in the boot ROM; **[ours]** = seen in our firmware export;
**[guess]** = inferred, not confirmed. "SDK" = `ext/Action_Digital_Kids_Camera_DOOM/firmware/sdk` (same code as
`ext/appotech-sdk/src`).

Cross-check with our firmware: a crude grep of `analysis/export/all.c/all.asm` finds the same SPR numbers for SPI0 (`0x9000`,
`0x9244..0x9260`), UART (`0x9080..0x908C`), I²C (`0x9090/0x90A0`), ADC (`0x9170..0x9178`), DAC (`0x9140/0x915C`), mic
(`0x9100/0x9114`), SD (`0x9880/0x9888`), LCD (`0xA800/0xA858`), compositor (`0xC800`), JPEG (`0xC000`), CSI (`0xB000/0xB00C`),
PM bus (`0x88E0/0x88EC`), clocks (`0x8840/0x8868/0x887C`), timer (`0x9800/0x9804`), USB (`0x9840/0xA004/0xD804`), PIC
(`0x4800`), muxes (`0x8340/0x8344/0x8348`), watchdog (`0x880C`). So the same register map applies to our chip **[ours]**.
Another agent is building a full SPR table of our firmware (`analysis/…`); it also shows blocks the SDK does not document:
`0x8900..0x89A8`, `0x980C..0x983C`, `0x9900..0x9908`, `0x92A4..0x92E0`, `0xB800..0xB940` (roles unknown; PWM/timers are
candidates for `0x89xx`/`0x98xx` **[guess]**).

## CPU core, caches, interrupts

| SPR | Name / use | Bits | Source |
|---|---|---|---|
| `0x0002` | CPUCFGR (standard) | ND bit not measured | apxtool `docs/loader-research.md` |
| `0x0011` | SR (standard) | — | same |
| `0x0018` | vendor control | bit 1 = external IRQ enable (start-up clears it); bits 1, 2, 14 cleared by the stock `0xDA` handler before entering the ROM; bit 14 left set by the bootstrap after an SPI boot (must be cleared or the ROM loader does not come up) | SDK `startup.S`, `runtime.c: apx_bootrom`; `research/spi-boot-recovery.md` |
| `0x0020/0x0030/0x0040` | read by the exception handler (EPCR0/EEAR0/ESR0 in standard OR1K; roles **not confirmed** on this chip) | | SDK `exception.c`, `spi-boot-recovery.md` |
| `0x1800` | data cache control | bit 0 enable | SDK `runtime.c: apx_caches_enable` |
| `0x1808` | data cache window base | `0x02000000` | same |
| `0x180C` | write back lines starting at this address | write address | `apx_dma_clean` |
| `0x1814` | invalidate lines starting at this address | write address | `apx_dma_invalidate` |
| `0x181C` | line count − 1 for the next `0x180C/0x1814` op (16-byte lines, ≤ 4 KiB per op) | | same |
| `0x2000` | instruction cache control | bit 0 enable (clearing drops all lines) | `apx_caches_enable`, `apx_jump_to_rom` |
| `0x2008` | instruction cache base | 0 | same |
| `0x4800` | PIC mask (standard PICMR) | bit 4, 21 display; 6 DAC; 14 camera/CSI; 15 USB; 16, 22 JPEG; 18 microphone (SDK keeps them masked, polls) | SDK `display.c`, `audio.c`, `camera.c`, `usb.c`, `jpeg.c`, `microphone.c` |
| `0x4802` | PIC status (standard) | not used by the SDK | **[guess]** |
| `0x5000/0x5004…` | OR1K tick timer | not used by any source | **[guess]** |

Exception vectors: SRAM `0x0000`, **16-byte slots** (`vector*0x10`): reset `0x10`, bus `0x20`, data/instr page fault `0x30/0x40`,
tick `0x50`, alignment `0x60`, illegal `0x70`, external IRQ `0x80`, DTLB/ITLB `0x90/0xA0`, range `0xB0`, syscall `0xC0`,
FP `0xD0`, trap `0xE0`. Many faults stall the CPU instead of trapping. [src: `research/spi-boot-recovery.md`, SDK `exception.c`]
Caches: 8 KiB I + 8 KiB D (AppoTech site, quoted by Habr; not verified).

## Clock, PLL, power gates

| SPR | Use | Values / bits | Source |
|---|---|---|---|
| `0x8840` | clock gates, **active low** (0 = clock on) | bit 7 compositor, 20 SPI0, 22 SD0, 24 + 30 audio DAC, 25 LCD, 27 CSI/sensor, 29 ADC, 31 JPEG | SDK `display.c`, `spi.c`, `sd.c`, `audio.c`, `camera.c`, `adc.c`, `jpeg.c` |
| `0x8844` | clock gates 32..63 (same helper as `0x8840`) | bit 3 cleared for SPI0, bit 0 cleared for USB | `spi.c`, `usb.c`, apxtool `loader-research.md` |
| `0x8848` | clock select | bits 9:8 audio, bit 5 sensor MCLK source | `audio.c`, `camera.c` |
| `0x884C` | dividers | bits 27:24 audio divider (`0xB`), bits 12:8 sensor MCLK divider (`0xB` → 288 MHz/12 = 24 MHz), bit 31 USB clock | `audio.c`, `camera.c`, `usb.c` |
| `0x8850` | clock/source select | bits 31:28 = 3 for SPI0, bit 26 sensor MCLK enable, bits 25:24 = 3 and bit 27 cleared for USB | `spi.c`, `camera.c`, `usb.c` |
| `0x8858` | PLL1 control | `0x1623` (96 MHz loader), `0x1123` (144 MHz) | SDK `clock.c`, `research/clock.md` |
| `0x885C` | PLL1 coefficient = VCO in Hz | `0x0B71B000` (192 000 000 → 96 MHz), `0x112A8800` (288 000 000 → 144 MHz) | same |
| `0x8860/0x8864` | PLL2 control / coefficient | baseline `0x1623` / `0x0BEBC200` (200 MHz); our header hook writes `0x8864 = 0x17D78400` (400 MHz) | apxtool `hw.py: PAIR_BASELINE`; [ROM]+our header |
| `0x8868` | analog/aux | bit 15 ADC internal reference enable (needed for battery channel 11); bits 12:0 = `0x182E` for the camera | `battery.c`, `camera.c` |
| `0x886C/0x8870` | audio analog control | values in `audio.c` init (`0x0158360F`, `0x124` …); mic sets `0x886C` bits `0x3C1F` | `audio.c`, `microphone.c` |
| `0x8874` | speaker amplifier | bits 7:0 = `0xBB` when playing, 0 = muted | `audio.c` |
| `0x887C` | LCD clock divider | `(div-1) << 2` (Action div 20) | `display.c` |
| `0x8880` | JPEG reset | bit 2 low then high | `jpeg.c` |
| `0xF800..0xF8AC` | DDR controller | `0xF860` status (`0x07` after calibration), `0xF818/0xF81C` timing/calibration | `research/silvergear/power-ddr.md`, apxtool `hw.py` |

PLL switch rule: write `0x885C` then `0x8858`, then a 500-count loop, all inside one 32-byte I-cache line (DDR is unavailable during
the switch). Detach USB first. [src: SDK `clock_pair.S`, `clock.c`]

## Watchdog

| SPR | Use | Source |
|---|---|---|
| `0x880C` | write `0x5500` = disable (reads 0); `0x0005_0000 \| sel` = reload + enable (key 5 in bits 18:16); `0x39` = immediate reset. Readback: bit 4 enabled, bit 3 reset enable, bits 2:0 selector. Selector 4/5/6/7 ≈ 0.46/1.82/7.31/29.1 s (×4 per step). Stock app uses `0x50006`; boot ROM `0x5001D` | SDK `watchdog.c`, `research/watchdog-power.md`; [ours] `0x0202701C`, `0x02027064` |

## Timers / time base

| SPR | Use | Source |
|---|---|---|
| `0x9800` | timer control (32 kHz domain): `0x701` / `0x721`; a write is accepted only some time (~70-340 ms) after reset | SDK `clock.c`, `spi-boot-recovery.md` |
| `0x9804` | free-running 14-bit counter of the 32.768 kHz clock (`& 0x3FFF`) | `runtime.c: apx_ticks` |
| `0x9808` | reload/period, `0x3FFF` | `clock.c` |
| `0x980C..0x983C` | present in our firmware, not documented | [ours] **[guess: more timers/PWM]** |

## Power management (PM chip on an internal serial bus)

| SPR | Use | Source |
|---|---|---|
| `0x88E0` | PM bus control/status: bit 3 busy, bit 6 bus enable, bit 8 transaction select, bit 21 = **external (USB) power present** | SDK `power.c`, `battery.c` |
| `0x88EC` | PM bus data byte (write sends, read returns the received byte) | same |

Transaction: set `0x88E0 |= 0x140`, send register address, send/receive value, clear bit 8. **Read = even address, write =
address + 1.** PM registers `0x40..0x5A` (always-powered domain, survive reboots):

| PM reg | Stock start-up (Action) | Meaning |
|---|---|---|
| `0x40` | `0x06`, then `|= 0x10` → `0x16` | power hold / rails; shutdown writes `0x02` |
| `0x42` | `0xE0` | rail setup (reads back `0x50`) |
| `0x44` | `0x00` (shutdown `0x10`) | |
| `0x54` | bit 5 = battery divider enable (`0x21` running); shutdown clears bit 5; Silvergear: bit 6 = backlight | |
| `0x58` | `|= 0x08` | |
| `0x5A` | `0x08` — **clearing it cut USB power and the POWER keep-alive** | |

Source: SDK `power.c: apx_power_domain_enable`, `appotech-sdk/boot/flasher.c: pm_enable`, `research/spi-boot-recovery.md`,
`research/silvergear/power-ddr.md` (the Silvergear board needs a different variant). Our firmware uses this bus (around
`0x020296C0..0x02029744`) **[ours]**; our exact sequence still has to be read from our code.

## GPIO

Five banks A..E (0..4), 16 bits each; register for bank *g* = base + 4·g. "Mask" = bit mask of pins (PB5 = bank 1, `0x20`).

| Base | Role | Source |
|---|---|---|
| `0x8000` | output latch (write) / pin state (read) | SDK `gpio.c`, `research/gpio.md` (stock `0x02023CB8/0x02023DC0`) |
| `0x8040` | direction: 1 = input (drive off), 0 = output | same (`0x02023AB8`) |
| `0x8080` | pull-up enable | same (`0x02023B5C` bit 0) |
| `0x80C0` | pull-down enable | same (bit 1) |
| `0x8100` | cleared for plain GPIO, set for peripheral use (SPI0 `0xD00`, SD `7`, UART PA7, LCD bus) | same; **role [guess: peripheral/function enable]** |
| `0x8140` | cleared for plain GPIO | role unknown |
| `0x81C0` | force-high override | same (`0x02023FF4`); PB5 LED confirmed |
| `0x8200` | force-low override | same |
| `0x8380` | set for GPIO and LCD bus pins | role **[guess: pad/digital enable]** |
| `0x8340` | UART mux: bits 9:5 TX route, 4:0 RX route (TX route 6 = PA7) | SDK `uart.c`, `research/progressive-uart.md` |
| `0x8344` | mux: bit 16 SD0 (1-bit, PA0..PA2), bits 21:20 SPI0 route (1) | `sd.c`, `spi.c` |
| `0x8348` | mux: bits 2:0 I²C route (3 = PD13/PD15), bits 9:6 LCD bus (13), bits 11:10 sensor MCLK/DVP (2) | `camera.c`, `display.c` |
| `0x83C0/0x83CC` | present in our firmware | [ours], role unknown |

Plain GPIO configure (stock `0x0202EBC0`, SDK `apx_gpio_configure`): set `0x8040` (input), set `0x8380`, clear `0x81C0`,
`0x8200`, `0x8100`, `0x8140`, set/clear pulls `0x8080`/`0x80C0`; for an output write the latch `0x8000` first, then clear
`0x8040`. Our firmware's helper `FUN_02027834(port, mask, flags)` writes `0x81C0+4·port` (flag bit 0) and `0x8200+4·port`
(flag bit 1): the same override pair **[ours]**. Interrupts on GPIO: not implemented anywhere.

## UART0

| SPR | Use | Source |
|---|---|---|
| `0x9080` | control: `0x10` enable, 0 off | SDK `uart.c` |
| `0x9084` | baud divider = `CPU_Hz / baud − 1` (1249 at 144 MHz/115200); **write-only** (reads 0) | same, `board.h` |
| `0x9088` | data | same |
| `0x908C` | status/ack: bit 0 RX pending (ack by writing `0x10`), bit 1 TX done (ack by writing `1`); init writes `0x30` | same |

TX pad PA7 (route 6), 115200 8N1; the bootstrap prints a boot trail there. Our header-hook table contains the words
`0x9084, 0x4E1` (1249), `0x9080, 0x10`, `0x9088`, `0x8864, 0x17D78400`, `0x9800, 0x701` next to each other; I did not decode
the table format exactly, so read these as "probably SPR, value pairs" **[guess]**.

## SPI0 (flash controller)

| SPR | Use | Source |
|---|---|---|
| `0x9000` | control: bit 0 enable, bit 1 DMA mode, bit 7 receive direction, **bit 14 CS level (0 = selected)**; init `0x01115005` | SDK `spi.c`, `boot/flasher.c`, tbelbek `flstub.py` |
| `0x9004/0x9008` | 0 at init | same |
| `0x900C` | DMA direction/config: `0x85` RX, `0x05` TX | `spi.c` |
| `0x9244` | start: `1` = one byte; `0x20000` then `2` = DMA; init `0x03FF0000` | same |
| `0x9248` | done flags: bit 0 byte done, bit 1 DMA done | same |
| `0x924C` | clock divider (init 5; boot header `+0x40` writes it during boot) | same, [ROM] |
| `0x9250` | TX/RX byte | same |
| `0x9254` | DMA length in words − 1 | `spi.c` |
| `0x9258` | DMA address | same |
| `0x925C` | DMA config `0x06000000` | same |
| `0x9260` | CRC of SPI data (init `0xFFFF`); the boot ROM compares it with header `+0x30` | `spi.c`, [ROM `0x1006E0`] |
| `0x9264/0x926C/0x9270` | init `0xFFFFFFFF`, `0x0FFFFFFF`, `0x0FFFFFFF` | same |
| `0x9268, 0x9274..0x927C` | zeroed at init | same |

Pins: PA8, PA10, PA11 (`0xD00`), PA10 latch high. PA9 not touched **[src: `spi.c`; pin roles guess]**.

## Second SPI / LCD MCU bus / display

LCD controller (MCU 8080-style bus) [src: SDK `display.c`, `research/display.md`]:

| SPR | Use |
|---|---|
| `0xA800` | LCD control: `0x11` = MCU bus enabled, `0x13` = also start DMA frame; 0 off |
| `0xA804` | status/config: bit 31 = PIO byte done; bit 3 = DMA frame done; write `0x00809F00` to clear/configure, `0x00800800` to ack |
| `0xA808` = 6, `0xA80C` = `0x44`, `0xA810` = `0x090000FF` | bus timing/polarity/width (stock config bytes) |
| `0xA814..0xA838` | 0 |
| `0xA840/0xA844` | width / height |
| `0xA848/0xA84C` | width − 1 / height − 1 |
| `0xA854` | byte count − 1 (`w*h*2 − 1`) |
| `0xA858` | PIO data byte (command/data selected by the RS GPIO) |
| `0xA85C` | output packing word (`0x02100008`), `0xA868/0xA86C` 0 |

Compositor / scaler ("image engine", YUV→RGB565 with DMA) [src: `display.c`]:

| SPR | Use |
|---|---|
| `0xC800` | control: 3 = start, 0 = stop (bit 1 "start image engine" also in penguin STOCK-FIRMWARE.md) |
| `0xC804` = 15, `0xC808`, `0xC80C` (bit 0 done, W1C-ish), `0xC814`, `0xC81C` = `0x707`, `0xC824`, `0xC838` = `0x4000` | setup |
| `0xC810/0xC820/0xC928/0xC92C` | geometry `((rows−1)<<16) \| (w−1)` |
| `0xC818` | mode: `0x52081` = RGB565 out, YUV in, identity scale, main plane |
| `0xC828/0xC830` | Y plane / VU plane addresses (NV21: V,U order) |
| `0xC82C/0xC834` | pitch / 4 (pitch multiple of 32) |
| `0xC920/0xC924` | scale `65536` (1:1) |
| `0xC880..0xC91C` | 40 scaler coefficients |

LCD pins on the Action board: data bus bank C mask `0x1FE0` (PC5..PC12), bank E mask `0x16` (PE1, PE2, PE4) + PE3, RS = PE2,
reset PB6, backlight PA6; mux `0x8348[9:6] = 13`. Panel config is a flash record (type `0x15`) holding mode, bus width, divider,
size and an init table `(op, value)` (op 0 cmd byte, 1 data byte, 3 delay ms, `0xFFFFFFFF` end) [src: `research/display.md`].
Our NV3030B record at flash `0x7C600` is very likely the same format **[guess, check]**.

## I²C (sensor control bus)

| SPR | Use | Source |
|---|---|---|
| `0x9090` | divider (71 → ~400 kHz at 144 MHz) | SDK `camera.c`, `research/camera.md` |
| `0x9094` | bit 7 enable | same |
| `0x9098` | received byte | same |
| `0x909C` | byte to send | same |
| `0x90A0` | command: `0x80` start, `0x40` stop, `0x10` send, `0x28` receive + NACK; bit 0 ack | same |
| `0x90A4` | status: bit 0 done, bit 7 NACK | same |

Pins PD13/PD15 (mux `0x8348[2:0] = 3`).

## ADC

| SPR | Use | Source |
|---|---|---|
| `0x9170` | control: bits 3:0 channel, bit 4 enable, bit 7 start, bit 6 busy | SDK `adc.c`, `research/gpio.md` |
| `0x9174` | divider (71 → 1 MHz at 144 MHz), write-only | same |
| `0x9178` | result, 10 bits | same |
| `0x8840` bit 29 | ADC clock gate (active low) | same |

Channels: 3 = key ladder (Action), 9 = battery (via PM divider, PM54 bit 5), 11 = internal reference (needs `0x8868` bit 15).
Voltage: `mV = 2 * adc9 * cal / adc11 (+20 mV offset)`, `cal` = word in SRAM written by the bootstrap (Action `0x1FEC`, Silvergear
`0x1E14`, **ours `0x1E28`**, read in our bootstrap code at SPI `0x96C`) [src: `battery.c`; ours: my disassembly].

## PWM

No external source documents PWM. Our firmware drives the backlight with "PWM channel 2, 4000, duty brightness*10+20 %".
Update from our code: PWM is the compare output of timers 0-3 (SPR `0x9800 + 0x10*n`); channel 2 = timer 2 at `0x9820`,
routed to PA6 by mux `0x8344[11:8]` ([[analysis/soc_core#5.3 Timers 0-3 (SPR 0x9800 + 0x10 per timer)]], [[analysis/display#9. Backlight — V]]).

## SD / SDIO (SD0)

| SPR | Use | Source |
|---|---|---|
| `0x9880` | control/status: bit 0 enable, bit 1 clock DAT0 while busy, bit 15 data done, bit 16 data CRC error, bit 17 command done, bit 19 command timeout, bit 20 card ready; init `0`, `0x42` | SDK `sd.c`, `research/sd.md` |
| `0x9884` | event/config: bits 2:0 response mode (2 none/CMD0, 3 R2, 5 R1b, 1 R1/R3/R6/R7), bit 4 RX DMA, bits 4+5 TX DMA, bit 6 IRQ enable; W1C for bits 15/17 | same |
| `0x9888` | clock divider: `source/(2*f) − 1` (source 144 MHz; 200 kHz init, 24 MHz run). Boot ROM writes it from the header when booting from SD | same, [ROM] |
| `0x988C` | long response config (`0x2000`) | same |
| `0x9890` | DMA address | same |
| `0x9894` | DMA length (512) | same |
| `0x9898` | command (`cmd \| 0x40`) | same |
| `0x989C` | argument (write) / short response (read) | same |
| `0x9280` | bit 12 set at SD init | same |

R2 (136-bit) responses land in SRAM `0x2000..0x200F`, bytes reversed in each word. Pins: PA0..PA2 1-bit; **PA2 must stay an
output driven low** on the Action board. 4-bit: PA3, PE10, PE11 (inferred). No card-detect pin is used.

## USB (Mentor MUSB-style core)

| SPR | Use | Source |
|---|---|---|
| `0xA000 + 4·n` | byte-wide core registers: `n` = 0 FADDR, 1 POWER (bit 4 HS, bit 5 HS enable, bit 6 soft-connect/pull-up), 2 INTRTX, 4 INTRRX, 0x0A INTRUSB (1 suspend, 2 resume, 4 reset), 0x0E INDEX, 0x10 TXMAXP, 0x12 TXCSR, 0x14 RXMAXP, 0x16 RXCSR, 0x18 RXCOUNT | SDK `usb.c`, `research/usb-musb.md` |
| `0xA080` | EP0 FIFO (write) | same |
| `0xA090` | EP1 FIFO (read/write) | same |
| SRAM `0x8000..` | EP0 setup FIFO, memory-mapped | same |
| `0x984C/0x9850/0x9854` | FIFO addresses `0x8000`, `0x8040`, `0x8240` | same |
| `0x9840` | PHY control: `|= 0x10000`, then `(&0xFC0DF3FF) \| 0x1080`, `|= 0x40`, `|= 1`, `|= 4` with delays (ROM `0x105D20..0x105F28`) | same |
| `0x9870` | bits 31:30 = `10` | same |
| `0xD800..0xD840` | PHY: `0xD840` bit 0 cleared, `0xD804 = 31` then wait bit 3, `0xD800 = 0xF0`, `0xD808 = 0`, `0xD80C |= 0x1800` | same |
| `0xA004` | POWER register copy used to detach (`&= ~0x40`) | `clock.c`, `runtime.c` |

USB detect: PM bus control `0x88E0` bit 21 (external power) [src: `battery.c`].

## Audio DAC (speaker)

| SPR | Use | Source |
|---|---|---|
| `0x9140` | DAC control (`0x10020` init, `0x202C` play) | SDK `audio.c`, `research/audio.md` |
| `0x9144` | length in words − 1 | same |
| `0x9148` | source address (32-byte aligned, DDR) | same |
| `0x914C` | event clear (7) / start (8) | same |
| `0x9150` | events (bit 2 = ran dry/finished) | same |
| `0x9158` | halfwords still to play; writing **adds** (one-deep next-block queue) | same |
| `0x915C` | codec indirect register access: `(index<<24) \| (write?1<<30) \| value`, busy bit 31 | same |
| `0x9160` | codec indirect read result | same |

Codec registers via `0x915C`: 0 (bit 0 enable, bits 7:4 rate selector), 2, 3 (gain = 32767·%/100), 4, 10..14 setup, 15 filter
coefficients (27 words). Amplifier: `0x8874` bits 7:0. Rates 8/16/32 kHz.

## Audio ADC (microphone)

| SPR | Use | Source |
|---|---|---|
| `0x9100` | control (rate prescaler from `board.h`, bits 0..3 run/enable) | SDK `microphone.c` |
| `0x9104` = `0x7C0002`, `0x9110` = `0x780A0005`, `0x9118`, `0x911C` = `0x40003000`, `0x9120` = `0x01007800` | setup | same |
| `0x9108/0x910C` | DMA address / length in words − 1 | same |
| `0x9114` | status/control: bit 0 buffer full, bit 1 half, bit 2 ready, bit 31 start | same |

## JPEG codec

Base `0xC000` ("JD") [src: SDK `jpeg.c`, `research/jpeg.md`]: `+0x00` control (decode `0x60000023 | …`, encode `0x0040EC01 |
sel<<23`), `+0x0C` size `(w<<16)|h`, `+0x10/+0x14` output (Y / VU or bitstream + limit), `+0x20/+0x24` input, `+0x2C` bit
offset, `+0x34` restart interval, `+0x3C`, `+0x4C` component table config, `+0x78..+0x80` scaling, `+0x84..+0x148` filters,
`+0xA4`, `+0xB0`, `+0xC0`. Quant/Huffman tables are written to **SRAM `0x66400`** (796 bytes). `0xB800` cleared with it
(role unknown). Clock gate `0x8840` bit 31, reset `0x8880` bit 2, IRQs PIC 16/22. tbelbek found stock code programming JPEG
SPRs `0xB18C..0xB1B0` (those are CSI scaler filters per matu) — `luxorparts FINDINGS.md`.

## CSI / sensor interface (DVP) and scaler

| SPR | Use | Source |
|---|---|---|
| `0xB000` | input config (`0x286`), bit 0 capture enable | SDK `camera.c`, `research/camera.md` |
| `0xB004` | preset (0 native, `0x00420000` scaled preview) | same |
| `0xB008` | bit 19 scaler parameter latch | same |
| `0xB00C` | W1C status: bit 0 native frame done, bit 1 scaled done, bit 3 frame start; error mask `0x000E0970` | same |
| `0xB014` | transfer config (`0x8006F839` native, `0x8008005A` scaled) | same |
| `0xB018` | bit 19 receive enable, bit 18 one-shot scaled DMA (self-clears) | same |
| `0xB01C` | input (h−1, w−1), `0x01DF027F` | same |
| `0xB020/0xB024` | `0x00640190` / `0x02D00500` | same |
| `0xB030/0xB034` | crop ends `640<<16`, `480<<16` | same |
| `0xB040..0xB064` | DMA: `0xB050/0xB054` native Y/VU, `0xB058` height, `0xB05C` luma bytes, `0xB060/0xB064` scaled Y/VU | same |
| `0xB068` | scaled pitch | same |
| `0xB180..0xB188` | scaled size and ratios | same |
| `0xB18C..0xB1E8` | 24 scaler filter words | same |

Sensor MCLK: PD10 (mux `0x8348[11:10] = 2`), `0x884C[12:8]` divider, `0x8850` bit 26. DVP pins PD2..PD9, PD11, PD12, PD14.
Output is 640×480 Y + interleaved VU.

## ISP

No source documents an ISP block. `0xB800..0xB940` (seen in our firmware and cleared by the SDK JPEG driver) is a candidate
**[guess]**. Sensor-side processing is done in the sensor registers.

## DMA

No general DMA engine is documented. Each block has its own DMA (SPI0, SD, DAC, mic, LCD/compositor, CSI, JPEG). The stock
firmware has an "asynchronous DMA memory copy" routine (penguin: `0x29CA0`/`0x29C3C` in their build), registers unknown.
Before any DMA: write back the source (`0x180C`), invalidate the destination (`0x1814`).

## RTC

Not found in any source. penguin: the clock value lives in RAM (`0x02086A00` in their build) and "survives power-off (battery
backed)" — so it is kept in the always-powered domain or recomputed **[guess]**. Our menu has date/time; look in our code.

## Board constants: Action camera (SDK) vs ours

| Function | Action JT5295 (`firmware/sdk/board/board.h`, `research/*.md`) | Silvergear (`appotech-sdk/boards/silvergear-3222882/board.h`) | MO2947 (from our code reports, 2026-11-12) |
|---|---|---|---|
| Power hold | PM chip regs (`0x40`, `0x5A`, …) | PM chip, different variant | PMU reg `0x40` = `0x0E` hold; full sequence in [[analysis/soc_core#3.2 What our firmware must do first to stay on]] [ours] |
| POWER key | PB0, high = pressed | on the ADC ladder | **PB0**, high = pressed; ioctl `0x2000000D` [ours] |
| Key ladder | ADC ch 3, centres 0/306/484/658/817 ±29 = SHUTTER/DOWN/UP/LEFT/RIGHT (stock codes 26/28/27/29/30) | ch 3, 7 keys | **same centres** 0/306/484/658/817 ±29, ADC channel 3; `0x1C` SHUTTER, `0x1F` DOWN, `0x1E` UP, `0x22` LEFT, `0x23` RIGHT [ours, from the handlers; confirmed on the device 2026-11-12] |
| Extra ad-key input | PB1 configured as input (role unknown) | PB1 | PB1 configured as input, never read [ours] |
| Status LED | PB5 (bank 1 mask `0x20`), via force-high/low overrides, active high | PB0 latch output | port 1 mask `0x20` = **PB5** [ours] |
| LCD reset | PB6 (bank 1 mask `0x40`) | dedicated `0x886C/0x8874` output | **PB6** pulse [ours]. (The mask-`0x40` pin driven low in `lcd_init` is PA6, the backlight) |
| LCD backlight | PA6 GPIO | PM54 bit 6 | **PA6**, PWM channel 2 (timer 2), 4 kHz [ours] |
| LCD RS | PE2 | PE2 | **PE2** [ours] |
| LCD bus | PC5..PC12, PE1/PE3/PE4, MCU 8-bit, divider 20 | divider 15, 240×320 ST7789 | NV3030B 240×320, PC5-PC12 + PE1-PE4, MCU 8-bit, divider 15; config at flash `0x7C600` [ours] |
| Speaker amp | internal, `0x8874` | | probably same |
| Sensor | SP0A39, I²C `0x42/0x43`, ID reg 1 = `0x39`; PD0 reset (pulse), PD1 power-down (low) | two sensors, enable masks `0x400`/`0x800` | 7 probe entries, fitted one unknown ([[analysis/camera]]); I²C PD13/PD15; PD0 low, PD1 high at start [ours] |
| Sensor MCLK | PD10, 24 MHz | | PD10, 24 MHz (20.6 MHz for SC030IOT) [ours] |
| SD | SD0 1-bit PA0..PA2; PA2 output low; no card detect | 1-bit | SD0 on PA0-PA3 + PE10/PE11; card detect by command response, no pin [ours] |
| USB detect | `0x88E0` bit 21 | | `0x88E0` bit 21 [ours] |
| Battery ADC | ch 9 + ref ch 11, cal SRAM `0x1FEC`, +20 mV | cal `0x1E14`, +30 mV | ch 9 + ch 11, cal SRAM `0x1E28`, +20 mV [ours] |
| UART debug | PA7 TX, 115200 | PA7 | PA7 TX, 115200 [ours] |
| Flash | `5E4015` 2 MiB, PA8/PA10/PA11 | `944016` 4 MiB | `5E4016` 4 MiB |
| DDR | 4 MiB | 4 MiB | **2 MiB likely** (bootstrap stack `0x021FFFFC`) |
| Saved ROM stack (bootstrap) | SRAM `0x1E6C` | `0x1C94` | **`0x1A38`** |
| App entry hook in bootstrap | SPI `0x528` | SPI `0x540` | SPI `0x528` → `0x020004A8` |
| CPU clock | 144 MHz | 144 MHz | 144 MHz [ours] |
