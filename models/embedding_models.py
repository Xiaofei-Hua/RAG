"""
Embedding Models - Lazy Initialization

All embedding models are loaded on first use, not at import time.
Primary model: local BGE-small-zh-v1.5 (no remote API dependency).
"""

import os
from typing import Optional

from langchain_huggingface import HuggingFaceEmbeddings

_local_model_path = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "local_models", "bge-small-zh-v1.5",
)

_instance: Optional[HuggingFaceEmbeddings] = None


def get_local_embeddings() -> HuggingFaceEmbeddings:
    """Get or create the local BGE embedding model (singleton)."""
    global _instance
    if _instance is None:
        _instance = HuggingFaceEmbeddings(
            model_name=_local_model_path,
            model_kwargs={"device": "cpu"},
            encode_kwargs={"normalize_embeddings": True, "batch_size": 8},
        )
    return _instance


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
    print(f"向量维度: {len(vector)}")
