"""A notify entity per TV: Home Assistant's notifications on its screen.

Through Raineworks TV Bridge, the TV app: a plain message pops up in the top
right. For an image, a camera, a corner, a duration or the panel, use the
googletv.notify action.
"""

from __future__ import annotations

from homeassistant.components.notify import NotifyEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import GoogleTvConfigEntry, GoogleTvCoordinator
from .entity import GoogleTvEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GoogleTvConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the TV's notify entity."""
    async_add_entities([GoogleTvNotify(entry.runtime_data)])


class GoogleTvNotify(GoogleTvEntity, NotifyEntity):
    """Pops a message up on the TV."""

    _attr_translation_key = "notifications"

    def __init__(self, coordinator: GoogleTvCoordinator) -> None:
        """Initialize the entity."""
        super().__init__(coordinator, "notify")

    @property
    def available(self) -> bool:
        """Available once TV Bridge is installed and paired."""
        return super().available and self.coordinator.data.bridge_paired

    async def async_send_message(self, message: str, title: str | None = None) -> None:
        """Pop the message up on the TV."""
        payload: dict[str, str] = {"message": message}
        if title:
            payload["title"] = title
        await self.coordinator.async_notify(payload)
