# SoC core and board control (MO2947, AX3295B family)

> [!summary]
> CPU and clocks, RAM and SRAM map, **power hold (PMU register 0x40)**, power key, every GPIO pin, timers, watchdog, interrupts, ADC, UART, the bootstrap and header hook, and the full SPR map. Verified in the stock code (tags V / I / X). Short version: [[HARDWARE]].

Topic `soc_core`. Sources: `analysis/export/all.asm` / `all.c`, the raw app image, flash sector 0 + bootstrap
(`dumps/mo2947_flash_a.bin` 0x000-0x21FF, disassembled with my own python decoder), cross-checked against
`analysis/research_registers.md`, `analysis/research_usb_flashing.md`, `ext/appotech-sdk` and the DOOM SDK copy.
Tags: **V** = verified in our code (address cited), **I** = inferred / guess, **X** = from the external SDK and consistent
with our code.

Scripts (scratch, not in the project): an SPR tracker that follows `l.movhi/l.ori/l.addi/l.add/l.slli` per function
(affine expressions over the arguments, so `0x8000+4*(0x70+port)` comes out as `4*a0 + 0x81c0`) and records every
`l.mtspr/l.mfspr` and the constant arguments of every `l.jal`.

## 1. Summary (the facts you need first)

| Item | Value | Tag |
|---|---|---|
| CPU / bus clock | 144 MHz (all dividers use the constant `0x08954400` = 144 000 000: timers `0x020281B4`, UART `0x02027FAC`, ADC `0x0202B0D8`, PWM `0x02028520`) | V |
| RAM | SDRAM at `0x02000000`, firmware uses 2 MiB (stack top `0x021FFFFC`, BSS clear ends `0x021FEC00`) | V (size I) |
| On-chip SRAM | `0x00000`-`0x43FFF` (cache helpers treat `<0x44000` as uncached; bootstrap writes `0xDEADDEAD` to `0x43FFC`). Bootstrap/vectors live in `0x0000-0x1FFF` | V/I |
| Power hold | PMU register `0x40` via the PMU bus (SPR `0x88E0/0x88EC`): `0x0E` = hold (stock), `0x02` = release. Done in the first call of `app_init`: `pm_power_hold(1)` `0x02029D54` | V |
| Power key | **PB0** (port 1, mask 1), digital, **high = pressed** | V |
| LED | **PB5** output, high = on | V |
| USB / VBUS present | SPR `0x88E0` bit 21 (`usb_vbus_present` `0x02029F00`) - not a GPIO | V |
| Keys ADC | SAR ADC channel **3**; battery = channel **9**, internal reference = channel **11** | V |
| Backlight | **PA6**, PWM on timer 2 (route 2), 4 kHz, duty = `brightness*10+20` % (max 99) | V |
| LCD reset | **PB6** (pulse high-low-high) | V |
| Sensor ctrl | PD0 driven low, PD1 driven high (`0x02002CA8`, from `sensor_ioctl`) - PWDN/RESET roles I | V/I |
| Debug UART | UART0 TX on **PA7** (mux route 6), **115200 8N1**, 144 MHz/1250. The bootstrap prints `'a'` at boot; the app has `uart_printf` `0x02036E5C`. `battery_init` later parks PA7 as input+pull-up | V |
| Watchdog | SPR `0x880C`: app enables `0x50006` (sel 6 ~7.3 s), kicks it in the main poll (`0x02027064`), `0x5500` = off | V (timing X) |
| System tick | Timer 0 at 100 Hz -> `g_ms` (`0x0207EFAC`) += 10 per tick | V |
| IRQ | Two vectors: `0x50` (full save, SRAM `0x1CC` -> `0x02026078`) and `0x80` (SRAM `0x2A4` -> `0x02025F98`); IRQ number in SPR `0x480C`; mask SPR `0x4800`; global enable SPR `0x18` bits 1/2 | V |

## 2. Start-up path (who runs what)

1. Boot ROM reads sector 0 (header), runs the **header hook** (flash `0x4C`), which calls ROM services with inline
   tables (PLL, UART, timer, SPR scripts) and loads flash `0x200-0x21FF` to **SRAM 0**, then calls SRAM `0xDD0`
   (`boot_sdram_init`, see section 9). V (ROM side from research_usb_flashing.md)
2. ROM loads the app (`0x3D2` sectors from `0x2200`) to `0x02000000` and jumps to SRAM 0 (header `+0x2C` = 0).
3. SRAM 0 = vector slot 0: `l.j 0x304` -> save 256 bytes of the ROM stack page to SRAM `0x1A38`, `r1 = 0x021FFFFC`,
   call `boot_early_init` (SRAM `0x6C8`), call **`app_main` `0x020004A8`** (the absolute call is at flash `0x528/0x52C`),
   and if it ever returns (task id 10 leaves the task loop) restore the ROM stack and return to the ROM. V
4. `app_main` -> `app_init` `0x020000BC`:

| Order | Call | What it does | Tag |
|---|---|---|---|
| 1 | `pm_power_hold(1)` `0x02035304`->`0x02029D54` | PMU bus enable (`0x88E0 |= 0x40`), PMU reg `0x40 = 0x0E` (**keeps the camera on**) | V |
| 2 | `pm_domain_init(1)` `0x02029F48` | PMU reg `0x42 = 0xE0`, reg `0x44 = 0`, reg `0x58 |= 8`, reg `0x40 |= 0x10` (-> `0x1E`), reg `0x5A = 8` | V |
| 3 | `heap_init` `0x02037710` -> `sys_init` `0x02026B64` | IRQs off (SPR `0x18` bits 1,2), WDT kick, I-cache on, D-cache on (window `0x02000000`), **BSS clear `0x0207A278-0x021FEC00`**, SRAM clear `0x1E3C-0x449B`, analog: `0x8868` bit15 (ADC ref) and bits 14:13=01, LDO1/LDO0 trim 0x14, clocks on (gates 0x1B CSI, 0x1A, 0x1F JPEG, 0x11 RTC/PMU), IRQ-15 callback = `0x0202C108` (USB), `irq_init` `0x020261FC`, heap range `0x02092180-0x021FEC00`, bus arbiter `0x02026FAC`, **watchdog on (`0x50006`)**, IRQs on (SPR `0x18 |= 6`) | V |
| 4 | `uart_init_debug` `0x02036AEC` | PA7 TX, 115200, IRQ 8 | V |
| 5 | `task_init`, `task_register_all` | task table | V |
| 6 | `0x0201F454` (clears `g_ms`, more inits), `timer_start(0, 100 Hz, systick_isr 0x0201F494)` | 10 ms tick, soft timers | V |
| 7 | `soft_timer_add(1000 ms, 0x0200E850)` | 1 s callback (video record clock text) | V |
| 8 | `FUN_0200236c(0)` (`dev_init_all`) | RTC init, `adc_init` (ch 3, 1 MHz), more inits, then each driver's `init` from `g_dev_table` | V |
| 9 | look up devices; if `battery` init failed -> **`system_power_off` `0x0200B51C`** | low battery at boot (<3250 mV and no USB) turns the camera off | V |
| 10 | read power key (`0x2000000D`) and USB; LED set; settings, sensor start, etc. | | V |

## 3. Power: hold, key, shutdown, auto-off

### 3.1 PMU bus (always-powered PMU/RTC block)

SPR `0x88E0` = control/status: bit 3 busy, bit 6 bus enable, bit 8 transaction active, bits 0/1 RTC IRQ flags
(`rtc_isr` `0x02029A54`), **bit 21 = VBUS present**. SPR `0x88EC` = data byte. V (matches X).

| Function | Address | Behaviour |
|---|---|---|
| `pm_tx(byte)` | `0x020296A8` | `0x88EC = b`, wait `0x88E0` bit 3 clear (timeout 0x8000) |
| `pm_rx()` | `0x020296F8` | `0x88EC = 0`, wait busy, return `0x88EC & 0xFF` |
| `pm_read(cmd, buf, n)` | `0x02029894` | `0x88E0 |= 0x100`; tx cmd; rx n bytes; clear bit 8 |
| `pm_write(cmd, buf, n)` | `0x0202991C` | same, tx n bytes |
| `pm_ram_read(addr, buf, n)` | `0x0202975C` | cmd `0x52`, addr, n bytes (PMU backup RAM) |
| `pm_ram_write(addr, buf, n)` | `0x020297F8` | cmd `0x53` |
| `rtc_read_counter()` | `0x02029CB8` | cmd `0xE0`, 4 bytes big-endian |
| `rtc_write_counter(v)` | `0x02029D0C` | cmd `0xF0` |
| `rtc_write_alarm(v)` | `0x02029C70` | cmd `0x51` |

Register convention: **even = read, odd (reg+1) = write** (e.g. read `0x54`, write `0x55`). V

| PMU reg | Stock use | Function |
|---|---|---|
| `0x40` | `0x0E` hold, then `|0x10`; `0x02` = release (power off) | `pm_power_hold` `0x02029D54`, `pm_domain_init` |
| `0x42` | `|= 0xE0` / `= 0xE0` | `pm_domain_init`, `rtc_init` `0x020299A4`, power-off `0x0202A100` |
| `0x44` | `0` on, `0x10` at power-off | `0x0202A0B0` |
| `0x54` | bit 5 = battery divider enable (`battery_div_enable` `0x0202A13C`); bit 7 set/cleared with LDO0 boost (`0x0202A1AC`); `rtc_init` writes `0x01` | |
| `0x58` | `|= 8` at start; bits 0,5 = RTC alarm enable (`0x02029B88`) | |
| `0x5A` | bit 3 = USB/VBUS path enable (`usb_init` -> `0x02029E90`; off clears bits 3 and 5) | |

### 3.2 What our firmware must do first to stay on

