"""Regression tests for the PV string V/I signed-decode fix.

The official Anker Modbus protocol V1.0.0 declares the per-string PV
registers (10167-10170: PV1 voltage/current, PV2 voltage/current) as
UINT16. In practice, firmware 1.0.16.1 emits small NEGATIVE two's
complement values on these registers at night (MPPT ADC offset) -- e.g.
register 10170 (PV2 current) reads 65527-65529 (-0.09..-0.07 A) every
night while the string's float voltage is still 15-215 V. Decoding those
registers as unsigned wraps -0.07 A into 655.27 A, so pv2_power reported
9,000-140,000 W of phantom power overnight.

Decoding voltage+current as signed int16 (clamped at zero, since a PV
string cannot source negative current) fixes this. Legitimate daytime
values can never reach the i16 sign bit (max string ~600V -> raw 6000;
~20A -> raw 2000), so real readings are unaffected.

Same constraint as tests/test_gridpv.py: `homeassistant` isn't installed,
so coordinator.py can't be imported directly. Structural claims are
verified by parsing the source with `ast`; modbus_client.py has no HA
dependency, so its decode helpers are exercised directly for genuine
behavioural coverage of the real decode path.
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
COORDINATOR_PY = REPO_ROOT / "custom_components" / "anker_x1" / "coordinator.py"
MODBUS_CLIENT_PY = REPO_ROOT / "custom_components" / "anker_x1" / "modbus_client.py"


def _import_modbus_client():
    """Import modbus_client.py directly from its file, bypassing the package
    __init__ (which pulls in `homeassistant`)."""
    spec = importlib.util.spec_from_file_location(
        "anker_x1_modbus_client_under_test_pv_signed", MODBUS_CLIENT_PY
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_update_data_func() -> ast.AsyncFunctionDef:
    tree = ast.parse(COORDINATOR_PY.read_text())
    return next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_async_update_data"
    )


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


# ---------------------------------------------------------------------------
# Structural: PV1/PV2 voltage+current must be decoded signed and clamped >= 0
# ---------------------------------------------------------------------------


def test_pv_string_voltage_and_current_decoded_signed_and_clamped():
    assignments = _load_assignment_sources()
    assert assignments.get("pv1_voltage") == "max(0.0, decode_i16(c[11]) / 10.0)"
    assert assignments.get("pv1_current") == "max(0.0, decode_i16(c[12]) / 100.0)"
    assert assignments.get("pv2_voltage") == "max(0.0, decode_i16(c[13]) / 10.0)"
    assert assignments.get("pv2_current") == "max(0.0, decode_i16(c[14]) / 100.0)"


# ---------------------------------------------------------------------------
# Behavioural: real decode path against observed register frames
# ---------------------------------------------------------------------------


def _decode_pv_string(
    modbus_client, voltage_raw: int, current_raw: int
) -> tuple[float, float, int]:
    """Mirror the coordinator's per-string decode: signed int16, clamped >= 0."""
    voltage = max(0.0, modbus_client.decode_i16(voltage_raw) / 10.0)
    current = max(0.0, modbus_client.decode_i16(current_raw) / 100.0)
    power = round(voltage * current)
    return voltage, current, power


def test_night_frame_pv2_negative_current_clamps_to_zero_power():
    """Observed on the France unit: reg 10169=150 (15.0V), reg 10170=65529
    (two's complement -0.07A) every night. Unsigned decode wrapped this to
    655.27A -> 9,000-140,000W of phantom power; signed decode + clamp fixes
    it."""
    modbus_client = _import_modbus_client()
    voltage, current, power = _decode_pv_string(modbus_client, 150, 65529)
    assert voltage == 15.0
    assert current == 0.0
    assert power == 0


def test_night_frame_pv1_small_positive_offset_unchanged():
    """PV1's ADC offset is slightly positive (raw current 9 = +0.09A) so it
    never wrapped even under the old unsigned decode; behaviour must stay
    unchanged (near-zero power) under the new signed decode."""
    modbus_client = _import_modbus_client()
    voltage, current, power = _decode_pv_string(modbus_client, 5, 9)
    assert current == 0.09
    assert power == 0


def test_day_frame_pv2_positive_current_decodes_normally():
    """Daytime frame: reg 10169=1480 (148.0V), reg 10170=17 (0.17A) ->
    148.0 * 0.17 = 25.16W, rounds to 25W."""
    modbus_client = _import_modbus_client()
    voltage, current, power = _decode_pv_string(modbus_client, 1480, 17)
    assert voltage == 148.0
    assert current == 0.17
    assert power == 25
