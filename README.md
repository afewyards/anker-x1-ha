# Anker SOLIX X1 — Home Assistant Integration

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![Validate](https://github.com/afewyards/anker-x1-ha/actions/workflows/validate.yml/badge.svg)](https://github.com/afewyards/anker-x1-ha/actions/workflows/validate.yml)
[![Buy Me a Coffee](https://img.shields.io/badge/Buy%20Me%20a%20Coffee-ffdd00?logo=buymeacoffee&logoColor=black)](https://buymeacoffee.com/afewyards)

Local **Modbus TCP** integration for the **Anker SOLIX X1** hybrid inverter /
battery (developed and tested on **X1-H12K-T**). No cloud, no internet — Home
Assistant talks directly to the unit on your LAN and exposes it as a single
**device** with monitoring sensors and write controls (charge / discharge /
idle, work-mode).

> Built by reverse-engineering the unit against Anker's *X1 Series Modbus
> Protocol V1.0.0* plus registers discovered on the device, and ground-truthed
> against live hardware (X1-H12K-T, both DC- and AC-coupled). The diagnostic
> scripts used to do that live in [`tools/`](tools/).

---

## Features

- **Local & cloud-free** — direct Modbus TCP, everything stays on your LAN.
- **One tidy device** with auto-detected model, firmware and serial.
- **Live monitoring** — power flow, PV strings, SOC/SOH, pack voltage, inverter
  temperature, daily & lifetime energy, plus an optional external-meter block.
- **Real control** — battery power setpoint, work-mode selection, and a master
  Modbus-control switch, with the inverter's comms watchdog as a safety net.
- **Derived metrics** computed in the integration — split charge/discharge
  power, true daily energy (reset at local midnight), and inverter loss.
- **Topology-aware** — auto-adapts its charge-power and loss math to DC-coupled
  vs AC-coupled installs (see the **PV connected** option).
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

All entities live under one **Anker X1** device. The identifiers below are the
integration's internal keys — the entity's HA name (and hence its `entity_id`)
can differ, e.g. `grid_bought_total` shows as *Grid Bought Today*. Several
entities are marked **Diagnostic** and hidden by default; show them from the
device page.

### Sensors — power (W)

| Entity | Notes |
| --- | --- |
| `battery_power` | + discharging / − charging |
| `charge_power` | unsigned charge power (0 when discharging) |
| `discharge_power` | unsigned discharge power (0 when charging) |
| `pv_power` | gross DC PV = `pv1_power` + `pv2_power` (0 with no DC PV) |
| `usable_pv_power` | inverter's post-MPPT harvested PV total; ≤ `pv_power` at low irradiance |
| `pv1_power` / `pv2_power` | per-string DC power (V × I) |
| `backup_power` | EPS / backup-port load |
| `meter_total_power` | external CHINT meter total (only if a meter is wired) |
| `rechargeable_power` / `dischargeable_power` | live charge/discharge headroom (diagnostic) |
| `inverter_loss` | derived conversion loss (diagnostic — see below) |

### Sensors — battery, energy, status

| Entity | Unit | Notes |
| --- | --- | --- |
| `soc` / `soh` | % | state of charge / health (SOH is diagnostic) |
| `battery_pack_voltage` | V | pack DC voltage (reg 10253; unavailable if unimplemented) |
| `battery_module_count` | — | installed 5 kWh modules (diagnostic) |
| `battery_nominal_capacity` | kWh | `battery_module_count` × 5 kWh (diagnostic) |
| `inverter_temperature` | °C | diagnostic |
| `battery_charge_energy` / `battery_discharge_energy` | kWh | **daily, resets at local midnight** (derived) |
| `battery_charge_total` / `battery_discharge_total` | kWh | **lifetime** |
| `pv_energy_today` / `pv_energy_total` | kWh | daily / lifetime |
| `grid_bought_total` / `grid_fed_in_total` | kWh | **daily** device counters (named *Grid Bought/Fed-in Today*) |
| `meter_fwd_energy_total` / `meter_rev_energy_total` | kWh | lifetime, from the external meter (if present) |
| `meter_total_reactive` | var | external meter reactive power (diagnostic) |
| `plant_status` / `battery_status` | — | text enum |
| `output_mode` | — | wiring topology (L/N vs three-phase) — diagnostic |
| `meter_comm_status` | — | external meter link state — diagnostic |
| `model` / `serial` | — | diagnostic |

> **PV, meter and pack-voltage sensors** appear on every install but only carry
> real values when the corresponding hardware is present and detected. With no
> DC PV they read 0 (see the **PV connected** option); with no external CHINT
> meter the `meter_*` sensors stay unavailable.

### Controls

| Entity | What it does |
| --- | --- |
| `switch` **Modbus Control** | ON hands the battery to HA (VPP mode); OFF returns it to the app |
| `number` **Battery Setpoint** | − = charge, + = discharge, 0 = idle; range follows the inverter's live limits |
| `select` **Work Mode** | Self-consumption / Time-of-Use / Backup-only / VPP/3rd-party / User-defined / Socket-aggregation / App-managed |

## Home Assistant Energy dashboard

**Settings → Dashboards → Energy** expects `kWh` totals with the
`total_increasing` state class (all of the sensors below have it). Map the
dashboard fields to these sensors:

| Energy dashboard field | Sensor |
| --- | --- |
| **Grid consumption** (electricity grid → *consumed from grid*) | `grid_bought_total` |
| **Return to grid** (electricity grid → *returned to grid*) | `grid_fed_in_total` |
| **Solar production** | `pv_energy_total` |
| **Battery systems** → *energy going in to the battery* | `battery_charge_total` |
| **Battery systems** → *energy coming out of the battery* | `battery_discharge_total` |

The battery and solar fields use the **lifetime `*_total`** sensors — the
Energy dashboard buckets them into hours/days itself. The **grid** sensors
(`grid_bought_total` / `grid_fed_in_total`) are the device's own **daily**
counters that reset at local midnight; that's still fine here — the Energy
dashboard's `total_increasing` handling detects the daily reset and keeps the
running total correct. The derived daily `battery_charge_energy` /
`battery_discharge_energy` sensors are for cards and automations, not this
dashboard.

> **Have an external CHINT meter?** `meter_fwd_energy_total` /
> `meter_rev_energy_total` are **lifetime** grid totals and can be used for the
> grid fields instead of the daily device counters. Which one is *consumption*
> vs *return* depends on your meter's CT orientation — verify against a live
> import/export before committing the mapping.

When you add the battery, HA also offers an optional **Type of power
measurement** step for live monitoring. Choose **Standard** and set:

| Power-measurement field | Sensor |
| --- | --- |
| **Battery power** | `battery_power` |
| **Battery state of charge** | `soc` |

`battery_power` is signed **+ discharging / − charging**, which is exactly HA's
**Standard** polarity (positive = discharge, negative = charge) — leave it on
**Standard**, not Inverted. These two are optional; the kWh in/out totals above
are what actually drive the dashboard.

> **No PV / AC-coupled solar?** If your X1 doesn't measure PV (the **PV
> connected** option is off, or your panels feed the grid through a separate
> AC-coupled inverter), leave **Solar production** unset here and add that
> inverter as its own solar source — `pv_energy_total` would otherwise read 0
> (or a phantom value; see [Troubleshooting](#troubleshooting)).

## Control

The X1 only obeys external power commands once it's handed to Modbus, so control
is a two-step sequence the integration performs for you:

- **Modbus Control ON** → work mode `10064 = 3` (VPP/3rd-party), which unlocks
  the setpoint.
- **Battery Setpoint** → writes signed watts to `10071`: **negative = charge**,
  **positive = discharge**, **0 = idle**. Only honored while Modbus Control is
  ON. Clamped to the inverter's **live** charge/discharge limits (reg
  10036/10038), which default to −6 kW / +6.6 kW when a limit read is missing.
- **Modbus Control OFF** → writes `10071 = 0` then `10064 = 20`, returning
  control to the Anker app.

Selecting **VPP/3rd-party** on the Work Mode select is equivalent to turning
Modbus Control ON; any other mode hands the battery back to that mode's logic.

**Watchdog:** the inverter has a comms watchdog (register `10080`) that reverts
it to self-consumption if the Modbus master goes quiet — a dead-man's switch, so
a crash or removal can't leave the battery stuck on a stale command. HA's 1 s
polling keeps the link alive.

At very low SOC the BMS sits in Standby and won't discharge regardless of
command.

## Derived metrics

- **`charge_power` / `discharge_power`** — the signed `battery_power` split into
  two unsigned sensors (handy for the Energy dashboard and automations).
- **`battery_charge_energy` / `battery_discharge_energy`** — true daily energy.
  The device's own "daily" registers don't reset on this firmware, so these are
  derived from the **lifetime totals** and reset at local midnight (the baseline
  is persisted across restarts and re-based if HA was off over midnight).
- **`pv_power` vs `usable_pv_power`** — `pv_power` is the *gross* sum of the two
  DC strings (V × I per string). `usable_pv_power` is the inverter's own
  post-MPPT harvested total (reg 10183); it reads lower than the gross sum at
  low irradiance and is the steadier, more authoritative figure.
- **`inverter_loss`** — DC↔AC conversion loss + the converter's own draw,
  computed from the power balance `total_pv + battery_power − ac_active_power`,
  where `total_pv` folds in the inverter's PV registers (native PV plus any
  externally-metered 3rd-party PV — internal quantities, not their own sensors).
  PV and the battery share one PCS, so `ac_active_power` already carries the PV
  contribution.
  Floored at 0 to absorb measurement noise. The formula is **topology-aware**:
  - **DC-coupled** (PV connected): loss is only observable on **discharge**
    (~10% conversion loss, validated against logged data); the registers don't
    expose the charge/idle loss, so it reports **0** while charging or idle.
  - **AC-coupled** (**PV connected** off): the same balance, plus an SoC-
    calibrated charge-power correction (this firmware under-reports charge power
    on that topology), and forced to 0 in Standby/Sleep where the converter is
    idle. On AC-coupled sites the figure is an upper bound — a neighbouring
    AC-coupled solar inverter's export can poison the balance.

## Important: one Modbus client at a time

The X1 accepts **only one Modbus TCP connection at a time**. While this
integration is running, don't point other Modbus clients (the YAML `modbus:`
integration, the `tools/` scripts, a second Node-RED Modbus node) at the same
device — drive control by calling **this integration's entities/services**
instead.

## Calibration notes (for the curious)

- The little-word-first decode helpers apply **only to the native Anker
  register bank** (10000–11134): 32-bit registers use **little-endian word
  order** (low word first) and strings are **low-byte-first** within each
  register. The embedded SunSpec bank (10698+ / 40000+) uses the opposite,
  standard **big-word-first** order and is not touched by this integration.
- Gains: voltage ÷10, current ÷100, frequency ÷100, temperature ÷10. **All
  energy accumulators are ÷100** on this firmware (PV, battery charge/discharge,
  and grid bought/fed-in) — the official spec's "gain 10" column is wrong for
  the energy registers (ground-truthed 2026-07-09: raw 666 = 6.66 kWh).
- `battery_nominal_capacity` is `battery_module_count` (reg 10249) × 5 kWh, the
  per-module size of every Anker SOLIX X1 pack.
- pymodbus renamed the per-call `slave=` kwarg to `device_id=` in 3.10; the
  integration detects which one the installed version uses at runtime.

## Options

After installation you can reconfigure the integration via **Settings →
Devices & Services → Anker SOLIX X1 → Configure**:

| Option | Default | Notes |
| --- | --- | --- |
| **Poll interval (seconds)** | 1 | How often to query the inverter over Modbus TCP (1–600 s). |
| **PV connected** | On | Turn **off** if your X1 has no DC PV strings attached. Some firmware builds misattribute grid overflow to the PV registers (phantom solar), and the per-string registers hold garbage. When disabled, `pv_power`, `usable_pv_power`, `pv1_power`, `pv2_power`, `pv_energy_today`, and `pv_energy_total` are forced to 0; the sensor entities stay visible, and the loss/charge math switches to the AC-coupled branch. |

## Troubleshooting

- **"Failed to connect over Modbus TCP"** — confirm Modbus TCP is enabled in the
  Professional app, the IP/port are right, and **nothing else holds the single
  Modbus connection** (stop the `tools/` scripts; remove any YAML `modbus:` hub
  pointed at the X1).
- **PV reads a phantom value** — on some units the device populates the PV
  registers even with no/undetected strings (grid overflow misattributed as PV).
  Disable the **PV connected** option (Settings → Configure) to pin all
  PV-derived sensors to 0. This also keeps `inverter_loss` honest: the loss
  balance includes PV, so pinning it to 0 stops the phantom value from leaking
  into the loss figure.
- **`meter_*` sensors are unavailable** — expected unless an external CHINT
  3-phase meter is wired to the X1 and communicating (`meter_comm_status` =
  *Normal*).
- **`battery_pack_voltage` is unavailable** — some units don't implement
  register 10253; the rest of the poll is unaffected.

## `tools/`

Standalone, dependency-free Python diagnostics used to build this: `scan.py`
(register sweep), `dashboard.py` (live readout), `decode.py` (register decode
helpers), `charge_test.py` (safe write test), `x1_control.py`
(discharge-on-need loop), and `anker_sampler.py` + `sampler_watchdog.sh` (a
long-running CSV telemetry sampler for HAOS).

## Disclaimer

Not affiliated with or endorsed by Anker. Writing to undocumented registers
controls real hardware — use at your own risk. The author accepts no liability
for damage or lost energy.

## License

[MIT](LICENSE)
