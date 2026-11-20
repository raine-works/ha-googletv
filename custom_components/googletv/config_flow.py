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

A TV with the app (Raineworks TV) announces ``_rwtvbridge._tcp`` too:
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
    ConfigEntryState,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import format_mac
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
import voluptuous as vol

from . import async_get_client
from .adb import GoogleTvAuthError, GoogleTvError
from .bridge import BRIDGE_SERVICE_TYPE, BridgeClient, BridgeError
from .const import (
    CONF_BRIDGE_TOKEN,
    CONF_CONNECTION,
    CONF_DASHBOARD_CONTROLS,
    CONF_INSTALL_BRIDGE,
    CONF_ONLINE_LOOKUPS,
    CONF_PROPS,
    CONNECTION_ADB,
    CONNECTION_APP,
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


# How long adding a TV through its app waits for Allow on the TV
CONFIRM_WAIT_S = 120


async def _app_info(hass: Any, host: str) -> dict[str, Any] | None:
    """The TV app's info, if it answers and can pair by Allow on the TV."""
    try:
        info = await BridgeClient(async_get_clientsession(hass), host).async_info()
    except BridgeError:
        return None
    return info if "confirm_pairing" in info.get("features", []) else None


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
        # The TV app's info, adding the TV through it alone
        self._app: dict[str, Any] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the TV's address, then connect, waiting for its prompt."""
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            port = user_input[CONF_PORT]
            # The TV app answering: added through it, no ADB needed
            if info := await _app_info(self.hass, host):
                self._host, self._app = host, info
                self._name = user_input.get(CONF_NAME, "").strip() or info.get(
                    "name", ""
                )
                return await self.async_step_app_confirm()
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
        if self._has_app and (info := await _app_info(self.hass, host)):
            # The app (2.3+) pairs by Allow on the TV: no ADB needed
            if tv_id := info.get("id"):
                await self.async_set_unique_id(tv_id)
                self._abort_if_unique_id_configured(updates={CONF_HOST: host})
            self._app = info
            return await self.async_step_app_confirm()
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

    async def async_step_app_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Add the TV through its app: it asks on screen, and Allow pairs."""
        errors: dict[str, str] = {}
        if user_input is not None:
            token, error = await self._async_allow(self._host)
            if token:
                if tv_id := self._app.get("id"):
                    await self.async_set_unique_id(tv_id, raise_on_progress=False)
                    self._abort_if_unique_id_configured(
                        updates={CONF_HOST: self._host, CONF_BRIDGE_TOKEN: token}
                    )
                props = {
                    key: str(self._app[key])
                    for key in ("manufacturer", "model", "android")
                    if self._app.get(key)
                }
                return self.async_create_entry(
                    title=self._name or self._app.get("name") or self._host,
                    data={
                        CONF_HOST: self._host,
                        CONF_CONNECTION: CONNECTION_APP,
                        CONF_BRIDGE_TOKEN: token,
                        CONF_PROPS: props,
                    },
                )
            errors["base"] = error or "unknown"
        return self.async_show_form(
            step_id="app_confirm",
            description_placeholders={"name": self._name, "host": self._host},
            errors=errors,
        )

    async def _async_allow(self, host: str) -> tuple[str | None, str | None]:
        """Ask on the TV, and wait for Allow: (its token, None), or (None, why not)."""
        bridge = BridgeClient(async_get_clientsession(self.hass), host)
        try:
            pairing_id = await bridge.async_confirm_start("Home Assistant")
            for _ in range(CONFIRM_WAIT_S):
                status = await bridge.async_confirm_status(pairing_id)
                if status == "allowed":
                    return bridge.token, None
                if status == "denied":
                    return None, "denied"
                if status != "pending":
                    break
                await asyncio.sleep(1)
        except BridgeError as err:
            _LOGGER.debug("Can't pair with the TV app on %s: %s", host, err)
            return None, "cannot_connect"
        return None, "not_allowed_in_time"

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        """The TV forgot Home Assistant's key: connect again, with its prompt."""
        if entry_data.get(CONF_CONNECTION) == CONNECTION_APP:
            return await self.async_step_reauth_app()
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_app(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """The TV app forgot Home Assistant (reinstalled): Allow on the TV again."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            token, error = await self._async_allow(entry.data[CONF_HOST])
            if token:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_BRIDGE_TOKEN: token}
                )
            errors["base"] = error or "unknown"
        return self.async_show_form(
            step_id="reauth_app",
            description_placeholders={"name": entry.title},
            errors=errors,
        )

    async def async_step_connect_adb(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """A TV added through its app, given ADB: the D-pad, power, inputs."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            port = user_input[CONF_PORT]
            client = await async_get_client(self.hass, entry.data[CONF_HOST], port)
            try:
                props = await client.async_pair()
            except GoogleTvAuthError:
                errors["base"] = "not_authorized"
            except GoogleTvError:
                errors["base"] = "cannot_connect"
            else:
                await client.async_close()
                # The app's pairing stays: both, from now on
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={
                        CONF_CONNECTION: CONNECTION_ADB,
                        CONF_PORT: port,
                        CONF_PROPS: {**entry.data.get(CONF_PROPS, {}), **props},
                    },
                )
            await client.async_close()
        return self.async_show_form(
            step_id="connect_adb",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PORT, default=DEFAULT_PORT): vol.All(
                        int, vol.Range(1, 65535)
                    )
                }
            ),
            description_placeholders={"name": entry.title},
            errors=errors,
        )

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
        """Change the TV's address or port (a new IP, network debugging moved).

        A TV added through its app alone is offered ADB instead.
        """
        entry = self._get_reconfigure_entry()
        if entry.data.get(CONF_CONNECTION) == CONNECTION_APP:
            return await self.async_step_connect_adb()
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
    """Online lookups, dashboards' controls, and the TV's apps."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """General options, or the apps (while the TV is set up)."""
        if self._coordinator() is None:
            return await self.async_step_general()
        return self.async_show_menu(step_id="init", menu_options=["apps", "general"])

    def _coordinator(self) -> Any:
        entry = self.config_entry
        if entry.state is ConfigEntryState.LOADED and entry.runtime_data.data:
            return entry.runtime_data
        return None

    async def async_step_general(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Online lookups, and whether dashboards on the TV can control devices."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        options = self.config_entry.options
        return self.async_show_form(
            step_id="general",
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

    async def async_step_apps(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Which apps Home Assistant shows, and where pop-ups appear.

        The same switches as the TV app's Apps screen: they're kept there.
        """
        coordinator = self._coordinator()
        if coordinator is None:
            return self.async_abort(reason="not_loaded")
        apps = coordinator.data.apps
        inputs = coordinator.data.state.inputs
        # Pop-ups' rules are the TV app's (2.4 or later)
        rules = coordinator.app_rules
        errors: dict[str, str] = {}
        if user_input is not None:
            shown = set(user_input.get(APPS_SHOWN, []))
            changes = {
                "hidden_apps": [a.package for a in apps if a.package not in shown]
            }
            if rules is not None:
                over = set(user_input.get(POPUPS_APPS, []))
                changes["blocked_apps"] = [
                    a.package for a in apps if a.package not in over
                ]
                over_inputs = set(user_input.get(POPUPS_INPUTS, []))
                changes["blocked_inputs"] = [
                    i.id for i in inputs if i.id not in over_inputs
                ]
            try:
                await coordinator.async_set_app_rules(changes)
            except HomeAssistantError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(data=dict(self.config_entry.options))

        def choices(pairs: list[tuple[str, str]]) -> SelectSelector:
            return SelectSelector(
                SelectSelectorConfig(
                    options=[SelectOptionDict(value=v, label=n) for v, n in pairs],
                    multiple=True,
                    mode=SelectSelectorMode.LIST,
                )
            )

        app_choices = [(a.package, a.name) for a in apps]
        hidden = coordinator.hidden_apps
        schema: dict[Any, Any] = {
            vol.Optional(
                APPS_SHOWN, default=[a.package for a in apps if a.package not in hidden]
            ): choices(app_choices)
        }
        if rules is not None:
            blocked = set(rules.get("blocked_apps") or [])
            schema[
                vol.Optional(
                    POPUPS_APPS,
                    default=[a.package for a in apps if a.package not in blocked],
                )
            ] = choices(app_choices)
            if inputs:
                blocked_inputs = set(rules.get("blocked_inputs") or [])
                schema[
                    vol.Optional(
                        POPUPS_INPUTS,
                        default=[i.id for i in inputs if i.id not in blocked_inputs],
                    )
                ] = choices([(i.id, i.label) for i in inputs])
        return self.async_show_form(
            step_id="apps",
            data_schema=vol.Schema(schema),
            errors=errors,
            description_placeholders={"name": self.config_entry.title},
        )


# The apps step's fields
APPS_SHOWN = "apps_shown"
POPUPS_APPS = "popups_apps"
POPUPS_INPUTS = "popups_inputs"
