import hashlib
import json
import os
import threading
import time
from pathlib import Path
from typing import Any

import mlflow
import mlflow.entities
import structlog
from mlflow.tracing.constant import CostKey, SpanAttributeKey, TokenUsageKey
from openai import OpenAI
from pydantic import BaseModel, ValidationError
from tenacity import retry, stop_after_attempt, wait_exponential

from lasagnastack.llm.base import LLMClient

log = structlog.get_logger()

_MAX_JSON_RETRIES = 2
_MAX_PROMPT_LOG_CHARS = 10000
_REQUEST_TIMEOUT_SEC = 300.0

_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


def _prompt_hash(text: str) -> str:
    """Return a short SHA-256 hex digest of text for log correlation.

    Args:
        text: The string to hash.

    Returns:
        A 12-character hexadecimal digest.
    """
    return hashlib.sha256(text.encode()).hexdigest()[:12]


def _extract_json(text: str) -> str:
    """Strip markdown code fences that some models wrap around JSON output.

    Args:
        text: Raw model response text.

    Returns:
        The innermost content between fences, or the original text if no
        fences are found.
    """
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        # Drop the opening fence line (```json or ```) and the closing ```
        end = len(lines) - 1
        while end > 0 and lines[end].strip() != "```":
            end -= 1
        text = "\n".join(lines[1:end]).strip()
    return text


