#!/usr/bin/env python3
"""Install our image in place of the stock app, or restore the stock app. Sector 0 is never touched.

The stock header loads flash 0x2200.. (0x7A400 bytes) to RAM 0x02000000 and the bootstrap calls 0x020004A8.
IMAGE is a binary of RAM 0x02000000.. (mo2947-hello: 0xE00 bytes; SDK: build/mo2947/<example>.bin).
Sector 0x2000 also holds the bootstrap tail 0x2000-0x21FF: kept byte-identical. Bytes after the image stay stock.

  plan    IMAGE                    offline: list the sectors that would change
  install IMAGE WRITE [--loader]   write the image
  restore WRITE [--loader]         write the stock app area 0x2000-0x7CFFF back from the backup (only sectors that differ)

Write order: every other sector first, sector 0x2000 (the entry) last. Until that last write the old entry stays intact
(mo2947-hello and the SDK image both escape to the loader when SHUTTER is held at power-on).
Default entry: camera in stock mass-storage mode (0xDA). --loader: wait up to 5 min for the boot ROM loader 1908:3319
(with our image installed: hold SHUTTER while switching the camera on).
Gates: live sector 0 == backup; install only if the live entry sector is stock or one of ours; the payload's write
window is [0x2000, end of the area being written). Run: python3 -I tools/mo2947_flash.py ...
"""
import hashlib
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import mo2947_dump as D      # noqa: E402

R = D.R
FIRST, APP, APP_MAX, SIZE = 0x2000, 0x2200, 0x7A400, 0x1000
AREA_END = 0x7D000                   # end of the sector holding the last app byte (0x7C5FF)
BACKUP = Path(os.environ.get('MO2947_DUMP', HERE.parent / 'dumps/mo2947_flash_a.bin'))   # your camera's own dump
if not BACKUP.is_file():
    sys.exit(f'no flash backup at {BACKUP}: dump this camera first (./cam dump stock {BACKUP}); '
             'every install is built from and checked against it')
JEDEC = bytes([0x5E, 0x40, 0x16])
ENTRY_OFF = APP - FIRST + 0x4A8      # 0x6A8: the bootstrap call target inside sector 0x2000


def target_area(image):
    backup = BACKUP.read_bytes()
    if not 0 < len(image) <= APP_MAX:
        sys.exit(f'image size {len(image):#x} not in 1..{APP_MAX:#x}')
    end = (APP + len(image) + SIZE - 1) & ~(SIZE - 1)
    area = bytearray(backup[FIRST:end])
    area[APP - FIRST:APP - FIRST + len(image)] = image
    assert area[:0x200] == backup[FIRST:APP]
    return backup, bytes(area)


def session(use_loader, window_end):
    bot = D.check_loader(300) if use_loader else D.enter_from_stock()
    import flstub
    blob = flstub.build(window=(FIRST, window_end))
    R.sram_write(bot, R.ENTRY, blob)
    if bot.rom_read(R.ENTRY, len(blob)) != blob:
        bot.release()
        sys.exit('payload upload read-back mismatch; nothing written')
    cmd = R._mkcmd(bot)
    st, jd = cmd(0, 0, 3)
    if st != 0 or jd != JEDEC:
        bot.release()
        sys.exit(f'JEDEC {jd.hex()} (status {st:#x}); nothing written')
    print(f'payload uploaded, write window 0x{FIRST:x}-0x{window_end:x}, JEDEC {jd.hex()}')

    def read(addr, n):
        out = bytearray()
        for off in range(0, n, 480):
            k = min(480, n - off)
            s, d = cmd(1, addr + off, k)
            if s != 0 or len(d) != k:
                sys.exit(f'read 0x{addr + off:x} failed (status {s:#x})')
            out += d
        return bytes(out)
    return bot, cmd, read


