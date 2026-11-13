"""libusb lookup shared by the tools.

Homebrew installs libusb outside pyusb's default search path on macOS (/opt/homebrew/lib on Apple Silicon,
/usr/local/lib on Intel). KDC_LIBUSB, if set, wins; it is also the variable the luxorparts tools in ext/ read.
"""
import os
import sys
from pathlib import Path

import usb.backend.libusb1

_CANDIDATES = ('/opt/homebrew/lib/libusb-1.0.dylib', '/usr/local/lib/libusb-1.0.dylib')


def libusb_path():
    path = os.environ.get('KDC_LIBUSB')
    if not path and sys.platform == 'darwin':
        path = next((c for c in _CANDIDATES if Path(c).exists()), None)
        if path:
            os.environ['KDC_LIBUSB'] = path      # for ext/luxorparts-kdc030d-re/device/kdc_dump.py
    return path


def backend():
    path = libusb_path()
    be = (usb.backend.libusb1.get_backend(find_library=lambda _: path) if path
          else usb.backend.libusb1.get_backend())
    if be is None:
        sys.exit('libusb 1.0 not found: install it (macOS: brew install libusb; Linux: your libusb-1.0 package) '
                 'or set KDC_LIBUSB to the library path')
    return be
