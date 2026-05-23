from lasagnastack.stages.optimize_skill_pipeline import optimize_skill


class TestFormatExamples:
    def test_numbered_example_header(self, optimize_skill_state) -> None:
        result = optimize_skill._format_examples(optimize_skill_state)
        assert "### Example 1:" in result

    def test_includes_cut_list_json(
        self, optimize_skill_state, fixture_cut_list
    ) -> None:
        result = optimize_skill._format_examples(optimize_skill_state)
        assert fixture_cut_list.reel_meta.title in result

    def test_includes_reel_style_json(self, optimize_skill_state) -> None:
        result = optimize_skill._format_examples(optimize_skill_state)
        assert "cut_styles" in result

    def test_multiple_examples_all_appear(
        self, tmp_path, brief_path, fixture_cut_list, fixture_reel_style_sheet
    ) -> None:
        from lasagnastack.optimize_skill_pipeline_state import (
            OptimizeSkillPipelineState,
        )

        state = OptimizeSkillPipelineState(
            input_dir=tmp_path / "input",
            output_dir=tmp_path / "output",
            brief_path=brief_path,
            skill_path=None,
            critique_max_retries=2,
            draft_cut_lists=[fixture_cut_list, fixture_cut_list],
            draft_reel_style_sheets=[
                fixture_reel_style_sheet,
                fixture_reel_style_sheet,
            ],
            optimized_skill_text=None,
        )
        result = optimize_skill._format_examples(state)
        assert "### Example 1:" in result
        assert "### Example 2:" in result


class TestBuildPrompt:
    def test_includes_existing_skill_text(self) -> None:
        prompt = optimize_skill._build_prompt(
            "# My Skill\nTest instructions.", "examples"
        )
        assert "My Skill" in prompt

    def test_includes_examples(self) -> None:
        prompt = optimize_skill._build_prompt(
            "skill text", "### Example 1: Test Restaurant"
        )
        assert "Example 1" in prompt

    def test_sentinel_when_no_existing_skill(self) -> None:
        prompt = optimize_skill._build_prompt(
            "(no existing skill — generate from scratch)", "examples"
        )
        assert "generate from scratch" in prompt


class TestRun:
    def test_returns_skill_text_string(self, optimize_skill_state, mock_client) -> None:
        result = optimize_skill.run(optimize_skill_state, client=mock_client)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_calls_generate_once(self, optimize_skill_state, mock_client) -> None:
        optimize_skill.run(optimize_skill_state, client=mock_client)
        assert len(mock_client.generate_calls) == 1

    def test_result_matches_fixture(
        self, optimize_skill_state, mock_client, fixture_optimized_skill
    ) -> None:
        result = optimize_skill.run(optimize_skill_state, client=mock_client)
        assert result == fixture_optimized_skill.skill_text

    def test_uses_sentinel_when_no_skill_path(
        self, optimize_skill_state, mock_client
    ) -> None:
        optimize_skill.run(optimize_skill_state, client=mock_client)
        prompt = mock_client.generate_calls[0]["prompt"]
        assert "generate from scratch" in prompt

    def test_uses_existing_skill_when_skill_path_set(
        self,
        tmp_path,
        brief_path,
        mock_client,
        fixture_cut_list,
        fixture_reel_style_sheet,
    ) -> None:
        from lasagnastack.optimize_skill_pipeline_state import (
            OptimizeSkillPipelineState,
        )

        skill_file = tmp_path / "skill.md"
        skill_file.write_text("# Existing Skill\nUse dissolve transitions.")

        state = OptimizeSkillPipelineState(
            input_dir=tmp_path / "input",
            output_dir=tmp_path / "output",
            brief_path=brief_path,
            skill_path=skill_file,
            critique_max_retries=2,
            draft_cut_lists=[fixture_cut_list],
            draft_reel_style_sheets=[fixture_reel_style_sheet],
            optimized_skill_text=None,
        )
        optimize_skill.run(state, client=mock_client)
        prompt = mock_client.generate_calls[0]["prompt"]
        assert "Existing Skill" in prompt

    def test_uses_default_gemini_client_when_none_passed(
        self,
        optimize_skill_state,
        monkeypatch,
        mock_llm_client_class,
        fixture_optimized_skill,
    ) -> None:
        created: list[object] = []

        class FakeGeminiClient(mock_llm_client_class):
            def __init__(self) -> None:
                super().__init__(generate_responses=[fixture_optimized_skill])
                created.append(self)

        monkeypatch.setattr(
            "lasagnastack.stages.optimize_skill_pipeline.optimize_skill.GeminiClient",
            FakeGeminiClient,
        )
        optimize_skill.run(optimize_skill_state)
        assert len(created) == 1
