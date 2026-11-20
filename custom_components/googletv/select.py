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
        return [i.label for i in self._shown]

    @property
    def _shown(self) -> list:
        """The inputs, but those left out (the TV app's switches)."""
        hidden = self.coordinator.data.hidden_inputs
        return [i for i in self._state.inputs if i.id not in hidden]

    @property
    def icon(self) -> str:
        """The icon of the input on screen (an Xbox's…), else an HDMI port's."""
        state = self._state
        if state.awake and state.input:
            return state.input.icon
        return "mdi:video-input-hdmi"

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Each input's icon, kind and CEC device, for dashboards."""
        return {
            "inputs": [
                {
                    "name": i.label,
                    "port": i.port,
                    "icon": i.icon,
                    "kind": i.kind.key,
                    "device": i.device,
                }
                for i in self._shown
            ]
        }

    @property
    def current_option(self) -> str | None:
        """The input on screen; none on an app, off, or on an input left out."""
        state = self._state
        if not state.awake or not state.input:
            return None
        if state.input.id in self.coordinator.data.hidden_inputs:
            return None
        return state.input.label

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
