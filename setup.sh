#!/usr/bin/env bash
# ToyCamera (MO2947) setup for macOS and Linux. Everything lands inside this folder except system packages and, on
# Linux, one udev rule.
#
#   1. packages: Homebrew (macOS) or pacman / apt / dnf (Linux): libusb, Python, and the host tools the cross-compiler
#      build needs (GMP/MPFR/MPC, flex, bison, texinfo, GNU make, Meson, Ninja)
#   2. .venv/ with pyusb and pyelftools (./cam and the SDK build use it)
#   3. ext/luxorparts-kdc030d-re (USB loader code the dump/flash tools use), pinned commit
#   4. firmware/appotech-sdk: matu6968's SDK at the pinned commit + our MO2947 port (firmware/appotech-sdk-mo2947.patch)
#      on branch mo2947, with its picolibc and tinyusb submodules
#   5. firmware/compilers: gcc + binutils sources at the pinned commits, then the or1k-appotech-elf toolchain is built
#      into firmware/appotech-sdk/toolchain/install (30-90 min, about 5 GB of disk)
#   6. Linux only: udev rule so the camera works without root (macOS uses sudo instead, see ./cam)
#
# Safe to re-run: finished steps are skipped.
#
# Usage: ./setup.sh [--skip-packages] [--skip-toolchain] [--skip-udev] [-y]

set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SDK="$ROOT/firmware/appotech-sdk"
SDK_PATCH="$ROOT/firmware/appotech-sdk-mo2947.patch"
SDK_URL=https://github.com/matu6968/appotech-sdk
SDK_BASE=b5163cc82bb3900ad2b3f1a2b4b44e6b9000d0e9
SDK_SUBMODULES=(third_party/picolibc third_party/tinyusb)
KDC_URL=https://github.com/tbelbek/luxorparts-kdc030d-re
KDC_COMMIT=c3850025e9d35122e485c467772e3d529150aca6
# dir|url|commit|branch (build.py checks the branch names and applies its own patches)
COMPILER_REPOS=(
	"binutils-gdb|https://github.com/gnutools/binutils-gdb|6ce87bbc521cf46eaee9a1f7ef61cee2cdfb3e32|binutils-openrisc-appotech"
	"gcc|https://github.com/gnutools/gcc|71b50793e1e2b12b36baff23c1211e43b8c86ecd|gcc16-openrisc-appotech"
)

DO_PACKAGES=1 DO_TOOLCHAIN=1 DO_UDEV=1 ASSUME_YES=0
for arg in "$@"; do
	case "$arg" in
		--skip-packages) DO_PACKAGES=0 ;;
		--skip-toolchain) DO_TOOLCHAIN=0 ;;
		--skip-udev) DO_UDEV=0 ;;
		-y|--yes) ASSUME_YES=1 ;;
		-h|--help) sed -n '2,19p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
		*) echo "unknown option: $arg (see --help)" >&2; exit 2 ;;
	esac
done

step() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
info() { printf '    %s\n' "$*"; }
warn() { printf '\033[1;33m!!  %s\033[0m\n' "$*" >&2; }
die()  { printf '\033[1;31mxx  %s\033[0m\n' "$*" >&2; exit 1; }
need() { command -v "$1" >/dev/null || die "missing command: $1"; }

[[ $EUID -ne 0 ]] || die "run as your normal user; the script calls sudo where it needs root"

OS=$(uname)
if [[ $OS == Darwin ]]; then PM=brew
elif command -v pacman >/dev/null; then PM=pacman
elif command -v apt-get >/dev/null; then PM=apt
elif command -v dnf >/dev/null; then PM=dnf
else PM=none
fi
NCPU=$( (command -v nproc >/dev/null && nproc) || sysctl -n hw.ncpu 2>/dev/null || echo 4)

