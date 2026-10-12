# -*- coding: utf-8 -*-
"""Connection diagnostics without credentials or device data."""
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .miot.const import DOMAIN


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict:
    """Return only fields that are safe to share in a support report."""
    clients = hass.data.get(DOMAIN, {}).get('miot_clients', {})
    client = clients.get(entry.entry_id)
    result = {
        'loaded': client is not None,
        'control_mode': entry.data.get('ctrl_mode', 'auto'),
    }
    if client is not None:
        result['network_available'] = client.miot_network.network_status
    return result
