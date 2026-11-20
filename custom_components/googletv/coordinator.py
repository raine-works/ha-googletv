"""Data update coordinator for a Google TV."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .adb import GoogleTvClient, GoogleTvError
from .const import APPS_INTERVAL, DOMAIN, SCAN_INTERVAL
from .parsers import App, TvState

_LOGGER = logging.getLogger(__name__)

type GoogleTvConfigEntry = ConfigEntry[GoogleTvCoordinator]


@dataclass
class GoogleTvData:
    """What the entities show: the latest poll and the launcher's apps."""

    state: TvState
    apps: list[App] = field(default_factory=list)


@contextmanager
def translate_errors() -> Iterator[None]:
    """Re-raise client errors from user actions as HomeAssistantError."""
    try:
        yield
    except GoogleTvError as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="command_failed",
            translation_placeholders={"error": str(err)},
        ) from err


class GoogleTvCoordinator(DataUpdateCoordinator[GoogleTvData]):
    """Reads one TV every few seconds over its ADB connection."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: GoogleTvConfigEntry,
        client: GoogleTvClient,
        props: dict[str, str],
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
            config_entry=entry,
        )
        self.client = client
        self.props = props
        self._apps: list[App] = []
        self._apps_read_at: datetime | None = None

    async def _async_update_data(self) -> GoogleTvData:
        """Read the TV, and its apps when they're due."""
        try:
            state = await self.client.async_get_state()
            now = dt_util.utcnow()
            if self._apps_read_at is None or now - self._apps_read_at >= APPS_INTERVAL:
                self._apps = await self.client.async_get_apps()
                self._apps_read_at = now
        except GoogleTvError as err:
            raise UpdateFailed(f"Can't read the TV: {err}") from err
        return GoogleTvData(state=state, apps=self._apps)
