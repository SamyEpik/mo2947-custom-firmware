#!/usr/bin/env python3
"""Talk to our SDK firmware over its USB debug link (APXD v1, vendor bulk interface of 1908:3319 "JT5295 SDK Debug").
Own client, written from the SDK's src/debug.c (header '<4sBBBBIIII': magic, version, operation, space, width, sequence,
address, length, status; payload after it, at most 4096 bytes).

  info                       board, build, clock, previous crash (JSON)
  log [SECONDS]              print the firmware log (printf), follow for SECONDS (default: once)
  spr NUMBER...              read SPRs, e.g. spr 0x8858 0x885c
  mem ADDRESS LENGTH         hex dump of memory (SRAM, SDRAM)
  clock                      the boot clock record our early code leaves at SRAM 0x2e80 + live PLL SPRs
  cmd OPERATION SUB [HEX]    raw subsystem command (STORAGE, CAMERA, AUDIO, MICROPHONE, BATTERY, JPEG, SPI, GPIO,
                             SYSTEM) with an optional hex payload; prints the reply (text if printable)
  sd [PATH]                  SD card state, volume and directory listing (default 0:/)
  camera                     camera state (JSON)
  photo OUT.jpg              capture 640x480 into camera RAM and download the JPEG (nothing is written to the SD card)
  rec SECONDS OUT.wav        record from the microphone (max ~2 s at 16 kHz) and download it as WAV
  tone [HZ] [MS]             play a tone on the speaker (default 880 Hz, 500 ms)
  battery                    battery state (JSON)
  loader                     ask the firmware to enter the boot ROM USB loader (no flash write; then
                             "mo2947_flash.py ... --loader" catches it)
Memory/SPR writes are not offered here on purpose. Run: python3 -I tools/mo2947_apxd.py ...
"""
import json
import struct
import sys
import time

import usb.core
import usb.util
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mo2947_usb   # noqa: E402

HEADER = struct.Struct('<4sBBBBIIII')
OPS = dict(INFO=0, READ=1, WRITE=2, BOOTROM=3, LOG=4, STORAGE=5, GPIO=6, SYSTEM=7, JPEG=8, AUDIO=9, MICROPHONE=10,
           CAMERA=11, SPI=12, BATTERY=13, UART=14)
STATUS = {0: 'OK', 1: 'INVALID', 2: 'RANGE', 3: 'UNSUPPORTED', 4: 'PROTECTED', 5: 'IO'}
MEMORY, SPR = 0, 2


class Link:
    def __init__(self, timeout=5000):
        devs = [d for d in usb.core.find(find_all=True, idVendor=0x1908, idProduct=0x3319, backend=mo2947_usb.backend())]
        found = []
        for d in devs:
            for intf in d.get_active_configuration():
                eps = {e.bEndpointAddress for e in intf}
                if intf.bInterfaceClass == 0xFF and eps == {0x01, 0x81}:
                    found.append((d, intf.bInterfaceNumber))
        if len(found) != 1:
            sys.exit(f'expected one "JT5295 SDK Debug" device, found {len(found)} (the boot ROM loader has no such interface)')
        self.dev, self.intf = found[0]
        usb.util.claim_interface(self.dev, self.intf)
        self.seq, self.timeout = 0, timeout

    def request(self, op, space=MEMORY, width=1, address=0, length=0, payload=b''):
        self.seq = (self.seq + 1) & 0xFFFFFFFF
        frame = HEADER.pack(b'APXD', 1, op, space, width, self.seq, address, length, 0) + payload
        self.dev.write(0x01, frame, timeout=self.timeout)
        data = bytes(self.dev.read(0x81, HEADER.size + 4096, timeout=self.timeout))
        magic, ver, rop, _, _, seq, _, rlen, status = HEADER.unpack_from(data)
        if magic != b'APXD' or seq != self.seq or len(data) != HEADER.size + rlen:
            raise RuntimeError(f'bad reply header {data[:24].hex()}')
        if status:
            raise RuntimeError(f'firmware status {STATUS.get(status, status)}')
        return data[HEADER.size:]

    def close(self):
        usb.util.release_interface(self.dev, self.intf)
        usb.util.dispose_resources(self.dev)


def num(s):
    return int(s, 0)


