# UI and input (buttons, events, widgets, task flow, settings write)

> [!summary]
> **Button map** (ADC ladder on channel 3 + power key on PB0), key events, the event queue, windows and pages, drawing, sound, the task flow, the settings write path, and the stock UI API.

Firmware `Y200-V1.1-20251020`, app at RAM `0x02000000`. Source: `analysis/export/all.c` / `all.asm`, plus my own
OR1K disassembly of code that Ghidra did not turn into functions (all page event handlers, e.g. `0x02006794`-`0x02006dbc`,
`0x02007d24`-`0x020092e0`, `0x0200a3b4`-`0x0200b3a0`, `0x0200d504`-`0x0200e740`, `0x0200f330`-`0x020111a0`,
`0x02011470`-`0x02011da4`, `0x02012b38`-`0x020147ec`, `0x0201d1a8`-`0x0201d820`). Those addresses are **not in the export**.

Tags: **[V]** = verified in code (address cited), **[I]** = inferred / guess.

## 1. Button map (top priority)

### 1.1 How a key becomes an event (V)

```
100 Hz timer ISR 0x0201f494: g_ms(0x0207efac) += 10, runs software timers
task_run_loop -> every service iteration: task_poll 0x02000440
   -> sys_poll 0x0200c50c(1) -> key_poll_post 0x0200bc7c  (at most every 20 ms)
        -> dev_ioctl(ad-key, 9) -> adkey_ioctl -> adkey_get_event 0x02002fa0
             -> adkey_longpress_filter 0x02002ed0 -> adkey_scan_raw 0x02002de4
        -> queue_post(g_event_queue, event)          (event = value<<16 | code)
   -> event_dispatch 0x02006544: queue_get, beep, page handler, global handler
```

- `adkey_scan_raw` 0x02002de4 [V]: reads **PB0** (`gpio_read(1, 1)`, SPR `0x8004` bit 0, via 0x020321b4 -> 0x02027600).
  PB0 high -> code **0x25** (power). Otherwise `adc_read(3)` and looks the value up in `adkey_table` 0x02076e50
  (5 x `{u8 code, u8 0, u16 centre, u16 lo, u16 hi}`, lo/hi = centre -/+ 29, filled by `adkey_init`). No match -> 0.
  Debounce: the same raw value must be read 3 times in a row. It then returns it and resets the counter. Otherwise it returns -1.
  So one "sample" is about every 3 polls (~60 ms) [I: timing depends on the main loop speed].
- `adkey_longpress_filter` 0x02002ed0 [V], for the two keys that have a long-press variant:
  - **0x1C** (ADC 0): while held it returns 0. On release after < 30 samples it gives **0x1C** once. After 30 samples
    (~1.8 s [I]) it gives **0x1D** (long shutter) continuously.
  - **0x25** (power): the same. Short = **0x25** on release, long (30 samples) = **0x27**.
  - So **a short shutter or power press is only reported when the button is released.**
- `adkey_get_event` 0x02002fa0 [V]: on change it returns `code` (press) or `last | 0x20000` (release). While the same
  code stays, a repeat `code | 0x10000` is sent after 12 samples, then every 2 samples (counter starts at -10).
- `key_poll_post` 0x0200bc7c [V]: if the backlight is off (screen saver), a non-power key only wakes the screen
  (`screen_saver_kick(1)`) and is swallowed until it is released. Power (0x25/0x27) always passes. Each key resets the
  auto-power-off timer.
- Handler argument `argv[0]` = event value: **0 = press, 1 = repeat/hold, 2 = release**.
- **Key tone** `key_tone_play` 0x0200beb0 [V]: called from `event_dispatch` for types 0x1C..0x29 except 0x27 with value 0.
  It is not called in Photo (3), USB (9), while recording video, in Playback (unless `0x0207e8a4` is set), or in the MP3
  player while playing. It plays resource **46** (key beep, 16 kHz PCM, header 0x2C skipped). It only plays if settings
  **slot 20 = On** (hidden "key beep" setting, `0x020818ec`). Volume = slot 30 x 10 %.

