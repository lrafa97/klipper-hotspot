# Architecture

## Goal

Let someone connect to a Klipper machine when there is no Wi-Fi or Ethernet where the machine
operates: the Raspberry Pi becomes a Wi-Fi access point, and Mainsail (browser) and KlipperScreen
(on the machine) keep working.

V1 is deliberately small: a hotspot that you switch on and off. The structure leaves room for
automatic fallback and a Wi-Fi setup page, but nothing for those is built yet.

## Non-goals (V1)

- Joining the customer's Wi-Fi from a phone (the "portal"). Planned, not built.
- Automatic fallback when the Wi-Fi disappears. Planned, not built.
- Running the hotspot and a client Wi-Fi connection at the same time. One radio, one role.
- Hotspot and Ethernet at the same time as a supported case.
- 5 GHz, WPA3, internet sharing.

## Overview

```
 Mainsail console ──┐                         ┌──────────────────────────────┐
 KlipperScreen menu ┼─► G-code macro ──► CLI ─┤ Unix socket (JSON, 4 verbs)  │
 SSH (human)  ──────┘   (fixed command)       └──────────────┬───────────────┘
                                                             ▼
                                   ┌─────────────────── hotspotd (root) ────────────────────┐
                                   │ api ─► Manager ─► State machine (OFF/ON)               │
                                   │          │  ▲         ▲                                 │
                                   │          │  └─ Policy (Manual: autostart yes/no)        │
                                   │          ├─► StateStore (/var/lib, atomic JSON)         │
                                   │          └─► NetworkBackend (interface)                 │
                                   └───────────────────────┬─────────────────────────────────┘
                                                           ▼
                                            NmcliBackend ─► nmcli / iw ─► NetworkManager
```

| Module | Responsibility |
|---|---|
| `api.py` | Newline-delimited JSON over a Unix socket. Fixed verbs, no arguments, size-capped. |
| `manager.py` | Applies verbs through the backend, owns state, serialises with a lock. |
| `state.py` | Explicit state machine; every (state, event) pair must be defined. |
| `policy.py` | Decides *when* the hotspot should be on. V1: `ManualPolicy` (autostart yes/no). |
| `backend.py` | `NetworkBackend` interface + `NmcliBackend`. The only code that touches the network stack. |
| `store.py` | Persisted state (`desired`, `since`). Corruption-tolerant, never blocks a switch. |
| `credentials.py` | Per-machine SSID and password, generated once, stored 0600, never logged. |
| `config.py` | Strict, versioned INI. Reserved sections for future features. |
| `doctor.py` | Read-only health checks (NetworkManager, interface, credentials, daemon, Moonraker). |
| `cli.py`, `client.py` | The command-line entry point the macros call. |

## Control protocol

One request, one response, each a single JSON line over `/run/klipper-hotspot/control.sock`.

```
-> {"v":1,"cmd":"status"}
<- {"v":1,"ok":true,"result":{"state":"on","interface":"wlan0","ssid":"Klipper-7K2P",
                              "ip":"10.42.0.1","clients":1,"since":1760880000,"last_error":null}}
<- {"v":1,"ok":false,"error":{"code":"backend_error","message":"..."}}
```

Verbs: `on`, `off`, `status`, `credentials`. Extra fields are ignored. `status` never contains the
password (it is polled and may be logged or rendered by UIs); `credentials` is the one explicit
way to read it. Error codes are stable: `bad_request`, `unsupported_version`, `unknown_command`,
`backend_error`, `backend_unavailable`, `backend_timeout`, `internal_error`.

Every future UI (a web page, a QR code, a Moonraker component) is a client of this same contract.

## State machine

V1 states: `OFF`, `ON`. Events: `START_OK`, `STOP_OK`, `OBSERVED_ACTIVE`, `OBSERVED_INACTIVE`.

The state is *observed*, not assumed: `status` asks the backend every time, so a hotspot brought up
or down by hand (`nmcli`) is noticed. `last_error` is kept beside the state, not as a state of its
own, so the state always tells the truth about the radio.

Adding a mode later (`STA`, `FALLBACK`, `DEFERRED`) means adding a state and its rows to
`TRANSITIONS`. `test_every_state_event_pair_is_defined` fails until each new pair is decided.

## Behaviours worth knowing

- `on` when already on does nothing. It does not recreate the access point, which would drop clients.
- `off` deletes the NetworkManager profile, so the hotspot password is not left in NetworkManager
  while the hotspot is off, and nothing can bring it back.
- The profile is created with `autoconnect no`: a reboot never revives the hotspot by itself.
  `autostart = true` in the config is the only way it comes up at boot.
- Restarting or stopping the daemon leaves the hotspot as it is. On start, an active hotspot is
  adopted (including its original start time). Updating the software does not kick users off.
- Failed start removes the half-created profile.

## Security model

- Credentials are unique per machine, generated at install (`secrets`), stored 0600 root.
  Never share one password across customers' machines.
- The daemon runs as root (it drives NetworkManager). Its socket is `0660 root:<group>`; the group
  is the user that runs Klipper. Anyone who can run G-code can switch the hotspot on and off: that
  is accepted. They can never make the daemon run anything: verbs are fixed, arguments do not exist,
  and macros call one fixed command.
