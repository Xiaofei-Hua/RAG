"""
MCP (Model Context Protocol) Module

Provides MCP server implementation for tool calling.
"""

from mcp.server import MCPServer, MCPServerConfig

__all__ = [
    "MCPServer",
    "MCPServerConfig",
]