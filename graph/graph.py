"""
RAG Graph - Main Workflow Definition

Implements the LangGraph workflow for the RAG pipeline:
    User Question → Agent → Retrieve → Grade → Generate/Rewrite → Answer

Optimized for low-resource servers with:
- Lazy initialization of components
- Configurable graph parameters
- Memory-efficient checkpointing
- Comprehensive error handling
- Session management

Graph Flow:
    START → agent → [tools_condition]
                         ↓
                      retrieve → grade_documents → [generate | rewrite]
                         ↓                              ↓
                      END                           generate → END
                                                      ↓
                                                   agent (retry)
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Literal, Optional

from langchain_core.messages import BaseMessage, HumanMessage
from langchain_core.language_models import BaseChatModel
from langchain_core.prompts import PromptTemplate, ChatPromptTemplate
from langgraph.checkpoint.memory import MemorySaver
from langgraph.constants import START, END
from langgraph.graph import StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from graph.graph_state import AgentState, Grade
from graph.agent_node import agent_node
from graph.generate_node import generate
from graph.get_human_message import get_last_human_message
from graph.rewrite_node import rewrite
from core.prompts.aircraft_prompts import GRADE_SYSTEM_PROMPT, GRADE_HUMAN_PROMPT
from utils.log_utils import log

__all__ = [
    "RAGGraphConfig",
    "RAGGraph",
    "create_rag_graph",
    "run_interactive_session",
]


# =============================================================================
# Configuration
# =============================================================================

@dataclass
class RAGGraphConfig:
    """
    Configuration for the RAG graph.

    Optimized for low-resource servers (4GB RAM, 4 CPU).
    """
    # Session settings
    session_id: Optional[str] = None
    thread_id: Optional[str] = None

    # Grading settings
    grade_system_prompt: str = GRADE_SYSTEM_PROMPT

    grade_human_prompt: str = GRADE_HUMAN_PROMPT

    # Retry settings
    max_retries: int = 2
    retry_delay: float = 1.0

    # Memory settings
    use_memory: bool = True

    def __post_init__(self):
        if self.session_id is None:
            self.session_id = str(uuid.uuid4())
        if self.thread_id is None:
            self.thread_id = str(uuid.uuid4())


# =============================================================================
# Grading Function
# =============================================================================

def create_grade_function(
    llm: BaseChatModel,
    config: Optional[RAGGraphConfig] = None,
) -> Callable[[AgentState], Literal["generate", "rewrite"]]:
    """
    Create the grade documents function with injected dependencies.

    Args:
        llm: Language model for grading
        config: Graph configuration

    Returns:
        Grading function for use in the graph
    """
    config = config or RAGGraphConfig()

    # Create structured output LLM
    llm_with_structured = llm.with_structured_output(Grade)

    # Create prompt
    prompt = ChatPromptTemplate.from_messages([
        ("system", config.grade_system_prompt),
        ("human", config.grade_human_prompt),
    ])

    chain = prompt | llm_with_structured

    def grade_documents(state: AgentState) -> Literal["generate", "rewrite"]:
        """
        Judge whether retrieved documents are relevant to the question.

        Args:
            state: Current graph state

        Returns:
            "generate" if documents are relevant, "rewrite" otherwise
        """
        log.info("---检查文档相关性---")

        # 检查重写次数限制
        rewrite_count = state.get("rewrite_count", 0)
        max_rewrites = state.get("max_rewrites", 3)

        if rewrite_count >= max_rewrites:
            log.warning(f"已达到最大重写次数 {rewrite_count}/{max_rewrites}, 强制进入生成节点")
            return "generate"

        messages = state["messages"]
        last_message = messages[-1]

        try:
            question = get_last_human_message(messages).content
            docs = last_message.content

            result = chain.invoke({
                "question": question,
                "context": docs
            })

            if result.is_relevant:
                log.info("---文档相关, 进入生成节点---")
                return "generate"
            else:
                log.info(f"---文档不相关, 进入重写节点 ({rewrite_count + 1}/{max_rewrites})---")
                return "rewrite"

        except Exception as e:
            log.error(f"Grading failed: {e}")
            # 检查是否还能重试
            if rewrite_count >= max_rewrites:
                log.warning("已达最大重写次数，强制生成")
                return "generate"
            return "rewrite"

    return grade_documents


# =============================================================================
# Graph Builder Class
# =============================================================================

class RAGGraph:
    """
    RAG Graph builder with lazy initialization.

    This class encapsulates the graph construction logic and provides
    a clean interface for creating and running the RAG pipeline.

    Features:
    - Lazy initialization of components
    - Configurable parameters
    - Session management
    - Memory checkpointing
    """

    def __init__(
        self,
        llm: Optional[BaseChatModel] = None,
        tools: Optional[List] = None,
        config: Optional[RAGGraphConfig] = None,
    ):
        """
        Initialize the RAG graph.

        Args:
            llm: Language model (lazy loaded if not provided)
            tools: List of tools (lazy loaded if not provided)
            config: Graph configuration
        """
        self._llm = llm
        self._tools = tools
        self._config = config or RAGGraphConfig()
        self._graph = None
        self._memory = None
        self._grade_function = None

    @property
    def llm(self) -> BaseChatModel:
        """Get LLM (lazy initialization)."""
        if self._llm is None:
            from models.llm_models import get_llm
            self._llm = get_llm()
        return self._llm

    @property
    def tools(self) -> List:
        """Get tools (lazy initialization)."""
        if self._tools is None:
            from tools.retriever_tools import get_retriever_tool
            self._tools = [get_retriever_tool()]
        return self._tools

    @property
    def grade_function(self):
        """Get grade function (lazy initialization)."""
        if self._grade_function is None:
            self._grade_function = create_grade_function(self.llm, self._config)
        return self._grade_function

    def build(self) -> StateGraph:
        """
        Build the RAG graph.

        Returns:
            Compiled StateGraph ready for execution
        """
        log.info("Building RAG graph...")

        # Create state graph
        workflow = StateGraph(AgentState)

        # Add nodes
        workflow.add_node("agent", agent_node)
        workflow.add_node("retrieve", ToolNode(self.tools))
        workflow.add_node("rewrite", rewrite)
        workflow.add_node("generate", generate)

        # Add edges
        workflow.add_edge(START, "agent")

        # Conditional edge from agent
        workflow.add_conditional_edges(
            "agent",
            tools_condition,
            {"tools": "retrieve", END: END}
        )

        # Conditional edge from retrieve (grading)
        workflow.add_conditional_edges(
            "retrieve",
            self.grade_function,
        )

        # Rewrite goes back to agent for retry
        workflow.add_edge("rewrite", "agent")

        # Generate ends the flow
        workflow.add_edge("generate", END)

        # Set up memory checkpointing (SQLite for persistence across restarts)
        if self._config.use_memory:
            try:
                import sqlite3
                from langgraph.checkpoint.sqlite import SqliteSaver
                import os
                os.makedirs("./data", exist_ok=True)
                conn = sqlite3.connect(
                    "./data/checkpoints.db",
                    check_same_thread=False,
                )
                self._memory = SqliteSaver(conn)
                log.info("Using SQLite checkpoint for graph persistence")
            except ImportError:
                log.warning("langgraph-checkpoint-sqlite not installed, using MemorySaver")
                self._memory = MemorySaver()
            self._graph = workflow.compile(checkpointer=self._memory)
        else:
            self._graph = workflow.compile()

        log.info("RAG graph built successfully")
        return self._graph

    @property
    def graph(self):
        """Get the compiled graph (lazy build)."""
        if self._graph is None:
            self.build()
        return self._graph

    def invoke(
        self,
        question: str,
        thread_id: Optional[str] = None,
        max_rewrites: int = 3,
    ) -> Dict[str, Any]:
        """
        Invoke the graph with a question.

        Args:
            question: User's question
            thread_id: Optional thread ID for session continuity
            max_rewrites: Maximum number of query rewrites (default 3)

        Returns:
            Final state after execution
        """
        thread_id = thread_id or self._config.thread_id

        config = {
            "configurable": {
                "thread_id": thread_id,
            }
        }

        # Initialize state with rewrite count tracking
        inputs = {
            "messages": [HumanMessage(content=question)],
            "rewrite_count": 0,
            "max_rewrites": max_rewrites,
        }

        return self.graph.invoke(inputs, config=config)

    def stream(
        self,
        question: str,
        thread_id: Optional[str] = None,
        stream_mode: str = "values",
        max_rewrites: int = 3,
    ):
        """
        Stream the graph execution.

        Args:
            question: User's question
            thread_id: Optional thread ID for session continuity
            stream_mode: Streaming mode ("values" or "updates")
            max_rewrites: Maximum number of query rewrites (default 3)

        Yields:
            State updates during execution
        """
        thread_id = thread_id or self._config.thread_id

        config = {
            "configurable": {
                "thread_id": thread_id,
            }
        }

        inputs = {
            "messages": [HumanMessage(content=question)],
            "rewrite_count": 0,  # 重置重写计数
            "max_rewrites": max_rewrites,
        }

        yield from self.graph.stream(inputs, config=config, stream_mode=stream_mode)

    def get_config(self) -> Dict[str, Any]:
        """Get current graph configuration."""
        return {
            "session_id": self._config.session_id,
            "thread_id": self._config.thread_id,
            "use_memory": self._config.use_memory,
        }

    def new_session(self) -> str:
        """Start a new session with fresh thread ID."""
        self._config.thread_id = str(uuid.uuid4())
        self._config.session_id = str(uuid.uuid4())
        return self._config.thread_id


# =============================================================================
# Module-level graph instance (backward compatibility)
# =============================================================================

_rag_graph: Optional[RAGGraph] = None


def get_rag_graph(config: Optional[RAGGraphConfig] = None) -> RAGGraph:
    """
    Get or create the RAG graph instance.

    Args:
        config: Optional configuration (uses defaults if not provided)

    Returns:
        RAGGraph instance
    """
    global _rag_graph

    if _rag_graph is None or config is not None:
        _rag_graph = RAGGraph(config=config)

    return _rag_graph


def create_rag_graph(
    llm: Optional[BaseChatModel] = None,
    tools: Optional[List] = None,
    config: Optional[RAGGraphConfig] = None,
) -> StateGraph:
    """
    Create a compiled RAG graph.

    This is the main entry point for creating the RAG workflow.

    Args:
        llm: Optional language model (lazy loaded if not provided)
        tools: Optional list of tools (lazy loaded if not provided)
        config: Optional graph configuration

    Returns:
        Compiled StateGraph

    Example:
        >>> graph = create_rag_graph()
        >>> result = graph.invoke({"messages": [HumanMessage(content="发动机振动异常如何排查?")]})
    """
    rag = RAGGraph(llm=llm, tools=tools, config=config)
    return rag.build()


# =============================================================================
# CLI and Interactive Session
# =============================================================================

def run_interactive_session(
    graph: Optional[StateGraph] = None,
    config: Optional[RAGGraphConfig] = None,
    print_callback: Optional[Callable] = None,
):
    """
    Run an interactive RAG session.

    Args:
        graph: Optional pre-built graph
        config: Optional configuration
        print_callback: Optional callback for printing events
    """
    from utils.print_utils import _print_event

    if graph is None:
        rag = get_rag_graph(config)
        graph = rag.graph

    config = config or RAGGraphConfig()
    thread_config = {
        "configurable": {
            "thread_id": config.thread_id,
        }
    }

    _printed = set()

    print("\n" + "=" * 60)
    print("RAG 智能问答系统")
    print("输入 'q', 'exit', 或 'quit' 退出")
    print("=" * 60 + "\n")

    while True:
        try:
            question = input("用户: ").strip()

            if not question:
                continue

            if question.lower() in ["q", "exit", "quit"]:
                log.info("对话结束，再见！")
                print("\n再见！\n")
                break

            inputs = {
                "messages": [HumanMessage(content=question)]
            }

            print()
            events = graph.stream(inputs, config=thread_config, stream_mode="values")

            for event in events:
                _print_event(event, _printed)

            print()

        except KeyboardInterrupt:
            print("\n\n对话被中断，再见！\n")
            break
        except Exception as e:
            log.error(f"Session error: {e}")
            print(f"\n发生错误: {e}\n")


# =============================================================================
# CLI Entry Point
# =============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="RAG Graph CLI")
    parser.add_argument(
        "--interactive", "-i",
        action="store_true",
        help="Run interactive session"
    )
    parser.add_argument(
        "--query", "-q",
        type=str,
        help="Single query to execute"
    )
    parser.add_argument(
        "--thread-id",
        type=str,
        default=None,
        help="Thread ID for session continuity"
    )

    args = parser.parse_args()

    graph_config = RAGGraphConfig(thread_id=args.thread_id)
    rag = get_rag_graph(graph_config)

    if args.query:
        # Single query mode
        print(f"\n查询: {args.query}\n")
        result = rag.invoke(args.query)
        messages = result.get("messages", [])
        if messages:
            last_message = messages[-1]
            print(f"回答: {last_message.content}\n")

    elif args.interactive:
        # Interactive mode
        run_interactive_session(rag.graph, graph_config)

    else:
        # Default: interactive mode
        run_interactive_session(rag.graph, graph_config)