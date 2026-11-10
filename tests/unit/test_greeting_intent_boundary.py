from unittest.mock import Mock

import pytest

from core.intent.classifier import IntentClassifier, IntentType


@pytest.mark.parametrize(
    "query",
    [
        "Which replacement limit applies now?",
        "Does this model support export?",
        "Must it be replaced within 20 days?",
    ],
)
def test_embedded_greeting_is_not_a_chat_shortcut(query):
    assert IntentClassifier(llm=Mock())._keyword_classify(query) is None


@pytest.mark.parametrize("query", ["Hi!", "Hello there", "你好", "谢谢"])
def test_standalone_greetings_keep_the_shortcut(query):
    result = IntentClassifier(llm=Mock())._keyword_classify(query)
    assert result.intent == IntentType.GENERAL_CHAT
