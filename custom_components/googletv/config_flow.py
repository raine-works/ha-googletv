"""Config flow for a Google TV.

The TV needs network debugging on (Settings → System → Developer options:
USB debugging, and Network or Wireless debugging where it's separate). The
first connection shows "Allow USB debugging?" with Home Assistant's key on the
TV: tick Always allow and choose Allow. The flow waits up to a minute for it.

TVs are also found on their own: every Google TV announces
``_androidtvremote2._tcp`` over mDNS, with its name and Bluetooth address
(``bt``). One whose ADB port answers is offered; the Bluetooth address is the
entry's unique id (read over ADB too), so a TV already set up isn't offered
again, and its entry follows it to a new address.

A TV with the app (Google TV by Raineworks) announces ``_rwtvbridge._tcp`` too:
it's offered even with network debugging off, and the flow says how to turn
it on. Adding a TV without the app offers to install it.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any

from homeassistant.config_entries import (
    SOURCE_REAUTH,
    SOURCE_RECONFIGURE,
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.core import callback
from homeassistant.helpers.device_registry import format_mac
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
import voluptuous as vol

from . import async_get_client
from .adb import GoogleTvAuthError, GoogleTvError
from .bridge import BRIDGE_SERVICE_TYPE
from .const import (
    CONF_DASHBOARD_CONTROLS,
    CONF_INSTALL_BRIDGE,
    CONF_ONLINE_LOOKUPS,
    DEFAULT_PORT,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

PROBE_TIMEOUT_S = 3


async def _adb_port_open(host: str, port: int) -> bool:
    """Whether the TV answers on its ADB port (network debugging is on)."""
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), PROBE_TIMEOUT_S
        )
    except (OSError, TimeoutError):
        return False
    writer.close()
    with contextlib.suppress(OSError):
        await writer.wait_closed()
    return True


def _tv_id(props: dict[str, str]) -> str | None:
    """The TV's unique id: its Bluetooth address, else its serial."""
    if bluetooth := props.get("bluetooth"):
        return format_mac(bluetooth)
    return props.get("serial")


# The app's mDNS name before 2.0: "Raineworks TV Bridge <the TV's name>"
OLD_BRIDGE_PREFIX = "Raineworks TV Bridge "


def _schema(
    host: str = "", port: int = DEFAULT_PORT, name: str = "", install: bool = True
) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_HOST, default=host): str,
            vol.Required(CONF_PORT, default=port): vol.All(int, vol.Range(1, 65535)),
            vol.Optional(CONF_NAME, default=name): str,
            vol.Required(CONF_INSTALL_BRIDGE, default=install): bool,
        }
    )


class GoogleTvConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add a Google TV by its address."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> GoogleTvOptionsFlow:
        """The TV's options."""
        return GoogleTvOptionsFlow()

    def __init__(self) -> None:
        """Start a flow."""
        self._host = ""
        self._name = ""
        # Found by the app's own announcement: it's installed
        self._has_app = False

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the TV's address, then connect, waiting for its prompt."""
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            port = user_input[CONF_PORT]
            client = await async_get_client(self.hass, host, port)
            try:
                props = await client.async_pair()
            except GoogleTvAuthError as err:
                _LOGGER.debug("The TV didn't accept the key: %s", err)
                errors["base"] = "not_authorized"
            except GoogleTvError as err:
                _LOGGER.debug("Can't reach the TV: %s", err)
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error adding the TV")
                errors["base"] = "unknown"
            else:
                await client.async_close()
                return await self._async_finish(
                    host,
                    port,
                    user_input.get(CONF_NAME, "").strip(),
                    props,
                    install=user_input.get(CONF_INSTALL_BRIDGE, False),
                )
            await client.async_close()

        defaults = user_input or {}
        return self.async_show_form(
            step_id="user",
            data_schema=_schema(
                defaults.get(CONF_HOST, ""),
                defaults.get(CONF_PORT, DEFAULT_PORT),
                defaults.get(CONF_NAME, ""),
                defaults.get(CONF_INSTALL_BRIDGE, True),
            ),
            errors=errors,
        )

    async def async_step_zeroconf(
        self, discovery_info: ZeroconfServiceInfo
    ) -> ConfigFlowResult:
        """A Google TV announced itself: offer it if its ADB port answers.

        One the app announced is offered with debugging off too: it says how
        to turn it on.
        """
        if discovery_info.ip_address.version != 4:
            return self.async_abort(reason="not_ipv4_address")
        host = str(discovery_info.ip_address)
        name = discovery_info.name.split("._", 1)[0].strip()
        self._has_app = discovery_info.type == BRIDGE_SERVICE_TYPE
        if self._has_app:
            name = discovery_info.properties.get("name") or name.removeprefix(
                OLD_BRIDGE_PREFIX
            )
        if bluetooth := discovery_info.properties.get("bt"):
            await self.async_set_unique_id(format_mac(bluetooth))
            self._abort_if_unique_id_configured(updates={CONF_HOST: host})
        # Also a TV set up by its address (or, before 0.2, by its serial)
        self._async_abort_entries_match({CONF_HOST: host})
        # One TV, two announcements (Google's remote service and the app)
        if any(
            flow["context"].get(CONF_HOST) == host
            for flow in self._async_in_progress(include_uninitialized=True)
        ):
            return self.async_abort(reason="already_in_progress")
        self.context[CONF_HOST] = host
        self._host, self._name = host, name
        self.context["title_placeholders"] = {"name": name}
        if not await _adb_port_open(host, DEFAULT_PORT):
            if self._has_app:
                return await self.async_step_enable_debugging()
            return self.async_abort(reason="adb_off")
        return await self.async_step_zeroconf_confirm()

    async def async_step_enable_debugging(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """The app is on the TV, debugging isn't: how to turn it on."""
        errors: dict[str, str] = {}
        if user_input is not None:
            if await _adb_port_open(self._host, DEFAULT_PORT):
                return await self.async_step_zeroconf_confirm()
            errors["base"] = "adb_off"
        return self.async_show_form(
            step_id="enable_debugging",
            description_placeholders={"name": self._name, "host": self._host},
            errors=errors,
        )

    async def async_step_zeroconf_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Add the TV found on the network, once someone is at it."""
        errors: dict[str, str] = {}
        if user_input is not None:
            client = await async_get_client(self.hass, self._host, DEFAULT_PORT)
            try:
                props = await client.async_pair()
            except GoogleTvAuthError:
                errors["base"] = "not_authorized"
            except GoogleTvError:
                errors["base"] = "cannot_connect"
            else:
                await client.async_close()
                return await self._async_finish(
                    self._host,
                    DEFAULT_PORT,
                    self._name,
                    props,
                    install=user_input.get(CONF_INSTALL_BRIDGE, False),
                )
            await client.async_close()
        return self.async_show_form(
            step_id="zeroconf_confirm",
            # The app's offered only to a TV without it
            data_schema=vol.Schema(
                {}
                if self._has_app
                else {vol.Required(CONF_INSTALL_BRIDGE, default=True): bool}
            ),
            description_placeholders={"name": self._name, "host": self._host},
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        """The TV forgot Home Assistant's key: connect again, with its prompt."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Retry the connection once someone is at the TV."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            client = await async_get_client(
                self.hass, entry.data[CONF_HOST], entry.data[CONF_PORT]
            )
            try:
                props = await client.async_pair()
            except GoogleTvAuthError:
                errors["base"] = "not_authorized"
            except GoogleTvError:
                errors["base"] = "cannot_connect"
            else:
                await client.async_close()
                return await self._async_finish(
                    entry.data[CONF_HOST], entry.data[CONF_PORT], entry.title, props
                )
            await client.async_close()
        return self.async_show_form(
            step_id="reauth_confirm",
            description_placeholders={"name": entry.title},
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the TV's address or port (a new IP, network debugging moved)."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            port = user_input[CONF_PORT]
            client = await async_get_client(self.hass, host, port)
            try:
                props = await client.async_pair()
            except GoogleTvAuthError:
                errors["base"] = "not_authorized"
            except GoogleTvError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error reconfiguring the TV")
                errors["base"] = "unknown"
            else:
                await client.async_close()
                return await self._async_finish(host, port, entry.title, props)
            await client.async_close()
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST, default=entry.data[CONF_HOST]): str,
                    vol.Required(CONF_PORT, default=entry.data[CONF_PORT]): vol.All(
                        int, vol.Range(1, 65535)
                    ),
                }
            ),
            description_placeholders={"name": entry.title},
            errors=errors,
        )

    async def _async_finish(
        self,
        host: str,
        port: int,
        name: str,
        props: dict[str, str],
        install: bool = False,
    ) -> ConfigFlowResult:
        """Create the entry (or update it on reauth or reconfigure), one per TV.

        ``install``: install the app once it's set up.
        """
        data = {CONF_HOST: host, CONF_PORT: port}
        if self.source in (SOURCE_REAUTH, SOURCE_RECONFIGURE):
            entry = (
                self._get_reauth_entry()
                if self.source == SOURCE_REAUTH
                else self._get_reconfigure_entry()
            )
            # The same TV, by its Bluetooth address or (entries from 0.1) serial
            known = {_tv_id(props), props.get("serial")} - {None}
            if entry.unique_id and known and entry.unique_id not in known:
                return self.async_abort(reason="wrong_device")
            # Only the address: its pairing with the TV app, its MACs and the
            # TV's own user stay
            return self.async_update_reload_and_abort(entry, data_updates=data)
        if tv_id := _tv_id(props):
            await self.async_set_unique_id(tv_id, raise_on_progress=False)
        self._abort_if_unique_id_configured(updates=data)
        title = (
            name
            or " ".join(p for p in (props.get("manufacturer"), props.get("model")) if p)
            or host
        )
        if install:
            data[CONF_INSTALL_BRIDGE] = True
        return self.async_create_entry(title=title, data=data)


class GoogleTvOptionsFlow(OptionsFlow):
    """Online lookups, and whether dashboards on the TV can control devices."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        options = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_ONLINE_LOOKUPS,
                        default=options.get(CONF_ONLINE_LOOKUPS, True),
                    ): bool,
                    vol.Required(
                        CONF_DASHBOARD_CONTROLS,
                        default=options.get(CONF_DASHBOARD_CONTROLS, False),
                    ): bool,
                }
            ),
        )
