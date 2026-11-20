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
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any

from homeassistant.config_entries import SOURCE_REAUTH, ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.helpers.device_registry import format_mac
import voluptuous as vol

try:
    from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
except ImportError:  # Home Assistant before 2025.1
    from homeassistant.components.zeroconf import ZeroconfServiceInfo

from . import async_get_client
from .adb import GoogleTvAuthError, GoogleTvError
from .const import DEFAULT_PORT, DOMAIN

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


def _schema(host: str = "", port: int = DEFAULT_PORT, name: str = "") -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_HOST, default=host): str,
            vol.Required(CONF_PORT, default=port): vol.All(int, vol.Range(1, 65535)),
            vol.Optional(CONF_NAME, default=name): str,
        }
    )


class GoogleTvConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add a Google TV by its address."""

    VERSION = 1

    def __init__(self) -> None:
        """Start a flow."""
        self._host = ""
        self._name = ""

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
                    host, port, user_input.get(CONF_NAME, "").strip(), props
                )
            await client.async_close()

        defaults = user_input or {}
        return self.async_show_form(
            step_id="user",
            data_schema=_schema(
                defaults.get(CONF_HOST, ""),
                defaults.get(CONF_PORT, DEFAULT_PORT),
                defaults.get(CONF_NAME, ""),
            ),
            errors=errors,
        )

    async def async_step_zeroconf(
        self, discovery_info: ZeroconfServiceInfo
    ) -> ConfigFlowResult:
        """A Google TV announced itself: offer it if its ADB port answers."""
        if discovery_info.ip_address.version != 4:
            return self.async_abort(reason="not_ipv4_address")
        host = str(discovery_info.ip_address)
        name = discovery_info.name.split("._", 1)[0].strip()
        if bluetooth := discovery_info.properties.get("bt"):
            await self.async_set_unique_id(format_mac(bluetooth))
            self._abort_if_unique_id_configured(updates={CONF_HOST: host})
        else:
            self._async_abort_entries_match({CONF_HOST: host})
        if not await _adb_port_open(host, DEFAULT_PORT):
            return self.async_abort(reason="adb_off")
        self._host, self._name = host, name
        self.context["title_placeholders"] = {"name": name}
        return await self.async_step_zeroconf_confirm()

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
                    self._host, DEFAULT_PORT, self._name, props
                )
            await client.async_close()
        return self.async_show_form(
            step_id="zeroconf_confirm",
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

    async def _async_finish(
        self, host: str, port: int, name: str, props: dict[str, str]
    ) -> ConfigFlowResult:
        """Create the entry (or, on reauth, update it), one per TV."""
        if tv_id := _tv_id(props):
            await self.async_set_unique_id(tv_id, raise_on_progress=False)
        data = {CONF_HOST: host, CONF_PORT: port}
        if self.source == SOURCE_REAUTH:
            return self.async_update_reload_and_abort(
                self._get_reauth_entry(), data=data
            )
        self._abort_if_unique_id_configured(updates=data)
        title = (
            name
            or " ".join(p for p in (props.get("manufacturer"), props.get("model")) if p)
            or host
        )
        return self.async_create_entry(title=title, data=data)