- Anyone connected to the hotspot is on a network Moonraker may trust (no login). The hotspot
  password is therefore the only protection. `doctor` checks that Moonraker's `trusted_clients`
  covers the hotspot subnet, otherwise Mainsail connects but cannot talk to Moonraker.
- Known trade-off: `nmcli connection add ... psk <password>` puts the password on the command line
  for the duration of that call (visible in the process list to local users). The backend interface
  allows swapping to a NetworkManager keyfile later without touching anything else.
- `HOTSPOT_CREDENTIALS` prints the password in the console, so it stays in the Mainsail console
  history. Acceptable on a machine where whoever has the console can already reach it; not
  acceptable to paste into a support chat.
- Passwords are redacted in backend errors, and `Credentials`/`HotspotSettings` have a `repr` that
  hides them. A test asserts the password never appears in captured logs.

## Failure modes

| Situation | Behaviour |
|---|---|
| NetworkManager down at daemon start | Logged, daemon stays up, state `off`; verbs retry the backend. |
| `nmcli connection up` fails | Profile removed, error returned (`backend_error`), state `off`. |
| `off` fails | State stays `on` (it really is), error returned. |
| Power cut during a switch | Profile is `autoconnect no`; after reboot the machine is on its normal Wi-Fi. |
| State file corrupt or unwritable | Ignored with a warning; state is rebuilt from the backend. |
| Config from a newer version | Refused with a clear message instead of misbehaving. |
| Reserved feature enabled early | Config error ("not implemented"), not a silent no-op. |
| Socket path occupied | Live daemon: refuse to start. Stale socket: replaced. Regular file: never deleted. |

## Testing strategy

| Layer | What | Where it runs |
|---|---|---|
| Unit | config, credentials, store, state table | CI |
| Manager | all behaviours above against `FakeBackend` | CI |
| Backend contract | one suite, three implementations: `FakeBackend`, `NmcliBackend` + simulated nmcli, `NmcliBackend` on a real Pi (`HOTSPOT_HW_TESTS=1`) | CI + Pi |
| API / CLI | request validation, error codes, real Unix socket round trips, permissions | CI |
| Doctor | Moonraker `trusted_clients` parsing against the MainsailOS default and custom lists | CI |

The simulated nmcli encodes *our assumptions* about nmcli's output. The hardware-gated contract
run is what checks those assumptions against the real thing, so run it on every new image.

## Roadmap and the seams that carry it

| Feature | Seam it plugs into | What changes |
|---|---|---|
| Automatic fallback (no Wi-Fi at boot) | `Policy` + new states | New `FallbackPolicy`, reads `[fallback]`; manager, API and macros untouched. |
| Do not switch while printing | `Policy` | Needs Moonraker print state; the macros already warn using Klipper's own `print_stats`. |
| Wi-Fi setup page (portal) | Control socket client | New process/page calling a new `scan`/`join` verb; protocol version stays 1 (new verbs are additive). |
| SSID/password shown on the screen (and a QR code) | `credentials` verb | Klipper action prompts for text, a KlipperScreen panel for a QR; no daemon change. |
| Password rotation | `credentials.py` | New verb and CLI command; creation already refuses to overwrite. |
| NetworkManager keyfile instead of argv password | `NetworkBackend` | Second implementation, same contract tests. |
| Config schema 2 | `config.py` | Add migration when `SUPPORTED_CONFIG_VERSION` goes to 2; today it only refuses newer versions. |

Rule for adding a seam: it must have a real implementation or a test double in the version that
introduces it. Placeholders for features nobody can specify yet are how rewrites start.

## Decisions

1. Hotspot is a manual mode; `autostart` defaults to off.
2. No hotspot + Ethernet scenario is supported or tested.
3. Python 3.9+, standard library only: nothing to `pip install` on the machines.
4. Program, macros, messages and docs are in English.
5. Control through a Unix socket, not through Moonraker, so the daemon works when Klipper or
   Moonraker are down, and every client is equal.
6. nmcli subprocess, not D-Bus bindings: easier to debug on a machine in the field.
7. Password never in `status`; explicit `credentials` verb instead.

## Must be verified on a real Pi before trusting it

- Raspberry Pi OS Bookworm with NetworkManager (not `dhcpcd`/`wpa_supplicant`).
- nmcli property names and output formats used by `NmcliBackend`.
- After `off`, NetworkManager reconnects to the known Wi-Fi by itself, and how long it takes.
- Wi-Fi regulatory country is set (`raspi-config`); otherwise the AP may not start or may be limited.
- `10.42.0.1` is reachable from iOS, Android and Windows, and Mainsail loads over it.
- Phones keep (or prompt to keep) a Wi-Fi network without internet.
- The hardening options in the systemd unit do not stop NetworkManager access.
- `gcode_shell_command` syntax and `verbose` output in the console.
- The KlipperScreen menu: syntax was checked against the KlipperScreen docs but never run on a screen;
  the icon name is an assumption. Pressing Status or Password runs a macro whose output goes to the
  console. Whether KlipperScreen shows it as a popup is unverified; the documented way to show text
  on the screen is Klipper action prompts (see the roadmap).
- The Pi 5 RTC battery, if clock accuracy matters without internet (no NTP in hotspot mode).
