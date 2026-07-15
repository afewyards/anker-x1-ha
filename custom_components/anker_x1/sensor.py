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
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.restore_state import ExtraStoredData, RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import (
    BATTERY_STATUS,
    DOMAIN,
    METER_COMM_STATUS,
    OUTPUT_MODE,
    PLANT_STATUS,
)
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
        key="charge_power",
        name="Charge Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    AnkerX1SensorEntityDescription(
        key="discharge_power",
        name="Discharge Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    AnkerX1SensorEntityDescription(
        key="inverter_loss",
        name="Inverter Loss",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    AnkerX1SensorEntityDescription(
        key="backup_power",
        name="Backup Power",
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
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    AnkerX1SensorEntityDescription(
        key="dischargeable_power",
        name="Dischargeable Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
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
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    AnkerX1SensorEntityDescription(
        key="inverter_temperature",
        name="Inverter Temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
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
        key="battery_charge_total",
        name="Battery Charge Total",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    AnkerX1SensorEntityDescription(
        key="battery_discharge_total",
        name="Battery Discharge Total",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    AnkerX1SensorEntityDescription(
        key="grid_bought_total",
        name="Grid Bought Today",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    AnkerX1SensorEntityDescription(
        key="grid_fed_in_total",
        name="Grid Fed-in Today",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    AnkerX1SensorEntityDescription(
        key="battery_module_count",
        name="Battery Modules",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    AnkerX1SensorEntityDescription(
        key="battery_nominal_capacity",
        name="Battery Nominal Capacity",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY_STORAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    AnkerX1SensorEntityDescription(
        key="battery_pack_voltage",
        name="Battery Pack Voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
    # -- PV strings (primary measurements on DC-coupled systems) ------------
    AnkerX1SensorEntityDescription(
        key="pv_power",
        name="PV Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    AnkerX1SensorEntityDescription(
        key="usable_pv_power",
        name="Usable PV Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    AnkerX1SensorEntityDescription(
        key="pv1_power",
        name="PV1 Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    AnkerX1SensorEntityDescription(
        key="pv2_power",
        name="PV2 Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    # -- Meter block (external CHINT 3-phase meter, regs 10620-10659) -------
    AnkerX1SensorEntityDescription(
        key="meter_total_power",
        name="Meter Total Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
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
    entity_category: EntityCategory | None = None


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
        key="output_mode",
        name="Output Mode",
        mapping=OUTPUT_MODE,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    AnkerX1EnumSensorDescription(
        key="meter_comm_status",
        name="Meter Comm Status",
        mapping=METER_COMM_STATUS,
        entity_category=EntityCategory.DIAGNOSTIC,
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
        self._attr_entity_category = description.entity_category

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


@dataclass
class _RestoredBaseline(ExtraStoredData):
    """Persisted baseline (lifetime total at the start of the current day)."""

    baseline: float | None
    day: str | None

    def as_dict(self) -> dict[str, Any]:
        return {"baseline": self.baseline, "day": self.day}


class AnkerX1DailyEnergySensor(
    CoordinatorEntity[AnkerX1Coordinator], RestoreEntity, SensorEntity
):
    """Daily energy derived from a lifetime total, reset at local midnight.

    The device's own 'daily' registers don't reset on this firmware, so we
    track the lifetime total and subtract its value at the start of the day.
    The baseline is persisted (survives restarts) and re-based if HA was off
    across midnight.
    """

    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_suggested_display_precision = 1

    def __init__(
        self,
        coordinator: AnkerX1Coordinator,
        entry: ConfigEntry,
        key: str,
        name: str,
        source_key: str,
    ) -> None:
        super().__init__(coordinator)
        self._attr_name = name
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = coordinator.device_info
        self._source_key = source_key
        self._baseline: float | None = None
        self._baseline_day: str | None = None

    @staticmethod
    def _today() -> str:
        return dt_util.now().date().isoformat()

    def _current_total(self) -> float | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get(self._source_key)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_extra_data()
        if last is not None:
            data = last.as_dict()
            self._baseline = data.get("baseline")
            self._baseline_day = data.get("day")
        # First run, or HA was off across midnight -> rebase to current total.
        if self._baseline is None or self._baseline_day != self._today():
            total = self._current_total()
            if total is not None:
                self._baseline = total
                self._baseline_day = self._today()
        self.async_on_remove(
            async_track_time_change(
                self.hass, self._handle_midnight, hour=0, minute=0, second=0
            )
        )

    @callback
    def _handle_midnight(self, now) -> None:
        total = self._current_total()
        if total is not None:
            self._baseline = total
            self._baseline_day = self._today()
        self.async_write_ha_state()

    @property
    def extra_restore_state_data(self) -> ExtraStoredData:
        return _RestoredBaseline(self._baseline, self._baseline_day)

    @property
    def native_value(self) -> float | None:
        total = self._current_total()
        if total is None:
            return None
        if self._baseline is None:
            self._baseline = total
            self._baseline_day = self._today()
        if total < self._baseline:  # device counter rolled back -> rebase
            self._baseline = total
        return round(total - self._baseline, 2)


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

    # Daily energy (resets at local midnight), derived from lifetime totals.
    entities.append(
        AnkerX1DailyEnergySensor(
            coordinator, entry, "battery_charge_energy",
            "Battery Charge Energy", "battery_charge_total",
        )
    )
    entities.append(
        AnkerX1DailyEnergySensor(
            coordinator, entry, "battery_discharge_energy",
            "Battery Discharge Energy", "battery_discharge_total",
        )
    )

    async_add_entities(entities)
