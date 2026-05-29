"""Compatibility shim -- use agent.skills.rewrite.skill instead."""
from agent.skills.rewrite.skill import RewriteSkill, RewriteSkillConfig
__all__ = ["RewriteSkill", "RewriteSkillConfig"]
