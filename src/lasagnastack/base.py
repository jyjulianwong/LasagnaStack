import os
import uuid
from abc import ABC, abstractmethod
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import mlflow
import mlflow.entities
import structlog

from lasagnastack.models.cut_list import CutList
from lasagnastack.models.enhance import ReelStyle
from lasagnastack.models.inventory import ClipInventory, NormalisedClip
from lasagnastack.models.post_caption import PostCaption

log = structlog.get_logger()


@dataclass
class PipelineState:
    """Data and configuration threaded through all pipeline stages."""

    input_dir: Path
    output_dir: Path
    brief_path: Path
    skill_path: Path | None = None
    critique_max_retries: int = 2
    normalised_clips: list[NormalisedClip] | None = None
    inventories: list[ClipInventory] | None = None
    cut_list: CutList | None = None
    reel_style: ReelStyle | None = None
    draft_path: Path | None = None
    post_caption: PostCaption | None = None


@contextmanager
def _mlflow_run(
    run_name: str,
    tags: dict[str, str],
    span_name: str,
) -> Generator[None, None, None]:
    """Context manager that wraps a block in an MLflow run and top-level span.

    Attempts to create an experiment (from ``MLFLOW_EXPERIMENT_NAME``) and
    start a run. Falls back to a no-op if the tracking server is unreachable
    or not configured, so the pipeline always continues regardless.

    Args:
        run_name: Display name for the MLflow run.
        tags: Key-value tags to attach to the run.
        span_name: Name for the top-level CHAIN span, typically
            ``"ClassName.run"``.

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


class Stage(ABC):
    """One step in a Pipeline.

    Implement run() to transform the state and completion_message() to
    provide the text shown in the confirmation prompt before the next stage.
    """

    @abstractmethod
    def run(self, state: PipelineState) -> PipelineState:
        """Execute this stage. Receives the current state; returns updated state."""
        ...

    @abstractmethod
    def completion_message(self, state: PipelineState) -> str:
        """Human-readable summary shown after this stage completes and before the next."""
        ...


class Pipeline(ABC):
    """An ordered sequence of Stages run end-to-end.

    Subclasses declare ``stages``. The concrete ``run()`` handles MLflow
    tracking, per-stage spans, confirmation prompts, and pipeline logging.
    Override the three hook methods to customise observability behaviour
    without touching the orchestration logic.
    """

    @property
    @abstractmethod
    def stages(self) -> list[Stage]: ...

    def _mlflow_run_name(self, state: PipelineState) -> str:
        """Return the MLflow run display name for this execution.

        Default: ``"{classname}-{brief_stem}-{4-char hex}"``.
        Override to use a different naming convention.

        Args:
            state: Current pipeline state.

        Returns:
            String used as the MLflow run name.
        """
        return (
            f"{type(self).__name__.lower()}-"
            f"{state.brief_path.stem}-"
            f"{uuid.uuid4().hex[:4]}"
        )

    def _mlflow_tags(self, state: PipelineState) -> dict[str, str]:
        """Return key-value tags attached to the MLflow run.

        Default: ``brief_path`` and ``critique_max_retries`` from state.
        Override (calling ``super()._mlflow_tags(state)``) to extend.

        Args:
            state: Current pipeline state.

        Returns:
            Dict of string tags written to the MLflow run.
        """
        return {
            "brief_path": state.brief_path.stem,
            "critique_max_retries": str(state.critique_max_retries),
        }

    def _log_mlflow_session_metrics(self, state: PipelineState) -> None:
        """Log session-level metrics to the active MLflow run.

        Called while the MLflow run is still active, immediately after all
        stages complete. No-op by default. Override to log token counts,
        cost totals, or other session-level values.

        Args:
            state: Final pipeline state after all stages have run.
        """
        pass

    def _run_stage(self, stage: Stage, state: PipelineState) -> PipelineState:
        """Invoke a single stage wrapped in an MLflow CHAIN span.

        The span is named ``"{StageName}.run"`` using the concrete subclass
        name so traces show e.g. ``AnalyseStage.run`` rather than ``Stage.run``.
        ``mlflow.start_span`` is a no-op when no active run exists.

        Args:
            stage: The stage to execute.
            state: Current pipeline state passed to the stage.

        Returns:
            Updated pipeline state returned by the stage.
        """
        span_name = f"{type(stage).__name__}.run"
        with mlflow.start_span(
            name=span_name,
            span_type=mlflow.entities.SpanType.CHAIN,
        ):
            return stage.run(state)

    def run(self, state: PipelineState, auto_confirm: bool = False) -> PipelineState:
        """Run all stages in order, wrapped in MLflow tracking.

        Opens an MLflow experiment run and a top-level CHAIN span named
        ``"{ClassName}.run"`` (using the concrete subclass name). Each stage
        is executed via ``_run_stage``, which opens an additional per-stage
        CHAIN span. Falls back to uninstrumented execution when MLflow is
        unreachable or unconfigured.

        After all stages complete (and while the run is still active),
        ``_log_mlflow_session_metrics`` is called so subclasses can log
        token counts, costs, or other session-level metrics.

        Args:
            state: Initial pipeline state.
            auto_confirm: When ``True``, skip the interactive confirmation
                prompt between stages.

        Returns:
            Final pipeline state after all stages complete.
        """
        run_name = self._mlflow_run_name(state)
        tags = self._mlflow_tags(state)
        span_name = f"{type(self).__name__}.run"

        with _mlflow_run(run_name, tags, span_name):
            state.output_dir.mkdir(parents=True, exist_ok=True)
            log.info(
                "pipeline_start",
                input_dir=str(state.input_dir),
                output_dir=str(state.output_dir),
            )
            for i, stage in enumerate(self.stages):
                state = self._run_stage(stage, state)
                if i < len(self.stages) - 1:
                    _confirm(stage.completion_message(state), auto_confirm)

            if mlflow.active_run():
                self._log_mlflow_session_metrics(state)

        return state


def _confirm(message: str, auto: bool) -> None:
    if auto:
        log.info("stage_confirm_auto", message=message)
        return
    answer = input(f"\n{message} [y/N] ").strip().lower()
    if answer != "y":
        raise SystemExit("Aborted by user.")
