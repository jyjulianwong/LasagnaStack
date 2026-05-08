from pathlib import Path

from pydantic import BaseModel


class NormalisedClip(BaseModel):
    """A single clip after Stage 1 normalisation."""

    source_path: Path
    normalised_path: Path
    duration_sec: float
    scene_cut_times: list[float]


class Segment(BaseModel):
    id: str
    start: str
    end: str
    shot_type: str
    description: str
    subject_position: str
    vertical_crop_safe: bool
    audio: str
    aesthetic_score: int
    hook_potential: int
    best_use: str


class OverallAssessment(BaseModel):
    usability: str
    primary_subject: str
    lighting: str
    issues: list[str]


class ClipInventory(BaseModel):
    """Stage 2 output for one clip."""

    source_file: str
    duration_sec: float
    overall_assessment: OverallAssessment
    segments: list[Segment]


class ClipAnalysisResponse(BaseModel):
    """What Gemini generates for Stage 2 (excludes metadata we already know)."""

    overall_assessment: OverallAssessment
    segments: list[Segment]
