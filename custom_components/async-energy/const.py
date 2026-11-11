"""Constants for the async-energy integration."""

DOMAIN = "asyncenergy"

CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_INSTALLATION_ID = "installation_id"
CONF_LOCATION_NAME = "location_name"

PORTAL_HOST = "my.ekz.ch"
LOGIN_URL = f"https://{PORTAL_HOST}/login"
CONSUMPTION_URL = (
    f"https://{PORTAL_HOST}/api/portal-services/consumption-view/v1/consumption-data"
)
TYPE_15MIN = "PK_VERB_15MIN"
TYPE_DAILY = "PK_VERB_TAG_EDM"
# A detailed (15 minute) response must contain these keys to be accepted.
DETAILED_KEYS = ("seriesHt", "seriesNt")

LOCAL_TIMEZONE = "Europe/Zurich"
RAW_DATA_DIR = "ekz_raw"  # relative to the Home Assistant config directory

# Days (ending yesterday) fetched on every scheduled update.
DAYS_TO_RETRIEVE = 8
MAX_BACKFILL_DAYS = 366
REQUEST_TIMEOUT = 30

STATISTIC_ID_KWH = f"{DOMAIN}:energy_consumption"
STATISTIC_ID_PRICE = f"{DOMAIN}:energy_cost"

SERVICE_BACKFILL = "backfill"
ATTR_DAYS = "days"

# Optional archive of the raw responses (off by default).
CONF_ARCHIVE = "archive"
ARCHIVE_NONE = "none"
ARCHIVE_LOCAL = "local"
ARCHIVE_DRIVE = "google_drive"
CONF_DRIVE_CREDENTIALS = "drive_service_account_json"
CONF_DRIVE_FOLDER_ID = "drive_folder_id"

# Optional user-defined tariff periods (YAML text); the bundled default is used if unset.
CONF_TARIFFS = "tariffs"
ISSUE_MISSING_TARIFF = "missing_tariff"
