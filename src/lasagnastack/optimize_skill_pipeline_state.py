from dataclasses import dataclass

from lasagnastack.base import PipelineState
from lasagnastack.models.reel_pipeline.cut_list import CutList
from lasagnastack.models.reel_pipeline.enhance import ReelStyleSheet


@dataclass
class OptimizeSkillPipelineState(PipelineState):
    """Concrete state for ``OptimizeSkillPipeline``: trainset drafts → improved skill file."""

    draft_cut_lists: list[CutList] | None = None
    draft_reel_style_sheets: list[ReelStyleSheet] | None = None
    optimized_skill_text: str | None = None
