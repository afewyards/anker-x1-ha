"""Tests for the restore work mode option, control read-back, watchdog and setpoint bounds.

Switching Modbus Control off writes the restore work mode option (default 20,
never VPP). 16 is the value the unit reports under Dynamic Tariff Mode on fw
1.0.19.16. The holding registers a caller needs to verify a write (10064 work
mode, 10071 setpoint, 10080 watchdog) are exposed read-only, and the setpoint
range comes from the nameplate registers 10124/10126.

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


def test_default_restore_mode_is_app_managed() -> None:
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


# ---------------------------------------------------------------------------
# Control read-back
# ---------------------------------------------------------------------------


def test_readback_offsets_in_block_e() -> None:
    src = (PKG / "coordinator.py").read_text()
    # Block E starts at 10060: 10071 -> e[11:13], 10080 -> e[20]
    assert "battery_setpoint: int = decode_i32_le(e[11:13])" in src
    assert "watchdog_s: int = decode_u16(e[20])" in src
    for key in ('"battery_setpoint"', '"watchdog_s"', '"last_poll"'):
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
    for key in ("work_mode", "battery_setpoint", "watchdog_s", "last_poll"):
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


def test_control_entities_are_disabled_by_default() -> None:
    expected = {
        "switch.py": {"AnkerX1Control"},
        "number.py": {"AnkerX1Setpoint", "AnkerX1ExportLimitValue", "AnkerX1ImportLimitValue"},
        "select.py": {"AnkerX1WorkMode", "AnkerX1ExportLimitMode", "AnkerX1ImportLimitMode"},
    }
    for name, classes in expected.items():
        tree = ast.parse((PKG / name).read_text())
        for cls in (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name in classes):
            flags = [
                n.value.value
                for n in cls.body
                if isinstance(n, ast.Assign)
                and any(getattr(t, "id", None) == "_attr_entity_registry_enabled_default" for t in n.targets)
            ]
            assert flags == [False], (name, cls.name)


# ---------------------------------------------------------------------------
# Setpoint bounds
# ---------------------------------------------------------------------------


def test_setpoint_bounds_decode_from_nameplate_with_fallback() -> None:
    b = [0] * 43  # Block B, base 10090
    b[34:38] = [12000, 0, 13200, 0]  # 10124 rated, 10126 max active power
    assert mc.decode_u32_le(b[34:36]) == 12000
    assert mc.decode_u32_le(b[36:38]) == 13200
    assert (mc.decode_u32_le([0, 0]) or const.MAX_CHARGE_W) == const.MAX_CHARGE_W
    src = (PKG / "coordinator.py").read_text()
    assert "decode_u32_le(b[34:36]) or MAX_CHARGE_W" in src
    assert "decode_u32_le(b[36:38]) or MAX_DISCHARGE_W" in src


def test_coordinator_clamps_to_nameplate_bounds() -> None:
    src = _function_source(PKG / "coordinator.py", "async_set_battery_power")
    assert "self.max_charge_w" in src and "self.max_discharge_w" in src
    assert "rechargeable_power" not in src and "dischargeable_power" not in src


def test_restore_mode_fallback() -> None:
    f = const.valid_restore_work_mode
    assert f(16) == 16 and f("0") == 0
    for bad in (None, "x", 3, "3", 99):
        assert f(bad) == const.DEFAULT_RESTORE_WORK_MODE
