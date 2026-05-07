from abc import ABC, abstractmethod
from pathlib import Path

from pydantic import BaseModel


class LLMClient(ABC):
    @abstractmethod
    def generate(
        self,
        prompt: str,
        response_schema: type[BaseModel],
        *,
        temperature: float = 0.4,
    ) -> BaseModel:
        """Send a text-only prompt; return a validated response_schema instance."""
        ...

    @abstractmethod
    def generate_with_video(
        self,
        video_path: Path,
        prompt: str,
        response_schema: type[BaseModel],
        *,
        temperature: float = 0.4,
    ) -> BaseModel:
        """Upload video_path to the Files API, generate, return validated response."""
        ...
