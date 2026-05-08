import os
import uuid
from collections.abc import Callable, Generator
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from typing import Any

import mlflow
import structlog

from lasagnastack.base import Pipeline, PipelineState, Stage
from lasagnastack.llm.base import LLMClient
from lasagnastack.llm.gemini import GeminiClient
from lasagnastack.stages.analyse import AnalyseStage
from lasagnastack.stages.critique import CritiqueStage
from lasagnastack.stages.direct import DirectStage
from lasagnastack.stages.ingest import IngestStage
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


@contextmanager
def _mlflow_run(
    run_name: str,
    tags: dict[str, str],
    span_name: str,
) -> Generator[None, None, None]:
    """Context manager that wraps a block in an MLflow run.

    Attempts to create an experiment (from ``MLFLOW_EXPERIMENT_NAME``) and
    start a run. Falls back to a no-op if the tracking server is unreachable
    or not configured, so the pipeline always continues regardless.

    Args:
        run_name: Display name for the MLflow run.
        tags: Key-value tags to attach to the run.
        span_name: Name for the top-level MLflow span, typically
            ``"ClassName.method_name"``.

    Yields:
        Nothing; used purely for its side effect of tracking the wrapped block.
    """
    try:
        experiment_name = os.getenv("MLFLOW_EXPERIMENT_NAME", "lasagnastack")
        mlflow.set_experiment(experiment_name)
        ctx = mlflow.start_run(run_name=run_name, tags=tags)
    except Exception as exc:
        log.warning("mlflow_unavailable", error=str(exc))
        yield
        return

    with ctx:
        with mlflow.start_span(
            name=span_name,
            span_type=mlflow.entities.SpanType.CHAIN,
        ):
            yield


def mlflow_tracked(
    method: Callable[..., PipelineState],
) -> Callable[..., PipelineState]:
    """Decorator that wraps a ``Pipeline.run`` method in an MLflow tracking run.

    Derives the run name and tags from the ``PipelineState`` passed as the
    first positional argument. Logs ``session_stats`` to the active run after
    the method returns, provided ``self._client`` is a non-``None``
    ``GeminiClient`` instance (i.e. the client was explicitly injected).

    Args:
        method: The ``run(self, state, ...)`` method to wrap.

    Returns:
        The wrapped method with MLflow tracking applied.
    """

    @wraps(method)
    def wrapper(self: Any, state: PipelineState, **kwargs: Any) -> PipelineState:
        run_name = f"lasagnastack-{state.brief_path.stem}-{uuid.uuid4().hex[:4]}"
        tags = {
            "model": os.getenv("LASAGNASTACK_LLM_MODEL", "gemini/gemini-2.5-flash"),
            "brief_path": state.brief_path.stem,
            "critique_max_retries": str(state.critique_max_retries),
        }

        span_name = f"{type(self).__name__}.{method.__name__}"
        with _mlflow_run(run_name, tags, span_name):
            result = method(self, state, **kwargs)
            client = getattr(self, "_client", None)
            if mlflow.active_run() and isinstance(client, GeminiClient):
                mlflow.log_metrics(client.session_stats)

        return result

    return wrapper


class ReelPipeline(Pipeline):
    """The five-stage raw video clips → CapCut draft pipeline."""

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
        """Return the five pipeline stages in execution order.

        Returns:
            Ordered list of ``Stage`` instances.
        """
        return [
            IngestStage(max_workers=self._ingest_max_workers),
            AnalyseStage(self._client, max_workers=self._analyse_max_workers),
            DirectStage(self._client),
            CritiqueStage(self._client),
            RenderStage(),
        ]

    @mlflow_tracked
    def run(self, state: PipelineState, **kwargs: Any) -> PipelineState:
        """Run all stages with MLflow tracking applied.

        Args:
            state: Initial pipeline state.
            **kwargs: Forwarded to ``Pipeline.run`` (e.g. ``auto_confirm``).

        Returns:
            Final pipeline state after all stages complete.
        """
        return super().run(state, **kwargs)


def run_pipeline(
    input_dir: Path,
    output_dir: Path,
    auto_confirm: bool = False,
    critique_max_retries: int = 2,
    ingest_max_workers: int = 2,
    analyse_max_workers: int = 4,
) -> None:
    """Run the full five-stage pipeline.

    A single ``GeminiClient`` instance is shared across all LLM stages so that
    per-session token and cost totals are accumulated on one object and logged
    to MLflow via the ``@mlflow_tracked`` decorator on ``ReelPipeline.run``.
    MLflow tracking is optional — the pipeline runs normally if the server is
    unreachable.

    Args:
        input_dir: Directory containing MP4/MOV clips and a single ``.txt``
            creator brief.
        output_dir: Root directory for all pipeline outputs (normalised clips,
            inventories, cut list, critique JSONs, and the CapCut draft).
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
