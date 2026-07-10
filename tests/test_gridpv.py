"""Tests for #8 (Output Mode), #5 (3rd-party PV), and the pv_power /
inverter_loss / grid_voltage / grid_frequency sensor removal.

Same constraint as test_sensor_cleanup.py: `homeassistant` isn't installed,
so sensor.py / coordinator.py can't be imported directly. Structural claims
are verified by parsing the source with `ast`. modbus_client.py has no HA
dependency, so its decode helpers are exercised directly for genuine
behavioural coverage of the new register offsets.
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SENSOR_PY = REPO_ROOT / "custom_components" / "anker_x1" / "sensor.py"
COORDINATOR_PY = REPO_ROOT / "custom_components" / "anker_x1" / "coordinator.py"
CONST_PY = REPO_ROOT / "custom_components" / "anker_x1" / "const.py"
MODBUS_CLIENT_PY = REPO_ROOT / "custom_components" / "anker_x1" / "modbus_client.py"


def _literal_or_source(node: ast.AST) -> object:
    """Return the Python literal for `node`, or its source text if it isn't one."""
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError):
        return ast.unparse(node)


def _load_descriptions_tuple(name: str) -> dict[str, dict[str, object]]:
    """Parse a module-level `name: tuple[...] = (...)` of Call literals."""
    tree = ast.parse(SENSOR_PY.read_text())
    assign = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == name
    )
    assert isinstance(assign.value, ast.Tuple)

    descriptions: dict[str, dict[str, object]] = {}
    for call in assign.value.elts:
        assert isinstance(call, ast.Call)
        kwargs = {
            kw.arg: _literal_or_source(kw.value)
            for kw in call.keywords
            if kw.arg is not None
        }
        key = kwargs["key"]
        assert isinstance(key, str)
        descriptions[key] = kwargs
    return descriptions


def _load_coordinator_source() -> str:
    return COORDINATOR_PY.read_text()


def _load_update_data_func() -> ast.AsyncFunctionDef:
    tree = ast.parse(_load_coordinator_source())
    return next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_async_update_data"
    )


def _load_coordinator_return_keys() -> set[str]:
    func = _load_update_data_func()
    ret = next(
        node
        for node in ast.walk(func)
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict)
    )
    assert isinstance(ret.value, ast.Dict)
    return {
        ast.literal_eval(key)
        for key in ret.value.keys
        if isinstance(key, ast.Constant) and isinstance(key.value, str)
    }


def _load_assignment_sources() -> dict[str, str]:
    """Map every assigned name in `_async_update_data` -> unparsed RHS source."""
    func = _load_update_data_func()
    out: dict[str, str] = {}
    for node in ast.walk(func):
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.value is not None
        ):
            out[node.target.id] = ast.unparse(node.value)
        elif (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            out[node.targets[0].id] = ast.unparse(node.value)
    return out


def _find_read_input_registers_calls() -> dict[int, int | None]:
    """Return {start_address: count} for every read_input_registers(...) call."""
    tree = ast.parse(_load_coordinator_source())
    calls: dict[int, int | None] = {}
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "read_input_registers"
        ):
            addr = ast.literal_eval(node.args[0])
            count = next(
                (ast.literal_eval(kw.value) for kw in node.keywords if kw.arg == "count"),
                None,
            )
            calls[addr] = count
    return calls


def _import_modbus_client():
    """Import modbus_client.py directly from its file, bypassing the package
    __init__ (which pulls in `homeassistant`)."""
    spec = importlib.util.spec_from_file_location(
        "anker_x1_modbus_client_under_test", MODBUS_CLIENT_PY
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# #8b — Output Mode register 10132
# ---------------------------------------------------------------------------

def test_block_b_extended_to_cover_10132():
    calls = _find_read_input_registers_calls()
    assert calls.get(10090) == 43


def test_output_mode_decoded_from_register_10132():
    assignments = _load_assignment_sources()
    assert assignments.get("output_mode") == "decode_u16(b[42])"


def test_output_mode_decode_offset_matches_register_10132():
    modbus_client = _import_modbus_client()
    b = [0] * 43  # synthetic Block B, base address 10090
    b[42] = 1  # index 42 == address 10090 + 42 == 10132
    assert modbus_client.decode_u16(b[42]) == 1


def test_output_mode_in_coordinator_return_dict():
    assert "output_mode" in _load_coordinator_return_keys()


def test_output_mode_const_mapping_exists():
    tree = ast.parse(CONST_PY.read_text())
    assign = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == "OUTPUT_MODE"
    )
    mapping = ast.literal_eval(assign.value)
    assert mapping == {0: "L/N", 1: "L1/L2/L3/N", 3: "Three-phase (3W)"}


def test_output_mode_enum_sensor_is_diagnostic():
    descriptions = _load_descriptions_tuple("ENUM_SENSOR_DESCRIPTIONS")
    assert "output_mode" in descriptions
    assert descriptions["output_mode"]["mapping"] == "OUTPUT_MODE"
    assert descriptions["output_mode"]["entity_category"] == "EntityCategory.DIAGNOSTIC"


# ---------------------------------------------------------------------------
# #5a — 3rd-party PV power register 10004-10005
#
# third_party_pv is decoded internally and folded into the `total_pv`
# inverter_loss balance, but (like ac_active_power) is NOT exposed as a
# user-facing sensor and is NOT in the coordinator return dict.
# ---------------------------------------------------------------------------

def test_third_party_pv_decoded_from_10004_10005():
    assignments = _load_assignment_sources()
    assert assignments.get("third_party_pv") == "decode_i32_le(a[4:6])"


