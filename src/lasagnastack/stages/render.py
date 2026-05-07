import dataclasses
import json
import re
import shutil
from pathlib import Path

import structlog
from pycapcut import (
    SEC,
    ClipSettings,
    CropSettings,
    DraftFolder,
    TextSegment,
    TextStyle,
    Timerange,
    TrackType,
    TransitionType,
    VideoMaterial,
    VideoSegment,
)

from lasagnastack import io
from lasagnastack.base import PipelineState, Stage
from lasagnastack.models.cut_list import CropHint, CutList

log = structlog.get_logger()

_DRAFT_WIDTH = 1080
_DRAFT_HEIGHT = 1920
_DRAFT_FPS = 30
_PREFIX = "LasagnaStack"


def run(cut_list: CutList, output_dir: Path, input_dir: Path) -> Path:
    """Translate the final cut list into a pyCapCut draft folder.

    Uses original source clips (not normalised) for full resolution.
    Draft written to output_dir/draft/<restaurant_name>/, then copied into
    the CapCut local drafts directory with source clips embedded alongside
    the draft JSON so CapCut opens it without missing-media errors.

    Args:
        cut_list: Approved cut list from Stage 4.
        output_dir: Pipeline root; draft created at output_dir/draft/.
        input_dir: Folder containing the original source clips.

    Returns:
        Path to the draft folder inside CapCut (or output_dir/draft/ if
        CapCut was not found).
    """
    draft_parent = io.draft_dir(output_dir)
    draft_parent.mkdir(parents=True, exist_ok=True)

    restaurant = cut_list.reel_meta.restaurant
    folder_name = _draft_folder_name(restaurant)
    display_name = _draft_display_name(restaurant)
    script = DraftFolder(str(draft_parent)).create_draft(
        folder_name, _DRAFT_WIDTH, _DRAFT_HEIGHT, _DRAFT_FPS, allow_replace=True
    )
    script.content["name"] = display_name
    script.add_track(TrackType.video)

    has_captions = any(cut.caption for cut in cut_list.cuts)
    if has_captions:
        script.add_track(TrackType.text, "captions")

    caption_style = TextStyle(bold=True, align=1, auto_wrapping=True)
    timeline_pos = 0

    for cut in cut_list.cuts:
        src_path = input_dir / cut.source_file
        src_start_us = _parse_timestamp(cut.in_)
        src_end_us = _parse_timestamp(cut.out)

        material = VideoMaterial(str(src_path))
        material.crop_settings = _make_crop_settings(cut.crop, material.width, material.height)

        src_end_us = min(src_end_us, material.duration)
        src_duration_us = src_end_us - src_start_us
        target_duration_us = round(src_duration_us / cut.speed)
        src_tr = Timerange(src_start_us, src_duration_us)
        target_tr = Timerange(timeline_pos, target_duration_us)

        seg = VideoSegment(material, target_tr, source_timerange=src_tr, speed=cut.speed)

        if cut.transition_out in {"fade", "dissolve"}:
            seg.add_transition(TransitionType.叠化)

        script.add_segment(seg)

        if cut.caption:
            cap_start = timeline_pos + cut.caption.in_ms * 1000
            cap_duration = (cut.caption.out_ms - cut.caption.in_ms) * 1000
            cap_tr = Timerange(cap_start, cap_duration)
            txt_seg = TextSegment(
                cut.caption.text,
                cap_tr,
                style=caption_style,
                clip_settings=ClipSettings(transform_y=_caption_y(cut.caption.position)),
            )
            script.add_segment(txt_seg, "captions")

        log.info("render_cut", order=cut.order, src=cut.source_file)
        timeline_pos += target_duration_us

    script.save()

    draft_path = draft_parent / folder_name
    capcut_path = _export_to_capcut(draft_path, input_dir, cut_list)
    final_path = capcut_path if capcut_path is not None else draft_path
    log.info("render_done", draft=str(final_path))
    return final_path


def _draft_display_name(restaurant: str) -> str:
    return f"{_PREFIX} - {restaurant}"


