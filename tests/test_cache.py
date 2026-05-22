from pathlib import Path

from lasagnastack.cache import DiskCache


class TestDiskCache:
    def test_get_returns_none_on_miss(self, tmp_path: Path) -> None:
        cache = DiskCache(tmp_path / ".cache")
        assert cache.get("nonexistent") is None

    def test_set_and_get_round_trips_dict(self, tmp_path: Path) -> None:
        cache = DiskCache(tmp_path / ".cache")
        cache.set("key1", {"foo": "bar", "num": 42})
        assert cache.get("key1") == {"foo": "bar", "num": 42}

    def test_set_and_get_round_trips_list(self, tmp_path: Path) -> None:
        cache = DiskCache(tmp_path / ".cache")
        cache.set("k", [1, 2, 3])
        assert cache.get("k") == [1, 2, 3]

    def test_creates_json_file_on_set(self, tmp_path: Path) -> None:
        cache_dir = tmp_path / ".cache"
        cache = DiskCache(cache_dir)
        cache.set("mykey", {"x": 1})
        assert (cache_dir / "mykey.json").exists()

    def test_set_overwrites_existing(self, tmp_path: Path) -> None:
        cache = DiskCache(tmp_path / ".cache")
        cache.set("k", {"v": 1})
        cache.set("k", {"v": 99})
        assert cache.get("k") == {"v": 99}

    def test_constructor_creates_cache_dir(self, tmp_path: Path) -> None:
        cache_dir = tmp_path / "deep" / ".cache"
        DiskCache(cache_dir)
        assert cache_dir.is_dir()


class TestMakeKey:
    def test_same_content_produces_same_key(self, tmp_path: Path) -> None:
        a = tmp_path / "a.bin"
        b = tmp_path / "b.bin"
        a.write_bytes(b"hello world")
        b.write_bytes(b"hello world")
        cache = DiskCache(tmp_path / ".cache")
        assert cache.make_key(a, "model-x") == cache.make_key(b, "model-x")

    def test_different_content_produces_different_keys(self, tmp_path: Path) -> None:
        a = tmp_path / "a.bin"
        b = tmp_path / "b.bin"
        a.write_bytes(b"hello")
        b.write_bytes(b"world")
        cache = DiskCache(tmp_path / ".cache")
        assert cache.make_key(a, "model-x") != cache.make_key(b, "model-x")

    def test_key_includes_model_string(self, tmp_path: Path) -> None:
        f = tmp_path / "f.bin"
        f.write_bytes(b"data")
        cache = DiskCache(tmp_path / ".cache")
        key = cache.make_key(f, "gemini-2.5-flash")
        assert "gemini-2.5-flash" in key

    def test_different_models_produce_different_keys(self, tmp_path: Path) -> None:
        f = tmp_path / "f.bin"
        f.write_bytes(b"data")
        cache = DiskCache(tmp_path / ".cache")
        key_a = cache.make_key(f, "model-a")
        key_b = cache.make_key(f, "model-b")
        assert key_a != key_b
