import dataclasses
import importlib.resources
import json
from pathlib import Path

import structlog

from lasagnastack import io
from lasagnastack.base import PipelineState, Stage
from lasagnastack.llm.base import LLMClient
from lasagnastack.llm.gemini import GeminiClient
from lasagnastack.models.cut_list import CutList
from lasagnastack.models.enhance import ReelStyle

log = structlog.get_logger()


def run(
    cut_list: CutList,
    brief_path: Path,
    output_dir: Path,
    client: LLMClient | None = None,
    skill_path: Path | None = None,
) -> ReelStyle:
    """Generate visual styling for the approved cut list.

    Sends the cut list and brief to the LLM and returns a ReelStyle describing
    per-cut transition types and caption effects (colour, animation, etc.).
    Writes reel_style.json to output_dir.

    Args:
        cut_list: Approved cut list from Stage 4.
        brief_path: Path to the freeform .txt creator brief.
        output_dir: Pipeline root; reel_style.json written here.
        client: LLM client to use. Defaults to GeminiClient.
        skill_path: Optional path to a Markdown skill file injected into the
            prompt before the creator brief.

    Returns:
        A ReelStyle ready for the render stage.
    """
    if client is None:
        client = GeminiClient()

    prompt = _build_prompt(cut_list, brief_path, skill_path)
    captioned = sum(1 for cut in cut_list.cuts if cut.caption)
    log.info("enhance_start", cuts=len(cut_list.cuts), captioned=captioned)

    reel_style: ReelStyle = client.generate(prompt, ReelStyle, temperature=0.5)

    io.write_json(reel_style, io.reel_style_path(output_dir))
    log.info("enhance_done", cut_styles=len(reel_style.cut_styles))
    return reel_style


def _build_prompt(
    cut_list: CutList,
    brief_path: Path,
    skill_path: Path | None = None,
) -> str:
    template = (
        importlib.resources.files("lasagnastack.prompts")
        .joinpath("enhance.md")
        .read_text(encoding="utf-8")
    )
    cut_list_json = json.dumps(cut_list.model_dump(by_alias=True), indent=2)
    skill_text = skill_path.read_text(encoding="utf-8").strip() if skill_path else ""
    return template.format(
        skill_text=skill_text,
        brief_text=brief_path.read_text(encoding="utf-8").strip(),
        cut_list_json=cut_list_json,
    )


class EnhanceStage(Stage):
    """Stage 5: assign visual styling and animations to the approved cut list."""

    def __init__(self, client: LLMClient | None = None) -> None:
        """Initialise with an optional LLM client.

        Args:
            client: LLM client to use. Defaults to GeminiClient.
        """
        self._client = client

    def run(self, state: PipelineState) -> PipelineState:
        """Run the enhance stage.

        Args:
            state: Current pipeline state. ``state.cut_list`` must be set.

        Returns:
            Updated pipeline state with ``reel_style`` set.
        """
        assert state.cut_list is not None
        reel_style = run(
            state.cut_list,
            state.brief_path,
            state.output_dir,
            self._client,
            state.skill_path,
        )
        return dataclasses.replace(state, reel_style=reel_style)

    def completion_message(self, state: PipelineState) -> str:
        """Return the post-stage confirmation message.

        Args:
            state: Current pipeline state.

        Returns:
            Human-readable completion string.
        """
        rs = state.reel_style
        assert rs is not None
        styled = sum(1 for cs in rs.cut_styles if cs.caption_effect is not None)
        return (
            f"Stage 5 complete — {len(rs.cut_styles)} cuts styled, "
            f"{styled} caption effect(s) assigned. Continue to Stage 6 (render)?"
        )
