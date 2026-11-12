"""Compose complete procedural answers from selected evidence wording."""

import re
from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, Field

from core.retrieval.evidence import render_untrusted_evidence

_PROCEDURE = re.compile(
    r"步骤|流程|操作顺序|逐步|"
    r"\b(?:how to|steps?|procedures?|workflows?|walkthroughs?|sequence)\b",
    re.IGNORECASE,
)
_REFERENCE = re.compile(r"\b(?:that|this|these|those|it|its)\b|该|此|其|上述|本次", re.IGNORECASE)


_CONSTRAINT = re.compile(
    r"必须|须|不得|不能|禁止|仅|只有|才能|完成才|方可|不允许|"
    r"\b(?:must|shall|only|before|until|unless|required|requires|allowed|permitted|"
    r"prohibited|cannot)\b|\b(?:may|can|do)\s+not\b",
    re.IGNORECASE,
)
ClauseRole = Literal["main_rule", "scope", "step", "record", "limit", "omit"]


class ProcedureAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    clauses: dict[str, ClauseRole] = Field(min_length=1)


def _clause_key(unit):
    return f"{unit['id']}:{unit['text']}"


def procedure_schema(procedure):
    keys = [_clause_key(unit) for unit in procedure["units"]]
    return {
        "type": "object",
        "properties": {
            "clauses": {
                "type": "object",
                "properties": {
                    key: {"type": "string", "enum": list(get_args(ClauseRole))} for key in keys
                },
                "required": keys,
                "additionalProperties": False,
            }
        },
        "required": ["clauses"],
        "additionalProperties": False,
    }


def procedural_question(question):
    return bool(_PROCEDURE.search(question))


def _language(text):
    chinese = re.search(r"[\u4e00-\u9fff]", text)
    if any(c.isalpha() and not c.isascii() and not "\u4e00" <= c <= "\u9fff" for c in text):
        return None
    if chinese:
        # 混合正文不直接拼装；英文型号/缩写之外的连续英文短语保守回退。
        if re.search(r"\b[A-Za-z]{2,}(?:[ -]+[A-Za-z]{2,})+\b", text):
            return None
        return "zh"
    words = set(re.findall(r"[a-z]+", text.lower()))
    markers = {
        "the",
        "this",
        "these",
        "those",
        "is",
        "are",
        "must",
        "shall",
        "before",
        "after",
        "only",
        "when",
        "if",
        "with",
        "and",
        "not",
        "how",
        "to",
    }
    return "en" if len(words & markers) >= 2 else None


def _eligible_evidence(evidence, question):
    language = _language(question)
    if re.search(r"(?:用|使用|in)\s*(?:英语|英文|English)", question, re.I):
        language = "en"
    if re.search(r"(?:用|使用|in)\s*(?:中文|汉语|Chinese)", question, re.I):
        language = "zh"
    if not evidence or language != "zh":
        return None
    from core.retrieval.scoring import probability

    def measured_probability(item):
        metadata = item.get("metadata") or {}
        if (
            metadata.get("rerank_applied") is True
            and metadata.get("rerank_output_space") == "probability"
        ):
            return probability(metadata.get("rerank_score"))
        return None

    languages = [_language(item["content"]) for item in evidence]
    scores = [measured_probability(item) for item in evidence]
    strong = any(
        lang == language and score is not None and score >= 0.9
        for lang, score in zip(languages, scores)
    )
    if any(
        lang != language and (not strong or score is None or score > 0.01)
        for lang, score in zip(languages, scores)
    ):
        return None
    return [item for item, lang in zip(evidence, languages) if lang == language]


def select_procedure_evidence(evidence, question):
    from core.prompts.domain_profile import get_active_profile

    if not get_active_profile().prompts.get("procedure_generate_system"):
        return evidence
    return _eligible_evidence(evidence, question) or evidence


def prepare_procedure(inputs):
    from core.prompts.domain_profile import get_active_profile

    original_evidence = inputs.get("evidence") or []
    evidence = _eligible_evidence(original_evidence, inputs["question"])
    if not evidence or not get_active_profile().prompts.get("procedure_generate_system"):
        return None
    original = render_untrusted_evidence(original_evidence)
    if original not in inputs["context"]:
        return None
    units, annotated = [], []
    for item in evidence:
        if not item["source"] or item["source"] not in inputs["sources"]:
            return None
        source_id = inputs["sources"].index(item["source"]) + 1
        sentences = re.split(r"(?<=[。！？])|(?<=[.!?])\s+(?=[A-Z])|\n+", item["content"])
        grouped = []
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            # 指代句连同同一来源中的前句保留，不把触发条件切掉。
            if grouped and _REFERENCE.match(sentence):
                grouped[-1] += " " + sentence
            else:
                grouped.append(sentence)
        lines = []
        for sentence in grouped:
            uid = len(units) + 1
            units.append({"id": uid, "source_id": source_id, "text": sentence})
            lines.append(f"[条款{uid}] {sentence}")
        annotated.append({**item, "content": "\n".join(lines)})
    if not units:
        return None
    return {
        "units": units,
        "language": _language(evidence[0]["content"]),
        "context": inputs["context"].replace(original, render_untrusted_evidence(annotated), 1),
    }


def render_procedure(message, sources, procedure):
    from core.local_rag_generation import CitedParagraph, complete_content, render_paragraph

    if (getattr(message, "response_metadata", {}) or {}).get("finish_reason") != "stop":
        raise ValueError("incomplete_procedure")
    answer = ProcedureAnswer.model_validate_json(complete_content(message))
    units = procedure["units"]
    roles = {
        key: "lead" if role in {"main_rule", "scope"} else role
        for key, role in answer.clauses.items()
    }
    if set(roles) != {_clause_key(unit) for unit in units}:
        raise ValueError("invalid_procedure_clauses")
    for unit in units:
        key = _clause_key(unit)
        # 只调整已选操作约束的位置，不恢复无关条款或改写许可条件。
        if roles[key] == "step" and _CONSTRAINT.search(unit["text"]):
            roles[key] = "lead"
    if "lead" not in roles.values():
        raise ValueError("missing_procedure_lead")
    titles = (
        ["规则与适用范围", "操作步骤", "记录与用途", "条件与边界"]
        if procedure["language"] == "zh"
        else ["Rules and scope", "Procedure", "Records and purposes", "Conditions and boundaries"]
    )
    paragraphs = []
    for role, title in zip(["lead", "step", "record", "limit"], titles):
        selected = [unit for unit in units if roles[_clause_key(unit)] == role]
        if not selected:
            continue
        cited = CitedParagraph(
            text="**" + title + "**\n\n" + " ".join(unit["text"] for unit in selected),
            source_ids=list(dict.fromkeys(unit["source_id"] for unit in selected)),
        )
        paragraphs.append(render_paragraph(cited, sources))
    return "\n\n".join(paragraphs)
