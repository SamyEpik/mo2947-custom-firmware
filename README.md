# ToyCamera: custom firmware for the MO2947 toy camera

Write your own programs for the **MOB/MO2947** promotional toy camera (beige, 2" screen, microSD, USB-C) and install
them over USB. No programmer and no soldering. The firmware is based on
[matu6968's AppoTech SDK](https://github.com/matu6968/appotech-sdk), ported to this camera. Programs can use the display,
keys, LED, camera (640x480 photos), SD card, microphone, speaker, battery, and USB (debug link, USB drive, webcam).

The idea: open [Claude Code](https://claude.com/claude-code) in this folder, describe the program you want, and Claude
writes and builds it (`CLAUDE.md` tells it how). You then install the image with the steps below.

Works on **macOS** (Apple Silicon or Intel) and **Linux** (Arch, Debian/Ubuntu, Fedora).

> [!WARNING]
> Installing firmware rewrites the camera's flash. The tools keep the boot sector untouched and always leave a way back
> to the stock firmware, but you do this at your own risk. **Back up your camera first** (step 2), and keep that backup.

## What you need

- An MO2947 camera, charged, with a **microSD card** in it (any size, FAT32).
- A USB **data** cable, plugged straight into the computer (no hub).
- macOS: [Homebrew](https://brew.sh) and the Xcode Command Line Tools (`xcode-select --install`).
- About 6 GB of disk space and 30-90 minutes for the first setup (it builds the cross-compiler).

## 1. Install

```sh
git clone <this repo> ToyCamera
cd ToyCamera
./setup.sh
```

`setup.sh` installs the packages it needs (Homebrew on macOS, pacman/apt/dnf on Linux), creates a Python environment in
`.venv`, downloads the SDK and applies our camera port (`firmware/appotech-sdk`), downloads and builds the
`or1k-appotech-elf` compiler, and on Linux installs a udev rule so the camera works without root. You can run it again
at any time; finished steps are skipped. `./setup.sh --help` lists the options.

Everything else runs through `./cam`:

| Command | Does |
|---|---|
| `./cam dump …` | reads the camera's flash (backup). Read-only |
| `./cam flash …` | installs a program, or restores the stock firmware |
| `./cam apxd …` | talks to a running custom firmware over USB (log, photo, battery, …) |

On macOS, `./cam dump` and `./cam flash` ask for your password: libusb needs root to take the camera away from the
macOS USB-drive driver.

## 2. Back up the camera (once, before anything else)

1. Put the SD card in, **switch the camera on** (live view on the screen), **then** plug in USB.
   (Camera off when plugging in gives webcam-only mode, which does not work for this.)
2. If your computer mounts the camera's SD card, eject it (Finder / file manager), but leave the cable in.
   On macOS, if a "disk not readable" dialog appears, click **Ignore**.
3. Check that the camera is found (sends nothing to it):
   ```sh
   ./cam dump info
   ```
   It must list `0219:3280` with a mass-storage interface.
4. Read the whole flash (a few minutes; the camera's screen goes dark):
   ```sh
   ./cam dump stock dumps/mo2947_flash_a.bin
   ```
   It reads the chip twice and compares. Afterwards switch the camera off and on again; it runs the stock firmware as
   before. (If it does not react to POWER, see "After every install" in step 4.)
5. Copy `dumps/mo2947_flash_a.bin` somewhere safe. It is the only way back to the stock firmware, and the install tool
   and the SDK build both need it in `dumps/`.

**Keep the dump private**: it contains the photos stored on the camera and the vendor's firmware. `dumps/` is in
`.gitignore`; never commit or share it.

## 3. Write a program with Claude

Start Claude Code in this folder (`claude`) and ask for what you want, for example:

> Write a program for the camera that shows a stopwatch: SHUTTER starts and stops it, DOWN resets it.

Claude creates `firmware/appotech-sdk/examples/<name>/`, builds it, and gives you the image path,
`firmware/appotech-sdk/build/mo2947/<name>.bin`. It does not flash the camera unless you tell it to.

To build by hand:
```sh
source .venv/bin/activate
cd firmware/appotech-sdk
make BOARD=mo2947 EXAMPLE=mo2947-camera      # the full demo: preview, photos to SD, sound, USB modes
```

## 4. Flash a program

Always look at the plan first. It works offline and lists the flash sectors that will change:
```sh
./cam flash plan firmware/appotech-sdk/build/mo2947/<name>.bin
```

**First install (the camera still runs the stock firmware):** SD card in, camera on, then USB (as in step 2), then
```sh
./cam flash install firmware/appotech-sdk/build/mo2947/<name>.bin WRITE
```

**Later installs (the camera runs one of our programs):** with the camera on and connected,
```sh
./cam apxd loader                                                            # program -> USB loader
./cam flash install firmware/appotech-sdk/build/mo2947/<name>.bin WRITE --loader
```
If the program does not answer over USB (it crashed, or it is in USB-drive/webcam mode): start the install command
with `--loader` first, then **hold SHUTTER while switching the camera on**. It waits up to 5 minutes for the camera.

**After every install:** the tool prints `all sectors verified`. Then switch the camera off and on. If it does not react
to POWER (screen dark), it is still held by the USB loader with its watchdog off: unplug USB and disconnect the battery
for a moment (case screws: Phillips PH00), then switch on.

Never interrupt a write. If an install stops with an error, run the same command again; the entry sector is written
last, so the old program still starts until then.

## 5. Debug a running program

Our programs show up over USB as "JT5295 SDK Debug" (`1908:3319`):
```sh
./cam apxd info              # board, build, clock, previous crash
./cam apxd log 30            # printf output, followed for 30 s
./cam apxd photo test.jpg    # take a photo and download it
./cam apxd battery
```
`./cam apxd` without arguments lists all commands.

## Back to the stock firmware

```sh
./cam flash restore WRITE --loader
```
then hold SHUTTER while switching the camera on. It writes the stock app back from your backup (only the sectors that
differ). If the camera no longer reaches the loader at all, see the recovery routes in `docs/FIRMWARE.md`
("Route B (forced loader, for recovery)"; needs the case open and tweezers).

## Layout

| Path | Contents |
|---|---|
| `setup.sh`, `cam` | install script, tool launcher |
| `tools/` | dump, flash and debug-link tools (Python, pyusb) |
| `firmware/appotech-sdk-mo2947.patch` | our camera port of the SDK; `setup.sh` applies it to `firmware/appotech-sdk` |
| `docs/` | the technical reference: start with `docs/HARDWARE.md` (Obsidian notes, plain Markdown) |
| `CLAUDE.md` | instructions for Claude Code |
| `dumps/` | your backup (private, not in git) |

## Credits

- [matu6968/appotech-sdk](https://github.com/matu6968/appotech-sdk) (MIT): the SDK, toolchain patches and much of the
  register knowledge.
- [tbelbek/luxorparts-kdc030d-re](https://github.com/tbelbek/luxorparts-kdc030d-re): the USB loader and flash payload
  code the dump and flash tools build on.
- GCC, binutils and picolibc, built from source by `setup.sh`.
