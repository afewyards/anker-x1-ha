"""Tests for #16 (PV strings) and the grid/backup electrical detail removal.

Grid electrical detail (grid_voltage_ubc/uca, grid_active_power_pcs,
grid_power_factor), backup electrical detail (backup_current_a/b/c,
backup_reactive_power, backup_power_factor, backup_frequency), and PV
string 3 (pv3_voltage/current/power) were all removed as unused sensors.
pv1/pv2 strings remain the primary DC-coupled PV measurement.

Decodes additional fields from EXISTING register blocks B/C/G — no new
Modbus reads. Same AST-parsing approach as test_sensor_cleanup.py: this repo
has no `homeassistant` package installed locally (see pyproject.toml), so we
parse the source instead of importing it.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SENSOR_PY = REPO_ROOT / "custom_components" / "anker_x1" / "sensor.py"
COORDINATOR_PY = REPO_ROOT / "custom_components" / "anker_x1" / "coordinator.py"


def _literal_or_source(node: ast.AST) -> object:
    """Return the Python literal for `node`, or its source text if it isn't one."""
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError):
        return ast.unparse(node)


def _load_numeric_sensor_descriptions() -> dict[str, dict[str, object]]:
    """Parse NUMERIC_SENSOR_DESCRIPTIONS into {key: {kwarg: value}}."""
    tree = ast.parse(SENSOR_PY.read_text())

    assign = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == "NUMERIC_SENSOR_DESCRIPTIONS"
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


def _load_coordinator_return_keys() -> set[str]:
    """Return the string-literal keys of the dict returned by _async_update_data."""
    tree = ast.parse(COORDINATOR_PY.read_text())

    func = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_async_update_data"
    )
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


def _source_for_assignment(tree: ast.AST, name: str) -> str:
    """Return the unparsed RHS source for `name: type = expr` inside
    _async_update_data (an ast.AnnAssign with target `name`)."""
    func = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_async_update_data"
    )
    assign = next(
        node
        for node in ast.walk(func)
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == name
    )
    return ast.unparse(assign.value)


PV_STRING_KEYS = {
    "pv1_power", "pv2_power",
}

REMOVED_GRID_BACKUP_PV3_KEYS = {
    "grid_voltage_ubc", "grid_voltage_uca",
    "grid_active_power_pcs", "grid_power_factor",
    "backup_current_a", "backup_current_b", "backup_current_c",
    "backup_reactive_power", "backup_power_factor", "backup_frequency",
    "pv3_voltage", "pv3_current", "pv3_power",
}


# ---------------------------------------------------------------------------
# Removed: grid electrical detail, backup electrical detail, PV string 3
# ---------------------------------------------------------------------------

def test_grid_backup_electrical_and_pv3_removed_from_sensor_descriptions():
    descriptions = _load_numeric_sensor_descriptions()
    assert not (REMOVED_GRID_BACKUP_PV3_KEYS & descriptions.keys())


def test_grid_backup_electrical_and_pv3_removed_from_coordinator_output():
    keys = _load_coordinator_return_keys()
    assert not (REMOVED_GRID_BACKUP_PV3_KEYS & keys)


# ---------------------------------------------------------------------------
# Coordinator: PV1/PV2 keys still present in the returned data dict
# ---------------------------------------------------------------------------

def test_pv_string_keys_present_in_coordinator_output():
    keys = _load_coordinator_return_keys()
    missing = PV_STRING_KEYS - keys
    assert not missing, f"missing from coordinator return dict: {missing}"


# ---------------------------------------------------------------------------
# Coordinator: PV1/PV2 decode expressions use the documented registers/scales
# ---------------------------------------------------------------------------

def test_pv_string_decode_expressions():
    tree = ast.parse(COORDINATOR_PY.read_text())
    assert _source_for_assignment(tree, "pv1_voltage") == "decode_u16(c[11]) / 10.0"
    assert _source_for_assignment(tree, "pv1_current") == "decode_u16(c[12]) / 100.0"
    assert _source_for_assignment(tree, "pv1_power") == "round(pv1_voltage * pv1_current)"
    assert _source_for_assignment(tree, "pv2_voltage") == "decode_u16(c[13]) / 10.0"
    assert _source_for_assignment(tree, "pv2_current") == "decode_u16(c[14]) / 100.0"
    assert _source_for_assignment(tree, "pv2_power") == "round(pv2_voltage * pv2_current)"


def test_pv_string_power_is_voltage_times_current():
    """The map (protocol V1.0.0 p.11) has no per-string power register; power
    is derived as V*I from the unsigned voltage/current, so it can never go
    negative -- no clamp needed."""
    tree = ast.parse(COORDINATOR_PY.read_text())
    for key, volt, curr in (
        ("pv1_power", "pv1_voltage", "pv1_current"),
        ("pv2_power", "pv2_voltage", "pv2_current"),
    ):
        src = _source_for_assignment(tree, key)
        assert volt in src and curr in src, f"{key} not derived from V*I: {src}"


# ---------------------------------------------------------------------------
# Sensor descriptions
# ---------------------------------------------------------------------------

def test_pv_string_keys_present_in_sensor_descriptions():
    descriptions = _load_numeric_sensor_descriptions()
    missing = PV_STRING_KEYS - descriptions.keys()
    assert not missing, f"missing sensor descriptions: {missing}"


def test_pv_string_sensors_are_not_diagnostic():
    descriptions = _load_numeric_sensor_descriptions()
    for key in PV_STRING_KEYS:
        assert descriptions[key].get("entity_category") is None, key


def test_power_sensor_properties():
    descriptions = _load_numeric_sensor_descriptions()
    power_keys = {"pv1_power", "pv2_power"}
    for key in power_keys:
        d = descriptions[key]
        assert d["device_class"] == "SensorDeviceClass.POWER", key
        assert d["state_class"] == "SensorStateClass.MEASUREMENT", key
