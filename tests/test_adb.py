"""The ADB client: an untrusted key, a dropped connection, what it sends."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

pytest.importorskip("adb_shell")

from adb_shell.exceptions import AdbTimeoutError, TcpTimeoutException  # noqa: E402

from custom_components.googletv.adb import (  # noqa: E402
    GoogleTvAuthError,
    GoogleTvClient,
    GoogleTvError,
)


def _client() -> tuple[GoogleTvClient, MagicMock]:
    client = GoogleTvClient("10.0.0.5", 5555, MagicMock())
    device = MagicMock()
    device.available = True
    device.connect = AsyncMock()
    device.shell = AsyncMock(return_value="ok")
    device.close = AsyncMock()
    client._device = device
    return client, device


async def test_an_untrusted_key_is_an_auth_error_and_prompts_once() -> None:
    client, device = _client()
    device.available = False

    async def refuse(*, auth_callback, **kwargs) -> None:
        # adb-shell sends the public key (the TV's prompt), then times out
        auth_callback(device)
        raise AdbTimeoutError("Never got one of the expected responses")

    device.connect.side_effect = refuse
    with pytest.raises(GoogleTvAuthError):
        await client.async_connect()
    # Not again: each try would show the prompt on the TV
    with pytest.raises(GoogleTvAuthError):
        await client.async_shell("echo hi")
    assert device.connect.await_count == 1


async def test_an_unreachable_tv_is_not_an_auth_error() -> None:
    client, device = _client()
    device.available = False
    device.connect.side_effect = OSError("No route to host")
    with pytest.raises(GoogleTvError) as err:
        await client.async_connect()
    assert not isinstance(err.value, GoogleTvAuthError)


async def test_a_dropped_connection_is_retried_once() -> None:
    client, device = _client()
    device.shell.side_effect = [TcpTimeoutException("reset"), "ok"]
    assert await client.async_shell("echo hi") == "ok"
    assert device.shell.await_count == 2
    device.shell.side_effect = TcpTimeoutException("down")
    with pytest.raises(GoogleTvError):
        await client.async_shell("echo hi")


async def test_commands_are_checked_and_quoted() -> None:
    client, device = _client()
    await client.async_launch_app("com.example.app", "com.example.app.Main$Inner")
    assert device.shell.await_args.args[0] == (
        "am start -n 'com.example.app/com.example.app.Main$Inner'"
    )
    await client.async_open_url("https://www.youtube.com/watch?v=abc&t=10")
    assert device.shell.await_args.args[0] == (
        "am start -a android.intent.action.VIEW"
        " -d 'https://www.youtube.com/watch?v=abc&t=10'"
    )
    for bad in ("com.example\n", "com.example; reboot"):
        with pytest.raises(GoogleTvError):
            await client.async_launch_app(bad)
    with pytest.raises(GoogleTvError):
        await client.async_key("²")
    await client.async_set_volume(0.5, 15)
    assert device.shell.await_args.args[0].endswith("--set 8")
