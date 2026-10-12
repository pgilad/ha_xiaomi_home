# -*- coding: utf-8 -*-
"""Import the integration against the installed Home Assistant release."""
import ast
import importlib
import inspect
from pathlib import Path

import pytest

# pylint: disable=import-outside-toplevel
pytestmark = pytest.mark.github


def test_home_assistant_platform_imports():
    """Detect removed Home Assistant APIs in every integration platform."""
    from custom_components.xiaomi_home.miot.const import SUPPORTED_PLATFORMS

    for module in ['config_flow', 'diagnostics', *SUPPORTED_PLATFORMS]:
        importlib.import_module(f'custom_components.xiaomi_home.{module}')


def test_client_constructor_call_sites():
    """Bind source call arguments to the current client signatures."""
    from custom_components.xiaomi_home.miot.miot_client import MIoTClient
    from custom_components.xiaomi_home.miot.miot_cloud import (
        MIoTHttpClient, MIoTOauthClient)

    constructors = {
        cls.__name__: inspect.signature(cls)
        for cls in (MIoTClient, MIoTHttpClient, MIoTOauthClient)}
    root = Path(__file__).resolve().parents[1]
    sources = [*root.glob('custom_components/**/*.py'), *root.glob('test/*.py')]
    checked = set()
    for file in sources:
        for node in ast.walk(ast.parse(file.read_text(encoding='utf-8'))):
            if not isinstance(node, ast.Call) or not isinstance(
                    node.func, ast.Name):
                continue
            if node.func.id not in constructors:
                continue
            args = [None] * len(node.args)
            kwargs = {item.arg: None for item in node.keywords}
            constructors[node.func.id].bind(*args, **kwargs)
            checked.add(node.func.id)
    assert checked == set(constructors)
