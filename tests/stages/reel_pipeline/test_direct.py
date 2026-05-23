from lasagnastack import io
from lasagnastack.models.reel_pipeline.cut_list import CutList
from lasagnastack.stages.reel_pipeline import direct


class TestBuildPrompt:
    def test_includes_brief_text(self, brief_path, fixture_inventory):
        prompt = direct._build_prompt([fixture_inventory], brief_path)
        assert "Test Kitchen" in prompt

    def test_includes_segment_id(self, brief_path, fixture_inventory):
        prompt = direct._build_prompt([fixture_inventory], brief_path)
        assert fixture_inventory.segments[0].id in prompt

    def test_includes_source_file(self, brief_path, fixture_inventory):
        prompt = direct._build_prompt([fixture_inventory], brief_path)
        assert fixture_inventory.source_file in prompt


class TestRun:
    def test_returns_cut_list(
        self, brief_path, tmp_path, mock_client, fixture_inventory
    ):
        result = direct.run([fixture_inventory], brief_path, tmp_path, mock_client)
        assert isinstance(result, CutList)

    def test_calls_generate_once(
        self, brief_path, tmp_path, mock_client, fixture_inventory
    ):
        direct.run([fixture_inventory], brief_path, tmp_path, mock_client)
        assert len(mock_client.generate_calls) == 1

    def test_writes_cut_list_json(
        self, brief_path, tmp_path, mock_client, fixture_inventory
    ):
        direct.run([fixture_inventory], brief_path, tmp_path, mock_client)
        assert io.cut_list_path(tmp_path).exists()

    def test_written_json_round_trips(
        self, brief_path, tmp_path, mock_client, fixture_inventory
    ):
        result = direct.run([fixture_inventory], brief_path, tmp_path, mock_client)
        reloaded = io.read_json(CutList, io.cut_list_path(tmp_path))
        assert reloaded.model_dump() == result.model_dump()

    def test_result_matches_fixture(
        self, brief_path, tmp_path, mock_client, fixture_inventory, fixture_cut_list
    ):
        result = direct.run([fixture_inventory], brief_path, tmp_path, mock_client)
        assert result.model_dump() == fixture_cut_list.model_dump()

    def test_uses_default_gemini_client_when_none_passed(
        self,
        brief_path,
        tmp_path,
        monkeypatch,
        mock_llm_client_class,
        fixture_inventory,
    ):
        created = []

        class FakeGeminiClient(mock_llm_client_class):
            def __init__(self):
                super().__init__()
                created.append(self)

        monkeypatch.setattr(
            "lasagnastack.stages.reel_pipeline.direct.GeminiClient", FakeGeminiClient
        )
        direct.run([fixture_inventory], brief_path, tmp_path)
        assert len(created) == 1
