"""A button per installed app: press to open it (the TV wakes first)."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import GoogleTvConfigEntry, GoogleTvCoordinator
from .entity import GoogleTvEntity
from .parsers import App


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GoogleTvConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """A button for each app in the launcher, and for apps installed later."""
    coordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def add_new_apps() -> None:
        new = [a.package for a in coordinator.data.apps if a.package not in known]
        if new:
            known.update(new)
            async_add_entities(GoogleTvAppButton(coordinator, p) for p in new)

    add_new_apps()
    entry.async_on_unload(coordinator.async_add_listener(add_new_apps))


class GoogleTvAppButton(GoogleTvEntity, ButtonEntity):
    """Opens one app, named and pictured from its Play Store listing."""

    _attr_translation_key = "app"

    def __init__(self, coordinator: GoogleTvCoordinator, package: str) -> None:
        """Initialize the button."""
        super().__init__(coordinator, f"app_{package}")
        self._package = package

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
