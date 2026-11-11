"""Config flow for async-energy integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.core import HomeAssistant

from .api import ApiError, async_fetch_meter_data, build_url
from .const import CONF_API_URL, CONF_LOCATION_NAME, DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_API_URL): str,
        vol.Required(CONF_LOCATION_NAME): str,
    }
)


class CannotConnect(Exception):
    """Error to indicate we cannot connect."""


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> None:
    """Check that the API is reachable and returns meter data."""
    try:
        await async_fetch_meter_data(hass, data[CONF_API_URL], 1)
    except ApiError as err:
        raise CannotConnect from err


class AsyncEnergyConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for async-energy."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            await self.async_set_unique_id(build_url(user_input[CONF_API_URL]).lower())
            self._abort_if_unique_id_configured()

            try:
                await validate_input(self.hass, user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(
                    title=user_input[CONF_LOCATION_NAME], data=user_input
                )

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_DATA_SCHEMA, user_input
            ),
            errors=errors,
        )
