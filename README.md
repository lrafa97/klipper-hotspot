# klipper-hotspot

Switch the Raspberry Pi of a Klipper machine into Wi-Fi hotspot mode, so you can reach
Mainsail from a phone or laptop where there is no network. Works with KlipperScreen on the machine.

> Status: V1, written and unit-tested off-device. Not yet run on a real Pi.
> See [ARCHITECTURE.md](ARCHITECTURE.md) ("Must be verified on a real Pi") before relying on it.

## Requirements

- Raspberry Pi OS Bookworm or newer, with NetworkManager (`nmcli`)
- A Wi-Fi interface (the Pi's own radio is fine) and the Wi-Fi country set (`raspi-config`)
- Klipper + Moonraker + Mainsail (MainsailOS defaults work)
- The `gcode_shell_command` Klipper extra (install with KIAUH)
- Python 3.9+ (nothing to `pip install`)

## Install

```
git clone https://github.com/lrafa97/klipper-hotspot.git
cd klipper-hotspot
./install.sh
```

Then add `[include klipper-hotspot.cfg]` to `printer.cfg` and restart Klipper.
For KlipperScreen buttons, paste `data/klipperscreen-menu.conf` into `KlipperScreen.conf`.

The installer generates a unique SSID and password for this machine. Print them on a label.

## Use

| Macro | What it does |
|---|---|
| `HOTSPOT_ON` | Switch the Wi-Fi radio to hotspot mode |
| `HOTSPOT_OFF` | Leave hotspot mode; the machine rejoins its normal Wi-Fi |
| `HOTSPOT_STATUS` | State, SSID, IP, connected clients (never the password) |
| `HOTSPOT_CREDENTIALS` | SSID and password (stays in the console history) |

Connect to the hotspot, then open `http://10.42.0.1` for Mainsail.

Over SSH: `klipper-hotspot on | off | status | credentials | doctor`.

Switching the hotspot on while connected over Wi-Fi disconnects you. Use the printer screen.

## Configuration

`/etc/klipper-hotspot/hotspot.conf`, see `data/hotspot.conf.example`. By default the hotspot
does **not** start at boot (`autostart = false`).

## Health check

```
klipper-hotspot doctor
```

Checks NetworkManager, the Wi-Fi interface, credentials, the daemon, and that Moonraker's
`trusted_clients` covers the hotspot subnet (MainsailOS trusts it by default).

## Update

```
cd klipper-hotspot && git pull && ./install.sh
```

Your config and credentials are kept. An active hotspot survives the update.

## Uninstall

```
./uninstall.sh          # keeps config and credentials
./uninstall.sh --purge  # removes everything
```

## Development

```
python3 -m pytest                       # everything that runs off-device
HOTSPOT_HW_TESTS=1 python3 -m pytest -m hardware   # on a Pi; switches the real radio
```

Hardware tests bring the real hotspot up and down: run them from the printer screen or Ethernet,
never over the Wi-Fi you are testing.

## License

Not chosen yet.
