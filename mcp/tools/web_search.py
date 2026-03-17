"""
Web Search Tool for MCP

Provides web search capability through Tavily API.
"""

from __future__ import annotations

from typing import Dict, Any, Optional

from utils.log_utils import log


async def web_search_tool(query: str, max_results: int = 3) -> Dict[str, Any]:
    """
    Web search tool using Tavily API.

    Args:
        query: Search query string
        max_results: Maximum number of results

    Returns:
        Dictionary with search results
    """
    try:
        from models.llm_models import get_web_search_tool
        tool = get_web_search_tool()

        if tool is None:
            return {
                "success": False,
                "error": "Web search unavailable: Tavily API key not configured"
            }

        result = await tool.ainvoke({
            "query": query,
            "max_results": max_results
        })

        return {
            "success": True,
            "results": result,
        }

    except Exception as e:
        log.error(f"Web search failed: {e}")
        return {
            "success": False,
            "error": str(e),
        }


# Tool definition for MCP
WEB_SEARCH_TOOL_DEF = {
    "name": "web_search",
    "description": "Search the web for current information when the knowledge base doesn't have the answer.",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query"
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of results to return",
                "default": 3
            }
        },
        "required": ["query"]
    }
}