### 1.2 Code -> action per task -> physical button

Physical names: our deduction from behaviour. It **agrees exactly** with matu's appotech-sdk (`ext/appotech-sdk/research/gpio.md`,
user-confirmed on the Action camera, same ladder: SHUTTER 0, DOWN 306, UP 484, LEFT 658, RIGHT 817, POWER = PB0 high).

| Code | Input | Main menu (6) | Photo (3) | Video (2) | Playback (4) | MP3 (5) | Settings (8) | Game menu (7) | Button | Conf. |
|---|---|---|---|---|---|---|---|---|---|---|
| `0x1C` | ADC ~0 (short, on release) | open highlighted mode | **take photo** (self-timer if set) | **start/stop recording** | play/pause video | play/pause | open item / option list; confirm | start game | **SHUTTER / OK** | high |
| `0x1D` | ADC ~0 held >~1.8 s | - | - | - | - | - | - | - | SHUTTER long: **no handler** (only beeps) | high |
| `0x1E` | ADC ~484 | row up/down (idx ±3) | tap: previous effect/frame; hold: **zoom in** (max 30) | tap: previous effect; hold: zoom in | open "Delete" (one file) dialog | **volume +1** (max 8, saved) | list **previous** | - | **UP** | high |
| `0x1F` | ADC ~306 | row up/down (idx ±3) | tap: next effect/frame; hold: **zoom out** | tap: next effect; hold: zoom out | open "Delete All" dialog | **volume -1** (saved) | list **next** | - | **DOWN** | high |
| `0x22` | ADC ~658 | **index -1** | on release: toggle self-timer Off<->5S (saved) | on release: speed mode Normal/Slow/Fast | **previous file** | **previous track** | back to main menu | index +1 (carousel) | **LEFT** | high |
| `0x23` | ADC ~817 | **index +1** | - | - | **next file** | **next track** | - (see note) | index -1 | **RIGHT** | high |
| `0x25` | PB0 short (on release) | (global only: wake screen) | **back to main menu** | back to main menu | back to main menu | stop, back to main menu | back to main menu | back to main menu | **POWER short = BACK/HOME** | high |
| `0x27` | PB0 held ~1.8 s | power off | power off | power off | power off | power off | power off | power off | **POWER long = OFF** | high |

Evidence (handler addresses) [V]:
- Main menu (page `0x02078c3c`): 0x1C `0x020144b0` (index -> task: 0->3 Photo, 1->2 Video, 2->4 Playback, 3->8 Settings,
  4->7 Games, 5->5 MP3); 0x22 `0x02014554` (idx-1, wraps 0->5); 0x23 `0x02014634` (idx+1); 0x1E `0x020147ec` and 0x1F
  `0x02014710` (idx ±3). The menu index is byte `0x0208194c`. The grid is 3x2 (resource 44 checked: row 1 = photo, video, gallery;
  row 2 = settings, games, music). So ±1 = horizontal and ±3 = vertical, which fits LEFT/RIGHT and UP/DOWN.
- Photo (page `0x020772f8`): 0x1C `0x02008a78` (self-timer slot 15 == Off -> post event **0x26** = capture, else start the
  countdown); 0x26 `0x02009228` (save to SD `0x02007604`, or to internal flash `0x02007828` when there is no card, "SPI is full" message);
  0x22 `0x02008c4c`; 0x25 `0x02008bd4`; 0x1F `0x02008d3c`; 0x1E `0x02008fa8`. Zoom = `digital_zoom_set` 0x02003f58 (crop
  window, 0..30). Effect cycle state machine in `0x02081945` (+97): mode 1 = sensor colour effect 1..5 (`sensor_set_effect`
  0x0204756c), mode 2 = counter 0..5 [I], mode 3 = photo frames (resource table `0x02077380` = res 12..4, `0x0203cbe8`).
- Video (page `0x0207797c`): 0x1C `0x0200e600` (recording? `video_stop` 0x0200cb0c : start `0x0200ca7c`); 0x22 `0x0200e120`
  (mode byte +112, label strings 192 "Slow" / 193 "Fast"; sets `FUN_02043d50(9, 10|30)` = probably fps [I]); 0x1F `0x0200e2b0`;
  0x1E `0x0200e424`; 0x25 `0x0200e59c`. 0x23 not handled.