def main():
    a = sys.argv[1:]
    if not a:
        sys.exit(__doc__)
    link = Link()
    try:
        if a[0] == 'info':
            print(json.dumps(json.loads(link.request(OPS['INFO'])), indent=1))
        elif a[0] == 'log':
            end = time.monotonic() + (float(a[1]) if len(a) > 1 else 0)
            while True:
                chunk = link.request(OPS['LOG'], length=4096)
                if chunk:
                    sys.stdout.write(chunk.decode(errors='replace'))
                    sys.stdout.flush()
                if time.monotonic() >= end:
                    break
                time.sleep(0.2)
        elif a[0] == 'spr':
            for s in a[1:]:
                v = struct.unpack('<I', link.request(OPS['READ'], SPR, 4, num(s), 4))[0]
                print(f'SPR {num(s):#06x} = {v:#010x}')
        elif a[0] == 'mem':
            addr, n = num(a[1]), num(a[2])
            out = b''
            while len(out) < n:
                k = min(4096, n - len(out))
                out += link.request(OPS['READ'], MEMORY, 4 if (addr + len(out)) % 4 == 0 and k % 4 == 0 else 1,
                                    addr + len(out), k)
            for i in range(0, len(out), 16):
                print(f'{addr + i:08x}  {out[i:i + 16].hex(" ")}')
        elif a[0] == 'clock':
            rec = struct.unpack('<9I', link.request(OPS['READ'], MEMORY, 4, 0x2E80, 36))
            names = ['0x8858', '0x885c', '0x9800', '0x9808', '0x880c', '0x8840', '0x8844', '0x8864']
            print('boot record', 'valid' if rec[0] == 0x304B4C43 else f'missing ({rec[0]:#x})')
            for n, v in zip(names, rec[1:]):
                live = struct.unpack('<I', link.request(OPS['READ'], SPR, 4, int(n, 16), 4))[0]
                print(f'  SPR {n}: at boot {v:#010x}   now {live:#010x}')
        elif a[0] == 'sd':
            print(link.request(OPS['STORAGE'], address=0).decode())
            try:
                v = link.request(OPS['STORAGE'], address=2)
                fs, csize, serial = struct.unpack_from('<III', v)
                print(f'volume: FAT type {fs}, cluster {csize} sectors, serial {serial:#010x}, label {v[12:].split(b"\0")[0].decode()!r}')
            except RuntimeError as exc:
                print('volume:', exc)
            path = (a[1] if len(a) > 1 else '0:/').encode() + b'\0'
            for i in range(10000):
                e = link.request(OPS['STORAGE'], address=3, length=4 + len(path), payload=struct.pack('<I', i) + path)
                if not e:
                    break
                size, _, attr, date, tm = struct.unpack_from('<IIIII', e)
                name = e[20:].split(b'\0')[0].decode(errors='replace')
                stamp = f'{(date >> 9) + 1980:04}-{(date >> 5) & 15:02}-{date & 31:02} {tm >> 11:02}:{(tm >> 5) & 63:02}'
                print(f'  {"<DIR>" if attr & 0x10 else f"{size:>10}"}  {stamp}  {name}')
        elif a[0] in ('camera', 'battery'):
            print(link.request(OPS[a[0].upper()]).decode())
        elif a[0] == 'photo':
            link.request(OPS['CAMERA'], address=2, length=12, payload=struct.pack('<III', 640, 480, 8))
            end = time.monotonic() + 15
            while True:
                info = json.loads(link.request(OPS['CAMERA']))
                if info['job'] == 4:
                    break
                if info['job'] == 5 or time.monotonic() > end:
                    sys.exit(f'capture failed: {info}')
                time.sleep(0.05)
            data = b''
            while len(data) < info['jpeg_bytes']:
                n = min(4096, info['jpeg_bytes'] - len(data))
                data += link.request(OPS['CAMERA'], address=3, length=8, payload=struct.pack('<II', len(data), n))
            open(a[1], 'wb').write(data)
            print(f'{a[1]}: {len(data)} bytes, starts {data[:4].hex()} (JPEG = ffd8ffe0/ffd8ffdb), sensor {info["sensor_id"]:#x}')
            link.request(OPS['CAMERA'], address=1, length=4, payload=struct.pack('<I', 1))
        elif a[0] == 'rec':
            rate = 16000
            n = min(65536, int(float(a[1]) * rate * 2)) & ~31
            link.request(OPS['MICROPHONE'], address=1, length=8, payload=struct.pack('<II', n, rate))
            end = time.monotonic() + float(a[1]) + 3
            while True:
                info = json.loads(link.request(OPS['MICROPHONE']))
                if info['state'] == 3:
                    break
                if info['state'] == 4 or time.monotonic() > end:
                    sys.exit(f'recording failed: {info}')
                time.sleep(0.1)
            pcm = b''
            while len(pcm) < info['bytes']:
                k = min(4096, info['bytes'] - len(pcm))
                pcm += link.request(OPS['MICROPHONE'], address=3, length=8, payload=struct.pack('<II', len(pcm), k))
            hdr = b'RIFF' + struct.pack('<I', 36 + len(pcm)) + b'WAVEfmt ' + struct.pack('<IHHIIHH', 16, 1, 1, rate, rate * 2, 2, 16)
            open(a[2], 'wb').write(hdr + b'data' + struct.pack('<I', len(pcm)) + pcm)
            samples = struct.unpack(f'<{len(pcm) // 2}h', pcm)
            peak = max(abs(s) for s in samples) if samples else 0
            print(f'{a[2]}: {len(samples)} samples at {rate} Hz, peak {peak} of 32767')
        elif a[0] == 'tone':
            hz = num(a[1]) if len(a) > 1 else 880
            ms = num(a[2]) if len(a) > 2 else 500
            link.request(OPS['AUDIO'], address=1, length=12, payload=struct.pack('<III', hz, ms, 16000))
            print(f'tone {hz} Hz {ms} ms started')
        elif a[0] == 'loader':
            link.request(OPS['BOOTROM'])
            print('firmware acknowledged; the boot ROM loader 1908:3319 should appear in about 0.3 s')
        elif a[0] == 'cmd':
            op = OPS[a[1].upper()]
            payload = bytes.fromhex(a[3]) if len(a) > 3 else b''
            reply = link.request(op, address=num(a[2]), length=len(payload), payload=payload)
            text = reply.decode(errors='replace')
            print(text if reply and all(32 <= c < 127 or c in (9, 10, 13) for c in reply) else reply.hex(' '))
        else:
            sys.exit(__doc__)
    finally:
        link.close()


if __name__ == '__main__':
    main()
