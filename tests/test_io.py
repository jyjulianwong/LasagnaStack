import json
from pathlib import Path

from lasagnastack import io
from lasagnastack.models.reel_pipeline.cut_list import CutList


class TestPathConventions:
    def test_cache_dir(self, tmp_path: Path) -> None:
        assert io.cache_dir(tmp_path) == tmp_path / ".cache"

    def test_inventory_path(self, tmp_path: Path) -> None:
        result = io.inventory_path(tmp_path, "clip_01.mp4")
        assert result == tmp_path / "inventories" / "clip_01_inventory.json"

    def test_inventory_path_uses_stem_only(self, tmp_path: Path) -> None:
        result = io.inventory_path(tmp_path, "nested/clip_01.mp4")
        assert result.name == "clip_01_inventory.json"

    def test_cut_list_path(self, tmp_path: Path) -> None:
        assert io.cut_list_path(tmp_path) == tmp_path / "cut_list.json"

    def test_critique_path_iteration_0(self, tmp_path: Path) -> None:
        assert (
            io.critique_path(tmp_path, 0) == tmp_path / "critique" / "iteration_0.json"
        )

    def test_critique_path_iteration_3(self, tmp_path: Path) -> None:
        assert (
            io.critique_path(tmp_path, 3) == tmp_path / "critique" / "iteration_3.json"
        )

    def test_reel_style_path(self, tmp_path: Path) -> None:
        assert io.reel_style_path(tmp_path) == tmp_path / "reel_style.json"

    def test_draft_dir(self, tmp_path: Path) -> None:
        assert io.draft_dir(tmp_path) == tmp_path / "draft"

    def test_post_caption_path(self, tmp_path: Path) -> None:
        assert io.post_caption_path(tmp_path) == tmp_path / "post_caption.txt"


class TestWriteJson:
    def test_creates_parent_dirs(self, tmp_path: Path, fixture_cut_list) -> None:
        path = tmp_path / "deep" / "dir" / "out.json"
        io.write_json(fixture_cut_list, path)
        assert path.exists()

    def test_writes_valid_json(self, tmp_path: Path, fixture_cut_list) -> None:
        path = tmp_path / "out.json"
        io.write_json(fixture_cut_list, path)
        json.loads(path.read_text())  # must not raise

    def test_cut_in_field_serialised_with_alias(
        self, tmp_path: Path, fixture_cut_list
    ) -> None:
        """Cut.in_ must appear as 'in' in the serialised JSON (field alias)."""
        path = tmp_path / "out.json"
        io.write_json(fixture_cut_list, path)
        content = json.loads(path.read_text())
        first_cut = content["cuts"][0]
        assert "in" in first_cut
        assert "in_" not in first_cut


class TestReadJson:
    def test_reads_and_returns_model_instance(
        self, tmp_path: Path, fixture_cut_list
    ) -> None:
        path = tmp_path / "out.json"
        io.write_json(fixture_cut_list, path)
        result = io.read_json(CutList, path)
        assert isinstance(result, CutList)

    def test_round_trips_pydantic_model(self, tmp_path: Path, fixture_cut_list) -> None:
        path = tmp_path / "out.json"
        io.write_json(fixture_cut_list, path)
        result = io.read_json(CutList, path)
        assert result.model_dump() == fixture_cut_list.model_dump()


class TestWritePostCaption:
    def test_creates_file_at_correct_path(self, tmp_path: Path) -> None:
        io.write_post_caption(tmp_path, "Test caption")
        assert io.post_caption_path(tmp_path).exists()

    def test_content_matches_input(self, tmp_path: Path) -> None:
        caption = "Amazing food at Test Kitchen!"
        io.write_post_caption(tmp_path, caption)
        assert io.post_caption_path(tmp_path).read_text(encoding="utf-8") == caption

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        nested = tmp_path / "deeply" / "nested"
        io.write_post_caption(nested, "caption")
        assert io.post_caption_path(nested).exists()
