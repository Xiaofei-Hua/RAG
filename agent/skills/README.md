# Skills

Each skill is a self-contained capability unit that implements `BaseSkill`.

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

## Pipeline Flow

```
AgentSkill -> RetrieveSkill -> GradeSkill -> GenerateSkill
                                         \-> RewriteSkill -> AgentSkill (loop)
```

## Adding a Skill

1. Create `my_skill.py` inheriting `BaseSkill`
2. Set `name` and `description` class attributes
3. Implement `execute()` and `aexecute()`
4. Register via `harness.register_skill(MySkill())`

## Current Skills

| Skill | File | Description |
|-------|------|-------------|
| agent | agent_skill.py | Tool-call decision node |
| retrieve | retrieve_skill.py | Hybrid retrieval (handled by ToolNode) |
| grade | grade_skill.py | Document relevance grading |
| rewrite | rewrite_skill.py | Query rewriting |
| generate | generate_skill.py | Final answer generation |
| intent | intent_skill.py | User intent classification |