- Playback (page `0x02077638`): 0x1C `0x0200af6c`, 0x1E `0x0200ac7c` (opens page `0x02077f94` "Delete"), 0x1F `0x0200abb0`
  (opens `0x02077e8c` "Delete All"), 0x22 `0x0200b298` (file idx -1), 0x23 `0x0200adc8` (idx +1), 0x25 `0x0200ad48`.
- MP3 (page `0x02078900`): 0x23 `0x02013258`, 0x22 `0x02013314`, 0x25 `0x020133d0`, 0x1C `0x02013450`, 0x1F `0x02013574`,
  0x1E `0x02013608` (slot 30 volume, `settings_save`, DAC volume `0x02031e8c`).
- Settings (page `0x020781bc`): 0x1F `0x0201089c` -> `list_select_next` 0x02021bf4 (sel+1, wraps); 0x1E `0x020108e0` ->
  `0x02021c64` (prev); 0x1C `0x02010924`; 0x22 `0x020107d4`, 0x25 `0x02010770`. **Firmware bug**: the table has two `0x25`
  entries (`0x02010838` and `0x02010770`) and no 0x23. The 3rd entry was probably meant to be 0x23, so RIGHT does nothing.
- Settings option list (page `0x020782cc`): 0x1F next (live brightness preview for slot 8), 0x1E prev, 0x1C select+save,
  0x22/0x23/0x25 close.
- Game menu (page `0x02078dd4`): 0x1C `0x0201d66c`, 0x22 `0x0201d738` (+1), 0x23 `0x0201d7ac` (-1), 0x25 `0x0201d608`.
- Global handlers (table `0x02077268`, always run after the page handler): 0x27 `0x02006a14` -> `task_switch(1 Power Off)`.
  Exception: in the USB task in charge-only state it shows WELCOME and goes to the main menu instead (a long press "boots" the camera).
  0x25 `0x02006d0c` (wake screen / USB state 2 action). 0x1C/1E/1F/22/23/28/29: reset auto-off and screen-saver timers.

**There is no separate MODE or MENU key.** Mode changes go through the main menu: POWER short goes back to it, SHUTTER enters.

**In games** the keys are read differently [V]: `Game_enter` starts a 3 ms software timer (`0x0201c898` ->
`game_key_timer` 0x0201c798). It calls `game_key_scan` 0x0201b330, which has its own ADC windows (0..49, 290..339, 450..549,
640..699, 790..849, power). It posts codes from table `0x020632f8` = `{-,0x1C,0x1E,0x1F,0x20,0x21,0x25}`, so **LEFT = 0x20 and
RIGHT = 0x21 in games**. There are no press/release values, it repeats about every 100 ms [I], and each key plays resource 46. At battery
level 0, `0x0201b284` posts 0x25 (forces an exit).

### 1.3 Test to confirm on this unit (no tools needed)
1. Main menu: the 2 buttons that move the highlight one tile sideways are 0x22 (towards Photo = LEFT) and 0x23 (RIGHT). The 2 that jump
   between rows are 0x1E/0x1F.
2. MP3 player: the button that raises the volume bar = 0x1E (UP), lowers it = 0x1F (DOWN).
3. Settings list: 0x1F moves the cursor down, 0x1E up. LEFT leaves the menu, RIGHT does nothing.
4. Shutter: a photo is taken **when the button is released**, not when it is pressed. Holding it ~2 s does nothing.
5. Power: a short press returns to the main menu, a long press (~2 s) switches off.
Optional: measure the ladder resistors. The ADC value ~ 1023 x R_key / (R_key + R_pullup) [I] (0 = button to ground = shutter).

## 2. Event and message system (V)

