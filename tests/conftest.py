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

# parsers.py imports nothing from the package, so it loads on its own
_spec = importlib.util.spec_from_file_location("googletv_parsers", _BASE / "parsers.py")
assert _spec and _spec.loader
_parsers = importlib.util.module_from_spec(_spec)
sys.modules["googletv_parsers"] = _parsers
_spec.loader.exec_module(_parsers)
