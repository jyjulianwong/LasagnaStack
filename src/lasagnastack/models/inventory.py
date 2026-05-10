from pathlib import Path

from pydantic import BaseModel


class NormalisedClip(BaseModel):
    """A single clip after Stage 1 normalisation."""

    source_path: Path
    """Path to the original source clip."""
    normalised_path: Path
    """Path to the 480×854 H.264 output written by Stage 1."""
    duration_sec: float
    """Duration of the source clip in seconds."""
    scene_cut_times: list[float]
    """Scene-cut timestamps (seconds from clip start) detected by PySceneDetect.

    Used as fallback segmentation hints for Stage 2; Gemini is the primary source.
    """


class Segment(BaseModel):
    """One usable segment identified by Gemini within a normalised clip."""

    id: str
    """Unique segment identifier within the clip, e.g. ``'clip_001_seg_2'``."""
    start: str
    """Segment start time in MM:SS.D format."""
    end: str
    """Segment end time in MM:SS.D format."""
    shot_type: str
    """establishing | action | reaction | detail_closeup | cutaway | talking_head | b_roll | other"""
    description: str
    """One-sentence description of what is visually happening in the segment."""
    subject_position: str
    """left-third | center | right-third — horizontal position of the main subject."""
    vertical_crop_safe: bool
    """False if the subject sits near the horizontal edge and would be cut off by a 9:16 crop."""
    audio: str
    """ambient | dialogue | sound_effects | music | silence"""
    aesthetic_score: int
    """1–10 rating of lighting, composition, sharpness, and colour grading."""
    hook_potential: int
    """1–10 rating of scroll-stopping power in the first 0.5 seconds."""
    best_use: str
    """Suggested role in the reel: hook | establish_location | payoff_reaction | detail | transition | callout | outro"""


class OverallAssessment(BaseModel):
    """Clip-level quality assessment produced by Stage 2."""

    usability: str
    """high | medium | low — overall suitability of the clip for use in the reel."""
    primary_subject: str
    """Brief description of the main subject, e.g. ``'chef plating food'``."""
    lighting: str
    """Brief lighting description, e.g. ``'natural window light, slightly overexposed'``."""
    issues: list[str]
    """Notable problems with the clip, e.g. ``['shaky camera', 'out of focus for first 2s']``."""


class ClipInventory(BaseModel):
    """Stage 2 output for one clip."""

    source_file: str
    """Filename of the original source clip (not its full path)."""
    duration_sec: float
    """Duration of the source clip in seconds."""
    overall_assessment: OverallAssessment
    """Clip-level quality summary."""
    segments: list[Segment]
    """Usable segments identified within this clip."""


class ClipAnalysisResponse(BaseModel):
    """What Gemini generates for Stage 2 (excludes metadata we already know).

    The ``source_file`` and ``duration_sec`` fields are added by the stage after
    the LLM call to produce a full ``ClipInventory``.
    """

    overall_assessment: OverallAssessment
    """Clip-level quality summary returned by the LLM."""
    segments: list[Segment]
    """Usable segments identified by the LLM."""
