"""Tests for #4 — meter block 10620-10666 (external CHINT 3-phase meter).

Same constraint as test_sensor_cleanup.py / test_gridpv.py: `homeassistant`
isn't installed, so sensor.py / coordinator.py can't be imported directly.
Structural claims are verified by parsing the source with `ast`.
modbus_client.py has no HA dependency, so its decode helpers are exercised
directly for genuine behavioural coverage of the new register offsets.
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


def _load_assignment_sources() -> dict[str, list[str]]:
    """Map every assigned name in `_async_update_data` -> list of unparsed RHS
    source strings (a name may legitimately be assigned more than once)."""
    func = _load_update_data_func()
    out: dict[str, list[str]] = {}
    for node in ast.walk(func):
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.value is not None
        ):
            out.setdefault(node.target.id, []).append(ast.unparse(node.value))
        elif (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            out.setdefault(node.targets[0].id, []).append(ast.unparse(node.value))
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
        "anker_x1_modbus_client_under_test_meter", MODBUS_CLIENT_PY
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Block M read: input registers 10620-10666 (count=47), tolerant like Block H
# ---------------------------------------------------------------------------

def test_block_m_reads_10620_count_47():
    calls = _find_read_input_registers_calls()
    assert calls.get(10620) == 47


def test_block_m_read_is_tolerant_like_block_h():
    source = _load_coordinator_source()
    assert "m = rr_m.registers if not rr_m.isError() else None" in source


def test_module_docstring_documents_block_m():
    docstring = ast.get_docstring(ast.parse(_load_coordinator_source()))
    assert docstring is not None
    assert "10620" in docstring
    assert "10666" in docstring


# ---------------------------------------------------------------------------
# Decode gating: meter_comm_status / meter_ok
# ---------------------------------------------------------------------------

def test_meter_comm_status_decoded_from_10630():
    assignments = _load_assignment_sources()
    assert "decode_u16(m[11]) if m else None" in assignments.get("meter_comm_status", [])


def test_meter_type_decoded_from_10631():
    assignments = _load_assignment_sources()
    assert "decode_u16(m[10]) if m else None" in assignments.get("meter_type", [])


def test_meter_ok_gates_on_comm_status_normal():
    assignments = _load_assignment_sources()
    assert (
        "m is not None and meter_comm_status == 0" in assignments.get("meter_ok", [])
    )


def test_meter_comm_status_in_coordinator_return_dict():
    assert "meter_comm_status" in _load_coordinator_return_keys()


# ---------------------------------------------------------------------------
# Per-field decode formulas (gated on meter_ok)
# ---------------------------------------------------------------------------

EXPECTED_DECODE_FORMULAS = {
    "meter_total_power": "decode_i32_le(m[24:26]) if meter_ok else None",
}

# Removed as recorder-storage hogs: reactive power + forward/reverse energy
# totals. Locks in the removal, mirroring test_sensor_cleanup.py.
REMOVED_METER_KEYS = {
    "meter_total_reactive",
    "meter_fwd_energy_total",
    "meter_rev_energy_total",
}


def test_meter_field_decode_formulas():
    assignments = _load_assignment_sources()
    for key, expected in EXPECTED_DECODE_FORMULAS.items():
        actual = assignments.get(key, [])
        assert expected in actual, f"{key}: expected {expected!r} in {actual!r}"


def test_all_meter_fields_in_coordinator_return_dict():
    keys = _load_coordinator_return_keys()
    assert set(EXPECTED_DECODE_FORMULAS) <= keys


def test_removed_meter_fields_not_assigned_in_coordinator():
    assignments = _load_assignment_sources()
    assert not (REMOVED_METER_KEYS & assignments.keys())


def test_removed_meter_fields_not_in_coordinator_return_dict():
    keys = _load_coordinator_return_keys()
    assert not (REMOVED_METER_KEYS & keys)


# ---------------------------------------------------------------------------
# Behavioural: decode helper offsets against a synthetic Block M register set
# ---------------------------------------------------------------------------

def test_meter_offsets_decode_correctly_against_synthetic_block():
    modbus_client = _import_modbus_client()
    m = [0] * 47  # synthetic Block M, base address 10620

    m[10] = 2  # 10630 meter type: three-phase
    m[11] = 0  # 10631 comm status: normal
    m[12] = 2301  # 10632 voltage_a raw -> 230.1 V
    m[15] = 150  # 10635 current_a raw -> 1.50 A
    m[16] = 171  # 10636 current_b raw -> 1.71 A
    m[18], m[19] = modbus_client.le_words(1234)  # 10638-10639 power_a
    m[20], m[21] = modbus_client.le_words(-500)  # 10640-10641 power_b (export)
    m[24], m[25] = modbus_client.le_words(734)  # 10644-10645 total power
    m[28] = 987  # 10648 power factor raw -> 0.987
    m[29] = 5001  # 10649 frequency raw -> 50.01 Hz
    m[30], m[31] = modbus_client.le_words(12345)  # 10650-10651 fwd energy a

    assert modbus_client.decode_u16(m[10]) == 2
    assert modbus_client.decode_u16(m[11]) == 0
    assert modbus_client.decode_u16(m[12]) / 10.0 == 230.1
    assert modbus_client.decode_u16(m[15]) / 100.0 == 1.50
    assert modbus_client.decode_u16(m[16]) / 100.0 == 1.71
    assert modbus_client.decode_i32_le(m[18:20]) == 1234
    assert modbus_client.decode_i32_le(m[20:22]) == -500
    assert modbus_client.decode_i32_le(m[24:26]) == 734
    assert modbus_client.decode_i16(m[28]) / 1000.0 == 0.987
    assert modbus_client.decode_u16(m[29]) / 100.0 == 50.01
    assert modbus_client.decode_u32_le(m[30:32]) / 100.0 == 123.45


# ---------------------------------------------------------------------------
# const.py — METER_COMM_STATUS mapping
# ---------------------------------------------------------------------------

def test_meter_comm_status_const_mapping():
    tree = ast.parse(CONST_PY.read_text())
    assign = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == "METER_COMM_STATUS"
    )
    mapping = ast.literal_eval(assign.value)
    assert mapping == {0: "Normal", 1: "Offline", 3: "Fault"}


# ---------------------------------------------------------------------------
# sensor.py — numeric sensor descriptions
# ---------------------------------------------------------------------------

def test_meter_total_power_sensor_configured():
    descriptions = _load_descriptions_tuple("NUMERIC_SENSOR_DESCRIPTIONS")
    desc = descriptions["meter_total_power"]
    assert desc["device_class"] == "SensorDeviceClass.POWER"
    assert desc["state_class"] == "SensorStateClass.MEASUREMENT"


def test_removed_meter_sensor_descriptions_absent():
    descriptions = _load_descriptions_tuple("NUMERIC_SENSOR_DESCRIPTIONS")
    assert not (REMOVED_METER_KEYS & descriptions.keys())


# ---------------------------------------------------------------------------
# sensor.py — meter_comm_status enum sensor
# ---------------------------------------------------------------------------

def test_meter_comm_status_enum_sensor_configured():
    descriptions = _load_descriptions_tuple("ENUM_SENSOR_DESCRIPTIONS")
    assert "meter_comm_status" in descriptions
    desc = descriptions["meter_comm_status"]
    assert desc["mapping"] == "METER_COMM_STATUS"
    assert desc["entity_category"] == "EntityCategory.DIAGNOSTIC"
