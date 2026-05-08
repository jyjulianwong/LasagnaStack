import dataclasses
import json
import platform as _sys_platform
import re
import shutil
import time
from datetime import datetime
from pathlib import Path

import pymediainfo as _pymediainfo
import structlog
from pycapcut import (
    SEC,
    ClipSettings,
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
_VIDEO_EXTENSIONS = {".mp4", ".mov"}


def run(cut_list: CutList, output_dir: Path, input_dir: Path) -> Path:
    """Translate the final cut list into a pyCapCut draft folder.

    Uses original source clips (not normalised) for full resolution.
    Draft written to output_dir/draft/<reel_name>/, then copied into
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

    title = cut_list.reel_meta.title
    timestamp = _make_timestamp()
    folder_name = _draft_folder_name(title, timestamp)
    display_name = _draft_display_name(title, timestamp)
    script = DraftFolder(str(draft_parent)).create_draft(
        folder_name, _DRAFT_WIDTH, _DRAFT_HEIGHT, _DRAFT_FPS, allow_replace=True
    )
    # CapCut 8.x expects draft_info.json; pyCapCut defaults to draft_content.json.
    script.save_path = str(draft_parent / folder_name / "draft_info.json")
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
        # Use display dimensions (post-rotation) for crop math and CapCut's
        # bounding box.  iPhone videos are stored as landscape with a 90°
        # rotation flag; pymediainfo returns the encoded dimensions, so we
        # swap width/height for rotated clips.
        disp_w, disp_h = _display_dimensions(src_path)
        if (disp_w, disp_h) != (material.width, material.height):
            material.width, material.height = disp_w, disp_h
        clip_settings = _make_clip_settings(
            cut.crop, disp_w, disp_h, _DRAFT_WIDTH, _DRAFT_HEIGHT
        )

        src_end_us = min(src_end_us, material.duration)
        src_duration_us = src_end_us - src_start_us
        target_duration_us = round(src_duration_us / cut.speed)
        src_tr = Timerange(src_start_us, src_duration_us)
        target_tr = Timerange(timeline_pos, target_duration_us)

        seg = VideoSegment(
            material,
            target_tr,
            source_timerange=src_tr,
            speed=cut.speed,
            clip_settings=clip_settings,
        )

        if cut.transition_out in {"fade", "dissolve"}:
            seg.add_transition(TransitionType.叠化)

        script.add_segment(seg)

        if cut.caption:
            cap_start = timeline_pos + cut.caption.in_ms * 1000
            cap_end = min(
                timeline_pos + cut.caption.out_ms * 1000,
                timeline_pos + target_duration_us,
            )
            cap_duration = cap_end - cap_start
            cap_tr = Timerange(cap_start, cap_duration)
            txt_seg = TextSegment(
                cut.caption.text,
                cap_tr,
                style=caption_style,
                clip_settings=ClipSettings(
                    transform_y=_caption_y(cut.caption.position)
                ),
            )
            script.add_segment(txt_seg, "captions")

        log.info("render_cut", order=cut.order, src=cut.source_file)
        timeline_pos += target_duration_us

    script.save()
    _patch_platform(draft_parent / folder_name / "draft_info.json")

    draft_path = draft_parent / folder_name
    capcut_path = _export_to_capcut(draft_path, input_dir, cut_list)
    final_path = capcut_path if capcut_path is not None else draft_path
    log.info("render_done", draft=str(final_path))
    return final_path


def _sanitise_title(title: str) -> str:
    """Remove special characters from a title, normalising whitespace.

    Keeps alphanumeric characters (including Unicode letters), spaces,
    hyphens, and underscores. Collapses consecutive whitespace to a single
    space so that removed characters do not leave double spaces behind.

    Args:
        title: Raw title string, e.g. from the creator brief.

    Returns:
        Sanitised title safe for use in file and folder names.
    """
    sanitised = re.sub(r"[^\w\s\-]", "", title)
    return re.sub(r"\s+", " ", sanitised).strip()


def _make_timestamp() -> str:
    """Return the current local time as a ``YYYYMMDD_HHMMSS`` string.

    Returns:
        Timestamp string, e.g. ``"20260508_200844"``.
    """
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _draft_display_name(title: str, timestamp: str) -> str:
    """Return the CapCut project display name for a given title and timestamp.

    Args:
        title: Reel title from the cut list.
        timestamp: Timestamp suffix in ``YYYYMMDD_HHMMSS`` format.

    Returns:
        Display name string, e.g. ``"LasagnaStack - Hana Don 20260508_200844"``.
    """
    return f"{_PREFIX} - {_sanitise_title(title)} {timestamp}"


def _draft_folder_name(title: str, timestamp: str) -> str:
    """Return the draft folder name for a given title and timestamp.

    The folder name is kept identical to the display name so CapCut shows
    the same label in both the file system and its project list.

    Args:
        title: Reel title from the cut list.
        timestamp: Timestamp suffix in ``YYYYMMDD_HHMMSS`` format.

    Returns:
        Folder name string, e.g. ``"LasagnaStack - Hana Don 20260508_200844"``.
    """
    return _draft_display_name(title, timestamp)


def _display_dimensions(path: Path) -> tuple[int, int]:
    """Return the display (post-rotation) width and height of a video.

    iPhone videos are encoded as landscape with a 90° or 270° rotation flag.
    pymediainfo exposes the encoded dimensions; this function swaps them when
    the rotation metadata indicates the frame should be shown portrait.
    """
    info = _pymediainfo.MediaInfo.parse(
        str(path), mediainfo_options={"File_TestContinuousFileNames": "0"}
    )
    if not info.video_tracks:
        return 0, 0
    track = info.video_tracks[0]
    w, h = int(track.width), int(track.height)
    try:
        rotation = float(track.rotation or 0) % 360
    except (TypeError, ValueError):
        rotation = 0.0
    if rotation in (90.0, 270.0):
        return h, w
    return w, h


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

    # Copy every video file from input_dir into the CapCut draft folder.
    # Timeline clips (those in the cut list) are also mapped so their paths
    # can be rewritten in draft_info.json.  Extra clips (not yet on the
    # timeline) are copied so they appear in CapCut's import panel.
    path_map: dict[str, str] = {}
    for video_file in input_dir.iterdir():
        if video_file.is_file() and video_file.suffix.lower() in _VIDEO_EXTENSIONS:
            src = video_file.resolve()
            clip_dest = dest / video_file.name
            shutil.copy2(src, clip_dest)
            path_map[str(src)] = str(clip_dest)
            log.info("render_copy_clip", src=str(src), dest=str(clip_dest))

    # Rewrite "path" fields in the copied draft_info.json.
    content_path = dest / "draft_info.json"
    content = json.loads(content_path.read_text(encoding="utf-8"))
    for video in content.get("materials", {}).get("videos", []):
        old = video.get("path", "")
        if old in path_map:
            video["path"] = path_map[old]
    content_path.write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")

    # Update draft_meta_info.json with correct paths and display name.
    _update_draft_meta_info(dest, capcut_drafts)

    # Register draft in root_meta_info.json so CapCut lists it immediately.
    _update_root_meta_info(capcut_drafts, dest, cut_list)

    log.info("render_exported_to_capcut", dest=str(dest))
    return dest


def _patch_platform(content_path: Path) -> None:
    """Fix the platform/OS fields in draft_info.json (pyCapCut template targets Windows)."""
    content = json.loads(content_path.read_text(encoding="utf-8"))
    mac_ver = _sys_platform.mac_ver()[0] or "15.0.0"
    info = {
        "os": "mac",
        "os_version": mac_ver,
        "app_id": 359289,
        "app_version": "8.5.0",
        "app_source": "cc",
        "device_id": "",
        "hard_disk_id": "",
        "mac_address": "",
    }
    content["platform"] = info
    content["last_modified_platform"] = info
    content_path.write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")


def _update_draft_meta_info(dest: Path, capcut_drafts: Path) -> None:
    """Fill in fold/root paths, display name, and import-panel materials in draft_meta_info.json."""
    meta_path = dest / "draft_meta_info.json"
    if not meta_path.exists():
        return
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["draft_fold_path"] = str(dest)
    meta["draft_root_path"] = str(capcut_drafts)
    meta["draft_name"] = dest.name

    # Populate draft_materials so clips appear in CapCut's import panel.
    content = json.loads((dest / "draft_info.json").read_text(encoding="utf-8"))
    now_sec = int(time.time())
    now_us = now_sec * 1_000_000
    seen_paths: set[str] = set()
    material_entries = []
    for vid in content.get("materials", {}).get("videos", []):
        file_path = vid.get("path", "")
        if file_path in seen_paths:
            continue
        seen_paths.add(file_path)
        duration = vid.get("duration", 0)
        material_entries.append(
            {
                "ai_group_type": "",
                "create_time": now_sec,
                "duration": duration,
                "enter_from": 0,
                "extra_info": Path(file_path).name if file_path else "",
                "file_Path": file_path,
                "height": vid.get("height", 0),
                "id": vid.get("id", ""),
                "import_time": now_sec,
                "import_time_ms": now_us,
                "item_source": 1,
                "md5": "",
                "metetype": "video",
                "roughcut_time_range": {"duration": duration, "start": 0},
                "sub_time_range": {"duration": -1, "start": -1},
                "type": 0,
                "width": vid.get("width", 0),
            }
        )
    # Also add clips that were copied to dest but are not on the timeline.
    for extra_file in dest.iterdir():
        if not (
            extra_file.is_file() and extra_file.suffix.lower() in _VIDEO_EXTENSIONS
        ):
            continue
        file_path = str(extra_file)
        if file_path in seen_paths:
            continue
        seen_paths.add(file_path)
        info = _pymediainfo.MediaInfo.parse(
            file_path, mediainfo_options={"File_TestContinuousFileNames": "0"}
        )
        if not info.video_tracks:
            continue
        track = info.video_tracks[0]
        w, h = int(track.width), int(track.height)
        try:
            rotation = float(track.rotation or 0) % 360
        except (TypeError, ValueError):
            rotation = 0.0
        if rotation in (90.0, 270.0):
            w, h = h, w
        duration = int(float(track.duration or 0) * 1_000)
        material_entries.append(
            {
                "ai_group_type": "",
                "create_time": now_sec,
                "duration": duration,
                "enter_from": 0,
                "extra_info": extra_file.name,
                "file_Path": file_path,
                "height": h,
                "id": "",
                "import_time": now_sec,
                "import_time_ms": now_us,
                "item_source": 1,
                "md5": "",
                "metetype": "video",
                "roughcut_time_range": {"duration": duration, "start": 0},
                "sub_time_range": {"duration": -1, "start": -1},
                "type": 0,
                "width": w,
            }
        )

    for dm in meta.get("draft_materials", []):
        if dm.get("type") == 0:
            dm["value"] = material_entries
            break

    meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")


def _update_root_meta_info(capcut_drafts: Path, dest: Path, cut_list: CutList) -> None:
    """Add or replace our draft entry in root_meta_info.json."""
    root_meta_path = capcut_drafts / "root_meta_info.json"
    if not root_meta_path.exists():
        return

    meta_path = dest / "draft_meta_info.json"
    draft_id = ""
    if meta_path.exists():
        draft_id = json.loads(meta_path.read_text(encoding="utf-8")).get("draft_id", "")

    root = json.loads(root_meta_path.read_text(encoding="utf-8"))
    store: list = root.setdefault("all_draft_store", [])

    entry = {
        "cloud_draft_cover": False,
        "cloud_draft_sync": False,
        "draft_cloud_last_action_download": False,
        "draft_cloud_purchase_info": "",
        "draft_cloud_template_id": "",
        "draft_cloud_tutorial_info": "",
        "draft_cloud_videocut_purchase_info": "",
        "draft_cover": "",
        "draft_fold_path": str(dest),
        "draft_id": draft_id,
        "draft_is_ai_shorts": False,
        "draft_is_cloud_temp_draft": False,
        "draft_is_invisible": False,
        "draft_is_web_article_video": False,
        "draft_json_file": str(dest / "draft_info.json"),
        "draft_name": dest.name,
        "draft_new_version": "",
        "draft_root_path": str(capcut_drafts),
        "draft_timeline_materials_size": 0,
        "draft_type": "",
        "draft_web_article_video_enter_from": "",
        "streaming_edit_draft_ready": True,
        "tm_draft_cloud_completed": "",
        "tm_draft_cloud_entry_id": -1,
        "tm_draft_cloud_modified": 0,
        "tm_draft_cloud_parent_entry_id": -1,
        "tm_draft_cloud_space_id": -1,
        "tm_draft_cloud_user_id": -1,
        "tm_draft_create": int(time.time() * 1_000_000),
        "tm_draft_modified": int(time.time() * 1_000_000),
        "tm_draft_removed": 0,
        "tm_duration": 0,
    }

    # Replace any existing entry for this folder (handles re-runs and renames).
    store[:] = [e for e in store if e.get("draft_fold_path") != str(dest)]
    store.insert(0, entry)
    root_meta_path.write_text(json.dumps(root, ensure_ascii=False), encoding="utf-8")


def _parse_timestamp(ts: str) -> int:
    """Parse "MM:SS.D" timestamp to microseconds."""
    minutes_str, seconds_str = ts.split(":")
    return int((int(minutes_str) * 60 + float(seconds_str)) * SEC)


def _make_clip_settings(
    crop: CropHint, src_w: int, src_h: int, canvas_w: int, canvas_h: int
) -> ClipSettings:
    """Compute a ClipSettings that pans to the desired horizontal third.

    At scale=1.0, CapCut scales the source to cover the canvas height. For
    landscape sources this overflows the canvas width; transform_x pans within
    that overflow to select the left, center, or right region.
    """
    src_aspect = src_w / src_h
    canvas_aspect = canvas_w / canvas_h
    if src_aspect <= canvas_aspect:
        # Portrait or matching source: fills by width, no horizontal pan needed.
        return ClipSettings()

    # Landscape source on portrait canvas: scale=1.0 covers canvas height.
    scaled_w = src_w * (canvas_h / src_h)
    overflow_px = scaled_w - canvas_w
    max_shift = (overflow_px / 2) / (canvas_w / 2)  # in transform_x units

    if crop.mode == "left_third":
        base = max_shift  # shift video right → see left portion
    elif crop.mode == "right_third":
        base = -max_shift  # shift video left → see right portion
    else:
        base = 0.0

    shift = base + crop.offset_x * max_shift
    shift = max(-max_shift, min(max_shift, shift))
    return ClipSettings(transform_x=shift)


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
