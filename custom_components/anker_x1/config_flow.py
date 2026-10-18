"""Config flow for Anker SOLIX X1 integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from pymodbus.client import AsyncModbusTcpClient

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant, callback

from .const import (
    CONF_PV_CONNECTED,
    CONF_RESTORE_WORK_MODE,
    CONF_SLAVE,
    DEFAULT_PORT,
    DEFAULT_PV_CONNECTED,
    DEFAULT_RESTORE_WORK_MODE,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SLAVE,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
    WORK_MODE,
)
from .modbus_client import decode_string_lowbyte, read_optional, unit_kwarg_name

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
        vol.Required(CONF_SLAVE, default=DEFAULT_SLAVE): int,
    }
)


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

        # Model 10090–10099 plus the PCS serial 10100–10111 in one frame.
        # Optional: a unit that does not implement them must still be addable.
        identity = await read_optional(
            client.read_input_registers, 10090, count=22, **unit
        )
        model = ""
        if identity.registers is not None:
            model = decode_string_lowbyte(identity.registers[0:10])

        # Serial 10750–10757. Preferred over 10100 so that unique_id stays
        # stable for installs already identified by it.
        serial_result = await read_optional(
            client.read_input_registers, 10750, count=8, **unit
        )
        serial = ""
        if serial_result.registers is not None:
            serial = decode_string_lowbyte(serial_result.registers)
        if not serial and identity.registers is not None:
            serial = decode_string_lowbyte(identity.registers[10:22])

        return {"serial": serial, "model": model}
    finally:
        client.close()


class AnkerX1ConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Anker SOLIX X1."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> AnkerX1OptionsFlow:
        """Return the options flow handler."""
        return AnkerX1OptionsFlow()

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


class AnkerX1OptionsFlow(OptionsFlow):
    """Handle options for an Anker SOLIX X1 entry (e.g. the Modbus poll rate)."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the integration options."""
        if user_input is not None:
            data = dict(user_input)
            if CONF_RESTORE_WORK_MODE in data:
                data[CONF_RESTORE_WORK_MODE] = int(data[CONF_RESTORE_WORK_MODE])
            return self.async_create_entry(data=data)

        current_interval = self.config_entry.options.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
        )
        current_pv = self.config_entry.options.get(
            CONF_PV_CONNECTED, DEFAULT_PV_CONNECTED
        )
        # Stored as the mode code; offered as "<code> - <label>" strings because
        # selectors and vol.In work on strings.
        restore_choices = {str(k): f"{k} - {v}" for k, v in WORK_MODE.items()}
        current_restore = str(
            self.config_entry.options.get(
                CONF_RESTORE_WORK_MODE, DEFAULT_RESTORE_WORK_MODE
            )
        )
        options_schema = vol.Schema(
            {
                vol.Required(CONF_SCAN_INTERVAL, default=current_interval): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL),
                ),
                vol.Required(CONF_PV_CONNECTED, default=current_pv): bool,
                vol.Required(
                    CONF_RESTORE_WORK_MODE, default=current_restore
                ): vol.In(restore_choices),
            }
        )

        return self.async_show_form(step_id="init", data_schema=options_schema)
