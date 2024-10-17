"""Example integration using DataUpdateCoordinator."""

from datetime import timedelta
import logging
import homeassistant.util.dt as dt_util
import requests
import json
from homeassistant.core import callback
from homeassistant.helpers.device_registry import format_mac as format_mac
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    statistics_during_period,
)
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.const import UnitOfEnergy
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

DAYS_TO_RETRIEVE = 10
SENSOR_ENERGY_NAME = "energy_consumption"
SENSOR_ENERGY_COST_NAME = "energy_cost"
sensor_name_kwh = DOMAIN + ":" + SENSOR_ENERGY_NAME
sensor_name_price = DOMAIN + ":" + SENSOR_ENERGY_COST_NAME

SENSORS: tuple[SensorEntityDescription, ...] = (
    SensorEntityDescription(
        key="sensor." + SENSOR_ENERGY_NAME,
        name="Energy consumption",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.ENERGY_KILO_WATT_HOUR,
    ),
    SensorEntityDescription(
        key="sensor." + SENSOR_ENERGY_COST_NAME,
        name="Energy cost",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement="kWh",
    ),
)


async def _get_statistics(days, hass):
    statistics_kwh = []
    statistcs_price = []

    try:
        # TODO: configurable API

        # get the data
        data = await get_instance(hass).async_add_executor_job(
            requests.get,
            "http://192.168.0.144:8000/get-meter-data?aggregation=HOURLY&numfiles="
            + str(days),
        )
        consumption_data = data.json()
        consumption_data = sorted(consumption_data, key=lambda x: x["ts"])
        first_timestamp = dt_util.utc_from_timestamp(consumption_data[0]["ts"])

        # get the last values to start counting from
        last_stats_kwh = await get_instance(hass).async_add_executor_job(
            statistics_during_period,
            hass,
            first_timestamp - timedelta(hours=2),
            first_timestamp,
            [sensor_name_kwh],
            ["hour"],
            {"consumption_kwh": "kwh"},
            ["sum"]
        )
        last_stats_chf = await get_instance(hass).async_add_executor_job(
            statistics_during_period,
            hass,
            first_timestamp - timedelta(hours=2),
            first_timestamp,
            [sensor_name_kwh],
            ["hour"],
            {"consumption_kwh": "kwh"},
            ["sum"]
        )
        if (
            len(last_stats_kwh) > 0
            and sensor_name_kwh in last_stats_kwh
            and len(last_stats_kwh[sensor_name_kwh]) > 0
        ):
            temp = last_stats_kwh[sensor_name_kwh]
            energy_sum = temp[len(temp) - 1]["sum"]
            if energy_sum is None:
                energy_sum = 0
        else:
            energy_sum = 0

        if (
            len(last_stats_chf) > 0
            and sensor_name_price in last_stats_kwh
            and len(last_stats_chf[sensor_name_price]) > 0
        ):
            temp = last_stats_chf[sensor_name_price]
            price_sum = temp[len(temp) - 1]["sum"]
            if price_sum is None:
                price_sum = 0
        else:
            price_sum = 0

        # TODO: configure field names
        for item in consumption_data:
            energy_sum = energy_sum + item["values"]["consumption_kwh"]
            price_sum = price_sum + item["values"]["price_chf"]

            statistics_kwh.append(
                {
                    "start": dt_util.utc_from_timestamp(item["ts"]),
                    "sum": energy_sum,
                }
            )

            statistcs_price.append(
                {
                    "start": dt_util.utc_from_timestamp(item["ts"]),
                    "sum": price_sum,
                }
            )

    except json.JSONDecodeError:
        _LOGGER.error("There has been an error")

    return {"price": statistcs_price, "kwh": statistics_kwh}


async def _insert_statistics(hass):

    metadata_kwh = {
        "source": DOMAIN,
        "statistic_id": DOMAIN + ":" + SENSOR_ENERGY_NAME,
        "unit_of_measurement": "kWh",
        "has_mean": False,
        "has_sum": True,
        "name": "Energy consumption",
    }
    metadata_price = {
        "source": DOMAIN,
        "statistic_id": DOMAIN + ":" + SENSOR_ENERGY_COST_NAME,
        "unit_of_measurement": "CHF",
        "has_mean": False,
        "has_sum": True,
        "name": "Energy price",
    }

    # load stats for the last 10 days
    statistics = await _get_statistics(DAYS_TO_RETRIEVE, hass)
    async_add_external_statistics(hass, metadata_kwh, statistics["kwh"])
    async_add_external_statistics(hass, metadata_price, statistics["price"])


async def async_setup_entry(hass, entry, async_add_entities):
    """Config entry example."""
    # assuming API object stored here by __init__.py
    # my_api = hass.data[DOMAIN][entry.entry_id]
    coordinator = JSONRetrievalCoordinator(hass, None)

    # Fetch initial data so we have data when entities subscribe
    #
    # If the refresh fails, async_config_entry_first_refresh will
    # raise ConfigEntryNotReady and setup will try again later
    #
    # If you do not want to retry setup on failure, use
    # coordinator.async_refresh() instead
    #
    await coordinator.async_config_entry_first_refresh()

    sensors = []
    for description in SENSORS:
        sensors.append(ElectricityEntity(coordinator, description))

    async_add_entities(sensors, True)

    return True


class JSONRetrievalCoordinator(DataUpdateCoordinator):
    """My custom coordinator."""

    def __init__(self, hass, my_api):
        """Initialize my coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            # Name of the data. For logging purposes.
            name="Daily",
            # Polling interval. Will only be polled if there are subscribers.
            update_interval=timedelta(hours=6),
        )

        self.my_api = my_api

    async def _async_update_data(self):
        """Fetch data from API endpoint.

        This is the place to pre-process the data to lookup tables
        so entities can quickly look up their data.
        """

        if "recorder" in self.hass.config.components:
            await _insert_statistics(self.hass)


class ElectricityEntity(CoordinatorEntity, SensorEntity):
    """An entity using CoordinatorEntity.

    The CoordinatorEntity class provides:
      should_poll
      async_update
      async_added_to_hass
      available

    """

    _attr_has_entity_name = True

    def __init__(self, coordinator, sensor):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_id = sensor.key
        self._attr_device_class = sensor.device_class
        self._attr_name = sensor.name
        self._attr_native_unit_of_measurement = sensor.native_unit_of_measurement
        self._attr_native_value = 0
        self._attr_unique_id = sensor.key + "-home"

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()
