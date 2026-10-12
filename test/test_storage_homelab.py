# -*- coding: utf-8 -*-
"""Check credential permissions and atomic storage failures."""
import os
import stat

import pytest

# pylint: disable=import-outside-toplevel
pytestmark = [pytest.mark.github, pytest.mark.asyncio]


async def test_credentials_and_keys_have_private_permissions(tmp_path):
    """Restrict new credential files, raw private keys, and storage folders."""
    from miot.miot_storage import MIoTStorage

    root = tmp_path / 'storage'
    storage = MIoTStorage(str(root))
    assert await storage.save_async('user_config', 'account', {
        'auth_info': {'access_token': 'private-token'}})
    assert await storage.save_file_async('cert', 'account.key', b'private-key')
    for file in root.rglob('*'):
        expected = 0o700 if file.is_dir() else 0o600
        assert stat.S_IMODE(file.stat().st_mode) == expected
    assert stat.S_IMODE(root.stat().st_mode) == 0o700


async def test_loading_old_credentials_restricts_permissions(tmp_path):
    """Protect existing credentials without changing the stored data."""
    from miot.miot_storage import MIoTStorage

    root = tmp_path / 'storage'
    storage = MIoTStorage(str(root))
    assert storage.save_file('cert', 'account.key', b'private-key')
    key = root / 'cert' / 'account.key'
    key.chmod(0o644)
    root.chmod(0o755)
    storage = MIoTStorage(str(root))
    assert await storage.load_file_async(
        'cert', 'account.key') == b'private-key'
    assert stat.S_IMODE(key.stat().st_mode) == 0o600
    assert stat.S_IMODE(root.stat().st_mode) == 0o700


@pytest.mark.parametrize('failure', ['fchmod', 'fsync', 'replace'])
async def test_failed_write_preserves_existing_credentials(
    tmp_path, monkeypatch, failure
):
    """An interrupted save keeps the old file and removes temporary data."""
    from miot.miot_storage import MIoTStorage

    storage = MIoTStorage(str(tmp_path))
    old = {'auth_info': {'access_token': 'old-token'}}
    assert await storage.save_async('user_config', 'account', old)

    def fail(*unused_args):
        raise OSError('simulated storage failure')

    monkeypatch.setattr(os, failure, fail)
    assert not await storage.save_async('user_config', 'account', {
        'auth_info': {'access_token': 'new-token'}})
    assert await storage.load_async('user_config', 'account', dict) == old
    assert not list(tmp_path.rglob('*.tmp'))


async def test_replacement_keeps_storage_format(tmp_path):
    """Atomic replacement retains compatibility with existing readers."""
    from miot.miot_storage import MIoTStorage

    storage = MIoTStorage(str(tmp_path))
    assert await storage.save_async('user_config', 'account', {'token': 'old'})
    assert await storage.save_async('user_config', 'account', {'token': 'new'})
    assert await storage.load_async('user_config', 'account', dict) == {
        'token': 'new'}
    assert not list(tmp_path.rglob('*.tmp'))
