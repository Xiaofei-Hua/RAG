"""
Message Utilities for RAG Pipeline

Provides helper functions for message extraction and manipulation.
Optimized for robustness and error handling.
"""

from __future__ import annotations

from typing import List, Optional, Type, TypeVar

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage

from utils.log_utils import log

__all__ = [
    "get_last_human_message",
    "get_last_ai_message",
    "get_messages_by_type",
    "get_message_content",
    "MessageExtractor",
]

# Type variable for message types
T = TypeVar("T", bound=BaseMessage)


class MessageNotFoundError(Exception):
    """Raised when a message of the expected type is not found."""
    pass


def get_last_human_message(messages: List[BaseMessage]) -> HumanMessage:
    """
    Get the last HumanMessage from a list of messages.

    Args:
        messages: List of messages to search

    Returns:
        The last HumanMessage found

    Raises:
        MessageNotFoundError: If no HumanMessage is found

    Example:
        >>> messages = [HumanMessage(content="Hello"), AIMessage(content="Hi")]
        >>> get_last_human_message(messages)
        HumanMessage(content="Hello")
    """
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            return message

    raise MessageNotFoundError(
        "No HumanMessage found in the messages list. "
        "Ensure the conversation starts with a user message."
    )


def get_last_ai_message(messages: List[BaseMessage]) -> Optional[AIMessage]:
    """
    Get the last AIMessage from a list of messages.

    Args:
        messages: List of messages to search

    Returns:
        The last AIMessage found, or None if not found
    """
    for message in reversed(messages):
        if isinstance(message, AIMessage):
            return message
    return None


def get_messages_by_type(
    messages: List[BaseMessage],
    message_type: Type[T],
) -> List[T]:
    """
    Filter messages by type.

    Args:
        messages: List of messages to filter
        message_type: The type of messages to return

    Returns:
        List of messages matching the specified type
    """
    return [msg for msg in messages if isinstance(msg, message_type)]


def get_message_content(message: BaseMessage, max_length: Optional[int] = None) -> str:
    """
    Extract content from a message with optional truncation.

    Args:
        message: The message to extract content from
        max_length: Maximum length of content (None for no limit)

    Returns:
        The message content, potentially truncated
    """
    content = message.content

    if max_length is not None and len(content) > max_length:
        return content[:max_length] + "..."

    return content


class MessageExtractor:
    """
    Utility class for extracting information from message lists.

    Provides methods for common message extraction patterns
    with proper error handling and logging.
    """

    def __init__(self, messages: List[BaseMessage]):
        self.messages = messages

    def get_last_human_message(self) -> HumanMessage:
        """Get the last HumanMessage with error handling."""
        try:
            return get_last_human_message(self.messages)
        except MessageNotFoundError as e:
            log.error(f"Failed to get human message: {e}")
            raise

    def get_last_ai_message(self) -> Optional[AIMessage]:
        """Get the last AIMessage."""
        return get_last_ai_message(self.messages)

    def get_last_human_content(self, max_length: Optional[int] = None) -> str:
        """
        Get the content of the last human message.

        Args:
            max_length: Optional maximum length for content

        Returns:
            The content string
        """
        message = self.get_last_human_message()
        return get_message_content(message, max_length)

    def get_message_count(self) -> int:
        """Get total message count."""
        return len(self.messages)

    def get_human_message_count(self) -> int:
        """Get count of human messages."""
        return len(get_messages_by_type(self.messages, HumanMessage))

    def get_ai_message_count(self) -> int:
        """Get count of AI messages."""
        return len(get_messages_by_type(self.messages, AIMessage))

    def get_conversation_summary(self) -> dict:
        """
        Get a summary of the conversation.

        Returns:
            Dictionary with conversation statistics
        """
        return {
            "total_messages": self.get_message_count(),
            "human_messages": self.get_human_message_count(),
            "ai_messages": self.get_ai_message_count(),
            "last_human_message_length": len(self.get_last_human_message().content)
            if self.get_human_message_count() > 0 else 0,
        }


# =============================================================================
# Backward compatibility - module-level function
# =============================================================================

# Keep the original function name for backward compatibility
def get_last_human_message(messages: List[BaseMessage]) -> HumanMessage:
    """Get the last HumanMessage from a list of messages."""
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            return message
    raise MessageNotFoundError("No HumanMessage found in the messages list")