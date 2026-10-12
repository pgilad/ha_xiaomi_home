# -*- coding: utf-8 -*-
"""Check optional probes without contacting external services."""
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

import pytest

# pylint: disable=import-outside-toplevel, protected-access
pytestmark = [pytest.mark.github, pytest.mark.asyncio]


async def test_disabled_probes_use_local_interfaces(monkeypatch):
    """A local network remains usable with no external probe requests."""
    from miot.miot_network import MIoTNetwork, NetworkInfo

    network = MIoTNetwork(ip_addr_list=[], url_addr_list=[])
    ping = AsyncMock()
    http = AsyncMock()
    monkeypatch.setattr(network, '_MIoTNetwork__ping_async', ping)
    monkeypatch.setattr(network, '_MIoTNetwork__http_async', http)
    monkeypatch.setattr(network, 'get_network_info_async', AsyncMock(
        return_value={'eth0': NetworkInfo(
            'eth0', '192.0.2.2', '255.255.255.0', '192.0.2.0/24')}))
    try:
        await network._MIoTNetwork__update_status_and_info_async()
        assert network.local_network_available
        assert network.network_status
        assert not network.probes_enabled
        assert await network.get_network_status_async()
        assert not await network.ping_multi_async([])
        assert not await network.http_multi_async([])
        ping.assert_not_awaited()
        http.assert_not_awaited()
    finally:
        await network.deinit_async()


async def test_probe_lists_distinguish_empty_from_defaults():
    """An empty list disables a probe type; None restores its defaults."""
    from miot.miot_network import MIoTNetwork

    network = MIoTNetwork(ip_addr_list=['192.0.2.1'], url_addr_list=[])
    try:
        assert network.probes_enabled
        assert not network._http_addr_map
        await network.update_addr_list_async([], [])
        assert not network.probes_enabled
        await network.update_addr_list_async(None, None)
        assert network._ip_addr_map
        assert network._http_addr_map
    finally:
        await network.deinit_async()


async def test_local_status_survives_failed_external_probes(monkeypatch):
    """Failed external checks do not erase local interface availability."""
    from miot.miot_network import MIoTNetwork, NetworkInfo

    network = MIoTNetwork()
    monkeypatch.setattr(network, 'get_network_status_async', AsyncMock(
        return_value=False))
    monkeypatch.setattr(network, 'get_network_info_async', AsyncMock(
        return_value={'eth0': NetworkInfo(
            'eth0', '192.0.2.2', '255.255.255.0', '192.0.2.0/24')}))
    try:
        await network._MIoTNetwork__update_status_and_info_async()
        assert network.local_network_available
        assert not network.network_status
    finally:
        await network.deinit_async()


async def test_legacy_empty_config_preserves_defaults():
    """Only explicit disabling changes an old empty configuration."""
    from miot.miot_network import MIoTNetwork

    assert MIoTNetwork.get_probe_addresses({}) == (None, None)
    assert MIoTNetwork.get_probe_addresses({'ip': [], 'url': []}) == (
        None, None)
    assert MIoTNetwork.get_probe_addresses({'disabled': True}) == ([], [])
    assert MIoTNetwork.get_probe_addresses({'ip': ['192.0.2.1']}) == (
        ['192.0.2.1'], [])


@pytest.mark.parametrize('options_flow', [False, True])
@pytest.mark.parametrize('storage_ok', [False, True])
async def test_config_flow_can_disable_all_probes(options_flow, storage_ok):
    """Both flows persist disabling and skip optional dependency requests."""
    from custom_components.xiaomi_home.config_flow import (
        XiaomiMihomeConfigFlow, OptionsFlowHandler)
    from homeassistant.data_entry_flow import AbortFlow

    flow_class = OptionsFlowHandler if options_flow else XiaomiMihomeConfigFlow
    flow = object.__new__(flow_class)
    flow._cc_network_detect_addr = ''
    flow._opt_network_detect_cfg = True
    flow._opt_check_network_deps = False
    flow._miot_storage = MagicMock()
    flow._miot_storage.update_user_config_async = AsyncMock(
        return_value=storage_ok)
    flow._miot_network = MagicMock()
    flow._miot_network.update_addr_list_async = AsyncMock()
    flow.async_step_oauth = AsyncMock()
    flow.async_step_config_confirm = AsyncMock()
    user_input = {'disable_network_probes': True, 'check_network_deps': True}
    if storage_ok:
        await flow.async_step_network_detect_config(user_input)
        flow._miot_network.update_addr_list_async.assert_awaited_once_with(
            ip_addr_list=[], url_addr_list=[])
    else:
        with pytest.raises(AbortFlow):
            await flow.async_step_network_detect_config(user_input)
        flow._miot_network.update_addr_list_async.assert_not_awaited()
        flow.async_step_oauth.assert_not_awaited()
        flow.async_step_config_confirm.assert_not_awaited()
    flow._miot_network.ping_multi_async.assert_not_called()
    flow._miot_network.http_multi_async.assert_not_called()
    saved = flow._miot_storage.update_user_config_async.call_args.kwargs
    assert saved['config']['network_detect_addr']['disabled']
