"""Wake-on-LAN's magic packet."""

from __future__ import annotations

import pytest

pytest.importorskip("homeassistant")

from custom_components.googletv.wol import magic_packet  # noqa: E402


def test_magic_packet() -> None:
    packet = magic_packet("d0:65:b3:e2:d2:a7")
    assert len(packet) == 102
    assert packet[:6] == b"\xff" * 6
    assert packet[6:12] == bytes.fromhex("d065b3e2d2a7")
    assert packet[6:] == bytes.fromhex("d065b3e2d2a7") * 16
    with pytest.raises(ValueError):
        magic_packet("not a mac")
