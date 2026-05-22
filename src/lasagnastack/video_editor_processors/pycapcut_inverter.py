"""Converts a CapCut draft folder (draft_info.json) into (CutList, ReelStyleSheet).

Recovers all structurally encoded data: clip timing, speed, crop orientation,
captions, overlays, transitions, text colour, size, bold/italic, border,
font identity, and entrance/exit animations. Fields that are LLM-only
(source_segment_id, role, alt_captions, reel tone) are filled with sentinel
values so the resulting CutList validates without schema changes.
"""

import json
from pathlib import Path

import structlog
from pycapcut import FontType
from pycapcut.metadata.text_intro import TextIntro
from pycapcut.metadata.text_outro import TextOutro

from lasagnastack.models.reel_pipeline.cut_list import (
    Caption,
    CropHint,
    Cut,
    CutList,
    Overlay,
    ReelMeta,
)
from lasagnastack.models.reel_pipeline.enhance import (
    CaptionEffect,
    CutStyle,
    OverlayStyle,
    ReelStyleSheet,
    TransitionSpec,
)

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# Font lookup: CapCut effect_id → our friendly key (or display name for
# fonts outside our 12-key write-side set).
# ---------------------------------------------------------------------------

_SUPPORTED_FONT_KEYS: dict[FontType, str] = {
    FontType.BebasNeue: "bebas_neue",
    FontType.Anton: "anton",
    FontType.CINZEL: "cinzel",
    FontType.Oswald_ExtraLight: "oswald",
    FontType.Montserrat: "montserrat",
    FontType.Poppins_Bold: "poppins",
    FontType.KaushanScript: "kaushan",
    FontType.Brush: "brush",
    FontType.Amatic_Bold: "amatic",
    FontType.PermanentMarker_Regular: "permanent_marker",
    FontType.PlayfairDisplay_Italic: "playfair",
    FontType.Nunito: "nunito",
}

# Build comprehensive reverse map at import time from the full FontType enum.
# Supported fonts map to friendly keys; all others map to the CapCut display name.
_FONT_ID_TO_KEY: dict[str, str] = {
    member.value.effect_id: _SUPPORTED_FONT_KEYS.get(member, member.value.name)
    for member in FontType
}

# ---------------------------------------------------------------------------
# Animation lookup: CapCut effect_id → our friendly key (intro / outro).
# Only the five intros and three outros we write are mapped; anything else
# returns None so training data stays accurate and uncontaminated.
# ---------------------------------------------------------------------------

_INTRO_ID_TO_KEY: dict[str, str] = {
    TextIntro.渐显.value.effect_id: "fade_in",
    TextIntro.向上滑动.value.effect_id: "slide_up",
    TextIntro.打字机_I.value.effect_id: "typewriter",
    TextIntro.弹出.value.effect_id: "pop",
    TextIntro.向上弹入.value.effect_id: "bounce",
}

_OUTRO_ID_TO_KEY: dict[str, str] = {
    TextOutro.渐隐.value.effect_id: "fade_out",
    TextOutro.向下滑动.value.effect_id: "slide_down",
    TextOutro.模糊.value.effect_id: "blur",
}

