"""Select platform for Anker SOLIX X1 — work mode selection."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, LIMIT_MODE, WORK_MODE

# Expose the documented spec modes (0-5) plus the empirically-observed
# App-managed value (20) the device reports/accepts when under app control.
_EXPOSED_MODE_KEYS = (0, 1, 2, 3, 4, 5, 20)
_EXPOSED_OPTIONS: list[str] = [WORK_MODE[k] for k in _EXPOSED_MODE_KEYS]
_OPTION_TO_INT: dict[str, int] = {v: k for k, v in WORK_MODE.items()}

_LIMIT_MODE_OPTIONS: list[str] = list(LIMIT_MODE.values())
_LIMIT_MODE_OPTION_TO_INT: dict[str, int] = {v: k for k, v in LIMIT_MODE.items()}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Anker X1 select entity."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            AnkerX1WorkMode(coordinator, entry),
            AnkerX1ExportLimitMode(coordinator, entry),
            AnkerX1ImportLimitMode(coordinator, entry),
        ]
    )


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


class AnkerX1ExportLimitMode(CoordinatorEntity, SelectEntity):
    """Export power limit control mode selector (reg 10074)."""

    _attr_has_entity_name = True
    _attr_name = "Export Limit Mode"
    _attr_icon = "mdi:transmission-tower-export"
    _attr_options = _LIMIT_MODE_OPTIONS
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        """Initialise the entity."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_export_limit_mode"
        self._attr_device_info = coordinator.device_info

    @property
    def current_option(self) -> str | None:
        """Return the current export limit mode label, or None if unknown."""
        raw: int | None = self.coordinator.data.get("export_limit_mode")
        return LIMIT_MODE.get(raw)  # type: ignore[arg-type]

    async def async_select_option(self, option: str) -> None:
        """Set the export limit mode by label."""
        value = _LIMIT_MODE_OPTION_TO_INT[option]
        await self.coordinator.async_set_export_limit_mode(value)


class AnkerX1ImportLimitMode(CoordinatorEntity, SelectEntity):
    """Import power limit control mode selector (reg 10077)."""

    _attr_has_entity_name = True
    _attr_name = "Import Limit Mode"
    _attr_icon = "mdi:transmission-tower-import"
    _attr_options = _LIMIT_MODE_OPTIONS
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        """Initialise the entity."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_import_limit_mode"
        self._attr_device_info = coordinator.device_info

    @property
    def current_option(self) -> str | None:
        """Return the current import limit mode label, or None if unknown."""
        raw: int | None = self.coordinator.data.get("import_limit_mode")
        return LIMIT_MODE.get(raw)  # type: ignore[arg-type]

    async def async_select_option(self, option: str) -> None:
        """Set the import limit mode by label."""
        value = _LIMIT_MODE_OPTION_TO_INT[option]
        await self.coordinator.async_set_import_limit_mode(value)
