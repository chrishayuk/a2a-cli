# tests/chat/commands/test_debug.py

import pytest
import sys
import types
import asyncio
from rich.panel import Panel

import a2a_cli.chat.commands.debug as debug_mod

@pytest.mark.asyncio
async def test_cmd_debug_info_basic(monkeypatch, capsys):
    # Stub rich module in sys.modules to avoid missing __version__
    dummy_rich = types.ModuleType('rich')
    dummy_rich.__version__ = '0.1.2'
    # Ensure print and Panel still refer to real rich for formatting
    monkeypatch.setitem(sys.modules, 'rich', dummy_rich)

    context = {}
    ok = await debug_mod.cmd_debug_info([], context)
    assert ok is True
    captured = capsys.readouterr()
    # Should include the Debug Information panel and connection details
    assert "Debug Information" in captured.out
    assert "Connection Details" in captured.out
    assert "System Information" in captured.out

@pytest.mark.asyncio
async def test_cmd_test_sse_invalid_timeout(capsys):
    # Provide invalid timeout value
    context = {}
    ok = await debug_mod.cmd_test_sse(["/test_sse", "--timeout", "abc"], context)
    assert ok is True
    captured = capsys.readouterr()
    # Should fall back to default timeout message
    assert "Invalid timeout value" in captured.out
    assert "Testing SSE Connection" in captured.out

@pytest.mark.asyncio
async def test_cmd_test_send_subscribe_no_text(capsys):
    # Missing text argument
    context = {}
    ok = await debug_mod.cmd_test_send_subscribe(["/test_send_subscribe"], context)
    assert ok is True
    captured = capsys.readouterr()
    assert "Error: No text provided" in captured.out


@pytest.mark.asyncio
async def test_cmd_debug_info_with_packages(monkeypatch, capsys):
    # Stub package versions to ensure import paths
    for mod_name in ['httpx', 'rich', 'prompt_toolkit', 'typer']:
        mod = types.ModuleType(mod_name)
        mod.__version__ = '9.9.9'
        monkeypatch.setitem(sys.modules, mod_name, mod)

    context = {}
    ok = await debug_mod.cmd_debug_info([], context)
    assert ok is True
    out = capsys.readouterr().out
    assert 'HTTPX: 9.9.9' in out
    assert 'Rich: 9.9.9' in out
    assert 'Prompt Toolkit: 9.9.9' in out
    assert 'Typer: 9.9.9' in out

@pytest.mark.asyncio
async def test_cmd_test_sse_with_client(monkeypatch, capsys):
    # Simulate existing streaming_client with transport
    class DummyTransport:
        def __init__(self):
            self.sse_endpoint = 'http://example.com/events'
    class DummyClient:
        def __init__(self):
            self.transport = DummyTransport()

    # Force httpx import to fail so HTTP path is skipped
    import builtins
    orig_import = builtins.__import__
    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == 'httpx':
            raise ImportError
        return orig_import(name, globals, locals, fromlist, level)
    monkeypatch.setattr(builtins, '__import__', fake_import)

    context = {'streaming_client': DummyClient(), 'base_url': 'http://example.com'}
    ok = await debug_mod.cmd_test_sse(['/test_sse'], context)
    assert ok is True
    out = capsys.readouterr().out
    assert 'Configured SSE endpoint: http://example.com/events' in out

    # Restore import
    monkeypatch.setattr(builtins, '__import__', orig_import)
