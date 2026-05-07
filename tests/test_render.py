import json

import pytest
from pycapcut import SEC

from lasagnastack import io
from lasagnastack.models.cut_list import Caption, CropHint, Cut, CutList, ReelMeta
from lasagnastack.stages import render
from tests.conftest import FIXTURE_CUT_LIST, FIXTURE_CUT


class TestDraftNaming:
    def test_display_name_has_prefix(self):
        assert render._draft_display_name("Hana Don") == "LasagnaStack - Hana Don"

    def test_folder_name_is_lowercase_slug(self):
        assert render._draft_folder_name("Hana Don") == "lasagnastack_hana_don"

    def test_folder_name_collapses_spaces(self):
        assert render._draft_folder_name("Test  Kitchen") == "lasagnastack_test_kitchen"

    def test_folder_name_strips_special_chars(self):
        # \w keeps Unicode letters (é stays), only punctuation/spaces become _
        assert render._draft_folder_name("Café & Bar") == "lasagnastack_café_bar"

    def test_folder_name_prefix(self):
        assert render._draft_folder_name("X").startswith("lasagnastack_")


class TestParseTimestamp:
    def test_zero(self):
        assert render._parse_timestamp("00:00.0") == 0

    def test_seconds(self):
        assert render._parse_timestamp("00:02.5") == 2_500_000

    def test_whole_seconds(self):
        assert render._parse_timestamp("00:05.0") == 5 * SEC

    def test_minutes(self):
        assert render._parse_timestamp("01:30.0") == 90 * SEC

    def test_minutes_and_seconds(self):
        assert render._parse_timestamp("01:05.5") == int(65.5 * SEC)


class TestMakeCropSettings:
    def test_landscape_center_is_symmetric(self):
        crop = CropHint(mode="center", offset_x=0.0)
        s = render._make_crop_settings(crop, 1920, 1080)
        assert s.upper_left_x == pytest.approx(1.0 - s.upper_right_x)

    def test_landscape_left_third_starts_at_zero(self):
        crop = CropHint(mode="left_third", offset_x=0.0)
        s = render._make_crop_settings(crop, 1920, 1080)
        assert s.upper_left_x == pytest.approx(0.0)

    def test_landscape_right_third_ends_at_one(self):
        crop = CropHint(mode="right_third", offset_x=0.0)
        s = render._make_crop_settings(crop, 1920, 1080)
        assert s.upper_right_x == pytest.approx(1.0)

    def test_portrait_source_no_crop(self):
        crop = CropHint(mode="center", offset_x=0.0)
        s = render._make_crop_settings(crop, 1080, 1920)
        assert s.upper_left_x == pytest.approx(0.0)
        assert s.upper_right_x == pytest.approx(1.0)

    def test_top_bottom_unchanged(self):
        crop = CropHint(mode="center", offset_x=0.0)
        s = render._make_crop_settings(crop, 1920, 1080)
        assert s.upper_left_y == 0.0
        assert s.lower_left_y == 1.0

    def test_offset_shifts_center(self):
        base = render._make_crop_settings(CropHint(mode="center", offset_x=0.0), 1920, 1080)
        shifted = render._make_crop_settings(CropHint(mode="center", offset_x=0.5), 1920, 1080)
        assert shifted.upper_left_x > base.upper_left_x


@pytest.fixture(autouse=True)
def no_capcut(monkeypatch):
    """Disable live CapCut detection for all render tests."""
    monkeypatch.setattr(render, "_find_capcut_user_data", lambda: None)


class TestRun:
    def test_creates_draft_folder(self, raw_clip, tmp_path):
        result = render.run(FIXTURE_CUT_LIST, tmp_path, raw_clip.parent)
        assert result.exists()
        assert result.is_dir()

    def test_returns_path_under_draft_dir(self, raw_clip, tmp_path):
        result = render.run(FIXTURE_CUT_LIST, tmp_path, raw_clip.parent)
        assert result.parent == io.draft_dir(tmp_path)

    def test_draft_contains_content_json(self, raw_clip, tmp_path):
        result = render.run(FIXTURE_CUT_LIST, tmp_path, raw_clip.parent)
        assert (result / "draft_content.json").exists()

    def test_draft_folder_name_is_slug(self, raw_clip, tmp_path):
        result = render.run(FIXTURE_CUT_LIST, tmp_path, raw_clip.parent)
        expected = render._draft_folder_name(FIXTURE_CUT_LIST.reel_meta.restaurant)
        assert result.name == expected

    def test_draft_content_json_has_display_name(self, raw_clip, tmp_path):
        result = render.run(FIXTURE_CUT_LIST, tmp_path, raw_clip.parent)
        content = json.loads((result / "draft_content.json").read_text())
        expected = render._draft_display_name(FIXTURE_CUT_LIST.reel_meta.restaurant)
        assert content["name"] == expected

    def test_allow_replace_overwrites_existing(self, raw_clip, tmp_path):
        render.run(FIXTURE_CUT_LIST, tmp_path, raw_clip.parent)
        render.run(FIXTURE_CUT_LIST, tmp_path, raw_clip.parent)  # second call must not raise

    def test_cut_with_caption(self, raw_clip, tmp_path):
        cut_with_caption = FIXTURE_CUT.model_copy(
            update={
                "caption": Caption(
                    text="Lovely dish",
                    style="bold",
                    position="bottom",
                    in_ms=0,
                    out_ms=2500,
                )
            }
        )
        cut_list = FIXTURE_CUT_LIST.model_copy(update={"cuts": [cut_with_caption]})
        result = render.run(cut_list, tmp_path, raw_clip.parent)
        assert result.exists()

    def test_cut_with_fade_transition(self, raw_clip, tmp_path):
        cut_with_fade = FIXTURE_CUT.model_copy(update={"transition_out": "fade"})
        cut_list = FIXTURE_CUT_LIST.model_copy(update={"cuts": [cut_with_fade]})
        result = render.run(cut_list, tmp_path, raw_clip.parent)
        assert result.exists()

    def test_returns_output_path_when_capcut_absent(self, raw_clip, tmp_path, monkeypatch):
        monkeypatch.setattr(render, "_find_capcut_user_data", lambda: None)
        result = render.run(FIXTURE_CUT_LIST, tmp_path, raw_clip.parent)
        assert result.parent == io.draft_dir(tmp_path)

    def test_returns_capcut_path_when_capcut_present(self, raw_clip, tmp_path, monkeypatch):
        fake_capcut = tmp_path / "CapCut" / "User Data"
        (fake_capcut / "Projects" / "com.lveditor.draft").mkdir(parents=True)
        monkeypatch.setattr(render, "_find_capcut_user_data", lambda: fake_capcut)
        result = render.run(FIXTURE_CUT_LIST, tmp_path, raw_clip.parent)
        capcut_drafts = fake_capcut / "Projects" / "com.lveditor.draft"
        assert result.parent == capcut_drafts


