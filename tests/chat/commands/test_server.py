# tests/chat/commands/test_server.py
"""
Unit tests for the server command.
"""
import pytest
from unittest.mock import MagicMock, patch, ANY
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from a2a_cli.chat.commands.server import cmd_server

@pytest.fixture

def mock_context():
    return {
        "base_url": "http://localhost:8000/pirate_agent",
        "client": MagicMock(),
        "streaming_client": MagicMock(),
        "agent_info": {
            "name": "Pirate Agent",
            "version": "0.1.0",
            "description": "Converts your text into salty pirate‑speak",
            "capabilities": ["streaming"]
        }
    }

@pytest.fixture
def mock_context_minimal():
    return {
        "base_url": "http://localhost:8000/pirate_agent",
        "client": MagicMock(),
        "streaming_client": MagicMock()
    }

@pytest.fixture
def mock_context_no_connection():
    return {}

@pytest.mark.asyncio
async def test_server_command_no_connection(mock_context_no_connection):
    """Test server command when not connected."""
    with patch('a2a_cli.chat.commands.server.print') as mock_print:
        result = await cmd_server(["/server"], mock_context_no_connection)
        assert result is True
        mock_print.assert_called_once()
        args = mock_print.call_args[0][0]
        assert "Not connected" in str(args)

@pytest.mark.asyncio
async def test_server_command_with_agent_info(mock_context):
    """Test server command with full agent info."""
    with patch('a2a_cli.chat.commands.server.Text.from_markup', return_value=MagicMock()) as mock_text:
        with patch('a2a_cli.chat.commands.server.Panel') as mock_panel:
            with patch('a2a_cli.chat.commands.server.Console.print') as mock_print:
                # Setup client mock to return RPC endpoint
                mock_context["client"].transport.endpoint = "http://localhost:8000/pirate_agent/rpc"
                
                result = await cmd_server(["/server"], mock_context)
                assert result is True
                
                # Check that Text.from_markup was called with content containing expected strings
                text_content = mock_text.call_args[0][0]
                assert "Pirate Agent" in text_content
                assert "v0.1.0" in text_content
                assert "Converts your text into salty pirate‑speak" in text_content
                assert "[cyan]Base URL:[/cyan] http://localhost:8000/pirate_agent" in text_content
                assert "[cyan]RPC Endpoint:[/cyan] http://localhost:8000/pirate_agent/rpc" in text_content
                assert "[cyan]Events Endpoint:[/cyan] http://localhost:8000/pirate_agent/events" in text_content
                assert "[cyan]Client Status:[/cyan] [green]Connected[/green]" in text_content
                assert "[cyan]Streaming Status:[/cyan] [green]Available[/green]" in text_content
                assert "streaming" in text_content
                
                # Check Panel was called with the right title
                mock_panel.assert_called_once()
                panel_args = mock_panel.call_args[1]
                assert panel_args["title"] == "Connected to Pirate Agent"
                assert panel_args["border_style"] == "cyan"

@pytest.mark.asyncio
async def test_server_command_without_agent_info(mock_context_minimal):
    """Test server command with minimal context (no agent info)."""
    with patch('a2a_cli.chat.commands.server.Text.from_markup', return_value=MagicMock()) as mock_text:
        with patch('a2a_cli.chat.commands.server.Panel') as mock_panel:
            with patch('a2a_cli.chat.commands.server.Console.print') as mock_print:
                # Setup client mock to return RPC endpoint
                mock_context_minimal["client"].transport.endpoint = "http://localhost:8000/pirate_agent/rpc"
                
                result = await cmd_server(["/server"], mock_context_minimal)
                assert result is True
                
                # Check text content - should extract name from URL
                text_content = mock_text.call_args[0][0]
                assert "Pirate Agent" in text_content  # Should extract from URL
                assert "[cyan]Base URL:[/cyan] http://localhost:8000/pirate_agent" in text_content
                assert "[cyan]RPC Endpoint:[/cyan] http://localhost:8000/pirate_agent/rpc" in text_content
                assert "[cyan]Events Endpoint:[/cyan] http://localhost:8000/pirate_agent/events" in text_content
                
                # Check Panel was called with the right title
                mock_panel.assert_called_once()
                panel_args = mock_panel.call_args[1]
                assert panel_args["title"] == "Connected to Pirate Agent"

