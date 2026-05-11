import os
import uuid
from pathlib import Path

import mlflow
import structlog

from lasagnastack import io
from lasagnastack.base import Pipeline, PipelineState, Stage
from lasagnastack.llm.base import LLMClient
from lasagnastack.llm.gemini import GeminiClient
from lasagnastack.stages.analyse import AnalyseStage
from lasagnastack.stages.critique import CritiqueStage
from lasagnastack.stages.direct import DirectStage
from lasagnastack.stages.enhance import EnhanceStage
from lasagnastack.stages.ingest import IngestStage
from lasagnastack.stages.post_caption import PostCaptionStage
from lasagnastack.stages.render import RenderStage

log = structlog.get_logger()


def _find_brief(input_dir: Path) -> Path:
    """Find the single .txt brief file in input_dir.

    Args:
        input_dir: Directory expected to contain exactly one ``.txt`` file.

    Returns:
        Path to the brief file.

    Raises:
        ValueError: If there is not exactly one ``.txt`` file in the directory.
    """
    txts = list(input_dir.glob("*.txt"))
    if len(txts) != 1:
        raise ValueError(
            f"Expected exactly 1 .txt brief in {input_dir}, found {len(txts)}."
        )
    return txts[0]


class ReelPipeline(Pipeline):
    """The seven-stage raw video clips → CapCut draft + post caption pipeline."""

    def __init__(
        self,
        client: LLMClient | None = None,
        ingest_max_workers: int = 2,
        analyse_max_workers: int = 4,
    ) -> None:
        """Initialise the pipeline with an optional shared LLM client.

        Args:
            client: LLM client injected into every LLM-backed stage. Defaults
                to a freshly constructed ``GeminiClient`` per stage when
                ``None``.
            ingest_max_workers: Parallel worker processes for Stage 1.
            analyse_max_workers: Concurrent LLM calls for Stage 2.
        """
        self._client = client
        self._ingest_max_workers = ingest_max_workers
        self._analyse_max_workers = analyse_max_workers

    @property
    def stages(self) -> list[Stage]:
        """Return the seven pipeline stages in execution order.

        Returns:
            Ordered list of ``Stage`` instances.
        """
        return [
            IngestStage(max_workers=self._ingest_max_workers),
            AnalyseStage(self._client, max_workers=self._analyse_max_workers),
            DirectStage(self._client),
            CritiqueStage(self._client),
            EnhanceStage(self._client),
            RenderStage(),
            PostCaptionStage(self._client),
        ]

    def _mlflow_run_name(self, state: PipelineState) -> str:
        """Return the MLflow run name, prefixed with ``lasagnastack``.

        Args:
            state: Current pipeline state.

        Returns:
            Run name string.
        """
        return f"lasagnastack-{state.brief_path.stem}-{uuid.uuid4().hex[:4]}"

    def _mlflow_tags(self, state: PipelineState) -> dict[str, str]:
        """Extend base tags with the active Gemini model name.

        Args:
            state: Current pipeline state.

        Returns:
            Dict of string tags written to the MLflow run.
        """
        return {
            **super()._mlflow_tags(state),
            "model": os.getenv("LASAGNASTACK_LLM_MODEL", "gemini/gemini-2.5-flash"),
        }

    def _log_mlflow_session_metrics(self, state: PipelineState) -> None:
        """Log GeminiClient token and cost totals to the active MLflow run.

        Only logs when ``self._client`` is a ``GeminiClient`` instance
        (i.e. an explicit client was injected).

        Args:
            state: Final pipeline state (unused; present for interface
                compatibility).
        """
        if isinstance(self._client, GeminiClient):
            mlflow.log_metrics(self._client.session_stats)


def run_pipeline(
    input_dir: Path,
    output_dir: Path,
    skill_path: Path | None = None,
    auto_confirm: bool = False,
    critique_max_retries: int = 2,
    ingest_max_workers: int = 2,
    analyse_max_workers: int = 4,
) -> None:
    """Run the full seven-stage pipeline.

    A single ``GeminiClient`` instance is shared across all LLM stages so that
    per-session token and cost totals are accumulated on one object and logged
    to MLflow via ``_log_mlflow_session_metrics`` on ``ReelPipeline``.
    MLflow tracking is optional — the pipeline runs normally if the server is
    unreachable.

    Args:
        input_dir: Directory containing MP4/MOV clips and a single ``.txt``
            creator brief.
        output_dir: Root directory for all pipeline outputs (normalised clips,
            inventories, cut list, critique JSONs, and the CapCut draft).
        skill_path: Optional path to a Markdown skill file injected into the
            direct, critique, and enhance prompt templates.
        auto_confirm: When ``True``, skip the interactive confirmation prompt
            between stages.
        critique_max_retries: Maximum number of critique iterations before the
            pipeline ships the current cut list as-is.
        ingest_max_workers: Parallel worker processes for Stage 1 (ingest).
        analyse_max_workers: Concurrent LLM calls for Stage 2 (analyse).
    """
    brief_path = _find_brief(input_dir)
    state = PipelineState(
        input_dir=input_dir,
        output_dir=output_dir,
        brief_path=brief_path,
        skill_path=skill_path,
        critique_max_retries=critique_max_retries,
    )

    client = GeminiClient()
    state = ReelPipeline(
        client,
        ingest_max_workers=ingest_max_workers,
        analyse_max_workers=analyse_max_workers,
    ).run(state, auto_confirm=auto_confirm)

    log.info("pipeline_complete", draft=str(state.draft_path))
    print(f"\nDraft saved to: {state.draft_path}")
    print(f"Post caption saved to: {io.post_caption_path(output_dir)}")
