from lasagnastack.models.inventory import ClipInventory
from lasagnastack.stages import analyse


class TestLoadPrompt:
    def test_prompt_contains_source_file(self):
        prompt = analyse._load_prompt("clip_01.mp4", 12.5)
        assert "clip_01.mp4" in prompt

    def test_prompt_contains_duration(self):
        prompt = analyse._load_prompt("clip_01.mp4", 12.5)
        assert "12.5" in prompt


class TestAnalyseClip:
    def test_calls_llm_on_first_run(
        self, fixture_normalised_clip, tmp_path, mock_client
    ):
        from lasagnastack.cache import DiskCache

        cache = DiskCache(tmp_path / ".cache")
        analyse._analyse_clip(fixture_normalised_clip, cache, mock_client)
        assert len(mock_client.generate_with_video_calls) == 1

    def test_returns_clip_inventory(
        self, fixture_normalised_clip, tmp_path, mock_client
    ):
        from lasagnastack.cache import DiskCache

        cache = DiskCache(tmp_path / ".cache")
        result = analyse._analyse_clip(fixture_normalised_clip, cache, mock_client)
        assert isinstance(result, ClipInventory)
        assert result.source_file == fixture_normalised_clip.source_path.name
        assert result.duration_sec == fixture_normalised_clip.duration_sec

    def test_cache_hit_skips_llm(self, fixture_normalised_clip, tmp_path, mock_client):
        from lasagnastack.cache import DiskCache

        cache = DiskCache(tmp_path / ".cache")
        # First call — populates cache
        analyse._analyse_clip(fixture_normalised_clip, cache, mock_client)
        assert len(mock_client.generate_with_video_calls) == 1

        # Second call — should hit cache
        analyse._analyse_clip(fixture_normalised_clip, cache, mock_client)
        assert len(mock_client.generate_with_video_calls) == 1  # unchanged

    def test_cached_result_matches_original(
        self, fixture_normalised_clip, tmp_path, mock_client
    ):
        from lasagnastack.cache import DiskCache

        cache = DiskCache(tmp_path / ".cache")
        first = analyse._analyse_clip(fixture_normalised_clip, cache, mock_client)
        second = analyse._analyse_clip(fixture_normalised_clip, cache, mock_client)
        assert first.model_dump() == second.model_dump()

    def test_segments_populated_from_llm_response(
        self, fixture_normalised_clip, tmp_path, mock_client, fixture_segment
    ):
        from lasagnastack.cache import DiskCache

        cache = DiskCache(tmp_path / ".cache")
        result = analyse._analyse_clip(fixture_normalised_clip, cache, mock_client)
        assert len(result.segments) == 1
        assert result.segments[0].shot_type == fixture_segment.shot_type


class TestRun:
    def test_returns_one_inventory_per_clip(
        self, fixture_normalised_clip, tmp_path, mock_client
    ):
        results = analyse.run([fixture_normalised_clip], tmp_path, mock_client)
        assert len(results) == 1

    def test_preserves_clip_order(self, fixture_normalised_clip, tmp_path, mock_client):
        # Pass the same clip twice to simulate multiple clips
        results = analyse.run(
            [fixture_normalised_clip, fixture_normalised_clip],
            tmp_path,
            mock_client,
        )
        assert len(results) == 2
        assert results[0].source_file == results[1].source_file

    def test_writes_inventory_json(
        self, fixture_normalised_clip, tmp_path, mock_client
    ):
        from lasagnastack import io

        analyse.run([fixture_normalised_clip], tmp_path, mock_client)
        expected = io.inventory_path(tmp_path, fixture_normalised_clip.source_path.name)
        assert expected.exists()

    def test_uses_default_gemini_client_when_none_passed(
        self, fixture_normalised_clip, tmp_path, monkeypatch, mock_llm_client_class
    ):
        created = []

        class FakeGeminiClient(mock_llm_client_class):
            def __init__(self):
                super().__init__()
                created.append(self)

        monkeypatch.setattr(
            "lasagnastack.stages.analyse.GeminiClient", FakeGeminiClient
        )  # noqa: E501
        analyse.run([fixture_normalised_clip], tmp_path)
        assert len(created) == 1