# ---------------------------------------------------------------------------------------------------------------------
install_packages() {
	step "System packages ($PM)"
	local y=()
	case "$PM" in
		brew)
			xcode-select -p >/dev/null 2>&1 || {
				xcode-select --install || true
				die "install the Xcode Command Line Tools (a dialog should have opened), then run ./setup.sh again"
			}
			command -v brew >/dev/null || die "install Homebrew first: https://brew.sh, then run ./setup.sh again"
			brew install git python libusb gmp mpfr libmpc flex bison texinfo m4 make meson ninja
			;;
		pacman)
			[[ $ASSUME_YES == 1 ]] && y=(--noconfirm)
			sudo pacman -S --needed "${y[@]}" base-devel git python libusb gmp mpfr libmpc flex bison texinfo meson ninja zlib
			;;
		apt)
			[[ $ASSUME_YES == 1 ]] && y=(-y)
			sudo apt-get update
			sudo apt-get install "${y[@]}" build-essential git python3 python3-venv libusb-1.0-0 \
				libgmp-dev libmpfr-dev libmpc-dev flex bison texinfo meson ninja-build zlib1g-dev
			;;
		dnf)
			[[ $ASSUME_YES == 1 ]] && y=(-y)
			sudo dnf install "${y[@]}" gcc gcc-c++ make git python3 libusb1 \
				gmp-devel mpfr-devel libmpc-devel flex bison texinfo meson ninja-build zlib-devel
			;;
		*)
			warn "unknown package manager. Install by hand: git, Python 3 (with venv), libusb 1.0, a C/C++ compiler,"
			warn "GNU make, GMP/MPFR/MPC headers, flex, bison, texinfo, meson, ninja, zlib headers."
			;;
	esac
}

# ---------------------------------------------------------------------------------------------------------------------
setup_venv() {
	step "Python environment (.venv: pyusb, pyelftools)"
	local py=python3
	[[ $PM == brew ]] && py="$(brew --prefix python)/bin/python3"
	[[ -x "$ROOT/.venv/bin/python" ]] || "$py" -m venv "$ROOT/.venv"
	"$ROOT/.venv/bin/python" -m pip install -q --upgrade pip
	"$ROOT/.venv/bin/python" -m pip install -q pyusb pyelftools
	"$ROOT/.venv/bin/python" -I -c 'import usb.core, elftools' && info "ok       .venv"
}

