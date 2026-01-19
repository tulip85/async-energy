"""The async-energy integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
import logging
import requests

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]

API_URL = "http://192.168.0.144:8000/get-meter-data"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up async-energy from a config entry."""
    # Check API connectivity before forwarding to platforms
    try:
        response = await hass.async_add_executor_job(
            requests.get,
            f"{API_URL}?aggregation=HOURLY&numfiles=1",
        )
        response.raise_for_status()
    except requests.RequestException as err:
        _LOGGER.error("Failed to connect to energy API: %s", err)
        raise ConfigEntryNotReady(f"Failed to connect to energy API: {err}") from err

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {"api_url": API_URL}

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
