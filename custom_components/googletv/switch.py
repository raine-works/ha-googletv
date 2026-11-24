"""Pop-ups on the TV, on or off: the TV app's own switch, from Home Assistant.

Off, every notification is handled as a blocked one (the panel, or nowhere,
as the app's "When pop-ups are off" says), whatever's on screen; a
notification sent with ``ignore_rules`` still pops up. For a movie mode, say.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import GoogleTvConfigEntry, GoogleTvCoordinator
from .entity import GoogleTvEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GoogleTvConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """The Pop-ups switch, once the TV app says it has one (2.7 and later)."""
    coordinator = entry.runtime_data
    added = False

    @callback
    def add_when_supported() -> None:
        nonlocal added
        if not added and "popups" in (coordinator.app_rules or {}):
            added = True
            async_add_entities([GoogleTvPopupsSwitch(coordinator)])

    add_when_supported()
    entry.async_on_unload(coordinator.async_add_listener(add_when_supported))


class GoogleTvPopupsSwitch(GoogleTvEntity, SwitchEntity):
    """Whether notifications pop up on the TV at all."""

    _attr_translation_key = "popups"
    # Switched while the TV is off (movie mode starting first): the app takes
    # it when it's back
    _available_offline = True

    def __init__(self, coordinator: GoogleTvCoordinator) -> None:
        """Initialize the switch."""
        super().__init__(coordinator, "popups")

    @property
    def is_on(self) -> bool:
        """On unless switched off, here or on the TV."""
        return (self.coordinator.app_rules or {}).get("popups", True) is not False

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Notifications pop up again (each app's and input's switch still counts)."""
        await self.coordinator.async_set_app_rules({"popups": True})

    async def async_turn_off(self, **kwargs: Any) -> None:
        """No pop-ups, over anything, until switched on again."""
        await self.coordinator.async_set_app_rules({"popups": False})
