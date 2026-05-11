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
from lasagnastack.models.inventory import ClipInventory
from lasagnastack.models.post_caption import PostCaption

log = structlog.get_logger()


def run(
    cut_list: CutList,
    inventories: list[ClipInventory],
    brief_path: Path,
    output_dir: Path,
    client: LLMClient | None = None,
    skill_path: Path | None = None,
) -> PostCaption:
    """Generate an Instagram post caption for the finished reel.

    Sends the brief, reel metadata, and segment descriptions to the LLM and
    returns a PostCaption. Writes post_caption.txt to output_dir.

    Args:
        cut_list: Approved cut list from Stage 4 (provides reel metadata and
            per-cut captions used to ground the generated text).
        inventories: Clip inventories from Stage 2 (segment descriptions used
            to make the caption specific to what was actually filmed).
        brief_path: Path to the freeform .txt creator brief.
        output_dir: Pipeline root; post_caption.txt written here.
        client: LLM client to use. Defaults to GeminiClient.
        skill_path: Optional path to a Markdown skill file injected into the
            prompt before the creator brief.

    Returns:
        A PostCaption ready to copy-paste at publish time.
    """
    if client is None:
        client = GeminiClient()

    prompt = _build_prompt(cut_list, inventories, brief_path, skill_path)
    log.info(
        "post_caption_start",
        reel_title=cut_list.reel_meta.title,
        clips=len(inventories),
    )

    post_caption: PostCaption = client.generate(prompt, PostCaption, temperature=0.7)

    io.write_post_caption(output_dir, post_caption.caption)
    log.info("post_caption_done", path=str(io.post_caption_path(output_dir)))
    return post_caption


def _build_prompt(
    cut_list: CutList,
    inventories: list[ClipInventory],
    brief_path: Path,
    skill_path: Path | None = None,
) -> str:
    template = (
        importlib.resources.files("lasagnastack.prompts")
        .joinpath("post_caption.md")
        .read_text(encoding="utf-8")
    )
    reel_meta_json = json.dumps(cut_list.reel_meta.model_dump(), indent=2)
    segment_descriptions = _format_segment_descriptions(inventories)
    skill_text = skill_path.read_text(encoding="utf-8").strip() if skill_path else ""
    return template.format(
        skill_text=skill_text,
        brief_text=brief_path.read_text(encoding="utf-8").strip(),
        reel_meta_json=reel_meta_json,
        segment_descriptions=segment_descriptions,
    )


def _format_segment_descriptions(inventories: list[ClipInventory]) -> str:
    lines: list[str] = []
    for inv in inventories:
        for seg in inv.segments:
            lines.append(f"- [{seg.shot_type}] {seg.description}")
    return "\n".join(lines)


class PostCaptionStage(Stage):
    """Stage 7: generate an Instagram post caption for the finished reel."""

    def __init__(self, client: LLMClient | None = None) -> None:
        """Initialise with an optional LLM client.

        Args:
            client: LLM client to use. Defaults to GeminiClient.
        """
        self._client = client

    def run(self, state: PipelineState) -> PipelineState:
        """Run the post caption stage.

        Args:
            state: Current pipeline state. ``state.cut_list`` and
                ``state.inventories`` must be set.

        Returns:
            Updated pipeline state with ``post_caption`` set.
        """
        assert state.cut_list is not None
        assert state.inventories is not None
        post_caption = run(
            state.cut_list,
            state.inventories,
            state.brief_path,
            state.output_dir,
            self._client,
            state.skill_path,
        )
        return dataclasses.replace(state, post_caption=post_caption)

    def completion_message(self, state: PipelineState) -> str:
        """Return the post-stage confirmation message.

        Args:
            state: Current pipeline state.

        Returns:
            Human-readable completion string.
        """
        path = io.post_caption_path(state.output_dir)
        return f"Stage 7 complete — post caption written to {path}."
