from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import ffmpeg
import pytest

from lasagnastack.cache import DiskCache
from lasagnastack.stages import ingest

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch


class TestFindClips:
    def test_discovers_mp4_and_mov(self, tmp_path):
        (tmp_path / "a.mp4").touch()
        (tmp_path / "b.MOV").touch()
        (tmp_path / "c.txt").touch()
        clips = ingest._find_clips(tmp_path)
        assert len(clips) == 2
        assert all(p.suffix.lower() in {".mp4", ".mov"} for p in clips)

    def test_returns_sorted(self, tmp_path):
        (tmp_path / "clip_b.mp4").touch()
        (tmp_path / "clip_a.mp4").touch()
        clips = ingest._find_clips(tmp_path)
        assert [p.name for p in clips] == ["clip_a.mp4", "clip_b.mp4"]

    def test_empty_dir_returns_empty_list(self, tmp_path):
        assert ingest._find_clips(tmp_path) == []


class TestNormaliseClip:
    def test_creates_output_file(self, raw_clip, tmp_path):
        dest = tmp_path / "norm.mp4"
        ingest._normalise_clip(raw_clip, dest)
        assert dest.exists()
        assert dest.stat().st_size > 0

    def test_output_is_portrait_720x1280(self, raw_clip, tmp_path):
        dest = tmp_path / "norm.mp4"
        ingest._normalise_clip(raw_clip, dest)
        probe = ffmpeg.probe(str(dest))
        vs = next(s for s in probe["streams"] if s["codec_type"] == "video")
        assert vs["width"] == 480
        assert vs["height"] == 854

    def test_output_codec_is_h264(self, raw_clip, tmp_path):
        dest = tmp_path / "norm.mp4"
        ingest._normalise_clip(raw_clip, dest)
        probe = ffmpeg.probe(str(dest))
        vs = next(s for s in probe["streams"] if s["codec_type"] == "video")
        assert vs["codec_name"] == "h264"

    def test_returns_source_duration(self, raw_clip, tmp_path):
        dest = tmp_path / "norm.mp4"
        duration = ingest._normalise_clip(raw_clip, dest)
        assert abs(duration - 5.0) < 0.1

    def test_handles_clip_without_audio(self, raw_clip, tmp_path):
        dest = tmp_path / "norm_no_audio.mp4"
        duration = ingest._normalise_clip(raw_clip, dest)
        assert dest.exists()
        assert duration > 0

    def test_handles_clip_with_audio(self, raw_clip_with_audio, tmp_path):
        dest = tmp_path / "norm_audio.mp4"
        ingest._normalise_clip(raw_clip_with_audio, dest)
        probe = ffmpeg.probe(str(dest))
        assert any(s["codec_type"] == "audio" for s in probe["streams"])


class TestDetectSceneCuts:
    def test_returns_list_of_floats(self, raw_clip):
        cuts = ingest._detect_scene_cuts(raw_clip)
        assert isinstance(cuts, list)
        assert all(isinstance(t, float) for t in cuts)

    def test_detects_colour_change_cut(self, raw_clip):
        # raw_clip is landscape (no letterbox padding), so ContentDetector gets full signal.
        cuts = ingest._detect_scene_cuts(raw_clip)
        assert len(cuts) >= 1

    def test_cut_is_near_midpoint(self, raw_clip):
        cuts = ingest._detect_scene_cuts(raw_clip)
        assert any(2.0 <= t <= 3.5 for t in cuts)

    def test_returns_empty_list_on_unreadable_file(self, tmp_path):
        bad = tmp_path / "bad.mp4"
        bad.write_bytes(b"not a video")
        cuts = ingest._detect_scene_cuts(bad)
        assert cuts == []


