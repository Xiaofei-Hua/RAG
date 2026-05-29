from __future__ import annotations

import re
import uuid
from typing import List

from agent.memory.types import MemoryEntry, MemoryType
from utils.log_utils import log


class MemoryExtractor:
    def extract_facts(self, question: str, answer: str) -> List[MemoryEntry]:
        entries = []

        if "诊断结论" in answer:
            content = self._extract_between_markers(answer, "诊断结论")
            if content:
                entries.append(
                    MemoryEntry(
                        id=str(uuid.uuid4()),
                        memory_type=MemoryType.FACT,
                        content=f"诊断结论: {content.strip()}",
                        metadata={"source_query": question},
                    )
                )

        if "可能原因" in answer:
            content = self._extract_between_markers(answer, "可能原因")
            if content:
                entries.append(
                    MemoryEntry(
                        id=str(uuid.uuid4()),
                        memory_type=MemoryType.FACT,
                        content=f"可能原因: {content.strip()}",
                        metadata={"source_query": question},
                    )
                )

        if entries:
            log.debug(f"MemoryExtractor: extracted {len(entries)} facts from answer")
        return entries

    def extract_correction(self, original: str, correction: str) -> MemoryEntry:
        return MemoryEntry(
            id=str(uuid.uuid4()),
            memory_type=MemoryType.CORRECTION,
            content=correction,
            metadata={"original_answer": original},
        )

    def _extract_between_markers(self, text: str, section: str) -> str:
        patterns = [
            rf"【{re.escape(section)}】(.*?)(?=【|$)",
            rf"{re.escape(section)}[：:](.*?)(?=【|$)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.DOTALL)
            if match:
                return match.group(1).strip()
        return ""