_CANVAS_W = 1080
_CANVAS_H = 1920


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_draft(draft_dir: Path) -> tuple[CutList, ReelStyleSheet]:
    """Parse a CapCut draft folder into a (CutList, ReelStyleSheet) pair.

    Args:
        draft_dir: Path to a CapCut draft folder containing ``draft_info.json``.

    Returns:
        A ``(CutList, ReelStyleSheet)`` tuple reconstructed from the draft.

    Raises:
        FileNotFoundError: If ``draft_info.json`` is absent.
        ValueError: If the draft contains no video track.
    """
    draft_info_path = draft_dir / "draft_info.json"
    draft = json.loads(draft_info_path.read_text(encoding="utf-8"))

    canvas = draft.get("canvas_config", {})
    canvas_w: int = canvas.get("width", _CANVAS_W)
    canvas_h: int = canvas.get("height", _CANVAS_H)

    materials = draft.get("materials", {})
    video_mat_lookup: dict[str, dict] = {
        v["id"]: v for v in materials.get("videos", [])
    }
    text_mat_lookup: dict[str, dict] = {t["id"]: t for t in materials.get("texts", [])}
    anim_lookup: dict[str, dict] = {
        a["id"]: a for a in materials.get("material_animations", [])
    }
    transition_lookup: dict[str, dict] = {
        t["id"]: t for t in materials.get("transitions", [])
    }

    tracks = draft.get("tracks", [])
    video_tracks = [t for t in tracks if t.get("type") == "video"]
    text_tracks = [t for t in tracks if t.get("type") == "text"]

    if not video_tracks:
        raise ValueError(f"No video track found in {draft_dir}")

    video_segs = sorted(
        video_tracks[0].get("segments", []),
        key=lambda s: s["target_timerange"]["start"],
    )

    # --- Pass 1: parse video segments ------------------------------------
    # Each entry: (segment_dict, material_dict, timeline_start_us, timeline_end_us)
    cut_data: list[tuple[dict, dict, int, int]] = []
    for seg in video_segs:
        mat = video_mat_lookup.get(seg.get("material_id", ""), {})
        t_start: int = seg["target_timerange"]["start"]
        t_end: int = t_start + seg["target_timerange"]["duration"]
        cut_data.append((seg, mat, t_start, t_end))

    cut_timeline_ranges = [(t_start, t_end) for _, _, t_start, t_end in cut_data]

    # --- Pass 2: classify text segments as captions or overlays ----------
    # cut_captions[cut_idx] = (Caption, CaptionEffect)
    cut_captions: dict[int, tuple[Caption, CaptionEffect]] = {}
    overlays: list[Overlay] = []
    overlay_effects: list[CaptionEffect] = []

    for text_track in text_tracks:
        for text_seg in text_track.get("segments", []):
            mat = text_mat_lookup.get(text_seg.get("material_id", ""), {})
            text = _extract_text(mat)
            if not text:
                continue

            ts_start: int = text_seg["target_timerange"]["start"]
            ts_end: int = ts_start + text_seg["target_timerange"]["duration"]
            transform_y: float = (
                text_seg.get("clip", {}).get("transform", {}).get("y", -0.8)
            )
            position = _infer_position(transform_y)
            effect, anim_in, anim_out = _extract_caption_effect(
                mat, text_seg, anim_lookup
            )
            effect = effect.model_copy(
                update={"animation_in": anim_in, "animation_out": anim_out}
            )

            idx = _find_containing_cut(ts_start, ts_end, cut_timeline_ranges)
            if idx is not None and idx not in cut_captions:
                cut_start = cut_timeline_ranges[idx][0]
                caption = Caption(
                    text=text,
                    style="bold",
                    position=position,
                    in_ms=(ts_start - cut_start) // 1000,
                    out_ms=(ts_end - cut_start) // 1000,
                )
                cut_captions[idx] = (caption, effect)
                log.debug("inverter_caption", cut_idx=idx, text=text[:30])
            else:
                overlays.append(
                    Overlay(
                        text=text,
                        style="bold",
                        position=position,
                        start_ms=ts_start // 1000,
                        end_ms=ts_end // 1000,
                    )
                )
                overlay_effects.append(effect)
                log.debug("inverter_overlay", text=text[:30])

    # --- Pass 3: assemble Cut objects ------------------------------------
    cuts: list[Cut] = []
    for i, (seg, mat, t_start, t_end) in enumerate(cut_data):
        src_start_us: int = seg["source_timerange"]["start"]
        src_end_us: int = src_start_us + seg["source_timerange"]["duration"]
        target_dur_us: int = t_end - t_start
        speed: float = seg.get("speed", 1.0)

        clip = seg.get("clip", {})
        mat_w: int = mat.get("width", canvas_w)
        mat_h: int = mat.get("height", canvas_h)
        crop = _reverse_crop(clip, mat_w, mat_h, canvas_w, canvas_h)

        src_file = Path(mat.get("path", "")).name or f"clip_{i + 1}"
        caption, _ = cut_captions.get(i, (None, None))

        cuts.append(
            Cut(
                order=i + 1,
                source_segment_id="human_edit",
                source_file=src_file,
                **{"in": _us_to_mmss(src_start_us)},
                out=_us_to_mmss(src_end_us),
                duration_sec=round(target_dur_us / 1_000_000, 3),
                role="unknown",
                crop=crop,
                speed=speed,
                transition_in="cut",
                transition_out=_detect_transition(seg, transition_lookup),
                caption=caption,
            )
        )

    total_us: int = cut_timeline_ranges[-1][1] if cut_timeline_ranges else 0
    cut_list = CutList(
        reel_meta=ReelMeta(
            title=draft_dir.name,
            target_duration_sec=round(total_us / 1_000_000, 1),
            aspect_ratio=f"{canvas_w}:{canvas_h}",
            tone="unknown",
        ),
        cuts=cuts,
        alt_captions=[],
        overlays=overlays,
    )

    # --- Build ReelStyleSheet --------------------------------------------
    cut_styles: list[CutStyle] = []
    for i, (seg, _mat, _ts, _te) in enumerate(cut_data):
        transition_type = _detect_transition(seg, transition_lookup)
        _, cap_effect = cut_captions.get(i, (None, None))
        cut_styles.append(
            CutStyle(
                cut_order=i + 1,
                transition_out=(
                    TransitionSpec(type=transition_type)
                    if transition_type != "cut"
                    else None
                ),
                caption_effect=cap_effect,
            )
        )

    reel_style_sheet = ReelStyleSheet(
        cut_styles=cut_styles,
        overlay_styles=[
            OverlayStyle(overlay_index=i, caption_effect=eff)
            for i, eff in enumerate(overlay_effects)
        ],
    )

    log.info(
        "inverter_parsed",
        draft=draft_dir.name,
        cuts=len(cuts),
        captions=len(cut_captions),
        overlays=len(overlays),
    )
    return cut_list, reel_style_sheet


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _us_to_mmss(us: int) -> str:
    """Convert microseconds to ``MM:SS.D`` timestamp format."""
    total_sec = us / 1_000_000
    minutes = int(total_sec // 60)
    secs = total_sec - minutes * 60
    return f"{minutes}:{secs:.1f}"


def _reverse_crop(
    clip: dict, src_w: int, src_h: int, canvas_w: int, canvas_h: int
) -> CropHint:
    """Infer a CropHint from a segment's clip transform and scale.

    CapCut stores ``transform.x`` in units of half-canvas-width and applies
    ``scale`` on top of the fit-to-height baseline. We reconstruct the
    effective horizontal overflow and classify the pan direction.
    """
    if src_w == 0 or src_h == 0:
        return CropHint(mode="center", offset_x=0.0)

    scale_x: float = clip.get("scale", {}).get("x", 1.0)
    transform_x: float = clip.get("transform", {}).get("x", 0.0)

    src_aspect = src_w / src_h
    canvas_aspect = canvas_w / canvas_h

    if src_aspect <= canvas_aspect:
        # Portrait or square source fills the canvas without horizontal overflow.
        return CropHint(mode="center", offset_x=0.0)

    # Effective displayed width = fit-to-height width × scale.
    scaled_w = src_w * (canvas_h / src_h) * scale_x
    overflow_px = scaled_w - canvas_w
    if overflow_px <= 0:
        return CropHint(mode="center", offset_x=0.0)

    # max_shift is the full pan range in half-canvas-width units.
    max_shift = overflow_px / canvas_w
    threshold = max_shift * 0.3

    if transform_x > threshold:
        mode = "left_third"
    elif transform_x < -threshold:
        mode = "right_third"
    else:
        mode = "center"

    offset_x = max(-1.0, min(1.0, transform_x / max_shift)) if max_shift else 0.0
    return CropHint(mode=mode, offset_x=round(offset_x, 3))


def _detect_transition(seg: dict, transition_lookup: dict[str, dict]) -> str:
    """Return the outgoing transition type for a video segment."""
    for ref_id in seg.get("extra_material_refs", []):
        entry = transition_lookup.get(ref_id)
        if entry is None:
            continue
        name: str = entry.get("name", "")
        if "叠化" in name or "dissolve" in name.lower() or "fade" in name.lower():
            return "dissolve"
    return "cut"


def _extract_text(mat: dict) -> str:
    """Extract the plain text string from a CapCut text material."""
    content_raw = mat.get("content", "")
    try:
        return json.loads(content_raw).get("text", "").strip()
    except (json.JSONDecodeError, TypeError, AttributeError):
        return str(content_raw).strip()


def _find_containing_cut(
    ts_start: int, ts_end: int, cut_ranges: list[tuple[int, int]]
) -> int | None:
    """Return the index of the cut that fully contains [ts_start, ts_end], or None."""
    for i, (c_start, c_end) in enumerate(cut_ranges):
        if ts_start >= c_start and ts_end <= c_end:
            return i
    return None


def _infer_position(transform_y: float) -> str:
    """Map a clip transform_y value back to top / center / bottom."""
    if transform_y > 0.4:
        return "top"
    if transform_y < -0.4:
        return "bottom"
    return "center"


def _rgb_to_hex(rgb: list | tuple) -> str:
    """Convert a [0,1] float RGB triple to a ``#RRGGBB`` hex string."""
    r, g, b = (min(255, max(0, round(float(c) * 255))) for c in rgb[:3])
    return f"#{r:02X}{g:02X}{b:02X}"


def _extract_animations(
    refs: list[str], anim_lookup: dict[str, dict]
) -> tuple[str | None, str | None]:
    """Return (animation_in_key, animation_out_key) from material_animations refs."""
    anim_in: str | None = None
    anim_out: str | None = None
    for ref_id in refs:
        entry = anim_lookup.get(ref_id)
        if not entry:
            continue
        for anim in entry.get("animations", []):
            effect_id: str = anim.get("effect_id", "")
            if anim_in is None and effect_id in _INTRO_ID_TO_KEY:
                anim_in = _INTRO_ID_TO_KEY[effect_id]
            elif anim_out is None and effect_id in _OUTRO_ID_TO_KEY:
                anim_out = _OUTRO_ID_TO_KEY[effect_id]
    return anim_in, anim_out


def _extract_caption_effect(
    mat: dict, text_seg: dict, anim_lookup: dict[str, dict]
) -> tuple[CaptionEffect, str | None, str | None]:
    """Extract CaptionEffect and animation keys from a text material + segment.

    Args:
        mat: The text material dict from ``materials.texts``.
        text_seg: The text segment dict from the track.
        anim_lookup: Map from animation material ID → animation dict.

    Returns:
        ``(CaptionEffect, animation_in_key, animation_out_key)``
    """
    content_styles: list[dict] = []
    try:
        content_styles = json.loads(mat.get("content", "{}")).get("styles", [])
    except (json.JSONDecodeError, TypeError):
        pass

    s0: dict = content_styles[0] if content_styles else {}

    # Colour: nested under fill.content.solid.color as [r, g, b] floats.
    rgb = (
        s0.get("fill", {})
        .get("content", {})
        .get("solid", {})
        .get("color", [1.0, 1.0, 1.0])
    )
    color = (
        _rgb_to_hex(rgb)
        if isinstance(rgb, (list, tuple)) and len(rgb) >= 3
        else "#FFFFFF"
    )

    size = float(s0.get("size", 8.0))
    size = max(4.0, min(20.0, size))

    bold = bool(s0.get("bold", True))
    italic = float(mat.get("italic_degree", 0)) != 0

    # Font: CapCut stores a numeric effect_id in styles[0].font.id.
    font_dict = s0.get("font", {})
    font_id = font_dict.get("id", "") if isinstance(font_dict, dict) else ""
    font = _FONT_ID_TO_KEY.get(font_id) if font_id else None

    # Border: flat fields on the material use different units (0–0.1 range).
    border_color_raw: str = mat.get("border_color", "")
    border_color = (
        border_color_raw
        if border_color_raw and border_color_raw.startswith("#")
        else None
    )
    border_width_raw = mat.get("border_width")
    border_width: float | None = None
    if border_color and border_width_raw is not None:
        # Scale raw CapCut units (~0–0.1) to our schema units (0–100).
        border_width = round(min(100.0, max(0.0, float(border_width_raw) * 625.0)), 1)

    anim_in, anim_out = _extract_animations(
        text_seg.get("extra_material_refs", []), anim_lookup
    )

    effect = CaptionEffect(
        font=font,
        color=color,
        bold=bold,
        italic=italic,
        size=round(size, 2),
        border_color=border_color,
        border_width=border_width,
    )
    return effect, anim_in, anim_out
