# Validation

## Red / Green
- 修复前：新增单元23例失败（启用路径10例通过）；两例API均因关闭后仍取得judge而失败，见日志包red-unit.log与red-e2e.log。
- 初次定向绿：两工作树各62通过。
- 新API测试清理最初引用了旧main不存在的函数；只修改测试，关闭并清空已有采样器。缺少web/dist还暴露了既有首页文档契约问题；本地API测试启动复用已有dist，没有前端源代码修改或重新构建的声明。
- 最终发布矩阵：1182通过、6跳过、3个已有依赖警告，58.73秒。
- 当前集成矩阵：2768通过、6跳过、3个已有依赖警告，154.65秒。测试清理适配后，两例API再次通过。
- Ruff：修改的业务与测试文件通过。

## Commands and Scope
隔离Linux网络环境，移除代理，设置PYTHON_DOTENV_DISABLED=1、EMBEDDING_PROVIDER=api、MILVUS_SPARSE_INDEX=false：

```bash
uv run --frozen --no-sync python -m pytest tests/unit/ tests/e2e/ tests/perf/ -q
uv run --frozen --no-sync ruff check agent/guardrails/types.py agent/guardrails/grounding_guardrail.py tests/unit/test_grounding_switch.py tests/e2e/test_grounding_switch_api.py
```

新API测试经过真实router、GenerateSkill和输出检查，使用harness适配器和模型mock；不宣称旧main因此获得了新整图或检查后流式发布契约。未修改前端行为，无本次变更的Playwright适用项。

## GitHub Checks
PR #4发布检查：build-and-size-check与check通过。后端test在既有test_wsl_guide_http_table_exactly_matches_openapi失败：CI没有web/dist时多出GET /，与指南表不符；本地有dist的矩阵不能掩盖这个差异。e2e-ui在既有前端生产依赖npm audit失败（4 high、1 critical），尚未执行Playwright。对应api/main.py、部署契约测试、package-lock及UI workflow均未被本PR修改；没有关闭检查或放宽断言。原始失败日志摘要随日志包归档。不能宣称GitHub CI全绿。

## Real Model
真实多轮结果与停止原因见results.md。默认保持true；实际完成12次开发终态、1次部分尝试，留出未执行。开关bug修复可独立交付，默认关闭核验没有取得质量资格。
