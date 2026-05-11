import asyncio
import dataclasses
import importlib.resources
from pathlib import Path

import structlog

from lasagnastack import io
from lasagnastack.base import PipelineState, Stage
from lasagnastack.cache import DiskCache
from lasagnastack.llm.base import LLMClient
from lasagnastack.llm.gemini import GeminiClient
from lasagnastack.models.inventory import (
    ClipAnalysisResponse,
    ClipInventory,
    NormalisedClip,
)

log = structlog.get_logger()


async def _analyse_clip_async(
    clip: NormalisedClip,
    cache: DiskCache,
    client: LLMClient,
    semaphore: asyncio.Semaphore,
) -> ClipInventory:
    async with semaphore:
        return await asyncio.to_thread(_analyse_clip, clip, cache, client)


async def _run_async(
    clips: list[NormalisedClip],
    cache: DiskCache,
    client: LLMClient,
    max_workers: int,
) -> list[ClipInventory]:
    semaphore = asyncio.Semaphore(max_workers)
    tasks = [_analyse_clip_async(clip, cache, client, semaphore) for clip in clips]
    return list(await asyncio.gather(*tasks))


def run(
    clips: list[NormalisedClip],
    output_dir: Path,
    client: LLMClient | None = None,
    max_workers: int = 4,
) -> list[ClipInventory]:
    """Analyse each normalised clip with Gemini; cache results by content hash.

    Args:
        clips: Normalised clips from Stage 1.
        output_dir: Pipeline root; cache lives at output_dir/.cache,
            inventories written to output_dir/inventories/.
        client: LLM client to use. Defaults to GeminiClient.
        max_workers: Maximum number of concurrent LLM calls. Uses
            ``asyncio.gather`` with a semaphore; all calls run as threads
            via ``asyncio.to_thread`` since the LLM client is synchronous.

    Returns:
        One ClipInventory per clip, in the same order as clips.
    """
    if client is None:
        client = GeminiClient()

    cache = DiskCache(io.cache_dir(output_dir))
    inventories = asyncio.run(_run_async(clips, cache, client, max_workers))

    for clip, inventory in zip(clips, inventories):
        io.write_json(inventory, io.inventory_path(output_dir, clip.source_path.name))

    return inventories


def _analyse_clip(
    clip: NormalisedClip,
    cache: DiskCache,
    client: LLMClient,
) -> ClipInventory:
    key = cache.make_key(clip.normalised_path, client.__class__.__name__)
    cached = cache.get(key)
    if cached is not None:
        log.info("analyse_cache_hit", source=clip.source_path.name)
        return ClipInventory.model_validate(cached)

    log.info("analyse_start", source=clip.source_path.name)
    prompt = _load_prompt(clip.source_path.name, clip.duration_sec)
    analysis: ClipAnalysisResponse = client.generate_with_video(
        clip.normalised_path,
        prompt,
        ClipAnalysisResponse,
    )
    inventory = ClipInventory(
        source_file=clip.source_path.name,
        duration_sec=clip.duration_sec,
        overall_assessment=analysis.overall_assessment,
        segments=analysis.segments,
    )
    cache.set(key, inventory.model_dump())
    log.info(
        "analyse_done",
        source=clip.source_path.name,
        segments=len(inventory.segments),
    )
    return inventory


def _load_prompt(source_file: str, duration_sec: float) -> str:
    template = (
        importlib.resources.files("lasagnastack.prompts")
        .joinpath("analyse.md")
        .read_text(encoding="utf-8")
    )
    return template.format(source_file=source_file, duration_sec=duration_sec)


class AnalyseStage(Stage):
    def __init__(self, client: LLMClient | None = None, max_workers: int = 4) -> None:
        """Initialise AnalyseStage.

        Args:
            client: LLM client to use. Defaults to GeminiClient.
            max_workers: Maximum number of concurrent LLM calls.
        """
        self._client = client
        self._max_workers = max_workers

    def run(self, state: PipelineState) -> PipelineState:
        assert state.normalised_clips is not None
        inventories = run(
            state.normalised_clips,
            state.output_dir,
            self._client,
            max_workers=self._max_workers,
        )
        return dataclasses.replace(state, inventories=inventories)

    def completion_message(self, state: PipelineState) -> str:
        invs = state.inventories or []
        total = sum(len(inv.segments) for inv in invs)
        return (
            f"Stage 2 complete — {total} segment(s) found across "
            f"{len(invs)} clip(s). Continue to Stage 3 (direct)?"
        )