class OpenRouterClient(LLMClient):
    """LLM client backed by OpenRouter (OpenAI-compatible API).

    Supports text-only generation. Video input is not available on OpenRouter;
    use ``GeminiClient`` for Stage 2 (analyse) when video upload is required.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        reasoning_max_tokens: int = 4000,
        reasoning_effort: str | None = None,
        total_max_tokens: int | None = None,
    ) -> None:
        """Initialise the OpenRouter client.

        Args:
            api_key: OpenRouter API key. Falls back to the
                ``LSNSTK_LLM_OPENROUTER_API_KEY`` environment variable.
            model: Model name to use (``"openrouter/<provider>/<model>"``
                or bare ``"<provider>/<model>"``). Falls back to the
                ``LSNSTK_LLM_MODEL`` environment variable, then
                ``"openrouter/meta-llama/llama-3.1-8b-instruct"``.
            reasoning_max_tokens: Token budget forwarded as
                ``reasoning.max_tokens`` when no effort level is set. Set
                to ``0`` to disable reasoning entirely.
            reasoning_effort: Qualitative effort level (``"none"`` /
                ``"minimal"`` / ``"low"`` / ``"medium"`` / ``"high"`` /
                ``"xhigh"``). When set, takes priority over
                ``reasoning_max_tokens`` and maps to ``reasoning.effort``
                in the request.
            total_max_tokens: Passed as ``max_tokens`` in the API request —
                the ceiling on all output tokens combined (reasoning + visible
                response). Required for Anthropic models where ``max_tokens``
                must be strictly greater than the reasoning budget.
        """
        super().__init__(
            reasoning_max_tokens=reasoning_max_tokens,
            reasoning_effort=reasoning_effort,
            total_max_tokens=total_max_tokens,
        )
        raw_model = model or os.getenv(
            "LSNSTK_LLM_MODEL", "openrouter/meta-llama/llama-3.1-8b-instruct"
        )
        self._model = raw_model.removeprefix("openrouter/")
        resolved_key = api_key or os.getenv("LSNSTK_LLM_OPENROUTER_API_KEY")
        if not resolved_key:
            raise ValueError(
                "OpenRouter API key not found. "
                "Set LSNSTK_LLM_OPENROUTER_API_KEY in .env or pass api_key=."
            )
        self._client = OpenAI(
            api_key=resolved_key,
            base_url=_OPENROUTER_BASE_URL,
            timeout=_REQUEST_TIMEOUT_SEC,
            max_retries=0,
        )

        self._total_input_tokens: int = 0
        self._total_output_tokens: int = 0
        self._total_thinking_tokens: int = 0
        self._total_cost_usd: float = 0.0
        self._call_count: int = 0
        self._stats_lock = threading.Lock()

    @property
    def session_stats(self) -> dict[str, float | int]:
        """Aggregated token and cost totals across all calls on this instance.

        Returns:
            A dict with keys ``total_input_tokens``, ``total_output_tokens``,
            ``total_thinking_tokens``, ``total_cost_usd``, and
            ``llm_call_count``. Cost is read directly from the ``usage.cost``
            field returned by OpenRouter — no static pricing table is needed.
        """
        return {
            "total_input_tokens": self._total_input_tokens,
            "total_output_tokens": self._total_output_tokens,
            "total_thinking_tokens": self._total_thinking_tokens,
            "total_cost_usd": self._total_cost_usd,
            "llm_call_count": self._call_count,
        }

    def generate(
        self,
        prompt: str,
        response_schema: type[BaseModel],
        *,
        temperature: float = 0.4,
    ) -> BaseModel:
        """Send a text-only prompt; return a validated response_schema instance.

        Args:
            prompt: The plain-text prompt to send.
            response_schema: Pydantic model class that defines the expected
                JSON structure of the response.
            temperature: Sampling temperature passed to the model.

        Returns:
            A validated instance of ``response_schema``.
        """
        return self._generate_contents(prompt, response_schema, temperature)

    def generate_with_video(
        self,
        video_path: Path,
        prompt: str,
        response_schema: type[BaseModel],
        *,
        temperature: float = 0.4,
    ) -> BaseModel:
        """Not supported — OpenRouter has no video upload API.

        Args:
            video_path: Unused.
            prompt: Unused.
            response_schema: Unused.
            temperature: Unused.

        Raises:
            NotImplementedError: Always. Use ``GeminiClient`` for Stage 2.
        """
        raise NotImplementedError(
            "OpenRouterClient does not support video input. "
            "Use GeminiClient for Stage 2 (analyse)."
        )

    @retry(
        stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=30)
    )
    def _call_api(
        self,
        system: str,
        prompt: str,
        temperature: float,
    ) -> tuple[str, Any]:
        """Raw API call with retry. Each invocation is logged as an MLflow span.

        Args:
            system: System message (used to inject the JSON schema).
            prompt: User message content.
            temperature: Sampling temperature passed to the model.

        Returns:
            A ``(response_text, usage)`` tuple.
        """
        ph = _prompt_hash(prompt)
        log.info(
            "llm_request",
            model=self._model,
            prompt_hash=ph,
            prompt_chars=len(prompt),
        )
        t0 = time.perf_counter()

        with mlflow.start_span(
            name=f"{type(self).__name__}._call_api",
            span_type=mlflow.entities.SpanType.LLM,
        ) as span:
            span.set_inputs(
                {"prompt": prompt[:_MAX_PROMPT_LOG_CHARS], "model": self._model}
            )

            # Build the reasoning control block. effort takes priority;
            # fall back to max_tokens; 0 tokens disables reasoning entirely.
            if self._reasoning_effort is not None:
                reasoning_cfg: dict[str, int | str] = {"effort": self._reasoning_effort}
            elif self._reasoning_max_tokens > 0:
                reasoning_cfg = {"max_tokens": self._reasoning_max_tokens}
            else:
                reasoning_cfg = {"effort": "none"}

            response = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                temperature=temperature,
                max_tokens=self._total_max_tokens,
                stream=False,
                timeout=_REQUEST_TIMEOUT_SEC,
                extra_body={"reasoning": reasoning_cfg},
            )

            text = response.choices[0].message.content or ""
            usage = response.usage
            latency_sec = round(time.perf_counter() - t0, 2)
            input_tokens = getattr(usage, "prompt_tokens", 0) or 0
            output_tokens = getattr(usage, "completion_tokens", 0) or 0
            # OpenRouter surfaces reasoning tokens under completion_tokens_details
            # (mirrors the OpenAI schema; field is optional).
            completion_details = getattr(usage, "completion_tokens_details", None)
            thinking_tokens = getattr(completion_details, "reasoning_tokens", 0) or 0
            total_tokens = input_tokens + output_tokens

            # OpenRouter returns actual USD cost in usage.cost (and a per-direction
            # breakdown in usage.cost_details). No static pricing table is needed.
            total_cost: float = getattr(usage, "cost", None) or 0.0
            cost_details = getattr(usage, "cost_details", None)
            input_cost: float = (
                getattr(cost_details, "upstream_inference_prompt_cost", None) or 0.0
            )
            output_cost: float = (
                getattr(cost_details, "upstream_inference_completions_cost", None)
                or 0.0
            )

            span.set_outputs({"response": text})
            span.set_attributes(
                {
                    SpanAttributeKey.MODEL: self._model,
                    SpanAttributeKey.CHAT_USAGE: {
                        TokenUsageKey.INPUT_TOKENS: input_tokens,
                        TokenUsageKey.OUTPUT_TOKENS: output_tokens,
                        TokenUsageKey.TOTAL_TOKENS: total_tokens,
                    },
                    SpanAttributeKey.LLM_COST: {
                        CostKey.INPUT_COST: input_cost,
                        CostKey.OUTPUT_COST: output_cost,
                        CostKey.TOTAL_COST: total_cost,
                    },
                    "input_tokens": input_tokens,
                    "input_cost_usd": input_cost,
                    "output_tokens": output_tokens,
                    "output_cost_usd": output_cost,
                    "thinking_tokens": thinking_tokens,
                    "total_tokens": total_tokens,
                    "total_cost_usd": total_cost,
                    "latency_sec": latency_sec,
                    "prompt_hash": ph,
                }
            )

        with self._stats_lock:
            self._total_input_tokens += input_tokens
            self._total_output_tokens += output_tokens
            self._total_thinking_tokens += thinking_tokens
            self._total_cost_usd += total_cost
            self._call_count += 1

        log.info(
            "llm_response",
            model=self._model,
            prompt_hash=ph,
            latency_sec=latency_sec,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            thinking_tokens=thinking_tokens,
            cost_usd=round(total_cost, 6),
        )
        return text, usage

    def _generate_contents(
        self,
        prompt: str,
        response_schema: type[BaseModel],
        temperature: float,
    ) -> BaseModel:
        """Call the API and validate the JSON response, repairing on failure.

        The JSON schema is injected into the system message. No
        ``response_format`` flag is sent — not all OpenRouter providers support
        it — so ``_extract_json`` strips any markdown code fences before
        validation.

        Args:
            prompt: User prompt text.
            response_schema: Pydantic model class for the expected response.
            temperature: Sampling temperature for the initial call.

        Returns:
            A validated instance of ``response_schema``.

        Raises:
            ValidationError: If the response cannot be repaired within
                ``_MAX_JSON_RETRIES`` attempts.
        """
        schema_json = json.dumps(response_schema.model_json_schema(), indent=2)
        system = (
            f"Respond with raw JSON only — no markdown, no code fences, no "
            f"explanation. The JSON must match this schema exactly:\n{schema_json}"
        )
        text, _ = self._call_api(system, prompt, temperature)

        for attempt in range(_MAX_JSON_RETRIES + 1):
            try:
                return response_schema.model_validate_json(_extract_json(text))
            except ValidationError as exc:
                if attempt == _MAX_JSON_RETRIES:
                    log.error("llm_json_unrecoverable", error=str(exc), response=text)
                    raise
                log.warning("llm_json_invalid", attempt=attempt + 1, error=str(exc))
                repair_prompt = (
                    f"Your previous response failed schema validation.\n"
                    f"Error: {exc}\n\n"
                    f"Return corrected JSON only. Previous response:\n{text}"
                )
                text, _ = self._call_api(system, repair_prompt, 0.0)
