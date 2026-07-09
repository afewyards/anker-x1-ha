"""Select platform for Anker SOLIX X1 — work mode selection."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, WORK_MODE

# Expose the documented spec modes (0-5) plus the empirically-observed
# App-managed value (20) the device reports/accepts when under app control.
_EXPOSED_MODE_KEYS = (0, 1, 2, 3, 4, 5, 20)
_EXPOSED_OPTIONS: list[str] = [WORK_MODE[k] for k in _EXPOSED_MODE_KEYS]
_OPTION_TO_INT: dict[str, int] = {v: k for k, v in WORK_MODE.items()}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Anker X1 select entity."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([AnkerX1WorkMode(coordinator, entry)])


class AnkerX1WorkMode(CoordinatorEntity, SelectEntity):
    """Work mode selector — exposes all spec modes (0-5) plus App-managed (20)."""

    _attr_has_entity_name = True
    _attr_name = "Work Mode"
    _attr_icon = "mdi:home-battery"
    _attr_options = _EXPOSED_OPTIONS

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        """Initialise the entity."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_work_mode_select"
        self._attr_device_info = coordinator.device_info

    @property
    def current_option(self) -> str | None:
        """Return the current work mode label, or None if not in the exposed set."""
        raw: int | None = self.coordinator.data.get("work_mode")
        label = WORK_MODE.get(raw)  # type: ignore[arg-type]
        if label in _EXPOSED_OPTIONS:
            return label
        return None

    async def async_select_option(self, option: str) -> None:
        """Set the work mode by label."""
        value = _OPTION_TO_INT[option]
        await self.coordinator.async_set_work_mode(value)
