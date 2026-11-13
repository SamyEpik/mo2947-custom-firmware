#!/usr/bin/env python3
"""Read-only SPI flash dump for the MO2947 (Jinrixin / Buildwin AX329x) through the chip's BootROM USB loader.

Built on tbelbek/luxorparts-kdc030d-re (device/kdc_dump.py, device/kdc_run.py, tools/flstub.py). That tool only
accepts the exact USB descriptors of the Luxorparts camera; this wrapper accepts our camera's IDs, keeps the strict
check on the loader (which is mask ROM, so it should match), and does two full reads.

It never sends a flash erase or program command: only SPI JEDEC-ID (0x9F) and READ (0x03) through flstub's
command 0 and command 1.

  info              list the camera's USB identities and interfaces (sends nothing to the camera)
  stock OUT.bin     camera in a mode with mass storage: INQUIRY, then 0xDA -> loader, then dump
  forced OUT.bin    wait (up to 2 min) for a loader forced with the flash pin-2/pin-3 short, then dump

Set KDC_REPO to the luxorparts-kdc030d-re checkout (default: ../ext/luxorparts-kdc030d-re). Linux: install the udev
rule (setup.sh does). macOS: run with sudo (libusb must detach the mass-storage driver); ./cam does that for you.
"""
import hashlib
import os
import struct
import sys
import time
from pathlib import Path

import usb.core
import usb.util

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mo2947_usb          # noqa: E402  (sets KDC_LIBUSB on macOS before the luxorparts tools load libusb)
mo2947_usb.libusb_path()

REPO = Path(os.environ.get('KDC_REPO', Path(__file__).resolve().parent.parent / 'ext' / 'luxorparts-kdc030d-re'))
sys.path.insert(0, str(REPO / 'device'))
sys.path.insert(0, str(REPO / 'tools'))
try:
    import kdc_dump as K   # noqa: E402
    import kdc_run as R    # noqa: E402
    import flstub          # noqa: E402
except ImportError as exc:
    sys.exit(f'cannot import the luxorparts tools from {REPO} ({exc}); clone it there or set KDC_REPO')

STOCK_IDS = [(0x0219, 0x3280), (0x1908, 0x3282), (0x1908, 0x3283)]
ALL_IDS = STOCK_IDS + [K.LOADER_ID]
REQ = 0x3400           # request block in SRAM, as in kdc_run.dumpflash
CHUNK = 480            # bytes per flash read, as in kdc_run.dumpflash
SIZES = {0x15: 0x200000, 0x16: 0x400000, 0x17: 0x800000}


def info():
    found = False
    for vid, pid in ALL_IDS:
        for dev in usb.core.find(find_all=True, idVendor=vid, idProduct=pid, backend=K.BACKEND):
            found = True
            print(f'{vid:04x}:{pid:04x} bus {dev.bus} addr {dev.address}')
            for idx in (1, 2, 3):
                try:
                    print(f'  string {idx}: {usb.util.get_string(dev, idx)!r}')
                except (usb.core.USBError, ValueError):
                    pass
            for cfg in dev:
                for intf in cfg:
                    try:
                        drv = 'kernel driver bound' if dev.is_kernel_driver_active(intf.bInterfaceNumber) else 'no driver'
                    except usb.core.USBError:
                        drv = 'driver state unknown'
                    kind = {1: 'audio', 8: 'MASS STORAGE', 14: 'video', 255: 'vendor'}.get(intf.bInterfaceClass, '?')
                    print(f'  interface {intf.bInterfaceNumber} alt {intf.bAlternateSetting}: class '
                          f'{intf.bInterfaceClass:#04x}/{intf.bInterfaceSubClass:#04x}/{intf.bInterfaceProtocol:#04x} '
                          f'({kind}), {drv}')
    if not found:
        print('no camera found (looked for ' + ', '.join(f'{v:04x}:{p:04x}' for v, p in ALL_IDS) + ')')


def check_loader(timeout):
    print(f'waiting up to {timeout:.0f} s for the BootROM loader {K.LOADER_ID[0]:04x}:{K.LOADER_ID[1]:04x} ...')
    bot, dev, ident = K.open_loader(time.monotonic() + timeout)
    device, config = K.descriptors(dev)
    maker, product = usb.util.get_string(dev, 1), usb.util.get_string(dev, 2)
    raw = bot.cmd(b'\x12\x00\x00\x00\x24\x00', 36)
    print(f'loader: {maker!r} {product!r}, INQUIRY {ident}')
    if (ident != ('buildwin', 'video050loader') or raw != K.LOADER_INQUIRY or device not in K.LOADER_DEV
            or config not in K.LOADER_CFG or {maker, product} != {'BUILDWIN', 'BLDR v1.00'}):
        bot.release()
        sys.exit('loader fingerprint differs from the known BootROMs; stopping before any 0xCB command')
    return bot


