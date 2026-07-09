"""Tests for the #18 + #3 + #17 sensor cleanup batch.

This repo is a Home Assistant custom integration with no `homeassistant`
package installed as a dependency (see pyproject.toml), so importing
sensor.py / coordinator.py directly isn't viable without heavy stubbing.
Instead these tests parse the source with `ast`, which is fast,
dependency-free, and precisely verifies the literal values baked into the
sensor descriptions and the coordinator's returned data dict.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SENSOR_PY = REPO_ROOT / "custom_components" / "anker_x1" / "sensor.py"
COORDINATOR_PY = REPO_ROOT / "custom_components" / "anker_x1" / "coordinator.py"

REMOVED_GRID_L1_L3_KEYS = {
    "grid_voltage_l1",
    "grid_voltage_l2",
    "grid_voltage_l3",
    "grid_current_l1",
    "grid_current_l2",
    "grid_current_l3",
}


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


# ---------------------------------------------------------------------------
# #18 — remove grid V/I L1-3
# ---------------------------------------------------------------------------

def test_grid_l1_l3_voltage_current_removed_from_sensor_descriptions():
    descriptions = _load_numeric_sensor_descriptions()
    assert not (REMOVED_GRID_L1_L3_KEYS & descriptions.keys())


def test_grid_l1_l3_voltage_current_removed_from_coordinator_output():
    keys = _load_coordinator_return_keys()
    assert not (REMOVED_GRID_L1_L3_KEYS & keys)


# ---------------------------------------------------------------------------
# #3 — rename grid energy sensors (name only; key/state_class untouched)
# ---------------------------------------------------------------------------

def test_grid_energy_sensors_renamed_to_today():
    descriptions = _load_numeric_sensor_descriptions()

    assert descriptions["grid_bought_total"]["name"] == "Grid Bought Today"
    assert descriptions["grid_fed_in_total"]["name"] == "Grid Fed-in Today"

    # key (and therefore entity_id/history) must be unchanged.
    assert "grid_bought_total" in descriptions
    assert "grid_fed_in_total" in descriptions

    assert (
        descriptions["grid_bought_total"]["state_class"]
        == "SensorStateClass.TOTAL_INCREASING"
    )
    assert (
        descriptions["grid_fed_in_total"]["state_class"]
        == "SensorStateClass.TOTAL_INCREASING"
    )


# ---------------------------------------------------------------------------
# #17 — rechargeable/dischargeable power -> DIAGNOSTIC
# ---------------------------------------------------------------------------

def test_rechargeable_and_dischargeable_power_are_diagnostic():
    descriptions = _load_numeric_sensor_descriptions()

    assert (
        descriptions["rechargeable_power"]["entity_category"]
        == "EntityCategory.DIAGNOSTIC"
    )
    assert (
        descriptions["dischargeable_power"]["entity_category"]
        == "EntityCategory.DIAGNOSTIC"
    )
