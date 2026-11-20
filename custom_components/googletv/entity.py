"""Base entity for a Google TV."""

from __future__ import annotations

from homeassistant.helpers.device_registry import (
    CONNECTION_BLUETOOTH,
    DeviceInfo,
    format_mac,
)
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import GoogleTvCoordinator
from .parsers import TvState


class GoogleTvEntity(CoordinatorEntity[GoogleTvCoordinator]):
    """An entity of one TV."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: GoogleTvCoordinator, key: str) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        entry = coordinator.config_entry
        assert entry is not None
        unique = entry.unique_id or entry.entry_id
        self._attr_unique_id = f"{unique}_{key}"
        props = coordinator.props
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, unique)},
            connections=(
                {(CONNECTION_BLUETOOTH, format_mac(props["bluetooth"]))}
                if props.get("bluetooth")
                else set()
            ),
            name=entry.title,
            manufacturer=props.get("manufacturer"),
            model=props.get("model"),
            sw_version=f"Android {props['android']}" if props.get("android") else None,
            serial_number=props.get("serial"),
        )

    @property
    def _state(self) -> TvState:
        """The latest poll."""
        return self.coordinator.data.state
