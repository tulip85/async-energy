"""Constants for the async-energy integration."""

DOMAIN = "asyncenergy"

CONF_API_URL = "api_url"
CONF_LOCATION_NAME = "location_name"

METER_DATA_PATH = "/get-meter-data"
DAYS_TO_RETRIEVE = 10
REQUEST_TIMEOUT = 30

STATISTIC_ID_KWH = f"{DOMAIN}:energy_consumption"
STATISTIC_ID_PRICE = f"{DOMAIN}:energy_cost"
