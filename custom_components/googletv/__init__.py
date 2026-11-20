"""The Google TV integration: one ADB connection per TV for everything."""

from __future__ import annotations

from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.storage import STORAGE_DIR

from .adb import GoogleTvAuthError, GoogleTvClient, GoogleTvError, load_signer
from .const import ADB_KEY_FILE, CONF_ONLINE_LOOKUPS
from .coordinator import GoogleTvConfigEntry, GoogleTvCoordinator
from .online import get_lookups

PLATFORMS: list[Platform] = [
    Platform.BUTTON,
    Platform.MEDIA_PLAYER,
    Platform.REMOTE,
    Platform.SELECT,
    Platform.SENSOR,
]


async def async_get_client(hass: HomeAssistant, host: str, port: int) -> GoogleTvClient:
    """A client for a TV, signing in with Home Assistant's own ADB key."""
    signer = await hass.async_add_executor_job(
        load_signer, hass.config.path(STORAGE_DIR, ADB_KEY_FILE)
    )
    return GoogleTvClient(host, port, signer)


async def async_setup_entry(hass: HomeAssistant, entry: GoogleTvConfigEntry) -> bool:
    """Set up a Google TV from a config entry."""
    client = await async_get_client(hass, entry.data[CONF_HOST], entry.data[CONF_PORT])
    try:
        await client.async_connect()
        props = await client.async_get_props()
    except GoogleTvAuthError as err:
        # The TV forgot Home Assistant's key (debugging turned off and on, a reset)
        await client.async_close()
        raise ConfigEntryAuthFailed(str(err)) from err
    except GoogleTvError as err:
        await client.async_close()
        raise ConfigEntryNotReady(str(err)) from err

    lookups = None
    if entry.options.get(CONF_ONLINE_LOOKUPS, True):
        lookups = get_lookups(hass)
        try:
            await lookups.async_load()
        except BaseException:
            await client.async_close()
            raise
    coordinator = GoogleTvCoordinator(hass, entry, client, props, lookups)
    try:
        await coordinator.async_config_entry_first_refresh()
    except BaseException:
        # Set up again later with a connection of its own: close this one
        await client.async_close()
        raise
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def _async_options_updated(
    hass: HomeAssistant, entry: GoogleTvConfigEntry
) -> None:
    """Set the TV up again with its new options."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: GoogleTvConfigEntry) -> bool:
    """Unload a config entry and close its connection."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.client.async_close()
    return unloaded
