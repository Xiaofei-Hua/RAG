"""Compatibility shim -- use agent.skills.generate.skill instead."""
from agent.skills.generate.skill import GenerateSkill, GenerateSkillConfig
__all__ = ["GenerateSkill", "GenerateSkillConfig"]