- Queue control blocks: 12 slots x 8 bytes at **`0x00001e7c`** (on-chip SRAM, real memory: `l.lbz/l.sb`, not SPR)
  `{u8 size, u8 count, u8 rd, u8 wr, u32 *buf}`. API: `queue_create(buf, n)` 0x0201f1b0, `queue_post(q, w)` 0x0201f2b8
  (returns 0 ok / 0xFF full), `queue_post_front` 0x0201f330, `queue_get(q, &err)` 0x0201f3ac (err 0 ok, 0xFE empty),
  `queue_count` 0x0201f43c, `queue_flush` 0x0201f278, `queue_delete` 0x0201f240.
- Main event queue: `g_event_queue` = `*(0x02081958)`, 20 words in `0x0207a280` (app_init). Word = `value << 16 | type`, type < 0x2A.
- Dispatch `event_dispatch` 0x02006544: one event per main-loop iteration. It calls `g_page_events[type]` (0x0207e68c, 42 entries)
  and then `g_global_events[type]` (0x0207e5e4). Signature: `int handler(win *top_window, int argc /*1*/, u32 *argv /*argv[0]=value*/)`.
  `event_send(type, a, b, c)` 0x020066a0 calls both tables directly (no queue).
- The page table is rebuilt on every page open/focus (`event_table_set_page` 0x02006410): first the default table `0x02077238`
  (no-ops for 0x25, 0x22, 0x23, 2, 3), then the page's own table. The global table is set once by `app_main` from `0x02077268`.

| Type | Meaning | Value | Producer |
|---|---|---|---|
| 0x01 | SD card state change | `0x020818e9`: 0 none, 1 detected/mounting, 2 mount error, 3 full, 4 ready | `sdcard_poll` 0x0200c308, `sdcard_on_mount` 0x0200c100, `sdcard_space_check` 0x0200c044, Photo/Video when full |
| 0x02 | USB state | 0 unplugged, 1 power only (charging), 2 PC host seen (switches to task 9) | `usb_battery_poll` 0x0200b888, app_main |
| 0x03 | battery level | 0..5. Level 0 -> "Low battery" box, power off after 5 s | 0x0200b888, app_main |
| 0x05 | video internal | ? | 0x0200d058 |
| 0x06 | Photo/Playback handler exists (`0x02007d24`/`0x02009c7c`) | ? | producer not found |
| 0x09 | 500 ms tick (main menu blink, MP3 animation) | - | `sys_tick_events` 0x0200b77c |
| 0x0A | RTC seconds changed (1 Hz): message box timeouts, power-off countdowns | - | 0x0200b77c |
| 0x0D | playback internal | - | 0x02009964, 0x02009c48 |
| 0x0F | page OPEN (argc, argv from `ui_page_open`) | | sent by page wndproc 0x02011e08 |
| 0x10 | page CLOSE | | same |
| 0x11 | page got focus again (child closed) | | same |
| 0x12 | sent to parent page when a child opens [I] | | same |
| 0x13 | window msg 22 forwarded [I] | | same |
| 0x14 | after-paint hook | top window | `ui_refresh` 0x020495d4 -> 0x02000474 |
| 0x15 | video recording stopped | | `video_stop` 0x0200cb0c |
| 0x16-0x18 | video recorder internal | | 0x0200cd50 (0x17), 0x0200cf1c/0x0200d040/0x0200d184 (0x18) |
| 0x1B | MP3 track finished (value 2) | | 0x020123d8 |
| 0x1C-0x23 | keys (table above); 0x20/0x21 only in games | 0/1/2 | key_poll_post, game_key_timer |
| 0x25 | POWER short (also posted by games at low battery) | | |
| 0x26 | Photo: capture now | | Photo 0x1C handler, self-timer end 0x020082cc |
| 0x27 | POWER long | | |
| 0x28, 0x29 | in the global table (timer reset) but **no producer** in this build | | |

Timers [V]: `get_ms` 0x0201f504 (10 ms resolution), `delay_ms` 0x0201f524 (busy wait), `swtimer_create(period_ms, cb)` 0x0201f5c0
(8 slots at 0x0207efb0 `{remaining, period, cb, ?}`, callbacks run from the 100 Hz ISR via 0x0201f67c [I: ISR context]),
`swtimer_delete` 0x0201f64c. Hardware timer: `FUN_020368d8(0, 100, isr)` in app_init.

