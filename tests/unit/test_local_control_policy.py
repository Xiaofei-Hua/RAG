def test_control_budget_preserves_tools_and_structured_output(bounded_local_model):
    from core.intent.classifier import IntentResult
    from models.local_rag_policy import control_kwargs

    model, calls, output = bounded_local_model
    output["text"] = '{"intent":"rag_query","confidence":0.9}'
    model.with_structured_output(IntentResult, method="json_mode", **control_kwargs(model)).invoke(
        "分类"
    )
    tool = {
        "type": "function",
        "function": {
            "name": "rag_retriever",
            "description": "检索",
            "parameters": {"type": "object", "properties": {"query": {"type": "string"}}},
        },
    }
    model.bind_tools([tool], **control_kwargs(model)).invoke("检索")
    assert calls[0]["response_format"] == {"type": "json_object"}
    assert calls[1]["tools"][0]["function"]["name"] == "rag_retriever"
    assert all(
        c["max_tokens"] == c["max_completion_tokens"] == 256 and c["reasoning_effort"] == "none"
        for c in calls
    )


def test_factory_keeps_general_chat_budget(bounded_local_model, monkeypatch):
    from models import llm_models

    model, _, _ = bounded_local_model
    seen = {}

    def create(**kwargs):
        seen.update(kwargs)
        return model

    monkeypatch.setattr(llm_models, "_llm_instance", None)
    monkeypatch.setattr(llm_models, "ChatOpenAI", create)
    monkeypatch.setattr(llm_models, "LLM_MODEL", "qwen3.5:9b")
    llm_models.get_llm(llm_models.LLMConfig(base_url="http://127.0.0.1:11434/v1"))
    assert seen["max_tokens"] == llm_models.LLM_MAX_TOKENS
    assert not seen.get("extra_body")
    assert "reasoning_effort" not in seen
    assert seen["max_retries"] == 0
