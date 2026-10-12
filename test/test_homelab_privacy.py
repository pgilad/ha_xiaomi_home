# -*- coding: utf-8 -*-
"""Check that authentication and diagnostics do not disclose secrets."""
import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

# pylint: disable=import-outside-toplevel, protected-access
pytestmark = [pytest.mark.github, pytest.mark.asyncio]


async def test_token_renewal_logs_no_secrets(caplog):
    """Keep renewed tokens usable without writing them to logs."""
    from custom_components.xiaomi_home.miot.miot_client import MIoTClient

    client = object.__new__(MIoTClient)
    client._uid = 'test-account'
    client._cloud_server = 'sg'
    client._storage = MagicMock()
    client._storage.load_user_config_async = AsyncMock(return_value={
        'auth_info': {
            'expires_ts': 0, 'access_token': 'old-access-secret',
            'refresh_token': 'old-refresh-secret'}})
    client._storage.update_user_config_async = AsyncMock(return_value=True)
    renewed = {
        'expires_ts': 9999999999, 'access_token': 'new-access-secret',
        'refresh_token': 'new-refresh-secret', 'mac_key': 'secret-mac-key'}
    client._oauth = MagicMock()
    client._oauth.refresh_access_token_async = AsyncMock(return_value=renewed)
    client._http = MagicMock()
    client._mips_cloud = MagicMock()
    client._MIoTClient__show_client_error_notify = MagicMock()
    client._MIoTClient__request_refresh_auth_info = MagicMock()
    with caplog.at_level(logging.DEBUG):
        assert await client.refresh_oauth_info_async()
    client._http.update_http_header.assert_called_once_with(
        access_token=renewed['access_token'])
    for secret in renewed.values():
        assert str(secret) not in caplog.text


async def test_oauth_callback_logs_no_code(caplog):
    """The callback completes login without logging its code."""
    from custom_components.xiaomi_home.config_flow import _handle_oauth_webhook
    from custom_components.xiaomi_home.miot.const import DOMAIN

    future = asyncio.get_running_loop().create_future()
    hass = SimpleNamespace(data={DOMAIN: {'test-hook': {
        'oauth_state': 'test-state', 'fut_oauth_code': future}}})
    request = SimpleNamespace(query={
        'state': 'test-state', 'code': 'private-login-code'})
    with caplog.at_level(logging.DEBUG):
        response = await _handle_oauth_webhook(hass, 'test-hook', request)
    assert response.status == 200
    assert future.result() == 'private-login-code'
    assert 'private-login-code' not in caplog.text


async def test_diagnostics_allow_only_safe_fields():
    """Unknown entry fields and runtime credentials stay out of reports."""
    from custom_components.xiaomi_home.diagnostics import (
        async_get_config_entry_diagnostics)
    from custom_components.xiaomi_home.miot.const import DOMAIN

    entry = SimpleNamespace(entry_id='test-entry', data={
        'ctrl_mode': 'auto', 'uuid': 'private-uuid',
        'unknown_secret': 'private-value', 'uid': 'private-account'})
    client = SimpleNamespace(
        miot_network=SimpleNamespace(network_status=True),
        access_token='private-token')
    hass = SimpleNamespace(data={DOMAIN: {
        'miot_clients': {'test-entry': client}}})
    assert await async_get_config_entry_diagnostics(hass, entry) == {
        'loaded': True, 'control_mode': 'auto', 'network_available': True}
    hass.data.clear()
    assert await async_get_config_entry_diagnostics(hass, entry) == {
        'loaded': False, 'control_mode': 'auto'}


async def test_cloud_logs_no_command_payload(monkeypatch, caplog):
    """Device values stay in requests and out of debug logs."""
    from custom_components.xiaomi_home.miot.miot_cloud import MIoTHttpClient
    from test_cloud_privacy import mock_session

    payload = [{'did': 'test-device', 'siid': 2, 'piid': 1,
                'value': 'private-command-value'}]
    session = mock_session(monkeypatch, {'code': 0, 'result': payload})
    client = MIoTHttpClient('sg', '123', 'private-access-token')
    try:
        with caplog.at_level(logging.DEBUG):
            assert await client.set_prop_async(payload) == payload
        assert session.post.call_args.kwargs['json']['params'] == payload
        assert 'private-command-value' not in caplog.text
        assert 'private-access-token' not in caplog.text
    finally:
        await client.deinit_async()


async def test_oauth_error_does_not_echo_response(monkeypatch):
    """An invalid token response must not expose returned secrets."""
    from custom_components.xiaomi_home.miot.miot_cloud import MIoTOauthClient
    from custom_components.xiaomi_home.miot.miot_error import MIoTOauthError
    from test_cloud_privacy import mock_session

    mock_session(monkeypatch, {'code': 0, 'result': {
        'access_token': 'private-response-token'}})
    client = MIoTOauthClient('123', 'https://ha.test/callback', 'sg', 'test-id')
    try:
        with pytest.raises(MIoTOauthError) as error:
            await client.get_access_token_async('private-login-code')
        assert 'private-response-token' not in str(error.value)
    finally:
        await client.deinit_async()
