"""The Google TV integration: one ADB connection per TV for everything."""

from __future__ import annotations

import contextlib

from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import STORAGE_DIR, Store

from .adb import GoogleTvAuthError, GoogleTvClient, GoogleTvError, load_signer
from .app_client import AppClient
from .bridge import BridgeClient, BridgeError
from .const import (
    ADB_KEY_FILE,
    CONF_BRIDGE_TOKEN,
    CONF_CONNECTION,
    CONF_DASHBOARD_USER,
    CONF_INSTALL_BRIDGE,
    CONF_ONLINE_LOOKUPS,
    CONF_PROPS,
    CONNECTION_APP,
    DOMAIN,
)
from .coordinator import LIVE_STORAGE_VERSION, GoogleTvConfigEntry, GoogleTvCoordinator
from .online import get_lookups

PLATFORMS: list[Platform] = [
    Platform.BUTTON,
    Platform.EVENT,
    Platform.MEDIA_PLAYER,
    Platform.NOTIFY,
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
    """Set up a Google TV from a config entry: over ADB, or through its app alone."""
    client: GoogleTvClient | AppClient
    if entry.data.get(CONF_CONNECTION) == CONNECTION_APP:
        client = AppClient(
            BridgeClient(
                async_get_clientsession(hass),
                entry.data[CONF_HOST],
                entry.data.get(CONF_BRIDGE_TOKEN),
            )
        )
    else:
        client = await async_get_client(
            hass, entry.data[CONF_HOST], entry.data[CONF_PORT]
        )
    stored: dict[str, str] | None = entry.data.get(CONF_PROPS)
    try:
        await client.async_connect()
        props = await client.async_get_props()
    except GoogleTvAuthError as err:
        # The TV forgot Home Assistant's key (debugging turned off and on, a reset)
        await client.async_close()
        raise ConfigEntryAuthFailed(str(err)) from err
    except GoogleTvError as err:
        await client.async_close()
        if not stored:
            raise ConfigEntryNotReady(str(err)) from err
        # Off its network (a TV that drops it in standby): set up as off, from
        # what's known of it, and connect once it's back
        props = dict(stored)
    if props != stored:
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_PROPS: props}
        )

    lookups = None
    if entry.options.get(CONF_ONLINE_LOOKUPS, True):
        lookups = get_lookups(hass)
        try:
            await lookups.async_load()
        except BaseException:
            await client.async_close()
            raise
    coordinator = GoogleTvCoordinator(hass, entry, client, props, lookups)
    # Asked for when the TV was added: no repair about it meanwhile
    coordinator.installing = bool(entry.data.get(CONF_INSTALL_BRIDGE))
    try:
        await coordinator.async_config_entry_first_refresh()
    except BaseException:
        # Set up again later with a connection of its own: close this one
        await client.async_close()
        raise
    entry.runtime_data = coordinator
    try:
        await coordinator.async_load_live()
    except BaseException:
        await client.async_close()
        raise
    entry.async_on_unload(coordinator.async_stop_live)
    entry.async_on_unload(coordinator.async_watch_app_buttons())
    coordinator.async_start_events()
    coordinator.async_report_soon()
    if entry.data.get(CONF_INSTALL_BRIDGE):
        # Asked for when the TV was added: once
        hass.config_entries.async_update_entry(
            entry,
            data={k: v for k, v in entry.data.items() if k != CONF_INSTALL_BRIDGE},
        )
        if coordinator.bridge_installed:
            coordinator.installing = False
        else:
            entry.async_create_background_task(
                hass, coordinator.async_install_bridge_quietly(), f"{DOMAIN} TV app"
            )

    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except BaseException:
        await coordinator.async_stop_live()
        await client.async_close()
        raise
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    _remove_apps_device(hass, entry)
    return True


def _remove_apps_device(hass: HomeAssistant, entry: GoogleTvConfigEntry) -> None:
    """The "<TV> Apps" device from before 2.4: its buttons are the TV's now."""
    registry = dr.async_get(hass)
    unique = entry.unique_id or entry.entry_id
    device = registry.async_get_device(identifiers={(DOMAIN, f"{unique}_apps")})
    tv = registry.async_get_device(identifiers={(DOMAIN, unique)})
    if device is None or tv is None:
        return
    # Disabled buttons weren't set up, so weren't moved: moved now, as removing
    # the device would remove them
    entities = er.async_get(hass)
    for entity in er.async_entries_for_device(
        entities, device.id, include_disabled_entities=True
    ):
        entities.async_update_entity(entity.entity_id, device_id=tv.id)
    registry.async_remove_device(device.id)


async def _async_options_updated(
    hass: HomeAssistant, entry: GoogleTvConfigEntry
) -> None:
    """Set the TV up again with its new options (not for its stored props)."""
    if entry.options != entry.runtime_data.options:
        await hass.config_entries.async_reload(entry.entry_id)


async def async_remove_entry(hass: HomeAssistant, entry: GoogleTvConfigEntry) -> None:
    """Forget a removed TV: its live notifications, its user, its pairing.

    The TV app takes its pop-ups down and forgets Home Assistant, if it's
    reachable.
    """
    if token := entry.data.get(CONF_BRIDGE_TOKEN):
        bridge = BridgeClient(
            async_get_clientsession(hass), entry.data[CONF_HOST], token
        )
        with contextlib.suppress(BridgeError):
            await bridge.async_dismiss()
            await bridge.async_unpair()
    await Store(
        hass, LIVE_STORAGE_VERSION, f"{DOMAIN}.live.{entry.entry_id}"
    ).async_remove()
    if (user_id := entry.data.get(CONF_DASHBOARD_USER)) and (
        user := await hass.auth.async_get_user(user_id)
    ):
        await hass.auth.async_remove_user(user)


async def async_unload_entry(hass: HomeAssistant, entry: GoogleTvConfigEntry) -> bool:
    """Unload a config entry and close its connection."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.client.async_close()
    return unloaded
