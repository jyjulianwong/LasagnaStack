from pathlib import Path

from lasagnastack import io
from lasagnastack.models.reel_pipeline.enhance import ReelStyleSheet
from lasagnastack.stages.reel_pipeline import enhance


class TestBuildPrompt:
    def test_includes_brief_text(self, brief_path: Path, fixture_cut_list) -> None:
        prompt = enhance._build_prompt(fixture_cut_list, brief_path)
        assert "Test Kitchen" in prompt

    def test_includes_cut_list_json(self, brief_path: Path, fixture_cut_list) -> None:
        prompt = enhance._build_prompt(fixture_cut_list, brief_path)
        assert fixture_cut_list.cuts[0].source_segment_id in prompt

    def test_includes_skill_text_when_skill_path_provided(
        self, brief_path: Path, tmp_path: Path, fixture_cut_list
    ) -> None:
        skill = tmp_path / "skill.md"
        skill.write_text("# Custom Style Guide\nAlways use bold captions.")
        prompt = enhance._build_prompt(fixture_cut_list, brief_path, skill_path=skill)
        assert "Custom Style Guide" in prompt

    def test_no_skill_text_when_skill_path_absent(
        self, brief_path: Path, fixture_cut_list
    ) -> None:
        prompt = enhance._build_prompt(fixture_cut_list, brief_path, skill_path=None)
        assert "Custom Style Guide" not in prompt


class TestRun:
    def test_returns_reel_style_sheet(
        self, brief_path: Path, tmp_path: Path, mock_client, fixture_cut_list
    ) -> None:
        result = enhance.run(fixture_cut_list, brief_path, tmp_path, mock_client)
        assert isinstance(result, ReelStyleSheet)

    def test_calls_generate_once(
        self, brief_path: Path, tmp_path: Path, mock_client, fixture_cut_list
    ) -> None:
        enhance.run(fixture_cut_list, brief_path, tmp_path, mock_client)
        assert len(mock_client.generate_calls) == 1

    def test_writes_reel_style_json(
        self, brief_path: Path, tmp_path: Path, mock_client, fixture_cut_list
    ) -> None:
        enhance.run(fixture_cut_list, brief_path, tmp_path, mock_client)
        assert io.reel_style_path(tmp_path).exists()

    def test_written_json_round_trips(
        self, brief_path: Path, tmp_path: Path, mock_client, fixture_cut_list
    ) -> None:
        result = enhance.run(fixture_cut_list, brief_path, tmp_path, mock_client)
        reloaded = io.read_json(ReelStyleSheet, io.reel_style_path(tmp_path))
        assert reloaded.model_dump() == result.model_dump()

    def test_result_matches_fixture(
        self,
        brief_path: Path,
        tmp_path: Path,
        mock_client,
        fixture_cut_list,
        fixture_reel_style_sheet,
    ) -> None:
        result = enhance.run(fixture_cut_list, brief_path, tmp_path, mock_client)
        assert result.model_dump() == fixture_reel_style_sheet.model_dump()

    def test_uses_default_gemini_client_when_none_passed(
        self,
        brief_path: Path,
        tmp_path: Path,
        monkeypatch,
        mock_llm_client_class,
        fixture_cut_list,
        fixture_reel_style_sheet,
    ) -> None:
        created: list[object] = []

        class FakeGeminiClient(mock_llm_client_class):
            def __init__(self) -> None:
                super().__init__(generate_responses=[fixture_reel_style_sheet])
                created.append(self)

        monkeypatch.setattr(
            "lasagnastack.stages.reel_pipeline.enhance.GeminiClient", FakeGeminiClient
        )
        enhance.run(fixture_cut_list, brief_path, tmp_path)
        assert len(created) == 1
