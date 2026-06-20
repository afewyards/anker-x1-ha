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
    DOMAIN,
    MAX_CHARGE_W,
    MAX_DISCHARGE_W,
    UPDATE_INTERVAL_SECONDS,
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
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"Anker X1 ({host}:{port})",
            update_interval=timedelta(seconds=UPDATE_INTERVAL_SECONDS),
        )
        self._host = host
        self._port = port
        self._slave = slave

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
            # Block G: PCS backup/EPS 10224-10239 (count=16)
            #   10233 backup active power i32
            # ----------------------------------------------------------
            rr_g = await self._client.read_input_registers(
                10224, count=16, **self._unit_kwargs
            )
            if rr_g.isError():
                raise UpdateFailed(f"Block G read failed: {rr_g}")
            g = rr_g.registers  # index 0 = address 10224

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
            # 10016-10017  pv_energy_today  u32  (raw /10 kWh)
            pv_energy_today: float = decode_u32_le(a[16:18]) / 10.0
            # 10018-10019  pv_energy_total  u32  (raw /10 kWh)
            pv_energy_total: float = decode_u32_le(a[18:20]) / 10.0
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

            # Inverter conversion loss = power in - useful power out.
            #
            # Sign convention: battery_power + discharge / - charge,
            # ac_active_power + AC output / - AC absorbed.
            #
            # Discharging (battery_power > 0): battery is the DC source, AC is
            #   measured after conversion and already contains the backup load,
            #   so loss = battery DC - AC out.
            # Charging (battery_power < 0): AC is the source (|ac| absorbed) and
            #   feeds both the battery (|battery|) AND the backup load, so
            #   loss = |ac| - |battery| - backup
            #        = battery_power - ac_active_power - backup_power.
            # Both reduce to (battery_power - ac_active_power), minus backup only
            # while charging. Floored at 0 to absorb measurement noise.
            inverter_loss = battery_power - ac_active_power
            if battery_power < 0:
                inverter_loss -= backup_power
            inverter_loss = max(0, inverter_loss)

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
            # Grid / environment (float, scaled)
            "grid_voltage": grid_voltage,
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
    # Control methods (all serialised; refresh coordinator after write)
    # ------------------------------------------------------------------

    async def async_set_battery_power(self, watts: int) -> None:
        """Set battery charge/discharge power target via VPP work mode.

        Positive watts = discharge, negative watts = charge.
        Values are clamped to the hardware limits defined in const.py.
        """
        watts = max(-MAX_CHARGE_W, min(MAX_DISCHARGE_W, watts))
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
