"""
MCP Tools Module

Defines MCP-compatible tools for the RAG platform.
"""

from mcp.tools.web_search import web_search_tool
from mcp.tools.calculator import calculator_tool

__all__ = [
    "web_search_tool",
    "calculator_tool",
]