def enter_from_stock():
    devs = [d for v, p in STOCK_IDS for d in usb.core.find(find_all=True, idVendor=v, idProduct=p, backend=K.BACKEND)]
    if len(devs) != 1:
        sys.exit(f'expected exactly one camera in stock mode, found {len(devs)}')
    dev = devs[0]
    print(f'stock device {dev.idVendor:04x}:{dev.idProduct:04x}')
    try:
        bot = K.Bot(dev)
    except RuntimeError:
        sys.exit('this USB mode has no mass-storage interface, so 0xDA cannot be sent. '
                 'Find a mass-storage mode or use "forced" (see DUMP_STEP_BY_STEP.md)')
    ident = bot.inquiry()
    print(f'INQUIRY: {ident}')
    if ident != ('buildwin', 'mediaplayer'):
        bot.release()
        sys.exit('mass-storage INQUIRY is not "Buildwin Media-Player"; stopping')
    print('sending 0xDA (reboot into the BootROM loader; RAM only, nothing is written)')
    try:
        bot.cmd(bytes([0xDA]) + b'\xff' * 15)
    except (usb.core.USBError, RuntimeError) as exc:
        print(f'  no status reply ({exc}); this is expected, the device re-enumerates')
    bot.release()
    return check_loader(15)


def dump(bot, out):
    blob = flstub.build()
    R.sram_write(bot, R.ENTRY, blob)
    if bot.rom_read(R.ENTRY, len(blob)) != blob:
        bot.release()
        sys.exit('payload upload read-back mismatch; stopping')
    print(f'read payload uploaded to SRAM 0x{R.ENTRY:x} ({len(blob)} bytes)')

    def cmd(command, addr, n):
        assert command in (0, 1)   # 0 = init + JEDEC, 1 = read. Never 2 (program) or 3 (erase).
        R.sram_write(bot, REQ, struct.pack('<7I', 0x52585041, 1, command, addr, n, 1, 0) + b'\0' * n)
        R.launch(bot, R.ENTRY, REQ)
        status = struct.unpack('<I', bot.rom_read(REQ + 20, 4))[0]
        return status, (bot.rom_read(REQ + 28, n) if n else b'')

    # Retry JEDEC so a forced loader can be caught before the pin short is released.
    jedec = None
    for _ in range(240):
        status, jd = cmd(0, 0, 3)
        if jd not in (b'\xff\xff\xff', b'\x00\x00\x00'):
            jedec = jd
            break
        print(f'  JEDEC {jd.hex()} (status 0x{status:x}): flash not readable yet; release the pin short now')
        time.sleep(0.25)
    if jedec is None:
        bot.release()
        sys.exit('flash never answered with a valid JEDEC ID; stopping')
    size = SIZES.get(jedec[2])
    print(f'JEDEC {jedec.hex()} (status 0x{status:x}) -> {"unknown size" if size is None else f"{size // 1024} KiB"}')
    if size is None:
        bot.release()
        sys.exit('unrecognised capacity byte; stopping (add it to SIZES once you know the chip)')

    passes = []
    for p in (1, 2):
        data = bytearray()
        start = time.monotonic()
        for off in range(0, size, CHUNK):
            n = min(CHUNK, size - off)
            status, d = cmd(1, off, n)
            if status != 0 or len(d) != n:
                bot.release()
                Path(f'{out}.pass{p}.partial').write_bytes(data)
                sys.exit(f'pass {p}: read failed at 0x{off:x} (status 0x{status:x}); partial data saved, NOT a backup')
            data += d
            if off % 0x40000 < CHUNK:
                print(f'  pass {p}: 0x{off:06x}/0x{size:06x}  {time.monotonic() - start:.0f} s', flush=True)
        passes.append(bytes(data))
    bot.release()

    h1, h2 = (hashlib.sha256(x).hexdigest() for x in passes)
    Path(out).write_bytes(passes[0])
    Path(f'{out}.pass2').write_bytes(passes[1])
    print(f'pass 1 sha256 {h1}\npass 2 sha256 {h2}')
    if h1 != h2:
        sys.exit('THE TWO READS DIFFER: do not trust this dump; run it again')
    print(f'two identical reads saved to {out} (and {out}.pass2); power-cycle the camera to return to stock')
    if passes[0][4:8] != b'BLDR':
        print('warning: no BLDR magic at offset 4; inspect the header before relying on this dump')


def main():
    if len(sys.argv) == 2 and sys.argv[1] == 'info':
        return info()
    if len(sys.argv) != 3 or sys.argv[1] not in ('stock', 'forced'):
        sys.exit(__doc__)
    out = sys.argv[2]
    if Path(out).exists():
        sys.exit(f'{out} exists; choose a new file name (backups are never overwritten)')
    bot = enter_from_stock() if sys.argv[1] == 'stock' else check_loader(120)
    dump(bot, out)


if __name__ == '__main__':
    main()
