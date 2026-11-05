"""Tests for the nightly recorder-history purge.

`homeassistant` isn't installed, so history.py is imported against stubbed
modules.
"""

from __future__ import annotations

import ast
import asyncio
import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import voluptuous as vol

PKG = Path(__file__).resolve().parent.parent / "custom_components" / "anker_x1"


class _HAError(Exception):
    pass


def _load():
    track = MagicMock(return_value="unsub")
    registry = MagicMock()
    er = types.SimpleNamespace(
        async_get=lambda hass: "reg", async_entries_for_config_entry=registry
    )
    stubs = {
        "homeassistant": types.ModuleType("homeassistant"),
        "homeassistant.config_entries": types.SimpleNamespace(ConfigEntry=object),
        "homeassistant.core": types.SimpleNamespace(HomeAssistant=object),
        "homeassistant.exceptions": types.SimpleNamespace(HomeAssistantError=_HAError),
        "homeassistant.helpers": types.SimpleNamespace(entity_registry=er),
        "homeassistant.helpers.event": types.SimpleNamespace(
            async_track_time_change=track
        ),
    }
    with patch.dict(sys.modules, stubs):
        spec = importlib.util.spec_from_file_location(
            "anker_x1_history_under_test", PKG / "history.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module, track, registry


def _entities(*keys):
    return [
        types.SimpleNamespace(entity_id=f"sensor.{k}", unique_id=f"e1_{k}")
        for k in keys
    ]


_MIXED = (
    "meter_power_a",
    "battery_power",
    "battery_setpoint",
    "export_limit_value",
    "import_limit_value",
    "model",
    "soc",
    "pv_power",
)


def _setup(keep_days, has_service=True, call=None, keys=_MIXED):
    module, track, registry = _load()
    registry.return_value = _entities(*keys)
    hass = MagicMock()
    hass.services.has_service.return_value = has_service
    hass.services.async_call = call or AsyncMock()
    entry = MagicMock(entry_id="e1")
    module.async_schedule_history_purge(hass, entry, keep_days)
    return hass, entry, track


def test_zero_schedules_nothing() -> None:
    _, entry, track = _setup(0)
    track.assert_not_called()
    entry.async_on_unload.assert_not_called()


def test_purges_only_high_rate_entities() -> None:
    hass, entry, track = _setup(3)
    assert track.call_args.kwargs == {"hour": 4, "minute": 30, "second": 0}
    entry.async_on_unload.assert_called_once_with("unsub")
    asyncio.run(track.call_args.args[1](None))
    hass.services.async_call.assert_awaited_once_with(
        "recorder",
        "purge_entities",
        {
            "entity_id": [
                "sensor.meter_power_a",
                "sensor.battery_power",
                "sensor.battery_setpoint",
            ],
            "keep_days": 3,
        },
        blocking=True,
    )


def test_service_error_does_not_raise() -> None:
    _, _, track = _setup(2, call=AsyncMock(side_effect=_HAError("boom")))
    asyncio.run(track.call_args.args[1](None))


def test_missing_service_is_skipped() -> None:
    hass, _, track = _setup(2, has_service=False)
    asyncio.run(track.call_args.args[1](None))
    hass.services.async_call.assert_not_awaited()


def test_validation_error_does_not_raise() -> None:
    _, _, track = _setup(2, call=AsyncMock(side_effect=vol.Invalid("bad")))
    asyncio.run(track.call_args.args[1](None))


def test_empty_selection_skips_call() -> None:
    hass, _, track = _setup(2, keys=("export_limit_value", "soc"))
    asyncio.run(track.call_args.args[1](None))
    hass.services.async_call.assert_not_awaited()


def test_setup_entry_schedules_purge_with_option() -> None:
    source = (PKG / "__init__.py").read_text()
    tree = ast.parse(source)
    fn = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "async_setup_entry"
    )
    call = next(
        n
        for n in ast.walk(fn)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "async_schedule_history_purge"
    )
    assert "CONF_HISTORY_DAYS" in ast.unparse(call.args[2])
