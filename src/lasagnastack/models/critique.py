from pydantic import BaseModel

from lasagnastack.models.cut_list import CutList


class CritiqueResult(BaseModel):
    """Stage 4 output from the critic."""

    verdict: str
    """``'approved'`` if all ten criteria pass; ``'revise'`` if any fail."""
    issues: list[str] = []
    """Specific problems found. Empty when ``verdict`` is ``'approved'``."""
    cut_list_v2: CutList | None = None
    """Corrected cut list that addresses every issue. ``None`` when ``verdict`` is ``'approved'``."""