The power key only powers the SoC while it is pressed; the hold is PMU reg `0x40`. Do this as early as possible (the stock
code does it as the very first call of `app_init`, i.e. within a few ms of reset, before the BSS clear):

```
SPR 0x88E0 |= 0x40                 ; PMU bus enable
pm_write(0x41, 0x0E)               ; hold  (stock value; Action SDK uses 0x06 - keep 0x0E for this board)
pm_write(0x43, 0xE0); pm_write(0x45, 0x00)
v = pm_read(0x58); pm_write(0x59, v | 0x08)
v = pm_read(0x40); pm_write(0x41, v | 0x10)
pm_write(0x5B, 0x08)               ; USB/keep-alive path; never clear it (X: clearing cut USB power)
v = pm_read(0x54); pm_write(0x55, v | 0x20)   ; battery divider on (needed before ADC ch 9)
```
Also keep the watchdog fed or disable it (`0x880C = 0x5500`): the bootstrap leaves it on with `0x5001D` (~1.8 s, X).
The PMU registers survive resets (X), so a camera that was power-cycled by our code may already be latched; do not rely
on that.

### 3.3 Power key

- `adkey_init` `0x02002694`: `gpio_config(PB, 0x1, input, no pull)` and `gpio_config(PB, 0x2, input, no pull)`. V
- `adkey_ioctl(0x2000000D)` returns `gpio_read(PB, 1)` = raw power key. V
- `adkey_scan` `0x02002DE4`: if PB0 is high -> key code `0x25`; else ADC ch 3 against `adkey_table`. A code is
  reported only after 3 equal reads. `adkey_event` `0x02002ED0`: power held 30 reports -> `0x27` (long press = power
  off), shorter -> `0x25`; key `0x1C` (ADC 0) held 30 -> `0x1D`. Scan period: `0x0200BC7C` polls when 11 ms have passed
  (10 ms tick) -> long press about 1.5-2 s (I).
- PB1 is configured as an input but never read in the code found (I: aux/charger status).

### 3.4 Shutdown

`PowerOff_enter` `0x0200B5C4` plays the animation; if VBUS present -> LED off, `task_switch(9 USB)`. Else
`system_power_off` `0x0200B51C` (V, exact order):
1. backlight off (`lcd_ioctl 0x20000004, 0`), LED off;
2. if `DAT_020818E5` != 0: wait until the power key reads 0 (released);
3. `timer_stop(0)` (tick), `sys_power_down` `0x02026CC4` (LDO0 off via `0x02026658(0,0x16,0)`, clock gates
   0x1B,0x1A,0x1F,0x19,0x1D,0x18,0x1E,0x07,0x16,0x14 off);
4. PMU reg `0x44 = 0x10`, reg `0x42 = 0xE0`, **reg `0x40 = 0x02`** -> power cut;
5. spin forever (`delay(50)` loop). With USB power the SoC stays alive and the watchdog (not fed) resets it (I).

### 3.5 Auto power off, screen saver, low battery

Called every 10 ms from the main poll `main_poll` `0x02000440` -> `power_mgr_poll` `0x0200C50C`:
- `screensaver_poll` `0x0200BB2C`: settings slot 10 (seconds); on a key -> backlight on; idle longer than the slot ->
  backlight off (`lcd_ioctl 0x20000004, 0`). Not in task 1. V
- `autooff_poll` `0x0200BDAC`: every 500 ms adds 500 ms of idle time unless the task is 0/9 (USB) or video/playback is
  busy; idle >= slot 9 x 1000 ms -> `task_switch(1)` (Power Off). V
- Boot check: `battery_init` `0x02002B74` fails when `mV + 50 < 3300` and no VBUS -> `system_power_off`. V
- Fatal exception handler in the bootstrap (section 9) powers off when the battery is <= 3700 mV.

## 4. GPIO

Five ports PA..PE = 0..4, 16 pins each, register = base + 4*port. All helpers check `port < 5`, `mask < 0x10000`.

| SPR base | Meaning | Helper (our firmware) | Tag |
|---|---|---|---|
| `0x8000` | output latch (write) / pin level (read) | `gpio_write(port,mask,level)` `0x020274F8`, wrapper `0x0203218C`; `gpio_read(port,mask)` -> 0/1 `0x02027600` (allows port<6), wrapper `0x020321B4` | V |
| `0x8040` | direction, **1 = input**, 0 = output | `gpio_set_input(port,mask,in)` `0x020272F8` | V(+X) |
| `0x8080` | pull-up | `gpio_set_pull(port,mask,flags)` `0x0202739C` flag bit 0 | V(+X) |
| `0x80C0` | pull-down | same, flag bit 1 | V(+X) |
| `0x8100` | peripheral/alternate function enable (set for UART TX PA7, PWM PA6, SPI, SD, LCD bus) | `gpio_set_altfunc(port,mask,on)` `0x02027684` | V use, meaning I |
| `0x8140` | cleared for GPIO; no other user | `0x02027468` | role unknown |
| `0x81C0` | override "force high" (X) | `gpio_set_override(port,mask,flags)` `0x02027834` bit 0 | V |
| `0x8200` | override "force low" (X) | same, bit 1 | V |
| `0x8380` | pad digital enable (set for GPIO and LCD bus; I) | `gpio_set_digital(port,mask,on)` `0x02027714` | V use |
| `0x8340/0x8344/0x8348` | pin mux fields | `pinmux_select(func,route)` `0x020270B4` | V |
| `0x83C0` / `0x83CC` | GPIO interrupt enable / pending (write `0xFFFF0000` to ack); 27 callbacks at `0x0207F0C0`; IRQ 7 | `gpio_irq_isr` `0x02027B20` | V (no user found) |

`gpio_config(port, mask, dir_in, pull)` `0x02031F60` = `0x8380 |= mask`, clear `0x8100`, `0x8140`, set direction,
clear both overrides, set pulls. (Order exactly as listed.) V

`pinmux_select(func, route)` fields (V, `0x020270B4`):

| func | SPR | bits | used for |
|---|---|---|---|
| 0 / 1 | `0x8340` | 19:15 / 14:10 | ? |
| 2 / 3 | `0x8340` | 9:5 / 4:0 | UART0 TX / RX route (TX 6 = PA7) |
| 4 | `0x8344` | 24:22 | ? |
| 5 | `0x8344` | 21:20 (route-1 if >2) | SPI0 (`0x02028EB4`) |
| 6 | `0x8344` | 19:17 | ? |
| 7 | `0x8344` | 16 | SD (`0x020569A0`, route 1) |
| 8 / 9 / 10 / 11 | `0x8344` | 15:12 / 11:8 / 7:4 / 3:0 | PWM out of timer 3 / 2 / 1 / 0 |
| 12 / 13 / 14 | `0x8348` | 20 / 19:17 / 16:14 | ? |
| 15 | `0x8348` | 11:10 | sensor DVP/MCLK (route 2) |
| 16 | `0x8348` | 9:6 | LCD 8080 bus (route 13) |
| 17 | `0x8348` | 5:3 | ? |
| 18 | `0x8348` | 2:0 | I2C (route 3 = PD13/PD15) |

### 4.1 Every pin the firmware touches

