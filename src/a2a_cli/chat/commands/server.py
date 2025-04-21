#!/usr/bin/env python3
# a2a_cli/chat/commands/server.py
"""
Server information commands for the A2A client interface.
Displays detailed information about the current server connection.
"""
import logging
from typing import List, Dict, Any

from rich import print
from rich.panel import Panel
from rich.table import Table
from rich.console import Console
from rich.text import Text

# Import the registration function
from a2a_cli.chat.commands import register_command

logger = logging.getLogger("a2a-cli")

async def cmd_server(cmd_parts: List[str], context: Dict[str, Any]) -> bool:
    """
    Display current server connection information.

    Usage: /server
    """
    console = Console()

    # Check if connected
    base_url = context.get("base_url")
    if not base_url:
        print("[yellow]Not connected to any server. Use /connect to connect.[/yellow]")
        return True

    # Get agent info if available
    agent_info = context.get("agent_info", {})
    
    # If agent info doesn't contain a name, try to fetch it again
    if not agent_info or "name" not in agent_info:
        try:
            # Try to extract agent name from base_url path
            path_parts = base_url.rstrip("/").split("/")
            if len(path_parts) > 3 and path_parts[-1]:
                possible_name = path_parts[-1].replace("_", " ").title()
                agent_name = possible_name
            else:
                agent_name = "Unknown Agent"
        except Exception:
            agent_name = "Unknown Agent"
    else:
        agent_name = agent_info.get("name", "Unknown Agent")
    
    agent_version = agent_info.get("version", "Unknown")
    
    # Get the actual connected URL (from transports)
    actual_base_url = base_url
    actual_rpc_url = base_url.rstrip("/") + "/rpc"
    
    # Check if there's a client to get the actual URLs from
    client = context.get("client")
    if client and hasattr(client, "transport") and hasattr(client.transport, "endpoint"):
        actual_rpc_url = client.transport.endpoint
        # Extract base URL from RPC endpoint
        if actual_rpc_url.endswith("/rpc"):
            actual_base_url = actual_rpc_url[:-4]  # Remove /rpc
    
    # Ensure events URL uses the same base path as RPC
    actual_events_url = actual_base_url + "/events"
    
    # Try to guess agent name from URL if still unknown
    if agent_name == "Unknown Agent" and "pirate_agent" in actual_base_url:
        agent_name = "Pirate Agent"
    
    # Connection details panel content
    content = f"[bold cyan]{agent_name}[/bold cyan]"
    if agent_version != "Unknown":
        content += f" [dim]v{agent_version}[/dim]"
    content += "\n\n"
    
    # Add agent description if available
    if "description" in agent_info:
        content += f"{agent_info['description']}\n\n"
    
    # Connection details
    content += "[bold yellow]Connection Details[/bold yellow]\n\n"
    content += f"• [cyan]Base URL:[/cyan] {actual_base_url}\n"
    content += f"• [cyan]RPC Endpoint:[/cyan] {actual_rpc_url}\n"
    content += f"• [cyan]Events Endpoint:[/cyan] {actual_events_url}\n"
    
    # Connection status
    content += "\n[bold yellow]Connection Status[/bold yellow]\n\n"
    client_status = "[green]Connected[/green]" if context.get("client") else "[red]Disconnected[/red]"
    content += f"• [cyan]Client Status:[/cyan] {client_status}\n"
    
    streaming_status = "[green]Available[/green]" if context.get("streaming_client") else "[yellow]Not initialized[/yellow]"
    content += f"• [cyan]Streaming Status:[/cyan] {streaming_status}\n"
    
    # Show capabilities if available
    if agent_info and "capabilities" in agent_info:
        caps = agent_info["capabilities"]
        if caps:
            content += "\n[bold yellow]Agent Capabilities[/bold yellow]\n\n"
            for cap in caps:
                # Add descriptions for common capabilities
                desc = {
                    "streaming": "Supports real-time streaming responses",
                    "tasks/sendSubscribe": "Supports combined send and subscribe operations",
                    "tasks/resubscribe": "Supports subscribing to existing tasks",
                    "tasks/send": "Supports sending tasks",
                    "tasks/get": "Supports retrieving task status",
                    "tasks/cancel": "Supports canceling tasks"
                }.get(cap, "")
                
                if desc:
                    content += f"• [green]{cap}[/green] - {desc}\n"
                else:
                    content += f"• [green]{cap}[/green]\n"
    
    # Use a panel with Rich text formatting
    console.print(Panel(
        Text.from_markup(content),
        title=f"Connected to {agent_name}",
        border_style="cyan"
    ))

    return True

# Register the command
register_command("/server", cmd_server)