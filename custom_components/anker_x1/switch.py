"""Switch platform for Anker SOLIX X1 — Modbus control engagement."""
from __future__ import annotations

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, WORK_MODE_VPP


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Anker X1 switch entity."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([AnkerX1Control(coordinator, entry)])


class AnkerX1Control(CoordinatorEntity, SwitchEntity):
    """Modbus control switch.

    ON  → engage VPP/3rd-party mode (work_mode == WORK_MODE_VPP).
    OFF → restore previous / app-managed mode.
    """

    _attr_has_entity_name = True
    _attr_name = "Modbus Control"
    _attr_icon = "mdi:tune-vertical"
    _attr_device_class = SwitchDeviceClass.SWITCH

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        """Initialise the entity."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_modbus_control"
        self._attr_device_info = coordinator.device_info

    @property
    def is_on(self) -> bool:
        """Return True when the inverter is in VPP/3rd-party (Modbus-controlled) mode."""
        return self.coordinator.data.get("work_mode") == WORK_MODE_VPP

    async def async_turn_on(self, **kwargs) -> None:
        """Engage Modbus control (set VPP mode)."""
        await self.coordinator.async_engage()

    async def async_turn_off(self, **kwargs) -> None:
        """Restore previous mode (exit Modbus control)."""
        await self.coordinator.async_restore()
