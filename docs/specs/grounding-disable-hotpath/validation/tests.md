# Validation

## Red / Green
- Before: 23 new unit cases failed (10 enabled-path cases passed); 2 API cases failed because the disabled setting still acquired the judge. Captured in red-unit.log and red-e2e.log.
- Initial targeted green: 62 passed in each tree.
- New API test cleanup originally used a helper absent in published main; fixed only the test to close/clear the existing sampler. Missing web/dist also exposed the existing deployment-table precondition; reused an existing built dist for API test startup, with no frontend source change.
- Final release matrix: 1182 passed, 6 skipped, 3 existing dependency warnings, 58.73 s.
- Integration matrix: 2768 passed, 6 skipped, 3 existing dependency warnings, 154.65 s. After the test cleanup adaptation, its two API cases passed again.
- Ruff: changed production and test files passed.

## Commands and Scope

Run in an isolated Linux network namespace with proxies removed, PYTHON_DOTENV_DISABLED=1, EMBEDDING_PROVIDER=api and MILVUS_SPARSE_INDEX=false:

```bash
uv run --frozen --no-sync python -m pytest tests/unit/ tests/e2e/ tests/perf/ -q
uv run --frozen --no-sync ruff check agent/guardrails/types.py agent/guardrails/grounding_guardrail.py tests/unit/test_grounding_switch.py tests/e2e/test_grounding_switch_api.py
```

The new API tests use the actual router, GenerateSkill and output checks with a harness adapter and mocked models. They do not establish a new full-graph or pre-publication streaming guarantee on the older remote main. No UI behavior changed; Playwright is not applicable.

## Real Model
The fixed 16-development / 8-held-out QA experiment is running on the current integration stack. Published main retains its existing default true. No semantic-quality qualification or production-default change is claimed before that experiment finishes.
