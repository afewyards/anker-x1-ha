"""Tests for export/import power-limit controls (holding registers 10074-10079).

Same constraint as test_meter_block.py: `homeassistant` isn't installed, so
coordinator.py / select.py / number.py can't be imported directly. Structural
claims are verified by parsing the source with `ast` (or targeted source-text
assertions). modbus_client.py has no HA dependency, so its decode/encode
helpers are exercised directly for genuine behavioural coverage.
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
COORDINATOR_PY = REPO_ROOT / "custom_components" / "anker_x1" / "coordinator.py"
CONST_PY = REPO_ROOT / "custom_components" / "anker_x1" / "const.py"
SELECT_PY = REPO_ROOT / "custom_components" / "anker_x1" / "select.py"
NUMBER_PY = REPO_ROOT / "custom_components" / "anker_x1" / "number.py"
MODBUS_CLIENT_PY = REPO_ROOT / "custom_components" / "anker_x1" / "modbus_client.py"


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


def _find_read_holding_registers_calls() -> dict[int, int | None]:
    """Return {start_address: count} for every read_holding_registers(...) call."""
    tree = ast.parse(_load_coordinator_source())
    calls: dict[int, int | None] = {}
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "read_holding_registers"
        ):
            addr = ast.literal_eval(node.args[0])
            count = next(
                (ast.literal_eval(kw.value) for kw in node.keywords if kw.arg == "count"),
                None,
            )
            calls[addr] = count
    return calls


def _load_coordinator_class() -> ast.ClassDef:
    tree = ast.parse(_load_coordinator_source())
    return next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef) and node.name == "AnkerX1Coordinator"
    )


def _load_method_source(name: str) -> str:
    cls = _load_coordinator_class()
    method = next(
        node
        for node in cls.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == name
    )
    return ast.unparse(method)


def _import_modbus_client():
    """Import modbus_client.py directly from its file, bypassing the package
    __init__ (which pulls in `homeassistant`)."""
    spec = importlib.util.spec_from_file_location(
        "anker_x1_modbus_client_under_test_limits", MODBUS_CLIENT_PY
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Block E: holding registers 10060-10080 (count=21), work_mode now at index 4
# ---------------------------------------------------------------------------


def test_block_e_widened_to_10060_count_21():
    calls = _find_read_holding_registers_calls()
    assert calls.get(10060) == 21


def test_module_docstring_documents_block_e_widened_range():
    docstring = ast.get_docstring(ast.parse(_load_coordinator_source()))
    assert docstring is not None
    assert "10060" in docstring
    assert "10080" in docstring


def test_work_mode_decoded_from_index_4():
    assignments = _load_assignment_sources()
    assert "decode_u16(e[4])" in assignments.get("work_mode", [])


def test_work_mode_decode_offset_matches_register_10064():
    modbus_client = _import_modbus_client()
    e = [0] * 21  # synthetic Block E, base address 10060
    e[4] = 3  # index 4 == address 10060 + 4 == 10064
    assert modbus_client.decode_u16(e[4]) == 3


# ---------------------------------------------------------------------------
# Decode formulas for the four new limit fields
# ---------------------------------------------------------------------------

EXPECTED_DECODE_FORMULAS = {
    "export_limit_mode": "decode_u16(e[14])",
    "export_limit_value": "decode_u32_le(e[15:17])",
    "import_limit_mode": "decode_u16(e[17])",
    "import_limit_value": "decode_u32_le(e[18:20])",
}


def test_limit_field_decode_formulas():
    assignments = _load_assignment_sources()
    for key, expected in EXPECTED_DECODE_FORMULAS.items():
        actual = assignments.get(key, [])
        assert expected in actual, f"{key}: expected {expected!r} in {actual!r}"


def test_limit_decode_offsets_match_registers_10074_10079():
    modbus_client = _import_modbus_client()
    e = [0] * 21  # synthetic Block E, base address 10060
    e[14] = 2  # 10074 export_limit_mode: Fixed power
    e[15], e[16] = modbus_client.le_words(1500)  # 10075-10076 export_limit_value
    e[17] = 1  # 10077 import_limit_mode: Percentage
    e[18], e[19] = modbus_client.le_words(50)  # 10078-10079 import_limit_value

    assert modbus_client.decode_u16(e[14]) == 2
    assert modbus_client.decode_u32_le(e[15:17]) == 1500
    assert modbus_client.decode_u16(e[17]) == 1
    assert modbus_client.decode_u32_le(e[18:20]) == 50


# ---------------------------------------------------------------------------
# All four keys present in the coordinator's returned data dict
# ---------------------------------------------------------------------------


def test_all_limit_fields_in_coordinator_return_dict():
    keys = _load_coordinator_return_keys()
    assert set(EXPECTED_DECODE_FORMULAS) <= keys


# ---------------------------------------------------------------------------
# Control methods: async_set_export_limit_mode/value, async_set_import_limit_mode/value
# ---------------------------------------------------------------------------


def test_async_set_export_limit_mode_writes_register_10074():
    source = _load_method_source("async_set_export_limit_mode")
    assert "write_register(10074" in source
    assert "isError()" in source
    assert "async_request_refresh()" in source


def test_async_set_export_limit_value_writes_registers_10075():
    source = _load_method_source("async_set_export_limit_value")
    assert "write_registers(10075, le_words(value)" in source
    assert "isError()" in source
    assert "async_request_refresh()" in source


def test_async_set_import_limit_mode_writes_register_10077():
    source = _load_method_source("async_set_import_limit_mode")
    assert "write_register(10077" in source
    assert "isError()" in source
    assert "async_request_refresh()" in source


def test_async_set_import_limit_value_writes_registers_10078():
    source = _load_method_source("async_set_import_limit_value")
    assert "write_registers(10078, le_words(value)" in source
    assert "isError()" in source
    assert "async_request_refresh()" in source


# ---------------------------------------------------------------------------
# const.py — LIMIT_MODE mapping
# ---------------------------------------------------------------------------


def test_limit_mode_const_mapping():
    tree = ast.parse(CONST_PY.read_text())
    assign = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == "LIMIT_MODE"
    )
    mapping = ast.literal_eval(assign.value)
    assert mapping == {
        0: "Disabled",
        1: "Percentage of rated power",
        2: "Fixed power",
    }


# ---------------------------------------------------------------------------
# select.py — new entity classes
# ---------------------------------------------------------------------------


def test_select_py_defines_export_and_import_limit_mode_classes():
    tree = ast.parse(SELECT_PY.read_text())
    class_names = {
        node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)
    }
    assert "AnkerX1ExportLimitMode" in class_names
    assert "AnkerX1ImportLimitMode" in class_names


def test_select_py_registers_new_entities_in_setup_entry():
    source = SELECT_PY.read_text()
    assert "AnkerX1ExportLimitMode" in source
    assert "AnkerX1ImportLimitMode" in source
    assert "AnkerX1WorkMode" in source  # existing entity untouched


# ---------------------------------------------------------------------------
# number.py — new entity classes
# ---------------------------------------------------------------------------


def test_number_py_defines_export_and_import_limit_value_classes():
    tree = ast.parse(NUMBER_PY.read_text())
    class_names = {
        node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)
    }
    assert "AnkerX1ExportLimitValue" in class_names
    assert "AnkerX1ImportLimitValue" in class_names


def test_number_py_registers_new_entities_in_setup_entry():
    source = NUMBER_PY.read_text()
    assert "AnkerX1ExportLimitValue" in source
    assert "AnkerX1ImportLimitValue" in source
    assert "AnkerX1Setpoint" in source  # existing entity untouched


# ---------------------------------------------------------------------------
# Behavioural: decode_u32_le / le_words round-trip a limit value like 20000
# ---------------------------------------------------------------------------


def test_le_words_and_decode_u32_le_roundtrip_limit_value():
    modbus_client = _import_modbus_client()
    words = modbus_client.le_words(20000)
    assert modbus_client.decode_u32_le(words) == 20000


def test_le_words_and_decode_u32_le_roundtrip_zero_and_max_power():
    modbus_client = _import_modbus_client()
    for value in (0, 30000):
        words = modbus_client.le_words(value)
        assert modbus_client.decode_u32_le(words) == value
