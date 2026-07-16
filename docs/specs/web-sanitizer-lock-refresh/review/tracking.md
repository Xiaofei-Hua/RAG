# Tracking — Web Sanitizer Lock Refresh

## 追踪矩阵

| Finding | Severity | REQ | Defender | Design | Fix commit | Verification | Permanent regression | Status |
|---|---|---|---|---|---|---|---|---|
| F-01 | Critical | REQ-WSR-005 | accepted | v2 §3/§5 | pending | cold web-builder/full image; installed DOMPurify 3.4.12 | `tests/unit/test_web_sanitizer_lock_refresh.py::test_api_only_docker_consumes_root_workspace_lock` | open |
| F-02 | High | REQ-WSR-004 | accepted | v2.1 §5 | pending | Playwright normal/failure screenshots + DOM/execute assertions; 21 passed | `tests/e2e_ui/chat.spec.ts` sanitizer cases | open |
| F-03 | High | REQ-WSR-007 | accepted | v2 §6 | pending | lock contract rejects `<3.4.11`; rollback is forward-only | `tests/unit/test_web_sanitizer_lock_refresh.py::test_dompurify_lock_is_patched_and_has_trusted_provenance` | open |
| F-04 | High | REQ-WSR-006 | accepted | v2 §1/§4 | pending | official registry audit 0; HTTPS host + sha512 integrity | `tests/unit/test_web_sanitizer_lock_refresh.py::{test_dompurify_lock_is_patched_and_has_trusted_provenance,test_ui_workflow_uses_controlled_production_audit}` | open |
| F-05 | High | REQ-WSR-001..006 | accepted | v2.1 §5/tasks | pending | red `4 failed` + implementation red `3 failed`; green contracts 23 passed; browser 21 passed | lock/Docker/workflow unit + Playwright sanitizer cases | open |
| WSR-IMP-H-01 | High | REQ-WSR-004 | accepted | v2.1 §4/§5 | pending | forced sanitizer error: red dangerous img → green escaped fallback | `test_web_sanitizer_lock_refresh.py::test_chat_markdown_fallback_is_html_escaped` + Playwright fail-closed case | open |
| WSR-IMP-M-01 | Medium | REQ-WSR-005/006 | accepted | v2.1 §1/§3 | pending | hosted and Docker Node/npm pinned and asserted | `test_web_sanitizer_lock_refresh.py::{test_ui_workflow_uses_controlled_production_audit,test_lock_workflow_uses_the_same_frontend_toolchain}` | open |
| WSR-IMP-M-02 | Medium | REQ-WSR-002/005 | defended-with-alternative | v2.1 §2/§3 | pending | npm 10.8.2 metadata normalization documented; Debian/glibc builder verified | lock tuple audit + cold Docker builder | open |

## Local Evidence

- Node 20.20.2 / npm 10.8.2 lock refresh from `https://registry.npmjs.org/` with empty userconfig.
- Package tuple audit: only DOMPurify 3.4.7→3.4.12 and its direct trusted-types layout changed;
  unrelated version/resolved/integrity tuples stayed fixed. npm 10.8.2 additionally normalized the Rollup GNU
  entry by removing its redundant `libc` metadata; the production builder is pinned to Debian/glibc.
- `npm audit --omit=dev`: 0 production vulnerabilities.
- cold classic Docker: web-builder 29s; full build 106s; Python dependency sync 40s;
  image 478101058 bytes; no FlagEmbedding/torch/ST/transformers/langchain-huggingface; import and
  versioned domain-profile files verified.
- Playwright: 21 passed; reviewer inspected sanitizer-safe-output, sanitizer-failure-fallback,
  sources-panel and opened-session.

F-01..F-05 remain open until the implementation commit is recorded. Remote workflow evidence is tracked with
`ci-index-routing` because the same Docker/Playwright runs exercise both specs.
