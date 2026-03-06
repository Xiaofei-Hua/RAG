"""
Graph Module for RAG Pipeline

This module implements the LangGraph-based RAG workflow with the following components:

- AgentState: State management for the graph
- agent_node: Decides whether to use tools or respond directly
- generate_node: Produces the final answer
- rewrite_node: Improves queries for better retrieval
- RAGGraph: Main graph builder class

Graph Flow:
    START → agent → [tools_condition]
                         ↓
                      retrieve → grade → [generate | rewrite]
                         ↓                      ↓
                      END                   generate → END
                                              ↓
                                           agent (retry)

Usage:
    >>> from graph import create_rag_graph, run_interactive_session
    >>> graph = create_rag_graph()
    >>> run_interactive_session(graph)
"""

from graph.graph_state import (
    AgentState,
    GraphMetadata,
    Grade,
    NodeType,
    RouteDecision,
    StateManager,
    RewrittenQuery,
    GeneratedAnswer,
)

from graph.get_human_message import (
    get_last_human_message,
    get_last_ai_message,
    get_messages_by_type,
    get_message_content,
    MessageExtractor,
    MessageNotFoundError,
)

from graph.agent_node import (
    agent_node,
    AgentNode,
    AgentNodeConfig,
)

from graph.generate_node import (
    generate,
    GenerateNode,
    GenerateNodeConfig,
)

from graph.rewrite_node import (
    rewrite,
    RewriteNode,
    RewriteNodeConfig,
)

from graph.graph import (
    RAGGraph,
    RAGGraphConfig,
    create_rag_graph,
    get_rag_graph,
    run_interactive_session,
)

__all__ = [
    # State
    "AgentState",
    "GraphMetadata",
    "Grade",
    "NodeType",
    "RouteDecision",
    "StateManager",
    "RewrittenQuery",
    "GeneratedAnswer",
    # Message utilities
    "get_last_human_message",
    "get_last_ai_message",
    "get_messages_by_type",
    "get_message_content",
    "MessageExtractor",
    "MessageNotFoundError",
    # Agent node
    "agent_node",
    "AgentNode",
    "AgentNodeConfig",
    # Generate node
    "generate",
    "GenerateNode",
    "GenerateNodeConfig",
    # Rewrite node
    "rewrite",
    "RewriteNode",
    "RewriteNodeConfig",
    # Graph
    "RAGGraph",
    "RAGGraphConfig",
    "create_rag_graph",
    "get_rag_graph",
    "run_interactive_session",
]

# Version
__version__ = "2.0.0"