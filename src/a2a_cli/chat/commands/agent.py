#!/usr/bin/env python3
# a2a_cli/chat/commands/agent.py
"""
Agent-related commands for the A2A client interface.
"""
import logging
import json
from typing import List, Dict, Any, Optional

from rich import print
from rich.panel import Panel
from rich.table import Table
from rich.console import Console
from rich.markdown import Markdown
from rich.syntax import Syntax
from rich.text import Text

# Import the registration function
from a2a_cli.chat.commands import register_command

logger = logging.getLogger("a2a-cli")

async def fetch_agent_card(base_url: str) -> Optional[Dict[str, Any]]:
    """
    Fetch the agent card from the server.
    
    Args:
        base_url: The base URL of the server
        
    Returns:
        The agent card data, or None if not found
    """
    try:
        import httpx
        async with httpx.AsyncClient() as client:
            url = f"{base_url}/agent-card.json"
            logger.debug(f"Fetching agent card from {url}")
            
            response = await client.get(url, timeout=3.0)
            if response.status_code == 200:
                data = response.json()
                return data
            else:
                logger.debug(f"Agent card not available: {response.status_code}")
                return None
    except Exception as e:
        logger.debug(f"Error fetching agent card: {e}")
        return None

async def cmd_agent_card(cmd_parts: List[str], context: Dict[str, Any]) -> bool:
    """
    Display the agent card for the current server.
    
    Usage: /agent_card [--raw]
    
    Options:
      --raw  Show the raw JSON of the agent card
    """
    console = Console()
    
    # Check if connected
    base_url = context.get("base_url")
    if not base_url:
        print("[yellow]Not connected to any server. Use /connect to connect.[/yellow]")
        return True
    
    # Check if we want raw output
    raw_mode = len(cmd_parts) > 1 and cmd_parts[1] == "--raw"
    
    # Check if we already have agent info
    agent_info = context.get("agent_info")
    
    if not agent_info:
        print(f"[dim]Fetching agent card from {base_url}/agent-card.json...[/dim]")
        agent_info = await fetch_agent_card(base_url)
        
        if agent_info:
            # Store in context for future use
            context["agent_info"] = agent_info
        else:
            print(f"[yellow]No agent card found at {base_url}/agent-card.json[/yellow]")
            return True
    
    # Display the agent card
    if raw_mode:
        # Show raw JSON
        json_str = json.dumps(agent_info, indent=2)
        console.print(Syntax(json_str, "json", theme="monokai", line_numbers=True))
        return True
    
    # Extract information
    agent_name = agent_info.get("name", "Unknown Agent")
    agent_version = agent_info.get("version", "Unknown")
    description = agent_info.get("description", "No description provided")
    
    # Format the agent card content
    content = f"[bold cyan]{agent_name}[/bold cyan]"
    
    if agent_version != "Unknown":
        content += f" [dim]v{agent_version}[/dim]"
    
    content += f"\n\n{description}\n\n"
    
    # Capabilities section
    capabilities = []
    if isinstance(agent_info.get("capabilities"), dict):
        for key, value in agent_info.get("capabilities", {}).items():
            if isinstance(value, bool) and value:
                capabilities.append(key)
    elif isinstance(agent_info.get("capabilities"), list):
        capabilities = agent_info.get("capabilities", [])
    
    if capabilities:
        content += "[bold yellow]Capabilities[/bold yellow]\n\n"
        for cap in capabilities:
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
    
    # Skills section
    skills = agent_info.get("skills", [])
    if skills:
        content += "\n[bold yellow]Skills[/bold yellow]\n\n"
        for skill in skills:
            skill_name = skill.get("name", "Unnamed")
            skill_desc = skill.get("description", "")
            content += f"• [green]{skill_name}[/green] - {skill_desc}\n"
    
    # Process input/output modes if they exist
    input_modes = agent_info.get("default_input_modes", {})
    if input_modes and isinstance(input_modes, dict):
        content += "\n[bold yellow]Input Modes[/bold yellow]\n\n"
        for mode_type, mode_info in input_modes.items():
            # Handle different data structures
            if isinstance(mode_info, dict):
                enabled = mode_info.get("enabled", False)
                status = "[green]Enabled[/green]" if enabled else "[red]Disabled[/red]"
                content += f"• [magenta]{mode_type}[/magenta]: {status}"
                
                # Show configuration if available
                if "configuration" in mode_info and isinstance(mode_info["configuration"], dict):
                    config = mode_info["configuration"]
                    if config:
                        content += " - "
                        config_items = []
                        for key, value in config.items():
                            if isinstance(value, bool):
                                value_str = "[green]Yes[/green]" if value else "[red]No[/red]"
                            else:
                                value_str = str(value)
                            config_items.append(f"{key}: {value_str}")
                        content += ", ".join(config_items)
            elif isinstance(mode_info, bool):
                # Simple boolean flag
                status = "[green]Enabled[/green]" if mode_info else "[red]Disabled[/red]"
                content += f"• [magenta]{mode_type}[/magenta]: {status}"
            else:
                # Some other format - show what we can
                content += f"• [magenta]{mode_type}[/magenta]: {mode_info}"
            
            content += "\n"
    
    output_modes = agent_info.get("default_output_modes", {})
    if output_modes and isinstance(output_modes, dict):
        content += "\n[bold yellow]Output Modes[/bold yellow]\n\n"
        for mode_type, mode_info in output_modes.items():
            # Handle different data structures
            if isinstance(mode_info, dict):
                enabled = mode_info.get("enabled", False)
                status = "[green]Enabled[/green]" if enabled else "[red]Disabled[/red]"
                content += f"• [magenta]{mode_type}[/magenta]: {status}"
                
                # Show configuration if available
                if "configuration" in mode_info and isinstance(mode_info["configuration"], dict):
                    config = mode_info["configuration"]
                    if config:
                        content += " - "
                        config_items = []
                        for key, value in config.items():
                            if isinstance(value, bool):
                                value_str = "[green]Yes[/green]" if value else "[red]No[/red]"
                            else:
                                value_str = str(value)
                            config_items.append(f"{key}: {value_str}")
                        content += ", ".join(config_items)
            elif isinstance(mode_info, bool):
                # Simple boolean flag
                status = "[green]Enabled[/green]" if mode_info else "[red]Disabled[/red]"
                content += f"• [magenta]{mode_type}[/magenta]: {status}"
            else:
                # Some other format - show what we can
                content += f"• [magenta]{mode_type}[/magenta]: {mode_info}"
            
            content += "\n"
    
    # Additional information
    known_fields = {"name", "version", "description", "capabilities", "skills", "url", 
                   "default_input_modes", "default_output_modes"}
    extra_fields = {k: v for k, v in agent_info.items() if k not in known_fields}
    
    if extra_fields:
        content += "\n[bold yellow]Additional Information[/bold yellow]\n\n"
        for key, value in extra_fields.items():
            if isinstance(value, (dict, list)):
                # Preview complex data instead of just hiding it
                if isinstance(value, dict) and len(value) <= 3:
                    # For small dicts, show the keys
                    preview = ", ".join(f"{k}" for k in value.keys())
                    content += f"• [cyan]{key}:[/cyan] {{[dim]{preview}[/dim]}} [dim italic](use --raw for details)[/dim italic]\n"
                elif isinstance(value, list) and len(value) <= 5:
                    # For small lists, show count and brief content
                    preview = f"{len(value)} items"
                    if all(isinstance(x, str) for x in value):
                        preview += f": {', '.join(value[:3])}"
                        if len(value) > 3:
                            preview += ", ..."
                    content += f"• [cyan]{key}:[/cyan] [[dim]{preview}[/dim]] [dim italic](use --raw for details)[/dim italic]\n"
                else:
                    content += f"• [cyan]{key}:[/cyan] [dim italic]Complex data ({type(value).__name__}) - use --raw to view[/dim italic]\n"
            else:
                content += f"• [cyan]{key}:[/cyan] {value}\n"
    
    # Show mount point info if available
    if "url" in agent_info or "mount" in agent_info or "basePath" in agent_info:
        content += "\n[bold yellow]Connection Information[/bold yellow]\n\n"
        if "url" in agent_info:
            content += f"• [cyan]URL:[/cyan] {agent_info['url']}\n"
        if "mount" in agent_info:
            content += f"• [cyan]Mount point:[/cyan] /{agent_info['mount']}\n"
        elif "basePath" in agent_info:
            content += f"• [cyan]Base path:[/cyan] {agent_info['basePath']}\n"
        
        # Show the actual connected base URL from context
        if base_url:
            content += f"• [cyan]Connected to:[/cyan] {base_url}\n"
    
    # Use a panel with Rich text formatting
    console.print(Panel(
        Text.from_markup(content),
        title="Agent Card",
        border_style="cyan"
    ))
    
    return True

# Register the commands
register_command("/agent_card", cmd_agent_card)
register_command("/agent", cmd_agent_card)  # Alias