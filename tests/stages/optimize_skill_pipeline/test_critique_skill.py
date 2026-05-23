from lasagnastack.models.optimize_skill_pipeline.skill import CritiqueSkillResult
from lasagnastack.stages.optimize_skill_pipeline import critique_skill


class TestCritiqueOnce:
    def test_calls_generate_once(self, mock_client) -> None:
        critique_skill._critique_once(
            existing_skill="",
            current_skill="# Skill\nTest",
            examples="### Example 1: Test",
            client=mock_client,
            iteration=0,
            previous_issues=[],
        )
        assert len(mock_client.generate_calls) == 1

    def test_returns_critique_skill_result(self, mock_client) -> None:
        result = critique_skill._critique_once(
            existing_skill="",
            current_skill="# Skill\nTest",
            examples="### Example 1: Test",
            client=mock_client,
            iteration=0,
            previous_issues=[],
        )
        assert isinstance(result, CritiqueSkillResult)

    def test_first_iteration_signals_no_history(self, mock_client) -> None:
        critique_skill._critique_once(
            existing_skill="",
            current_skill="# Skill",
            examples="examples",
            client=mock_client,
            iteration=0,
            previous_issues=[],
        )
        prompt = mock_client.generate_calls[0]["prompt"]
        assert "first review" in prompt.lower()

    def test_previous_issues_appear_in_prompt(self, mock_client) -> None:
        issues = [["Transitions are unclear", "Missing hook guidance"]]
        critique_skill._critique_once(
            existing_skill="",
            current_skill="# Skill",
            examples="examples",
            client=mock_client,
            iteration=1,
            previous_issues=issues,
        )
        prompt = mock_client.generate_calls[0]["prompt"]
        assert "Transitions are unclear" in prompt
        assert "Missing hook guidance" in prompt


class TestRun:
    def test_returns_skill_text_when_approved(
        self, optimize_skill_state, mock_client
    ) -> None:
        result = critique_skill.run(
            optimize_skill_state, client=mock_client, max_retries=1
        )
        assert result == optimize_skill_state.optimized_skill_text

    def test_writes_iteration_json(self, optimize_skill_state, mock_client) -> None:
        critique_skill.run(optimize_skill_state, client=mock_client, max_retries=1)
        assert (
            optimize_skill_state.output_dir / "skill_critique" / "iteration_0.json"
        ).exists()

    def test_revise_updates_skill_text(
        self,
        optimize_skill_state,
        mock_llm_client_class,
        fixture_critique_skill_revise,
        fixture_critique_skill_approved,
    ) -> None:
        client = mock_llm_client_class(
            generate_responses=[
                fixture_critique_skill_revise,
                fixture_critique_skill_approved,
            ]
        )
        result = critique_skill.run(optimize_skill_state, client=client, max_retries=2)
        assert result == fixture_critique_skill_revise.skill_v2

    def test_ships_at_cap(
        self,
        optimize_skill_state,
        mock_llm_client_class,
        fixture_critique_skill_revise,
    ) -> None:
        client = mock_llm_client_class(
            generate_responses=[
                fixture_critique_skill_revise,
                fixture_critique_skill_revise,
            ]
        )
        result = critique_skill.run(optimize_skill_state, client=client, max_retries=2)
        assert result == fixture_critique_skill_revise.skill_v2

    def test_zero_retries_returns_original_skill(
        self, optimize_skill_state, mock_client
    ) -> None:
        result = critique_skill.run(
            optimize_skill_state, client=mock_client, max_retries=0
        )
        assert len(mock_client.generate_calls) == 0
        assert result == optimize_skill_state.optimized_skill_text

    def test_previous_issues_logged_in_next_iteration(
        self,
        optimize_skill_state,
        mock_llm_client_class,
        fixture_critique_skill_revise,
        fixture_critique_skill_approved,
    ) -> None:
        client = mock_llm_client_class(
            generate_responses=[
                fixture_critique_skill_revise,
                fixture_critique_skill_approved,
            ]
        )
        critique_skill.run(optimize_skill_state, client=client, max_retries=2)
        second_prompt = client.generate_calls[1]["prompt"]
        assert fixture_critique_skill_revise.issues[0] in second_prompt

    def test_uses_default_gemini_client_when_none_passed(
        self,
        optimize_skill_state,
        monkeypatch,
        mock_llm_client_class,
        fixture_critique_skill_approved,
    ) -> None:
        created: list[object] = []

        class FakeGeminiClient(mock_llm_client_class):
            def __init__(self) -> None:
                super().__init__(generate_responses=[fixture_critique_skill_approved])
                created.append(self)

        monkeypatch.setattr(
            "lasagnastack.stages.optimize_skill_pipeline.critique_skill.GeminiClient",
            FakeGeminiClient,
        )
        critique_skill.run(optimize_skill_state, max_retries=1)
        assert len(created) == 1
