"""Compatibility shim -- use agent.skills.grade.skill instead."""
from agent.skills.grade.skill import GradeSkill, GradeSkillConfig
__all__ = ["GradeSkill", "GradeSkillConfig"]
