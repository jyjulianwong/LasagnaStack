import hashlib
import json
from pathlib import Path
from typing import Any


def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class DiskCache:
    def __init__(self, cache_dir: Path) -> None:
        self._dir = cache_dir
        cache_dir.mkdir(parents=True, exist_ok=True)

    def get(self, key: str) -> Any | None:
        path = self._dir / f"{key}.json"
        if path.exists():
            return json.loads(path.read_text())
        return None

    def set(self, key: str, value: Any) -> None:
        (self._dir / f"{key}.json").write_text(json.dumps(value, indent=2))

    def make_key(self, file_path: Path, model: str) -> str:
        return f"{_hash_file(file_path)}_{model}"
