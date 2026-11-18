"""Tiered polling: fast blocks every poll, slow blocks every SLOW_POLL_INTERVAL_S.

`homeassistant` isn't installed, so it is stubbed just enough to import the real
coordinator.py and drive `_async_update_data` against a fake Modbus client.
"""

from __future__ import annotations

import ast
import asyncio
import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest
import voluptuous as vol

PKG = Path(__file__).resolve().parent.parent / "custom_components" / "anker_x1"

FAST = {10000, 10156, 10224, 10620}
SLOW = {10090, 10060, 10258, 10253}


def _stub(name: str, **attrs) -> None:
    mod = types.ModuleType(name)
    mod.__dict__.update(attrs)
    sys.modules[name] = mod


class _UpdateFailed(Exception):
    pass


class _DataUpdateCoordinator:
    def __init__(self, hass, logger, *, name, update_interval):
        self.hass = hass
        self.name = name
        self.update_interval = update_interval
        self.config_entry = None
        self.refresh_requests = 0
        self.super_scheduled = 0
        self.handled = 0

    async def _handle_refresh_interval(self, _now=None):
        self.handled += 1

    def __class_getitem__(cls, _item):
        return cls

    def _schedule_refresh(self):
        self.super_scheduled += 1

    def _async_unsub_refresh(self):
        pass

    async def async_request_refresh(self):
        self.refresh_requests += 1


