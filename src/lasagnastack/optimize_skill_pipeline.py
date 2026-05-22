"""Three-stage pipeline that analyses human-edited CapCut drafts and produces an improved skill file."""

import uuid
from pathlib import Path

import structlog

from lasagnastack.base import Pipeline, Stage
from lasagnastack.llm.base import LLMClient
from lasagnastack.optimize_skill_pipeline_state import OptimizeSkillPipelineState
from lasagnastack.stages.optimize_skill_pipeline.critique_skill import (
    CritiqueSkillStage,
)
from lasagnastack.stages.optimize_skill_pipeline.ingest_drafts import IngestDraftsStage
from lasagnastack.stages.optimize_skill_pipeline.optimize_skill import (
    OptimizeSkillStage,
)

log = structlog.get_logger()

_OUTPUT_FILENAME = "optimized_skill.md"


class OptimizeSkillPipeline(Pipeline):
    """Trainset → improved skill file pipeline.

    Stage 1 (IngestDraftsStage): parse every CapCut draft in the trainset folder
        into (CutList, ReelStyleSheet) pairs.
    Stage 2 (OptimizeSkillStage): call the LLM with the existing skill + examples
        to generate a draft improved skill file.
    Stage 3 (CritiqueSkillStage): iteratively critique and revise the draft skill
        until approved or the retry cap is reached.
    """

    def __init__(
        self,
        optimize_client: LLMClient | None = None,
        critique_client: LLMClient | None = None,
    ) -> None:
        """Initialise the pipeline with optional per-stage LLM clients.

        Args:
            optimize_client: LLM client for Stage 2 (optimize).
            critique_client: LLM client for Stage 3 (critique).
        """
        self._optimize_client = optimize_client
        self._critique_client = critique_client

    @property
    def stages(self) -> list[Stage]:
        """Return the three pipeline stages in execution order."""
        return [
            IngestDraftsStage(),
            OptimizeSkillStage(client=self._optimize_client),
            CritiqueSkillStage(client=self._critique_client),
        ]

    def run(  # type: ignore[override]
        self,
        state: OptimizeSkillPipelineState,
        auto_confirm: bool = False,
    ) -> OptimizeSkillPipelineState:
        """Run all three stages, then write the approved skill file to disk.

        Args:
            state: Initial pipeline state. ``input_dir`` must point at the
                trainset folder; ``skill_path`` (optional) points at the
                existing skill file to improve.
            auto_confirm: When ``True``, skip the interactive prompts between stages.

        Returns:
            Final pipeline state with ``optimized_skill_text`` set.
        """
        state = super().run(state, auto_confirm=auto_confirm)
        assert isinstance(state, OptimizeSkillPipelineState)

        if state.optimized_skill_text:
            out_path = state.output_dir / _OUTPUT_FILENAME
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(state.optimized_skill_text, encoding="utf-8")
            log.info("optimize_skill_written", path=str(out_path))
            print(f"\nOptimized skill file saved to: {out_path}")

        return state

    def _mlflow_run_name(self, state: OptimizeSkillPipelineState) -> str:  # type: ignore[override]
        stem = state.brief_path.stem if state.brief_path else "skill"
        return f"optimize-skill-{stem}-{uuid.uuid4().hex[:4]}"

    def _mlflow_tags(self, state: OptimizeSkillPipelineState) -> dict[str, str]:  # type: ignore[override]
        return {
            **super()._mlflow_tags(state),
            "trainset_dir": str(state.input_dir),
        }


def build_state(
    trainset_dir: Path,
    output_dir: Path,
    skill_path: Path | None,
    critique_max_retries: int,
) -> OptimizeSkillPipelineState:
    """Construct an OptimizeSkillPipelineState suitable for OptimizeSkillPipeline.

    ``brief_path`` is set to ``skill_path`` (the skill being optimised acts as
    the primary input document, which doubles as the MLflow run identifier).
    When no existing skill is provided a sentinel path is used so the pipeline
    can still start from scratch.

    Args:
        trainset_dir: Folder containing CapCut draft subfolders.
        output_dir: Where to write ``optimized_skill.md`` and critique JSONs.
        skill_path: Path to an existing skill file to improve, or ``None``.
        critique_max_retries: Maximum critique iterations.

    Returns:
        A fully initialised ``OptimizeSkillPipelineState``.
    """
    brief_path = skill_path if skill_path else (trainset_dir / "skill.md")
    return OptimizeSkillPipelineState(
        input_dir=trainset_dir,
        output_dir=output_dir,
        brief_path=brief_path,
        skill_path=skill_path,
        critique_max_retries=critique_max_retries,
    )
