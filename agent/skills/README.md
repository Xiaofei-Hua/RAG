# Skills

Each skill is a self-contained capability unit that implements `BaseSkill`. The
source of truth is the **directory** form: `agent/skills/<name>/skill.py`.

## Interface

```python
class BaseSkill(ABC):
    name: str
    description: str

    @abstractmethod
    def execute(self, context: SkillContext) -> SkillResult: ...

    @abstractmethod
    async def aexecute(self, context: SkillContext) -> SkillResult: ...
```

Each skill directory may also carry `prompts.py` (re-exporting from
`core/prompts/profile_prompts.py`), `config.yaml`, and a `README.md`.

## Pipeline Flow

```
AgentSkill -> RetrieveSkill -> GradeSkill -> GenerateSkill
                                         \-> RewriteSkill -> AgentSkill (loop)
```

## Adding a Skill

1. Create `agent/skills/<name>/skill.py` inheriting `BaseSkill`.
2. Set `name` and `description` class attributes.
3. Implement `execute()` and `aexecute()`.
4. Register in `agent/harness/orchestrator.py` `register_defaults()` (or wire
   into `build_graph()`).

## Current Skills

| Skill | File | Description |
|-------|------|-------------|
| agent | agent/skills/agent/skill.py | Tool-call decision node |
| retrieve | agent/skills/retrieve/skill.py | Hybrid retrieval (Dense + BM25 + RRF) |
| grade | agent/skills/grade/skill.py | Document relevance grading |
| rewrite | agent/skills/rewrite/skill.py | Query rewriting |
| generate | agent/skills/generate/skill.py | Final answer generation (Qwen3 reasoning capture + grounding + confidence) |

> Note: `IntentSkill` has been removed — intent classification lives in the chat
> router (`api/routers/chat.py` via `core/intent/classifier.py`), not in the graph.
> Legacy flat shim files (`agent/skills/*_skill.py`) have also been removed — they
> only re-exported the directory skills. Always use the directory form above.
