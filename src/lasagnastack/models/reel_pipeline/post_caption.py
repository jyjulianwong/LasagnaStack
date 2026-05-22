from pydantic import BaseModel


class PostCaption(BaseModel):
    """Stage 7 output: Instagram post caption for the finished reel."""

    caption: str
    """Full Instagram post caption, ready to copy-paste at publish time."""
