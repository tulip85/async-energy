"""Load meter data from the API and import it as external statistics."""
from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import StatisticMeanType
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    statistics_during_period,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .api import async_fetch_hourly
from .archive import build_archive
from .const import (
    CONF_INSTALLATION_ID,
    CONF_PASSWORD,
    CONF_USERNAME,
    DAYS_TO_RETRIEVE,
    DOMAIN,
    STATISTIC_ID_KWH,
    STATISTIC_ID_PRICE,
)

_LOGGER = logging.getLogger(__name__)

UPDATE_INTERVAL = timedelta(hours=6)

# How far back to look for the statistic that precedes the first imported hour.
ANCHOR_LOOKBACK = timedelta(days=60)

METADATA_KWH = {
    "source": DOMAIN,
    "statistic_id": STATISTIC_ID_KWH,
    "unit_of_measurement": "kWh",
    "unit_class": "energy",
    "has_mean": False,
    "has_sum": True,
    "mean_type": StatisticMeanType.NONE,
    "name": "Energy consumption",
}
METADATA_PRICE = {
    "source": DOMAIN,
    "statistic_id": STATISTIC_ID_PRICE,
    "unit_of_measurement": "CHF",
    "unit_class": None,
    "has_mean": False,
    "has_sum": True,
    "mean_type": StatisticMeanType.NONE,
    "name": "Energy cost",
}


class StatisticsImporter:
    """Fetch meter data and import it as external statistics."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the importer."""
        self._hass = hass
        self._entry = entry

    async def _previous_sum(self, statistic_id: str, before: datetime) -> float:
        """Return the cumulative sum of the last statistic before `before`."""
        stats = await get_instance(self._hass).async_add_executor_job(
            statistics_during_period,
            self._hass,
            before - ANCHOR_LOOKBACK,
            before,
            {statistic_id},
            "hour",
            None,
            {"sum"},
        )
        rows = stats.get(statistic_id) or []
        if rows and rows[-1].get("sum") is not None:
            return float(rows[-1]["sum"])
        return 0.0

    async def async_import(self, days: int = DAYS_TO_RETRIEVE) -> None:
        """Fetch the latest `days` days and write them as statistics.

        Raises InvalidAuth for bad credentials, ApiError for other failures.
        """
        data = self._entry.data
        readings = await async_fetch_hourly(
            self._hass,
            data[CONF_USERNAME],
            data[CONF_PASSWORD],
            data[CONF_INSTALLATION_ID],
            days,
            build_archive(self._hass, self._entry.options),
        )
        items = sorted(
            ((r.start, r.kwh, r.chf) for r in readings), key=lambda x: x[0]
        )

        if not items:
            _LOGGER.warning("EKZ returned no data")
            return

        # Continue counting from the statistics stored before the first sample.
        # Re-importing hours that already exist is safe: they are overwritten
        # with the same values because the anchor stays the same.
        first_start = items[0][0]
        energy_sum = await self._previous_sum(STATISTIC_ID_KWH, first_start)
        price_sum = await self._previous_sum(STATISTIC_ID_PRICE, first_start)

        stats_kwh: list[dict[str, Any]] = []
        stats_price: list[dict[str, Any]] = []
        for start, kwh, price in items:
            energy_sum += kwh
            price_sum += price
            stats_kwh.append({"start": start, "sum": energy_sum})
            stats_price.append({"start": start, "sum": price_sum})

        async_add_external_statistics(self._hass, METADATA_KWH, stats_kwh)
        async_add_external_statistics(self._hass, METADATA_PRICE, stats_price)
