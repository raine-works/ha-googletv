"""Test bootstrap.

Two kinds of tests live here:

* ``test_parsers.py`` — fast unit tests for the shell-output parsers, on output
  captured from real TVs. They load ``parsers.py`` directly (below), *without*
  executing the package ``__init__`` (which imports Home Assistant and
  adb-shell), so they need neither installed.
* ``test_config_flow.py`` — exercises the config flow with a real Home
  Assistant instance via ``pytest-homeassistant-custom-component``, the TV
  mocked. Those tests skip themselves when that harness is not installed.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_BASE = _ROOT / "custom_components" / "googletv"

# Make ``import custom_components.googletv`` work for the Home Assistant tests.
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Register the Home Assistant test plugin only when it is available, so the
# lightweight unit environment (no Home Assistant) still collects cleanly.
try:  # noqa: SIM105
    import pytest_homeassistant_custom_component  # noqa: F401

    pytest_plugins = ("pytest_homeassistant_custom_component",)
except ImportError:
    pass

# parsers.py and lookups.py import nothing from the package or Home Assistant,
# so they load on their own
for _name in ("parsers", "lookups"):
    _spec = importlib.util.spec_from_file_location(
        f"googletv_{_name}", _BASE / f"{_name}.py"
    )
    assert _spec and _spec.loader
    _module = importlib.util.module_from_spec(_spec)
    sys.modules[f"googletv_{_name}"] = _module
    _spec.loader.exec_module(_module)
