"""Anker SOLIX X1 Home Assistant integration.

Config-entry based; one coordinator (and one Modbus TCP connection) per entry.
Platform files (sensor, number, select, switch) each receive the coordinator
from hass.data[DOMAIN][entry.entry_id].
"""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
import homeassistant.helpers.config_validation as cv

from .const import (
    CONF_PV_CONNECTED,
    CONF_RESTORE_WORK_MODE,
    CONF_SLAVE,
    DEFAULT_PV_CONNECTED,
    DEFAULT_RESTORE_WORK_MODE,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SLAVE,
    DOMAIN,
    MAX_WATCHDOG_S,
    MIN_WATCHDOG_S,
    PLATFORMS,
)
from .coordinator import AnkerX1Coordinator

_LOGGER = logging.getLogger(__name__)

SERVICE_SET_WATCHDOG = "set_watchdog"
ATTR_SECONDS = "seconds"
ATTR_CONFIG_ENTRY_ID = "config_entry_id"

SET_WATCHDOG_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_SECONDS): vol.All(
            vol.Coerce(int), vol.Range(min=MIN_WATCHDOG_S, max=MAX_WATCHDOG_S)
        ),
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
    }
)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Register the integration-level services."""

    async def _async_set_watchdog(call: ServiceCall) -> None:
        coordinators: dict[str, AnkerX1Coordinator] = hass.data.get(DOMAIN, {})
        entry_id = call.data.get(ATTR_CONFIG_ENTRY_ID)
        if entry_id is not None:
            if entry_id not in coordinators:
                raise ServiceValidationError(f"No loaded Anker X1 entry {entry_id}")
            targets = [coordinators[entry_id]]
        elif len(coordinators) == 1:
            targets = list(coordinators.values())
        else:
            raise ServiceValidationError(
                "config_entry_id is required when zero or several X1 entries are loaded"
            )
        for coordinator in targets:
            await coordinator.async_set_watchdog(call.data[ATTR_SECONDS])

    hass.services.async_register(
        DOMAIN, SERVICE_SET_WATCHDOG, _async_set_watchdog, schema=SET_WATCHDOG_SCHEMA
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Anker SOLIX X1 from a config entry."""
    host: str = entry.data[CONF_HOST]
    port: int = entry.data[CONF_PORT]
    slave: int = entry.data.get(CONF_SLAVE, DEFAULT_SLAVE)
    scan_interval: int = entry.options.get(
        CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
    )
    pv_connected: bool = entry.options.get(CONF_PV_CONNECTED, DEFAULT_PV_CONNECTED)
    restore_work_mode: int = int(
        entry.options.get(CONF_RESTORE_WORK_MODE, DEFAULT_RESTORE_WORK_MODE)
    )

    coordinator = AnkerX1Coordinator(
        hass, host, port, slave, scan_interval, pv_connected, restore_work_mode
    )

    # Perform the first refresh; raises ConfigEntryNotReady on failure so HA
    # will retry automatically.
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Re-forward options updates (e.g. poll interval changes) if needed.
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle config entry option updates by reloading the entry."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry and close the Modbus connection."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        coordinator: AnkerX1Coordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_close()

    return unload_ok
