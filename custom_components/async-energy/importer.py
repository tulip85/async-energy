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
from homeassistant.core import HomeAssistant
import homeassistant.util.dt as dt_util

from .api import ApiError, async_fetch_meter_data
from .const import (
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

    def __init__(self, hass: HomeAssistant, api_url: str) -> None:
        """Initialize the importer."""
        self._hass = hass
        self._api_url = api_url

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

    async def async_import(self) -> None:
        """Fetch the latest data and write it as statistics.

        Raises ApiError if the API is unreachable or returns unusable data.
        """
        raw = await async_fetch_meter_data(self._hass, self._api_url, DAYS_TO_RETRIEVE)

        try:
            items = sorted(
                (
                    (
                        dt_util.utc_from_timestamp(item["ts"]).replace(
                            minute=0, second=0, microsecond=0
                        ),
                        float(item["values"]["consumption_kwh"]),
                        float(item["values"]["price_chf"]),
                    )
                    for item in raw
                ),
                key=lambda x: x[0],
            )
        except (KeyError, TypeError, ValueError) as err:
            raise ApiError(f"Unexpected data format from energy API: {err!r}") from err

        if not items:
            _LOGGER.warning("Energy API returned no data")
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
