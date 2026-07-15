"""Number platform for Anker SOLIX X1 — battery power setpoint."""
from __future__ import annotations

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Anker X1 number entity."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            AnkerX1Setpoint(coordinator, entry),
            AnkerX1ExportLimitValue(coordinator, entry),
            AnkerX1ImportLimitValue(coordinator, entry),
        ]
    )


class AnkerX1Setpoint(CoordinatorEntity, NumberEntity):
    """Battery power setpoint control.

    Negative values = charging, positive = discharging. The slider range
    follows the inverter's live limits (reg 10036/10038) via the coordinator.
    """

    _attr_has_entity_name = True
    _attr_name = "Battery Setpoint (− charge / + discharge)"
    _attr_native_step = 100
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_mode = NumberMode.SLIDER
    _attr_device_class = NumberDeviceClass.POWER
    _attr_icon = "mdi:battery-charging"
    _attr_extra_state_attributes = {
        "help": (
            "Requires 'Modbus Control' switch ON. "
            "Negative watts = charge, positive = discharge, 0 = idle. "
            "Clamped to the inverter's live charge/discharge limits; "
            "won't discharge at very low SOC."
        )
    }

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        """Initialise the entity."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_battery_setpoint"
        self._attr_device_info = coordinator.device_info

    @property
    def native_min_value(self) -> float:
        """Most-negative setpoint = max charge power, from the live limit."""
        return float(-self.coordinator.max_charge_w)

    @property
    def native_max_value(self) -> float:
        """Most-positive setpoint = max discharge power, from the live limit."""
        return float(self.coordinator.max_discharge_w)

    @property
    def native_value(self) -> float | None:
        """Return current battery power (negative = charging)."""
        return self.coordinator.data.get("battery_power")

    async def async_set_native_value(self, value: float) -> None:
        """Set the battery power setpoint."""
        await self.coordinator.async_set_battery_power(int(value))


class AnkerX1ExportLimitValue(CoordinatorEntity, NumberEntity):
    """Export power limit value control (reg 10075-10076).

    Meaning depends on the matching export_limit_mode register: percentage of
    rated power when mode=1, fixed watts when mode=2 (or disabled, mode=0).
    """

    _attr_has_entity_name = True
    _attr_name = "Export Limit"
    _attr_native_min_value = 0
    _attr_mode = NumberMode.BOX
    _attr_icon = "mdi:transmission-tower-export"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        """Initialise the entity."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_export_limit_value"
        self._attr_device_info = coordinator.device_info

    @property
    def native_unit_of_measurement(self) -> str:
        """Percent when mode=1 (percentage of rated power), else watts."""
        if self.coordinator.data.get("export_limit_mode") == 1:
            return PERCENTAGE
        return UnitOfPower.WATT

    @property
    def native_max_value(self) -> float:
        """100 when mode=1 (percentage of rated power), else 30000 W."""
        if self.coordinator.data.get("export_limit_mode") == 1:
            return 100
        return 30000

    @property
    def native_step(self) -> float:
        """1 when mode=1 (percentage of rated power), else 100 W."""
        if self.coordinator.data.get("export_limit_mode") == 1:
            return 1
        return 100

    @property
    def native_value(self) -> float | None:
        """Return the current export limit value."""
        return self.coordinator.data.get("export_limit_value")

    async def async_set_native_value(self, value: float) -> None:
        """Set the export limit value."""
        await self.coordinator.async_set_export_limit_value(int(value))


class AnkerX1ImportLimitValue(CoordinatorEntity, NumberEntity):
    """Import power limit value control (reg 10078-10079).

    Meaning depends on the matching import_limit_mode register: percentage of
    rated power when mode=1, fixed watts when mode=2 (or disabled, mode=0).
    """

    _attr_has_entity_name = True
    _attr_name = "Import Limit"
    _attr_native_min_value = 0
    _attr_mode = NumberMode.BOX
    _attr_icon = "mdi:transmission-tower-import"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        """Initialise the entity."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_import_limit_value"
        self._attr_device_info = coordinator.device_info

    @property
    def native_unit_of_measurement(self) -> str:
        """Percent when mode=1 (percentage of rated power), else watts."""
        if self.coordinator.data.get("import_limit_mode") == 1:
            return PERCENTAGE
        return UnitOfPower.WATT

    @property
    def native_max_value(self) -> float:
        """100 when mode=1 (percentage of rated power), else 30000 W."""
        if self.coordinator.data.get("import_limit_mode") == 1:
            return 100
        return 30000

    @property
    def native_step(self) -> float:
        """1 when mode=1 (percentage of rated power), else 100 W."""
        if self.coordinator.data.get("import_limit_mode") == 1:
            return 1
        return 100

    @property
    def native_value(self) -> float | None:
        """Return the current import limit value."""
        return self.coordinator.data.get("import_limit_value")

    async def async_set_native_value(self, value: float) -> None:
        """Set the import limit value."""
        await self.coordinator.async_set_import_limit_value(int(value))