| Pin | Use | Evidence (caller) | Tag |
|---|---|---|---|
| PA0-PA3 (`0xF`,`7`,`0xA`,`4`) | SD card bus (PA2 driven low) | `0x020569A0` | V (details: SD agent) |
| PA6 (`0x40`) | **LCD backlight**, PWM timer 2 route 2; `lcd_init` sets it output low; on: `0x8100` set + `pwm_start(2,2,4000,duty)` | `0x02002820/0x02002830`, `lcd_ioctl` `0x02002AE4/0x02002B14` | V |
| PA7 (`0x80`) | **UART0 TX** (bootstrap + `uart_pins_init` `0x02027F0C`); `battery_init` reconfigures it as input with pull-up (`0x02002BA0`) | | V |
| PA8, PA10, PA11 (`0x100`,`0x400`,`0x800`; `0xC00`,`0x3C0`,`0x300` variants) | SPI0 flash bus | `0x02028EB4` | V (SPI agent) |
| PB0 (`0x1`) | **power key**, input, high = pressed | `0x02002720`, `0x02002DFC`, `0x020030B0`, `0x0201B2EC` | V |
| PB1 (`0x2`) | input, not read | `0x02002734` | V/I |
| PB5 (`0x20`) | **status LED**: output + override bit `0x8200` set at init; `led_ioctl(0x20000015, on)` writes the latch | `led_init` `0x0200276C/0x0200277C`, `led_ioctl` `0x02002A84` | V |
| PB6 (`0x40`) | **LCD reset**: output, high, delay 20, low, delay 50, high, delay 50 | `lcd_reset` `0x02002C30` (from `0x02033860`) | V |
| PC5-PC12 (`0x1FE0`) | LCD 8080 data bus | `0x0202F94C`, `0x0202FA30` | V (display.md) |
| PC5, PC6, PC7 (`0x20`,`0x40`,`0x80`) | bit-banged lines (LCD/other serial) | `0x0202EEC0`, `0x0202EF70`, `0x0202EFAC` | V use / I role |
| PD0 (`0x1`) | output low (sensor PWDN? I) | `sensor_power_pins` `0x02002CA8` | V/I |
| PD1 (`0x2`) | output high (sensor RESET#? I); driven low by the bootstrap fatal handler | same | V/I |
| PD2-PD14 (`0x5BFC`/`0x5FFC`), PD10 (`0x400`) | sensor DVP bus, PD10 output with alt function (MCLK, I) | `0x0202E2F8`, `0x0202E37C` | V (sensor agent) |
| PD13, PD15 (`0xA000`) | I2C SCL/SDA (pull-ups, mux 18 = 3) | `0x0202A594` | V |
| PE1-PE4 (`0x16`,`0x8`,`0xE`,`0x10`) | LCD control (PE2 = RS/DC toggled per byte) | `0x0202F120..0x0202F25C`, `0x0202F94C` | V (display.md) |
| PE10, PE11 (`0xC00`) | SD (wide bus extra pins) | `0x020569A0` | V |
| PA8, PD1, PA6, PA7 | driven low by the bootstrap's fatal/low-battery power-off | SRAM `0x1928..0x1A14` | V |

No GPIO for USB detect (PMU bit), SD detect (`sdcard_ioctl` calls `0x02035B98`, a card command probe, I), or a speaker
amplifier (audio uses SPR `0x8874`, X) was found.

## 5. Clocks, timers, delays, watchdog

### 5.1 Clock gates (SPR `0x8840`, `0x8844`; bit set = clock off)

`clk_enable(id, on)` `0x0202683C`: id 0-31 -> `0x8840`, 32-63 -> `0x8844`; on clears the bit. V

| id | Block (caller) |
|---|---|
| 0x07 | display compositor `0x0202D288` |
| 0x0A-0x0D | timers 0-3 (PWM) `0x02028520` |
| 0x11 | RTC/PMU `0x020299A4` |
| 0x14 | SPI0 `0x02028EB4` |
| 0x16 | SD `0x020569A0` |
| 0x18, 0x1E | audio DAC / mic `0x0202AF28`, `0x0202B4B8` |
| 0x19 | LCD `0x0202F2E0` |
| 0x1A | image block at `0xB800` (IRQ 16) `0x02030860` |
| 0x1B | CSI `0x0202E350` |
| 0x1D | SAR ADC `0x0202B070` |
| 0x1F | image block at `0xC000` (JPEG, IRQ 22) `0x02030EC0` |
| 0x21 | block at `0xD000` (IRQ 27) `0x0202CE68` |
| 0x22 | block at `0x8980` (IRQ 23) `0x0202CBCC` |

Clock select/divider SPRs `0x8848/0x884C/0x8850/0x8854` are written by audio, CSI, SPI and USB drivers (other agents;
see research_registers.md). `0x887C` = LCD clock divider. PLL1 (`0x8858/0x885C`) is **never written by the app**; it is set
before the app runs (header hook, section 9).

### 5.2 Analog / LDO SPR `0x8868` (`analog_cfg(sel, value, en)` `0x02026658`)

| sel | bits | stock call |
|---|---|---|
| 0 | 4:0 value, 5 enable, 6 boost (only if `0x8800` hi16 != 0 and value > 0x16; also PMU reg 0x54 bit 7) | `(0, 0x14, 1)` in `sys_init`; `(0,0x16,0)` off at power-down |
| 1 | 11:7 value, 12 enable | `(1, 0x14, 1)` |
| 2 | 15 enable, 20:16 value | - |
| 3 | 14:13 | `sys_init` writes 01 directly |
| 4 | 21 | - |
| 5 | 10 | - |
Bit 15 must be set for ADC channel 11 (X; `sys_init` sets it). The bootstrap copies an OTP trim into bits 20:16.

### 5.3 Timers 0-3 (SPR 0x9800 + 0x10 per timer)

| Offset | Meaning |
|---|---|
| `+0` | control: bit 0 run, bit 3 IRQ enable, bit 1 PWM output, bits 13:11 prescaler shift (divide by `1<<ps`), bits 10:8 clock source (bootstrap `0x701` = 32 kHz free-run, I) |
| `+4` | counter (`0x9804` is the 14-bit 32.768 kHz counter after the bootstrap, X) |
| `+8` | period (reload) |
| `+C` | PWM compare |
| `0x98A8 + 4*n` | status/ack: ISR writes `|= 0x20`; PWM init writes `0x30` |

- `timer_start(n, hz, cb)` `0x020281B4` (wrapper `0x020368D8`): ps = 3 if hz > 749999 else 7; period =
  `(144e6/hz >> ps) - 1` (must be <= 0xFFFF); ctrl = `ps<<11 | 9`; counter = 0; callback in `0x02082D5C[n]`; IRQ n on. V
- `timer_stop(n)` `0x020282B0` (wrapper `0x020368FC`): ctrl &= ~9, IRQ n off, callback cleared. V
- Timer ISRs `0x02028060/0x020280A4/0x020280E8/0x0202812C` (IRQ 0-3): ack, call callback. V
- `pwm_start(n, route, hz, duty%)` `0x02028520` (wrapper `0x020369B0`): duty clamped 1..99; period =
  `144e6/hz/2 - 1`; compare = `duty*period/100`; mux func `11-n` = route; pin set as output; clock gate on;
  ctrl = `0x800` (ps 1), `+8` period, `+C` compare, `+4` = 0, status `0x30`, then ctrl bit 1 set (cleared if duty == 1).
  `pwm_stop(n)` `0x02028998` (wrapper `0x020369DC`): gate off, mux field = 0. V
- PWM routes (pin made an output; from the decompile): timer 2: 0/1 PA2, **2 PA6**, 3 PC0, 4 PE0, 5 PE8, 6 PD1 (V, asm);
  timer 0: 1 PA1, 2 PA4, 3 PB0, 4 PB1, 5 PB5, 6 PB6, 7 PC2, 8 PE2, 9 PE11, 10 PD15; timer 1: 1 PA1, 2 PA5, 3 PB4,
  4 PC3, 5 PC10, 6 PE7, 7 PD0; timer 3: 1 PA3, 2 PA9, 3 PE1, 4 PE9, 5 PD2 (I, decompile only).
  So the LED (PB5) could be dimmed with timer 0 route 5 (I).

### 5.4 Time base, delays, soft timers

| Function | Address | Notes |
|---|---|---|
| `systick_isr` | `0x0201F494` | `g_irq_depth` (`0x02082CD4`)++; `g_ticks` (`0x0207EFA8`)++; **`g_ms` (`0x0207EFAC`) += 10**; `soft_timer_service`; depth-- |
| `get_ms()` | `0x0201F504` | returns `g_ms` (10 ms resolution) |
| `get_ticks()` | `0x0201F560` | 10 ms ticks |
| `delay_ms(ms)` | `0x0201F524` | busy-waits on `g_ms`; **returns at once if `g_ms` is still 0** (tick not started) |
| `soft_timer_init` | `0x0201F580` | 8 slots of 16 bytes at `0x0207EFB0` `{remaining, period, cb, -}` |
| `soft_timer_add(ms, cb)` | `0x0201F5C0` | returns slot pointer or 0 |
| `soft_timer_del(h)` | `0x0201F64C` | |
| `soft_timer_service` | `0x0201F67C` | subtracts 10 ms, calls cb, reloads |
| `delay_loop(n)` | `0x02026340` | `n*16000` empty iterations, no timer (used before the tick runs: LCD reset, PMU) - roughly 0.5-1 ms per unit (I) |
| `delay_spin(n)` | `0x0202637C` | n iterations |

### 5.5 Watchdog SPR `0x880C`

`wdt_enable(on)` `0x0202701C`: on -> `0x50006`, off -> `0x5500`. `wdt_kick()` `0x02027064`: if `0x880C` bit 4 set,
write `0x50006`. Kicked from `main_poll` `0x02000440` (every loop of `task_run_loop`) and from long operations (photo,
video, upgrade). `upgrade_DestBin` disables it during the flash rewrite. Bootstrap uses `0x5001D`; the fatal handler
`0x50005`. Selector timing (X): 5 ~1.8 s, 6 ~7.3 s. `0x39` = immediate reset (X, not used by stock app).

## 6. Interrupts, exceptions, caches

### 6.1 Vector table (SRAM `0x0000`, 16-byte slots, first word = `l.j`)

| Slot | Target (SRAM) | Meaning |
|---|---|---|
| `0x00`, `0x10` | `0x304` | reset / entry: save ROM stack, SP `0x021FFFFC`, `boot_early_init`, `app_main` |
| `0x20,0x30,0x40,0x60,0x70,0x90,0xA0,0xB0,0xC0,0xD0,0xE0,0xF0` | stubs `0x158..0x1B4`: `r3 = vector; j 0x1B8` -> `jalr 0x17B0` (`fatal_exception`) ; `l.rfe` | bus error, page faults, alignment, illegal, TLB, range, syscall, FP, trap |
| `0x50` | `0x1CC` | **IRQ path A**: saves r2-r9,r11-r31 odd + EPCR(`0x20`)/ESR(`0x40`), calls `irq_dispatch_a` `0x02026078`, restores, `l.rfe` |
| `0x80` | `0x2A4` | **IRQ path B**: saves only r9, EPCR, ESR, calls `irq_dispatch_b` `0x02025F98` (the C code must save the rest; it is compiled code, so it does), `l.rfe` |

Neither dispatcher is in the Ghidra export (not disassembled): `0x02025F98..0x02026168`.
`irq_dispatch_a`: IRQ = `SPR 0x480C & 0x1F`, jump table `0x02063798`. `irq_dispatch_b`: IRQ = `(SPR 0x480C >> 16) & 0x1F`,
table `0x02063720`. Both tables (V):

| IRQ | Handler | Block |
|---|---|---|
| 0-3 | `0x02028060`, `0x020280A4`, `0x020280E8`, `0x0202812C` | timers 0-3 |
| 4 | `0x0202F72C` | LCD (`0xA800`) |
| 5 | `0x02029A54` | RTC/PMU (`0x88E0` bits 0/1 -> callbacks `0x02082D6C/0x02082D70`) |
| 6 | `0x0202AA44` | audio DAC |
| 7 | `0x02027B20` | GPIO interrupt |
| 8 | `0x02027EBC` | UART0 RX (callback `0x0207F12C`) |
| 14 | `0x0202DEFC` | CSI/sensor |
| 15 | `*(0x02082D4C)` = `0x0202C108` | USB |
| 16 | `0x020300EC` (table A only) | image block `0xB800` |
| 18 | `0x0202B184` | microphone ADC |
| 21 | `0x0202D208` | compositor |
| 22 | `0x02031274` | image/JPEG block `0xC000` |
| 23 | `0x0202CD38` (A only) | block `0x8980` |
| 26 | `0x0202CA44` | block `0x9028` |
| 27 | `0x0202D0DC` (A only) | block `0xD000` |
| 29 | `*(0x02082D50)` | callback |

`irq_enable(n, on)` `0x0202616C`: SPR `0x4800` bit n (1 = enabled). `irq_set_b(n,on)` `0x020261B4` (not in export; one
caller `0x0203B6DC`): SPR `0x4804` bit n - probably selects path B for that IRQ (I). `irq_init` `0x020261FC` clears
mask bits 0-8,14,15,18,21,22,29 and sets `0x4814` bit 1 (meaning unknown). Global: SPR `0x18` bits 1 and 2 are cleared
together at the start of `sys_init` and set together at its end (V); that bit 1 = "external IRQ enable" is X, and the
pairing bit 1 -> path A / bit 2 -> path B is I. Bit 14 is set by the bootstrap (V) and must be cleared before
returning to the ROM loader (X).

### 6.2 Caches (vendor layout, matches X)

| Function | Address | Registers |
|---|---|---|
| `dcache_enable` | `0x020263A4` | `0x1800 &= ~1`, `0x1808 = 0x02000000`, `0x1800 |= 1` |
| `icache_enable` | `0x020263E8` | `0x2008 = 0`, `0x2000 |= 1` |
| `dcache_writeback(addr, len)` | `0x0202642C` | per <=4 KiB: `0x181C = lines-1`, `0x180C = addr`; skipped for `addr < 0x44000` |
| `dcache_invalidate(addr, len)` | `0x020264A8` | `0x181C`, `0x1814 = addr` |
| (after BSS clear) | `0x0202663C` | `0x1810 = 0xFFFFFFFF` (I: invalidate all) |
| `dma_copy(dst, src, len)` | `0x0202693C` | write back src, invalidate dst, DMA ch0 `0x8900=8,1; 0x8904=src; 0x8908=dst; 0x890C=len-1`; `dma_wait` `0x020268D8` polls `0x8900` bit 1. Channels 1/2 at `0x8910`, `0x8920` (`0x02026A60`, `0x02026A00`) |

## 7. ADC, battery, keys, UART/printf

### 7.1 SAR ADC (SPR `0x9170` ctrl, `0x9174` clock divider, `0x9178` result)

`adc_read(ch)` `0x02031BC8` (V):
1. `adc_select(ch, 1)` `0x0202B070`: clock gate 0x1D on; `0x9170 = 0x10 | ch` (bit 4 enable, bits 3:0 channel, ch <= 11).
2. `adc_set_clock(1000000)` `0x0202B0D8`: `0x9174 = (144e6 / (2*hz) - 1) & 0x7F` = 71.
3. `adc_start()` `0x0202B108`: `0x9170 |= 0x80`.
4. `adc_wait_result()` `0x0202B12C`: poll while `0x9170` bit 6 (busy), timeout 0x8FFFF; return `0x9178 & 0x3FF`.
`adc_init` `0x02031B14` = channel 3 + 1 MHz + start (from `dev_init_all`).

| Channel | Use | Note |
|---|---|---|
| 3 | key ladder (`adkey_scan`, `0x0201B284`) | 5 keys, see [[analysis/ui_input#1. Button map (top priority)]] |
| 9 | battery (through the divider switched by PMU reg 0x54 bit 5) | |
| 11 | internal reference (needs `0x8868` bit 15) | |

`adc_to_mv(adc9, adc11)` `0x02031C04` calls the **bootstrap routine at SRAM `0x76C`**: `mV = 2 * adc9 * cal / adc11`,
`cal` = word at SRAM `0x1E28` (computed by the bootstrap from OTP data, default 800). So the app depends on the
bootstrap still being in SRAM. `battery_ioctl` adds 20 mV, averages 16 pairs, levels at 3500/3600/3750/3950/4000 mV
with 30 mV hysteresis. V

### 7.2 UART0 (SPR `0x9080` ctrl, `0x9084` divider, `0x9088` data, `0x908C` status)

| Function | Address | Notes |
|---|---|---|
| `uart_pins_init(on)` | `0x02027F0C` | on: PA7 output, pull-up, latch 1, `0x8100` set, mux TX = 6, RX = 0; off: mux TX/RX = 0 |
| `uart_init(baud, rx_cb)` | `0x02027FAC` | `0x9080 = 0`, `0x9084 = 144e6/baud - 1`, `0x908C |= 0x30`, `0x9080 |= 0x10`, IRQ 8 on |
| `uart_putc(c)` | `0x02028020` | `0x9088 = c`; wait `0x908C` bit 1; `0x908C |= 1` |
| `uart_isr` | `0x02027EBC` | `0x908C |= 0x10`; `rx_cb(0x9088 & 0xFF)` |
| `uart_init_debug` | `0x02036AEC` | `uart_pins_init(1)` + `uart_init(115200, 0x02036A00)` |
| `uart_putc_crlf` | `0x02036A38`, `0x02036B80` | `\n` -> `\r\n` |
| `uart_put_hex(v, upper)` | `0x02036BF4` | |
| `uart_put_udec` / `uart_put_dec` | `0x02036D20` / `0x02036DB4` | |
| **`uart_printf(fmt, ...)`** | `0x02036E5C` | `%d %i %u %x %X %c %s`, unknown -> `@`; re-inits PA7 first if flag `0x02080470` is set |

Output: PA7, 115200 8N1. Only ~10 callers (FS mount errors, `0x020259AC`, `0x02033744`, ...). `battery_init` turns PA7
into an input with pull-up, so after boot the stock firmware is mostly silent (I). For our firmware: call
`uart_init_debug` (or the raw sequence) after `battery_init`, or simply never reconfigure PA7.

## 8. Memory map (RAM)

| Range | Content | Tag |
|---|---|---|
| `0x00000000-0x00001FFF` | bootstrap (flash `0x200-0x21FF`) incl. vectors, IRQ entry code, `adc_to_mv` helper, variables `0x1E24-0x1E37` | V |
| `0x00001E3C-0x0000449B` | SRAM cleared by the app (`0x020265A0`); used as DMA/USB buffers (`0x381C`, `0x3A1C`, `0x3C9C`) | V |
| `0x00008460`, `0x000084EC` | more SRAM buffers (DMA ch2) | V |
| `0x00043FFC` | `0xDEADDEAD` marker (bootstrap) | V |
| `0x02000000-0x0207A277` | app code + data (image `0x7A400`) | V |
| `0x0207A278-0x02092180` | static BSS (first word `0x0207A278` = `g_soft_timer_1s`) | V |
| `0x02092180` / `0x020921C0` | heap start (64-aligned) | V |
| `0x021FEC00` | heap end = BSS clear end | V |
| `0x021FEC00-0x021FFFFC` | stack (5 KiB), SP set by the bootstrap to `0x021FFFFC` | V |

Heap (`heap_init` `0x02037710`, `mem_alloc(size, align)` `0x0203785C`, `mem_free` `0x0203792C`): first-fit list, sizes
rounded to 64 bytes, **at most 32 blocks** (descriptor pool `0x0208049C`, 32 x 16 bytes). ~1.43 MiB. V
RAM size: the code assumes 2 MiB; the bootstrap has an address-line test (`0xBBC`) that could probe more (I).

## 9. Bootstrap (flash 0x200) and header hook

Decoded with my own disassembler. Flash `0x200-0x21FF` is loaded to **SRAM `0x0000`** (flash = SRAM + `0x200`; checked:
every absolute jump target, e.g. `0xDD0`, `0x17B0`, `0x6C8`, lands on a function prologue). Used code ends at SRAM
`~0x1A40`, followed by data/variables.

### 9.1 Header hook (flash `0x4C-0x1D7`, runs from the ROM before the bootstrap is used)

The ROM calls `+0x4C` with `r3` = ROM service base (kept in `r10`). Each service call is
`l.addi r3,r10,K ; l.jalr r10` followed by **inline data words**; the ROM returns after the data. V (format of the data I).

| Flash | Service | Inline data | Reading |
|---|---|---|---|
| `0x64` | `+0xC` (SPR script) | `0x8849,0,0x01000000` `0x9808,0x3FFF` `0x9804,0` `0x9800,0x701` `0` | script format (I, fits all entries): word = SPR | op; op 0 = write next word; op 1 = read-modify-write (clear mask, set mask); 0 ends. -> `0x8848 |= 0x01000000`; timer0: period `0x3FFF`, count 0, ctrl `0x701` (32 kHz free-running counter) |
| `0x98` | `+0x8` | `0x8800112A, 0x00010000` | PLL1 setup. `0x112A8800` (halves swapped here) is the SDK's 288 MHz VCO -> 144 MHz coefficient for SPR `0x885C` (X). I |
| `0xA8` | `+0xC` | `0x8341: clr 0x3FF set 0xC0` (UART TX route 6) ; `0x9084=0x4E1` (115200) ; `0x9080=0x10` ; **`0x9088=0x61` (prints `a`)** ; `0x8864=0x17D78400` (PLL2 400 MHz, X) ; `0x8861`: set 2, clr 0x7CC set 0x300, set 1, set 0x20 ; `0x8884=0x3FF` ; `0x884D`: clr 0xE0 set 0x20 ; `0x8849`: clr 0x400000 set 0x800000 ; `0x8889`: clr 0x20000000 | UART up, PLL2 config, clock selects |
| `0x13C` | `+0x18` | `0, 1, 0x10, 0` | load flash sectors 1..16 to SRAM 0 (research_usb_flashing.md) |
| `0x180` | (sub) | timer check: `0x9804 = 0`, service `+0x10` with `0x36B0` (delay), read `0x9804`; retry up to 20 times while the counter <= 600 | waits for the 32 kHz clock to run |
| `0x154/0x174` | | `l.jal`, then `jr 0x00000DD0` | **SDRAM init in the bootstrap**, then return 0 to the ROM |

Do not change this hook (also research_usb_flashing.md). It is the only place where PLL1/PLL2 are set for the app.

### 9.2 Bootstrap map (SRAM addresses; flash = +0x200)

| SRAM | Name (proposed) | What it does | Tag |
|---|---|---|---|
| `0x000-0x0FF` | vector table | 16 slots x 16 B, first word `l.j` (see 6.1) | V |
| `0x100-0x157` | `SFAT` table | `0x02000000,"SFAT"`, `0x0080FC04`, `0x0080FBE4`, `0x0203EF80`, `0x0203F01C`, flash `0x7C600` len `0x24C` (LCD config), flash `0x7CC9C` len `0x1F8` (sensor config), app pointers `0x0204749C..0x02047558` | V data / I meaning |
| `0x158-0x1B4` | exception stubs | `r3 = vector`, jump to `0x1B8`: `jalr 0x17B0`, `l.rfe` | V |
| `0x1CC` | `irq_entry_a` | full register save, `jal 0x02026078` | V |
| `0x2A4` | `irq_entry_b` | saves r9/EPCR/ESR, `jal 0x02025F98` | V |
| `0x2E4` | `entry_mark` | writes `0xDEADDEAD` to `0x43FFC`, falls into `0x304` | V |
| `0x304` | `boot_entry` | `jal 0x340` (save ROM stack page to `0x1A38`), `r1 = 0x021FFFFC`, `jalr 0x6C8`, `jalr 0x020004A8` (app_main), `jal 0x384` (restore, return to ROM) | V |
| `0x3D0` | `pm_write_reg(reg, val)` | PMU bus write | V |
| `0x43C` | table helper | ring/lookup over byte pairs | ? |
| `0x514` / `0x5BC` | `pm_ram_write` / `pm_ram_read` | PMU cmd `0x53` / `0x52` | V |
| `0x698` | `memset` | | V |
| `0x6C8` | `boot_early_init` | SPR `0x50 = 0` (I: vector base), SPR `0x18 |= 0x4000`, `0x88DC = 0x60`, `0x8340` TX route 6, PA7 `0x8100` set + output, `0x9084 = 0x4E1`, `0x908C |= 0x30`, `0x9080 |= 0x10` | V |
| `0x76C` | `adc_to_mv` | `2 * a * [0x1E28] / b` (used by the app!) | V |
| `0x798` | `dram_phy_power_up` | `0x8868 |= 0x10000000`, sequence of set bits on SPR `0x8838` (`0x800,4,2,0x80000,0xE020,0x1000,0x10000,0x10`; second chip variant: other order + wait `0x8838` bit 0) | V regs / I meaning |
| `0x944` | `sdram_ctrl_init` | `0x98C0 = 0x1A0`, `0x98C8 = 0x2297FBF5` (timing), `0x98C0 |= 0x80`, commands on `0x98C4`: `0x11` (precharge all), 8 x `0x13` (auto refresh), `0x98CC = 0x32` (mode: CL 3, burst 4 - I), `0x12` (load mode); each waits `0x98C4` bit 6 | V regs / I meaning (SDR SDRAM) |
| `0xA14-0xBB8` | ADC helpers | wait/read, start, clock (`0x9174`), clock gate, select, `adc_read` - same code as the app | V |
| `0xBBC` | `sdram_pattern_test(bits)` | writes/reads patterns at `0x02000000 + masks` | V |
| `0xD3C` | set `0x1E24` | | V |
| `0xD5C` | `calib_checksum` | byte hash (poly-like `0x31`), feeds WDT `0x5001D` | V |
| `0xDD0` | `boot_sdram_init` (called by the header hook) | `0x8868` bits 14:13 = 10, WDT `0x5001D`, `0x8868 |= 0x8000`; OTP word `[0x4FAC]>>24 & 0x1F` -> `0x8868` bits 20:16; `[0x4FA8] & 0x7F` -> **ADC calibration `0x1E28 = x*31/10 + 755`** (800 if absent); chip id `0x8800 & 0xFFFF0000` -> `0x1E30` (variant 0 / 0x10000 / 0x30000 selects `0x8838` vs `0x8854` delay register); D-cache off; reads the saved SDRAM delay from PMU RAM `0x10/0x14` and reuses it if `calib_checksum` matches, else trains the delay (loops over `0x8854`/`0x8838` values with `sdram_pattern_test`) and stores the result back to PMU RAM; `sdram_ctrl_init`; returns | V regs / I meaning |
| `0x17B0` | `fatal_exception(vector)` | WDT `0x50005` (~1.8 s), save vector byte to `0x1E37`, ensure PMU reg 0x54 bit 5, 4 x ADC ch 9 + ch 11, `mV = 2*sum9*cal/sum11`; **mV > 3700 -> spin (watchdog reboots)**; else gate clocks (`0x8840 |= 0xFFF1FE00`), PD1 low, PA8 low, PA6/PA7 low, `0x8868 &= 0xFFDFEFDF`, PMU reg 0x42 = 0xE0, reg 0x40 = 0x02 (power off), loop | V |
| `0x1A1C` | `panic()` | stub whose third word is not a valid instruction (`0x33323130`) -> illegal-instruction exception -> `fatal_exception`. Called by the app at `0x0203B9B0` | V |
| `0x1A38-0x1B37` | saved ROM stack page | | V |
| `0x1B38-0x1D24` | SDRAM training tables | | V |
| `0x1E24-0x1E37` | variables: `0x1E28` ADC calibration, `0x1E2C` variant flag, `0x1E30` chip id, `0x1E34` last exception | V |

SPRs written only by the bootstrap/header: `0x50`, `0x88DC`, `0x8838`, `0x8854` (also app CSI), `0x8860/0x8864`,
`0x8884`, `0x8888`, `0x98C0-0x98CC`, `0x885C/0x8858` (via ROM service).

**Consequences for our firmware:** keep the header and bootstrap unchanged and patch only the app call at flash
`0x528/0x52C`, or load our image at `0x02000000` in place of the stock app. Our code then starts with SDRAM, PLL (144 MHz),
UART (115200 on PA7), caches **off**, IRQs off, watchdog on (`0x5001D`, ~1.8 s), and SP `0x021FFFFC`. Keep SRAM
`0x0000-0x1E37` intact (vectors, IRQ entries, `adc_to_mv`, calibration word).

## 10. API for our firmware

Calling convention: args r3-r8, return r11, no delay slots. All addresses V unless noted. Most of these are leaf
functions that only touch SPRs and can be called from our code while the stock app image is in RAM.

| Address | Signature | Does |
|---|---|---|
| `0x02029D54` | `void pm_power_hold(u8 on)` | PMU reg 0x40 = on ? 0x0E : 0x02 (off = power cut on battery) |
| `0x02029F48` | `void pm_domain_init(u8 on)` | rest of the PMU start-up sequence (3.1) |
| `0x0202A13C` | `void battery_div_enable(u8 on)` | PMU reg 0x54 bit 5 |
| `0x02029F00` | `int usb_vbus_present(void)` | `(SPR 0x88E0 >> 21) & 1` |
| `0x02029894` / `0x0202991C` | `void pm_read/pm_write(u8 cmd, u8 *buf, u8 n)` | PMU bus |
| `0x0200B51C` | `void system_power_off(void)` (noreturn) | full stock shutdown |
| `0x02031F60` | `void gpio_config(u8 port, u32 mask, u8 dir_in, u8 pull)` | pull: bit0 up, bit1 down |
| `0x020274F8` | `void gpio_write(u8 port, u32 mask, u8 level)` | |
| `0x02027600` | `int gpio_read(u8 port, u32 mask)` | 0/1 |
| `0x020272F8` | `void gpio_set_input(u8 port, u32 mask, u8 in)` | |
| `0x02027834` | `void gpio_set_override(u8 port, u32 mask, u8 flags)` | bit0 force-high, bit1 force-low |
| `0x020270B4` | `void pinmux_select(u8 func, u8 route)` | table in 4 |
| `0x0202683C` | `void clk_enable(u8 id, u8 on)` | gates 5.1 |
| `0x02031BC8` | `u16 adc_read(u8 ch)` | 10-bit, blocking |
| `0x02031C04` | `int adc_to_mv(u16 adc, u16 ref)` | via SRAM `0x76C` |
| `0x020281B4` / `0x020282B0` | `int timer_start(u8 n, u32 hz, void (*cb)(void))` / `timer_stop(u8 n)` | IRQ n |
| `0x02028520` / `0x02028998` | `int pwm_start(u8 n, u8 route, u32 hz, u8 duty)` / `pwm_stop(u8 n)` | backlight = (2, 2, 4000, d) |
| `0x0201F504` / `0x0201F524` | `u32 get_ms(void)` / `void delay_ms(u32)` | need the 100 Hz tick |
| `0x02026340` | `void delay_loop(u32 n)` | busy loop, no timer |
| `0x0201F5C0` | `void *soft_timer_add(u32 ms, void (*cb)(void))` | 8 slots |
| `0x0202701C` / `0x02027064` | `wdt_enable(u8 on)` / `wdt_kick(void)` | |
| `0x0202616C` | `void irq_enable(u8 irq, u8 on)` | |
| `0x0202642C` / `0x020264A8` | `dcache_writeback(addr, len)` / `dcache_invalidate(addr, len)` | |
| `0x0202693C` | `void dma_copy(void *dst, const void *src, u32 len)` | DMA ch0, does cache maintenance, does not wait |
| `0x020268D8` | `void dma_wait(void)` | |
| `0x02036AEC` | `void uart_init_debug(void)` | PA7 115200 |
| `0x02028020` | `void uart_putc(u8)` | |
| `0x02036E5C` | `void uart_printf(const char *fmt, ...)` | `%d %i %u %x %X %c %s` |
| `0x0203785C` / `0x0203792C` | `mem_alloc(size, align)` / `mem_free(p)` | needs `heap_init` |

Raw sequences (no stock code):

```
; GPIO output, e.g. LED PB5 on (port 1, mask 0x20)
SPR[0x8384] |= 0x20       ; digital pad on (0x8380+4*1)
SPR[0x8104] &= ~0x20 ; SPR[0x8144] &= ~0x20
SPR[0x81C4] &= ~0x20 ; SPR[0x8204] &= ~0x20      ; no overrides
SPR[0x8004] |= 0x20       ; latch high
SPR[0x8044] &= ~0x20      ; output
; power key: (SPR[0x8004] & 1) != 0 -> pressed (after gpio_config(1,1,input,no pull))

; ADC channel ch
SPR[0x8840] &= ~(1<<29); SPR[0x9170] = 0x10|ch; SPR[0x9174] = 71
SPR[0x9170] |= 0x80; while (SPR[0x9170] & 0x40); v = SPR[0x9178] & 0x3FF
; battery mV = 2*adc9*[SRAM 0x1E28]/adc11  (needs PMU 0x54 bit5 and SPR 0x8868 bit 15)

; 100 Hz tick on timer 0 (IRQ 0)
SPR[0x9808] = (144000000/100 >> 7) - 1 ; SPR[0x9804] = 0 ; SPR[0x9800] = (7<<11)|9
SPR[0x4800] |= 1 ; SPR[0x18] |= 6 ; ISR: SPR[0x98A8] |= 0x20
; (note: this replaces the bootstrap's 32 kHz free-running use of timer 0)

; backlight PWM 4 kHz on PA6, duty d %
SPR[0x8100] |= 0x40 ; SPR[0x8040] &= ~0x40
SPR[0x8344] = (SPR[0x8344] & ~0xF00) | (2<<8)        ; timer2 route 2
SPR[0x8840] &= ~(1<<12)
P = 144000000/4000/2 - 1
SPR[0x9820] = 0x800 ; SPR[0x9828] = P ; SPR[0x982C] = d*P/100 ; SPR[0x9824] = 0 ; SPR[0x98B0] = 0x30
SPR[0x9820] |= 2

; watchdog: SPR[0x880C] = 0x5500 (off) | 0x50006 (on/kick, ~7 s) | 0x5001D (~1.8 s)
; UART TX: see 7.2 ; PMU hold: see 3.2
```

## 11. Full SPR map from code usage

Every SPR number resolved in `all.asm` (1,456 `l.mtspr/l.mfspr`). Consecutive registers with the same users are merged.
"Values" are constants found by a linear scan (may miss branch-dependent values). Block names: my scope verified, other
blocks named after research_registers.md / the other agents (I). Not resolved to a number (9 accesses): register merges
across branches in `0x02026658` (`0x8800/0x8868`), `0x0202AA44` (`0x914C/0x9150`), `0x0202F648`, `0x0202EE04`,
`0x0202B184`, `0x0202D470`, `0x0202E640`, `0x02056FFC` - all target registers of the same block already listed.
Computed (port) registers: `0x8000/0x8040/0x8080/0x80C0/0x8100/0x8140/0x81C0/0x8200/0x8380 + 4*port` (GPIO helpers, 4).

| SPR | R/W | Block | Functions (FUN_ prefix dropped) | Values |
|---|---|---|---|---|
| `0x0018` | RW | CPU vendor SR | 0202693c, 02026b64, 0203baec, 0203bf3c, 0203c6ec, 0203c970 +2 |  |
| `0x1800` | RW | D-cache | 020263a4 |  |
| `0x1808` | W | D-cache | 020263a4 | 0x2000000 |
| `0x180C` | W | D-cache | 0202642c |  |
| `0x1810` | W | D-cache | 020265f4 | 0xFFFFFFFF (after BSS loop) |
| `0x1814` | W | D-cache | 020264a8 |  |
| `0x181C` | W | D-cache | 0202642c, 020264a8 |  |
| `0x2000` | RW | I-cache | 020263e8 |  |
| `0x2008` | W | I-cache | 020263e8 | 0x0 |
| `0x4800` | RW | PIC | 0202616c, 020261fc |  |
| `0x4814` | RW | PIC | 020261fc |  |
| `0x8340` | RW | pin mux | 020270b4 |  |
| `0x8344` | RW | pin mux | 020270b4 |  |
| `0x8348` | RW | pin mux | 020270b4 |  |
| `0x83C0` | R | GPIO IRQ | 02027b20 |  |
| `0x83CC` | RW | GPIO IRQ | 02027b20 | -0x10000 |
| `0x8800` | R | chip ID | 02026658 (+bootstrap) |  |
| `0x880C` | RW | watchdog | 0202701c, 02027064 | 0x50006, 0x5500 |
| `0x8840` | RW | clock gates | 0202683c, 02030080 |  |
| `0x8844` | RW | clock gates | 0202683c, 02028eb4 |  |
| `0x8848` | RW | clock sel/div | 0202af28, 0202b4b8, 0202be2c, 0202e37c, 0202e5d8 |  |
| `0x884C` | RW | clock sel/div | 0202af28, 0202b4b8, 0202e37c |  |
| `0x8850` | RW | clock sel/div | 02028eb4, 0202be2c, 0202e37c |  |
| `0x8854` | RW | clock sel/div | 0202e6d4 |  |
| `0x8868` | RW | analog/LDO | 02026658, 02026b64, 02026cc4 |  |
| `0x886C` | RW | audio analog / LCD clk | 0202af28, 0202b4b8 |  |
| `0x8870` | RW | audio analog / LCD clk | 0202ace8, 0202af28 | 0x124 |
| `0x8874` | RW | audio analog / LCD clk | 0202ac0c, 0202af28 | 0x2bb |
| `0x887C` | W | audio analog / LCD clk | 0202f4cc |  |
| `0x8880` | RW | misc reset bits | 02026898, 0202cdfc, 02030080 |  |
| `0x88E0` | RW | PMU/RTC bus | 020296a8, 020296f8, 0202975c, 020297f8, 02029894, 0202991c +7 | 0x240 |
| `0x88E4` | RW | PMU/RTC bus | 020299a4, 02029a54, 02029b0c, 02029b88 | 0x7 |
| `0x88EC` | RW | PMU/RTC bus | 020296a8, 020296f8 | 0x0 |
| `0x8900` | RW | DMA x3 | 020268d8, 0202693c | 0x1, 0x8 |
| `0x8904-0x890C` | W | DMA x3 | 0202693c |  |
| `0x8910` | RW | DMA x3 | 02026a60 | 0x1, 0x8 |
| `0x8914-0x891C` | W | DMA x3 | 02026a60 |  |
| `0x8920` | RW | DMA x3 | 02026a00 | 0x1, 0x8 |
| `0x8924-0x892C` | W | DMA x3 | 02026a00 |  |
| `0x8980` | RW | blk IRQ23 | 0202c788, 0202c804, 0202c848 |  |
| `0x8984-0x8988` | W | blk IRQ23 | 0202c788 | 0x0 |
| `0x898C` | RW | blk IRQ23 | 0202cb60, 0202cbcc |  |
| `0x8990-0x89A4` | W | blk IRQ23 | 0202cbcc |  |
| `0x89A8` | RW | blk IRQ23 | 0202cbcc, 0202cd38 | 0x1 |
| `0x9000` | RW | SPI0 | 02028eb4, 02029128, 0202917c, 02029234, spi_cs, spi_tx_byte |  |
| `0x9004-0x9008` | W | SPI0 | 02028eb4 | 0x0 |
| `0x900C` | RW | SPI0 | 02028eb4, 0202917c, 02029234 |  |
| `0x9028` | R | blk IRQ26 | 0202ca44 |  |
| `0x9030` | RW | blk IRQ26 | 0202ca44 |  |
| `0x9080` | RW | UART0 | 02027fac | 0x0 |
| `0x9084` | W | UART0 | 02027fac |  |
| `0x9088` | RW | UART0 | 02027ebc, 02028020 |  |
| `0x908C` | RW | UART0 | 02027ebc, 02027fac, 02028020 |  |
| `0x9090` | W | I2C | 0202a594 |  |
| `0x9094` | RW | I2C | 0202a594 |  |
| `0x9098` | R | I2C | 0202a790 |  |
| `0x909C` | W | I2C | 0202a740 |  |
| `0x90A0` | RW | I2C | 0202a698, 0202a6b4, 0202a740, 0202a790 | 0x40, 0x80 |
| `0x90A4` | R | I2C | 0202a6b4, 0202a6f4, 0202a740, 0202a790 |  |
| `0x9100` | RW | mic ADC | 0202b254, 0202b34c, 0202b458, 0202b55c |  |
| `0x9104` | W | mic ADC | 0202b55c | 0x7c0002 |
| `0x9108-0x910C` | W | mic ADC | 0202b458 |  |
| `0x9110` | W | mic ADC | 0202b3dc |  |
| `0x9114` | RW | mic ADC | 0202b184, 0202b254, 0202b3dc | 0x30000, 0x400 |
| `0x9118` | RW | mic ADC | 0202b254, 0202b34c, 0202b3dc |  |
| `0x911C-0x9120` | W | mic ADC | 0202b34c | 0x1007800, 0x40003000 |
| `0x9140` | W | audio DAC | 0202ace8, 0202af28 | 0x10020, 0x202c |
| `0x9144` | W | audio DAC | 0202aca4, 0202ace8, 0202af28 | 0x0 |
| `0x9148` | W | audio DAC | 0202ac84, 0202ace8, 0202af28 | 0x0 |
| `0x914C` | RW | audio DAC | 0202aa44, 0202ace8, 0202ad64, 0202af28 | 0x7 |
| `0x9150` | R | audio DAC | 0202aa44 |  |
| `0x9158` | W | audio DAC | 0202ac84, 0202ace8, 0202af28 | 0x0 |
| `0x915C` | RW | audio DAC | 0202aa04, 0202ab18, 0202ab88 | 0x0 |
| `0x9160` | R | audio DAC | 0202ab18, 0202ab88 |  |
| `0x9170` | RW | SAR ADC | 0202b070, 0202b108, 0202b12c |  |
| `0x9174` | W | SAR ADC | 0202b0d8 |  |
| `0x9178` | R | SAR ADC | 0202b12c |  |
| `0x9244` | W | SPI0 DMA/CRC | 02028eb4, 02029128, 0202917c, 02029234, spi_tx_byte | 0x1, 0x2, 0x20000, 0x3ff0000 |
| `0x9248` | RW | SPI0 DMA/CRC | 02028eb4, 02029128, 0202917c, 02029234, spi_tx_byte | 0x0 |
| `0x924C` | W | SPI0 DMA/CRC | 02028eb4 |  |
| `0x9250` | RW | SPI0 DMA/CRC | 02028eb4, 02029128, spi_tx_byte | 0x0, 0xff |
| `0x9254-0x925C` | W | SPI0 DMA/CRC | 02028eb4, 0202917c, 02029234 | 0x0, 0x6000000 |
| `0x9260-0x927C` | W | SPI0 DMA/CRC | 02028eb4 | -0x1, 0x0, 0xffff, 0xfffffff |
| `0x9280` | RW | SD pad? | 02026fd4 |  |
| `0x92A4` | W | bus arbiter | 02026d84 |  |
| `0x92B4-0x92B8` | W | bus arbiter | 02026d84 |  |
| `0x92C0-0x92E0` | W | bus arbiter | 02026d84 |  |
| `0x9800` | RW | timers 0-3 | 020281b4, 020282b0, 02028520, 02028998 | 0x0, 0x3809, 0x800 |
| `0x9804-0x9808` | W | timers 0-3 | 020281b4, 02028520 | 0x0 |
| `0x980C` | W | timers 0-3 | 02028520 |  |
| `0x9810` | RW | timers 0-3 | 020281b4, 020282b0, 02028520, 02028998 | 0x0, 0x3809, 0x800 |
| `0x9814-0x9818` | W | timers 0-3 | 020281b4, 02028520 | 0x0 |
| `0x981C` | W | timers 0-3 | 02028520 |  |
| `0x9820` | RW | timers 0-3 | 020281b4, 020282b0, 02028520, 02028998 | 0x0, 0x3809, 0x800 |
| `0x9824-0x9828` | W | timers 0-3 | 020281b4, 02028520 | 0x0 |
| `0x982C` | W | timers 0-3 | 02028520 |  |
| `0x9830` | RW | timers 0-3 | 020281b4, 020282b0, 02028520, 02028998 | 0x0, 0x3809, 0x800 |
| `0x9834-0x9838` | W | timers 0-3 | 020281b4, 02028520 | 0x0 |
| `0x983C` | W | timers 0-3 | 02028520 |  |
| `0x9840` | RW | USB PHY/cfg | 0202be2c, 0202c238, 0203d530, 0203f578 | 0x0, 0x21307400 |
| `0x9844` | W | USB PHY/cfg | 0202b8ec, 0202bb34, 0202bc24, 0203d7b8, 0203dae0 |  |
| `0x984C` | W | USB PHY/cfg | 0203d7b8, 0203dae0, 0203e5dc | 0x8000 |
| `0x9850` | W | USB PHY/cfg | 0202b8ec, 0203e750 | 0x8040 |
| `0x9854` | W | USB PHY/cfg | 0202ba28, 0203e750, 0203f41c | 0x8250 |
| `0x9858` | W | USB PHY/cfg | 0202bb34 |  |
| `0x9860` | W | USB PHY/cfg | 0202bb34 |  |
| `0x9868` | W | USB PHY/cfg | 0202bb34, 0202bc24 |  |
| `0x9880` | RW | SD | 020569a0, 02056b60, 02056cac, 02056cf0, 02056d7c, 02056e0c +3 | 0x0 |
| `0x9884` | RW | SD | 020569a0, 02056b60, 02056cf0, 02056d44, 02056e0c | 0x5 |
| `0x9888` | W | SD | 020569a0, 02056ffc | 0x167 |
| `0x988C` | W | SD | 02056b60 | 0x1e3c |
| `0x9890-0x9894` | W | SD | 02056cf0, 02056d44 |  |
| `0x9898` | W | SD | 02056b60 |  |
| `0x989C` | RW | SD | 02056b60, 02056e80 |  |
| `0x98A8` | RW | timer status | 02028060, 02028520 | 0x30 |
| `0x98AC` | RW | timer status | 020280a4, 02028520 | 0x30 |
| `0x98B0` | RW | timer status | 020280e8, 02028520 | 0x30 |
| `0x98B4` | RW | timer status | 0202812c, 02028520 | 0x30 |
| `0x9900` | W | CRC (SD) | 020284b0, 020284e4 | 0x0, 0x40, 0x42 |
| `0x9904` | W | CRC (SD) | 020284b0 | -0x1 |
| `0x9908` | RW | CRC (SD) | 020284b0, 02028504 | 0x0 |
| `0xA000` | W | USB | 0202bd94, 0203d908 | 0x0 |
| `0xA004` | W | USB | 0202bd94 | 0x60 |
| `0xA008` | R | USB | 0202c0e8 |  |
| `0xA018` | W | USB | 0202bd94 | 0x9 |
| `0xA020` | W | USB | 0202bd94 | 0x0 |
| `0xA028` | R | USB | 0202c0e8 |  |
| `0xA02C` | W | USB | 0202bd94, 0202c0e8, 0203decc | 0xc, 0xd |
| `0xA038` | RW | USB | 0202b8ec, 0202ba28, 0202bb34, 0202bc24, 0202bd94, 0203d8bc +10 | 0x0, 0x1, 0x3, 0x4 |
| `0xA03C` | W | USB | 0202bd94 | 0x0 |
| `0xA040-0xA044` | W | USB | 0203e750, 0203fdec, 02040754 | 0x0, 0x1f, 0x4, 0xec |
| `0xA048` | RW | USB | 0202b8ec, 0202bb34, 0202bc24, 0203d7b8, 0203d8bc, 0203d954 +12 | 0x0, 0x20, 0x40, 0x48 … |
| `0xA04C` | W | USB | 0203d8bc, 0203e750, 0203fdec, 02040754 | 0x0, 0x20, 0x60 |
| `0xA050-0xA054` | W | USB | 0203e750, 0203fdec, 02040754 | 0x0, 0x1f, 0x4, 0xec |
| `0xA058` | RW | USB | 0202ba28, 0203d8bc, 0203d990, 0203da1c, 0203e750, 0203f41c +4 | 0x0, 0x10, 0x20, 0x80 … |
| `0xA05C` | W | USB | 0203e750, 0203fdec, 02040754 | 0x0, 0x60 |
| `0xA060` | R | USB | 0203fcb8 |  |
| `0xA064` | R | USB | 0203fcb8 |  |
| `0xA800` | RW | LCD | 0202f2e0, 0202f600, 0202f648, 0202f6ac, 0202f6f4, 0202f72c | 0x0 |
| `0xA804` | RW | LCD | 0202f120, 0202f184, 0202f1d8, 0202f25c, 0202f2e0, 0202f32c +1 | 0x809f00 |
| `0xA808` | W | LCD | 0202f374 |  |
| `0xA80C` | W | LCD | 0202f390 |  |
| `0xA810` | RW | LCD | 0202f390, 0202f428, 0202f47c |  |
| `0xA814-0xA818` | W | LCD | 0202f4ec |  |
| `0xA81C` | W | LCD | 0202f510 |  |
| `0xA820-0xA824` | W | LCD | 0202f4ec |  |
| `0xA828-0xA830` | W | LCD | 0202f510 |  |
| `0xA834-0xA838` | W | LCD | 0202f534 |  |
| `0xA840-0xA844` | W | LCD | 0202f550 |  |
| `0xA848-0xA84C` | W | LCD | 0202f56c |  |
| `0xA854` | W | LCD | 0202f5cc |  |
| `0xA858` | W | LCD | 0202f120, 0202f184, 0202f1d8, 0202f25c |  |
| `0xA85C` | W | LCD | 0202f588 |  |
| `0xA860-0xA864` | W | LCD | 0202f5e4 |  |
| `0xA868-0xA86C` | W | LCD | 0202f588 |  |
| `0xB000` | RW | CSI/ISP | 0202defc, 0202e488, 0202e4ec, 0202e530, 0202e59c, 0202e5d8 +4 |  |
| `0xB004` | RW | CSI/ISP | 0202d128 |  |
| `0xB008` | RW | CSI/ISP | 0202e928, 0202eda0 |  |
| `0xB00C` | RW | CSI/ISP | 0202defc, 0202e848, 020303fc | 0x40, 0x5a, 0x60000, 0x8005a … |
| `0xB014` | RW | CSI/ISP | 0202defc, 0202e1c8, 0202e238, 0202e2c4, 0202e848, 0202ee04 +1 | -0x7ffd07e8 |
| `0xB018` | RW | CSI/ISP | 0202defc, 0202e1c8, 0202e238, 0202e848, 0202e8e4, 0202edc8 |  |
| `0xB01C` | W | CSI/ISP | 0202e71c |  |
| `0xB020-0xB024` | W | CSI/ISP | 0202e76c |  |
| `0xB028-0xB02C` | W | CSI/ISP | 0202eb04 |  |
| `0xB030-0xB034` | W | CSI/ISP | 0202e928 |  |
| `0xB038-0xB03C` | W | CSI/ISP | 0202ec4c |  |
| `0xB040-0xB04C` | W | CSI/ISP | 0202e238 |  |
| `0xB050-0xB05C` | W | CSI/ISP | 0202e1c8 |  |
| `0xB060-0xB064` | W | CSI/ISP | 0202e81c |  |
| `0xB068` | W | CSI/ISP | 0202e928 |  |
| `0xB180-0xB188` | W | CSI/ISP | 0202e928, 0202eb04 |  |
| `0xB18C-0xB1E8` | W | CSI/ISP | 0202e928 |  |
| `0xB800` | RW | img blk IRQ16 | 020303fc, 02030684, 020306fc, 020307e0, 02030860, 02030a98 +1 | 0x40e801 |
| `0xB80C` | W | img blk IRQ16 | 020305dc |  |
| `0xB810-0xB814` | W | img blk IRQ16 | 020303b0 |  |
| `0xB818` | R | img blk IRQ16 | 02038804 |  |
| `0xB81C` | R | img blk IRQ16 | 02030828 |  |
| `0xB820-0xB824` | W | img blk IRQ16 | 02030844 |  |
| `0xB830` | W | img blk IRQ16 | 02030860 | 0x3000258 |
| `0xB83C` | RW | img blk IRQ16 | 020303fc, 02030860 | -0x7fffffab |
| `0xB840` | R | img blk IRQ16 | 020300ec, 02030140 |  |
| `0xB850` | RW | img blk IRQ16 | 02028a4c, 02028b24 |  |
| `0xB854-0xB85C` | W | img blk IRQ16 | 02028bcc |  |
| `0xB860-0xB868` | W | img blk IRQ16 | 02028cb0 |  |
| `0xB86C-0xB874` | W | img blk IRQ16 | 02028d94 |  |
| `0xB878-0xB880` | W | img blk IRQ16 | 020305dc |  |
| `0xB884-0xB8A0` | W | img blk IRQ16 | 02030860 | 0x12fa0200, 0x1df703ff, 0x28f504ff, 0x32f504ff … |
| `0xB8A4` | W | img blk IRQ16 | 02030860, 02030a98 | 0x0, 0x320, 0x8 |
| `0xB8B0` | RW | img blk IRQ16 | 020300ec, 02030140, 020303fc, 02030860 | -0x1 |
| `0xB8C4-0xB940` | W | img blk IRQ16 | 02030860 | -0x1f0c804, -0x2c2fa00, -0x2e6d005, -0x3c8f002 … |
| `0xC000` | RW | img blk IRQ22 | 02030ec0, 02031164, 020311e0, 02031238 | 0x0 |
| `0xC004` | W | img blk IRQ22 | 02030bd4 | 0x0 |
| `0xC00C` | RW | img blk IRQ22 | 02030bd4 |  |
| `0xC010-0xC014` | W | img blk IRQ22 | 02030df8 |  |
| `0xC020-0xC024` | W | img blk IRQ22 | 02030e14 |  |
| `0xC028` | W | img blk IRQ22 | 02030ec0 | 0x0 |
| `0xC02C` | W | img blk IRQ22 | 02030e14 |  |
| `0xC034` | W | img blk IRQ22 | 02030e4c |  |
| `0xC03C` | RW | img blk IRQ22 | 02030ec0, 020310c4 | -0x7ffffea0 |
| `0xC040` | R | img blk IRQ22 | 02031274, 020313d0, 02031a78 |  |
| `0xC04C` | W | img blk IRQ22 | 02030e64 |  |
| `0xC050` | RW | img blk IRQ22 | 02028a4c, 02028ab8, 02028b70 |  |
| `0xC054` | RW | img blk IRQ22 | 02028c28 |  |
| `0xC058` | RW | img blk IRQ22 | 02028c28 |  |
| `0xC05C` | RW | img blk IRQ22 | 02028c28 |  |
| `0xC060` | RW | img blk IRQ22 | 02028d0c |  |
| `0xC064` | RW | img blk IRQ22 | 02028d0c |  |
| `0xC068` | RW | img blk IRQ22 | 02028d0c |  |
| `0xC06C` | RW | img blk IRQ22 | 02028dd8 |  |
| `0xC070` | RW | img blk IRQ22 | 02028dd8 |  |
| `0xC074` | RW | img blk IRQ22 | 02028dd8 |  |
| `0xC078` | RW | img blk IRQ22 | 02030bd4 |  |
| `0xC07C` | RW | img blk IRQ22 | 02030bd4 |  |
| `0xC080` | RW | img blk IRQ22 | 02030bd4 |  |
| `0xC084-0xC0A0` | W | img blk IRQ22 | 02030ec0 | 0x12fa0200, 0x1df703ff, 0x28f504ff, 0x32f504ff … |
| `0xC0B0` | RW | img blk IRQ22 | 02030ec0, 02031238, 02031274, 02031a78 | 0xffc |
| `0xC0C0` | W | img blk IRQ22 | 02030bd4 |  |
| `0xC0C4-0xC140` | W | img blk IRQ22 | 02030ec0 | -0x1f0c804, -0x2c2fa00, -0x2e6d005, -0x3c8f002 … |
| `0xC144` | RW | img blk IRQ22 | 020310c4 | -0x7bb55e00 |
| `0xC148` | W | img blk IRQ22 | 02030ec0 | 0x22105105 |
| `0xC800` | RW | compositor | 0202d164, 0202d1c0, 0202d1e4, 0202d288 | 0x3 |
| `0xC804-0xC808` | W | compositor | 0202d288 | 0x0, 0xf |
| `0xC80C` | RW | compositor | 0202d164, 0202d208, 0202d288 | 0x0 |
| `0xC810` | W | compositor | 0202d288 |  |
| `0xC814` | W | compositor | 0202d304 |  |
| `0xC818` | RW | compositor | 0202d288, 0202d384, 0202d424, 0202d470, 0202d4e0, 0202d694 +2 | 0x0 |
| `0xC820` | W | compositor | 0202dcb4 |  |
| `0xC824` | W | compositor | 0202d604 |  |
| `0xC828` | W | compositor | 0202d58c |  |
| `0xC82C` | W | compositor | 0202d5a8 |  |
| `0xC830` | W | compositor | 0202d58c |  |
| `0xC834` | W | compositor | 0202d5a8 |  |
| `0xC838` | W | compositor | 0202d424 |  |
| `0xC83C` | RW | compositor | 0202da4c, 0202db3c |  |
| `0xC840` | W | compositor | 0202daa0 |  |
| `0xC844-0xC848` | W | compositor | 0202db3c |  |
| `0xC84C` | RW | compositor | 0202da4c, 0202db3c |  |
| `0xC850` | W | compositor | 0202daa0 |  |
| `0xC854-0xC858` | W | compositor | 0202db3c |  |
| `0xC85C` | RW | compositor | 0202dc48 |  |
| `0xC87C` | R | compositor | 0202d52c |  |
| `0xC880-0xC92C` | W | compositor | 0202dcb4 |  |
| `0xD000-0xD008` | W | blk IRQ27 | 0202ce68 |  |
| `0xD010` | W | blk IRQ27 | 0202ce68 |  |
| `0xD014` | RW | blk IRQ27 | 0202ce68, 0202d0dc | 0x3 |
| `0xD018` | RW | blk IRQ27 | 0202cdd8, 0202ce68 |  |
| `0xD804` | RW | USB misc | 0203f578 |  |
| `0x0020`, `0x0040` | RW | EPCR / ESR | bootstrap IRQ entries (SRAM `0x1CC`, `0x2A4`) | |
| `0x0050` | W | ? (vector base, I) | bootstrap `0x6C8` | 0 |
| `0x8838` | RW | DRAM PHY/PLL ctl (I) | bootstrap `0x798`, `0xDD0` | |
| `0x8854` | RW | SDRAM delay / clock (I) | bootstrap `0xDD0` (also app `0x0202E6D4`) | |
| `0x8860/0x8864/0x8884/0x8888` | W/RMW | PLL2 / misc | header hook | `0x8864 = 0x17D78400` |
| `0x88DC` | W | ? | bootstrap `0x6C8` | `0x60` |
| `0x98C0-0x98CC` | RW | SDRAM controller | bootstrap `0x944` | `0x1A0`, `0x2297FBF5`, cmds `0x11/0x13/0x12`, mode `0x32` |
| `0x4804` | RW | IRQ path select (I) | `0x020261B4` (not in export) | |
| `0x480C` | R | pending IRQ number (bits 4:0 path A, 20:16 path B) | `0x02026078`, `0x02025F98` (not in export) | |

## 12. Open questions

- Exact meaning of `0x8100`, `0x8140`, `0x8380` (GPIO) and of the overrides `0x81C0/0x8200` on an output pin: stock LED
  init sets `0x8200` (force-low) and later still turns the LED on through the latch - either the override only acts on
  inputs, or the meaning differs. Test on hardware.
- Which SR bit enables which IRQ path, and what `0x4804`/`0x4814` do.
- PB1 role; PD0/PD1 polarity vs sensor PWDN/RESET.
- `delay_loop` unit in real time; long-press time of the power key.
- The ROM service at hook `+0x8` (PLL) and `+0x18` (sector load): argument format.
- RAM size (2 MiB assumed by the code).
