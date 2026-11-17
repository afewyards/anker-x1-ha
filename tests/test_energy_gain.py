"""Energy accumulator gain depends on firmware (0.1 kWh/count on 1.0.18.x, else 0.01)."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parent.parent / "custom_components" / "anker_x1"

_spec = importlib.util.spec_from_file_location("modbus_client", PKG / "modbus_client.py")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)


@pytest.mark.parametrize(
    ("version", "gain"),
    [
        ("1.0.18.8", 10.0),
        ("1.0.16.1", 100.0),
        ("1.0.17.8", 100.0),
        ("1.0.19.16", 100.0),
        (None, 100.0),
        ("", 100.0),
    ],
)
def test_energy_gain(version, gain):
    assert _mod.energy_gain(version) == gain


def test_coordinator_energy_decodes_use_gain():
    src = (PKG / "coordinator.py").read_text()
    assert not re.search(r"decode_u32_le\([^)]*\) / 100\.0", src)
