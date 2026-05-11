import hashlib
import os
import threading
import time
from pathlib import Path
from typing import Any

import mlflow
import mlflow.entities
import structlog
from google import genai
from google.genai import types
from mlflow.tracing.constant import CostKey, SpanAttributeKey, TokenUsageKey
from pydantic import BaseModel, ValidationError
from tenacity import retry, stop_after_attempt, wait_exponential

from lasagnastack.llm.base import LLMClient

log = structlog.get_logger()

# Number of follow-up re-prompts when Gemini returns malformed JSON before raising.
_MAX_JSON_RETRIES = 2
# Seconds between status polls while waiting for an uploaded file to become ACTIVE.
_FILE_POLL_INTERVAL_SEC = 3
# Truncate logged prompt text to keep MLflow traces a reasonable size.
_MAX_PROMPT_LOG_CHARS = 10000

# USD cost per 1 million tokens: {model_prefix: (input_cost, output_cost, thinking_cost)}.
# Matched by longest prefix so more-specific entries take priority.
# Text, image, and video input tokens are all billed at the same per-token rate.
# Thinking tokens are billed separately at their own rate (0.0 for models without thinking).
# Rates reflect the Standard paid tier as of May 2026 (ai.google.dev/gemini-api/docs/pricing).
_GEMINI_PRICING: dict[str, tuple[float, float, float]] = {
    "gemini-2.5-pro": (1.25, 10.00, 10.00),
    "gemini-2.5-flash-lite": (0.10, 0.40, 0.40),
    "gemini-2.5-flash": (0.30, 2.50, 2.50),
    "gemini-2.0-flash": (0.10, 0.40, 0.0),  # deprecated; shuts down 2026-06-01
}


def _prompt_hash(text: str) -> str:
    """Return a short SHA-256 hex digest of text for log correlation.

    Args:
        text: The string to hash.

    Returns:
        A 12-character hexadecimal digest.
    """
    return hashlib.sha256(text.encode()).hexdigest()[:12]


def _compute_cost(
    model: str, input_tokens: int, output_tokens: int, thinking_tokens: int = 0
) -> tuple[float, float, float, float]:
    """Estimate the USD cost of a Gemini API call from its token counts.

    Matches the model name against the longest known prefix in
    ``_GEMINI_PRICING``. Falls back to zero for unrecognised models so the
    pipeline never raises on a new model string.

    Args:
        model: Gemini model name, e.g. ``"gemini-2.5-flash"``.
        input_tokens: Number of prompt tokens consumed.
        output_tokens: Number of completion tokens generated.
        thinking_tokens: Number of thinking (reasoning) tokens generated.

    Returns:
        A ``(input_cost, output_cost, thinking_cost, total_cost)`` tuple in
        USD, or ``(0.0, 0.0, 0.0, 0.0)`` if the model is not in the pricing
        table.
    """
    for prefix in sorted(_GEMINI_PRICING, key=len, reverse=True):
        if model.startswith(prefix):
            input_cost_per_1m, output_cost_per_1m, thinking_cost_per_1m = (
                _GEMINI_PRICING[prefix]
            )
            input_cost = input_tokens * input_cost_per_1m / 1_000_000
            output_cost = output_tokens * output_cost_per_1m / 1_000_000
            thinking_cost = thinking_tokens * thinking_cost_per_1m / 1_000_000
            return (
                input_cost,
                output_cost,
                thinking_cost,
                input_cost + output_cost + thinking_cost,
            )
    return 0.0, 0.0, 0.0, 0.0


