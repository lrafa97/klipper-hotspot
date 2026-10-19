#!/usr/bin/env bash
# klipper-hotspot uninstaller.
#
#   ./uninstall.sh [--user NAME] [--printer-data DIR] [--purge]
#
# --purge also deletes the configuration, the credentials and the saved state.
# Without it they are kept, so a later reinstall keeps the same SSID and password.
set -euo pipefail

PREFIX=/opt/klipper-hotspot
BIN=/usr/local/bin/klipper-hotspot
ETC=/etc/klipper-hotspot
STATE=/var/lib/klipper-hotspot
UNIT=/etc/systemd/system/klipper-hotspot.service

die() { echo "ERROR: $*" >&2; exit 1; }
info() { echo "==> $*"; }

if [ "$(id -u)" -ne 0 ]; then
    exec sudo -- "$0" "$@"
fi

USER_NAME="${SUDO_USER:-}"
PRINTER_DATA=""
PURGE=0
while [ $# -gt 0 ]; do
    case "$1" in
        --user) [ $# -ge 2 ] || die "--user needs a value"; USER_NAME="$2"; shift 2 ;;
        --printer-data) [ $# -ge 2 ] || die "--printer-data needs a value"; PRINTER_DATA="$2"; shift 2 ;;
        --purge) PURGE=1; shift ;;
        -h|--help) sed -n '2,8p' "$0"; exit 0 ;;
        *) die "unknown option: $1" ;;
    esac
done

if [ -z "$PRINTER_DATA" ] && [ -n "$USER_NAME" ] && id "$USER_NAME" >/dev/null 2>&1; then
    PRINTER_DATA="$(getent passwd "$USER_NAME" | cut -d: -f6)/printer_data"
fi

info "Stopping the service"
systemctl stop klipper-hotspot.service 2>/dev/null || true
systemctl disable klipper-hotspot.service 2>/dev/null || true

if [ -x "$BIN" ]; then
    info "Removing the hotspot profile (the machine returns to its normal Wi-Fi)"
    "$BIN" cleanup || echo "WARNING: could not remove the hotspot profile; check with: nmcli connection show" >&2
fi

rm -f "$UNIT"
systemctl daemon-reload
rm -f "$BIN"
rm -rf "$PREFIX"

if [ -n "$PRINTER_DATA" ] && [ -f "$PRINTER_DATA/config/klipper-hotspot.cfg" ]; then
    rm -f "$PRINTER_DATA/config/klipper-hotspot.cfg"
fi

if [ "$PURGE" -eq 1 ]; then
    info "Purging configuration, credentials and state"
    rm -rf "$ETC" "$STATE"
else
    info "Keeping $ETC (use --purge to delete it)"
fi

cat <<EOF

Removed. Two manual steps:
  - delete "[include klipper-hotspot.cfg]" from printer.cfg and restart Klipper
  - delete the hotspot entries from KlipperScreen.conf, if you added them
EOF
