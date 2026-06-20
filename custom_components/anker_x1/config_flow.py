"""Config flow for Anker SOLIX X1 integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from pymodbus.client import AsyncModbusTcpClient

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant

from .const import CONF_SLAVE, DEFAULT_PORT, DEFAULT_SLAVE, DOMAIN
from .modbus_client import unit_kwarg_name

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
        vol.Required(CONF_SLAVE, default=DEFAULT_SLAVE): int,
    }
)


def _decode_string_low_byte_first(registers: list[int]) -> str:
    """Decode a Modbus register string where each register is low-byte then high-byte."""
    chars: list[str] = []
    for reg in registers:
        low = reg & 0xFF
        high = (reg >> 8) & 0xFF
        if low == 0:
            break
        chars.append(chr(low))
        if high == 0:
            break
        chars.append(chr(high))
    return "".join(chars).strip()


async def _validate_connection(
    hass: HomeAssistant, host: str, port: int, slave: int
) -> dict[str, Any]:
    """Validate the connection and return device identifiers."""
    client = AsyncModbusTcpClient(host, port=port)
    try:
        await client.connect()
        if not client.connected:
            raise ConnectionError("Could not connect")

        # pymodbus <3.9 uses slave=, >=3.9 uses device_id=.
        unit = {unit_kwarg_name(client): slave}

        # Read SOC register (10014) as a connectivity check
        soc_result = await client.read_input_registers(10014, count=1, **unit)
        if soc_result.isError():
            raise ConnectionError("Could not read SOC register")

        # Read model string from registers 10090–10099 (10 registers)
        model_result = await client.read_input_registers(10090, count=10, **unit)
        model = ""
        if not model_result.isError():
            model = _decode_string_low_byte_first(list(model_result.registers))

        # Read serial string from registers 10750–10757 (8 registers)
        serial_result = await client.read_input_registers(10750, count=8, **unit)
        serial = ""
        if not serial_result.isError():
            serial = _decode_string_low_byte_first(list(serial_result.registers))

        return {"serial": serial, "model": model}
    finally:
        client.close()


class AnkerX1ConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Anker SOLIX X1."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST]
            port = user_input[CONF_PORT]
            slave = user_input[CONF_SLAVE]

            try:
                device_info = await _validate_connection(
                    self.hass, host, port, slave
                )
            except Exception:
                _LOGGER.exception("Unexpected error connecting to Anker X1 at %s:%s", host, port)
                errors["base"] = "cannot_connect"
            else:
                serial = device_info.get("serial") or f"{host}:{port}"
                await self.async_set_unique_id(serial)
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=f"Anker X1 ({host})",
                    data={
                        CONF_HOST: host,
                        CONF_PORT: port,
                        CONF_SLAVE: slave,
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )
