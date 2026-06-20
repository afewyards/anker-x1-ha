"""Constants for the Anker SOLIX X1 integration."""

DOMAIN = "anker_x1"

DEFAULT_PORT = 502
DEFAULT_SLAVE = 1
CONF_SLAVE = "slave"

UPDATE_INTERVAL_SECONDS = 5

MAX_CHARGE_W = 6000
MAX_DISCHARGE_W = 6600

WORK_MODE_VPP = 3
WORK_MODE_APP = 20

PLATFORMS = ["sensor", "number", "select", "switch"]

PLANT_STATUS = {
    1: "On-grid",
    2: "Off-grid",
    3: "Standby",
    4: "Fault",
}

BATTERY_STATUS = {
    0: "Standby",
    1: "Charging",
    2: "Discharging",
    3: "Sleep",
}

WORK_MODE = {
    0: "Self-consumption",
    1: "Time-of-Use",
    2: "Backup-only",
    3: "VPP/3rd-party",
    4: "User-defined",
    5: "Socket-aggregation",
    20: "App-managed",
}
