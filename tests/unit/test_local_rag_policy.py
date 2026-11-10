import os
import subprocess
import sys
from types import SimpleNamespace

import httpx
import pytest


def test_default_model_is_qwen35():
    environment = dict(os.environ, PYTHON_DOTENV_DISABLED="1")
    environment.pop("LLM_MODEL", None)
    result = subprocess.check_output(
        [sys.executable, "-c", "from utils.env_utils import LLM_MODEL; print(LLM_MODEL)"],
        env=environment,
        text=True,
    )
    assert result.strip() == "qwen3.5:9b"


@pytest.mark.parametrize(
    "version,expected",
    [
        ("0.24.0-format-backport", True),
        ("0.24.0", False),
        ("0.31.2", False),
        (None, False),
    ],
)
def test_auto_requires_the_qualified_server_and_caches_it(monkeypatch, version, expected):
    import models.local_rag_policy as policy

    monkeypatch.delenv("LOCAL_RAG_POLICY", raising=False)
    monkeypatch.setenv("DOMAIN_PROFILE", "general")
    source = SimpleNamespace(model_name="qwen3.5:9b", base_url="http://127.0.0.1:11434/v1")
    calls = []

    def respond(request):
        calls.append(request)
        assert request.url.path == "/api/version"
        if version is None:
            raise httpx.ConnectError("unavailable", request=request)
        return httpx.Response(200, json={"version": version})

    original = httpx.Client

    def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["timeout"] == 1.0
        return original(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(httpx, "Client", client)
    policy._qualified_runtime.cache_clear()
    try:
        assert policy.bounded_local_rag(source) is expected
        assert policy.bounded_local_rag(source) is expected
        assert len(calls) == 1
        monkeypatch.setenv("LOCAL_RAG_POLICY", "legacy")
        assert not policy.bounded_local_rag(source)
        assert len(calls) == 1
    finally:
        policy._qualified_runtime.cache_clear()
