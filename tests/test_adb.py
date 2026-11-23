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


_MISMATCH = (
    "Performing Streamed Install\n"
    "adb: failed to install: Failure [INSTALL_FAILED_UPDATE_INCOMPATIBLE: "
    "Existing package com.raineworks.tvbridge signatures do not match "
    "newer version; ignoring!]"
)


async def test_an_install_is_one_push_and_one_command() -> None:
    client, device = _client()
    device.push = AsyncMock()
    device.shell.return_value = "Success\n"
    assert await client.async_install_apk(b"PK apk") is False
    device.push.assert_awaited_once()
    assert device.shell.await_count == 1
    assert device.shell.await_args.args[0].startswith("pm install -r -g ")


async def test_an_app_signed_with_another_key_is_uninstalled_and_installed_again(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client, device = _client()
    device.push = AsyncMock()
    device.shell.side_effect = [_MISMATCH, "Success\n", "Success\n"]
    with caplog.at_level("WARNING"):
        assert await client.async_install_apk(b"PK apk") is True
    commands = [call.args[0] for call in device.shell.await_args_list]
    assert commands[0].startswith("pm install -r -g ")
    assert commands[1] == "pm uninstall com.raineworks.tvbridge"
    assert commands[2] == commands[0]
    # The APK is copied again: the failed install removed its copy
    assert device.push.await_count == 2
    assert "signed with another key" in caplog.text


async def test_another_install_failure_doesnt_uninstall_anything() -> None:
    client, device = _client()
    device.push = AsyncMock()
    device.shell.return_value = "Failure [INSTALL_FAILED_INSUFFICIENT_STORAGE]"
    with pytest.raises(GoogleTvError, match="INSUFFICIENT_STORAGE"):
        await client.async_install_apk(b"PK apk")
    assert device.shell.await_count == 1
    assert device.push.await_count == 1


async def test_an_app_the_tv_wont_uninstall_is_an_error() -> None:
    client, device = _client()
    device.push = AsyncMock()
    device.shell.side_effect = [
        _MISMATCH,
        "Failure [DELETE_FAILED_DEVICE_POLICY_MANAGER]",
    ]
    with pytest.raises(GoogleTvError, match="wouldn't uninstall it"):
        await client.async_install_apk(b"PK apk")
    assert device.shell.await_count == 2
    assert device.push.await_count == 1


async def test_a_second_failure_after_the_uninstall_is_an_error() -> None:
    client, device = _client()
    device.push = AsyncMock()
    device.shell.side_effect = [
        _MISMATCH,
        "Success\n",
        "Failure [INSTALL_FAILED_INVALID_APK]",
    ]
    with pytest.raises(GoogleTvError, match="INVALID_APK"):
        await client.async_install_apk(b"PK apk")
    # Once only: no third try, no second uninstall
    assert device.shell.await_count == 3