@pytest.fixture(scope="module")
def coordinator_module():
    saved = dict(sys.modules)
    for name in (
        "homeassistant",
        "homeassistant.helpers",
        "homeassistant.util",
    ):
        _stub(name)
    _stub("homeassistant.core", HomeAssistant=object, callback=lambda f: f)
    _stub("homeassistant.helpers.device_registry", DeviceInfo=dict)
    _stub(
        "homeassistant.helpers.update_coordinator",
        DataUpdateCoordinator=_DataUpdateCoordinator,
        UpdateFailed=_UpdateFailed,
    )
    _stub("homeassistant.util.dt", utcnow=lambda: None)
    pkg = types.ModuleType("anker_x1_tiered")
    pkg.__path__ = [str(PKG)]
    sys.modules["anker_x1_tiered"] = pkg
    spec = importlib.util.spec_from_file_location(
        "anker_x1_tiered.coordinator", PKG / "coordinator.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.clear()
    sys.modules.update(saved)


class _FakeClient:
    connected = True

    def __init__(self) -> None:
        self.reads: list[int] = []
        self.fail: dict[int, Exception] = {}
        self.values: dict[int, list[int]] = {}
        self.closed = 0

    def close(self):
        self.closed += 1

    async def _read(self, address, count=None, **_unit):
        self.reads.append(address)
        if address in self.fail:
            raise self.fail[address]
        regs = self.values.get(address, [0] * count)
        return SimpleNamespace(isError=lambda: False, registers=regs)

    async def write_register(self, *_a, **_kw):
        return SimpleNamespace(isError=lambda: True)

    read_input_registers = _read
    read_holding_registers = _read


class _FakeLoop:
    def __init__(self) -> None:
        self.now = 100.0
        self.calls: list[float] = []
        self.callbacks: list = []

    def time(self) -> float:
        return self.now

    def call_at(self, when, callback):
        self.calls.append(when)
        self.callbacks.append(callback)
        return SimpleNamespace(cancel=lambda: None)


def _make(module, monkeypatch, interval=1.0):
    clock = SimpleNamespace(now=1000.0)
    monkeypatch.setattr(module, "monotonic", lambda: clock.now)
    monkeypatch.setattr(module, "AsyncModbusTcpClient", lambda **_kw: _FakeClient())
    hass = SimpleNamespace(loop=_FakeLoop(), tasks=[])

    def create_task(coro, **kw):
        hass.tasks.append(kw)
        asyncio.run(coro)

    hass.async_create_background_task = create_task
    coord = module.AnkerX1Coordinator(hass, "h", 502, 1, interval)
    coord._serial_probe_done = True
    return coord, clock


def _poll(coord) -> set[int]:
    coord._client.reads.clear()
    asyncio.run(coord._async_update_data())
    return set(coord._client.reads)


def test_first_poll_reads_everything(coordinator_module, monkeypatch):
    coord, _ = _make(coordinator_module, monkeypatch)
    assert _poll(coord) == FAST | SLOW


def test_slow_blocks_not_reread_within_interval(coordinator_module, monkeypatch):
    coord, clock = _make(coordinator_module, monkeypatch)
    _poll(coord)
    clock.now += coordinator_module.SLOW_POLL_INTERVAL_S - 0.1
    assert _poll(coord) == FAST


def test_slow_blocks_reread_after_interval(coordinator_module, monkeypatch):
    coord, clock = _make(coordinator_module, monkeypatch)
    _poll(coord)
    clock.now += coordinator_module.SLOW_POLL_INTERVAL_S
    assert _poll(coord) == FAST | SLOW
    assert _poll(coord) == FAST


def test_failed_write_still_rereads_slow_blocks(coordinator_module, monkeypatch):
    coord, _ = _make(coordinator_module, monkeypatch)
    _poll(coord)
    with pytest.raises(RuntimeError):
        asyncio.run(coord.async_set_work_mode(1))
    assert _poll(coord) == FAST | SLOW


def test_failed_slow_read_on_a_later_poll_is_retried_next_poll(coordinator_module, monkeypatch):
    coord, clock = _make(coordinator_module, monkeypatch)
    assert _poll(coord) == FAST | SLOW
    clock.now += coordinator_module.SLOW_POLL_INTERVAL_S
    good = coord._client._read

    async def bad_b(address, count=None, **unit):
        if address == 10090:
            return SimpleNamespace(isError=lambda: True, registers=[])
        return await good(address, count, **unit)

    coord._client.read_input_registers = bad_b
    with pytest.raises(_UpdateFailed):
        _poll(coord)
    coord._client.read_input_registers = good
    assert _poll(coord) == FAST | SLOW
    assert _poll(coord) == FAST


def test_transport_error_rereads_slow_blocks(coordinator_module, monkeypatch):
    coord, _ = _make(coordinator_module, monkeypatch)
    _poll(coord)
    coord._client.fail[10156] = TimeoutError()
    with pytest.raises(_UpdateFailed):
        _poll(coord)
    assert coord._client.closed == 1
    del coord._client.fail[10156]
    assert _poll(coord) == FAST | SLOW


def test_silent_meter_block_does_not_break_serial_or_slow_tier(coordinator_module, monkeypatch):
    coord, _ = _make(coordinator_module, monkeypatch)
    coord._serial_probe_done = False
    coord._client.values[10750] = [0x4142] * 8
    coord._client.fail[10620] = TimeoutError()
    assert _poll(coord) == FAST | SLOW | {10750}
    assert coord.serial
    assert coord._client.reads[-1] == 10620


def test_sub_second_interval_ticks_from_poll_start(coordinator_module, monkeypatch):
    coord, _ = _make(coordinator_module, monkeypatch, interval=0.25)
    coord.hass.loop.now = 105.6
    asyncio.run(coord._async_update_data())
    coord.hass.loop.now = 105.8
    coord._schedule_refresh()
    assert coord.hass.loop.calls == [pytest.approx(105.85)]
    assert coord.super_scheduled == 0
    coord.hass.loop.callbacks[0]()
    assert coord.handled == 1
    assert coord.hass.tasks == [{"name": "Anker X1 (h:502) - refresh", "eager_start": True}]


def test_sub_second_refresh_runs_under_the_config_entry(coordinator_module, monkeypatch):
    coord, _ = _make(coordinator_module, monkeypatch, interval=0.25)
    started = []

    def create(hass, coro, *, name, eager_start):
        started.append((name, eager_start))
        asyncio.run(coro)

    coord.config_entry = SimpleNamespace(
        pref_disable_polling=False, title="X1", async_create_background_task=create
    )
    coord._schedule_refresh()
    coord.hass.loop.callbacks[0]()
    assert coord.handled == 1
    assert started == [("Anker X1 (h:502) - X1 - refresh", True)]


def test_whole_second_interval_uses_stock_scheduler(coordinator_module, monkeypatch):
    coord, _ = _make(coordinator_module, monkeypatch, interval=2)
    coord._schedule_refresh()
    assert coord.super_scheduled == 1


def test_options_flow_accepts_fractional_interval():
    from importlib import util

    spec = util.spec_from_file_location("anker_x1_const_tiered", PKG / "const.py")
    const = util.module_from_spec(spec)
    spec.loader.exec_module(const)
    schema = vol.All(
        vol.Coerce(float),
        vol.Range(min=const.MIN_SCAN_INTERVAL, max=const.MAX_SCAN_INTERVAL),
    )
    assert schema(0.25) == 0.25
    assert schema("0.5") == 0.5
    assert schema(1) == 1.0  # options stored as int before this change
    with pytest.raises(vol.Invalid):
        schema(0.1)
    with pytest.raises(vol.Invalid):
        schema(float("nan"))
    src = ast.unparse(ast.parse((PKG / "config_flow.py").read_text()))
    assert "vol.Coerce(float)" in src.split("CONF_SCAN_INTERVAL, default=current_interval")[1][:200]
