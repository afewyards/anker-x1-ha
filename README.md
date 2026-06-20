# Anker SOLIX X1 — Home Assistant Integration

A local **Modbus TCP** integration for the Anker SOLIX X1 hybrid inverter/battery
(tested on **X1-H12K-T**). No cloud, no internet — talks directly to the unit on
your LAN. Creates a proper **device** with monitoring sensors and write controls
(charge / discharge / idle, work mode).

> Built by reverse-engineering the device against Anker's published *X1 Series
> Modbus Protocol V1.0.0* plus discovered undocumented registers. See `tools/`.

## Features

- **Monitoring:** battery / grid / load / PV power, SOC, SOH, grid voltage &
  frequency, inverter temperature, daily & lifetime energy counters, plant /
  battery / work-mode status.
- **Control:** battery power setpoint (−6000 W charge … +6600 W discharge),
  work-mode selection, and a Modbus-control switch (engage VPP / restore app
  control).
- Single device card, auto-detected model/firmware/serial.

## Requirements

- Anker SOLIX X1 with **Modbus TCP enabled** (Anker Solix **Professional** app →
  Communication Settings → Modbus TCP toggle).
- Wired LAN recommended.

## Installation (HACS — custom repository)

1. HACS → Integrations → ⋮ → **Custom repositories** → add
   `https://github.com/afewyards/anker-x1-ha`, category **Integration**.
2. Install **Anker SOLIX X1**, restart Home Assistant.
3. Settings → Devices & Services → **Add Integration** → "Anker X1" → enter the
   device IP (port `502`, unit `1`).

## Important: one Modbus client only

The X1 accepts **only one Modbus TCP connection at a time**. While this
integration is running, don't point other Modbus clients (the YAML `modbus:`
integration, the `tools/` scripts, a second Node-RED Modbus node) at the same
device — drive control by **calling this integration's entities/services**
instead.

## Calibration notes (for the curious)

- 32-bit registers use **little-endian word order** (low word first).
- Strings are **low-byte-first** within each register.
- Gains: voltage ÷10, current ÷100, frequency ÷100, temperature ÷10, energy ÷10.
- Control: write `10064 = 3` (VPP/3rd-party) to unlock the setpoint at `10071`
  (signed int32 W: negative = charge, positive = discharge). Restore with
  `10064 = 20`. The VPP watchdog (`10080`) reverts the device if comms stop.

## `tools/`

Standalone, dependency-free Python diagnostics used to build this:
`scan.py` (register sweep), `dashboard.py` (live readout), `charge_test.py`
(safe write test), `x1_control.py` (discharge-on-need loop).

## License

MIT
