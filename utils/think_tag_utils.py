"""Helpers for suppressing model reasoning from public answer text."""

from __future__ import annotations

NO_THINK_SUFFIX = " /no_think"

_OPEN = "<think"
_CLOSE = "</think"


def _suffix_prefix_length(value: str, *prefixes: str) -> int:
    """Return the longest suffix of ``value`` that starts one of ``prefixes``."""
    lowered = value.lower()
    longest = 0
    for prefix in prefixes:
        upper = min(len(lowered), len(prefix) - 1)
        for length in range(1, upper + 1):
            if lowered.endswith(prefix[:length]):
                longest = max(longest, length)
    return longest


class IncrementalThinkFilter:
    """Incrementally remove Qwen-style ``<think>`` sections.

    The parser is deliberately fail closed: once a valid opening prefix is
    observed, malformed or unfinished reasoning is never released. Only a
    small possible-tag suffix is retained between chunks.
    """

    def __init__(self, *, max_tag_chars: int = 256):
        if max_tag_chars < len(_CLOSE) + 1:
            raise ValueError("max_tag_chars is too small")
        self._max_tag_chars = max_tag_chars
        self._buffer = ""
        self._state = "public"
        self._depth = 0
        self._finished = False

    @property
    def buffered_chars(self) -> int:
        """Number of characters retained across chunk boundaries."""
        return len(self._buffer)

    def push(self, chunk: str) -> str:
        """Consume one model chunk and return only newly public text."""
        if self._finished:
            raise RuntimeError("cannot push after finish")
        if not chunk:
            return ""
        self._buffer += str(chunk)
        output: list[str] = []

        while self._buffer:
            if self._state == "discard":
                self._buffer = ""
                break
            if self._state == "public":
                if not self._process_public(output):
                    break
                continue
            if self._state == "opening":
                if not self._process_opening():
                    break
                continue
            if self._state == "closing":
                if not self._process_closing():
                    break
                continue
            if not self._process_hidden():
                break

        return "".join(output)

    def finish(self) -> str:
        """Finish once, releasing only an ordinary public tag-prefix suffix."""
        if self._finished:
            return ""
        self._finished = True
        if self._state == "public":
            trailing = self._buffer
            self._buffer = ""
            return trailing
        self._buffer = ""
        return ""

    def _process_public(self, output: list[str]) -> bool:
        lowered = self._buffer.lower()
        index = lowered.find(_OPEN)
        if index < 0:
            retained = _suffix_prefix_length(self._buffer, _OPEN)
            if retained:
                output.append(self._buffer[:-retained])
                self._buffer = self._buffer[-retained:]
                return False
            output.append(self._buffer)
            self._buffer = ""
            return False

        if index:
            output.append(self._buffer[:index])
            self._buffer = self._buffer[index:]

        if len(self._buffer) == len(_OPEN):
            return False
        delimiter = self._buffer[len(_OPEN)]
        if delimiter == ">":
            self._buffer = self._buffer[len(_OPEN) + 1 :]
            self._depth = 1
            self._state = "hidden"
            return True
        if delimiter.isspace():
            self._depth = 1
            self._state = "opening"
            return True

        # A near match such as <thinkology> is ordinary public text.
        output.append(self._buffer[0])
        self._buffer = self._buffer[1:]
        return True

    def _process_opening(self) -> bool:
        end = self._buffer.find(">", len(_OPEN) + 1)
        if end >= 0:
            self._buffer = self._buffer[end + 1 :]
            self._state = "hidden"
            return True
        if len(self._buffer) > self._max_tag_chars:
            self._buffer = ""
            self._state = "discard"
        return False

    def _process_hidden(self) -> bool:
        index = self._buffer.find("<")
        if index < 0:
            self._buffer = ""
            return False
        if index:
            self._buffer = self._buffer[index:]

        lowered = self._buffer.lower()
        if _OPEN.startswith(lowered) or _CLOSE.startswith(lowered):
            return False

        if lowered.startswith(_OPEN):
            if len(self._buffer) == len(_OPEN):
                return False
            delimiter = self._buffer[len(_OPEN)]
            if delimiter == ">":
                self._depth += 1
                self._buffer = self._buffer[len(_OPEN) + 1 :]
                return True
            if delimiter.isspace():
                self._depth += 1
                self._state = "opening"
                return True

        if lowered.startswith(_CLOSE):
            if len(self._buffer) == len(_CLOSE):
                return False
            delimiter = self._buffer[len(_CLOSE)]
            if delimiter == ">":
                self._complete_close(len(_CLOSE) + 1)
                return True
            if delimiter.isspace():
                self._state = "closing"
                return True

        self._buffer = self._buffer[1:]
        return True

    def _process_closing(self) -> bool:
        for index in range(len(_CLOSE), len(self._buffer)):
            char = self._buffer[index]
            if char == ">":
                self._complete_close(index + 1)
                return True
            if not char.isspace():
                self._buffer = self._buffer[1:]
                self._state = "hidden"
                return True
        if len(self._buffer) > self._max_tag_chars:
            self._buffer = ""
            self._state = "hidden"
        return False

    def _complete_close(self, consumed: int) -> None:
        self._buffer = self._buffer[consumed:]
        self._depth -= 1
        self._state = "public" if self._depth == 0 else "hidden"


def sanitize_model_text(text: str) -> str:
    """Apply the streaming-safe parser to a complete model response."""
    if not text:
        return text
    parser = IncrementalThinkFilter()
    return (parser.push(str(text)) + parser.finish()).strip()


def strip_think_tags(text: str) -> str:
    """Backward-compatible alias for the fail-closed sanitizer."""
    return sanitize_model_text(text)


def build_fast_mode_prompt(question: str) -> str:
    """Append /no_think to suppress Qwen3 reasoning in fast mode."""
    return question.rstrip() + NO_THINK_SUFFIX