Other polled sources (`sys_poll` 0x0200c50c, every >10 ms): screen saver (`screen_saver_kick` 0x0200bb2c, slot 10), auto power
off (`autopoweroff_tick` 0x0200bdac, slot 9, 500 ms steps), SD (`sdcard_poll`), USB/battery (`usb_battery_poll`).

## 3. UI / graphics API

A small window manager. The windows draw into an **8-bit palette-indexed OSD layer** (`osd_get_buffer` 0x0204952c = layer-1 buffer,
width `*(u16*)0x02080ad2` = 320, height `*(u16*)0x02080ad0` = 240, rotation `0x020335fc` = 0/3/4/5). Window heap: 40 KiB at
`0x02087b20` (`ui_init` 0x020258c0). Coordinates are written for 320x240 and scaled to the layer (unless flag 0x20).

### 3.1 Windows [V unless marked]

| Address | Signature | Notes |
|---|---|---|
| 0x02024424 | `win *win_create(s16 x, s16 y, u16 w, u16 h, win *parent, wndproc proc, u32 size, u16 flags)` | flag 2 = child, 8 = absolute coords, 0x20 = no scaling. Struct: rect s16 x0,x1,y0,y1 @0; invalid rect @0xC; u8 colour @0x18; u16 flags @0x1A; proc @0x20; parent @0x24; sibling @0x28; child @0x2C |
| 0x02023410 | `win *frame_create(x, y, w, h, parent, flags, id)` | proc 0x020232a4 |
| 0x02023188 | `win *progress_create(x, y, w, h, parent, flags, id)` | proc 0x02022f60 |
| 0x02023718 | `win *label_create(x, y, w, h, parent, flags, id)` | proc 0x02023508 |
| 0x02023f0c | `win_send(win, msg *m)` | m = `{u32 type, win *dst, win *src, u32 arg, ...}`; calls `win->proc(m)` |
| 0x02023f74 | `win_notify_parent(win, msg)` | |
| 0x02024830 | `win_destroy(win **pw)` | |
| 0x02025518 | `win_invalidate(win)` | |
| 0x02024e70 | `win_invalidate_parent_area(win)` | msg 5 |
| 0x02024d14 | `win_set_text(win, u32 text)` | msg 7. text = `0x81000000\|n` string n, `0x88000000\|n` file-list name, or `char *` |
| 0x02024d44 | `win_set_image(win, id)` [I] | msg 8 |
| 0x02024c54 | `win_set_visible(win, bool)` | msg 0xC get, 0xB set |
| 0x02024cd8 | `bool win_is_visible(win)` | |
| 0x02024bec | `win_set_colour_d(win, u8 c)` | msg 0xD (progress: bar colour; root: 0xFB) [I: which colour] |
| 0x02024c20 | `win_set_colour_e(win, u8 c)` | msg 0xE (frame/progress background) [I] |
| 0x02024d74 | `label_set_style(win, u8 font, u8 align, u8 colour)` | msg 0xF; align 1 left, 2 centre, 4 right [I] |
| 0x02025588 | `win_set_value(win, v)` | msg 0x10: progress bar / zoom bar value |
| 0x02020488 | `win *win_get_child(win, u16 id)` | msg 0x1A |
| 0x02021bf4 / 0x02021c64 | `list_select_next(list)` / `list_select_prev(list)` [prev: I] | wrap around |
| 0x02021de0 | `int list_get_selection(list)` [I] | |
| 0x02021638 | `list_set_selection(list, i)` | |
| 0x020255e8 | `win *ui_get_focus(void)` | `0x0207f0a8` |
| 0x02025608 | `ui_paint_all(void)` | sends msg 6 (PAINT) with the clip rect to invalid windows |
| 0x020495d4 | `ui_refresh(bool force)` | paint, event 0x14, copy the OSD buffer to the layer (`0x0202693c`) and show it (`0x02003e58`) |
| 0x0202584c | `ui_destroy_all(void)` | called on every task switch |

