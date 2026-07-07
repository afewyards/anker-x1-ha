"""DataUpdateCoordinator for Anker SOLIX X1.

ONE AsyncModbusTcpClient is shared for the lifetime of the config entry.
ALL register reads and writes are serialised through a single asyncio.Lock
because the device accepts only one TCP connection and corrupts responses
when requests interleave.

Register map summary
--------------------
Block A  read_input_registers(10000, count=40)  → addresses 10000-10039
Block B  read_input_registers(10090, count=30)  → addresses 10090-10119
Block C  read_input_registers(10156, count=60)  → addresses 10156-10215
Block D  read_input_registers(10750, count=8)   → addresses 10750-10757  (serial, cached)
Block E  read_holding_registers(10064, count=1) → address  10064          (work_mode)
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
            # Block B: input registers 10090-10119  (count=30)
            # ----------------------------------------------------------
            rr_b = await self._client.read_input_registers(
                10090, count=30, **self._unit_kwargs
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
            # Block E: holding register 10064 (work_mode)
            # ----------------------------------------------------------
            rr_e = await self._client.read_holding_registers(
                10064, count=1, **self._unit_kwargs
            )
            if rr_e.isError():
                raise UpdateFailed(f"Block E read failed: {rr_e}")
            e = rr_e.registers  # index 0 = address 10064

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
            # Decode Block A (base address 10000)
            # ----------------------------------------------------------
            # 10000  plant_status  u16
            plant_status: int = decode_u16(a[0])
            # 10001  battery_status  u16
            battery_status: int = decode_u16(a[1])
            # 10002-10003  pv_power  i32
            pv_power: int = decode_i32_le(a[2:4])
            # 10006-10007  ac_active_power  i32
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
            # 10030-10031  grid_bought_total  u32  (raw /10 kWh)
            grid_bought_total: float = decode_u32_le(a[30:32]) / 10.0
            # 10034-10035  grid_fed_in_total  u32  (raw /10 kWh)
            grid_fed_in_total: float = decode_u32_le(a[34:36]) / 10.0
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

            # ----------------------------------------------------------
            # Decode Block C (base address 10156)
            # ----------------------------------------------------------
            # 10156  inverter_temperature  i16  (/10 °C)
            inverter_temperature: float = decode_i16(c[0]) / 10.0
            # 10199  grid_voltage  u16  (/10 V)
            grid_voltage: float = decode_u16(c[43]) / 10.0
            # 10202  grid_voltage_l1  u16  (/10 V, line-to-neutral)
            grid_voltage_l1: float = decode_u16(c[46]) / 10.0
            # 10203  grid_voltage_l2  u16  (/10 V, line-to-neutral)
            grid_voltage_l2: float = decode_u16(c[47]) / 10.0
            # 10204  grid_voltage_l3  u16  (/10 V, line-to-neutral)
            grid_voltage_l3: float = decode_u16(c[48]) / 10.0
            # 10205  grid_current_l1  u16  (/100 A)
            grid_current_l1: float = decode_u16(c[49]) / 100.0
            # 10206  grid_current_l2  u16  (/100 A)
            grid_current_l2: float = decode_u16(c[50]) / 100.0
            # 10207  grid_current_l3  u16  (/100 A)
            grid_current_l3: float = decode_u16(c[51]) / 100.0
            # 10213  grid_frequency  u16  (/100 Hz)
            grid_frequency: float = decode_u16(c[57]) / 100.0

            # ----------------------------------------------------------
            # Decode Block E (base address 10064)
            # ----------------------------------------------------------
            work_mode: int = decode_u16(e[0])

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

            # When the user has declared no PV is connected, the Anker firmware
            # can still report phantom solar (grid-overflow misattributed to the
            # PV registers). Pin all PV-derived values to 0 first, so dashboards,
            # energy flows, and the conversion-loss balance below are not
            # polluted by spurious readings.
            if not self.pv_connected:
                pv_power = 0
                pv_energy_today = 0.0
                pv_energy_total = 0.0

            # --- Conversion loss + charge-power handling ------------------
            # The two supported topologies need different treatment.
            #
            # DC-coupled (PV wired into the Anker's MPPT, pv_connected=True):
            #   battery_power is accurate, and during ANY charging the firmware
            #   derives it so that (pv + grid_import) == charge + load exactly
            #   (verified on hardware: pv+battery-ac ~= 0 on solar charge;
            #   (pv+grid)-charge-load == 0 on grid charge). So no conversion loss
            #   is observable on the charge path and no charge-correction is
            #   needed -- battery_power is left raw. Loss is only measurable on
            #   discharge, where ac_active_power is an independent AC-side reading
            #   (~90% of the DC discharge). The DC power crossing the converter is
            #   (pv_power + battery_power), so any concurrent PV is included; with
            #   PV idle this reduces to battery_power - ac_active_power.
            #   => discharge-only.
            #
            # AC-coupled (no DC PV, pv_connected=False): keep the SoC-calibrated
            # behaviour tuned on that site (charge under-reported ~20%; mean of
            # battery/ac tracks true DC charge; loss = pv+battery-ac).
            if self.pv_connected:
                if battery_power > 0:  # discharging (possibly with concurrent PV)
                    inverter_loss = max(0, pv_power + battery_power - ac_active_power)
                else:  # charging or idle: loss not exposed by the registers
                    inverter_loss = 0
            else:
                # Charge-power correction. Applied BEFORE the loss balance so
                # charge_power / discharge_power follow from it automatically.
                # TODO: remove once Anker fixes the firmware register attribution.
                if battery_power < 0:  # charging
                    battery_power = -round(
                        (abs(battery_power) + abs(ac_active_power)) / 2
                    )
                # Inverter conversion loss = DC power in - useful AC power out.
                # PV and the battery share one PCS, so ac_active_power already
                # carries the PV contribution; the net DC crossing the converter
                # is (pv_power + battery_power) and the loss is that minus AC out.
                # backup_power is excluded (phantom/independent on AC-coupled).
                inverter_loss = max(0, pv_power + battery_power - ac_active_power)

                # In Standby/Sleep the converter is idle (battery_power = 0), so
                # no DC<->AC conversion and no loss. Guarded by pv_power == 0 so a
                # real array inverting to grid with the battery idle still reports
                # its loss.
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
            "grid_power": grid_power,
            "load_power": load_power,
            "pv_power": pv_power,
            "ac_active_power": ac_active_power,
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
            "grid_voltage": grid_voltage,
            "grid_voltage_l1": grid_voltage_l1,
            "grid_voltage_l2": grid_voltage_l2,
            "grid_voltage_l3": grid_voltage_l3,
            "grid_current_l1": grid_current_l1,
            "grid_current_l2": grid_current_l2,
            "grid_current_l3": grid_current_l3,
            "grid_frequency": grid_frequency,
            "inverter_temperature": inverter_temperature,
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
