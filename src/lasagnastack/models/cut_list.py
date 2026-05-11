from pydantic import BaseModel, Field


class ReelMeta(BaseModel):
    """Reel-level metadata describing the target output."""

    title: str
    """Short title for the reel, used as the CapCut project name."""
    target_duration_sec: float
    """Intended total reel duration in seconds (30–60)."""
    aspect_ratio: str
    """Target aspect ratio, e.g. ``'9:16'``."""
    tone: str
    """One or two words capturing the mood, e.g. ``'energetic upbeat'`` or ``'intimate moody'``."""


class CropHint(BaseModel):
    """Horizontal crop positioning hint for a cut."""

    mode: str
    """center | left_third | right_third — which horizontal region to show."""
    offset_x: float
    """Fine horizontal nudge, -1.0 (far left) to 1.0 (far right). 0.0 = no adjustment."""


class Caption(BaseModel):
    """Clip-scoped text overlay for a single cut.

    Timing is relative to the cut's own start and is clamped to the cut's
    duration at render time. For text that must persist across a cut boundary,
    use ``CutList.overlays`` instead.
    """

    text: str
    """On-screen text, ≤ 30 characters."""
    style: str
    """bold | minimal | subtitle"""
    position: str
    """top | center | bottom"""
    in_ms: int
    """Milliseconds after this cut's start when the caption appears."""
    out_ms: int
    """Milliseconds after this cut's start when the caption disappears.

    Must not exceed the cut's ``duration_sec × 1000``; enforced by the critique stage.
    """


class Cut(BaseModel):
    """One clip segment placed on the edit timeline."""

    order: int
    """1-based position in the timeline (1 = first cut)."""
    source_segment_id: str
    """The ``Segment.id`` this cut was taken from."""
    source_file: str
    """Filename of the source clip, matched against ``input_dir`` at render time."""
    in_: str = Field(alias="in")
    """Trim-in point in MM:SS.D format. Aliased from ``'in'`` to avoid the Python keyword."""
    out: str
    """Trim-out point in MM:SS.D format."""
    duration_sec: float
    """(out − in) in seconds, calculated precisely."""
    role: str
    """hook | establish_location | payoff_reaction | detail | transition | callout | outro"""
    crop: CropHint
    """Horizontal crop positioning for this cut."""
    speed: float
    """Playback speed multiplier. 1.0 = normal; < 1.0 = slow motion; > 1.0 = speed ramp."""
    transition_in: str
    """Incoming transition: none | cut | fade | dissolve"""
    transition_out: str
    """Outgoing transition: none | cut | fade | dissolve.

    May be overridden by ``ReelStyle.cut_styles`` at render time.
    """
    caption: Caption | None
    """Optional clip-scoped text overlay. Use ``CutList.overlays`` for text that spans multiple cuts."""

    model_config = {"populate_by_name": True}


class AltCaptionSet(BaseModel):
    """A set of alternative caption strings for one cut, used for A/B testing."""

    cut_order: int
    """The ``Cut.order`` this set belongs to."""
    texts: list[str]
    """2–3 alternative caption strings for the cut."""


class Overlay(BaseModel):
    """A text overlay placed at an absolute timeline position, independent of any single cut.

    Use this for text that must persist across a cut boundary — e.g. a location
    title that bridges an establishing shot and the first detail shot, or a CTA
    that appears over the final two clips. Timing is expressed in milliseconds from
    the start of the full reel timeline, NOT relative to any individual cut.
    """

    text: str
    """On-screen text, ≤ 40 characters."""
    style: str
    """bold | minimal | subtitle"""
    position: str
    """top | center | bottom"""
    start_ms: int
    """Absolute timeline start in milliseconds from reel start."""
    end_ms: int
    """Absolute timeline end in milliseconds from reel start. Must be > ``start_ms``."""


class CutList(BaseModel):
    """Stage 3 output: the full ordered edit."""

    reel_meta: ReelMeta
    """Reel-level metadata (title, duration, aspect ratio, tone)."""
    cuts: list[Cut]
    """Ordered list of cuts that make up the timeline."""
    alt_captions: list[AltCaptionSet]
    """Alternative caption texts for A/B testing, one set per captioned cut."""
    overlays: list[Overlay] = []
    """Timeline-level text overlays that may span multiple cuts. Empty if none needed."""
