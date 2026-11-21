"""An event entity per TV: its notifications' buttons pressed, dismissed, or failed.

From the TV app's event stream (googletv_event on the bus has every event).
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.event import EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import GoogleTvConfigEntry, GoogleTvCoordinator
from .entity import GoogleTvEntity

EVENT_TYPES = {
    "notification_action": "action",
    "notification_dismissed": "dismissed",
    # Its image, icon, clip or camera didn't load on the TV
    "notification_failed": "failed",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GoogleTvConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the TV's notification events."""
    async_add_entities([GoogleTvNotificationEvent(entry.runtime_data)])


class GoogleTvNotificationEvent(GoogleTvEntity, EventEntity):
    """A notification's button pressed (action), or it dismissed on the TV."""

    _attr_translation_key = "notification_events"
    _attr_event_types = list(EVENT_TYPES.values())
    # Events come when they come, whether the TV answers polls or not
    _available_offline = True

    def __init__(self, coordinator: GoogleTvCoordinator) -> None:
        """Initialize the entity."""
        super().__init__(coordinator, "notification_events")

    @property
    def available(self) -> bool:
        """Available once the TV app is installed and paired."""
        return super().available and self.coordinator.data.bridge_paired

    async def async_added_to_hass(self) -> None:
        """Listen to the TV app's notification events."""
        await super().async_added_to_hass()
        self.async_on_remove(self.coordinator.async_add_event_listener(self._event))

    @callback
    def _event(self, event: dict[str, Any]) -> None:
        attributes: dict[str, Any] = {"tag": event.get("tag")}
        if "action" in event:
            attributes["action"] = event["action"]
        for key in ("by", "media", "reason"):
            if key in event:
                attributes[key] = event[key]
        self._trigger_event(EVENT_TYPES[event["type"]], attributes)
        self.async_write_ha_state()
