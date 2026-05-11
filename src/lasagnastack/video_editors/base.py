from abc import ABC, abstractmethod
from pathlib import Path

from lasagnastack.models.cut_list import CutList
from lasagnastack.models.enhance import ReelStyle


class VideoEditorAdapter(ABC):
    """Interface for translating a cut list into a video editor draft project."""

    @abstractmethod
    def build_draft(
        self,
        cut_list: CutList,
        draft_parent: Path,
        folder_name: str,
        display_name: str,
        input_dir: Path,
        reel_style: ReelStyle | None = None,
    ) -> Path:
        """Translate cut_list into a draft project at draft_parent/folder_name.

        Args:
            cut_list: Approved cut list from Stage 4.
            draft_parent: Directory that will contain the new draft subfolder.
            folder_name: Name for the new draft subfolder.
            display_name: Human-readable project name written into the draft.
            input_dir: Folder containing original source clips.
            reel_style: Optional visual styling from Stage 5.

        Returns:
            Path to the created draft folder.
        """
        ...

    @abstractmethod
    def export(
        self,
        draft_path: Path,
        input_dir: Path,
        cut_list: CutList,
    ) -> Path | None:
        """Export the draft into the editor's native project directory.

        Args:
            draft_path: Path to the locally-built draft folder.
            input_dir: Folder containing original source clips.
            cut_list: Cut list (used to enumerate unique source files).

        Returns:
            Path to the draft inside the editor app, or None if not installed.
        """
        ...
