"""Compatibility shim -- use agent.skills.intent.skill instead."""
from agent.skills.intent.skill import IntentSkill, IntentSkillConfig
__all__ = ["IntentSkill", "IntentSkillConfig"]
