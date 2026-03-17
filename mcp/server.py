"""
MCP Server for Enterprise RAG Platform

Implements the Model Context Protocol for standardized tool calling.

MCP allows AI models to:
- Call external tools
- Access resources
- Execute actions

Protocol: https://modelcontextprotocol.io
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Union

from utils.log_utils import log

__all__ = [
    "MCPServer",
    "MCPServerConfig",
    "MCPTool",
    "MCPToolResult",
]


@dataclass
class MCPServerConfig:
    """Configuration for MCP server."""
    name: str = "rag-mcp-server"
    version: str = "1.0.0"
    description: str = "MCP Server for Enterprise RAG Platform"


@dataclass
class MCPTool:
    """MCP tool definition."""
    name: str
    description: str
    input_schema: Dict[str, Any]
    handler: Callable


@dataclass
class MCPToolResult:
    """Result from tool execution."""
    success: bool
    result: Any
    error: Optional[str] = None


class MCPServer:
    """
    MCP Server implementation.

    Provides a registry for tools and handles tool execution.

    Example:
        >>> server = MCPServer()
        >>> server.register_tool(
        ...     name="web_search",
        ...     description="Search the web",
        ...     input_schema={"query": {"type": "string"}},
        ...     handler=search_function,
        ... )
        >>> result = await server.call_tool("web_search", {"query": "hello"})
    """

    def __init__(self, config: Optional[MCPServerConfig] = None):
        """
        Initialize MCP server.

        Args:
            config: Server configuration
        """
        self.config = config or MCPServerConfig()
        self._tools: Dict[str, MCPTool] = {}

        log.info(f"MCPServer initialized: {self.config.name}")

    def register_tool(
        self,
        name: str,
        description: str,
        input_schema: Dict[str, Any],
        handler: Callable,
    ):
        """
        Register a new tool.

        Args:
            name: Tool name (unique identifier)
            description: Tool description for AI to understand
            input_schema: JSON schema for input validation
            handler: Async or sync function to execute
        """
        if name in self._tools:
            log.warning(f"Tool '{name}' already registered, overwriting")

        self._tools[name] = MCPTool(
            name=name,
            description=description,
            input_schema=input_schema,
            handler=handler,
        )

        log.debug(f"Tool registered: {name}")

    def unregister_tool(self, name: str):
        """Unregister a tool."""
        if name in self._tools:
            del self._tools[name]
            log.debug(f"Tool unregistered: {name}")

    def list_tools(self) -> List[Dict[str, Any]]:
        """List all registered tools in MCP format."""
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "inputSchema": tool.input_schema,
            }
            for tool in self._tools.values()
        ]

    async def call_tool(
        self,
        name: str,
        arguments: Dict[str, Any],
    ) -> MCPToolResult:
        """
        Execute a tool.

        Args:
            name: Tool name
            arguments: Tool arguments

        Returns:
            MCPToolResult with execution result
        """
        if name not in self._tools:
            return MCPToolResult(
                success=False,
                result=None,
                error=f"Tool '{name}' not found",
            )

        tool = self._tools[name]

        try:
            log.info(f"Executing tool: {name} with args: {arguments}")

            # Handle async and sync handlers
            import asyncio
            if asyncio.iscoroutinefunction(tool.handler):
                result = await tool.handler(**arguments)
            else:
                result = tool.handler(**arguments)

            return MCPToolResult(
                success=True,
                result=result,
            )

        except Exception as e:
            log.error(f"Tool execution failed: {e}")
            return MCPToolResult(
                success=False,
                result=None,
                error=str(e),
            )

    def get_tool_schemas_for_llm(self) -> List[Dict[str, Any]]:
        """
        Get tool schemas formatted for LLM tool binding.

        Returns:
            List of tool definitions in LangChain format
        """
        schemas = []
        for tool in self._tools.values():
            schemas.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.input_schema,
                }
            })
        return schemas

    def bind_to_llm(self, llm):
        """
        Bind tools to an LLM.

        Args:
            llm: LangChain LLM instance

        Returns:
            LLM with tools bound
        """
        schemas = self.get_tool_schemas_for_llm()
        return llm.bind_tools(schemas)


# Pre-configured tools
def setup_default_tools(server: MCPServer):
    """Register default tools for RAG platform."""

    # Web search tool
    async def web_search(query: str, max_results: int = 3) -> str:
        """Search the web for information."""
        try:
            from models.llm_models import get_web_search_tool
            tool = get_web_search_tool()
            if tool is None:
                return "Web search unavailable: Tavily API key not configured"

            result = await tool.ainvoke({"query": query})
            return str(result)
        except Exception as e:
            return f"Web search failed: {e}"

    server.register_tool(
        name="web_search",
        description="Search the web for up-to-date information. Use when the knowledge base doesn't have the answer.",
        input_schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query"
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results",
                    "default": 3
                }
            },
            "required": ["query"]
        },
        handler=web_search,
    )

    # Calculator tool
    def calculator(expression: str) -> str:
        """Evaluate mathematical expressions safely."""
        import ast
        import operator

        # Safe operators
        operators = {
            ast.Add: operator.add,
            ast.Sub: operator.sub,
            ast.Mult: operator.mul,
            ast.Div: operator.truediv,
            ast.Pow: operator.pow,
            ast.Mod: operator.mod,
        }

        def eval_expr(node):
            if isinstance(node, ast.Num):
                return node.n
            elif isinstance(node, ast.BinOp):
                op = operators.get(type(node.op))
                if op is None:
                    raise ValueError(f"Unsupported operator: {type(node.op)}")
                return op(eval_expr(node.left), eval_expr(node.right))
            else:
                raise ValueError(f"Unsupported node: {type(node)}")

        try:
            tree = ast.parse(expression, mode='eval')
            result = eval_expr(tree.body)
            return str(result)
        except Exception as e:
            return f"Calculation error: {e}"

    server.register_tool(
        name="calculator",
        description="Evaluate mathematical expressions. Example: '2 + 2' or '10 * 5'",
        input_schema={
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "Mathematical expression to evaluate"
                }
            },
            "required": ["expression"]
        },
        handler=calculator,
    )

    # Document query tool
    async def query_documents(query: str, top_k: int = 5) -> str:
        """Query the knowledge base for specific documents."""
        try:
            from core.retrieval.hybrid_retriever import get_hybrid_retriever
            retriever = get_hybrid_retriever()
            docs = retriever.retrieve(query, top_k=top_k)

            if not docs:
                return "No relevant documents found."

            results = []
            for i, doc in enumerate(docs, 1):
                source = doc.metadata.get("source", "Unknown")
                results.append(f"[{i}] {doc.page_content[:200]}... (Source: {source})")

            return "\n\n".join(results)
        except Exception as e:
            return f"Query failed: {e}"

    server.register_tool(
        name="query_documents",
        description="Query the knowledge base for documents about semiconductors and chips.",
        input_schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query"
                },
                "top_k": {
                    "type": "integer",
                    "description": "Number of results",
                    "default": 5
                }
            },
            "required": ["query"]
        },
        handler=query_documents,
    )

    log.info("Default MCP tools registered")


# Module-level server instance
_mcp_server: Optional[MCPServer] = None


def get_mcp_server() -> MCPServer:
    """Get or create MCP server instance with default tools."""
    global _mcp_server
    if _mcp_server is None:
        _mcp_server = MCPServer()
        setup_default_tools(_mcp_server)
    return _mcp_server