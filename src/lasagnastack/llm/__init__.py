import os

from lasagnastack.llm.base import LLMClient


def make_client(model: str | None = None, *, thinking_budget: int = 4000) -> LLMClient:
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
        thinking_budget: Maximum thinking tokens per call. Forwarded only to
            ``GeminiClient`` (ignored for other providers).

    Returns:
        A concrete ``LLMClient`` instance for the resolved provider.

    Raises:
        ValueError: If the provider prefix is not recognised.
    """
    resolved = model or os.getenv("LSNSTK_LLM_MODEL", "gemini/gemini-2.5-flash")
    prefix = resolved.split("/")[0]

    if prefix == "gemini":
        from lasagnastack.llm.gemini import GeminiClient

        return GeminiClient(model=resolved, thinking_budget=thinking_budget)

    if prefix == "openrouter":
        from lasagnastack.llm.openrouter import OpenRouterClient

        return OpenRouterClient(model=resolved)

    raise ValueError(
        f"Unknown LLM provider prefix {prefix!r} in model {resolved!r}. "
        "Expected 'gemini' or 'openrouter'."
    )
