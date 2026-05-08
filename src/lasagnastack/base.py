from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

import structlog

from lasagnastack.models.cut_list import CutList
from lasagnastack.models.inventory import ClipInventory, NormalisedClip

log = structlog.get_logger()


@dataclass
class PipelineState:
    """Data and configuration threaded through all pipeline stages."""

    input_dir: Path
    output_dir: Path
    brief_path: Path
    max_critique_retries: int = 2
    normalised_clips: list[NormalisedClip] | None = None
    inventories: list[ClipInventory] | None = None
    cut_list: CutList | None = None
    draft_path: Path | None = None


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

    Subclasses declare stages(). The concrete run() handles confirmation
    prompts between stages and pipeline-level logging.
    """

    @property
    @abstractmethod
    def stages(self) -> list[Stage]: ...

    def run(self, state: PipelineState, auto_confirm: bool = False) -> PipelineState:
        """Run all stages in order, prompting for confirmation between each."""
        state.output_dir.mkdir(parents=True, exist_ok=True)
        log.info(
            "pipeline_start",
            input_dir=str(state.input_dir),
            output_dir=str(state.output_dir),
        )
        for i, stage in enumerate(self.stages):
            state = stage.run(state)
            if i < len(self.stages) - 1:
                _confirm(stage.completion_message(state), auto_confirm)
        return state


def _confirm(message: str, auto: bool) -> None:
    if auto:
        log.info("stage_confirm_auto", message=message)
        return
    answer = input(f"\n{message} [y/N] ").strip().lower()
    if answer != "y":
        raise SystemExit("Aborted by user.")
