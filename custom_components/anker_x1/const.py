"""Constants for the Anker SOLIX X1 integration."""

DOMAIN = "anker_x1"

DEFAULT_PORT = 502
DEFAULT_SLAVE = 1
CONF_SLAVE = "slave"

# Modbus poll rate (seconds). Default, plus bounds for the options flow.
DEFAULT_SCAN_INTERVAL = 5
MIN_SCAN_INTERVAL = 1
MAX_SCAN_INTERVAL = 600

# PV-connected flag.  When False the coordinator pins all PV-derived values to
# 0, suppressing phantom solar that some firmware builds misattribute to PV
# when there is no PV string attached.
CONF_PV_CONNECTED = "pv_connected"
DEFAULT_PV_CONNECTED = True

MAX_CHARGE_W = 6000
MAX_DISCHARGE_W = 6600

# Nominal capacity of a single Anker SOLIX X1 battery module (kWh). Total pack
# capacity = battery_module_count (reg 10249) x this.
BATTERY_MODULE_KWH = 5

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

OUTPUT_MODE = {
    0: "L/N",
    1: "L1/L2/L3/N",
    3: "Three-phase (3W)",
}

METER_COMM_STATUS = {
    0: "Normal",
    1: "Offline",
    3: "Fault",
}