class TestExportToCapCut:
    def _make_draft(self, raw_clip, tmp_path):
        """Build a minimal draft folder and return (draft_path, input_dir)."""
        monkeypatch_target = None  # unused helper — just call run() with no CapCut
        render.run.__wrapped__ = None  # ensure no stale state
        draft_parent = io.draft_dir(tmp_path / "out")
        draft_parent.mkdir(parents=True, exist_ok=True)
        # Build the draft using render.run with CapCut disabled
        return None  # not used directly; tests call _export_to_capcut

    def test_clips_copied_into_capcut_draft(self, raw_clip, tmp_path):
        fake_capcut = tmp_path / "CapCut" / "User Data"
        capcut_drafts = fake_capcut / "Projects" / "com.lveditor.draft"
        capcut_drafts.mkdir(parents=True)

        # Build the draft without exporting to CapCut
        import unittest.mock as mock
        with mock.patch.object(render, "_find_capcut_user_data", return_value=None):
            draft_path = render.run(FIXTURE_CUT_LIST, tmp_path / "out", raw_clip.parent)

        render._export_to_capcut(draft_path, raw_clip.parent, FIXTURE_CUT_LIST)

        # Monkeypatch doesn't apply to _export_to_capcut directly, so call with fake capcut
        with mock.patch.object(render, "_find_capcut_user_data", return_value=fake_capcut):
            dest = render._export_to_capcut(draft_path, raw_clip.parent, FIXTURE_CUT_LIST)

        assert dest is not None
        assert (dest / FIXTURE_CUT.source_file).exists()

    def test_paths_rewritten_in_content_json(self, raw_clip, tmp_path):
        fake_capcut = tmp_path / "CapCut" / "User Data"
        capcut_drafts = fake_capcut / "Projects" / "com.lveditor.draft"
        capcut_drafts.mkdir(parents=True)

        import unittest.mock as mock
        with mock.patch.object(render, "_find_capcut_user_data", return_value=None):
            draft_path = render.run(FIXTURE_CUT_LIST, tmp_path / "out", raw_clip.parent)

        with mock.patch.object(render, "_find_capcut_user_data", return_value=fake_capcut):
            dest = render._export_to_capcut(draft_path, raw_clip.parent, FIXTURE_CUT_LIST)

        assert dest is not None
        content = json.loads((dest / "draft_content.json").read_text())
        paths = [v["path"] for v in content["materials"]["videos"]]
        assert all(p.startswith(str(dest)) for p in paths)

    def test_returns_none_when_capcut_absent(self, raw_clip, tmp_path):
        import unittest.mock as mock
        with mock.patch.object(render, "_find_capcut_user_data", return_value=None):
            draft_path = render.run(FIXTURE_CUT_LIST, tmp_path / "out", raw_clip.parent)
            result = render._export_to_capcut(draft_path, raw_clip.parent, FIXTURE_CUT_LIST)
        assert result is None

    def test_overwrites_existing_capcut_draft(self, raw_clip, tmp_path):
        fake_capcut = tmp_path / "CapCut" / "User Data"
        capcut_drafts = fake_capcut / "Projects" / "com.lveditor.draft"
        capcut_drafts.mkdir(parents=True)

        import unittest.mock as mock
        with mock.patch.object(render, "_find_capcut_user_data", return_value=None):
            draft_path = render.run(FIXTURE_CUT_LIST, tmp_path / "out", raw_clip.parent)

        with mock.patch.object(render, "_find_capcut_user_data", return_value=fake_capcut):
            render._export_to_capcut(draft_path, raw_clip.parent, FIXTURE_CUT_LIST)
            dest = render._export_to_capcut(draft_path, raw_clip.parent, FIXTURE_CUT_LIST)

        assert dest is not None and dest.exists()