class GeminiClient(LLMClient):
    """LLM client backed by the Gemini Developer API.

    Wraps ``google-genai`` with structured JSON output, tenacity retries, a
    JSON-repair loop, and MLflow span tracing for every API call.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        thinking_budget: int = 4000,
    ) -> None:
        """Initialise the Gemini client.

        Args:
            api_key: Gemini Developer API key. Falls back to the
                ``GEMINI_API_KEY`` environment variable.
            model: Model name to use for all calls (LiteLLM naming convention).
                Falls back to the ``LASAGNASTACK_LLM_MODEL`` environment
                variable, then ``"gemini/gemini-2.5-flash"``.
            thinking_budget: Maximum number of thinking tokens the model may
                use per call. Set to ``0`` to disable thinking entirely.
        """
        raw_model = model or os.getenv(
            "LASAGNASTACK_LLM_MODEL", "gemini/gemini-2.5-flash"
        )
        self._model = raw_model.removeprefix("gemini/")
        resolved_key = api_key or os.getenv("GEMINI_API_KEY")
        if not resolved_key:
            raise ValueError(
                "Gemini API key not found. Set GEMINI_API_KEY in .env or pass api_key=."
            )
        self._client = genai.Client(api_key=resolved_key)
        self._thinking_budget = thinking_budget

        # Per-instance accumulators — updated after every successful API call.
        self._total_input_tokens: int = 0
        self._total_output_tokens: int = 0
        self._total_thinking_tokens: int = 0
        self._total_cost_usd: float = 0.0
        self._call_count: int = 0
        self._stats_lock = threading.Lock()

    # ── public interface ────────────────────────────────────────────────────

    @property
    def session_stats(self) -> dict[str, float | int]:
        """Aggregated token and cost totals across all calls on this instance.

        Returns:
            A dict with keys ``total_input_tokens``, ``total_output_tokens``,
            ``total_cost_usd``, and ``llm_call_count``.
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
        """Upload video_path to the Files API, generate, return validated response.

        Args:
            video_path: Local path to the MP4 clip to analyse.
            prompt: Text prompt sent alongside the video.
            response_schema: Pydantic model class for the expected JSON response.
            temperature: Sampling temperature passed to the model.

        Returns:
            A validated instance of ``response_schema``.
        """
        file_ref = self._upload_and_wait(video_path)
        try:
            contents = [
                types.Part.from_uri(file_uri=file_ref.uri, mime_type="video/mp4"),
                prompt,
            ]
            return self._generate_contents(contents, response_schema, temperature)
        finally:
            self._delete_file(file_ref.name)

    # ── internals ───────────────────────────────────────────────────────────

    def _upload_and_wait(self, path: Path) -> Any:
        """Upload a local file to the Gemini Files API and poll until ACTIVE.

        Args:
            path: Local path to the file to upload.

        Returns:
            The active ``File`` resource returned by the Files API.

        Raises:
            RuntimeError: If the file does not reach the ACTIVE state.
        """
        log.info(
            "files_upload_start",
            path=path.name,
            size_mb=round(path.stat().st_size / 1e6, 1),
        )
        with path.open("rb") as fh:
            file_ref = self._client.files.upload(
                file=fh,
                config=types.UploadFileConfig(
                    mime_type="video/mp4",
                    display_name=path.name,
                ),
            )
        # Poll until ACTIVE; files go through PROCESSING before becoming usable
        while getattr(getattr(file_ref, "state", None), "name", None) == "PROCESSING":
            log.debug("files_waiting", name=file_ref.name)
            time.sleep(_FILE_POLL_INTERVAL_SEC)
            file_ref = self._client.files.get(
                name=file_ref.name  # pyrefly: ignore[bad-argument-type]
            )

        state_name = getattr(getattr(file_ref, "state", None), "name", "UNKNOWN")
        if state_name not in {"ACTIVE", "UNKNOWN"}:
            raise RuntimeError(
                f"File {file_ref.name} did not reach ACTIVE state: {state_name}"
            )
        log.info(
            "files_upload_done", name=file_ref.name, uri=getattr(file_ref, "uri", "")
        )
        return file_ref

    def _delete_file(self, name: str) -> None:
        """Delete a file from the Gemini Files API, logging a warning on failure.

        Args:
            name: The Files API resource name of the file to delete.
        """
        try:
            self._client.files.delete(name=name)
            log.debug("files_deleted", name=name)
        except Exception:
            log.warning("files_delete_failed", name=name)

    @retry(
        stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=30)
    )
    def _call_api(
        self,
        contents: Any,
        response_schema: type[BaseModel],
        temperature: float,
    ) -> tuple[str, Any]:
        """Raw API call with retry. Each invocation is logged as an MLflow span.

        Retried by tenacity on any exception (network, rate-limit, etc.).

        Args:
            contents: Text string or list of ``types.Part`` objects to send.
            response_schema: Pydantic model class for structured JSON output.
            temperature: Sampling temperature passed to the model.

        Returns:
            A ``(response_text, usage_metadata)`` tuple.
        """
        ph = _prompt_hash(str(contents))
        log.info("llm_request", model=self._model, prompt_hash=ph)
        t0 = time.perf_counter()

        with mlflow.start_span(
            name=f"{type(self).__name__}._call_api",
            span_type=mlflow.entities.SpanType.LLM,
        ) as span:
            span.set_inputs(
                {"prompt": str(contents)[:_MAX_PROMPT_LOG_CHARS], "model": self._model}
            )

            response = self._client.models.generate_content(
                model=self._model,
                contents=contents,
                config=types.GenerateContentConfig(
                    temperature=temperature,
                    response_mime_type="application/json",
                    response_schema=response_schema,
                    thinking_config=types.ThinkingConfig(
                        thinking_budget=self._thinking_budget
                    ),
                ),
            )

            usage = response.usage_metadata
            latency_sec = round(time.perf_counter() - t0, 2)
            input_tokens = getattr(usage, "prompt_token_count", 0) or 0
            output_tokens = getattr(usage, "candidates_token_count", 0) or 0
            thinking_tokens = getattr(usage, "thoughts_token_count", 0) or 0
            total_tokens = input_tokens + output_tokens + thinking_tokens
            input_cost, output_cost, thinking_cost, total_cost = _compute_cost(
                self._model, input_tokens, output_tokens, thinking_tokens
            )

            span.set_outputs({"response": response.text})
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
                    # NOTE: These are custom fields that will show up in the "Attributes" tab in the MLflow UI.
                    "input_tokens": input_tokens,
                    "input_cost_usd": input_cost,
                    "output_tokens": output_tokens,
                    "output_cost_usd": output_cost,
                    "thinking_tokens": thinking_tokens,
                    "thinking_cost_usd": thinking_cost,
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
        return response.text, usage

    def _generate_contents(
        self,
        contents: Any,
        response_schema: type[BaseModel],
        temperature: float,
    ) -> BaseModel:
        """Call the API and validate the JSON response, repairing on failure.

        Args:
            contents: Text string or list of ``types.Part`` objects to send.
            response_schema: Pydantic model class for the expected response.
            temperature: Sampling temperature for the initial call.

        Returns:
            A validated instance of ``response_schema``.

        Raises:
            ValidationError: If the response cannot be repaired within
                ``_MAX_JSON_RETRIES`` attempts.
        """
        text, _ = self._call_api(contents, response_schema, temperature)

        for attempt in range(_MAX_JSON_RETRIES + 1):
            try:
                return response_schema.model_validate_json(text)
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
                text, _ = self._call_api(repair_prompt, response_schema, 0.0)
