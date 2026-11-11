"""The async-energy integration.

This integration has no entities: it only imports meter data from an external
API into Home Assistant's long-term statistics.
"""
from __future__ import annotations

from datetime import datetime
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.event import async_track_time_interval

from .api import ApiError
from .const import CONF_API_URL
from .importer import UPDATE_INTERVAL, StatisticsImporter

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up async-energy from a config entry."""
    importer = StatisticsImporter(hass, entry.data[CONF_API_URL])

    # Retry setup later if the API is not reachable yet.
    try:
        await importer.async_import()
    except ApiError as err:
        raise ConfigEntryNotReady(str(err)) from err

    async def _scheduled_import(_now: datetime) -> None:
        try:
            await importer.async_import()
        except ApiError as err:
            _LOGGER.warning("Could not update energy statistics: %s", err)

    entry.async_on_unload(
        async_track_time_interval(hass, _scheduled_import, UPDATE_INTERVAL)
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return True
