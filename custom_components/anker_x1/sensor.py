"""Sensor platform for Anker SOLIX X1 integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import BATTERY_STATUS, DOMAIN, PLANT_STATUS, WORK_MODE
from .coordinator import AnkerX1Coordinator


# ---------------------------------------------------------------------------
# Numeric sensor descriptions
# ---------------------------------------------------------------------------

@dataclass(frozen=True, kw_only=True)
class AnkerX1SensorEntityDescription(SensorEntityDescription):
    """Describe an Anker X1 numeric sensor."""


NUMERIC_SENSOR_DESCRIPTIONS: tuple[AnkerX1SensorEntityDescription, ...] = (
    AnkerX1SensorEntityDescription(
        key="battery_power",
        name="Battery Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    AnkerX1SensorEntityDescription(
        key="grid_power",
        name="Grid Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    AnkerX1SensorEntityDescription(
        key="load_power",
        name="Load Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    AnkerX1SensorEntityDescription(
        key="pv_power",
        name="PV Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    AnkerX1SensorEntityDescription(
        key="ac_active_power",
        name="AC Active Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    AnkerX1SensorEntityDescription(
        key="rechargeable_power",
        name="Rechargeable Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    AnkerX1SensorEntityDescription(
        key="dischargeable_power",
        name="Dischargeable Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    AnkerX1SensorEntityDescription(
        key="soc",
        name="Battery SOC",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    AnkerX1SensorEntityDescription(
        key="soh",
        name="Battery SOH",
        native_unit_of_measurement=PERCENTAGE,
        device_class=None,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    AnkerX1SensorEntityDescription(
        key="grid_voltage",
        name="Grid Voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    AnkerX1SensorEntityDescription(
        key="grid_frequency",
        name="Grid Frequency",
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        device_class=SensorDeviceClass.FREQUENCY,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    AnkerX1SensorEntityDescription(
        key="inverter_temperature",
        name="Inverter Temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    AnkerX1SensorEntityDescription(
        key="pv_energy_today",
        name="PV Energy Today",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    AnkerX1SensorEntityDescription(
        key="pv_energy_total",
        name="PV Energy Total",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    AnkerX1SensorEntityDescription(
        key="battery_charge_today",
        name="Battery Charge Today",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    AnkerX1SensorEntityDescription(
        key="grid_bought_total",
        name="Grid Bought Total",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    AnkerX1SensorEntityDescription(
        key="grid_fed_in_total",
        name="Grid Fed-in Total",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
)


# ---------------------------------------------------------------------------
# Enum/text sensor descriptions
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AnkerX1EnumSensorDescription:
    """Describe an Anker X1 enum/status sensor."""

    key: str
    name: str
    mapping: dict[int, str]


ENUM_SENSOR_DESCRIPTIONS: tuple[AnkerX1EnumSensorDescription, ...] = (
    AnkerX1EnumSensorDescription(
        key="plant_status",
        name="Plant Status",
        mapping=PLANT_STATUS,
    ),
    AnkerX1EnumSensorDescription(
        key="battery_status",
        name="Battery Status",
        mapping=BATTERY_STATUS,
    ),
    AnkerX1EnumSensorDescription(
        key="work_mode",
        name="Work Mode",
        mapping=WORK_MODE,
    ),
)


# ---------------------------------------------------------------------------
# Diagnostic sensor descriptions
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AnkerX1DiagnosticSensorDescription:
    """Describe an Anker X1 diagnostic string sensor."""

    key: str
    name: str


DIAGNOSTIC_SENSOR_DESCRIPTIONS: tuple[AnkerX1DiagnosticSensorDescription, ...] = (
    AnkerX1DiagnosticSensorDescription(key="model", name="Model"),
    AnkerX1DiagnosticSensorDescription(key="serial", name="Serial"),
)


# ---------------------------------------------------------------------------
# Entity classes
# ---------------------------------------------------------------------------

class AnkerX1Sensor(CoordinatorEntity[AnkerX1Coordinator], SensorEntity):
    """Base sensor entity for Anker SOLIX X1."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: AnkerX1Coordinator,
        entry: ConfigEntry,
        key: str,
        name: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._key = key
        self._attr_name = name
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = coordinator.device_info


class AnkerX1NumericSensor(AnkerX1Sensor):
    """Numeric sensor for Anker SOLIX X1."""

    entity_description: AnkerX1SensorEntityDescription

    def __init__(
        self,
        coordinator: AnkerX1Coordinator,
        entry: ConfigEntry,
        description: AnkerX1SensorEntityDescription,
    ) -> None:
        """Initialize the numeric sensor."""
        super().__init__(coordinator, entry, description.key, description.name)
        self.entity_description = description
        self._attr_native_unit_of_measurement = description.native_unit_of_measurement
        self._attr_device_class = description.device_class
        self._attr_state_class = description.state_class

    @property
    def native_value(self) -> Any:
        """Return the sensor value."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get(self._key)


class AnkerX1EnumSensor(AnkerX1Sensor):
    """Enum/status sensor for Anker SOLIX X1."""

    def __init__(
        self,
        coordinator: AnkerX1Coordinator,
        entry: ConfigEntry,
        description: AnkerX1EnumSensorDescription,
    ) -> None:
        """Initialize the enum sensor."""
        super().__init__(coordinator, entry, description.key, description.name)
        self._mapping = description.mapping

    @property
    def native_value(self) -> str | None:
        """Return mapped string value."""
        if self.coordinator.data is None:
            return None
        raw = self.coordinator.data.get(self._key)
        if raw is None:
            return None
        return self._mapping.get(int(raw), "Unknown")


class AnkerX1DiagnosticSensor(AnkerX1Sensor):
    """Diagnostic string sensor for Anker SOLIX X1."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: AnkerX1Coordinator,
        entry: ConfigEntry,
        description: AnkerX1DiagnosticSensorDescription,
    ) -> None:
        """Initialize the diagnostic sensor."""
        super().__init__(coordinator, entry, description.key, description.name)

    @property
    def native_value(self) -> str | None:
        """Return the diagnostic string value."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get(self._key)


# ---------------------------------------------------------------------------
# Platform setup
# ---------------------------------------------------------------------------

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Anker SOLIX X1 sensors from a config entry."""
    coordinator: AnkerX1Coordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[SensorEntity] = []

    for description in NUMERIC_SENSOR_DESCRIPTIONS:
        entities.append(AnkerX1NumericSensor(coordinator, entry, description))

    for description in ENUM_SENSOR_DESCRIPTIONS:
        entities.append(AnkerX1EnumSensor(coordinator, entry, description))

    for description in DIAGNOSTIC_SENSOR_DESCRIPTIONS:
        entities.append(AnkerX1DiagnosticSensor(coordinator, entry, description))

    async_add_entities(entities)
