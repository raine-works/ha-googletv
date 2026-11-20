"""Wake-on-LAN: the magic packet, for a TV that's off its network."""

from __future__ import annotations

import socket

from homeassistant.core import HomeAssistant

WOL_PORT = 9


def magic_packet(mac: str) -> bytes:
    """Six 0xFF bytes, then the MAC sixteen times."""
    address = bytes.fromhex(mac.replace(":", "").replace("-", ""))
    if len(address) != 6:
        raise ValueError(f"Not a MAC: {mac}")
    return b"\xff" * 6 + address * 16


def _send(packets: list[bytes]) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for packet in packets:
            sock.sendto(packet, ("255.255.255.255", WOL_PORT))


async def async_wake(hass: HomeAssistant, macs: list[str]) -> None:
    """Broadcast a magic packet to each MAC (Ethernet and Wi-Fi)."""
    packets = [magic_packet(mac) for mac in macs]
    if packets:
        await hass.async_add_executor_job(_send, packets)
