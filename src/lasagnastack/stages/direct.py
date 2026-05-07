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

log = structlog.get_logger()


def run(
    inventories: list[ClipInventory],
    brief_path: Path,
    output_dir: Path,
    client: LLMClient | None = None,
) -> CutList:
    """Generate an ordered cut list from all segment inventories and the brief.

    Writes cut_list.json to output_dir via io.write_json / io.cut_list_path.

    Args:
        inventories: All ClipInventory objects from Stage 2.
        brief_path: Path to the freeform .txt creator brief.
        output_dir: Pipeline root; cut_list.json written here.
        client: LLM client to use. Defaults to GeminiClient.

    Returns:
        A CutList ready for critique or rendering.
    """
    if client is None:
        client = GeminiClient()

    prompt = _build_prompt(inventories, brief_path)
    total_segments = sum(len(inv.segments) for inv in inventories)
    log.info("direct_start", clips=len(inventories), segments=total_segments)

    cut_list: CutList = client.generate(prompt, CutList, temperature=0.6)

    io.write_json(cut_list, io.cut_list_path(output_dir))
    log.info("direct_done", cuts=len(cut_list.cuts))
    return cut_list


def _build_prompt(inventories: list[ClipInventory], brief_path: Path) -> str:
    template = (
        importlib.resources.files("lasagnastack.prompts")
        .joinpath("direct.txt")
        .read_text(encoding="utf-8")
    )
    inventories_json = json.dumps(
        [inv.model_dump() for inv in inventories], indent=2
    )
    return template.format(
        brief_text=brief_path.read_text(encoding="utf-8").strip(),
        inventories_json=inventories_json,
    )


class DirectStage(Stage):
    def __init__(self, client: LLMClient | None = None) -> None:
        self._client = client

    def run(self, state: PipelineState) -> PipelineState:
        assert state.inventories is not None
        cut_list = run(state.inventories, state.brief_path, state.output_dir, self._client)
        return dataclasses.replace(state, cut_list=cut_list)

    def completion_message(self, state: PipelineState) -> str:
        cl = state.cut_list
        assert cl is not None
        return (
            f"Stage 3 complete — {len(cl.cuts)} cut(s) planned "
            f"(~{cl.reel_meta.target_duration_sec}s). Continue to Stage 4 (critique)?"
        )
