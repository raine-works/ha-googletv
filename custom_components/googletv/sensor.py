"""Sensors: what the TV is doing (for automations), its app, and diagnostics.

``Activity`` is the one to trigger on: off, screensaver, home, app (one is
open, nothing playing), playing, paused or input (an HDMI input's on screen).
Dim the lights when it turns to playing, raise them at paused.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
    UnitOfInformation,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import GoogleTvConfigEntry, GoogleTvCoordinator, GoogleTvData
from .entity import GoogleTvEntity
from .parsers import (
    ACTIVITIES,
    CONNECTION_ETHERNET,
    CONNECTION_WIFI,
    app_name,
)


def _app(data: GoogleTvData) -> str | None:
    """The app in front, by name (none while the screen is off)."""
    state = data.state
    if not state.awake or not state.app:
        return None
    app = next((a for a in data.apps if a.package == state.app), None)
    return app.name if app else app_name(state.app)


def _last_boot(data: GoogleTvData) -> datetime | None:
    """When the TV started, to the minute."""
    return data.last_boot


@dataclass(frozen=True, kw_only=True)
class GoogleTvSensorDescription(SensorEntityDescription):
    """A sensor and how it reads the TV."""

    value: Callable[[GoogleTvData], Any]
    attributes: Callable[[GoogleTvData], dict[str, Any]] | None = None
    # Made only when this says the TV has it (a Wi-Fi signal on a wired TV…)
    exists: Callable[[GoogleTvData], bool] | None = None
    # Stays available, off, while the TV is off its network
    available_offline: bool = False


SENSORS: tuple[GoogleTvSensorDescription, ...] = (
    GoogleTvSensorDescription(
        key="activity",
        translation_key="activity",
        available_offline=True,
        device_class=SensorDeviceClass.ENUM,
        options=list(ACTIVITIES),
        value=lambda data: data.state.activity_state,
        attributes=lambda data: {
            "app_id": data.state.app if data.state.awake else None,
            "input": data.state.input.label
            if data.state.awake and data.state.input
            else None,
        },
    ),
    GoogleTvSensorDescription(
        key="app",
        translation_key="current_app",
        value=_app,
        attributes=lambda data: {
            "package": data.state.app if data.state.awake else None
        },
    ),
    GoogleTvSensorDescription(
        key="connection",
        translation_key="connection",
        device_class=SensorDeviceClass.ENUM,
        options=[CONNECTION_ETHERNET, CONNECTION_WIFI],
        entity_category=EntityCategory.DIAGNOSTIC,
        value=lambda data: data.diagnostics.connection,
    ),
    GoogleTvSensorDescription(
        key="ip_address",
        translation_key="ip_address",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value=lambda data: data.diagnostics.ip_address,
    ),
    GoogleTvSensorDescription(
        key="wifi_signal",
        translation_key="wifi_signal",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value=lambda data: data.diagnostics.wifi_signal,
        exists=lambda data: data.diagnostics.connection == CONNECTION_WIFI,
    ),
    GoogleTvSensorDescription(
        key="storage_used",
        translation_key="storage_used",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value=lambda data: data.diagnostics.storage_used,
    ),
    GoogleTvSensorDescription(
        key="storage_free",
        translation_key="storage_free",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.MEGABYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        suggested_display_precision=1,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value=lambda data: data.diagnostics.storage_free_mb,
    ),
    GoogleTvSensorDescription(
        key="memory_free",
        translation_key="memory_free",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.MEGABYTES,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value=lambda data: data.diagnostics.memory_free_mb,
    ),
    GoogleTvSensorDescription(
        key="tv_app",
        translation_key="tv_app",
        entity_category=EntityCategory.DIAGNOSTIC,
        available_offline=True,
        value=lambda data: data.bridge_version,
        attributes=lambda data: {"build": data.bridge_build},
        # Once the TV app has said which it is
        exists=lambda data: data.bridge_version is not None,
    ),
    GoogleTvSensorDescription(
        key="last_boot",
        translation_key="last_boot",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value=_last_boot,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GoogleTvConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the TV's sensors."""
    coordinator = entry.runtime_data
    added: set[str] = set()

    @callback
    def add_sensors() -> None:
        """Add the sensors the TV has, and later ones it turns out to have."""
        new = [
            d
            for d in SENSORS
            if d.key not in added and (d.exists is None or d.exists(coordinator.data))
        ]
        if new:
            added.update(d.key for d in new)
            async_add_entities(GoogleTvSensor(coordinator, d) for d in new)

    add_sensors()
    entry.async_on_unload(coordinator.async_add_listener(add_sensors))


class GoogleTvSensor(GoogleTvEntity, SensorEntity):
    """One of the TV's sensors."""

    entity_description: GoogleTvSensorDescription

    def __init__(
        self,
        coordinator: GoogleTvCoordinator,
        description: GoogleTvSensorDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, description.key)
        self.entity_description = description
        self._available_offline = description.available_offline

    @property
    def native_value(self) -> Any:
        """The sensor's reading."""
        return self.entity_description.value(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """The sensor's attributes, if it has any."""
        attributes = self.entity_description.attributes
        return attributes(self.coordinator.data) if attributes else None
