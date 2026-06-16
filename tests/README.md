# 测试目录

## 目录结构

```
tests/
├── README.md              ← 你在这里
├── unit/                  # 单元测试（不需要后端运行）
│   ├── test_skills.py     # Skill 组件、AgentState、MCP Server
│   └── test_pdf_parser.py # PDF 文本层 / 表格 / OCR fallback
├── api/                   # API 接口测试（需要后端运行）
│   ├── test_health.py     # 健康检查 / 配置 / 监控
│   ├── test_chat.py       # 对话接口（非流式 + SSE 流式 + 快速模式）
│   ├── test_documents.py  # 文档上传 / 列表 / 删除
│   ├── test_sessions.py   # 会话创建 / 历史 / 删除
│   ├── test_retrieval.py  # 知识库检索（混合 / 纯向量 / BM25）
│   └── test_feedback.py   # 用户反馈 / 纠正 / 升级
└── integration/           # 全链路集成测试
    └── test_system.py     # 端到端全链路（上传→对话→检索→清理）
```

## 运行方式

### 1. 启动后端

```bash
python -m uvicorn api.main:app --host 0.0.0.0 --port 8000
```

### 2. 单元测试（不需要后端）

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
