from pathlib import Path

from lasagnastack import io
from lasagnastack.models.reel_pipeline.post_caption import PostCaption
from lasagnastack.stages.reel_pipeline import post_caption


class TestFormatSegmentDescriptions:
    def test_each_segment_appears(self, fixture_inventory) -> None:
        result = post_caption._format_segment_descriptions([fixture_inventory])
        assert fixture_inventory.segments[0].description in result

    def test_includes_shot_type(self, fixture_inventory) -> None:
        result = post_caption._format_segment_descriptions([fixture_inventory])
        assert fixture_inventory.segments[0].shot_type in result

    def test_empty_inventories_returns_empty_string(self) -> None:
        result = post_caption._format_segment_descriptions([])
        assert result == ""


class TestBuildPrompt:
    def test_includes_brief_text(
        self, brief_path: Path, fixture_cut_list, fixture_inventory
    ) -> None:
        prompt = post_caption._build_prompt(
            fixture_cut_list, [fixture_inventory], brief_path
        )
        assert "Test Kitchen" in prompt

    def test_includes_reel_meta(
        self, brief_path: Path, fixture_cut_list, fixture_inventory
    ) -> None:
        prompt = post_caption._build_prompt(
            fixture_cut_list, [fixture_inventory], brief_path
        )
        assert fixture_cut_list.reel_meta.title in prompt

    def test_includes_segment_descriptions(
        self, brief_path: Path, fixture_cut_list, fixture_inventory
    ) -> None:
        prompt = post_caption._build_prompt(
            fixture_cut_list, [fixture_inventory], brief_path
        )
        assert fixture_inventory.segments[0].description in prompt

    def test_includes_skill_text_when_provided(
        self, brief_path: Path, tmp_path: Path, fixture_cut_list, fixture_inventory
    ) -> None:
        skill = tmp_path / "skill.md"
        skill.write_text("# Caption Guide\nAlways use emojis.")
        prompt = post_caption._build_prompt(
            fixture_cut_list, [fixture_inventory], brief_path, skill_path=skill
        )
        assert "Caption Guide" in prompt

    def test_no_skill_text_when_absent(
        self, brief_path: Path, fixture_cut_list, fixture_inventory
    ) -> None:
        prompt = post_caption._build_prompt(
            fixture_cut_list, [fixture_inventory], brief_path, skill_path=None
        )
        assert "Caption Guide" not in prompt


class TestRun:
    def test_returns_post_caption(
        self,
        brief_path: Path,
        tmp_path: Path,
        mock_client,
        fixture_cut_list,
        fixture_inventory,
    ) -> None:
        result = post_caption.run(
            fixture_cut_list, [fixture_inventory], brief_path, tmp_path, mock_client
        )
        assert isinstance(result, PostCaption)

    def test_calls_generate_once(
        self,
        brief_path: Path,
        tmp_path: Path,
        mock_client,
        fixture_cut_list,
        fixture_inventory,
    ) -> None:
        post_caption.run(
            fixture_cut_list, [fixture_inventory], brief_path, tmp_path, mock_client
        )
        assert len(mock_client.generate_calls) == 1

    def test_writes_post_caption_txt(
        self,
        brief_path: Path,
        tmp_path: Path,
        mock_client,
        fixture_cut_list,
        fixture_inventory,
    ) -> None:
        post_caption.run(
            fixture_cut_list, [fixture_inventory], brief_path, tmp_path, mock_client
        )
        assert io.post_caption_path(tmp_path).exists()

    def test_written_text_matches_caption(
        self,
        brief_path: Path,
        tmp_path: Path,
        mock_client,
        fixture_cut_list,
        fixture_inventory,
    ) -> None:
        result = post_caption.run(
            fixture_cut_list, [fixture_inventory], brief_path, tmp_path, mock_client
        )
        content = io.post_caption_path(tmp_path).read_text(encoding="utf-8")
        assert content == result.caption

    def test_result_matches_fixture(
        self,
        brief_path: Path,
        tmp_path: Path,
        mock_client,
        fixture_cut_list,
        fixture_inventory,
        fixture_post_caption,
    ) -> None:
        result = post_caption.run(
            fixture_cut_list, [fixture_inventory], brief_path, tmp_path, mock_client
        )
        assert result.model_dump() == fixture_post_caption.model_dump()

    def test_uses_default_gemini_client_when_none_passed(
        self,
        brief_path: Path,
        tmp_path: Path,
        monkeypatch,
        mock_llm_client_class,
        fixture_cut_list,
        fixture_inventory,
        fixture_post_caption,
    ) -> None:
        created: list[object] = []

        class FakeGeminiClient(mock_llm_client_class):
            def __init__(self) -> None:
                super().__init__(generate_responses=[fixture_post_caption])
                created.append(self)

        monkeypatch.setattr(
            "lasagnastack.stages.reel_pipeline.post_caption.GeminiClient",
            FakeGeminiClient,
        )
        post_caption.run(fixture_cut_list, [fixture_inventory], brief_path, tmp_path)
        assert len(created) == 1