def _draft_folder_name(restaurant: str) -> str:
    slug = re.sub(r"[^\w]+", "_", restaurant.lower()).strip("_")
    return f"lasagnastack_{slug}"


def _find_capcut_user_data() -> Path | None:
    """Return the CapCut User Data folder if CapCut is installed, else None."""
    candidate = Path.home() / "Movies" / "CapCut" / "User Data"
    return candidate if candidate.is_dir() else None


def _export_to_capcut(
    draft_path: Path,
    input_dir: Path,
    cut_list: CutList,
) -> Path | None:
    """Copy source clips and draft into CapCut's local drafts directory.

    - Copies each unique source clip into the CapCut draft folder.
    - Rewrites all video "path" entries in draft_content.json to point to
      the copied clips so CapCut opens the draft without missing-media errors.
    - Returns the path of the draft inside CapCut, or None if CapCut was not
      found.

    Args:
        draft_path: Path to the draft folder under output_dir/draft/.
        input_dir: Folder containing the original source clips.
        cut_list: Cut list (used to enumerate unique source files).
    """
    capcut_user_data = _find_capcut_user_data()
    if capcut_user_data is None:
        log.warning("capcut_not_found", searched=str(Path.home() / "Movies" / "CapCut"))
        return None

    capcut_drafts = capcut_user_data / "Projects" / "com.lveditor.draft"
    dest = capcut_drafts / draft_path.name

    # Copy draft folder (draft_content.json + draft_meta_info.json) to CapCut.
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(draft_path, dest)

    # Copy each unique source clip into the CapCut draft folder and build a
    # mapping from the original absolute path to the new one.
    source_files = {cut.source_file for cut in cut_list.cuts}
    path_map: dict[str, str] = {}
    for source_file in source_files:
        src = (input_dir / source_file).resolve()
        clip_dest = dest / source_file
        shutil.copy2(src, clip_dest)
        path_map[str(src)] = str(clip_dest)
        log.info("render_copy_clip", src=str(src), dest=str(clip_dest))

    # Rewrite "path" fields in the copied draft_content.json.
    content_path = dest / "draft_content.json"
    content = json.loads(content_path.read_text(encoding="utf-8"))
    for video in content.get("materials", {}).get("videos", []):
        old = video.get("path", "")
        if old in path_map:
            video["path"] = path_map[old]
    content_path.write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")

    log.info("render_exported_to_capcut", dest=str(dest))
    return dest


def _parse_timestamp(ts: str) -> int:
    """Parse "MM:SS.D" timestamp to microseconds."""
    minutes_str, seconds_str = ts.split(":")
    return int((int(minutes_str) * 60 + float(seconds_str)) * SEC)


def _make_crop_settings(crop: CropHint, src_w: int, src_h: int) -> CropSettings:
    """Compute portrait (9:16) crop rectangle for a given source clip size."""
    target_aspect = 9.0 / 16.0
    crop_w = min(target_aspect / (src_w / src_h), 1.0)

    if crop.mode == "left_third":
        center_x = crop_w / 2
    elif crop.mode == "right_third":
        center_x = 1.0 - crop_w / 2
    else:
        center_x = 0.5

    max_shift = (1.0 - crop_w) / 2
    center_x = max(crop_w / 2, min(1.0 - crop_w / 2, center_x + crop.offset_x * max_shift))

    left = center_x - crop_w / 2
    right = center_x + crop_w / 2
    return CropSettings(
        upper_left_x=left, upper_left_y=0.0,
        upper_right_x=right, upper_right_y=0.0,
        lower_left_x=left, lower_left_y=1.0,
        lower_right_x=right, lower_right_y=1.0,
    )


def _caption_y(position: str) -> float:
    if position == "top":
        return 0.8
    if position in {"center", "middle"}:
        return 0.0
    return -0.8


class RenderStage(Stage):
    def run(self, state: PipelineState) -> PipelineState:
        assert state.cut_list is not None
        draft_path = run(state.cut_list, state.output_dir, state.input_dir)
        return dataclasses.replace(state, draft_path=draft_path)

    def completion_message(self, state: PipelineState) -> str:
        return "Stage 5 complete."
