# AGENTS.md

## Architecture

This project uses a **Harness + Skills + MCP** agent architecture powered by LangGraph.

```
agent/
├── harness/                # Orchestration layer
│   ├── orchestrator.py     # AgentHarness: builds & runs the LangGraph pipeline
│   ├── planner.py          # Execution plan (thinking vs fast mode)
│   ├── lifecycle.py        # Before/after/error lifecycle hooks
│   └── observability.py    # Per-skill tracing & timing
├── skills/                 # Modular capabilities
│   ├── base.py             # BaseSkill, SkillContext, SkillResult, SkillStatus
│   ├── registry.py         # SkillRegistry
│   ├── agent_skill.py      # Tool-call decision (bind tools, route to retrieve)
│   ├── retrieve_skill.py   # Hybrid retrieval (dense + BM25 + RRF)
│   ├── grade_skill.py      # Document relevance grading
│   ├── rewrite_skill.py    # Query rewriting for better retrieval
│   ├── generate_skill.py   # Final answer generation (Qwen3 reasoning capture)
│   └── intent_skill.py     # User intent classification
├── context/                # Shared state
│   ├── state.py            # AgentState, Grade, get_last_human_message
│   ├── context_manager.py  # Shared state across skills
│   └── session.py          # Session context
└── mcp/                    # Model Context Protocol
    ├── server.py           # MCPServer + InProcessMCPServer + LangChain conversion
    ├── client.py           # MCPClient for aggregating tools from servers
    ├── retrieval_server.py # RAG retrieval MCP server
    └── retriever_tools.py  # RetrieverManager, MilvusRetriever, get_retriever_tool
```

## Graph Topology

### Thinking Mode (full pipeline)

```
START -> agent -> [tools_condition]
                      |
                   retrieve -> grade -> [generate | rewrite]
                      |                       |
                   END                    agent (loop)
```

### Fast Mode (direct)

```
retrieve -> generate (/no_think)
```

## Entry Points

- **API**: `api/routers/chat.py` -> `agent.harness.get_agent_harness()`
- **CLI**: `agent/harness/orchestrator.py` -> `AgentHarness.invoke()`
- **Shutdown**: `api/main.py` -> `get_agent_harness().close()`

## Skills

Each skill implements `BaseSkill` with `execute(ctx) -> SkillResult` and optional `aexecute()`.

| Skill | Role | Produces |
|-------|------|----------|
| AgentSkill | Decide tool usage vs direct response | AIMessage (tool_calls or content) |
| RetrieveSkill | Hybrid retrieval via ToolNode | ToolMessage with documents |
| GradeSkill | Grade document relevance | next_action: "generate" or "rewrite" |
| RewriteSkill | Rewrite query for better retrieval | HumanMessage (rewritten query) |
| GenerateSkill | Final answer with reasoning | AIMessage (answer + reasoning) |
| IntentSkill | Classify user intent | next_action: routing decision |

## Adding a New Skill

1. Create `agent/skills/my_skill.py` inheriting `BaseSkill`
2. Implement `execute(context: SkillContext) -> SkillResult`
3. Register: `harness.register_skill(MySkill())`
4. Wire into graph in `orchestrator.build_graph()`

## Model

- **LLM**: Qwen3:14b (Ollama, Q4_K_M, ~9.3GB VRAM)
- **Embedding**: BGE-small-zh-v1.5 (local)
- **Reasoning**: Captured via OpenAI SDK `reasoning` field (LangChain discards it)

## Key Dependencies

- LangGraph (StateGraph, ToolNode, checkpointing)
- LangChain (messages, tools, output parsers)
- Milvus Lite (vector storage)
- Redis / SQLite (session memory)
