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
        action_async=AsyncMock())
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
