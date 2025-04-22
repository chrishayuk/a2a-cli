# tests/chat/commands/test_agent.py

import pytest
import json
import sys
import types
from rich.syntax import Syntax
from rich.panel import Panel
from rich.console import Console

import a2a_cli.chat.commands.agent as agent_mod


class DummyResponse:
    def __init__(self, status_code=200, data=None):
        self.status_code = status_code
        self._data = data if data is not None else {"foo": "bar"}

    def json(self):
        return self._data


class DummyClient:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, timeout):
        return DummyResponse()


@pytest.mark.asyncio
async def test_fetch_agent_card_success(monkeypatch):
    # Stub httpx via sys.modules to ensure our DummyClient is used
    httpx_mod = types.ModuleType('httpx')
    httpx_mod.AsyncClient = DummyClient
    monkeypatch.setitem(sys.modules, 'httpx', httpx_mod)

    data = await agent_mod.fetch_agent_card("http://example.com")
    assert data == {"foo": "bar"}


@pytest.mark.asyncio
async def test_fetch_agent_card_non_200(monkeypatch):
    # Return a 404
    class BadClient(DummyClient):
        async def get(self, url, timeout):
            return DummyResponse(status_code=404)

    httpx_mod = types.ModuleType('httpx')
    httpx_mod.AsyncClient = BadClient
    monkeypatch.setitem(sys.modules, 'httpx', httpx_mod)

    result = await agent_mod.fetch_agent_card("http://example.com")
    assert result is None


@pytest.mark.asyncio
async def test_fetch_agent_card_exception(monkeypatch):
    # Make the constructor raise
    class RaisingClient:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("connection failed")

    httpx_mod = types.ModuleType('httpx')
    httpx_mod.AsyncClient = RaisingClient
    monkeypatch.setitem(sys.modules, 'httpx', httpx_mod)

    result = await agent_mod.fetch_agent_card("http://example.com")
    assert result is None


@pytest.mark.asyncio
async def test_cmd_agent_card_not_connected(capsys):
    # No base_url in context
    context = {}
    ok = await agent_mod.cmd_agent_card([], context)
    assert ok is True

    captured = capsys.readouterr()
    assert "Not connected to any server" in captured.out


@pytest.mark.asyncio
async def test_cmd_agent_card_raw_mode(monkeypatch):
    # Provide agent_info and --raw flag, capture Console.print call
    context = {
        "base_url": "http://example.com",
        "agent_info": {"name": "X", "version": "1.0", "description": "Desc"}
    }

    printed = {}
    def fake_print(self, renderable, *args, **kwargs):
        printed["last"] = renderable

    monkeypatch.setattr(Console, "print", fake_print)

    ok = await agent_mod.cmd_agent_card(["/agent_card", "--raw"], context)
    assert ok is True
    assert isinstance(printed.get("last"), Syntax)


@pytest.mark.asyncio
async def test_cmd_agent_card_formatted(monkeypatch):
    # No agent_info in context → fetch_agent_card should be called
    context = {"base_url": "http://example.com"}

    agent_data = {
        "name": "AgentX",
        "version": "2.5",
        "description": "Test agent",
        "capabilities": {"tasks/send": True, "streaming": False},
        "skills": [{"name": "SkillA", "description": "Does A"}],
    }

    async def fake_fetch(base_url):
        return agent_data

    monkeypatch.setattr(agent_mod, "fetch_agent_card", fake_fetch)

    printed = {}
    def fake_console_print(self, panel, *args, **kwargs):
        printed["panel"] = panel

    monkeypatch.setattr(Console, "print", fake_console_print)

    ok = await agent_mod.cmd_agent_card(["/agent_card"], context)
    assert ok is True

    panel = printed.get("panel")
    assert isinstance(panel, Panel)

    text = panel.renderable
    plain = text.plain

    assert "AgentX" in plain
    assert "v2.5" in plain
    assert "Test agent" in plain
    assert "tasks/send" in plain
    assert "SkillA" in plain
