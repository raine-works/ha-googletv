"""Diagnostics for a Google TV: what it reports, with identifiers redacted."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant

from .coordinator import GoogleTvConfigEntry

TO_REDACT = {
    CONF_HOST,
    "serial",
    "bluetooth",
    "ip_address",
    "unique_id",
    "mac_ethernet",
    "mac_wifi",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: GoogleTvConfigEntry
) -> dict[str, Any]:
    """The TV's latest poll, apps, inputs and settings."""
    coordinator = entry.runtime_data
    data = coordinator.data
    state = asdict(data.state)
    return {
        "entry": async_redact_data(
            {
                "data": dict(entry.data),
                "options": dict(entry.options),
                "unique_id": entry.unique_id,
            },
            TO_REDACT,
        ),
        "device": async_redact_data(dict(coordinator.props), TO_REDACT),
        "state": {**state, "activity_state": data.state.activity_state},
        "apps": [asdict(app) for app in data.apps],
        "artwork": data.artwork,
        "diagnostics": async_redact_data(asdict(data.diagnostics), TO_REDACT),
        "last_update_success": coordinator.last_update_success,
    }
