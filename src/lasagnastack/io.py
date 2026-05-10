"""Shared output-path conventions and JSON helpers for all pipeline stages.

Each stage writes its output to a predictable location under output_dir so that
intermediate results can be inspected, replayed, and debugged independently.

Layout
------
output_dir/
  .cache/                 Gemini response cache (keyed by clip hash + model)
  normalised/             Stage 1 — 480×854 H.264 clips for analysis
  inventories/            Stage 2 — ClipInventory JSON per source clip
  cut_list.json           Stage 3 — CutList JSON
  critique/               Stage 4 — CritiqueResult JSON per iteration
    iteration_0.json
    ...
  draft/                  Stage 5 — CapCut draft folder (written by pyCapCut)
"""

import json
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

_T = TypeVar("_T", bound=BaseModel)


# ── path conventions ──────────────────────────────────────────────────────────


def cache_dir(output_dir: Path) -> Path:
    return output_dir / ".cache"


def inventory_path(output_dir: Path, source_name: str) -> Path:
    stem = Path(source_name).stem
    return output_dir / "inventories" / f"{stem}_inventory.json"


def cut_list_path(output_dir: Path) -> Path:
    return output_dir / "cut_list.json"


def critique_path(output_dir: Path, iteration: int) -> Path:
    return output_dir / "critique" / f"iteration_{iteration}.json"


def reel_style_path(output_dir: Path) -> Path:
    return output_dir / "reel_style.json"


def draft_dir(output_dir: Path) -> Path:
    return output_dir / "draft"


# ── read / write helpers ──────────────────────────────────────────────────────


def write_json(data: BaseModel | list, path: Path) -> None:
    """Write a Pydantic model or list of models to a JSON file, creating parents."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, list):
        serialised = [
            item.model_dump(by_alias=True) if isinstance(item, BaseModel) else item
            for item in data
        ]
        path.write_text(json.dumps(serialised, indent=2))
    else:
        path.write_text(data.model_dump_json(indent=2, by_alias=True))


def read_json(schema: type[_T], path: Path) -> _T:
    """Read a JSON file and validate it against a Pydantic schema."""
    return schema.model_validate_json(path.read_text())
