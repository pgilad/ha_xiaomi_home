# -*- coding: utf-8 -*-
"""Check cloud request privacy without making external requests."""
import json
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import parse_qs, urlparse

import pytest


def mock_session(monkeypatch, payload):
    """Capture the request arguments before they reach the HTTP transport."""
    import aiohttp  # pylint: disable=import-outside-toplevel

    response = MagicMock(status=200)
    response.text = AsyncMock(return_value=json.dumps(payload))
    session = MagicMock(closed=False)
    session.get = AsyncMock(return_value=response)
    session.post = AsyncMock(return_value=response)
    session.close = AsyncMock()
    monkeypatch.setattr(aiohttp, 'ClientSession', lambda **kwargs: session)
    return session


@pytest.mark.github
@pytest.mark.asyncio
async def test_oauth_request_privacy(monkeypatch):
    """Login and renewal keep auth data but send no identifying User-Agent."""
    # pylint: disable=import-outside-toplevel
    from miot.const import OAUTH2_CLIENT_ID
    from miot.miot_cloud import MIoTOauthClient

    session = mock_session(monkeypatch, {
        'code': 0, 'result': {
            'access_token': 'test-access',
            'refresh_token': 'test-refresh',
            'expires_in': 3600}})
    client = MIoTOauthClient(
        client_id=OAUTH2_CLIENT_ID,
        redirect_url='https://ha.example.test/callback',
        cloud_server='sg', uuid='private-test-installation')
    try:
        query = parse_qs(urlparse(client.gen_auth_url()).query)
        assert query['device_id'] == ['ha.private-test-installation']
        assert query['client_id'] == [OAUTH2_CLIENT_ID]
        assert query['state'] == [client.state]
        assert (await client.get_access_token_async('test-code'))[
            'access_token'] == 'test-access'
        assert (await client.refresh_access_token_async('test-refresh'))[
            'access_token'] == 'test-access'
        assert session.get.await_count == 2
        for call in session.get.call_args_list:
            assert call.kwargs['headers']['User-Agent'] == 'ha_xiaomi_home'
        login_data = json.loads(
            session.get.call_args_list[0].kwargs['params']['data'])
        assert login_data['device_id'] == 'ha.private-test-installation'
        assert login_data['code'] == 'test-code'
        refresh_data = json.loads(
            session.get.call_args_list[1].kwargs['params']['data'])
        assert refresh_data['refresh_token'] == 'test-refresh'
    finally:
        await client.deinit_async()


@pytest.mark.github
@pytest.mark.asyncio
async def test_device_request_privacy(monkeypatch):
    """Property reads and writes keep authentication and command payloads."""
    # pylint: disable=import-outside-toplevel
    from miot.const import OAUTH2_CLIENT_ID
    from miot.miot_cloud import MIoTHttpClient

    result = [{'did': 'test-device', 'siid': 2, 'piid': 1, 'value': 42}]
    session = mock_session(monkeypatch, {'code': 0, 'result': result})
    client = MIoTHttpClient(
        cloud_server='sg', client_id=OAUTH2_CLIENT_ID,
        access_token='test-access')
    read_params = [{'did': 'test-device', 'siid': 2, 'piid': 1}]
    try:
        assert await client.get_props_async(read_params) == result
        assert await client.set_prop_async(result) == result
        assert session.post.await_count == 2
        for call in session.post.call_args_list:
            headers = call.kwargs['headers']
            assert headers['User-Agent'] == 'ha_xiaomi_home'
            assert headers['Authorization'] == 'Bearertest-access'
            assert headers['X-Client-AppId'] == OAUTH2_CLIENT_ID
        assert session.post.call_args_list[0].kwargs['json'][
            'params'] == read_params
        assert session.post.call_args_list[1].kwargs['json'][
            'params'] == result
        client.update_http_header(access_token='test-renewed-access')
        await client.get_props_async(read_params)
        assert session.post.call_args.kwargs['headers'][
            'Authorization'] == 'Bearertest-renewed-access'
        assert session.post.call_args.kwargs['headers'][
            'User-Agent'] == 'ha_xiaomi_home'
    finally:
        await client.deinit_async()


@pytest.mark.github
@pytest.mark.asyncio
async def test_profile_request_privacy(monkeypatch):
    """Profile requests use the same fixed header as cloud commands."""
    # pylint: disable=import-outside-toplevel
    from miot.const import OAUTH2_CLIENT_ID
    from miot.miot_cloud import MIoTHttpClient

    profile = {'miliaoNick': 'Test user'}
    session = mock_session(monkeypatch, {'code': 0, 'data': profile})
    client = MIoTHttpClient(
        cloud_server='sg', client_id=OAUTH2_CLIENT_ID,
        access_token='test-access')
    try:
        assert await client.get_user_info_async() == profile
        request = session.get.call_args.kwargs
        assert request['headers']['User-Agent'] == 'ha_xiaomi_home'
        assert request['params'] == {
            'clientId': OAUTH2_CLIENT_ID, 'token': 'test-access'}
    finally:
        await client.deinit_async()
