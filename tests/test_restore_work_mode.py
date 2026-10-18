"""Tests for the configurable restore work mode, control read-back and watchdog.

A unit that the Anker app runs in Dynamic Tariff Mode reports work mode 16 on
fw 1.0.19.16. Switching Modbus Control off used to write a hard-coded 20
(App-managed), which is not the mode the unit came from. The restore mode is
now an option (default 20, unchanged behaviour), 16 is a known mode, and the
holding registers a caller needs to verify a write (10064 work mode, 10071
setpoint, 10080 watchdog) are exposed read-only.

Same constraint as the other test modules: `homeassistant` isn't installed,
so the HA-importing modules are checked by parsing the source with `ast`.
const.py and modbus_client.py have no HA dependency and are imported directly.
"""

from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PKG = REPO_ROOT / "custom_components" / "anker_x1"


def _import(name: str):
    spec = importlib.util.spec_from_file_location(f"anker_x1_{name}_under_test_restore", PKG / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


const = _import("const")
mc = _import("modbus_client")


def _function_source(path: Path, name: str) -> str:
    source = path.read_text()
    tree = ast.parse(source)
    node = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name
    )
    return ast.get_source_segment(source, node) or ""


# ---------------------------------------------------------------------------
# Work modes and the restore option
# ---------------------------------------------------------------------------


def test_dynamic_tariff_mode_is_known() -> None:
    assert const.WORK_MODE_DYNAMIC_TARIFF == 16
    assert const.WORK_MODE[16] == "Dynamic Tariff (app)"


def test_default_restore_mode_keeps_upstream_behaviour() -> None:
    assert const.DEFAULT_RESTORE_WORK_MODE == const.WORK_MODE_APP == 20


def test_select_exposes_dynamic_tariff() -> None:
    tree = ast.parse((PKG / "select.py").read_text())
    assign = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "_EXPOSED_MODE_KEYS" for t in n.targets)
    )
    keys = ast.literal_eval(assign.value)
    assert 16 in keys and 20 in keys
    assert all(k in const.WORK_MODE for k in keys)


def test_restore_writes_configured_mode_not_hardcoded_app() -> None:
    src = _function_source(PKG / "coordinator.py", "async_restore")
    assert "self.restore_work_mode" in src
    assert "WORK_MODE_APP" not in src
    # setpoint is still cleared before the mode is handed back
    assert src.index("10071") < src.index("self.restore_work_mode")


def test_restore_mode_reaches_the_coordinator() -> None:
    init_src = _function_source(PKG / "__init__.py", "async_setup_entry")
    assert "CONF_RESTORE_WORK_MODE" in init_src
    assert "restore_work_mode" in init_src


def test_options_flow_offers_restore_mode_and_stores_an_int() -> None:
    src = _function_source(PKG / "config_flow.py", "async_step_init")
    assert "CONF_RESTORE_WORK_MODE" in src
    assert "int(data[CONF_RESTORE_WORK_MODE])" in src


# ---------------------------------------------------------------------------
# Control read-back
# ---------------------------------------------------------------------------


def test_readback_offsets_in_block_e() -> None:
    src = (PKG / "coordinator.py").read_text()
    # Block E starts at 10060: 10071 -> e[11:13], 10080 -> e[20]
    assert "battery_setpoint: int = decode_i32_le(e[11:13])" in src
    assert "watchdog_s: int = decode_u16(e[20])" in src
    assert "read_holding_registers(\n                10060, count=21" in src
    for key in ('"battery_setpoint"', '"watchdog_s"', '"work_mode_code"', '"last_poll"'):
        assert key in src


def test_setpoint_readback_round_trips_the_written_words() -> None:
    for watts in (-6000, -1000, 0, 1000, 6600):
        assert mc.decode_i32_le(mc.le_words(watts)) == watts


def _sensor_keys() -> list[str]:
    tree = ast.parse((PKG / "sensor.py").read_text())
    keys: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg == "key" and isinstance(kw.value, ast.Constant):
                    keys.append(kw.value.value)
            # AnkerX1DailyEnergySensor(coordinator, entry, "<key>", "<name>", ...)
            if getattr(node.func, "id", None) == "AnkerX1DailyEnergySensor":
                keys.append(node.args[2].value)
    return keys


def test_sensor_unique_id_keys_are_unique() -> None:
    keys = _sensor_keys()
    assert len(keys) == len(set(keys)), sorted(k for k in keys if keys.count(k) > 1)


def test_readback_sensors_exist() -> None:
    keys = _sensor_keys()
    for key in ("work_mode", "work_mode_code", "battery_setpoint", "watchdog_s", "last_poll"):
        assert key in keys


# ---------------------------------------------------------------------------
# Watchdog service
# ---------------------------------------------------------------------------


def test_watchdog_bounds() -> None:
    assert const.WATCHDOG_REGISTER == 10080
    assert 0 < const.MIN_WATCHDOG_S < const.MAX_WATCHDOG_S


def test_set_watchdog_validates_and_writes_10080() -> None:
    src = _function_source(PKG / "coordinator.py", "async_set_watchdog")
    assert "MIN_WATCHDOG_S <= seconds <= MAX_WATCHDOG_S" in src
    assert "WATCHDOG_REGISTER" in src
    assert "self._lock" in src


def test_service_is_registered_and_described() -> None:
    init_src = (PKG / "__init__.py").read_text()
    assert 'SERVICE_SET_WATCHDOG = "set_watchdog"' in init_src
    assert "hass.services.async_register" in init_src
    services_yaml = (PKG / "services.yaml").read_text()
    assert services_yaml.startswith("set_watchdog:")
    for name in ("strings.json", "translations/en.json"):
        data = json.loads((PKG / name).read_text())
        assert set(data["services"]["set_watchdog"]["fields"]) == {"seconds", "config_entry_id"}
        assert "restore_work_mode" in data["options"]["step"]["init"]["data"]


def test_nothing_writes_outside_control_paths() -> None:
    """Writes only in the explicit async_set_*/engage/restore methods."""
    tree = ast.parse((PKG / "coordinator.py").read_text())
    for fn in (n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef)):
        src = ast.unparse(fn)
        if "write_register" in src:
            assert fn.name.startswith("async_set_") or fn.name in ("async_restore",), fn.name
