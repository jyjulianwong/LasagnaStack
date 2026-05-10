import dataclasses
import re
from datetime import datetime
from pathlib import Path

import structlog

from lasagnastack import io
from lasagnastack.base import PipelineState, Stage
from lasagnastack.models.cut_list import CutList
from lasagnastack.video_editors.base import VideoEditorAdapter
from lasagnastack.video_editors.pycapcut import PyCapCutAdapter

log = structlog.get_logger()

_PREFIX = "LasagnaStack"
_SEC = 1_000_000


def run(
    cut_list: CutList,
    output_dir: Path,
    input_dir: Path,
    adapter: VideoEditorAdapter | None = None,
) -> Path:
    """Translate the final cut list into a video editor draft folder.

    Uses original source clips (not normalised) for full resolution.
    Delegates draft construction and editor-app export to adapter.

    Args:
        cut_list: Approved cut list from Stage 4.
        output_dir: Pipeline root; draft created at output_dir/draft/.
        input_dir: Folder containing the original source clips.
        adapter: Video editor adapter to use. Defaults to PyCapCutAdapter.

    Returns:
        Path to the draft folder inside the editor app (or output_dir/draft/
        if the editor was not found).
    """
    if adapter is None:
        adapter = PyCapCutAdapter()

    draft_parent = io.draft_dir(output_dir)
    draft_parent.mkdir(parents=True, exist_ok=True)

    title = cut_list.reel_meta.title
    timestamp = _make_timestamp()
    folder_name = _draft_folder_name(title, timestamp)
    display_name = _draft_display_name(title, timestamp)

    draft_path = adapter.build_draft(
        cut_list, draft_parent, folder_name, display_name, input_dir
    )
    capcut_path = adapter.export(draft_path, input_dir, cut_list)
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
    """Return the project display name for a given title and timestamp.

    Args:
        title: Reel title from the cut list.
        timestamp: Timestamp suffix in ``YYYYMMDD_HHMMSS`` format.

    Returns:
        Display name string, e.g. ``"LasagnaStack - Hana Don 20260508_200844"``.
    """
    return f"{_PREFIX} - {_sanitise_title(title)} {timestamp}"


def _draft_folder_name(title: str, timestamp: str) -> str:
    """Return the draft folder name for a given title and timestamp.

    The folder name is kept identical to the display name so the editor shows
    the same label in both the file system and its project list.

    Args:
        title: Reel title from the cut list.
        timestamp: Timestamp suffix in ``YYYYMMDD_HHMMSS`` format.

    Returns:
        Folder name string, e.g. ``"LasagnaStack - Hana Don 20260508_200844"``.
    """
    return _draft_display_name(title, timestamp)


def _parse_timestamp(ts: str) -> int:
    """Parse "MM:SS.D" timestamp to microseconds.

    Args:
        ts: Timestamp string in ``MM:SS.D`` format.

    Returns:
        Duration in microseconds.
    """
    minutes_str, seconds_str = ts.split(":")
    return int((int(minutes_str) * 60 + float(seconds_str)) * _SEC)


class RenderStage(Stage):
    """Stage 5: translate the approved cut list into a video editor draft."""

    def __init__(self, adapter: VideoEditorAdapter | None = None) -> None:
        """Initialise with an optional video editor adapter.

        Args:
            adapter: Adapter used to build and export the draft. Defaults to
                ``PyCapCutAdapter`` when ``None``.
        """
        self._adapter = adapter

    def run(self, state: PipelineState) -> PipelineState:
        """Run the render stage.

        Args:
            state: Current pipeline state. ``state.cut_list`` must be set.

        Returns:
            Updated pipeline state with ``draft_path`` set.
        """
        assert state.cut_list is not None
        draft_path = run(
            state.cut_list, state.output_dir, state.input_dir, adapter=self._adapter
        )
        return dataclasses.replace(state, draft_path=draft_path)

    def completion_message(self, state: PipelineState) -> str:
        """Return the post-stage confirmation message.

        Args:
            state: Current pipeline state.

        Returns:
            Human-readable completion string.
        """
        return "Stage 5 complete."
