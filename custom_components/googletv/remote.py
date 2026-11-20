"""The TV's remote: key presses (the d-pad, Back, Home, media keys)."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from typing import Any

from homeassistant.components.remote import (
    ATTR_DELAY_SECS,
    ATTR_NUM_REPEATS,
    DEFAULT_DELAY_SECS,
    RemoteEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import GoogleTvConfigEntry, GoogleTvCoordinator, translate_errors
from .entity import GoogleTvEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GoogleTvConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the TV's remote."""
    async_add_entities([GoogleTvRemote(entry.runtime_data)])


class GoogleTvRemote(GoogleTvEntity, RemoteEntity):
    """Sends a TV's remote keys (``remote.send_command``: DPAD_UP, BACK, HOME…)."""

    _attr_name = None

    def __init__(self, coordinator: GoogleTvCoordinator) -> None:
        """Initialize the remote."""
        super().__init__(coordinator, "remote")

    @property
    def is_on(self) -> bool:
        """The screen is on."""
        return self._state.awake

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Wake the TV."""
        with translate_errors():
            await self.coordinator.client.async_key("WAKEUP")
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Put the TV to sleep."""
        with translate_errors():
            await self.coordinator.client.async_key("SLEEP")
        await self.coordinator.async_request_refresh()

    async def async_send_command(self, command: Iterable[str], **kwargs: Any) -> None:
        """Press each key in turn, ``num_repeats`` times, ``delay_secs`` apart."""
        repeats = kwargs.get(ATTR_NUM_REPEATS, 1)
        delay = kwargs.get(ATTR_DELAY_SECS, DEFAULT_DELAY_SECS)
        with translate_errors():
            for _ in range(repeats):
                for key in command:
                    await self.coordinator.client.async_key(key)
                    await asyncio.sleep(delay)
