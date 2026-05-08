from pydantic import BaseModel, Field


class ReelMeta(BaseModel):
    title: str
    target_duration_sec: float
    aspect_ratio: str
    tone: str
    music_mood: str


class CropHint(BaseModel):
    mode: str
    offset_x: float


class Caption(BaseModel):
    text: str
    style: str
    position: str
    in_ms: int
    out_ms: int


class Cut(BaseModel):
    order: int
    source_segment_id: str
    source_file: str
    in_: str = Field(alias="in")
    out: str
    duration_sec: float
    role: str
    crop: CropHint
    speed: float
    transition_in: str
    transition_out: str
    caption: Caption | None

    model_config = {"populate_by_name": True}


class AltCaptionSet(BaseModel):
    cut_order: int
    texts: list[str]


class CutList(BaseModel):
    """Stage 3 output: the full ordered edit."""

    reel_meta: ReelMeta
    cuts: list[Cut]
    alt_captions: list[AltCaptionSet]
    music_search_terms: list[str]
    rationale: str
