from pydantic import BaseModel

from lasagnastack.models.cut_list import CutList


class CritiqueResult(BaseModel):
    """Stage 4 output from the critic."""

    verdict: str
    issues: list[str] = []
    cut_list_v2: CutList | None = None
