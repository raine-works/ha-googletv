"""Buttons: the remote's keys on the TV, and one per app.

The keys (Home, Back, the d-pad, OK, playback, volume, Settings) are the TV's
own controls; each app's button opens it, waking the TV first. An app left
out of Home Assistant (its switch in the TV app, or its button disabled here)
has its button disabled.
"""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .app_client import APP_KEYS
from .coordinator import GoogleTvConfigEntry, GoogleTvCoordinator, translate_errors
from .entity import GoogleTvEntity
from .parsers import App


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GoogleTvConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """The remote's keys, and a button for each app (and apps installed later)."""
    coordinator = entry.runtime_data
    # Through the TV app alone: only the keys an app can press
    async_add_entities(
        GoogleTvKeyButton(coordinator, d)
        for d in KEYS
        if not coordinator.app_only or d.keycode in APP_KEYS
    )
    known: set[str] = set()

    @callback
    def add_new_apps() -> None:
        new = [a.package for a in coordinator.data.apps if a.package not in known]
        if new:
            known.update(new)
            async_add_entities(GoogleTvAppButton(coordinator, p) for p in new)

    add_new_apps()
    entry.async_on_unload(coordinator.async_add_listener(add_new_apps))


@dataclass(frozen=True, kw_only=True)
class GoogleTvKeyDescription(ButtonEntityDescription):
    """A remote key: the ``KEYCODES`` name it presses."""

    keycode: str


KEYS: tuple[GoogleTvKeyDescription, ...] = tuple(
    GoogleTvKeyDescription(key=key, translation_key=key, keycode=keycode)
    for key, keycode in (
        ("home", "HOME"),
        ("back", "BACK"),
        ("up", "DPAD_UP"),
        ("down", "DPAD_DOWN"),
        ("left", "DPAD_LEFT"),
        ("right", "DPAD_RIGHT"),
        ("select", "DPAD_CENTER"),
        ("play_pause", "MEDIA_PLAY_PAUSE"),
        ("volume_up", "VOLUME_UP"),
        ("volume_down", "VOLUME_DOWN"),
        ("mute", "VOLUME_MUTE"),
        ("settings", "SETTINGS"),
    )
)


class GoogleTvKeyButton(GoogleTvEntity, ButtonEntity):
    """Presses one of the remote's keys."""

    entity_description: GoogleTvKeyDescription

    def __init__(
        self, coordinator: GoogleTvCoordinator, description: GoogleTvKeyDescription
    ) -> None:
        """Initialize the button."""
        super().__init__(coordinator, f"key_{description.key}")
        self.entity_description = description

    async def async_press(self) -> None:
        """Press the key."""
        with translate_errors():
            await self.coordinator.client.async_key(self.entity_description.keycode)
        await self.coordinator.async_request_refresh()


class GoogleTvAppButton(GoogleTvEntity, ButtonEntity):
    """Opens one app, named and pictured from its Play Store listing."""

    _attr_translation_key = "app"

    def __init__(self, coordinator: GoogleTvCoordinator, package: str) -> None:
        """Initialize the button."""
        super().__init__(coordinator, f"app_{package}")
        self._package = package
        # Made disabled for an app that's left out
        self._attr_entity_registry_enabled_default = (
            package not in coordinator.data.hidden_apps
        )

    @property
    def _app(self) -> App | None:
        return next(
            (a for a in self.coordinator.data.apps if a.package == self._package),
            None,
        )

    @property
    def available(self) -> bool:
        """Unavailable once the app is uninstalled."""
        return super().available and self._app is not None

    @property
    def name(self) -> str:
        """The app's name."""
        app = self._app
        return app.name if app else self._package

    @property
    def entity_picture(self) -> str | None:
        """The app's icon."""
        app = self._app
        return app.icon if app else None

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        """The app's package, for automations and dashboards."""
        return {"package": self._package}

    async def async_press(self) -> None:
        """Open the app."""
        if app := self._app:
            await self.coordinator.async_open_app(app)
