"""Stage 1 of the optimize-skill pipeline: ingest CapCut drafts from a trainset folder."""

import dataclasses

import structlog

from lasagnastack.base import PipelineState, Stage
from lasagnastack.optimize_skill_pipeline_state import OptimizeSkillPipelineState
from lasagnastack.video_editor_processors.pycapcut_inverter import parse_draft

log = structlog.get_logger()


class IngestDraftsStage(Stage):
    """Scan the trainset directory and parse each CapCut draft into a CutList + ReelStyleSheet."""

    def run(self, state: PipelineState) -> PipelineState:
        """Walk ``state.input_dir`` for subdirectories containing ``draft_info.json``.

        Args:
            state: Pipeline state; ``input_dir`` must point at the trainset root.

        Returns:
            Updated state with ``draft_cut_lists`` and ``draft_reel_style_sheets`` populated.

        Raises:
            ValueError: If no valid draft folders are found.
        """
        assert isinstance(state, OptimizeSkillPipelineState)
        draft_dirs = sorted(
            p
            for p in state.input_dir.iterdir()
            if p.is_dir() and (p / "draft_info.json").exists()
        )

        if not draft_dirs:
            raise ValueError(
                f"No CapCut draft folders found in {state.input_dir}. "
                "Each subfolder must contain a draft_info.json file."
            )

        cut_lists = []
        reel_style_sheets = []

        for draft_dir in draft_dirs:
            log.info("ingest_drafts_parsing", draft=draft_dir.name)
            try:
                cut_list, reel_style_sheet = parse_draft(draft_dir)
                cut_lists.append(cut_list)
                reel_style_sheets.append(reel_style_sheet)
            except Exception as exc:
                log.warning(
                    "ingest_drafts_skipped",
                    draft=draft_dir.name,
                    error=str(exc),
                )

        if not cut_lists:
            raise ValueError(f"All draft folders in {state.input_dir} failed to parse.")

        log.info("ingest_drafts_done", count=len(cut_lists))
        return dataclasses.replace(
            state,
            draft_cut_lists=cut_lists,
            draft_reel_style_sheets=reel_style_sheets,
        )

    def completion_message(self, state: PipelineState) -> str:
        assert isinstance(state, OptimizeSkillPipelineState)
        n = len(state.draft_cut_lists or [])
        return (
            f"Stage 1 complete — parsed {n} draft(s). "
            "Continue to Stage 2 (optimize skill)?"
        )
