"""Number platform for Anker SOLIX X1 — battery power setpoint."""
from __future__ import annotations

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MAX_CHARGE_W, MAX_DISCHARGE_W


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Anker X1 number entity."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([AnkerX1Setpoint(coordinator, entry)])


class AnkerX1Setpoint(CoordinatorEntity, NumberEntity):
    """Battery power setpoint control.

    Negative values = charging (up to MAX_CHARGE_W).
    Positive values = discharging (up to MAX_DISCHARGE_W).
    """

    _attr_has_entity_name = True
    _attr_name = "Battery Setpoint (− charge / + discharge)"
    _attr_native_min_value = -MAX_CHARGE_W  # -6000 W
    _attr_native_max_value = MAX_DISCHARGE_W  # 6600 W
    _attr_native_step = 100
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_mode = NumberMode.SLIDER
    _attr_device_class = NumberDeviceClass.POWER
    _attr_icon = "mdi:battery-charging"
    _attr_extra_state_attributes = {
        "help": (
            "Requires 'Modbus Control' switch ON. "
            "Negative watts = charge, positive = discharge, 0 = idle. "
            "Clamped to ±6 kW; won't discharge at very low SOC."
        )
    }

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        """Initialise the entity."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_battery_setpoint"
        self._attr_device_info = coordinator.device_info

    @property
    def native_value(self) -> float | None:
        """Return current battery power (negative = charging)."""
        return self.coordinator.data.get("battery_power")

    async def async_set_native_value(self, value: float) -> None:
        """Set the battery power setpoint."""
        await self.coordinator.async_set_battery_power(int(value))
