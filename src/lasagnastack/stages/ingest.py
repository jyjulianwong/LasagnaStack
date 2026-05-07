import dataclasses
from pathlib import Path

import ffmpeg
import structlog
from scenedetect import ContentDetector, open_video
from scenedetect.scene_manager import SceneManager

from lasagnastack.base import PipelineState, Stage
from lasagnastack.models.inventory import NormalisedClip

log = structlog.get_logger()

_CLIP_EXTENSIONS = {".mp4", ".mov"}
_TARGET_WIDTH = 720
_TARGET_HEIGHT = 1280
_TARGET_CODEC = "libx264"


def run(input_dir: Path, output_dir: Path) -> list[NormalisedClip]:
    """Normalise all clips to 720×1280 H.264 and detect scene cuts.

    Args:
        input_dir: Folder containing raw MP4/MOV clips and the brief .txt.
        output_dir: Destination root; normalised clips written to output_dir/normalised/.

    Returns:
        One NormalisedClip per source file, in discovery order.
    """
    clips = _find_clips(input_dir)
    if not clips:
        raise ValueError(f"No MP4/MOV files found in {input_dir}")

    normalised_dir = output_dir / "normalised"
    normalised_dir.mkdir(parents=True, exist_ok=True)

    results = []
    for src in clips:
        dest = normalised_dir / f"{src.stem}_norm.mp4"
        log.info("ingest_normalising", source=src.name, dest=dest.name)
        duration = _normalise_clip(src, dest)
        cuts = _detect_scene_cuts(src)  # source clip: unpadded, better signal
        log.info(
            "ingest_done",
            source=src.name,
            duration_sec=round(duration, 2),
            scene_cuts=len(cuts),
        )
        results.append(
            NormalisedClip(
                source_path=src,
                normalised_path=dest,
                duration_sec=duration,
                scene_cut_times=cuts,
            )
        )

    return results


def _find_clips(input_dir: Path) -> list[Path]:
    return sorted(
        p for p in input_dir.iterdir() if p.suffix.lower() in _CLIP_EXTENSIONS
    )


def _normalise_clip(src: Path, dest: Path) -> float:
    """Re-encode src to 720×1280 H.264/AAC at dest. Returns source duration in seconds."""
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
    out_kwargs: dict = dict(vcodec=_TARGET_CODEC, crf=23, preset="fast")
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
        log.warning("scene_detect_failed", clip=clip_path.name, exc_info=True)
        return []
    # scene_list is [(start, end), ...]; cut times are the start of each scene after the first
    return [scene[0].seconds for scene in scene_list[1:]]


class IngestStage(Stage):
    def run(self, state: PipelineState) -> PipelineState:
        clips = run(state.input_dir, state.output_dir)
        return dataclasses.replace(state, normalised_clips=clips)

    def completion_message(self, state: PipelineState) -> str:
        n = len(state.normalised_clips or [])
        return f"Stage 1 complete — {n} clip(s) normalised. Continue to Stage 2 (analyse)?"
