from abc import ABC, abstractmethod
from pathlib import Path

from pydantic import BaseModel


class LLMClient(ABC):
    """Abstract base class for all LLM provider clients.

    Subclasses must implement :meth:`generate` and
    :meth:`generate_with_video`. The constructor stores three shared
    reasoning-control parameters that each concrete client interprets
    according to its provider's API:

    * ``reasoning_max_tokens`` — a hard token budget for internal
      reasoning/thinking. Gemini maps this to ``thinking_budget``; OpenRouter
      maps it to ``reasoning.max_tokens`` (when no effort level is set).
    * ``reasoning_effort`` — a qualitative effort level (``"none"`` /
      ``"minimal"`` / ``"low"`` / ``"medium"`` / ``"high"`` / ``"xhigh"``).
      OpenRouter maps this to ``reasoning.effort`` and it takes priority over
      ``reasoning_max_tokens`` when both are supplied. Not used by Gemini.
    * ``total_max_tokens`` — ceiling on all output tokens combined (reasoning +
      visible response). Maps directly to the ``max_tokens`` API parameter.
      Required for Anthropic models via OpenRouter, where this total must be
      strictly greater than the reasoning budget. Ignored by Gemini.
    """

    def __init__(
        self,
        reasoning_max_tokens: int = 4000,
        reasoning_effort: str | None = None,
        total_max_tokens: int | None = None,
    ) -> None:
        """Store shared reasoning-control parameters.

        Args:
            reasoning_max_tokens: Maximum tokens the model may spend on
                internal reasoning per call. Set to ``0`` to disable
                reasoning entirely (when no effort level overrides it).
            reasoning_effort: Qualitative effort level controlling reasoning
                depth. When set, takes priority over ``reasoning_max_tokens``
                for providers that support it (e.g. OpenRouter). ``None``
                defers to ``reasoning_max_tokens``.
            total_max_tokens: Hard ceiling on all output tokens combined
                (reasoning + visible response). Maps to the ``max_tokens``
                API parameter. Required for Anthropic models (via OpenRouter)
                to ensure the total exceeds the reasoning budget. ``None``
                lets the provider use its default.
        """
        self._reasoning_max_tokens = reasoning_max_tokens
        self._reasoning_effort = reasoning_effort
        self._total_max_tokens = total_max_tokens

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
