"""
Agent Skills Package (Skills Store)

Each skill lives in its own directory with:
  skill.py     -- BaseSkill implementation
  config.yaml  -- optional configuration overrides
  prompts.py   -- optional prompt templates
  README.md    -- self-documentation

Base classes:
    BaseSkill, SkillContext, SkillResult, SkillStatus
    SkillRegistry

Skills:
    AgentSkill, RetrieveSkill, GradeSkill, RewriteSkill,
    GenerateSkill, IntentSkill
"""

from agent.skills.agent.skill import AgentSkill
from agent.skills.base import BaseSkill, SkillContext, SkillResult, SkillStatus
from agent.skills.generate.skill import GenerateSkill
from agent.skills.grade.skill import GradeSkill
from agent.skills.intent.skill import IntentSkill
from agent.skills.registry import SkillRegistry
from agent.skills.retrieve.skill import RetrieveSkill
from agent.skills.rewrite.skill import RewriteSkill

__all__ = [
    # Base
    "BaseSkill",
    "SkillContext",
    "SkillResult",
    "SkillStatus",
    "SkillRegistry",
    # Skills
    "AgentSkill",
    "RetrieveSkill",
    "GradeSkill",
    "RewriteSkill",
    "GenerateSkill",
    "IntentSkill",
]
