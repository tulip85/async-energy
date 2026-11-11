"""The async-energy integration.

Logs in to my.ekz.ch, archives the raw consumption data in the config
directory and imports it into Home Assistant's long-term statistics. It has
no entities.
"""
from __future__ import annotations

from datetime import datetime
import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    HomeAssistantError,
    ConfigEntryNotReady,
)
from homeassistant.helpers.event import async_track_time_interval

from .api import ApiError, InvalidAuth
from .const import (
    ATTR_DAYS,
    CONF_PASSWORD,
    CONF_USERNAME,
    DOMAIN,
    MAX_BACKFILL_DAYS,
    SERVICE_BACKFILL,
)
from .importer import UPDATE_INTERVAL, StatisticsImporter

_LOGGER = logging.getLogger(__name__)

type AsyncEnergyConfigEntry = ConfigEntry[StatisticsImporter]

BACKFILL_SCHEMA = vol.Schema(
    {vol.Required(ATTR_DAYS): vol.All(vol.Coerce(int), vol.Range(min=1, max=MAX_BACKFILL_DAYS))}
)


async def async_setup_entry(hass: HomeAssistant, entry: AsyncEnergyConfigEntry) -> bool:
    """Set up async-energy from a config entry."""
    # Entries created before the integration talked to EKZ itself only have
    # an API URL: ask the user for their EKZ login.
    if CONF_USERNAME not in entry.data or CONF_PASSWORD not in entry.data:
        raise ConfigEntryAuthFailed("EKZ credentials are required")

    importer = StatisticsImporter(hass, entry)
    entry.runtime_data = importer

    try:
        await importer.async_import()
    except InvalidAuth as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except ApiError as err:
        raise ConfigEntryNotReady(str(err)) from err

    async def _scheduled_import(_now: datetime) -> None:
        try:
            await importer.async_import()
        except InvalidAuth:
            entry.async_start_reauth(hass)
        except ApiError as err:
            _LOGGER.warning("Could not update energy statistics: %s", err)

    entry.async_on_unload(
        async_track_time_interval(hass, _scheduled_import, UPDATE_INTERVAL)
    )

    if not hass.services.has_service(DOMAIN, SERVICE_BACKFILL):

        async def _backfill(call: ServiceCall) -> None:
            entries = hass.config_entries.async_loaded_entries(DOMAIN)
            if not entries:
                raise HomeAssistantError("async-energy is not loaded")
            for loaded in entries:
                try:
                    await loaded.runtime_data.async_import(call.data[ATTR_DAYS])
                except InvalidAuth as err:
                    loaded.async_start_reauth(hass)
                    raise HomeAssistantError(str(err)) from err
                except ApiError as err:
                    raise HomeAssistantError(str(err)) from err

        hass.services.async_register(
            DOMAIN, SERVICE_BACKFILL, _backfill, schema=BACKFILL_SCHEMA
        )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: AsyncEnergyConfigEntry) -> bool:
    """Unload a config entry."""
    # Remove the service together with the last loaded entry.
    if len(hass.config_entries.async_loaded_entries(DOMAIN)) <= 1:
        hass.services.async_remove(DOMAIN, SERVICE_BACKFILL)
    return True
