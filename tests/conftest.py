import os
from collections.abc import Generator
from pathlib import Path

import ffmpeg
import pytest
from pydantic import BaseModel

from lasagnastack.llm.base import LLMClient
from lasagnastack.models.critique import CritiqueResult
from lasagnastack.models.cut_list import CropHint, Cut, CutList, ReelMeta
from lasagnastack.models.inventory import (
    ClipAnalysisResponse,
    ClipInventory,
    NormalisedClip,
    OverallAssessment,
    Segment,
)

# ── MLflow isolation ────────────────────────────────────────────────────────


@pytest.fixture(autouse=True, scope="session")
def _mlflow_tmp_tracking(
    tmp_path_factory: pytest.TempPathFactory,
) -> Generator[None, None, None]:
    """Redirect MLflow to a temporary directory for the entire test session.

    Prevents tests from writing to a real MLflow server or polluting the
    project-level ``mlruns/`` folder. Mirrors the ``no_capcut`` pattern used
    to isolate CapCut writes.
    """
    mlruns = tmp_path_factory.mktemp("mlruns")
    original = os.environ.get("MLFLOW_TRACKING_URI")
    os.environ["MLFLOW_TRACKING_URI"] = str(mlruns)
    yield
    if original is None:
        os.environ.pop("MLFLOW_TRACKING_URI", None)
    else:
        os.environ["MLFLOW_TRACKING_URI"] = original


# ── shared fixture data ──────────────────────────────────────────────────────

FIXTURE_SEGMENT = Segment(
    id="clip_00_s01",
    start="00:00.0",
    end="00:02.5",
    shot_type="dish_reveal",
    description="Overhead shot of test dish",
    subjects=["dish"],
    motion="static",
    framing="close-up",
    subject_position="center",
    vertical_crop_safe=True,
    audio="ambient",
    aesthetic_score=8,
    hook_potential=7,
    best_use="hook",
    notes="",
)

FIXTURE_ASSESSMENT = OverallAssessment(
    usability="high",
    primary_subject="Test dish",
    lighting="warm",
    audio_notes="ambient",
    issues=[],
)

FIXTURE_INVENTORY = ClipInventory(
    source_file="raw_clip.mp4",
    duration_sec=5.0,
    overall_assessment=FIXTURE_ASSESSMENT,
    segments=[FIXTURE_SEGMENT],
)

FIXTURE_CUT = Cut(  # pyrefly: ignore[missing-argument]
    order=1,
    source_segment_id="clip_00_s01",
    source_file="raw_clip.mp4",
    in_="00:00.0",
    out="00:02.5",
    duration_sec=2.5,
    role="hook",
    crop=CropHint(mode="center", offset_x=0.0),
    speed=1.0,
    transition_in="none",
    transition_out="cut",
    caption=None,
)

FIXTURE_CUT_LIST = CutList(
    reel_meta=ReelMeta(
        title="Test Restaurant",
        target_duration_sec=60.0,
        aspect_ratio="9:16",
        tone="vibrant",
        music_mood="upbeat",
    ),
    cuts=[FIXTURE_CUT],
    alt_captions=[],
    music_search_terms=["upbeat foodie", "London restaurant"],
    rationale="Strong hook followed by a dish reveal creates a compelling narrative.",
)

FIXTURE_CRITIQUE_APPROVED = CritiqueResult(
    verdict="approved",
    issues=[],
    cut_list_v2=None,
)

FIXTURE_CRITIQUE_REVISE = CritiqueResult(
    verdict="revise",
    issues=["Duration is only 2.5s, target is 30–60s."],
    cut_list_v2=FIXTURE_CUT_LIST,
)


class MockLLMClient(LLMClient):
    """Returns fixture data without making any real API calls.

    Pass generate_responses to control the sequence of values returned by
    generate() — each call pops the next item from the list. When the list is
    exhausted (or empty), the default fixture for the schema is used.
    """

    def __init__(self, generate_responses: list[BaseModel] | None = None) -> None:
        self.generate_calls: list[dict] = []
        self.generate_with_video_calls: list[dict] = []
        self._generate_queue: list[BaseModel] = list(generate_responses or [])

    def generate(
        self,
        prompt: str,
        response_schema: type[BaseModel],
        *,
        temperature: float = 0.4,
    ) -> BaseModel:
        self.generate_calls.append({"prompt": prompt, "schema": response_schema})
        if self._generate_queue:
            return self._generate_queue.pop(0)
        if response_schema is CutList:
            return FIXTURE_CUT_LIST
        if response_schema is CritiqueResult:
            return FIXTURE_CRITIQUE_APPROVED
        raise NotImplementedError(f"MockLLMClient: no fixture for {response_schema}")

    def generate_with_video(
        self,
        video_path: Path,
        prompt: str,
        response_schema: type[BaseModel],
        *,
        temperature: float = 0.4,
    ) -> BaseModel:
        self.generate_with_video_calls.append(
            {"video_path": video_path, "prompt": prompt, "schema": response_schema}
        )
        if response_schema is ClipAnalysisResponse:
            return ClipAnalysisResponse(
                overall_assessment=FIXTURE_ASSESSMENT,
                segments=[FIXTURE_SEGMENT],
            )
        raise NotImplementedError(f"MockLLMClient: no fixture for {response_schema}")


