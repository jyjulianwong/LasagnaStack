from pydantic import BaseModel, Field


class CaptionEffect(BaseModel):
    """Visual styling for a single caption or overlay text segment."""

    font: str | None = None
    """Font key. Available values: bebas_neue | anton | cinzel | oswald | montserrat |
    poppins | kaushan | brush | amatic | permanent_marker | playfair | nunito.
    Omit to use the CapCut default system font."""
    color: str = "#FFFFFF"
    """Hex text colour, e.g. ``'#FF4500'``."""
    bold: bool = True
    """True makes text heavier; recommended for hook and callout captions."""
    italic: bool = False
    """Sparingly — best for quotes or poetic tone."""
    size: float = Field(default=8.0, ge=4.0, le=20.0)
    """Font size in CapCut units (4–20). Larger for short punchy captions; smaller for subtitle text."""
    border_color: str | None = None
    """Hex stroke/outline colour, e.g. ``'#000000'``. Omit for no border."""
    border_width: float | None = Field(default=None, ge=0.0, le=100.0)
    """Stroke width 0–100. Required when ``border_color`` is set; typical range 30–50."""
    animation_in: str | None = None
    """Entrance animation key: fade_in | slide_up | typewriter | pop | bounce."""
    animation_out: str | None = None
    """Exit animation key: fade_out | slide_down | blur."""


class TransitionSpec(BaseModel):
    """Transition specification for the outgoing edge of a cut."""

    type: str = "cut"
    """Transition type: cut | dissolve."""


class CutStyle(BaseModel):
    """Styling directives for a single cut."""

    cut_order: int
    """The ``Cut.order`` this style applies to."""
    transition_out: TransitionSpec | None = None
    """Override the transition on this cut's outgoing edge. Falls back to ``Cut.transition_out`` if absent."""
    caption_effect: CaptionEffect | None = None
    """Text styling for this cut's caption. Ignored if the cut has no caption."""


class OverlayStyle(BaseModel):
    """Styling directives for a single timeline overlay."""

    overlay_index: int
    """Zero-based index into ``CutList.overlays``."""
    caption_effect: CaptionEffect
    """Text styling applied to this overlay."""


class ReelStyle(BaseModel):
    """Stage 5 output: visual styling and animation layer for the approved cut list."""

    cut_styles: list[CutStyle]
    """One entry per cut. Must cover every ``cut_order`` present in the ``CutList``."""
    overlay_styles: list[OverlayStyle] = []
    """Styling for timeline overlays. Include one entry per overlay that needs non-default styling."""
