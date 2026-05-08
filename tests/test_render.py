import json
import unittest.mock as mock

import pytest
from pycapcut import SEC

from lasagnastack import io
from lasagnastack.models.cut_list import Caption, CropHint
from lasagnastack.stages import render


class TestDraftNaming:
    def test_display_name_has_prefix(self):
        assert render._draft_display_name("Hana Don") == "LasagnaStack - Hana Don"

    def test_folder_name_matches_display_name(self):
        assert render._draft_folder_name("Hana Don") == "LasagnaStack - Hana Don"

    def test_folder_name_preserves_spaces(self):
        assert (
            render._draft_folder_name("Test  Kitchen") == "LasagnaStack - Test  Kitchen"
        )

    def test_folder_name_preserves_special_chars(self):
        assert render._draft_folder_name("Café & Bar") == "LasagnaStack - Café & Bar"

    def test_folder_name_prefix(self):
        assert render._draft_folder_name("X").startswith("LasagnaStack - ")


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


class TestMakeClipSettings:
    def test_landscape_center_no_shift(self):
        clip = render._make_clip_settings(
            CropHint(mode="center", offset_x=0.0), 1920, 1080, 1080, 1920
        )
        assert clip.transform_x == pytest.approx(0.0)

    def test_landscape_left_third_positive_shift(self):
        clip = render._make_clip_settings(
            CropHint(mode="left_third", offset_x=0.0), 1920, 1080, 1080, 1920
        )
        assert clip.transform_x > 0.0

    def test_landscape_right_third_negative_shift(self):
        clip = render._make_clip_settings(
            CropHint(mode="right_third", offset_x=0.0), 1920, 1080, 1080, 1920
        )
        assert clip.transform_x < 0.0

    def test_left_and_right_are_symmetric(self):
        left = render._make_clip_settings(
            CropHint(mode="left_third", offset_x=0.0), 1920, 1080, 1080, 1920
        )
        right = render._make_clip_settings(
            CropHint(mode="right_third", offset_x=0.0), 1920, 1080, 1080, 1920
        )
        assert left.transform_x == pytest.approx(-right.transform_x)

    def test_portrait_source_no_shift(self):
        clip = render._make_clip_settings(
            CropHint(mode="center", offset_x=0.0), 1080, 1920, 1080, 1920
        )
        assert clip.transform_x == pytest.approx(0.0)

    def test_offset_shifts_center(self):
        base = render._make_clip_settings(
            CropHint(mode="center", offset_x=0.0), 1920, 1080, 1080, 1920
        )
        shifted = render._make_clip_settings(
            CropHint(mode="center", offset_x=0.5), 1920, 1080, 1080, 1920
        )
        assert shifted.transform_x > base.transform_x


@pytest.fixture(autouse=True)
def no_capcut(monkeypatch):
    """Disable live CapCut detection for all render tests."""
    monkeypatch.setattr(render, "_find_capcut_user_data", lambda: None)


