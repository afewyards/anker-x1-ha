"""Daily trim of this entry's own recorder history."""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_time_change

_LOGGER = logging.getLogger(__name__)

# Only the ~1 Hz entities: purging by last_updated also deletes the sole row of
# constant entities (limits, diagnostics), emptying their history.
PURGE_KEYS = frozenset(
    {
        "inverter_loss",
        "inverter_temperature",
        "backup_power",
        "charge_power",
        "discharge_power",
        "battery_power",
        "rechargeable_power",
        "dischargeable_power",
        "battery_setpoint",
    }
)


def _is_high_rate(entry_id: str, unique_id: str | None) -> bool:
    if not unique_id or not unique_id.startswith(f"{entry_id}_"):
        return False
    key = unique_id[len(entry_id) + 1 :]
    return key.startswith("meter_") or key in PURGE_KEYS


def async_schedule_history_purge(
    hass: HomeAssistant, entry: ConfigEntry, keep_days: int
) -> None:
    """Purge recorder states older than keep_days every night at 04:30."""
    if keep_days <= 0:
        return

    async def _purge(_now) -> None:
        if not hass.services.has_service("recorder", "purge_entities"):
            return
        entity_ids = [
            e.entity_id
            for e in er.async_entries_for_config_entry(
                er.async_get(hass), entry.entry_id
            )
            if _is_high_rate(entry.entry_id, e.unique_id)
        ]
        if not entity_ids:
            return
        try:
            await hass.services.async_call(
                "recorder",
                "purge_entities",
                {"entity_id": entity_ids, "keep_days": keep_days},
                blocking=True,
            )
        except (HomeAssistantError, vol.Invalid) as err:
            _LOGGER.warning("Recorder history purge failed: %s", err)

    entry.async_on_unload(
        async_track_time_change(hass, _purge, hour=4, minute=30, second=0)
    )
