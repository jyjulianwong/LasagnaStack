from pathlib import Path

import structlog

from lasagnastack.base import Pipeline, PipelineState, Stage
from lasagnastack.llm.base import LLMClient
from lasagnastack.stages.analyse import AnalyseStage
from lasagnastack.stages.critique import CritiqueStage
from lasagnastack.stages.direct import DirectStage
from lasagnastack.stages.ingest import IngestStage
from lasagnastack.stages.render import RenderStage

log = structlog.get_logger()


def _find_brief(input_dir: Path) -> Path:
    txts = list(input_dir.glob("*.txt"))
    if len(txts) != 1:
        raise ValueError(
            f"Expected exactly 1 .txt brief in {input_dir}, found {len(txts)}."
        )
    return txts[0]


class ReelPipeline(Pipeline):
    """The five-stage restaurant footage → CapCut draft pipeline."""

    def __init__(self, client: LLMClient | None = None) -> None:
        self._client = client

    @property
    def stages(self) -> list[Stage]:
        return [
            IngestStage(),
            AnalyseStage(self._client),
            DirectStage(self._client),
            CritiqueStage(self._client),
            RenderStage(),
        ]


def run_pipeline(
    input_dir: Path,
    output_dir: Path,
    auto_confirm: bool = False,
    max_critique_retries: int = 2,
) -> None:
    brief_path = _find_brief(input_dir)
    state = PipelineState(
        input_dir=input_dir,
        output_dir=output_dir,
        brief_path=brief_path,
        max_critique_retries=max_critique_retries,
    )
    state = ReelPipeline().run(state, auto_confirm=auto_confirm)
    log.info("pipeline_complete", draft=str(state.draft_path))
    print(f"\nDraft saved to: {state.draft_path}")