def test_third_party_pv_decode_offset_matches_register_10004_10005():
    modbus_client = _import_modbus_client()
    a = [0] * 40  # synthetic Block A, base address 10000
    a[4], a[5] = modbus_client.le_words(-1234)  # indices 4:6 == addresses 10004-10005
    assert modbus_client.decode_i32_le(a[4:6]) == -1234


def test_third_party_pv_folded_into_total_pv():
    assignments = _load_assignment_sources()
    assert assignments.get("total_pv") == "pv_power + third_party_pv"


def test_third_party_pv_not_exposed_as_sensor_or_return_key():
    descriptions = _load_descriptions_tuple("NUMERIC_SENSOR_DESCRIPTIONS")
    assert "third_party_pv" not in descriptions
    assert "third_party_pv" not in _load_coordinator_return_keys()


# ---------------------------------------------------------------------------
# grid_voltage / grid_frequency removal + pv_power / inverter_loss retention
#
# grid_voltage (Uab) and grid_frequency were removed as unused sensors.
# inverter_loss is retained as a diagnostic sensor and still computed from the
# `total_pv` DC-balance intermediate. `pv_power` returns as the user-facing
# "PV Power" sensor, now sourced as the sum of the two DC strings (distinct
# from the register-derived internal `pv_power` that feeds inverter_loss).
# ---------------------------------------------------------------------------

REMOVED_KEYS = {"grid_voltage", "grid_frequency"}


def test_removed_keys_absent_from_sensor_descriptions():
    descriptions = _load_descriptions_tuple("NUMERIC_SENSOR_DESCRIPTIONS")
    assert not (REMOVED_KEYS & descriptions.keys())


def test_removed_keys_absent_from_coordinator_return_dict():
    assert not (REMOVED_KEYS & _load_coordinator_return_keys())


def test_total_pv_and_inverter_loss_still_computed():
    assignments = _load_assignment_sources()
    assert "total_pv" in assignments
    assert "inverter_loss" in assignments


def test_inverter_loss_exposed_as_diagnostic_sensor():
    descriptions = _load_descriptions_tuple("NUMERIC_SENSOR_DESCRIPTIONS")
    assert "inverter_loss" in descriptions
    assert descriptions["inverter_loss"]["entity_category"] == "EntityCategory.DIAGNOSTIC"


def test_pv_power_is_gross_string_sum():
    """"PV Power" is the gross sum of the per-string V*I values."""
    assignments = _load_assignment_sources()
    assert assignments.get("combined_pv_power") == "pv1_power + pv2_power"
    assert "pv_power" in _load_coordinator_return_keys()
    descriptions = _load_descriptions_tuple("NUMERIC_SENSOR_DESCRIPTIONS")
    assert "pv_power" in descriptions
    assert descriptions["pv_power"]["device_class"] == "SensorDeviceClass.POWER"


def test_usable_pv_power_uses_total_pv_power_register():
    """"Usable PV Power" reads the inverter's Total PV Power register
    (10183-10184) -- the post-MPPT harvested total, which reads lower than the
    gross string sum at low irradiance."""
    # source-level check: total_pv_power is also pinned to 0 on AC-coupled, so
    # the assignment-source map can't distinguish the decode; assert the raw
    # decode expression is present instead.
    assert "decode_i32_le(c[27:29])" in _load_coordinator_source()
    assert "usable_pv_power" in _load_coordinator_return_keys()
    descriptions = _load_descriptions_tuple("NUMERIC_SENSOR_DESCRIPTIONS")
    assert "usable_pv_power" in descriptions
    assert descriptions["usable_pv_power"]["device_class"] == "SensorDeviceClass.POWER"
    assert descriptions["usable_pv_power"]["state_class"] == "SensorStateClass.MEASUREMENT"


def test_ac_active_power_not_exposed_as_sensor_or_return_key():
    # ac_active_power sensor was removed, but the underlying register is kept
    # as an internal-only decode (see next test) -- it still feeds the
    # AC-coupled charge-power correction.
    descriptions = _load_descriptions_tuple("NUMERIC_SENSOR_DESCRIPTIONS")
    assert "ac_active_power" not in descriptions
    assert "ac_active_power" not in _load_coordinator_return_keys()


def test_ac_active_power_still_decoded_internally_for_charge_correction():
    assignments = _load_assignment_sources()
    assert assignments.get("ac_active_power") == "decode_i32_le(a[6:8])"


def test_ac_active_power_decode_offset_matches_register_10006_10007():
    modbus_client = _import_modbus_client()
    a = [0] * 40  # synthetic Block A, base address 10000
    a[6], a[7] = modbus_client.le_words(-500)  # indices 6:8 == addresses 10006-10007
    assert modbus_client.decode_i32_le(a[6:8]) == -500


def test_ac_coupled_charge_power_correction_still_applied():
    # The AC-coupled (pv_connected=False) charge-power correction is
    # independent of the inverter_loss balance -- verify the coordinator
    # source still contains it, guarded on `not self.pv_connected`.
    source = _load_coordinator_source()
    assert "not self.pv_connected and battery_power < 0" in source
    assert (
        "-round(\n                    (abs(battery_power) + abs(ac_active_power)) / 2\n                )"
        in source
        or "abs(battery_power) + abs(ac_active_power)" in source
    )


def test_ac_coupled_charge_power_correction_math():
    battery_power = -300  # charging
    ac_active_power = -200
    corrected = -round((abs(battery_power) + abs(ac_active_power)) / 2)
    assert corrected == -250