### 3.2 Pages (screens) (V)
`ui_page_open(page_desc *p, int argc, ...)` **0x02011fbc** (up to 5 extra args, on the stack). `page_desc` = `{event_table *ev,
widget_desc *layout, win *handle, u8 opened}`. It builds the windows from `layout` (`ui_create_from_layout` 0x020203d8), installs
`ev` and sends OPEN (0x0F) with the args. The common page wndproc is 0x02011e08.

Layout = array of 48-byte widget descriptors, ended by a 0 word: `{ctor, u16 id, u16 x, u16 y, u16 w, u16 h, u16 flags, u32 colour,
u32 image, u32 ?, u32 text, u32 style(align | colour<<8 | font<<16 [I]), ...}`. Constructors: frame 0x020206fc, label 0x020237d4,
image/icon 0x020209a0, listbox 0x02020aa0, progress bar 0x0202320c, level bar 0x02023494 (MP3 spectrum).

| Page | Address | Use |
|---|---|---|
| Main menu | 0x02078c3c | full screen, no widgets (draws JPEGs 38-44, table 0x020631b0 = res 41,44,42,43,39,40) |
| Photo / Video / Playback / MP3 | 0x020772f8 / 0x0207797c / 0x02077638 / 0x02078900 | status icons, labels, zoom bar |
| Settings list / option list | 0x020781bc / 0x020782cc | listbox |
| Game menu | 0x02078dd4 | carousel |
| Message box | 0x02078594 | `ui_page_open(&msgbox, 2, text_id, timeout_s /* -1 = none */)`, title "Prompt" |
| Message (no title) | 0x020786d8 | same args |
| Delete / Delete All confirm | 0x02077f94 / 0x02077e8c | OK/Cancel list |
| Format / Factory reset confirm | 0x020780a4 / 0x02077d74 | opened by 0x020063b8 / 0x020063e4 |
| Date/Time editor / Version box | 0x02077c8c / 0x020787e4 | opened by 0x02006360 / 0x0200638c |
| "No files" | 0x020784bc | |

### 3.3 Drawing primitives (OSD layer, 1 byte per pixel) (V)
| Address | Signature |
|---|---|
| 0x0204b278 | `osd_draw_text(rect *box, rect *clip, u32 text, u8 font, u8 align, u8 fg, s8 bg /* -1 = no fill */, ?)` |
| 0x02049b4c | `int text_measure(u32 text, u16 *w, u16 *h, u8 font)` (returns char count) |
| 0x0204ae44 | `osd_draw_icon(rect *box, rect *clip, u32 icon_id, u32 align, u8 ?)` |
| 0x0204beec | `res_image_size(u32 id, u16 *w, u16 *h)` |
| 0x0204a4b8 | `osd_fill_rect(rect *r, u8 colour)` |
| 0x0204aca4 | `osd_fill_rect_outside(rect *outer, rect *inner, u8 colour)` |
| 0x02049dc4 | `osd_flush_rect(rect *r)` (D-cache write-back of the rows, 0x0202642c) |
| 0x0201f6e8 | `jpeg_res_decode(res, dst, ?, w, h)` [I] (full-screen menu JPEGs) |
| 0x02005bf0 | `show_fullscreen_jpeg_res(res)` [I] |

- Resource IDs: **`0x80000000|n` = icon n of resource 53** (cache table 0x02078e98, 34 x 24 bytes, entry 0 = 14x14, matches
  the resource catalogue (not in this repo)). **`0x81000000|n` = string n** of the current language (table 0x020791c8, 204 strings, `lang_apply` 0x02005a54).
- Colours = palette indices (palette 54 [I: 54 rather than 55]): 0xF1 dark grey, 0xF2 darker grey, 0xF6 grey, 0xF7 orange,
  0xF8 black 50 % alpha, **0xF9 fully transparent** (full-screen pages, so live video shows through), 0xFA black, 0xFB white,
  0xFC blue, 0xFD green, 0xFE red, **0xFF = "no colour" (skip fill)**.

