import dataclasses
import itertools
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import ffmpeg
import structlog
from scenedetect import ContentDetector, open_video
from scenedetect.scene_manager import SceneManager

from lasagnastack import io
from lasagnastack.base import PipelineState, Stage
from lasagnastack.cache import DiskCache
from lasagnastack.logging_config import configure_logging
from lasagnastack.models.inventory import NormalisedClip

log = structlog.get_logger()

_CLIP_EXTENSIONS = {".mp4", ".mov"}
_TARGET_WIDTH = 480
_TARGET_HEIGHT = 854
_TARGET_FPS = 5
_TARGET_CODEC = "libx264"


def _process_clip(src: Path, dest: Path, cache_dir: Path) -> tuple[float, list[float]]:
    """Normalise src and detect its scene cuts. Module-level for multiprocessing picklability.

    Checks a ``DiskCache`` keyed on the SHA-256 of *src* before doing any work.
    A cache hit is only accepted when *dest* already exists on disk — if the
    normalised file was deleted the entry is treated as stale and processing
    runs again.

    Args:
        src: Source clip path.
        dest: Destination path for the normalised clip.
        cache_dir: Directory for the disk cache.

    Returns:
        ``(duration_sec, scene_cut_times)`` tuple.
    """
    cache = DiskCache(cache_dir)
    key = f"{src.name}_ingest"
    cached = cache.get(key)
    if cached is not None and dest.exists():
        log.info("ingest_cache_hit", source=src.name)
        return cached["duration_sec"], cached["scene_cut_times"]

    log.info("ingest_normalising", source=src.name, dest=dest.name)
    duration = _normalise_clip(src, dest)
    cuts = _detect_scene_cuts(src)
    log.info(
        "ingest_done",
        source=src.name,
        duration_sec=round(duration, 2),
        scene_cuts=len(cuts),
    )
    cache.set(key, {"duration_sec": duration, "scene_cut_times": cuts})
    return duration, cuts


def run(
    input_dir: Path,
    output_dir: Path,
    max_workers: int = 1,
) -> list[NormalisedClip]:
    """Normalise all clips to 480×854 H.264 and detect scene cuts.

    Args:
        input_dir: Folder containing raw MP4/MOV clips and the brief .txt.
        output_dir: Destination root; normalised clips written to output_dir/normalised/.
        max_workers: Number of parallel worker processes. ``1`` runs serially
            in the current process; ``>1`` uses a ``ProcessPoolExecutor``.

    Returns:
        One NormalisedClip per source file, in discovery order.
    """
    clips = _find_clips(input_dir)
    if not clips:
        raise ValueError(f"No MP4/MOV files found in {input_dir}")

    normalised_dir = output_dir / "normalised"
    normalised_dir.mkdir(parents=True, exist_ok=True)
    dests = [normalised_dir / f"{src.stem}_norm.mp4" for src in clips]
    cache_dir = io.cache_dir(output_dir)

    if max_workers > 1:
        with ProcessPoolExecutor(
            max_workers=max_workers, initializer=configure_logging
        ) as executor:
            process_results = list(
                executor.map(_process_clip, clips, dests, itertools.repeat(cache_dir))
            )
    else:
        process_results = [
            _process_clip(src, dest, cache_dir) for src, dest in zip(clips, dests)
        ]

    return [
        NormalisedClip(
            source_path=src,
            normalised_path=dest,
            duration_sec=duration,
            scene_cut_times=cuts,
        )
        for src, dest, (duration, cuts) in zip(clips, dests, process_results)
    ]


def _find_clips(input_dir: Path) -> list[Path]:
    return sorted(
        p for p in input_dir.iterdir() if p.suffix.lower() in _CLIP_EXTENSIONS
    )


def _normalise_clip(src: Path, dest: Path) -> float:
    """Re-encode src to 480×854 H.264/AAC at dest. Returns source duration in seconds."""
    probe = ffmpeg.probe(str(src))
    duration = float(probe["format"]["duration"])
    has_audio = any(s["codec_type"] == "audio" for s in probe["streams"])

    inp = ffmpeg.input(str(src))
    video = inp.video.filter(
        "scale",
        w=_TARGET_WIDTH,
        h=_TARGET_HEIGHT,
        force_original_aspect_ratio="decrease",
        force_divisible_by=2,
    ).filter(
        "pad",
        w=_TARGET_WIDTH,
        h=_TARGET_HEIGHT,
        x="(ow-iw)/2",
        y="(oh-ih)/2",
    )

    out_streams = [video, inp.audio] if has_audio else [video]
    out_kwargs: dict = dict(vcodec=_TARGET_CODEC, crf=23, preset="fast", r=_TARGET_FPS)
    if has_audio:
        out_kwargs["acodec"] = "aac"

    ffmpeg.output(*out_streams, str(dest), **out_kwargs).overwrite_output().run(
        quiet=True
    )
    return duration


def _detect_scene_cuts(clip_path: Path) -> list[float]:
    """Return scene-cut timestamps (seconds) via PySceneDetect ContentDetector.

    Uses the PyAV backend to avoid macOS OpenCV/AVFoundation timestamp issues.
    Returns an empty list on failure — Gemini-derived segments are the primary
    source; scene cuts are a fallback only.
    """
    try:
        video = open_video(str(clip_path), backend="pyav")
        manager = SceneManager()
        manager.add_detector(ContentDetector())
        manager.detect_scenes(video, show_progress=False)
        scene_list = manager.get_scene_list(start_in_scene=True)
    except Exception:
        log.warning("scene_detect_failed", source=clip_path.name, exc_info=True)
        return []
    # scene_list is [(start, end), ...]; cut times are the start of each scene after the first
    return [scene[0].seconds for scene in scene_list[1:]]


class IngestStage(Stage):
    def __init__(self, max_workers: int = 1) -> None:
        """Initialise IngestStage.

        Args:
            max_workers: Number of parallel worker processes for clip
                normalisation and scene detection. ``1`` runs serially.
        """
        self._max_workers = max_workers

    def run(self, state: PipelineState) -> PipelineState:
        clips = run(state.input_dir, state.output_dir, max_workers=self._max_workers)
        return dataclasses.replace(state, normalised_clips=clips)

    def completion_message(self, state: PipelineState) -> str:
        n = len(state.normalised_clips or [])
        return (
            f"Stage 1 complete — {n} clip(s) normalised. Continue to Stage 2 (analyse)?"
        )
