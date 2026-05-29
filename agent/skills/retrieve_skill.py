"""Compatibility shim -- use agent.skills.retrieve.skill instead."""
from agent.skills.retrieve.skill import RetrieveSkill, RetrieveSkillConfig
__all__ = ["RetrieveSkill", "RetrieveSkillConfig"]
