#!/usr/bin/env bash
# klipper-hotspot installer. Safe to run again: it never overwrites your config or credentials.
#
#   ./install.sh [--user NAME] [--printer-data DIR]
#
# --user          the user that runs Klipper (default: the user who invoked sudo)
# --printer-data  the printer_data directory (default: ~USER/printer_data)
set -euo pipefail

PREFIX=/opt/klipper-hotspot
BIN=/usr/local/bin/klipper-hotspot
ETC=/etc/klipper-hotspot
UNIT=/etc/systemd/system/klipper-hotspot.service

die() { echo "ERROR: $*" >&2; exit 1; }
info() { echo "==> $*"; }
warn() { echo "WARNING: $*" >&2; }

# Re-run through sudo when not root (the Pi image normally has passwordless sudo, as KIAUH expects).
if [ "$(id -u)" -ne 0 ]; then
    exec sudo -- "$0" "$@"
fi

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
USER_NAME="${SUDO_USER:-}"
PRINTER_DATA=""

while [ $# -gt 0 ]; do
    case "$1" in
        --user) [ $# -ge 2 ] || die "--user needs a value"; USER_NAME="$2"; shift 2 ;;
        --printer-data) [ $# -ge 2 ] || die "--printer-data needs a value"; PRINTER_DATA="$2"; shift 2 ;;
        -h|--help) sed -n '2,8p' "$0"; exit 0 ;;
        *) die "unknown option: $1" ;;
    esac
done

[ -n "$USER_NAME" ] || die "cannot tell which user runs Klipper; pass --user NAME"
id "$USER_NAME" >/dev/null 2>&1 || die "user not found: $USER_NAME"
GROUP_NAME="$(id -gn "$USER_NAME")"
HOME_DIR="$(getent passwd "$USER_NAME" | cut -d: -f6)"
[ -n "$PRINTER_DATA" ] || PRINTER_DATA="$HOME_DIR/printer_data"

command -v python3 >/dev/null || die "python3 not found"
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' || die "Python 3.9 or newer is required"
command -v nmcli >/dev/null || die "nmcli not found: NetworkManager is required (Raspberry Pi OS Bookworm or newer)"
command -v systemctl >/dev/null || die "systemd is required"
if [ "$(nmcli -g WIFI-PROPERTIES.AP device show wlan0 2>/dev/null || true)" = "no" ]; then
    warn "NetworkManager says wlan0 does not support access point mode."
    warn "The hotspot will not work with this Wi-Fi adapter. Check: nmcli -f WIFI-PROPERTIES device show wlan0"
fi
[ -d "$SRC/src/klipper_hotspot" ] || die "run this script from a checkout of the repository"

info "Installing program to $PREFIX"
mkdir -p "$PREFIX"
rm -rf "$PREFIX/src"
cp -r "$SRC/src" "$PREFIX/src"
find "$PREFIX/src" -name '__pycache__' -type d -prune -exec rm -rf {} +

cat > "$BIN" <<'EOF'
#!/bin/sh
PYTHONPATH=/opt/klipper-hotspot/src exec python3 -m klipper_hotspot "$@"
EOF
chmod 755 "$BIN"

info "Configuration in $ETC"
mkdir -p "$ETC"
if [ -f "$ETC/hotspot.conf" ]; then
    info "Keeping existing $ETC/hotspot.conf"
else
    sed -e "s|@SOCKET_GROUP@|$GROUP_NAME|" \
        -e "s|@MOONRAKER_CONF@|$PRINTER_DATA/config/moonraker.conf|" \
        "$SRC/data/hotspot.conf.example" > "$ETC/hotspot.conf"
    chmod 644 "$ETC/hotspot.conf"
fi

"$BIN" init

info "Installing systemd service"
install -m 644 "$SRC/data/klipper-hotspot.service" "$UNIT"
systemctl daemon-reload
systemctl enable klipper-hotspot.service >/dev/null
# Restarting the daemon does not drop an active hotspot: it adopts it on startup.
systemctl restart klipper-hotspot.service

if [ -d "$PRINTER_DATA/config" ]; then
    info "Installing Klipper macros to $PRINTER_DATA/config"
    install -o "$USER_NAME" -g "$GROUP_NAME" -m 644 "$SRC/data/klipper-hotspot.cfg" "$PRINTER_DATA/config/klipper-hotspot.cfg"
else
    warn "$PRINTER_DATA/config not found; copy data/klipper-hotspot.cfg into your Klipper config folder by hand"
fi

MISSING_DEPS=0
if [ ! -f "$HOME_DIR/klipper/klippy/extras/gcode_shell_command.py" ]; then
    MISSING_DEPS=1
    warn "the gcode_shell_command Klipper extra was not found."
    warn "Install it with KIAUH BEFORE adding the include line, or Klipper will stop with:"
    warn "  Section gcode_shell_command hotspot_cmd is not a valid config section"
fi
if [ -d "$PRINTER_DATA/config" ] && ! grep -rqs --include="*.cfg" "^\[respond\]" "$PRINTER_DATA/config"; then
    MISSING_DEPS=1
    warn "no respond section found in your Klipper config. Add a line with only: [respond]"
    warn "to printer.cfg, or the macros and the on-screen messages will fail."
fi

cat <<EOF

Installed. Two manual steps (this installer never edits your printer.cfg or KlipperScreen.conf):

  1. Once the warnings above (if any) are fixed, add this line to printer.cfg, then restart Klipper:
         [include klipper-hotspot.cfg]

  2. Optional, KlipperScreen buttons (they appear in the More menu): paste
     data/klipperscreen-menu.conf into KlipperScreen.conf and restart KlipperScreen.

Health check:
EOF
"$BIN" doctor || true