def write_sector(cmd, read, addr, data):
    fail = f'sector 0x{addr:x}: %s. The entry sector 0x2000 is written last, so the old entry should still boot; ' \
           f'retry, or run "restore WRITE --loader"'
    st, _ = cmd(3, addr, 0)
    if st != 0:
        sys.exit(fail % f'erase failed (status {st:#x})')
    if read(addr, SIZE) != b'\xff' * SIZE:
        sys.exit(fail % 'not blank after erase')
    for p in range(16):
        st, _ = cmd(2, addr + p * 256, 256, data[p * 256:(p + 1) * 256])
        if st != 0:
            sys.exit(fail % f'program page {p} failed (status {st:#x})')
    if read(addr, SIZE) != data:
        sys.exit(fail % 'verify mismatch')


def main():
    args = sys.argv[1:]
    use_loader = '--loader' in args
    args = [a for a in args if a != '--loader']
    if not args or args[0] not in ('plan', 'install', 'restore'):
        sys.exit(__doc__)
    backup = BACKUP.read_bytes()
    stock_entry = backup[FIRST:FIRST + SIZE]
    if args[0] in ('plan', 'install'):
        image = Path(args[1]).read_bytes()
        _, area = target_area(image)
        sectors = [FIRST + o for o in range(0, len(area), SIZE)]
        print(f'image {args[1]}: {len(image)} bytes, sha256 {hashlib.sha256(image).hexdigest()[:16]}')
        print(f'flash 0x{FIRST:x}-0x{FIRST + len(area) - 1:x}: {len(sectors)} sector(s); '
              f'{sum(a != b for a, b in zip(area, backup[FIRST:FIRST + len(area)]))} bytes differ from stock; '
              f'bootstrap tail identical: {area[:0x200] == backup[FIRST:APP]}')
        if args[0] == 'plan':
            return
        if args[2:] != ['WRITE']:
            sys.exit('add WRITE to write the flash')
    else:
        if args[1:] != ['WRITE']:
            sys.exit('add WRITE to write the flash')
        area = backup[FIRST:AREA_END]
    end = FIRST + len(area)

    bot, cmd, read = session(use_loader, end)
    try:
        if read(0, SIZE) != backup[:SIZE]:
            sys.exit('live sector 0 differs from the backup; refusing (wrong camera or wrong backup?)')
        live_entry = read(FIRST, SIZE)
        if live_entry[:0x200] != backup[FIRST:APP]:
            print('warning: bootstrap tail 0x2000-0x21FF differs from the backup; it will be rewritten')
        ours = live_entry[:0x200] == backup[FIRST:APP] and live_entry[ENTRY_OFF:ENTRY_OFF + 8] != stock_entry[ENTRY_OFF:ENTRY_OFF + 8]
        if args[0] == 'install' and live_entry != stock_entry and not ours:
            sys.exit('live entry sector is neither stock nor one of our images; run "restore WRITE" first')
        print(f'live entry sector: {"stock" if live_entry == stock_entry else "one of our images"}')
        print(f'reading 0x{FIRST:x}-0x{end - 1:x} to find the sectors that differ ...')
        live = live_entry + read(FIRST + SIZE, end - FIRST - SIZE)
        todo = [o for o in range(SIZE, len(area), SIZE) if live[o:o + SIZE] != area[o:o + SIZE]]
        if live[:SIZE] != area[:SIZE]:
            todo.append(0)                       # the entry sector, last
        if not todo:
            print('flash already has the requested content; nothing written')
            return
        print(f'writing {len(todo)} sector(s): ' + ' '.join(f'0x{FIRST + o:x}' for o in todo))
        for o in todo:
            write_sector(cmd, read, FIRST + o, area[o:o + SIZE])
            print(f'  0x{FIRST + o:x} OK', flush=True)
        if read(0, SIZE) != backup[:SIZE]:
            sys.exit('sector 0 changed?! (it was never addressed; investigate before power-cycling)')
        if read(FIRST, end - FIRST) != area:
            sys.exit('final read-back of the whole area differs; do not power-cycle, run the command again')
        print('all sectors verified, sector 0 unchanged. Switch the camera off (hold POWER or unplug), then on.')
    finally:
        bot.release()


if __name__ == '__main__':
    main()
