"""Client helpers for the energy meter API."""
from __future__ import annotations

from typing import Any

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import METER_DATA_PATH, REQUEST_TIMEOUT


class ApiError(Exception):
    """Raised when the energy API cannot be reached or returns bad data."""


def build_url(api_url: str) -> str:
    """Return the full meter-data endpoint for a user supplied base URL."""
    base = api_url.strip().rstrip("/")
    if base.endswith(METER_DATA_PATH):
        base = base[: -len(METER_DATA_PATH)]
    return base + METER_DATA_PATH


async def async_fetch_meter_data(
    hass: HomeAssistant, api_url: str, days: int
) -> list[dict[str, Any]]:
    """Fetch hourly meter data for the last `days` files."""
    session = async_get_clientsession(hass)
    try:
        async with session.get(
            build_url(api_url),
            params={"aggregation": "HOURLY", "numfiles": days},
            timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
        ) as response:
            response.raise_for_status()
            data = await response.json(content_type=None)
    except (aiohttp.ClientError, TimeoutError, ValueError) as err:
        raise ApiError(f"Error talking to energy API: {err}") from err

    if not isinstance(data, list):
        raise ApiError("Unexpected response from energy API (expected a list)")
    return data