@pytest.mark.asyncio
async def test_server_command_transport_without_endpoint(mock_context):
    """Test server command with transport that doesn't have endpoint attribute."""
    with patch('a2a_cli.chat.commands.server.Text.from_markup', return_value=MagicMock()) as mock_text:
        with patch('a2a_cli.chat.commands.server.Panel') as mock_panel:
            with patch('a2a_cli.chat.commands.server.Console.print') as mock_print:
                # Remove endpoint attribute from transport
                mock_context["client"].transport = MagicMock(spec=[])
                
                result = await cmd_server(["/server"], mock_context)
                assert result is True
                
                # Check text content - should use base_url + /rpc
                text_content = mock_text.call_args[0][0]
                assert "[cyan]Base URL:[/cyan] http://localhost:8000/pirate_agent" in text_content
                assert "[cyan]RPC Endpoint:[/cyan] http://localhost:8000/pirate_agent/rpc" in text_content

@pytest.mark.asyncio
async def test_server_command_no_client(mock_context):
    """Test server command when client is not available."""
    with patch('a2a_cli.chat.commands.server.Text.from_markup', return_value=MagicMock()) as mock_text:
        with patch('a2a_cli.chat.commands.server.Panel') as mock_panel:
            with patch('a2a_cli.chat.commands.server.Console.print') as mock_print:
                # Remove client
                mock_context.pop("client")
                
                result = await cmd_server(["/server"], mock_context)
                assert result is True
                
                # Check text content - should use base_url
                text_content = mock_text.call_args[0][0]
                assert "[cyan]Client Status:[/cyan] [red]Disconnected[/red]" in text_content

@pytest.mark.asyncio
async def test_server_command_no_streaming_client(mock_context):
    """Test server command when streaming client is not available."""
    with patch('a2a_cli.chat.commands.server.Text.from_markup', return_value=MagicMock()) as mock_text:
        with patch('a2a_cli.chat.commands.server.Panel') as mock_panel:
            with patch('a2a_cli.chat.commands.server.Console.print') as mock_print:
                # Remove streaming client
                mock_context.pop("streaming_client")
                
                result = await cmd_server(["/server"], mock_context)
                assert result is True
                
                # Check text content
                text_content = mock_text.call_args[0][0]
                assert "[cyan]Streaming Status:[/cyan] [yellow]Not initialized[/yellow]" in text_content

@pytest.mark.asyncio
async def test_server_command_with_capabilities(mock_context):
    """Test server command with capabilities in agent info."""
    with patch('a2a_cli.chat.commands.server.Text.from_markup', return_value=MagicMock()) as mock_text:
        with patch('a2a_cli.chat.commands.server.Panel') as mock_panel:
            with patch('a2a_cli.chat.commands.server.Console.print') as mock_print:
                # Add more capabilities
                mock_context["agent_info"]["capabilities"] = [
                    "streaming", 
                    "tasks/sendSubscribe", 
                    "tasks/resubscribe",
                    "custom_capability"
                ]
                
                result = await cmd_server(["/server"], mock_context)
                assert result is True
                
                # Check text content
                text_content = mock_text.call_args[0][0]
                
                # Check if all capabilities are shown
                assert "streaming" in text_content
                assert "tasks/sendSubscribe" in text_content
                assert "tasks/resubscribe" in text_content
                assert "custom_capability" in text_content
                
                # Check if descriptions are shown for known capabilities
                assert "Supports real-time streaming responses" in text_content
                assert "Supports combined send and subscribe operations" in text_content
                assert "Supports subscribing to existing tasks" in text_content
