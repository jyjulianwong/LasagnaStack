import dataclasses
import importlib.resources
import json
from pathlib import Path

import structlog

from lasagnastack import io
from lasagnastack.base import PipelineState, Stage
from lasagnastack.llm.base import LLMClient
from lasagnastack.llm.gemini import GeminiClient
from lasagnastack.models.critique import CritiqueResult
from lasagnastack.models.cut_list import CutList
from lasagnastack.models.inventory import ClipInventory

log = structlog.get_logger()

_MAX_RETRIES_DEFAULT = 2


def run(
    cut_list: CutList,
    inventories: list[ClipInventory],
    brief_path: Path,
    output_dir: Path,
    max_retries: int = _MAX_RETRIES_DEFAULT,
    client: LLMClient | None = None,
) -> CutList:
    """Run the critique loop, replacing the cut list on revision until approved or capped.

    Writes critique/iteration_N.json per iteration via io.write_json / io.critique_path.

    Args:
        cut_list: Initial cut list from Stage 3.
        inventories: Segment inventories (for context).
        brief_path: Path to the creator brief.
        output_dir: Pipeline root; critique JSONs written here.
        max_retries: Maximum critique iterations before shipping as-is.
        client: LLM client to use. Defaults to GeminiClient.

    Returns:
        The approved (or capped) CutList.
    """
    if client is None:
        client = GeminiClient()

    for iteration in range(max_retries):
        result = _critique_once(cut_list, inventories, brief_path, client, iteration)
        io.write_json(result, io.critique_path(output_dir, iteration))

        if result.verdict == "approved" or result.cut_list_v2 is None:
            return cut_list

        log.info("critique_revising", iteration=iteration, issues=result.issues)
        cut_list = result.cut_list_v2

    if max_retries > 0:
        log.warning("critique_cap_reached", max_retries=max_retries)
    return cut_list


def _critique_once(
    cut_list: CutList,
    inventories: list[ClipInventory],
    brief_path: Path,
    client: LLMClient,
    iteration: int,
) -> CritiqueResult:
    prompt = _build_prompt(cut_list, inventories, brief_path)
    log.info("critique_start", iteration=iteration)
    result: CritiqueResult = client.generate(prompt, CritiqueResult, temperature=0.3)
    log.info(
        "critique_done",
        iteration=iteration,
        verdict=result.verdict,
        issues=len(result.issues),
    )
    return result


def _build_prompt(
    cut_list: CutList,
    inventories: list[ClipInventory],
    brief_path: Path,
) -> str:
    template = (
        importlib.resources.files("lasagnastack.prompts")
        .joinpath("critique.txt")
        .read_text(encoding="utf-8")
    )
    cut_list_json = json.dumps(cut_list.model_dump(by_alias=True), indent=2)
    inventories_json = json.dumps([inv.model_dump() for inv in inventories], indent=2)
    return template.format(
        brief_text=brief_path.read_text(encoding="utf-8").strip(),
        inventories_json=inventories_json,
        cut_list_json=cut_list_json,
    )


class CritiqueStage(Stage):
    def __init__(self, client: LLMClient | None = None) -> None:
        self._client = client

    def run(self, state: PipelineState) -> PipelineState:
        assert state.cut_list is not None
        assert state.inventories is not None
        cut_list = run(
            state.cut_list,
            state.inventories,
            state.brief_path,
            state.output_dir,
            max_retries=state.max_critique_retries,
            client=self._client,
        )
        return dataclasses.replace(state, cut_list=cut_list)

    def completion_message(self, state: PipelineState) -> str:
        return "Stage 4 complete — cut list approved. Continue to Stage 5 (render)?"
