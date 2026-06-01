# CLAUDE.md

## Project

企业级 RAG 智能平台（PHM 航空故障诊断），基于 FastAPI + LangGraph + Qwen3:14b。

## Commands

```bash
# Start backend
python -m uvicorn api.main:app --host 0.0.0.0 --port 8000

# Unit tests (no backend needed)
python tests/unit/test_skills.py
python tests/unit/test_skills.py --full    # includes LLM calls

# API tests (need backend running)
python tests/api/test_health.py
python tests/api/test_chat.py
python tests/api/test_documents.py
python tests/api/test_sessions.py
python tests/api/test_retrieval.py
python tests/api/test_feedback.py

# Integration test (need backend running)
python tests/integration/test_system.py

# Quick import check
python -c "import api.main; print('OK')"
python -c "from agent.harness import get_agent_harness; h=get_agent_harness(); print(list(h.graph.nodes.keys())); h.close()"
```

## Architecture

```
agent/          # Harness + Skills Store + MCP
├── harness/    # Orchestrator, Planner, Lifecycle, Observability
├── skills/     # Skills Store: each skill is a directory
│   ├── agent/      skill.py, prompts.py, config.yaml, README.md
│   ├── retrieve/   skill.py, config.yaml, README.md
│   ├── grade/      skill.py, prompts.py, config.yaml, README.md
│   ├── rewrite/    skill.py, prompts.py, config.yaml, README.md
│   ├── generate/   skill.py, prompts.py, config.yaml, README.md
│   └── intent/     skill.py, config.yaml, README.md
├── context/    # AgentState, Grade, message utilities
└── mcp/        # MCPServer, retrieval_server, retriever_tools
api/            # FastAPI routers (chat, documents, sessions, admin)
core/           # Infrastructure (retrieval, fallback, memory, prompts, intent)
documents/      # Milvus document management
models/         # LLM (Qwen3:14b via Ollama) and Embedding (BGE-small-zh-v1.5)
utils/          # Logging, env, think_tag utilities
```

## Conventions

- **Language**: Code comments and prompts in Chinese (PHM domain); variable names and docstrings in English
- **No unnecessary comments**: Don't add comments unless the WHY is non-obvious
- **No emojis in code**
- **Prompts**: Single source of truth in `core/prompts/aircraft_prompts.py`; skill-level `prompts.py` re-exports from there
- **Skills Store pattern**: Each skill lives in `agent/skills/<name>/` with `skill.py`, optional `prompts.py`/`config.yaml`, and `README.md`
- **Adding a skill**: Create directory under `agent/skills/<name>/`, implement `BaseSkill`, register in orchestrator or use `registry.auto_discover()`

## Key Patterns

- **Graph topology (thinking mode)**: START → agent → retrieve → grade → [generate | rewrite → agent]
- **Fast mode**: retrieve → generate (/no_think)
- **Entry point**: `agent.harness.get_agent_harness()` — singleton with `register_defaults()` + `build_graph()`
- **LLM**: Qwen3:14b via Ollama (Q4_K_M), reasoning captured via OpenAI SDK `reasoning` field
- **Retrieval**: Hybrid (BGE dense + BM25 sparse + RRF fusion)

## Testing

Always verify after changes:
1. `python -c "import api.main"` — no circular imports
2. `python tests/unit/test_skills.py` — all pass
3. Start backend, test `/health` and chat endpoint