class TestRun:
    def test_creates_draft_folder(self, raw_clip, tmp_path, fixture_cut_list):
        result = render.run(fixture_cut_list, tmp_path, raw_clip.parent)
        assert result.exists()
        assert result.is_dir()

    def test_returns_path_under_draft_dir(self, raw_clip, tmp_path, fixture_cut_list):
        result = render.run(fixture_cut_list, tmp_path, raw_clip.parent)
        assert result.parent == io.draft_dir(tmp_path)

    def test_draft_contains_info_json(self, raw_clip, tmp_path, fixture_cut_list):
        result = render.run(fixture_cut_list, tmp_path, raw_clip.parent)
        assert (result / "draft_info.json").exists()

    def test_draft_folder_name_is_display_name(
        self, raw_clip, tmp_path, fixture_cut_list
    ):
        result = render.run(fixture_cut_list, tmp_path, raw_clip.parent)
        expected = render._draft_folder_name(fixture_cut_list.reel_meta.restaurant)
        assert result.name == expected

    def test_draft_info_json_has_display_name(
        self, raw_clip, tmp_path, fixture_cut_list
    ):
        result = render.run(fixture_cut_list, tmp_path, raw_clip.parent)
        content = json.loads((result / "draft_info.json").read_text())
        expected = render._draft_display_name(fixture_cut_list.reel_meta.restaurant)
        assert content["name"] == expected

    def test_allow_replace_overwrites_existing(
        self, raw_clip, tmp_path, fixture_cut_list
    ):
        render.run(fixture_cut_list, tmp_path, raw_clip.parent)
        render.run(
            fixture_cut_list, tmp_path, raw_clip.parent
        )  # second call must not raise

    def test_cut_with_caption(self, raw_clip, tmp_path, fixture_cut, fixture_cut_list):
        cut_with_caption = fixture_cut.model_copy(
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
        cut_list = fixture_cut_list.model_copy(update={"cuts": [cut_with_caption]})
        result = render.run(cut_list, tmp_path, raw_clip.parent)
        assert result.exists()

    def test_cut_with_fade_transition(
        self, raw_clip, tmp_path, fixture_cut, fixture_cut_list
    ):
        cut_with_fade = fixture_cut.model_copy(update={"transition_out": "fade"})
        cut_list = fixture_cut_list.model_copy(update={"cuts": [cut_with_fade]})
        result = render.run(cut_list, tmp_path, raw_clip.parent)
        assert result.exists()

    def test_returns_output_path_when_capcut_absent(
        self, raw_clip, tmp_path, monkeypatch, fixture_cut_list
    ):
        monkeypatch.setattr(render, "_find_capcut_user_data", lambda: None)
        result = render.run(fixture_cut_list, tmp_path, raw_clip.parent)
        assert result.parent == io.draft_dir(tmp_path)

    def test_returns_capcut_path_when_capcut_present(
        self, raw_clip, tmp_path, monkeypatch, fixture_cut_list
    ):
        fake_capcut = tmp_path / "CapCut" / "User Data"
        (fake_capcut / "Projects" / "com.lveditor.draft").mkdir(parents=True)
        monkeypatch.setattr(render, "_find_capcut_user_data", lambda: fake_capcut)
        result = render.run(fixture_cut_list, tmp_path, raw_clip.parent)
        capcut_drafts = fake_capcut / "Projects" / "com.lveditor.draft"
        assert result.parent == capcut_drafts


class TestExportToCapCut:
    def test_clips_copied_into_capcut_draft(
        self, raw_clip, tmp_path, fixture_cut_list, fixture_cut
    ):
        fake_capcut = tmp_path / "CapCut" / "User Data"
        capcut_drafts = fake_capcut / "Projects" / "com.lveditor.draft"
        capcut_drafts.mkdir(parents=True)

        with mock.patch.object(render, "_find_capcut_user_data", return_value=None):
            draft_path = render.run(fixture_cut_list, tmp_path / "out", raw_clip.parent)

        render._export_to_capcut(draft_path, raw_clip.parent, fixture_cut_list)

        with mock.patch.object(
            render, "_find_capcut_user_data", return_value=fake_capcut
        ):
            dest = render._export_to_capcut(
                draft_path, raw_clip.parent, fixture_cut_list
            )

        assert dest is not None
        assert (dest / fixture_cut.source_file).exists()

    def test_paths_rewritten_in_info_json(self, raw_clip, tmp_path, fixture_cut_list):
        fake_capcut = tmp_path / "CapCut" / "User Data"
        capcut_drafts = fake_capcut / "Projects" / "com.lveditor.draft"
        capcut_drafts.mkdir(parents=True)

        with mock.patch.object(render, "_find_capcut_user_data", return_value=None):
            draft_path = render.run(fixture_cut_list, tmp_path / "out", raw_clip.parent)

        with mock.patch.object(
            render, "_find_capcut_user_data", return_value=fake_capcut
        ):
            dest = render._export_to_capcut(
                draft_path, raw_clip.parent, fixture_cut_list
            )

        assert dest is not None
        content = json.loads((dest / "draft_info.json").read_text())
        paths = [v["path"] for v in content["materials"]["videos"]]
        assert all(p.startswith(str(dest)) for p in paths)

    def test_returns_none_when_capcut_absent(
        self, raw_clip, tmp_path, fixture_cut_list
    ):
        with mock.patch.object(render, "_find_capcut_user_data", return_value=None):
            draft_path = render.run(fixture_cut_list, tmp_path / "out", raw_clip.parent)
            result = render._export_to_capcut(
                draft_path, raw_clip.parent, fixture_cut_list
            )
        assert result is None

    def test_overwrites_existing_capcut_draft(
        self, raw_clip, tmp_path, fixture_cut_list
    ):
        fake_capcut = tmp_path / "CapCut" / "User Data"
        capcut_drafts = fake_capcut / "Projects" / "com.lveditor.draft"
        capcut_drafts.mkdir(parents=True)

        with mock.patch.object(render, "_find_capcut_user_data", return_value=None):
            draft_path = render.run(fixture_cut_list, tmp_path / "out", raw_clip.parent)

        with mock.patch.object(
            render, "_find_capcut_user_data", return_value=fake_capcut
        ):
            render._export_to_capcut(draft_path, raw_clip.parent, fixture_cut_list)
            dest = render._export_to_capcut(
                draft_path, raw_clip.parent, fixture_cut_list
            )

        assert dest is not None and dest.exists()

    def test_extra_clips_copied_and_in_import_panel(
        self, raw_clip, tmp_path, fixture_cut_list
    ):
        """Clips in the input folder but absent from the cut list are copied
        and listed in draft_meta_info.json so CapCut shows them in the import
        panel."""
        import shutil

        extra_clip = raw_clip.parent / "extra_clip.mp4"
        shutil.copy2(raw_clip, extra_clip)

        fake_capcut = tmp_path / "CapCut" / "User Data"
        capcut_drafts = fake_capcut / "Projects" / "com.lveditor.draft"
        capcut_drafts.mkdir(parents=True)

        with mock.patch.object(render, "_find_capcut_user_data", return_value=None):
            draft_path = render.run(fixture_cut_list, tmp_path / "out", raw_clip.parent)

        with mock.patch.object(
            render, "_find_capcut_user_data", return_value=fake_capcut
        ):
            dest = render._export_to_capcut(
                draft_path, raw_clip.parent, fixture_cut_list
            )

        assert dest is not None
        assert (dest / "extra_clip.mp4").exists()

        meta = json.loads((dest / "draft_meta_info.json").read_text())
        imported_names = {
            entry["extra_info"]
            for dm in meta.get("draft_materials", [])
            if dm.get("type") == 0
            for entry in dm.get("value", [])
        }
        assert "extra_clip.mp4" in imported_names
