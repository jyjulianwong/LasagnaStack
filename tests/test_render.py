import json
import re
import unittest.mock as mock

import pytest
from pycapcut import SEC

from lasagnastack import io
from lasagnastack.models.cut_list import Caption, CropHint
from lasagnastack.stages import render

_TS = "20260508_200844"


class TestDraftNaming:
    def test_display_name_has_prefix(self) -> None:
        """Display name is prefixed with 'LasagnaStack - ' and suffixed with the timestamp."""
        assert (
            render._draft_display_name("Hana Don", _TS)
            == f"LasagnaStack - Hana Don {_TS}"
        )

    def test_folder_name_matches_display_name(self) -> None:
        """Folder name is identical to the display name."""
        assert render._draft_folder_name("Hana Don", _TS) == render._draft_display_name(
            "Hana Don", _TS
        )

    def test_folder_name_collapses_extra_whitespace(self) -> None:
        """Consecutive spaces are collapsed to a single space in the folder name."""
        result = render._draft_folder_name("Test  Kitchen", _TS)
        assert "Test Kitchen" in result

    def test_folder_name_strips_special_chars(self) -> None:
        """Special characters such as '&' are removed from the folder name."""
        result = render._draft_folder_name("Café & Bar", _TS)
        assert "&" not in result

    def test_folder_name_prefix(self) -> None:
        """Folder name always begins with the LasagnaStack prefix."""
        assert render._draft_folder_name("X", _TS).startswith("LasagnaStack - ")

    def test_folder_name_has_timestamp_suffix(self) -> None:
        """Folder name ends with the supplied timestamp."""
        assert render._draft_folder_name("X", _TS).endswith(_TS)

    def test_sanitise_title_removes_ampersand(self) -> None:
        """'&' is treated as a special character and stripped."""
        assert "&" not in render._sanitise_title("Café & Bar")

    def test_sanitise_title_keeps_letters_and_digits(self) -> None:
        """Alphanumeric characters and unicode letters are preserved."""
        assert render._sanitise_title("Café123") == "Café123"

    def test_sanitise_title_keeps_hyphens(self) -> None:
        """Hyphens are preserved as they are filesystem-safe."""
        assert "-" in render._sanitise_title("Hana-Don")


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

    def test_draft_folder_name_has_prefix_and_timestamp(
        self, raw_clip, tmp_path, fixture_cut_list
    ) -> None:
        """Draft folder name starts with the LasagnaStack prefix and ends with a timestamp."""
        result = render.run(fixture_cut_list, tmp_path, raw_clip.parent)
        assert result.name.startswith("LasagnaStack - ")
        assert re.search(r"\d{8}_\d{6}$", result.name)

    def test_draft_info_json_has_display_name(
        self, raw_clip, tmp_path, fixture_cut_list
    ) -> None:
        """draft_info.json 'name' field matches the draft folder name."""
        result = render.run(fixture_cut_list, tmp_path, raw_clip.parent)
        content = json.loads((result / "draft_info.json").read_text())
        assert content["name"] == result.name

    def test_second_run_creates_new_folder(
        self, raw_clip, tmp_path, fixture_cut_list, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Each run produces a uniquely-named folder; earlier drafts are not overwritten."""
        monkeypatch.setattr(render, "_make_timestamp", lambda: "20260508_100000")
        result1 = render.run(fixture_cut_list, tmp_path, raw_clip.parent)
        monkeypatch.setattr(render, "_make_timestamp", lambda: "20260508_100001")
        result2 = render.run(fixture_cut_list, tmp_path, raw_clip.parent)
        assert result1.exists()
        assert result2.exists()
        assert result1 != result2

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
