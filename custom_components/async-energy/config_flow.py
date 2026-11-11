"""Config flow for async-energy integration."""
from __future__ import annotations

from collections.abc import Mapping
import json
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import ApiError, InvalidAuth, async_fetch_hourly
from .const import (
    ARCHIVE_DRIVE,
    ARCHIVE_LOCAL,
    ARCHIVE_NONE,
    CONF_ARCHIVE,
    CONF_DRIVE_CREDENTIALS,
    CONF_DRIVE_FOLDER_ID,
    CONF_INSTALLATION_ID,
    CONF_LOCATION_NAME,
    CONF_PASSWORD,
    CONF_USERNAME,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

CREDENTIALS_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Required(CONF_INSTALLATION_ID): str,
    }
)
STEP_USER_DATA_SCHEMA = CREDENTIALS_SCHEMA.extend(
    {vol.Required(CONF_LOCATION_NAME): str}
)


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> str | None:
    """Log in and fetch yesterday. Returns an error key, or None if all is well."""
    try:
        await async_fetch_hourly(
            hass,
            data[CONF_USERNAME],
            data[CONF_PASSWORD],
            data[CONF_INSTALLATION_ID],
            1,
        )
    except InvalidAuth:
        return "invalid_auth"
    except ApiError:
        return "cannot_connect"
    except Exception:  # pylint: disable=broad-except
        _LOGGER.exception("Unexpected exception")
        return "unknown"
    return None


class AsyncEnergyConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for async-energy."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow (optional raw-data archive)."""
        return AsyncEnergyOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            user_input = {**user_input, CONF_INSTALLATION_ID: user_input[CONF_INSTALLATION_ID].strip()}
            await self.async_set_unique_id(user_input[CONF_INSTALLATION_ID])
            self._abort_if_unique_id_configured()

            if error := await validate_input(self.hass, user_input):
                errors["base"] = error
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

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start reauthentication (also used to migrate API-URL entries)."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the EKZ login again."""
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()

        if user_input is not None:
            user_input = {**user_input, CONF_INSTALLATION_ID: user_input[CONF_INSTALLATION_ID].strip()}
            if error := await validate_input(self.hass, user_input):
                errors["base"] = error
            else:
                return self.async_update_reload_and_abort(
                    entry,
                    unique_id=user_input[CONF_INSTALLATION_ID],
                    data_updates=user_input,
                )

        suggested = user_input or {
            CONF_USERNAME: entry.data.get(CONF_USERNAME),
            CONF_INSTALLATION_ID: entry.data.get(CONF_INSTALLATION_ID),
        }
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=self.add_suggested_values_to_schema(
                CREDENTIALS_SCHEMA, suggested
            ),
            errors=errors,
        )


class AsyncEnergyOptionsFlow(OptionsFlow):
    """Choose where (if anywhere) the raw EKZ responses are archived."""

    def __init__(self) -> None:
        self._archive = ARCHIVE_NONE

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick the archive target."""
        if user_input is not None:
            self._archive = user_input[CONF_ARCHIVE]
            if self._archive == ARCHIVE_DRIVE:
                return await self.async_step_drive()
            return self.async_create_entry(data={CONF_ARCHIVE: self._archive})

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_ARCHIVE,
                        default=self.config_entry.options.get(
                            CONF_ARCHIVE, ARCHIVE_NONE
                        ),
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=[ARCHIVE_NONE, ARCHIVE_LOCAL, ARCHIVE_DRIVE],
                            translation_key=CONF_ARCHIVE,
                            mode=SelectSelectorMode.LIST,
                        )
                    )
                }
            ),
        )

    async def async_step_drive(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Google Drive service account and folder."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                info = json.loads(user_input[CONF_DRIVE_CREDENTIALS])
                if not {"client_email", "private_key"} <= set(info):
                    raise ValueError
            except ValueError:
                errors[CONF_DRIVE_CREDENTIALS] = "invalid_service_account"
            else:
                return self.async_create_entry(
                    data={
                        CONF_ARCHIVE: ARCHIVE_DRIVE,
                        CONF_DRIVE_CREDENTIALS: user_input[CONF_DRIVE_CREDENTIALS],
                        CONF_DRIVE_FOLDER_ID: user_input[CONF_DRIVE_FOLDER_ID].strip(),
                    }
                )

        return self.async_show_form(
            step_id="drive",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Required(CONF_DRIVE_CREDENTIALS): TextSelector(
                            TextSelectorConfig(
                                type=TextSelectorType.PASSWORD, multiline=True
                            )
                        ),
                        vol.Required(CONF_DRIVE_FOLDER_ID): str,
                    }
                ),
                user_input
                or {
                    CONF_DRIVE_FOLDER_ID: self.config_entry.options.get(
                        CONF_DRIVE_FOLDER_ID
                    )
                },
            ),
            errors=errors,
        )
