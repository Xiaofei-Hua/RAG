"""Compatibility shim -- use agent.skills.agent.skill instead."""
from agent.skills.agent.skill import AgentSkill, AgentSkillConfig
__all__ = ["AgentSkill", "AgentSkillConfig"]
