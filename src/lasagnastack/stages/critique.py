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
    client: LLMClient | None = None,
    skill_path: Path | None = None,
    max_retries: int = _MAX_RETRIES_DEFAULT,
) -> CutList:
    """Run the critique loop, replacing the cut list on revision until approved or capped.

    Writes critique/iteration_N.json per iteration via io.write_json / io.critique_path.

    Args:
        cut_list: Initial cut list from Stage 3.
        inventories: Segment inventories (for context).
        brief_path: Path to the creator brief.
        output_dir: Pipeline root; critique JSONs written here.
        client: LLM client to use. Defaults to GeminiClient.
        skill_path: Optional path to a Markdown skill file injected into the
            prompt before the creator brief.
        max_retries: Maximum critique iterations before shipping as-is.

    Returns:
        The approved (or capped) CutList.
    """
    if client is None:
        client = GeminiClient()

    previous_issues: list[list[str]] = []
    for iteration in range(max_retries):
        result = _critique_once(
            cut_list,
            inventories,
            brief_path,
            client,
            iteration,
            previous_issues,
            skill_path,
        )
        io.write_json(result, io.critique_path(output_dir, iteration))

        if result.verdict == "approved" or result.cut_list_v2 is None:
            return cut_list

        log.info("critique_revising", iteration=iteration, issues=result.issues)
        previous_issues.append(result.issues)
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
    previous_issues: list[list[str]],
    skill_path: Path | None = None,
) -> CritiqueResult:
    prompt = _build_prompt(
        cut_list, inventories, brief_path, previous_issues, skill_path
    )
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
    previous_issues: list[list[str]],
    skill_path: Path | None = None,
) -> str:
    template = (
        importlib.resources.files("lasagnastack.prompts")
        .joinpath("critique.md")
        .read_text(encoding="utf-8")
    )
    cut_list_json = json.dumps(cut_list.model_dump(by_alias=True), indent=2)
    inventories_json = json.dumps([inv.model_dump() for inv in inventories], indent=2)
    if previous_issues:
        issues_lines = [
            f"Iteration {i}: {'; '.join(issues) if issues else 'none'}"
            for i, issues in enumerate(previous_issues)
        ]
        previous_issues_text = "\n".join(issues_lines)
    else:
        previous_issues_text = "None — this is the first review."
    skill_text = skill_path.read_text(encoding="utf-8").strip() if skill_path else ""
    return template.format(
        skill_text=skill_text,
        brief_text=brief_path.read_text(encoding="utf-8").strip(),
        inventories_json=inventories_json,
        cut_list_json=cut_list_json,
        previous_issues=previous_issues_text,
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
            client=self._client,
            skill_path=state.skill_path,
            max_retries=state.critique_max_retries,
        )
        return dataclasses.replace(state, cut_list=cut_list)

    def completion_message(self, state: PipelineState) -> str:
        return "Stage 4 complete — cut list approved. Continue to Stage 5 (enhance)?"
