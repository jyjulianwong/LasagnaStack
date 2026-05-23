"""Stage 3 of the optimize-skill pipeline: critique loop for the generated skill file."""

import dataclasses
import importlib.resources
import json

import structlog

from lasagnastack import io
from lasagnastack.base import PipelineState, Stage
from lasagnastack.llm.base import LLMClient
from lasagnastack.llm.gemini import GeminiClient
from lasagnastack.models.optimize_skill_pipeline.skill import CritiqueSkillResult
from lasagnastack.optimize_skill_pipeline_state import OptimizeSkillPipelineState

log = structlog.get_logger()

_MAX_RETRIES_DEFAULT = 2


def run(
    state: OptimizeSkillPipelineState,
    client: LLMClient | None = None,
    max_retries: int = _MAX_RETRIES_DEFAULT,
) -> str:
    """Critique the generated skill text, revising until approved or the retry cap is hit.

    Writes ``output_dir/skill_critique/iteration_N.json`` per iteration.

    Args:
        state: Pipeline state. ``draft_cut_lists``, ``draft_reel_style_sheets``,
            and ``optimized_skill_text`` must be set.
        client: LLM client to use. Defaults to ``GeminiClient``.
        max_retries: Maximum critique iterations before shipping the current text.

    Returns:
        The approved (or capped) skill text.
    """
    if client is None:
        client = GeminiClient()

    assert state.draft_cut_lists is not None
    assert state.draft_reel_style_sheets is not None
    assert state.optimized_skill_text is not None

    existing_skill = (
        state.skill_path.read_text(encoding="utf-8").strip()
        if state.skill_path and state.skill_path.exists()
        else ""
    )
    examples = _format_examples(state)
    current_skill = state.optimized_skill_text
    previous_issues: list[list[str]] = []

    for iteration in range(max_retries):
        result = _critique_once(
            existing_skill=existing_skill,
            current_skill=current_skill,
            examples=examples,
            client=client,
            iteration=iteration,
            previous_issues=previous_issues,
        )

        critique_path = (
            state.output_dir / "skill_critique" / f"iteration_{iteration}.json"
        )
        io.write_json(result, critique_path)

        if result.verdict == "approved" or result.skill_v2 is None:
            log.info("critique_skill_approved", iteration=iteration)
            return current_skill

        log.info(
            "critique_skill_revising",
            iteration=iteration,
            issues=result.issues,
        )
        previous_issues.append(result.issues)
        current_skill = result.skill_v2

    if max_retries > 0:
        log.warning("critique_skill_cap_reached", max_retries=max_retries)
    return current_skill


def _critique_once(
    existing_skill: str,
    current_skill: str,
    examples: str,
    client: LLMClient,
    iteration: int,
    previous_issues: list[list[str]],
) -> CritiqueSkillResult:
    if previous_issues:
        issues_lines = [
            f"Iteration {i}: {'; '.join(issues) if issues else 'none'}"
            for i, issues in enumerate(previous_issues)
        ]
        previous_issues_text = "\n".join(issues_lines)
    else:
        previous_issues_text = "None — this is the first review."

    template = (
        importlib.resources.files("lasagnastack.prompts.optimize_skill_pipeline")
        .joinpath("critique_skill.md")
        .read_text(encoding="utf-8")
    )
    prompt = template.format(
        existing_skill=existing_skill,
        current_skill=current_skill,
        examples=examples,
        previous_issues=previous_issues_text,
    )

    log.info("critique_skill_start", iteration=iteration)
    result: CritiqueSkillResult = client.generate(
        prompt, CritiqueSkillResult, temperature=0.3
    )
    log.info(
        "critique_skill_done",
        iteration=iteration,
        verdict=result.verdict,
        issues=len(result.issues),
    )
    return result


def _format_examples(state: OptimizeSkillPipelineState) -> str:
    assert state.draft_cut_lists is not None
    assert state.draft_reel_style_sheets is not None

    blocks = []
    for i, (cut_list, reel_style_sheet) in enumerate(
        zip(state.draft_cut_lists, state.draft_reel_style_sheets), start=1
    ):
        cut_list_json = json.dumps(
            cut_list.model_dump(by_alias=True), indent=2, ensure_ascii=False
        )
        reel_style_sheet_json = json.dumps(
            reel_style_sheet.model_dump(), indent=2, ensure_ascii=False
        )
        blocks.append(
            f"### Example {i}: {cut_list.reel_meta.title}\n\n"
            f"**Cut list:**\n```json\n{cut_list_json}\n```\n\n"
            f"**Reel style sheet:**\n```json\n{reel_style_sheet_json}\n```"
        )

    return "\n\n---\n\n".join(blocks)


class CritiqueSkillStage(Stage):
    """Iteratively critique and refine the generated skill file."""

    def __init__(self, client: LLMClient | None = None) -> None:
        self._client = client

    def run(self, state: PipelineState) -> PipelineState:
        """Run the critique loop and update ``optimized_skill_text`` with the result.

        Args:
            state: Pipeline state with ``optimized_skill_text`` set.

        Returns:
            Updated state with the approved (or capped) ``optimized_skill_text``.
        """
        assert isinstance(state, OptimizeSkillPipelineState)
        skill_text = run(
            state,
            client=self._client,
            max_retries=state.critique_max_retries,
        )
        return dataclasses.replace(state, optimized_skill_text=skill_text)

    def completion_message(self, state: PipelineState) -> str:
        return "Stage 3 complete — skill file approved."