### 3.4 Sound (V)
- `audio_play(audio_req *r)` 0x02040d70. `r = {u8 fmt (2 or 6), u8 ch (1), u16 rate, u32 len, u16 src (0 file, 1 resource
  index, 2 RAM), u16 ?, u32 ptr_or_res}`. `audio_get_state` 0x02041048 (1 = playing). `audio_set_volume(0..100)` 0x0204113c.
- Key tone: `key_tone_play` 0x0200beb0 (resource 46, loaded once by `key_tone_load` 0x02006200).
  `play_wav_buffer(ptr, len)` 0x0200bf80. `play_wav_res_blocking(res)` 0x02005dd0.
- `power_screen_sound(play, wait, mode)` 0x02005f60: mode 1 = WELCOME (res 57) + **sound 50**; mode 0 = GOODBYE (56) +
  **sound 49**; mode 2 = black (3) + 49. So **50 is the power-on jingle and 49 the power-off jingle** (the old the resource catalogue (not in this repo) guess had them swapped; fixed there).
- Games use their own path: `game_play_sound(res 25|46, wait_before, wait_after)` 0x0201c5f0.

## 4. Task flow (V)

| Task | What it does |
|---|---|
| 6 Main menu | `MainMenu_enter` opens page 0x02078c3c. 2x3 icon grid, highlight blinks every 500 ms (JPEG 38 <-> 39-44). OK -> task |
| 3 Photo | live view, zoom, effects/frames, self-timer, capture on event 0x26. SD or internal flash |
| 2 Video | record start/stop, zoom, effects, speed mode (Normal/Slow/Fast) |
| 4 Playback | browse files, play/pause video, delete / delete all |
| 5 MP3 | track prev/next, play/pause, volume |
| 8 Settings | list of 14 items (table 0x02076ee0, [[FIRMWARE#Settings block]]). Items with options open list 0x020782cc. Date/Time, Version, Format, Default open their own pages |
| 7 Game menu | carousel of **3 games**; OK stores the game entry in `0x020829e8` and switches to task 11 |
| 11 Game | `Game_service` 0x0201c27c calls the game main loop **synchronously**, then `task_switch(7)` |
| 9 USB, 1 Power Off | [[analysis/io_storage#1. USB device (stock firmware)]], [[analysis/soc_core#3.4 Shutdown]] |

Games (table `0x02063450`, icons `0x0206345c` = res 17, 16, 15) [V table; game identity I from the icons]:
| # | Entry | Icon | Game |
|---|---|---|---|
| 0 | 0x02019fdc | res 17 crate | push-box (Sokoban) |
| 1 | 0x0201e7e8 | res 16 plane | plane shooter |
| 2 | 0x0201ef10 | res 15 maze | maze |

Icons 14 (bricks), 18 (blocks), 19 (snake) are unused, and so are the 7 game names in the string table. Game code loads resources 24, 29, 30,
31, 34 (via 0x0201b554) and 25/46 (sounds). There is also a 4th entry referenced at `0x0201989c` (special-cased in 0x0201b1f4),
but it is not in the menu [I: leftover game].

## 5. Settings write path (V)

- Flash address = `settings_flash_addr` 0x02048f28 = resource base + length rounded up to 4 KiB = **0x27C000**
  (`g_settings_addr` 0x0207a380). RAM copy `g_settings` **0x0207a3a0** (128 words). Word 127 = 0x0207a59c.
- `settings_checksum` 0x02003110: 32-bit sum of words 0..126. **If the sum is 0 it uses 0xAA55AA55.**
- `settings_load` 0x020032cc (app_init): two 256-byte reads. If the checksum is wrong -> zero, `settings_defaults` 0x020031d8 (also saves).
- `settings_save` **0x02003164**: word127 = checksum, `spi_flash_sector_erase(0x27C000)`, `spi_flash_write` 0x100 + 0x100.
- `settings_set_label(slot, label)` 0x0200337c (slot <= 126), `settings_get_label` 0x020033b8, `settings_apply(slot)` 0x02005acc [I].
- Saved **only** from: defaults (0x020032b0), option list select (0x020110ec), brightness page close (0x02010c08), Photo
  self-timer toggle (0x02008cd0/0x02008cf8), MP3 volume (0x020135d4/0x02013688). The date/time editor does not save (the RTC only)
  [I], which is why words 0-3 still hold the defaults 2025,1,1,4 on both units.
- Defaults (0x020031d8) = unit B's values: English, brightness 8, 50Hz, 1080P, date stamp On, cyclic 3 Min, 18M,
  volume 8, slot 20 On (key beep), slot 19 Mid, slot 25 Auto, slots 24/29 "0".
- **Slot 20 = key beep on/off (verified)**: `app_init` stores `settings_get_value(20)` in 0x020818ec, which `key_tone_play` checks.

## 6. API for our firmware

Stock functions (OR1K ABI, args r3..r8, return r11):

| Address | Signature | Use |
|---|---|---|
| 0x02002fa0 | `u32 adkey_get_event(void)` | 0 = none, else code \| 0x10000 (repeat) \| 0x20000 (release). Poll every ~20 ms |
| 0x02002de4 | `int adkey_scan_raw(void)` | debounced raw code or -1 |
| 0x02031bc8 | `u32 adc_read(ch)` | ch 3 = keys, 9 = battery, 11 = reference |
| 0x02027600 | `int gpio_read(port, mask)` | `gpio_read(1, 1)` = power key |
| 0x0201f1b0 / 0x0201f2b8 / 0x0201f3ac | queue create/post/get | main queue `*(0x02081958)` |
| 0x0201f504 / 0x0201f524 / 0x0201f5c0 | get_ms / delay_ms / swtimer_create | |
| 0x02011fbc | `ui_page_open(page, argc, ...)` | e.g. `ui_page_open(0x02078594, 2, 0x810000a3, 3)` = "Low battery" box, 3 s |
| 0x020495d4 | `ui_refresh(1)` | push the OSD to the screen |
| 0x0204b278 / 0x0204a4b8 / 0x0204ae44 | draw text / fill / icon on the OSD | |
| 0x0200beb0 | `key_tone_play()` | |
| 0x02040d70 | `audio_play(req)` | |
| 0x02003164 / 0x0200337c | settings_save / settings_set_label | |
| 0x02006ee0 | `task_switch(id, arg)` | |

Raw sequences:
- **Power key**: `l.mfspr rD, r0, 0x8004` -> bit 0 = 1 while pressed (PB0). adkey_init configures PB0 **and PB1** as inputs
  (`gpio_setup(1, 1, 1, 0)` and `gpio_setup(1, 2, 1, 0)`, 0x02031f60). PB1 is probably the ladder pin [I].
- **Ladder**: ADC channel 3, 10-bit, idle 1023. Windows centre ±29: 0 SHUTTER, 306 DOWN, 484 UP, 658 LEFT, 817 RIGHT. ADC
  registers (from appotech-sdk gpio.md, not re-verified here): clock gate bit 29 in SPR 0x8840 (active low), divider SPR 0x9174
  (71 -> 1 MHz), start = SPR 0x9170 bit 7, busy = 0x9170 bit 6, result = SPR 0x9178 low 10 bits. Stock: 0x0202b070 (select channel),
  0x0202b0d8 (clock 1 MHz), 0x0202b108 (start), 0x0202b12c (wait, read).
- Only one ladder key can be read at a time (chords are ambiguous). Power can be combined with a ladder key.
- **Settings block**: build 128 words, word127 = sum(0..126) (0 -> 0xAA55AA55), erase sector 0x27C000, program 512 bytes.

## 7. Open questions
- 0x06, 0x12, 0x13, 0x16-0x18 event meanings; Photo effect "mode 2"; Video `FUN_02043d50(9/10, x)` parameters.
- Which colour msg 0xD and msg 0xE set on each widget class; palette 54 vs 55 for the OSD.
- The game-menu carousel direction (LEFT = +1 is reversed compared with the main menu).
- Long shutter (0x1D) is generated but unused: a free input for custom firmware.