# ---------------------------------------------------------------------------------------------------------------------
clone_pinned() { # dir url commit [branch]
	local dir=$1 url=$2 commit=$3 branch=${4:-} rel=${1#"$ROOT"/}
	if [[ -d "$dir/.git" || -f "$dir/.git" ]]; then
		local head; head=$(git -C "$dir" rev-parse HEAD)
		if [[ "$head" == "$commit" ]]; then info "ok       $rel @ ${commit:0:10}"
		else warn "$rel is at ${head:0:10}, expected ${commit:0:10}; left as is"
		fi
		return 0
	fi
	[[ -e "$dir" ]] && { warn "$rel exists but is not a git checkout; skipped"; return 0; }
	info "fetching $rel @ ${commit:0:10}"
	git init -q "$dir"
	git -C "$dir" remote add origin "$url"
	git -C "$dir" fetch -q --depth 1 origin "$commit"
	if [[ -n "$branch" ]]; then git -C "$dir" checkout -q -b "$branch" FETCH_HEAD
	else git -C "$dir" -c advice.detachedHead=false checkout -q FETCH_HEAD
	fi
}

setup_ext() {
	step "ext/luxorparts-kdc030d-re (boot ROM loader code for dump/flash)"
	need git
	mkdir -p "$ROOT/ext"
	clone_pinned "$ROOT/ext/luxorparts-kdc030d-re" "$KDC_URL" "$KDC_COMMIT"
}

setup_sdk() {
	step "firmware/appotech-sdk (upstream ${SDK_BASE:0:7} + MO2947 port, branch mo2947)"
	need git
	if [[ ! -d "$SDK/.git" ]]; then
		[[ -e "$SDK" ]] && die "$SDK exists but is not a git checkout; move it away and re-run"
		clone_pinned "$SDK" "$SDK_URL" "$SDK_BASE" mo2947
		git -C "$SDK" -c user.name="ToyCamera setup" -c user.email=setup@localhost am -q --committer-date-is-author-date "$SDK_PATCH"
		info "applied $(grep -c '^From [0-9a-f]\{40\} ' "$SDK_PATCH") commits from ${SDK_PATCH#"$ROOT"/}"
	else
		info "ok       firmware/appotech-sdk on branch $(git -C "$SDK" branch --show-current) @ $(git -C "$SDK" rev-parse --short HEAD)"
	fi
	git -C "$SDK" submodule update --init --depth 1 "${SDK_SUBMODULES[@]}"
	info "ok       submodules ${SDK_SUBMODULES[*]}"
}

# ---------------------------------------------------------------------------------------------------------------------
setup_toolchain() {
	local gcc="$SDK/toolchain/install/bin/or1k-appotech-elf-gcc"
	if [[ -x "$gcc" && -e "$SDK/toolchain/install/or1k-appotech-elf/lib/libc.a" ]]; then
		step "Toolchain"; info "ok       $("$gcc" --version | head -1)"; return 0
	fi
	step "Compiler sources in firmware/compilers (shallow, pinned)"
	mkdir -p "$ROOT/firmware/compilers"
	local e dir url commit branch
	for e in "${COMPILER_REPOS[@]}"; do
		IFS='|' read -r dir url commit branch <<<"$e"
		clone_pinned "$ROOT/firmware/compilers/$dir" "$url" "$commit" "$branch"
	done

	step "Building or1k-appotech-elf toolchain with $NCPU jobs (30-90 min; logs in firmware/appotech-sdk/toolchain-build-*.log)"
	local s
	for s in binutils gcc picolibc libgcc; do
		info "stage $s"
		(cd "$SDK" && "$ROOT/.venv/bin/python" toolchain/build.py "$s" --jobs "$NCPU" > "toolchain-build-$s.log" 2>&1) \
			|| die "stage $s failed; see firmware/appotech-sdk/toolchain-build-$s.log (tail: $(tail -3 "$SDK/toolchain-build-$s.log" | tr '\n' ' '))"
	done
	info "ok       $("$gcc" --version | head -1)"
}

# ---------------------------------------------------------------------------------------------------------------------
setup_udev() {
	[[ $OS == Linux ]] || return 0
	step "udev rule for the camera (USB vendors 1908 and 0219)"
	local rule=/etc/udev/rules.d/70-mo2947.rules tmp
	tmp=$(mktemp)
	cat > "$tmp" <<'EOF'
# MO2947 toy camera (ToyCamera project): user access to all Buildwin/Jinrixin USB modes
SUBSYSTEM=="usb", ATTR{idVendor}=="1908", MODE="0660", TAG+="uaccess"
SUBSYSTEM=="usb", ATTR{idVendor}=="0219", MODE="0660", TAG+="uaccess"
EOF
	if [[ -f "$rule" ]] && cmp -s "$tmp" "$rule"; then
		info "ok       $rule"
	else
		sudo install -m 0644 "$tmp" "$rule"
		sudo udevadm control --reload-rules && sudo udevadm trigger --subsystem-match=usb || true
		info "installed $rule (replug the camera)"
	fi
	rm -f "$tmp"
}

# ---------------------------------------------------------------------------------------------------------------------
[[ $DO_PACKAGES == 1 ]] && install_packages
setup_venv
setup_ext
setup_sdk
[[ $DO_TOOLCHAIN == 1 ]] && setup_toolchain
[[ $DO_UDEV == 1 ]] && setup_udev

step "Done"
mkdir -p "$ROOT/dumps"
if [[ -f "$ROOT/dumps/mo2947_flash_a.bin" ]]; then
	info "flash backup present: dumps/mo2947_flash_a.bin"
else
	info "Next: back up your camera's flash (README.md, step 'Back up the camera'):"
	info "  ./cam dump stock dumps/mo2947_flash_a.bin"
fi
