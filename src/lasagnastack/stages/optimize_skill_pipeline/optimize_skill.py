"""Stage 2 of the optimize-skill pipeline: generate an improved skill file."""

import dataclasses
import importlib.resources
import json

import structlog

from lasagnastack.base import PipelineState, Stage
from lasagnastack.llm.base import LLMClient
from lasagnastack.llm.gemini import GeminiClient
from lasagnastack.models.optimize_skill_pipeline.skill import OptimizedSkill
from lasagnastack.optimize_skill_pipeline_state import OptimizeSkillPipelineState

log = structlog.get_logger()


def run(
    state: OptimizeSkillPipelineState,
    client: LLMClient | None = None,
) -> str:
    """Call the LLM with the existing skill + few-shot examples → improved skill text.

    Args:
        state: Pipeline state. ``draft_cut_lists``, ``draft_reel_style_sheets``,
            and ``skill_path`` must all be set.
        client: LLM client to use. Defaults to ``GeminiClient``.

    Returns:
        The full text of the improved skill Markdown file.
    """
    if client is None:
        client = GeminiClient()

    assert state.draft_cut_lists is not None
    assert state.draft_reel_style_sheets is not None

    existing_skill = (
        state.skill_path.read_text(encoding="utf-8").strip()
        if state.skill_path and state.skill_path.exists()
        else "(no existing skill — generate from scratch)"
    )

    examples = _format_examples(state)
    prompt = _build_prompt(existing_skill, examples)

    log.info("optimize_skill_start", drafts=len(state.draft_cut_lists))
    result: OptimizedSkill = client.generate(prompt, OptimizedSkill, temperature=0.4)
    log.info("optimize_skill_done", chars=len(result.skill_text))
    return result.skill_text


def _format_examples(state: OptimizeSkillPipelineState) -> str:
    """Render each (CutList, ReelStyleSheet) pair as a numbered Markdown block."""
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


def _build_prompt(existing_skill: str, examples: str) -> str:
    template = (
        importlib.resources.files("lasagnastack.prompts.optimize_skill_pipeline")
        .joinpath("optimize_skill.md")
        .read_text(encoding="utf-8")
    )
    return template.format(existing_skill=existing_skill, examples=examples)


class OptimizeSkillStage(Stage):
    """Generate an improved skill file from the parsed training examples."""

    def __init__(self, client: LLMClient | None = None) -> None:
        self._client = client

    def run(self, state: PipelineState) -> PipelineState:
        """Run the optimization LLM call and store the result in state.

        Args:
            state: Pipeline state with ``draft_cut_lists`` and ``draft_reel_style_sheets``.

        Returns:
            Updated state with ``optimized_skill_text`` set.
        """
        assert isinstance(state, OptimizeSkillPipelineState)
        skill_text = run(state, client=self._client)
        return dataclasses.replace(state, optimized_skill_text=skill_text)

    def completion_message(self, state: PipelineState) -> str:
        return (
            "Stage 2 complete — skill draft generated. Continue to Stage 3 (critique)?"
        )
