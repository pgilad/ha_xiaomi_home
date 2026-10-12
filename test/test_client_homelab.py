# -*- coding: utf-8 -*-
"""Exercise client routing and recovery with real modules and fake devices."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

# pylint: disable=import-outside-toplevel, protected-access
pytestmark = [pytest.mark.github, pytest.mark.asyncio]


@pytest_asyncio.fixture(name='client')
async def make_client():
    """Create an isolated client without cloud or local connections."""
    from custom_components.xiaomi_home.miot.miot_client import MIoTClient
    from custom_components.xiaomi_home.miot.miot_network import MIoTNetwork
    from custom_components.xiaomi_home.miot.miot_storage import MIoTStorage
    from custom_components.xiaomi_home.miot.miot_mdns import MipsService
    from custom_components.xiaomi_home.miot.miot_lan import MIoTLan

    instance = MIoTClient(
        entry_id='test-entry',
        entry_data={'uid': 'test-user', 'cloud_server': 'sg'},
        network=MagicMock(spec=MIoTNetwork, network_status=True),
        storage=MagicMock(spec=MIoTStorage),
        mips_service=MagicMock(spec=MipsService),
        miot_lan=MagicMock(spec=MIoTLan))
    instance._device_list_cache = {'test-device': {'online': True}}
    instance._device_list_cloud = {'test-device': {'online': True}}
    instance._http = SimpleNamespace(
        get_prop_async=AsyncMock(), set_prop_async=AsyncMock(),
        action_async=AsyncMock(), get_props_async=AsyncMock())
    instance._i18n = MagicMock()
    return instance


@pytest.mark.parametrize('value', [False, 0, ''])
async def test_cloud_property_preserves_false_values(client, value):
    """A valid false value must not be mistaken for a failed read."""
    client._http.get_prop_async.return_value = value
    assert await client.get_prop_async('test-device', 2, 1) == value
    client._miot_lan.get_prop_async.assert_not_called()


@pytest.mark.parametrize('command', ['property', 'action'])
async def test_command_error_schedules_device_refresh(client, command):
    """An offline error schedules a coroutine and keeps the command error."""
    from custom_components.xiaomi_home.miot.miot_error import MIoTClientError

    refresh = AsyncMock()
    client._MIoTClient__refresh_cloud_device_with_dids_async = refresh
    tasks = []

    def create_task(coroutine):
        task = asyncio.create_task(coroutine)
        tasks.append(task)
        return task

    client._main_loop = SimpleNamespace(create_task=create_task)
    with pytest.raises(MIoTClientError):
        if command == 'property':
            client._http.set_prop_async.return_value = [{'code': -704010000}]
            await client.set_prop_async('test-device', 2, 1, True)
        else:
            client._http.action_async.return_value = {'code': -704010000}
            await client.action_async('test-device', 2, 1, [])
    assert len(tasks) == 1
    await tasks[0]
    refresh.assert_awaited_once_with(dids=['test-device'])


@pytest.mark.parametrize('mode', ['auto', 'cloud'])
@pytest.mark.parametrize('transport', ['gateway', 'lan'])
async def test_local_only_device_uses_local_transport(client, mode, transport):
    """Device policy overrides cloud mode for reads, writes, and actions."""
    from custom_components.xiaomi_home.miot.miot_client import CtrlMode

    client._local_only_devices = frozenset(['test-device'])
    client._ctrl_mode = CtrlMode.load(mode)
    local = SimpleNamespace(
        get_prop_async=AsyncMock(return_value=False),
        set_prop_async=AsyncMock(return_value={'code': 0}),
        action_async=AsyncMock(return_value={'code': 0, 'out': [42]}))
    if transport == 'gateway':
        client._device_list_gateway = {'test-device': {
            'online': True, 'specv2_access': True, 'group_id': 'test-group'}}
        client._mips_local = {'test-group': local}
    else:
        client._device_list_lan = {'test-device': {'online': True}}
        client._miot_lan = local
    assert await client.get_prop_async('test-device', 2, 1) is False
    assert await client.set_prop_async('test-device', 2, 1, True)
    assert await client.action_async('test-device', 2, 1, []) == [42]
    client._http.get_prop_async.assert_not_awaited()
    client._http.set_prop_async.assert_not_awaited()
    client._http.action_async.assert_not_awaited()


async def test_local_only_device_has_no_cloud_fallback(client):
    """No local route means an error, even if the cloud device is online."""
    from custom_components.xiaomi_home.miot.miot_error import MIoTClientError

    client._local_only_devices = frozenset(['test-device'])
    for operation in (
        client.get_prop_async('test-device', 2, 1),
        client.set_prop_async('test-device', 2, 1, True),
        client.action_async('test-device', 2, 1, []),
    ):
        with pytest.raises(MIoTClientError, match='No local control route'):
            await operation
    client._http.get_prop_async.assert_not_awaited()
    client._http.set_prop_async.assert_not_awaited()
    client._http.action_async.assert_not_awaited()
    assert not client._MIoTClient__check_device_state(
        'test-device', True, False, False)


async def test_batched_cloud_reads_exclude_local_only_devices(client):
    """Only permitted devices enter a cloud property request."""
    client._local_only_devices = frozenset(['test-device'])
    private = {'did': 'test-device', 'siid': 2, 'piid': 1}
    public = {'did': 'cloud-device', 'siid': 2, 'piid': 1}
    client._refresh_props_list = {
        'test-device|2|1': private, 'cloud-device|2|1': public}
    client._http.get_props_async.return_value = [{**public, 'value': 0}]
    assert await client._MIoTClient__refresh_props_from_cloud()
    client._http.get_props_async.assert_awaited_once_with(params=[public])
    assert client._refresh_props_list == {'test-device|2|1': private}


async def test_local_only_device_does_not_subscribe_to_cloud(client):
    """Cloud availability alone cannot enable a restricted subscription."""
    client._local_only_devices = frozenset(['test-device'])
    client._mips_cloud = MagicMock()
    client._MIoTClient__update_device_msg_sub('test-device')
    client._mips_cloud.sub_prop.assert_not_called()
    client._mips_cloud.sub_event.assert_not_called()


@pytest.mark.parametrize('value', [None, False, RuntimeError('read failed')])
async def test_local_refresh_retains_failed_requests(client, value):
    """Failures and missing routes stay queued; valid false values complete."""
    client._local_only_devices = frozenset(['test-device'])
    client._miot_lan.init_done = True
    client._miot_lan.get_prop_async = AsyncMock()
    if isinstance(value, BaseException):
        client._miot_lan.get_prop_async.side_effect = value
    else:
        client._miot_lan.get_prop_async.return_value = value
    client._device_list_lan = {'test-device': {'online': True}}
    params = {'did': 'test-device', 'siid': 2, 'piid': 1}
    missing = {'did': 'no-local-route', 'siid': 2, 'piid': 1}
    client._refresh_props_list = {
        'test-device|2|1': params, 'no-local-route|2|1': missing}
    result = await client._MIoTClient__refresh_props_from_lan()
    assert result is (value is False)
    assert 'no-local-route|2|1' in client._refresh_props_list
    assert ('test-device|2|1' in client._refresh_props_list) is (
        value is not False)


async def test_options_save_device_policy_without_internet():
    """The option is saved on confirmation without cloud availability."""
    from custom_components.xiaomi_home.config_flow import OptionsFlowHandler

    entry = SimpleNamespace(entry_id='test-entry', data={
        'uid': 'test-user', 'cloud_server': 'sg', 'virtual_did': 'test-hook',
        'storage_path': '/unused', 'home_selected': {}},
        options={}, unique_id='test-user')
    flow = OptionsFlowHandler(entry)
    flow._miot_client = MagicMock()
    flow.async_step_update_user_info = AsyncMock()
    await flow.async_step_config_options({
        'local_only_devices': ['test-device']})
    assert flow._need_reload
    assert 'local_only_devices' not in entry.data
    flow.hass = SimpleNamespace(config_entries=MagicMock())
    flow._main_loop = MagicMock()
    flow.async_create_entry = MagicMock()
    await flow.async_step_config_confirm({'confirm': True})
    saved = flow.hass.config_entries.async_update_entry.call_args.kwargs
    assert saved['data']['local_only_devices'] == ['test-device']


async def test_partial_cloud_reply_keeps_unresolved_properties(client):
    """Missing results stay queued for a local path or a later retry."""
    first = {'did': 'test-device', 'siid': 2, 'piid': 1}
    second = {'did': 'test-device', 'siid': 2, 'piid': 2}
    client._refresh_props_list = {
        'test-device|2|1': first, 'test-device|2|2': second}
    client._http.get_props_async.return_value = [{**first, 'value': False}]
    assert await client._MIoTClient__refresh_props_from_cloud()
    assert client._refresh_props_list == {'test-device|2|2': second}
