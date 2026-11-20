"""The TV's HDMI input: shows the one on screen, and switches to another."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .coordinator import GoogleTvConfigEntry, GoogleTvCoordinator
from .entity import GoogleTvEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GoogleTvConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """The Input select, once the TV reports HDMI inputs."""
    coordinator = entry.runtime_data
    added = False

    @callback
    def add_when_inputs() -> None:
        nonlocal added
        if not added and coordinator.data.state.inputs:
            added = True
            async_add_entities([GoogleTvInputSelect(coordinator)])

    add_when_inputs()
    entry.async_on_unload(coordinator.async_add_listener(add_when_inputs))


class GoogleTvInputSelect(GoogleTvEntity, SelectEntity):
    """The HDMI inputs by the names given to them on the TV."""

    _attr_translation_key = "input"

    def __init__(self, coordinator: GoogleTvCoordinator) -> None:
        """Initialize the select."""
        super().__init__(coordinator, "input")

    @property
    def options(self) -> list[str]:
        """Every input ("Xbox", "HDMI 2")."""
        return [i.label for i in self._state.inputs]

    @property
    def current_option(self) -> str | None:
        """The input on screen; none while an app is (or the TV is off)."""
        state = self._state
        return state.input.label if state.awake and state.input else None

    async def async_select_option(self, option: str) -> None:
        """Switch to the input (waking the TV)."""
        tv_input = next((i for i in self._state.inputs if i.label == option), None)
        if tv_input is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unknown_source",
                translation_placeholders={"source": option},
            )
        await self.coordinator.async_select_input(tv_input.id)
