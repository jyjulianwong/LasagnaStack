import os

from lasagnastack.llm.base import LLMClient


def make_client(
    model: str | None = None,
    *,
    reasoning_max_tokens: int = 4000,
    reasoning_effort: str | None = None,
    total_max_tokens: int | None = None,
) -> LLMClient:
    """Instantiate the correct ``LLMClient`` for the given model string.

    Dispatches on the provider prefix (the first path segment of the model
    name). The prefix is stripped before the model name is forwarded to the
    client constructor.

    Supported prefixes:

    * ``gemini/`` → :class:`~lasagnastack.llm.gemini.GeminiClient`
    * ``openrouter/`` → :class:`~lasagnastack.llm.openrouter.OpenRouterClient`

    When ``model`` is ``None``, the ``LSNSTK_LLM_MODEL`` environment variable
    is read, falling back to ``"gemini/gemini-2.5-flash"``.

    Args:
        model: Full model string including provider prefix, e.g.
            ``"gemini/gemini-2.5-flash"`` or
            ``"openrouter/deepseek/deepseek-v3.2"``.
        reasoning_max_tokens: Token budget for internal reasoning. Forwarded
            as ``thinking_budget`` to ``GeminiClient`` and as
            ``reasoning.max_tokens`` to ``OpenRouterClient`` (when no effort
            level is set).
        reasoning_effort: Qualitative effort level (``"none"`` /
            ``"minimal"`` / ``"low"`` / ``"medium"`` / ``"high"`` /
            ``"xhigh"``). Forwarded to ``OpenRouterClient`` where it takes
            priority over ``reasoning_max_tokens``; accepted but ignored by
            ``GeminiClient``.
        total_max_tokens: Ceiling on all output tokens combined (reasoning +
            visible response). Forwarded to ``OpenRouterClient`` as the
            ``max_tokens`` API parameter; accepted but ignored by
            ``GeminiClient``.

    Returns:
        A concrete ``LLMClient`` instance for the resolved provider.

    Raises:
        ValueError: If the provider prefix is not recognised.
    """
    resolved = model or os.getenv("LSNSTK_LLM_MODEL", "gemini/gemini-2.5-flash")
    prefix = resolved.split("/")[0]

    if prefix == "gemini":
        from lasagnastack.llm.gemini import GeminiClient

        return GeminiClient(
            model=resolved,
            reasoning_max_tokens=reasoning_max_tokens,
            reasoning_effort=reasoning_effort,
            total_max_tokens=total_max_tokens,
        )

    if prefix == "openrouter":
        from lasagnastack.llm.openrouter import OpenRouterClient

        return OpenRouterClient(
            model=resolved,
            reasoning_max_tokens=reasoning_max_tokens,
            reasoning_effort=reasoning_effort,
            total_max_tokens=total_max_tokens,
        )

    raise ValueError(
        f"Unknown LLM provider prefix {prefix!r} in model {resolved!r}. "
        "Expected 'gemini' or 'openrouter'."
    )
