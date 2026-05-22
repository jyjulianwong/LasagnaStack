from typing import Literal

from pydantic import BaseModel


class OptimizedSkill(BaseModel):
    """LLM output for Stage 2 of the optimize-skill pipeline."""

    skill_text: str
    """Full content of the improved skill Markdown file."""


class CritiqueSkillResult(BaseModel):
    """LLM output for Stage 3 of the optimize-skill pipeline."""

    verdict: Literal["approved", "revise"]
    """``approved`` if the skill accurately reflects the training examples; ``revise`` otherwise."""
    issues: list[str]
    """Specific problems found. Empty when verdict is ``approved``."""
    skill_v2: str | None = None
    """Corrected skill text. Required when verdict is ``revise``; null when approved."""
