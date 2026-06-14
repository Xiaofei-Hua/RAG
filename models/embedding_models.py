"""Embedding model factory with environment-based configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from langchain_huggingface import HuggingFaceEmbeddings

from utils.env_utils import (
    EMBEDDING_BATCH_SIZE,
    EMBEDDING_DEVICE,
    EMBEDDING_MODEL,
    EMBEDDING_MODEL_PATH,
    EMBEDDING_NORMALIZE,
)
from utils.log_utils import log

_instance: Optional[HuggingFaceEmbeddings] = None


def is_embedding_model_cached() -> bool:
    """Return whether the configured local path contains a saved model."""
    if not EMBEDDING_MODEL_PATH:
        return False
    local_path = Path(EMBEDDING_MODEL_PATH)
    return local_path.is_dir() and any(
        (local_path / marker).is_file()
        for marker in ("modules.json", "config.json", "model.safetensors")
    )


def get_embedding_model_source() -> str:
    """Return the local model path when available, otherwise the model ID."""
    if is_embedding_model_cached():
        return EMBEDDING_MODEL_PATH
    return EMBEDDING_MODEL


def get_local_embeddings() -> HuggingFaceEmbeddings:
    """Get or create the configured embedding model singleton."""
    global _instance
    if _instance is None:
        model_source = get_embedding_model_source()
        log.info(
            f"Creating embedding model: source={model_source}, "
            f"device={EMBEDDING_DEVICE}"
        )
        _instance = HuggingFaceEmbeddings(
            model_name=model_source,
            model_kwargs={"device": EMBEDDING_DEVICE},
            encode_kwargs={
                "normalize_embeddings": EMBEDDING_NORMALIZE,
                "batch_size": EMBEDDING_BATCH_SIZE,
            },
        )
    return _instance


def reset_embeddings() -> None:
    """Reset the singleton so changed configuration can be applied in tests."""
    global _instance
    _instance = None


# Legacy aliases - lazy, only created when accessed
def __getattr__(name):
    if name == "bge_embedding":
        return get_local_embeddings()
    if name == "openai_embeddings":
        raise ImportError(
            "openai_embeddings removed: use get_local_embeddings() instead. "
            "Remote OpenAI embeddings are no longer supported for this project."
        )
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


if __name__ == "__main__":
    text = "这是一个本地部署的测试文本"
    vector = get_local_embeddings().embed_query(text)
    print(f"模型来源: {get_embedding_model_source()}")
    print(f"向量维度: {len(vector)}")
