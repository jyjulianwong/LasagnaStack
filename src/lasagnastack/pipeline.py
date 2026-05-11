import os
import uuid
from pathlib import Path

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
        ingest_max_workers: int = 2,
        analyse_max_workers: int = 4,
        analyse_client: LLMClient | None = None,
        direct_client: LLMClient | None = None,
        critique_client: LLMClient | None = None,
        enhance_client: LLMClient | None = None,
        post_caption_client: LLMClient | None = None,
    ) -> None:
        """Initialise the pipeline with optional per-stage LLM clients.

        Each LLM-backed stage accepts its own client. When ``None``, the stage
        constructs a fresh ``GeminiClient`` internally.

        Args:
            ingest_max_workers: Parallel worker processes for Stage 1.
            analyse_max_workers: Concurrent LLM calls for Stage 2.
            analyse_client: LLM client for Stage 2 (analyse).
            direct_client: LLM client for Stage 3 (direct).
            critique_client: LLM client for Stage 4 (critique).
            enhance_client: LLM client for Stage 5 (enhance).
            post_caption_client: LLM client for Stage 7 (post caption).
        """
        self._ingest_max_workers = ingest_max_workers
        self._analyse_max_workers = analyse_max_workers
        self._analyse_client = analyse_client
        self._direct_client = direct_client
        self._critique_client = critique_client
        self._enhance_client = enhance_client
        self._post_caption_client = post_caption_client

    @property
    def stages(self) -> list[Stage]:
        """Return the seven pipeline stages in execution order.

        Returns:
            Ordered list of ``Stage`` instances.
        """
        return [
            IngestStage(max_workers=self._ingest_max_workers),
            AnalyseStage(
                client=self._analyse_client, max_workers=self._analyse_max_workers
            ),
            DirectStage(client=self._direct_client),
            CritiqueStage(client=self._critique_client),
            EnhanceStage(client=self._enhance_client),
            RenderStage(),
            PostCaptionStage(client=self._post_caption_client),
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
            "model": os.getenv("LSNSTK_LLM_MODEL", "gemini/gemini-2.5-flash"),
        }


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

    A dedicated ``GeminiClient`` instance is created for each LLM-backed stage.
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

    state = ReelPipeline(
        ingest_max_workers=ingest_max_workers,
        analyse_max_workers=analyse_max_workers,
        analyse_client=GeminiClient(thinking_budget=4000),
        direct_client=GeminiClient(thinking_budget=12000),
        critique_client=GeminiClient(thinking_budget=12000),
        enhance_client=GeminiClient(thinking_budget=4000),
        post_caption_client=GeminiClient(thinking_budget=4000),
    ).run(state, auto_confirm=auto_confirm)

    log.info("pipeline_complete", draft=str(state.draft_path))
    print(f"\nDraft saved to: {state.draft_path}")
    print(f"Post caption saved to: {io.post_caption_path(output_dir)}")
