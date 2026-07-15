"""DataUpdateCoordinator for Anker SOLIX X1.

ONE AsyncModbusTcpClient is shared for the lifetime of the config entry.
ALL register reads and writes are serialised through a single asyncio.Lock
because the device accepts only one TCP connection and corrupts responses
when requests interleave.

Register map summary
--------------------
Block A  read_input_registers(10000, count=40)  → addresses 10000-10039
Block B  read_input_registers(10090, count=43)  → addresses 10090-10132
Block C  read_input_registers(10156, count=60)  → addresses 10156-10215
Block D  read_input_registers(10750, count=8)   → addresses 10750-10757  (serial, cached)
Block E  read_holding_registers(10060, count=21) → addresses 10060-10080  (work_mode, export/import power limit control)
Block M  read_input_registers(10620, count=47)  → addresses 10620-10666  (external meter, tolerant)
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from pymodbus.client import AsyncModbusTcpClient

from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    BATTERY_MODULE_KWH,
    BATTERY_STATUS,
    DEFAULT_PV_CONNECTED,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_CHARGE_W,
    MAX_DISCHARGE_W,
    WORK_MODE_APP,
    WORK_MODE_VPP,
)
from .modbus_client import (
    decode_i16,
    decode_i32_le,
    decode_string_lowbyte,
    decode_u16,
    decode_u32_le,
    le_words,
    unit_kwarg_name,
)

_LOGGER = logging.getLogger(__name__)


class AnkerX1Coordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinate polling and control for a single Anker SOLIX X1 unit."""

    def __init__(
        self,
        hass: HomeAssistant,
        host: str,
        port: int,
        slave: int,
        scan_interval: int = DEFAULT_SCAN_INTERVAL,
        pv_connected: bool = DEFAULT_PV_CONNECTED,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"Anker X1 ({host}:{port})",
            update_interval=timedelta(seconds=scan_interval),
        )
        self._host = host
        self._port = port
        self._slave = slave
        self.pv_connected: bool = pv_connected

        self._client: AsyncModbusTcpClient = AsyncModbusTcpClient(
            host=host,
            port=port,
        )
        # pymodbus <3.9 uses slave=, >=3.9 uses device_id=. Detect once.
        self._unit_kwargs: dict[str, int] = {unit_kwarg_name(self._client): slave}
        self._lock: asyncio.Lock = asyncio.Lock()

        # Cached device-identity fields (read once, then re-used).
        self.serial: str | None = None
        self.model: str | None = None
        self.sw_version: str | None = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _ensure_connected(self) -> None:
        """Connect the Modbus client if it is not already connected."""
        if not self._client.connected:
            connected = await self._client.connect()
            if not connected:
                raise UpdateFailed(
                    f"Cannot connect to Anker X1 at {self._host}:{self._port}"
                )

    # ------------------------------------------------------------------
    # DataUpdateCoordinator hook
    # ------------------------------------------------------------------

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch all live data from the inverter in one polling cycle."""
        async with self._lock:
            await self._ensure_connected()

            # ----------------------------------------------------------
            # Block A: input registers 10000-10039  (count=40)
            # ----------------------------------------------------------
            rr_a = await self._client.read_input_registers(
                10000, count=40, **self._unit_kwargs
            )
            if rr_a.isError():
                raise UpdateFailed(f"Block A read failed: {rr_a}")
            a = rr_a.registers  # index 0 = address 10000

            # ----------------------------------------------------------
            # Block B: input registers 10090-10132  (count=43)
            #   10132 output_mode  u16  (diagnostic)
            # ----------------------------------------------------------
            rr_b = await self._client.read_input_registers(
                10090, count=43, **self._unit_kwargs
            )
            if rr_b.isError():
                raise UpdateFailed(f"Block B read failed: {rr_b}")
            b = rr_b.registers  # index 0 = address 10090

            # ----------------------------------------------------------
            # Block C: input registers 10156-10215  (count=60)
            # ----------------------------------------------------------
            rr_c = await self._client.read_input_registers(
                10156, count=60, **self._unit_kwargs
            )
            if rr_c.isError():
                raise UpdateFailed(f"Block C read failed: {rr_c}")
            c = rr_c.registers  # index 0 = address 10156

            # ----------------------------------------------------------
            # Block D: serial string 10750-10757  (cached after first ok)
            # ----------------------------------------------------------
            if self.serial is None:
                rr_d = await self._client.read_input_registers(
                    10750, count=8, **self._unit_kwargs
                )
                if not rr_d.isError():
                    self.serial = decode_string_lowbyte(rr_d.registers)

            # ----------------------------------------------------------
            # Block E: holding registers 10060-10080  (work_mode, export/
            # import power limit control)
            # ----------------------------------------------------------
            rr_e = await self._client.read_holding_registers(
                10060, count=21, **self._unit_kwargs
            )
            if rr_e.isError():
                raise UpdateFailed(f"Block E read failed: {rr_e}")
            e = rr_e.registers  # index 0 = address 10060

            # ----------------------------------------------------------
            # Block F: battery energy totals 10258-10265 (count=8)
            #   10262 total charge energy u32, 10264 total discharge u32
            #   (lifetime, monotonic — daily values are derived in HA)
            # ----------------------------------------------------------
            rr_f = await self._client.read_input_registers(
                10258, count=8, **self._unit_kwargs
            )
            if rr_f.isError():
                raise UpdateFailed(f"Block F read failed: {rr_f}")
            f = rr_f.registers  # index 0 = address 10258

            # ----------------------------------------------------------
            # Block G: PCS backup/EPS + battery config 10224-10249 (count=26)
            #   10233 backup active power i32
            #   10249 battery module count   u16
            # ----------------------------------------------------------
            rr_g = await self._client.read_input_registers(
                10224, count=26, **self._unit_kwargs
            )
            if rr_g.isError():
                raise UpdateFailed(f"Block G read failed: {rr_g}")
            g = rr_g.registers  # index 0 = address 10224

            # ----------------------------------------------------------
            # Block H: battery pack voltage 10253  (tolerant: not all units
            # implement this register, so a failure here must not sink the
            # rest of the poll — mirrors the Block D serial-read pattern)
            # ----------------------------------------------------------
            rr_h = await self._client.read_input_registers(
                10253, count=1, **self._unit_kwargs
            )
            h = rr_h.registers if not rr_h.isError() else None  # index 0 = address 10253

            # ----------------------------------------------------------
            # Block M: input registers 10620-10666 (count=47) — external
            # CHINT 3-phase meter. Tolerant read (like Block H): not every
            # unit has a meter connected, so a failure here must not sink
            # the rest of the poll.
            # ----------------------------------------------------------
            rr_m = await self._client.read_input_registers(
                10620, count=47, **self._unit_kwargs
            )
            m = rr_m.registers if not rr_m.isError() else None  # index 0 = address 10620

            # ----------------------------------------------------------
            # Decode Block A (base address 10000)
            # ----------------------------------------------------------
            # 10000  plant_status  u16
            plant_status: int = decode_u16(a[0])
            # 10001  battery_status  u16
            battery_status: int = decode_u16(a[1])
            # 10002-10003  pv_power  i32  (internal only -- feeds total_pv for the
            # inverter_loss balance below; not exposed as a sensor)
            pv_power: int = decode_i32_le(a[2:4])
            # 10004-10005  third_party_pv  i32  (internal only -- externally-metered
            # 3rd-party PV, W; feeds total_pv for the inverter_loss balance below;
            # not exposed as a sensor)
            third_party_pv: int = decode_i32_le(a[4:6])
            # 10006-10007  ac_active_power  i32  (internal only -- feeds the
            # AC-coupled charge-power correction below; not exposed as a sensor)
            ac_active_power: int = decode_i32_le(a[6:8])
            # 10008-10009  battery_power  i32  (+ discharge / - charge)
            battery_power: int = decode_i32_le(a[8:10])
            # 10010-10011  load_power  i32
            load_power: int = decode_i32_le(a[10:12])
            # 10012-10013  grid_power  i32  (+ import / - export)
            grid_power: int = decode_i32_le(a[12:14])
            # 10014  soc  u16  (%)
            soc: int = decode_u16(a[14])
            # 10015  soh  u16  (%)
            soh: int = decode_u16(a[15])
            # 10016-10017  pv_energy_today  u32  (raw /100 kWh)
            pv_energy_today: float = decode_u32_le(a[16:18]) / 100.0
            # 10018-10019  pv_energy_total  u32  (raw /100 kWh)
            pv_energy_total: float = decode_u32_le(a[18:20]) / 100.0
            # 10022-10023  battery_charge_total  u32  (raw /100 kWh, lifetime)
            battery_charge_total: float = decode_u32_le(a[22:24]) / 100.0
            # 10030-10031  grid_bought_total  u32  (raw /100 kWh)
            # NOTE: gain is /100, same as every other energy reg here — the
            # official spec's "gain 10" column is wrong for energy on fw 1.0.16.
            # Ground-truthed 2026-07-09: raw 666 = 6.66 kWh (not 66.6).
            grid_bought_total: float = decode_u32_le(a[30:32]) / 100.0
            # 10034-10035  grid_fed_in_total  u32  (raw /100 kWh)
            grid_fed_in_total: float = decode_u32_le(a[34:36]) / 100.0
            # 10036-10037  rechargeable_power  i32  (W)
            rechargeable_power: int = decode_i32_le(a[36:38])
            # 10038-10039  dischargeable_power  i32  (W)
            dischargeable_power: int = decode_i32_le(a[38:40])

            # ----------------------------------------------------------
            # Decode Block B (base address 10090)
            # ----------------------------------------------------------
            # 10090-10099  model  string(10 regs)
            if self.model is None:
                self.model = decode_string_lowbyte(b[0:10])  # 10090-10099
            # 10112-10117  sw_version  string(6 regs)
            if self.sw_version is None:
                self.sw_version = decode_string_lowbyte(b[22:28])  # 10112-10117
            # 10132  output_mode  u16  (0=L/N, 1=L1/L2/L3/N)
            output_mode: int = decode_u16(b[42])

            # ----------------------------------------------------------
            # Decode Block C (base address 10156)
            # ----------------------------------------------------------
            # 10156  inverter_temperature  i16  (/10 °C)
            inverter_temperature: float = decode_i16(c[0]) / 10.0
            # PV strings: the official map (protocol V1.0.0 p.11) exposes
            # Voltage + Current per string ONLY -- 8 strings packed 2 registers
            # apart from 10167 -- with NO per-string power register. Derive
            # power as V*I. The spec declares these UINT16, but firmware
            # 1.0.16.1 emits small NEGATIVE two's-complement values at night
            # (MPPT ADC offset) -- decoding them unsigned wraps e.g. -0.07A
            # into 655.27A, producing phantom power. Decode signed and clamp
            # at zero: a PV string can't source negative current, and
            # legitimate values can't reach the i16 sign bit (max string
            # ~600V -> raw 6000; ~20A -> raw 2000). c index = addr - 10156.
            pv1_voltage: float = max(0.0, decode_i16(c[11]) / 10.0)   # 10167
            pv1_current: float = max(0.0, decode_i16(c[12]) / 100.0)  # 10168
            pv1_power: int = round(pv1_voltage * pv1_current)
            pv2_voltage: float = max(0.0, decode_i16(c[13]) / 10.0)   # 10169
            pv2_current: float = max(0.0, decode_i16(c[14]) / 100.0)  # 10170
            pv2_power: int = round(pv2_voltage * pv2_current)
            # 10183-10184  Total PV Power  i32 (W) -- the inverter's own DC PV
            # total across all strings; drives the user-facing "PV Power".
            total_pv_power: int = decode_i32_le(c[27:29])

            # ----------------------------------------------------------
            # Decode Block E (base address 10060)
            # ----------------------------------------------------------
            # 10064  work_mode  u16
            work_mode: int = decode_u16(e[4])
            # 10074  export_limit_mode  u16  (0=Disabled, 1=%, 2=Fixed power)
            export_limit_mode: int = decode_u16(e[14])
            # 10075-10076  export_limit_value  u32  (W when mode=2, % when mode=1)
            export_limit_value: int = decode_u32_le(e[15:17])
            # 10077  import_limit_mode  u16  (0=Disabled, 1=%, 2=Fixed power)
            import_limit_mode: int = decode_u16(e[17])
            # 10078-10079  import_limit_value  u32  (W when mode=2, % when mode=1)
            import_limit_value: int = decode_u32_le(e[18:20])

            # ----------------------------------------------------------
            # Decode Block F (base address 10258) — lifetime discharge total
            # 10264-10265 = f[6:8]
            # ----------------------------------------------------------
            battery_discharge_total: float = decode_u32_le(f[6:8]) / 100.0

            # Block G decode (base 10224) — backup active power 10233 = g[9:11]
            backup_power: int = decode_i32_le(g[9:11])

            # 10249 battery_module_count u16 = g[25]. The X1 reports the number
            # of installed 5 kWh modules here (verified: reads 2 with two
            # populated per-pack telemetry blocks; supports up to 6). Total
            # nominal capacity is simply that count x 5 kWh.
            battery_module_count: int = decode_u16(g[25])
            battery_nominal_capacity: float = (
                battery_module_count * BATTERY_MODULE_KWH
            )

            # 10253 battery_pack_voltage u16 (/10 V) = h[0]. Tolerant read
            # (Block H above) — None when the register isn't implemented.
            battery_pack_voltage: float | None = (
                decode_u16(h[0]) / 10.0 if h else None
            )

            # ----------------------------------------------------------
            # Decode Block M (base address 10620) — external meter.
            # Official layout (spec V1.0.0): 10620-10629 = meter model
            # string, 10630 = type (1=single/2=three-phase), 10631 =
            # status (0=normal/1=offline/3=fault). Data fields start at
            # 10632. Ground-truthed 2026-07-09 vs live CHINT 3φ meter.
            # ----------------------------------------------------------
            meter_type: int | None = decode_u16(m[10]) if m else None      # 10630
            meter_comm_status: int | None = decode_u16(m[11]) if m else None  # 10631
            meter_ok: bool = m is not None and meter_comm_status == 0

            meter_voltage_a: float | None = decode_u16(m[12]) / 10.0 if meter_ok else None   # 10632
            meter_voltage_b: float | None = decode_u16(m[13]) / 10.0 if meter_ok else None   # 10633
            meter_voltage_c: float | None = decode_u16(m[14]) / 10.0 if meter_ok else None   # 10634
            meter_current_a: float | None = decode_u16(m[15]) / 100.0 if meter_ok else None  # 10635
            meter_current_b: float | None = decode_u16(m[16]) / 100.0 if meter_ok else None  # 10636
            meter_current_c: float | None = decode_u16(m[17]) / 100.0 if meter_ok else None  # 10637
            meter_power_a: int | None = decode_i32_le(m[18:20]) if meter_ok else None        # 10638
            meter_power_b: int | None = decode_i32_le(m[20:22]) if meter_ok else None        # 10640
            meter_power_c: int | None = decode_i32_le(m[22:24]) if meter_ok else None        # 10642
            meter_total_power: int | None = decode_i32_le(m[24:26]) if meter_ok else None    # 10644
            meter_total_reactive: int | None = decode_i32_le(m[26:28]) if meter_ok else None  # 10646
            meter_power_factor: float | None = (
                decode_i16(m[28]) / 1000.0 if meter_ok else None                              # 10648
            )
            meter_frequency: float | None = decode_u16(m[29]) / 100.0 if meter_ok else None  # 10649
            meter_fwd_energy_total: float | None = (
                decode_u32_le(m[36:38]) / 100.0 if meter_ok else None                         # 10656
            )
            meter_rev_energy_total: float | None = (
                decode_u32_le(m[44:46]) / 100.0 if meter_ok else None                         # 10664
            )

            # When the user has declared no PV is connected, the Anker firmware
            # can still report phantom solar (grid-overflow misattributed to the
            # PV energy registers) and the PV string registers contain
            # uninitialised garbage. Pin everything to 0.
            if not self.pv_connected:
                pv_power = 0
                pv1_voltage = pv1_current = 0.0
                pv1_power = 0
                pv2_voltage = pv2_current = 0.0
                pv2_power = 0
                total_pv_power = 0
                pv_energy_today = 0.0
                pv_energy_total = 0.0

            # Gross PV power = sum of the per-string V*I values (0 on
            # AC-coupled). Distinct from `usable_pv_power` (reg 10183), the
            # inverter's post-MPPT harvested total, which reads lower.
            combined_pv_power: int = pv1_power + pv2_power

            # AC-coupled charge-power correction (no DC PV, pv_connected=False):
            # the firmware under-reports charge power on this topology; the
            # SoC-calibrated fix is to average it with the independent AC-side
            # reading (ac_active_power), which tracks true DC charge power more
            # closely. DC-coupled installs derive battery_power accurately from
            # the firmware directly, so no correction is applied there.
            # TODO: remove once Anker fixes the firmware register attribution.
            if not self.pv_connected and battery_power < 0:  # charging
                battery_power = -round(
                    (abs(battery_power) + abs(ac_active_power)) / 2
                )

            # --- Inverter conversion loss --------------------------------
            # DC power crossing the PCS minus useful AC power out. PV and the
            # battery share one converter, so ac_active_power already carries
            # the PV contribution and the net DC in is (total_pv + battery_power).
            # backup_power is excluded (phantom/independent on AC-coupled).
            # Validated against 6.5 days of logged data:
            #   - DC-coupled: only observable on discharge (~10% conversion
            #     loss); charge/idle is not exposed by the registers -> 0.
            #   - AC-coupled: uses the SoC-calibrated charge correction applied
            #     above; a true loss is only an upper bound here because the
            #     AC-coupled GoodWe poisons the balance (project note).
            total_pv: int = pv_power + third_party_pv
            if self.pv_connected:
                if battery_power > 0:  # discharging (possibly with concurrent PV)
                    inverter_loss = max(0, total_pv + battery_power - ac_active_power)
                else:  # charging or idle: loss not exposed by the registers
                    inverter_loss = 0
            else:
                inverter_loss = max(0, total_pv + battery_power - ac_active_power)
                # Standby/Sleep: converter idle, no conversion loss. Guarded by
                # pv_power == 0 so a real array inverting to grid with the
                # battery idle still reports its loss.
                if (
                    BATTERY_STATUS.get(battery_status) in ("Standby", "Sleep")
                    and pv_power == 0
                ):
                    inverter_loss = 0

        # Return the canonical data dict consumed by all platform entities.
        return {
            # Power (W, signed)
            "battery_power": battery_power,
            # Split unsigned charge/discharge power (W)
            "charge_power": max(0, -battery_power),
            "discharge_power": max(0, battery_power),
            "inverter_loss": inverter_loss,
            "backup_power": backup_power,
            "rechargeable_power": rechargeable_power,
            "dischargeable_power": dischargeable_power,
            # State of charge / health (%)
            "soc": soc,
            "soh": soh,
            # Battery pack configuration
            "battery_module_count": battery_module_count,
            "battery_nominal_capacity": battery_nominal_capacity,
            "battery_pack_voltage": battery_pack_voltage,
            # Grid / environment (float, scaled)
            "inverter_temperature": inverter_temperature,
            # PV: gross string sum + usable total (reg 10183) + per-string V*I
            # (all 0 on AC-coupled units with no DC PV)
            "pv_power": combined_pv_power,
            "usable_pv_power": total_pv_power,
            "pv1_power": pv1_power,
            "pv2_power": pv2_power,
            # Energy totals (kWh, float)
            "pv_energy_today": pv_energy_today,
            "pv_energy_total": pv_energy_total,
            "battery_charge_total": battery_charge_total,
            "battery_discharge_total": battery_discharge_total,
            "grid_bought_total": grid_bought_total,
            "grid_fed_in_total": grid_fed_in_total,
            # Status enums (raw int)
            "plant_status": plant_status,
            "battery_status": battery_status,
            "work_mode": work_mode,
            "output_mode": output_mode,
            "export_limit_mode": export_limit_mode,
            "export_limit_value": export_limit_value,
            "import_limit_mode": import_limit_mode,
            "import_limit_value": import_limit_value,
            # Meter block (external CHINT 3-phase meter; None when not present
            # or not communicating — see meter_ok gating above)
            "meter_comm_status": meter_comm_status,
            "meter_type": meter_type,
            "meter_total_power": meter_total_power,
            "meter_total_reactive": meter_total_reactive,
            "meter_fwd_energy_total": meter_fwd_energy_total,
            "meter_rev_energy_total": meter_rev_energy_total,
            # Device identity (str)
            "model": self.model or "",
            "serial": self.serial or "",
            "sw_version": self.sw_version or "",
        }

    # ------------------------------------------------------------------
    # Device info (used by all platform entities)
    # ------------------------------------------------------------------

    @property
    def device_info(self) -> DeviceInfo:
        """Return a DeviceInfo dict for the HA device registry."""
        identifier = self.serial or f"{self._host}:{self._port}"
        return DeviceInfo(
            identifiers={(DOMAIN, identifier)},
            manufacturer="Anker SOLIX",
            model=self.model or "X1",
            name="Anker X1",
            sw_version=self.sw_version,
            serial_number=self.serial,
            configuration_url="https://github.com/afewyards/anker-x1-ha#control",
        )

    # ------------------------------------------------------------------
    # Live hardware power limits (reg 10036 / 10038), const.py fallback
    # ------------------------------------------------------------------

    @property
    def max_charge_w(self) -> int:
        """Max charge power the inverter currently allows (W, positive)."""
        v = (self.data or {}).get("rechargeable_power")
        return v if isinstance(v, int) and v > 0 else MAX_CHARGE_W

    @property
    def max_discharge_w(self) -> int:
        """Max discharge power the inverter currently allows (W, positive)."""
        v = (self.data or {}).get("dischargeable_power")
        return v if isinstance(v, int) and v > 0 else MAX_DISCHARGE_W

    # ------------------------------------------------------------------
    # Control methods (all serialised; refresh coordinator after write)
    # ------------------------------------------------------------------

    async def async_set_battery_power(self, watts: int) -> None:
        """Set battery charge/discharge power target via VPP work mode.

        Positive watts = discharge, negative watts = charge. Clamped to the
        inverter's live limits (reg 10036/10038), falling back to the const.py
        defaults if those reads are unavailable.
        """
        watts = max(-self.max_charge_w, min(self.max_discharge_w, watts))
        async with self._lock:
            await self._ensure_connected()
            # Switch to VPP/3rd-party mode first.
            wr = await self._client.write_register(
                10064, WORK_MODE_VPP, **self._unit_kwargs
            )
            if wr.isError():
                raise RuntimeError(f"Failed to set VPP work mode: {wr}")
            # Write power setpoint as signed 32-bit LE at 10071.
            wr2 = await self._client.write_registers(
                10071, le_words(watts), **self._unit_kwargs
            )
            if wr2.isError():
                raise RuntimeError(f"Failed to write battery power setpoint: {wr2}")
        await self.async_request_refresh()

    async def async_set_work_mode(self, value: int) -> None:
        """Write a work-mode code to holding register 10064."""
        async with self._lock:
            await self._ensure_connected()
            wr = await self._client.write_register(10064, value, **self._unit_kwargs)
            if wr.isError():
                raise RuntimeError(f"Failed to write work mode {value}: {wr}")
        await self.async_request_refresh()

    async def async_set_export_limit_mode(self, mode: int) -> None:
        """Write the export power limit control mode to holding register 10074."""
        async with self._lock:
            await self._ensure_connected()
            wr = await self._client.write_register(10074, mode, **self._unit_kwargs)
            if wr.isError():
                raise RuntimeError(f"Failed to write export limit mode {mode}: {wr}")
        await self.async_request_refresh()

    async def async_set_export_limit_value(self, value: int) -> None:
        """Write the export power limit value as signed 32-bit LE at 10075."""
        async with self._lock:
            await self._ensure_connected()
            wr = await self._client.write_registers(
                10075, le_words(value), **self._unit_kwargs
            )
            if wr.isError():
                raise RuntimeError(f"Failed to write export limit value {value}: {wr}")
        await self.async_request_refresh()

    async def async_set_import_limit_mode(self, mode: int) -> None:
        """Write the import power limit control mode to holding register 10077."""
        async with self._lock:
            await self._ensure_connected()
            wr = await self._client.write_register(10077, mode, **self._unit_kwargs)
            if wr.isError():
                raise RuntimeError(f"Failed to write import limit mode {mode}: {wr}")
        await self.async_request_refresh()

    async def async_set_import_limit_value(self, value: int) -> None:
        """Write the import power limit value as signed 32-bit LE at 10078."""
        async with self._lock:
            await self._ensure_connected()
            wr = await self._client.write_registers(
                10078, le_words(value), **self._unit_kwargs
            )
            if wr.isError():
                raise RuntimeError(f"Failed to write import limit value {value}: {wr}")
        await self.async_request_refresh()

    async def async_engage(self) -> None:
        """Switch the inverter into VPP/3rd-party control mode."""
        await self.async_set_work_mode(WORK_MODE_VPP)

    async def async_restore(self) -> None:
        """Clear power setpoint and hand control back to the app."""
        async with self._lock:
            await self._ensure_connected()
            # Clear the power setpoint (write 0,0 to 10071).
            wr = await self._client.write_registers(
                10071, [0, 0], **self._unit_kwargs
            )
            if wr.isError():
                raise RuntimeError(f"Failed to clear power setpoint: {wr}")
            # Switch back to app-managed mode.
            wr2 = await self._client.write_register(
                10064, WORK_MODE_APP, **self._unit_kwargs
            )
            if wr2.isError():
                raise RuntimeError(f"Failed to restore app-managed mode: {wr2}")
        await self.async_request_refresh()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def async_close(self) -> None:
        """Close the Modbus TCP connection cleanly."""
        self._client.close()
