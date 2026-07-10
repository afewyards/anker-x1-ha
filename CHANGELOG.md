# CHANGELOG


## v0.3.1 (2026-07-10)

### Bug Fixes

- **coordinator**: Correct PV string decode and add Usable PV Power
  ([`166136f`](https://github.com/afewyards/anker-x1-ha/commit/166136f80010bfb3aeccaa1048fa6c2e27e72ed8))

The shipped PV-string decode was wrong for real DC PV: per-string power was read as an i32 at
  10169/10170, but protocol V1.0.0 (p.11) defines those as PV2's voltage+current -- so pv1_power
  reported ~1e6 W of garbage on DC-coupled units (masked on AC-coupled, where strings pin to 0).

The map exposes per-string Voltage + Current only (8 strings, 2 registers apart from 10167); there
  is no per-string power register. Fixes: - pv1_power / pv2_power = V*I from the correct addresses
  (unsigned, so never negative -- supersedes the earlier clamp). - pv_power = gross sum of the
  strings (PV1 + PV2). - new "Usable PV Power" sensor = Total PV Power register 10183-10184, the
  inverter's post-MPPT harvested total (reads lower than the gross sum at low irradiance; steady and
  authoritative).

Ground-truthed against the France H12K-T under live sun: PV1 72W, PV2 40W, gross 112W, usable
  (10183) 89W.


## v0.3.0 (2026-07-09)

### Documentation

- **modbus**: Note native vs SunSpec register byte order
  ([`72bef55`](https://github.com/afewyards/anker-x1-ha/commit/72bef55bb92511929cf66b5ea864a5251220c107))

The little-word-first decode helpers apply only to the native Anker register bank (10000-11134). The
  embedded SunSpec bank (10698+ / 40000+) uses the opposite, standard big-word-first order and is
  not decoded by these helpers.

### Features

- **select**: Expose full spec work-mode range (0-5)
  ([`6f7eecf`](https://github.com/afewyards/anker-x1-ha/commit/6f7eecf84a5cbf4e9474d0293fdbdd8946e5b5d5))

Previously only modes 0, 3 and 20 were selectable. Expose all documented spec work modes (0-5)
  alongside the empirically-observed App-managed (20) value the device reports and accepts under app
  control.

- **sensor**: Add combined PV Power sensor and clamp PV strings
  ([`4e286a8`](https://github.com/afewyards/anker-x1-ha/commit/4e286a8140ee40c166edafadabf010095e60e8be))

Expose a user-facing "PV Power" sensor (key `pv_power`) sourced as the sum of the two DC strings,
  restoring the entity removed in the protocol V1.0.0 rework but now derived from pv1+pv2 rather
  than the internal register. The register-derived `pv_power` (10002-10003) is unchanged and still
  feeds the inverter_loss DC-balance.

Also clamp pv1_power / pv2_power to >= 0 at decode: PV strings are source-only, so any negative
  reading is register tearing / a glitch frame.

Reconcile test_gridpv.py with the shipped design: inverter_loss (a diagnostic sensor) and its
  total_pv intermediate are intentionally retained, not removed -- the earlier removal assertions
  were stale.

- **sensor**: Align register map and sensors with Modbus protocol V1.0.0
  ([`61a0475`](https://github.com/afewyards/anker-x1-ha/commit/61a04759ae40b1d9fac9594936226d5b96b8ecd9))

Rework the register map and exposed entities against Anker's official Modbus protocol V1.0.0,
  ground-truthed against live hardware on 2026-07-09.

Added: - 3rd-party PV power sensor (10004-10005) (#5) - Output Mode diagnostic enum (10132) (#8) -
  PV string 1/2 power sensors (10167-10180) (#16) - External CHINT 3-phase meter block (10620-10666,
  tolerant read): total/reactive power, forward/reverse energy, comm status, type (#4) -
  inverter_loss now folds third-party PV into the DC balance and drops the duplicated topology
  branch

Fixed: - grid_bought_total / grid_fed_in_total scale corrected from /10 to /100 (raw 666 = 6.66 kWh,
  not 66.6); these are daily counters, renamed to "Grid Bought/Fed-in Today"

Removed (unused, redundant, or wrongly-decoded per the protocol review): - grid_power, load_power,
  pv_power, ac_active_power (internal-only or redundant) (#18/#3) - grid_voltage,
  grid_voltage_l1/l2/l3, grid_current_l1/l2/l3, grid_frequency (#16/#17) - work_mode read-only enum
  sensor (writable Work Mode select remains)

BREAKING CHANGE: The following sensor entities are removed and any dashboards, automations, or
  Energy-dashboard configuration referencing them must be updated: grid_power, load_power, pv_power,
  ac_active_power, grid_voltage, grid_voltage_l1/l2/l3, grid_current_l1/l2/l3, grid_frequency, and
  the work_mode enum sensor. Additionally, grid_bought_total and grid_fed_in_total are rescaled by
  10x (now /100) and renamed to "Grid Bought Today" / "Grid Fed-in Today".

### Testing

- Add regression tests for protocol V1.0.0 sensor rework
  ([`cb49d66`](https://github.com/afewyards/anker-x1-ha/commit/cb49d667b15b59c165dc1ddaa3c5cc3d8daa2632))

homeassistant isn't installed locally (see pyproject.toml), so the structural claims are verified by
  parsing the source with ast; the dependency-free modbus_client decode helpers are exercised
  directly for behavioural coverage of the new register offsets.

- test_meter_block.py external meter block 10620-10666 (#4) - test_gridpv.py 3rd-party PV (#5) +
  output mode (#8) - test_grid_backup_pv.py PV strings + grid/backup detail removal (#16) -
  test_sensor_cleanup.py sensor cleanup batch (#18/#3/#17)


## v0.2.0 (2026-07-07)

### Bug Fixes

- **coordinator**: Topology-aware inverter loss for DC-coupled sites
  ([`ffbfcb2`](https://github.com/afewyards/anker-x1-ha/commit/ffbfcb28dd5ac0fb15c944628d2cc76398887acf))

On DC-coupled sites (pv_connected=True) the X1 firmware reports battery charge as (pv + grid_import)
  - load exactly, so charge-path conversion loss is not observable. The AC-coupled charge-power
  correction was corrupting battery_power (raw -3980 W reported as -2414 W) and inflating
  inverter_loss to a phantom ~1.3-2.6 kW, which also amplified jitter.

Branch the loss/charge logic on pv_connected: - DC-coupled: leave battery_power raw; inverter_loss
  is discharge-only, max(0, pv + battery - ac), and 0 while charging or idle. - AC-coupled
  (pv_connected=False): unchanged - charge-correction, loss formula, and Standby/Sleep guard
  preserved.

Bumps manifest to 0.1.10.

### Documentation

- Add Buy Me a Coffee badge
  ([`46a86b6`](https://github.com/afewyards/anker-x1-ha/commit/46a86b653a65696df82751152e7914add77cb66b))

### Features

- Add per-phase grid metering and battery pack voltage sensors
  ([`1deb36a`](https://github.com/afewyards/anker-x1-ha/commit/1deb36ad1b75a89eead9c07c5e1c927c74b5872d))

Expose 7 new sensors decoded from already-available Modbus registers: - grid_voltage_l1/l2/l3
  (line-to-neutral, 10202-10204, /10 V) - grid_current_l1/l2/l3 (per-phase, 10205-10207, /100 A) -
  battery_pack_voltage (10253, /10 V)

Per-phase grid data comes from the existing Block C read (no extra round-trip). Pack voltage uses a
  new tolerant read (Block H) so units that do not implement register 10253 report the sensor as
  unavailable rather than failing the entire poll. All decodes verified against live X1-H12K-T
  hardware.

- **tools**: Add HAOS Modbus sampler and watchdog
  ([`6099a2b`](https://github.com/afewyards/anker-x1-ha/commit/6099a2b6340ad40527f9580a5f56d72b873a2ee2))

Long-running Anker X1 Modbus TCP sampler (5s interval) that appends register telemetry to a CSV, now
  including SOH (reg 10015) and pack voltage (reg 10253) alongside the existing power/SOC fields.
  The watchdog auto-restarts the sampler if it dies. Both scripts run on HAOS under /share; tracked
  here for version history and recovery.


## v0.1.9 (2026-06-27)

### Features

- Derive battery setpoint range from live inverter limits
  ([`f840fe2`](https://github.com/afewyards/anker-x1-ha/commit/f840fe27ab1b6401ff795396d423e8a4b35baf59))

The forced charge/discharge setpoint range was hardcoded to 6000/6600 W. Drive it from the
  inverter's live limit registers instead: reg 10036 (rechargeable_power, max charge) and 10038
  (dischargeable_power, max discharge), exposed via new coordinator properties max_charge_w /
  max_discharge_w that fall back to the const.py defaults when a read is missing or zero. The number
  slider min/max now follow these per poll, and async_set_battery_power clamps to them, so the
  integration adapts to any X1 power class (and tracks the limit if it is dynamic BMS headroom).


## v0.1.8 (2026-06-26)

### Features

- Expose battery module count and nominal capacity
  ([`037625a`](https://github.com/afewyards/anker-x1-ha/commit/037625accf84b4f4e626632a8bf167f7be43de79))

Read register 10249 (battery module count) by extending the Block G input read from 16 to 26
  registers, and add two diagnostic sensors: "Battery Modules" (the count) and "Battery Nominal
  Capacity" (count x 5 kWh, the per-module size of every Anker SOLIX X1 pack). Verified against
  hardware: reg 10249 reads 2 with two populated per-pack telemetry blocks, giving 10 kWh.


## v0.1.7 (2026-06-26)

### Bug Fixes

- Zero inverter loss while battery is idle (standby/sleep)
  ([`15cfe15`](https://github.com/afewyards/anker-x1-ha/commit/15cfe1595b5a99dee63abef5dfe4a62e14b89bca))

In Standby/Sleep the battery converter is idle, so there is no DC<->AC conversion and no loss. The
  balance otherwise surfaced the inverter's AC-port self-consumption and, on AC-coupled sites, large
  phantom values when a neighbouring solar inverter's export flows past the idle port (measured
  ac_active down to -1718 W at rest). Force inverter_loss to 0 in those states, guarded by pv_power
  == 0 so a real PV array inverting to grid with the battery idle still reports its loss.

### Documentation

- Document Energy dashboard sensor mapping
  ([`72f54d3`](https://github.com/afewyards/anker-x1-ha/commit/72f54d37d050e190930db23d50199e3718440959))


## v0.1.6 (2026-06-25)

### Bug Fixes

- Base inverter loss on corrected charge and drop phantom backup
  ([`6e95e80`](https://github.com/afewyards/anker-x1-ha/commit/6e95e80939e673b439f89891cd7df3b3d7e5e56d))

Compute inverter_loss after the SoC charge correction so it uses the true DC power, and remove the
  backup_power term. On AC-coupled sites backup is a phantom reading (~330 W even at standby, and it
  exceeds the discharge it would supposedly feed), so it is not part of the converter DC<->AC
  throughput. Validated against a 7168-row SoC-anchored log: ~10% loss on discharge, ~20% apparent
  on solar charge, ~0 on grid charge.


## v0.1.5 (2026-06-25)

### Bug Fixes

- **coordinator**: Correct battery charge power during AC-coupled solar charging
  ([`bf66c7e`](https://github.com/afewyards/anker-x1-ha/commit/bf66c7ec424f92d13722759d907f4a7f5f145882))

Firmware under-reports battery charge power (reg 10008) by ~22% during AC-coupled solar charging
  while ac_active_power over-reports by ~22%. Averaging the two while charging recovers the true
  SoC-derived charge (validated within +-3% against a 9.79 kWh capacity calibrated from a controlled
  setpoint charge). Temporary workaround pending an Anker firmware fix.

### Chores

- Release v0.1.5
  ([`34ca2c1`](https://github.com/afewyards/anker-x1-ha/commit/34ca2c141259af577c6b4939c077f248efbb8925))


## v0.1.4 (2026-06-23)

### Bug Fixes

- Include PV power in inverter loss balance
  ([`6fda536`](https://github.com/afewyards/anker-x1-ha/commit/6fda53607b5008bd75615a4b87c3180a0d81c32e))

inverter_loss omitted pv_power, so on PV-equipped units the daytime balance went negative and
  floored to 0 -- real conversion losses read as zero whenever solar was producing. Add the PV term:
  pv_power + battery_power - ac_active_power (minus backup while charging). PV and battery share one
  PCS, so ac_active_power already carries PV. Move the PV-zeroing block ahead of the calc so the
  no-PV ("PV connected" off) path reduces to the prior battery-only formula unchanged.

### Chores

- Release v0.1.4
  ([`02a36d9`](https://github.com/afewyards/anker-x1-ha/commit/02a36d9c0f016b1de251e5b86d18996ace7bdb69))

### Features

- Add PV-connected option to suppress phantom solar
  ([`09b4866`](https://github.com/afewyards/anker-x1-ha/commit/09b4866866f1b053047ff151733fc8dd76cce9c0))

Some X1 units have no PV strings attached, yet the firmware reports phantom solar (grid overflow
  misattributed to the PV registers). Add a "PV connected" options-flow toggle (default on); when
  turned off the coordinator pins pv_power, pv_energy_today and pv_energy_total to 0. The sensor
  entities remain (pinned to 0, not hidden). inverter_loss is unchanged -- it derives from the
  battery/AC balance and excludes PV.


## v0.1.3 (2026-06-21)

### Chores

- Release v0.1.3
  ([`fa6fb22`](https://github.com/afewyards/anker-x1-ha/commit/fa6fb2272df43c7f5f3cedd524c1aff0167bd571))

### Features

- Make Modbus poll interval configurable via options flow
  ([`7bd5287`](https://github.com/afewyards/anker-x1-ha/commit/7bd52872f977026b70c716f015ad43a4d28e0e7c))

Add an OptionsFlow so the poll rate can be changed from the integration UI (1-600s, default 5)
  instead of editing const.py. The coordinator now takes the interval from entry options and HA
  reloads the entry on change.


## v0.1.2 (2026-06-20)

### Bug Fixes

- Correct battery energy total scale (/100) and inverter loss while charging
  ([`32f41c1`](https://github.com/afewyards/anker-x1-ha/commit/32f41c1d001243c103d09349387d847a954e8bf6))

- battery_charge_total / battery_discharge_total used /10 but the device reports these lifetime
  accumulators at /100 (confirmed against the app: ~228/~327 kWh). Daily derived sensors self-rebase
  across the change. - inverter_loss was hardcoded to 0 while charging. Add the charge-side power
  balance: |ac| - |battery| - backup, so loss is reported in both directions. Floored at 0.

- Correct PV energy total scale (/100) and document mixed energy gains
  ([`8aa67df`](https://github.com/afewyards/anker-x1-ha/commit/8aa67df3fd490b4e2df53811a27f4f05e687592a))

PV today/total used /10 but the device reports them at /100 (confirmed against the app, same as the
  battery accumulators). Grid bought/fed stay at /10 — verified by live import deltas, not all
  accumulators share a gain on this firmware. README notes the mixed gains and that grid voltage
  10199 is line-to-line on three-phase units.

### Chores

- Release v0.1.2
  ([`d05f88e`](https://github.com/afewyards/anker-x1-ha/commit/d05f88e0748a7f8e27aa7b77de96845b86716a8b))


## v0.1.1 (2026-06-20)

### Chores

- Release v0.1.1
  ([`d1eb2e9`](https://github.com/afewyards/anker-x1-ha/commit/d1eb2e971d8b6ab934f96c13d7005212e472b86d))

Backup Power sensor, Inverter Loss (discharge-only), daily charge/discharge energy, control help
  labels, pymodbus 3.10 device_id compatibility.

### Features

- Add backup power sensor; rename inverter loss; fix CI
  ([`ecd5389`](https://github.com/afewyards/anker-x1-ha/commit/ecd538961115bac845e5e3d819d24ec97e94acec))

Add Backup Power sensor (reg 10233). Rename Inverter Consumption -> Inverter Loss (it measures
  discharge-side conversion loss; charge-side isn't isolable since ac_active bundles load-serving +
  backup, verified on hardware). Sort manifest keys (hassfest) and ignore brands in HACS validation
  (custom repo).


## v0.1.0 (2026-06-20)

### Bug Fixes

- Support pymodbus 3.9+ device_id kwarg
  ([`050688b`](https://github.com/afewyards/anker-x1-ha/commit/050688b99a6aed4c59e75343d7c19b6134be3f19))

HA 2026.x ships pymodbus >=3.9 which renamed the per-call slave= kwarg to device_id=, causing
  'unexpected keyword argument slave' at config-flow validation. Detect the correct kwarg at runtime
  from the client signature so the integration works across pymodbus versions. Verified live: config
  entry created, all sensors/controls reporting on an X1-H12K-T.

### Documentation

- Comprehensive README and HACS validation workflow
  ([`5048536`](https://github.com/afewyards/anker-x1-ha/commit/5048536f7cd43257e1cea538ff46fe012ac47127))

Full README (features, entities, control, derived metrics, troubleshooting) and a CI workflow
  running HACS Action + hassfest.

### Features

- Add Anker SOLIX X1 Home Assistant integration
  ([`eac12ee`](https://github.com/afewyards/anker-x1-ha/commit/eac12eea349e1572f70554173c2bd10cf4a268c5))

Local Modbus TCP integration (config flow, device, sensors, controls) for the Anker SOLIX X1 hybrid
  inverter/battery. Includes a DataUpdateCoordinator with single-client serialization and
  little-endian word-order decoding, charge/discharge/idle setpoint, work-mode select, control
  switch, and the reverse-engineering tools under tools/.

- Add derived sensors and control help labels
  ([`7f35e0f`](https://github.com/afewyards/anker-x1-ha/commit/7f35e0fd3efb4c3a790895373cc8b4ce0329f71d))

Split charge/discharge power sensors; true daily charge/discharge energy derived from lifetime
  totals with a midnight reset that survives restarts; inverter consumption (battery - AC active, PV
  excluded); embed control explanations in entity names and add a device configuration_url.
