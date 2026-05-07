from lasagnastack import io
from lasagnastack.models.critique import CritiqueResult
from lasagnastack.stages import critique
from tests.conftest import (
    FIXTURE_CRITIQUE_APPROVED,
    FIXTURE_CRITIQUE_REVISE,
    FIXTURE_CUT_LIST,
    FIXTURE_INVENTORY,
    MockLLMClient,
)


class TestBuildPrompt:
    def test_includes_brief_text(self, brief_path):
        prompt = critique._build_prompt(FIXTURE_CUT_LIST, [FIXTURE_INVENTORY], brief_path)
        assert "Test Kitchen" in prompt

    def test_includes_cut_list(self, brief_path):
        prompt = critique._build_prompt(FIXTURE_CUT_LIST, [FIXTURE_INVENTORY], brief_path)
        assert FIXTURE_CUT_LIST.cuts[0].source_segment_id in prompt

    def test_includes_segment_id(self, brief_path):
        prompt = critique._build_prompt(FIXTURE_CUT_LIST, [FIXTURE_INVENTORY], brief_path)
        assert FIXTURE_INVENTORY.segments[0].id in prompt


class TestCritiqueOnce:
    def test_calls_generate_once(self, brief_path, mock_client):
        critique._critique_once(
            FIXTURE_CUT_LIST, [FIXTURE_INVENTORY], brief_path, mock_client, iteration=0
        )
        assert len(mock_client.generate_calls) == 1

    def test_returns_critique_result(self, brief_path, mock_client):
        result = critique._critique_once(
            FIXTURE_CUT_LIST, [FIXTURE_INVENTORY], brief_path, mock_client, iteration=0
        )
        assert isinstance(result, CritiqueResult)


class TestRun:
    def test_returns_cut_list_when_approved(self, brief_path, tmp_path, mock_client):
        result = critique.run(
            FIXTURE_CUT_LIST, [FIXTURE_INVENTORY], brief_path, tmp_path,
            max_retries=1, client=mock_client,
        )
        assert result.model_dump() == FIXTURE_CUT_LIST.model_dump()

    def test_writes_iteration_json(self, brief_path, tmp_path, mock_client):
        critique.run(
            FIXTURE_CUT_LIST, [FIXTURE_INVENTORY], brief_path, tmp_path,
            max_retries=1, client=mock_client,
        )
        assert io.critique_path(tmp_path, 0).exists()

    def test_written_json_round_trips(self, brief_path, tmp_path, mock_client):
        critique.run(
            FIXTURE_CUT_LIST, [FIXTURE_INVENTORY], brief_path, tmp_path,
            max_retries=1, client=mock_client,
        )
        reloaded = io.read_json(CritiqueResult, io.critique_path(tmp_path, 0))
        assert reloaded.verdict == FIXTURE_CRITIQUE_APPROVED.verdict

    def test_revise_updates_cut_list(self, brief_path, tmp_path):
        client = MockLLMClient(
            generate_responses=[FIXTURE_CRITIQUE_REVISE, FIXTURE_CRITIQUE_APPROVED]
        )
        result = critique.run(
            FIXTURE_CUT_LIST, [FIXTURE_INVENTORY], brief_path, tmp_path,
            max_retries=2, client=client,
        )
        assert result.model_dump() == FIXTURE_CRITIQUE_REVISE.cut_list_v2.model_dump()

    def test_revise_writes_multiple_iterations(self, brief_path, tmp_path):
        client = MockLLMClient(
            generate_responses=[FIXTURE_CRITIQUE_REVISE, FIXTURE_CRITIQUE_APPROVED]
        )
        critique.run(
            FIXTURE_CUT_LIST, [FIXTURE_INVENTORY], brief_path, tmp_path,
            max_retries=2, client=client,
        )
        assert io.critique_path(tmp_path, 0).exists()
        assert io.critique_path(tmp_path, 1).exists()

    def test_ships_at_cap(self, brief_path, tmp_path):
        client = MockLLMClient(
            generate_responses=[FIXTURE_CRITIQUE_REVISE, FIXTURE_CRITIQUE_REVISE]
        )
        result = critique.run(
            FIXTURE_CUT_LIST, [FIXTURE_INVENTORY], brief_path, tmp_path,
            max_retries=2, client=client,
        )
        assert result.model_dump() == FIXTURE_CRITIQUE_REVISE.cut_list_v2.model_dump()

    def test_zero_retries_skips_critique(self, brief_path, tmp_path, mock_client):
        result = critique.run(
            FIXTURE_CUT_LIST, [FIXTURE_INVENTORY], brief_path, tmp_path,
            max_retries=0, client=mock_client,
        )
        assert len(mock_client.generate_calls) == 0
        assert result.model_dump() == FIXTURE_CUT_LIST.model_dump()

    def test_uses_default_gemini_client_when_none_passed(
        self, brief_path, tmp_path, monkeypatch
    ):
        created = []

        class FakeGeminiClient(MockLLMClient):
            def __init__(self):
                super().__init__()
                created.append(self)

        monkeypatch.setattr("lasagnastack.stages.critique.GeminiClient", FakeGeminiClient)
        critique.run(
            FIXTURE_CUT_LIST, [FIXTURE_INVENTORY], brief_path, tmp_path, max_retries=1
        )
        assert len(created) == 1
