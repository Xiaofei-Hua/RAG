# 测试目录

## 目录结构

```
tests/
├── README.md              ← 你在这里
├── conftest.py            # E2E 共享 fixture（fake LLM/retriever/harness/store）
├── unit/                  # 单元测试（纯逻辑，不需要后端/LLM/Milvus）
│   ├── test_skills.py        # Skill 组件、AgentState、MCP Server
│   ├── test_pdf_parser.py    # PDF 文本层 / 表格 / OCR fallback
│   ├── test_eval.py          # 评测：judge 解析 / scorer / runner / 回归
│   ├── test_eval_flywheel.py # 飞轮：inference store / sampler / candidates
│   ├── test_replay_eval.py   # 离线 replay 评测 + judge 降级
│   ├── test_grounding_guardrail.py # P0 在线幻觉检测 / 置信度 / 拒绝回答
│   ├── test_p1_retrieval.py  # P1 检索深度：token budget/MMR/过滤/HyDE/parent/index
│   └── ...
├── e2e/                   # 端到端测试（in-process，mock 单例，无需 Ollama/Milvus）
│   ├── test_e2e_chat.py        # chat 四分支 + 置信度/拒绝/SSE/历史
│   ├── test_e2e_flywheel.py    # 飞轮闭环：采样→inference→反馈→candidate→miss
│   ├── test_e2e_replay.py      # 离线 replay 评测驱动 + 历史/回归
│   └── test_e2e_admin_docs.py  # admin/feedback/documents/sessions/health
├── api/                   # 独立运行的 HTTP 脚本（需真实后端 + Ollama）
└── integration/           # 全链路 HTTP 脚本（需真实后端）
    └── test_system.py
```

## 运行方式

### 1. 单元 + 端到端测试（无需后端，CI 可跑）

```bash
# 全部（169 个测试）
python -m pytest tests/unit/ tests/e2e/ -q

# 仅单元测试（130 个）
python -m pytest tests/unit/ -q

# 仅端到端测试（39 个，in-process FastAPI + mocked 单例）
python -m pytest tests/e2e/ -q

# 单个文件
python -m pytest tests/e2e/test_e2e_flywheel.py -v
```

E2E 测试通过 `conftest.py` 用 TestClient 在进程内启动真实 FastAPI app，并用 fake LLM/retriever/harness/session 替换昂贵单例——**完全不依赖 Ollama 或 Milvus**，可在任何环境（含 CI）运行。

### 2. 真实后端测试（需要 Ollama + Milvus）

```bash
python -m uvicorn api.main:app --host 0.0.0.0 --port 8000
```

### 3. 单元测试（不需要后端）

```bash
python tests/unit/test_skills.py           # 运行全部
python tests/unit/test_skills.py agent     # 运行单个测试
python tests/unit/test_skills.py --full    # 包含 LLM 调用测试
```

### 3. API 接口测试（需要后端运行）

每个测试文件独立运行，互不依赖：

```bash
python tests/api/test_health.py            # 健康检查
python tests/api/test_chat.py              # 对话接口
python tests/api/test_documents.py         # 文档管理
python tests/api/test_sessions.py          # 会话管理
python tests/api/test_retrieval.py         # 知识库检索
python tests/api/test_feedback.py          # 用户反馈
```

### 4. 全链路集成测试

```bash
python tests/integration/test_system.py    # 完整流程
```

## 注意事项

- API 测试使用 Python 标准库（`urllib` / `http.client`），无需额外依赖
- `test_retrieval.py` 会自动上传测试文档（如知识库为空）
- `test_documents.py` 会在测试结束时清理上传的文档
- 所有测试脚本均可独立运行，无交叉依赖
- OCR 功能测试需要 `paddlepaddle` 和 `paddleocr`；首次运行会下载模型到
  `~/.paddlex/official_models/`
