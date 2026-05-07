from lasagnastack import io
from lasagnastack.models.cut_list import CutList
from lasagnastack.stages import direct
from tests.conftest import FIXTURE_CUT_LIST, FIXTURE_INVENTORY, MockLLMClient


class TestBuildPrompt:
    def test_includes_brief_text(self, brief_path):
        prompt = direct._build_prompt([FIXTURE_INVENTORY], brief_path)
        assert "Test Kitchen" in prompt

    def test_includes_segment_id(self, brief_path):
        prompt = direct._build_prompt([FIXTURE_INVENTORY], brief_path)
        assert FIXTURE_INVENTORY.segments[0].id in prompt

    def test_includes_source_file(self, brief_path):
        prompt = direct._build_prompt([FIXTURE_INVENTORY], brief_path)
        assert FIXTURE_INVENTORY.source_file in prompt


class TestRun:
    def test_returns_cut_list(self, brief_path, tmp_path, mock_client):
        result = direct.run([FIXTURE_INVENTORY], brief_path, tmp_path, mock_client)
        assert isinstance(result, CutList)

    def test_calls_generate_once(self, brief_path, tmp_path, mock_client):
        direct.run([FIXTURE_INVENTORY], brief_path, tmp_path, mock_client)
        assert len(mock_client.generate_calls) == 1

    def test_writes_cut_list_json(self, brief_path, tmp_path, mock_client):
        direct.run([FIXTURE_INVENTORY], brief_path, tmp_path, mock_client)
        assert io.cut_list_path(tmp_path).exists()

    def test_written_json_round_trips(self, brief_path, tmp_path, mock_client):
        result = direct.run([FIXTURE_INVENTORY], brief_path, tmp_path, mock_client)
        reloaded = io.read_json(CutList, io.cut_list_path(tmp_path))
        assert reloaded.model_dump() == result.model_dump()

    def test_result_matches_fixture(self, brief_path, tmp_path, mock_client):
        result = direct.run([FIXTURE_INVENTORY], brief_path, tmp_path, mock_client)
        assert result.model_dump() == FIXTURE_CUT_LIST.model_dump()

    def test_uses_default_gemini_client_when_none_passed(
        self, brief_path, tmp_path, monkeypatch
    ):
        created = []

        class FakeGeminiClient(MockLLMClient):
            def __init__(self):
                super().__init__()
                created.append(self)

        monkeypatch.setattr("lasagnastack.stages.direct.GeminiClient", FakeGeminiClient)
        direct.run([FIXTURE_INVENTORY], brief_path, tmp_path)
        assert len(created) == 1