@pytest.fixture(scope="session")
def fixture_segment() -> Segment:
    return FIXTURE_SEGMENT


@pytest.fixture(scope="session")
def fixture_inventory() -> ClipInventory:
    return FIXTURE_INVENTORY


@pytest.fixture(scope="session")
def fixture_cut() -> Cut:
    return FIXTURE_CUT


@pytest.fixture(scope="session")
def fixture_cut_list() -> CutList:
    return FIXTURE_CUT_LIST


@pytest.fixture(scope="session")
def fixture_critique_approved() -> CritiqueResult:
    return FIXTURE_CRITIQUE_APPROVED


@pytest.fixture(scope="session")
def fixture_critique_revise() -> CritiqueResult:
    return FIXTURE_CRITIQUE_REVISE


@pytest.fixture(scope="session")
def mock_llm_client_class() -> type[MockLLMClient]:
    return MockLLMClient


@pytest.fixture
def mock_client() -> MockLLMClient:
    return MockLLMClient()


@pytest.fixture
def brief_path(tmp_path) -> Path:
    p = tmp_path / "brief.txt"
    p.write_text("Restaurant: Test Kitchen\nTone: warm and inviting")
    return p


@pytest.fixture
def fixture_normalised_clip(raw_clip, tmp_path) -> NormalisedClip:
    from lasagnastack.stages.ingest import _normalise_clip

    dest = tmp_path / "norm.mp4"
    duration = _normalise_clip(raw_clip, dest)
    return NormalisedClip(
        source_path=raw_clip,
        normalised_path=dest,
        duration_sec=duration,
        scene_cut_times=[],
    )


@pytest.fixture(scope="session")
def raw_clip(tmp_path_factory) -> Path:
    """5-second 1920×1080 landscape clip with a hard colour change at ~2.5s.

    Uses file-based concat (not the filter concat) so every frame carries
    clean, continuous PTS — required for OpenCV's CAP_PROP_POS_MSEC to return
    a non-NaN value in scenedetect 0.7.
    """
    tmp = tmp_path_factory.mktemp("clips")
    seg_a = tmp / "seg_a.mp4"
    seg_b = tmp / "seg_b.mp4"
    out = tmp / "raw_clip.mp4"

    for color, seg_path in [("blue", seg_a), ("red", seg_b)]:
        (
            ffmpeg.input(
                f"color=c={color}:size=1920x1080:rate=30",
                f="lavfi",
                t=2.5,
            )
            .output(
                str(seg_path),
                vcodec="libx264",
                pix_fmt="yuv420p",
                r=30,
                movflags="+faststart",
            )
            .overwrite_output()
            .run(quiet=True)
        )

    concat_list = tmp / "list.txt"
    concat_list.write_text(f"file '{seg_a.absolute()}'\nfile '{seg_b.absolute()}'\n")
    (
        ffmpeg.input(str(concat_list), f="concat", safe=0)
        .output(
            str(out),
            vcodec="libx264",
            pix_fmt="yuv420p",
            r=30,
            movflags="+faststart",
        )
        .overwrite_output()
        .run(quiet=True)
    )
    return out


@pytest.fixture(scope="session")
def raw_clip_with_audio(tmp_path_factory) -> Path:
    """5-second 1920×1080 landscape clip with a 440 Hz sine-wave audio track."""
    out = tmp_path_factory.mktemp("clips") / "raw_clip_audio.mp4"
    video = ffmpeg.input("color=c=green:size=1920x1080:rate=30", f="lavfi", t=5)
    audio = ffmpeg.input("sine=frequency=440:sample_rate=44100", f="lavfi", t=5)
    (
        ffmpeg.output(
            video,
            audio,
            str(out),
            vcodec="libx264",
            acodec="aac",
            pix_fmt="yuv420p",
            r=30,
            movflags="+faststart",
        )
        .overwrite_output()
        .run(quiet=True)
    )
    return out
