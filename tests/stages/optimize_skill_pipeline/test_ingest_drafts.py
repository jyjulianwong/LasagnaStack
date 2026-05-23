import pytest

import lasagnastack.stages.optimize_skill_pipeline.ingest_drafts as ingest_drafts_mod
from lasagnastack.optimize_skill_pipeline_state import OptimizeSkillPipelineState
from lasagnastack.stages.optimize_skill_pipeline.ingest_drafts import IngestDraftsStage


def _make_state(tmp_path, brief_path, input_dir=None):
    if input_dir is None:
        input_dir = tmp_path / "trainset"
        input_dir.mkdir(exist_ok=True)
    return OptimizeSkillPipelineState(
        input_dir=input_dir,
        output_dir=tmp_path / "output",
        brief_path=brief_path,
        skill_path=None,
        critique_max_retries=2,
    )


class TestIngestDraftsStage:
    def test_raises_when_no_draft_folders_found(self, tmp_path, brief_path) -> None:
        state = _make_state(tmp_path, brief_path)
        with pytest.raises(ValueError, match="No CapCut draft folders"):
            IngestDraftsStage().run(state)

    def test_raises_when_all_drafts_fail_to_parse(
        self, tmp_path, brief_path, monkeypatch
    ) -> None:
        input_dir = tmp_path / "trainset"
        input_dir.mkdir()
        draft_dir = input_dir / "draft1"
        draft_dir.mkdir()
        (draft_dir / "draft_info.json").touch()

        def _fail(d):
            raise ValueError("bad draft")

        monkeypatch.setattr(ingest_drafts_mod, "parse_draft", _fail)
        state = _make_state(tmp_path, brief_path, input_dir=input_dir)
        with pytest.raises(ValueError, match="All draft folders"):
            IngestDraftsStage().run(state)

    def test_skips_failed_draft_and_keeps_valid_one(
        self,
        tmp_path,
        brief_path,
        monkeypatch,
        fixture_cut_list,
        fixture_reel_style_sheet,
    ) -> None:
        input_dir = tmp_path / "trainset"
        input_dir.mkdir()

        bad_dir = input_dir / "draft_bad"
        bad_dir.mkdir()
        (bad_dir / "draft_info.json").touch()

        good_dir = input_dir / "draft_good"
        good_dir.mkdir()
        (good_dir / "draft_info.json").touch()

        def _parse(d):
            if d == bad_dir:
                raise ValueError("corrupt")
            return (fixture_cut_list, fixture_reel_style_sheet)

        monkeypatch.setattr(ingest_drafts_mod, "parse_draft", _parse)
        state = _make_state(tmp_path, brief_path, input_dir=input_dir)
        result = IngestDraftsStage().run(state)
        assert isinstance(result, OptimizeSkillPipelineState)
        assert len(result.draft_cut_lists) == 1  # pyrefly: ignore[bad-argument-type]

    def test_populates_cut_lists_and_style_sheets(
        self,
        tmp_path,
        brief_path,
        monkeypatch,
        fixture_cut_list,
        fixture_reel_style_sheet,
    ) -> None:
        input_dir = tmp_path / "trainset"
        input_dir.mkdir()
        draft_dir = input_dir / "draft1"
        draft_dir.mkdir()
        (draft_dir / "draft_info.json").touch()

        monkeypatch.setattr(
            ingest_drafts_mod,
            "parse_draft",
            lambda d: (fixture_cut_list, fixture_reel_style_sheet),
        )
        state = _make_state(tmp_path, brief_path, input_dir=input_dir)
        result = IngestDraftsStage().run(state)
        assert result.draft_cut_lists == [  # pyrefly: ignore[missing-attribute]
            fixture_cut_list
        ]
        assert result.draft_reel_style_sheets == [  # pyrefly: ignore[missing-attribute]
            fixture_reel_style_sheet
        ]

    def test_completion_message_shows_count(
        self,
        tmp_path,
        brief_path,
        monkeypatch,
        fixture_cut_list,
        fixture_reel_style_sheet,
    ) -> None:
        input_dir = tmp_path / "trainset"
        input_dir.mkdir()
        for name in ("draft1", "draft2"):
            d = input_dir / name
            d.mkdir()
            (d / "draft_info.json").touch()

        monkeypatch.setattr(
            ingest_drafts_mod,
            "parse_draft",
            lambda d: (fixture_cut_list, fixture_reel_style_sheet),
        )
        state = _make_state(tmp_path, brief_path, input_dir=input_dir)
        result = IngestDraftsStage().run(state)
        msg = IngestDraftsStage().completion_message(result)
        assert "2" in msg

    def test_ignores_files_at_root_level(self, tmp_path, brief_path) -> None:
        """Files (not directories) at the trainset root should be ignored."""
        input_dir = tmp_path / "trainset"
        input_dir.mkdir()
        (input_dir / "draft_info.json").touch()  # file at root, not a subdir

        state = _make_state(tmp_path, brief_path, input_dir=input_dir)
        with pytest.raises(ValueError, match="No CapCut draft folders"):
            IngestDraftsStage().run(state)
