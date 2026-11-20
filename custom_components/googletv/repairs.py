"""Repairs: the TV app missing from a TV Home Assistant reaches over ADB."""

from __future__ import annotations

from typing import Any

from homeassistant import data_entry_flow
from homeassistant.components.repairs import RepairsFlow
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .bridge import BRIDGE_APK_URL


class InstallTvAppFlow(RepairsFlow):
    """Install the TV app over ADB, at the press of Submit."""

    def __init__(self, entry_id: str) -> None:
        """Set up the flow for one TV."""
        self._entry_id = entry_id

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> data_entry_flow.FlowResult:
        """Ask, then install."""
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> data_entry_flow.FlowResult:
        """Install it; an error stays on the form."""
        entry = self.hass.config_entries.async_get_entry(self._entry_id)
        if entry is None:
            return self.async_abort(reason="tv_removed")
        errors: dict[str, str] = {}
        placeholders = {"name": entry.title, "error": ""}
        if user_input is not None:
            try:
                await entry.runtime_data.async_install_bridge(BRIDGE_APK_URL)
            except HomeAssistantError as err:
                errors["base"] = "install_failed"
                placeholders["error"] = str(err)
            else:
                return self.async_create_entry(data={})
        return self.async_show_form(
            step_id="confirm", errors=errors, description_placeholders=placeholders
        )


async def async_create_fix_flow(
    hass: HomeAssistant, issue_id: str, data: dict[str, Any] | None
) -> RepairsFlow:
    """The fix for an issue."""
    return InstallTvAppFlow((data or {})["entry_id"])
