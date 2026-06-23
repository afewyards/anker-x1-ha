# Anker SOLIX X1 — Home Assistant Integration

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![Validate](https://github.com/afewyards/anker-x1-ha/actions/workflows/validate.yml/badge.svg)](https://github.com/afewyards/anker-x1-ha/actions/workflows/validate.yml)

Local **Modbus TCP** integration for the **Anker SOLIX X1** hybrid inverter /
battery (developed and tested on **X1-H12K-T**). No cloud, no internet — Home
Assistant talks directly to the unit on your LAN and exposes it as a single
**device** with monitoring sensors and write controls (charge / discharge /
idle, work-mode).

> Built by reverse-engineering the unit against Anker's *X1 Series Modbus
> Protocol V1.0.0* plus registers discovered on the device. The diagnostic
> scripts used to do that live in [`tools/`](tools/).

---

## Features

- **Local & cloud-free** — direct Modbus TCP, everything stays on your LAN.
- **One tidy device** with auto-detected model, firmware and serial.
- **Live monitoring** — power flow, SOC/SOH, grid voltage/frequency, inverter
  temperature, daily & lifetime energy.
- **Real control** — battery power setpoint, work-mode selection, and a master
  Modbus-control switch, with a comms watchdog as a safety net.
- **Derived metrics** computed in the integration — split charge/discharge
  power, true daily energy (reset at local midnight), and inverter consumption.
- **Version-proof** — auto-adapts to the pymodbus version Home Assistant ships
  (`slave=` vs `device_id=`).

## Requirements

- An Anker SOLIX X1 with **Modbus TCP enabled** — in the Anker Solix
  **Professional** app → *Communication Settings* → toggle **Modbus TCP** on.
- A wired LAN connection to the inverter is recommended.
- Home Assistant 2024.1 or newer.

## Installation

### HACS (recommended)

1. HACS → **Integrations** → ⋮ → **Custom repositories**.
2. Add `https://github.com/afewyards/anker-x1-ha`, category **Integration**.
3. Install **Anker SOLIX X1**, then restart Home Assistant.
4. **Settings → Devices & Services → Add Integration → "Anker SOLIX X1"** and
   enter the inverter's IP (port `502`, unit id `1` by default).

### Manual

Copy `custom_components/anker_x1/` into your HA `config/custom_components/`
directory and restart, then add the integration as in step 4 above.

## Entities

All entities live under one **Anker X1** device.

### Sensors — power (W)

| Entity | Notes |
| --- | --- |
| `battery_power` | + discharging / − charging |
| `charge_power` | unsigned charge power (0 when discharging) |
| `discharge_power` | unsigned discharge power (0 when charging) |
| `grid_power` | + import / − export |
| `load_power` | house load |
| `pv_power` | PV input |
| `ac_active_power` | PCS AC-side power (+ output / − absorbing) |
| `inverter_consumption` | derived self-use / losses (see below) |
| `rechargeable_power` / `dischargeable_power` | available headroom |

### Sensors — battery, grid, energy

| Entity | Unit | Notes |
| --- | --- | --- |
| `battery_soc` / `battery_soh` | % | |
| `grid_voltage` / `grid_frequency` | V / Hz | |
| `inverter_temperature` | °C | |
| `battery_charge_energy` / `battery_discharge_energy` | kWh | **daily, resets at local midnight** |
| `battery_charge_total` / `battery_discharge_total` | kWh | lifetime |
| `pv_energy_today` / `pv_energy_total` | kWh | |
| `grid_bought_total` / `grid_fed_in_total` | kWh | |
| `plant_status` / `battery_status` / `work_mode` | — | text |
| `model` / `serial` | — | diagnostic |

### Controls

| Entity | What it does |
| --- | --- |
| `switch` **Modbus Control** | ON hands the battery to HA (VPP mode); OFF returns it to the app |
| `number` **Battery Setpoint** | − = charge, + = discharge, 0 = idle (±6 kW) |
| `select` **Work Mode** | Self-consumption / VPP / App-managed |

## Control

The X1 only obeys external power commands once it's handed to Modbus, so control
is a two-step sequence the integration performs for you:

- **Modbus Control ON** → work mode `10064 = 3` (VPP/3rd-party), which unlocks
  the setpoint.
- **Battery Setpoint** → writes signed watts to `10071`: **negative = charge**,
  **positive = discharge**, **0 = idle**. Only honored while Modbus Control is
  ON. Clamped to ±6 kW (the inverter rating).
- **Modbus Control OFF** → writes `10071 = 0` then `10064 = 20`, returning
  control to the Anker app.

**Watchdog:** register `10080` reverts the inverter to self-consumption if HA
stops polling — a dead-man's switch, so a crash or removal can't leave the
battery stuck on a stale command. HA's 5 s polling keeps it fed.

At very low SOC the BMS sits in Standby and won't discharge regardless of
command.

## Derived metrics

- **`charge_power` / `discharge_power`** — the signed `battery_power` split into
  two unsigned sensors (handy for the Energy dashboard and automations).
- **`battery_charge_energy` / `battery_discharge_energy`** — true daily energy.
  The device's own "daily" registers don't reset on this firmware, so these are
  derived from the **lifetime totals** and reset at local midnight (the baseline
  is persisted across restarts and re-based if HA was off over midnight).
- **`inverter_consumption`** — conversion losses + the inverter's own draw,
  computed from the DC↔AC power balance. PV and battery share one PCS, so
  `ac_active_power` already carries the PV contribution and the net DC across
  the converter is `pv_power + battery_power`:
  - **base:** `pv_power + battery_power − ac_active_power`.
  - **charging** (`battery_power < 0`): also subtract `backup_power` — the AC
    side absorbs power that feeds both the battery and the backup load, and
    backup is a real load, not a conversion loss.
  - Floored at 0 (absorbs measurement noise). Reduces to
    `battery_power − ac_active_power` at night (`pv_power = 0`); with the **PV
    connected** option off, `pv_power` is pinned to 0 so it reduces to the same.
  - The PV term assumes `ac_active_power` already includes PV-sourced output
    (single shared PCS) — true for a hybrid inverter, but unvalidated on a
    PV-equipped unit here. If yours reports an implausibly large
    `inverter_consumption` while exporting solar, the register semantics differ;
    open an issue (or turn **PV connected** off as a workaround).

## Important: one Modbus client at a time

The X1 accepts **only one Modbus TCP connection at a time**. While this
integration is running, don't point other Modbus clients (the YAML `modbus:`
integration, the `tools/` scripts, a second Node-RED Modbus node) at the same
device — drive control by calling **this integration's entities/services**
instead.

