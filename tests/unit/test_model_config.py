"""Model configuration tests."""

from __future__ import annotations

import os
import subprocess
import sys


def test_default_model_configuration():
    from documents.milvus_db import MilvusConfig
    from models.llm_models import LLMConfig
    from utils.env_utils import (
        EMBEDDING_DIMENSION,
        EMBEDDING_MODEL,
        LLM_MODEL,
        RERANKER_ENABLED,
    )

    assert LLMConfig().model_name == LLM_MODEL
    assert EMBEDDING_MODEL
    assert isinstance(RERANKER_ENABLED, bool)
    assert MilvusConfig().dense_dim == EMBEDDING_DIMENSION


def test_process_environment_overrides_dotenv():
    env = os.environ.copy()
    env.update(
        {
            "LLM_MODEL": "test-llm",
            "LLM_MAX_TOKENS": "123",
            "EMBEDDING_MODEL": "test/embedding",
            "EMBEDDING_MODEL_PATH": "",
            "EMBEDDING_DIMENSION": "768",
            "EMBEDDING_NORMALIZE": "false",
        }
    )
    code = """
from models.embedding_models import get_embedding_model_source
from models.llm_models import LLMConfig
from documents.milvus_db import MilvusConfig
from utils.env_utils import EMBEDDING_NORMALIZE
assert LLMConfig().model_name == "test-llm"
assert LLMConfig().max_tokens == 123
assert get_embedding_model_source() == "test/embedding"
assert MilvusConfig().dense_dim == 768
assert EMBEDDING_NORMALIZE is False
"""
    subprocess.run([sys.executable, "-c", code], check=True, env=env)