class TestProcessClipCache:
    """Tests for the DiskCache integration in _process_clip."""

    def test_cache_miss_processes_and_stores(
        self, raw_clip: Path, tmp_path: Path
    ) -> None:
        """On a cache miss, _process_clip normalises the clip and writes to cache."""
        dest = tmp_path / "norm.mp4"
        cache_dir = tmp_path / ".cache"

        ingest._process_clip(raw_clip, dest, cache_dir)

        cache = DiskCache(cache_dir)
        key = f"{raw_clip.name}_ingest"
        cached = cache.get(key)
        assert cached is not None
        assert "duration_sec" in cached
        assert "scene_cut_times" in cached
        assert dest.exists()

    def test_cache_hit_skips_normalisation(
        self, raw_clip: Path, tmp_path: Path, monkeypatch: "MonkeyPatch"
    ) -> None:
        """On a cache hit with dest present, normalisation and scene detection are skipped."""
        dest = tmp_path / "norm.mp4"
        cache_dir = tmp_path / ".cache"

        # Pre-populate the cache and create a dummy dest file.
        cache = DiskCache(cache_dir)
        key = f"{raw_clip.name}_ingest"
        cache.set(key, {"duration_sec": 3.0, "scene_cut_times": [1.5]})
        dest.write_bytes(b"dummy")

        normalise_calls: list[bool] = []
        detect_calls: list[bool] = []
        monkeypatch.setattr(
            ingest, "_normalise_clip", lambda *a: normalise_calls.append(True) or 0.0
        )
        monkeypatch.setattr(
            ingest, "_detect_scene_cuts", lambda *a: detect_calls.append(True) or []
        )

        duration, cuts = ingest._process_clip(raw_clip, dest, cache_dir)

        assert not normalise_calls
        assert not detect_calls
        assert duration == 3.0
        assert cuts == [1.5]

    def test_cache_hit_without_dest_reprocesses(
        self, raw_clip: Path, tmp_path: Path
    ) -> None:
        """A cache entry is ignored when the normalised dest file is absent."""
        dest = tmp_path / "norm.mp4"
        cache_dir = tmp_path / ".cache"

        # Write a cache entry but do NOT create the dest file.
        cache = DiskCache(cache_dir)
        key = f"{raw_clip.name}_ingest"
        cache.set(key, {"duration_sec": 99.0, "scene_cut_times": []})

        duration, _ = ingest._process_clip(raw_clip, dest, cache_dir)

        # Should have re-processed and returned the real duration (~5 s), not 99.
        assert abs(duration - 5.0) < 0.1
        assert dest.exists()

    def test_cache_hit_logs_ingest_cache_hit(
        self, raw_clip: Path, tmp_path: Path
    ) -> None:
        """ingest_cache_hit is emitted when the result is served from cache."""
        import structlog.testing

        dest = tmp_path / "norm.mp4"
        cache_dir = tmp_path / ".cache"

        cache = DiskCache(cache_dir)
        key = f"{raw_clip.name}_ingest"
        cache.set(key, {"duration_sec": 3.0, "scene_cut_times": []})
        dest.write_bytes(b"dummy")

        with structlog.testing.capture_logs() as logs:
            ingest._process_clip(raw_clip, dest, cache_dir)

        assert any(entry.get("event") == "ingest_cache_hit" for entry in logs)

    def test_run_uses_cache_on_second_call(
        self, raw_clip: Path, tmp_path: Path, monkeypatch: "MonkeyPatch"
    ) -> None:
        """Calling run() twice skips normalisation on the second call via cache."""
        input_dir = tmp_path / "input"
        input_dir.mkdir()
        (input_dir / raw_clip.name).symlink_to(raw_clip)
        out = tmp_path / "out"

        ingest.run(input_dir, out)

        normalise_calls: list[bool] = []
        detect_calls: list[bool] = []
        monkeypatch.setattr(
            ingest, "_normalise_clip", lambda *a: normalise_calls.append(True) or 0.0
        )
        monkeypatch.setattr(
            ingest, "_detect_scene_cuts", lambda *a: detect_calls.append(True) or []
        )

        ingest.run(input_dir, out)

        assert not normalise_calls
        assert not detect_calls


class TestRun:
    def test_raises_on_empty_input(self, tmp_path):
        with pytest.raises(ValueError, match="No MP4/MOV files found"):
            ingest.run(tmp_path, tmp_path / "out")

    def test_returns_one_result_per_clip(self, raw_clip, tmp_path):
        input_dir = tmp_path / "input"
        input_dir.mkdir()
        (input_dir / raw_clip.name).symlink_to(raw_clip)
        results = ingest.run(input_dir, tmp_path / "out")
        assert len(results) == 1

    def test_normalised_clip_exists_on_disk(self, raw_clip, tmp_path):
        input_dir = tmp_path / "input"
        input_dir.mkdir()
        (input_dir / raw_clip.name).symlink_to(raw_clip)
        results = ingest.run(input_dir, tmp_path / "out")
        assert results[0].normalised_path.exists()

    def test_result_has_positive_duration(self, raw_clip, tmp_path):
        input_dir = tmp_path / "input"
        input_dir.mkdir()
        (input_dir / raw_clip.name).symlink_to(raw_clip)
        results = ingest.run(input_dir, tmp_path / "out")
        assert results[0].duration_sec > 0
