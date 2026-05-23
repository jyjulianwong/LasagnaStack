from dataclasses import dataclass
from pathlib import Path

from lasagnastack.base import PipelineState
from lasagnastack.models.reel_pipeline.cut_list import CutList
from lasagnastack.models.reel_pipeline.enhance import ReelStyleSheet
from lasagnastack.models.reel_pipeline.inventory import ClipInventory, NormalisedClip
from lasagnastack.models.reel_pipeline.post_caption import PostCaption


@dataclass
class ReelPipelineState(PipelineState):
    """Concrete state for ``ReelPipeline``: raw clips → CapCut draft."""

    normalised_clips: list[NormalisedClip] | None = None
    inventories: list[ClipInventory] | None = None
    cut_list: CutList | None = None
    reel_style_sheet: ReelStyleSheet | None = None
    draft_path: Path | None = None
    post_caption: PostCaption | None = None