## Calibration notes (for the curious)

- 32-bit registers use **little-endian word order** (low word first).
- Strings are **low-byte-first** within each register.
- Gains: voltage ÷10, current ÷100, frequency ÷100, temperature ÷10. Energy
  gains are **mixed** on this firmware (verified against the app + live deltas):
  PV and battery charge/discharge totals are ÷100, but grid bought/fed-in
  totals are ÷10.
- Grid voltage (`10199`) is **line-to-line** on three-phase units (~411 V);
  phase-to-neutral is that ÷√3 (~237 V).
- pymodbus renamed the per-call `slave=` kwarg to `device_id=` in 3.10; the
  integration detects which one the installed version uses at runtime.

## Options

After installation you can reconfigure the integration via **Settings →
Devices & Services → Anker SOLIX X1 → Configure**:

| Option | Default | Notes |
| --- | --- | --- |
| **Poll interval (seconds)** | 5 | How often to query the inverter over Modbus TCP (1–600 s). |
| **PV connected** | On | Turn **off** if your X1 has no PV strings attached. Some firmware builds misattribute grid overflow to the PV registers, producing phantom solar readings. When disabled, `pv_power`, `pv_energy_today`, and `pv_energy_total` are forced to 0; the sensor entities remain visible. |

## Troubleshooting

- **"Failed to connect over Modbus TCP"** — confirm Modbus TCP is enabled in the
  Professional app, the IP/port are right, and **nothing else holds the single
  Modbus connection** (stop the `tools/` scripts; remove any YAML `modbus:` hub
  pointed at the X1).
- **PV reads a phantom value** — on some units the device populates the PV
  register even with no/undetected strings (grid overflow misattributed as PV).
  Disable the **PV connected** option (Settings → Configure) to pin all
  PV-derived sensors to 0. This also keeps `inverter_consumption` honest: the
  loss balance includes `pv_power`, so pinning it to 0 stops the phantom value
  from leaking into the loss figure.

## `tools/`

Standalone, dependency-free Python diagnostics used to build this: `scan.py`
(register sweep), `dashboard.py` (live readout), `charge_test.py` (safe write
test), `x1_control.py` (discharge-on-need loop).

## Disclaimer

Not affiliated with or endorsed by Anker. Writing to undocumented/registers
controls real hardware — use at your own risk. The author accepts no liability
for damage or lost energy.

## License

[MIT](LICENSE)
