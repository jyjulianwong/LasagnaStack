import hashlib
import os
import time
from pathlib import Path
from typing import Any

import structlog
from google import genai
from google.genai import types
from pydantic import BaseModel, ValidationError
from tenacity import retry, stop_after_attempt, wait_exponential

from lasagnastack.llm.base import LLMClient

log = structlog.get_logger()

_MAX_JSON_RETRIES = 2
_FILE_POLL_INTERVAL_S = 3


def _prompt_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:12]


class GeminiClient(LLMClient):
    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
    ) -> None:
        self._model = model or os.getenv("LASAGNASTACK_MODEL", "gemini-2.5-flash")
        resolved_key = api_key or os.getenv("GEMINI_API_KEY")
        if not resolved_key:
            raise ValueError(
                "Gemini API key not found. Set GEMINI_API_KEY in .env or pass api_key=."
            )
        self._client = genai.Client(api_key=resolved_key)

    # ── public interface ────────────────────────────────────────────────────

    def generate(
        self,
        prompt: str,
        response_schema: type[BaseModel],
        *,
        temperature: float = 0.4,
    ) -> BaseModel:
        return self._generate_contents(prompt, response_schema, temperature)

    def generate_with_video(
        self,
        video_path: Path,
        prompt: str,
        response_schema: type[BaseModel],
        *,
        temperature: float = 0.4,
    ) -> BaseModel:
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
            time.sleep(_FILE_POLL_INTERVAL_S)
            file_ref = self._client.files.get(name=file_ref.name)

        state_name = getattr(getattr(file_ref, "state", None), "name", "UNKNOWN")
        if state_name not in {"ACTIVE", "UNKNOWN"}:
            raise RuntimeError(
                f"File {file_ref.name} did not reach ACTIVE state: {state_name}"
            )
        log.info("files_upload_done", name=file_ref.name, uri=getattr(file_ref, "uri", ""))
        return file_ref

    def _delete_file(self, name: str) -> None:
        try:
            self._client.files.delete(name=name)
            log.debug("files_deleted", name=name)
        except Exception:
            log.warning("files_delete_failed", name=name)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=30))
    def _call_api(
        self,
        contents: Any,
        response_schema: type[BaseModel],
        temperature: float,
    ) -> tuple[str, Any]:
        """Raw API call. Retried by tenacity on any exception (network, rate-limit, etc.)."""
        t0 = time.perf_counter()
        ph = _prompt_hash(str(contents))
        log.info("llm_request", model=self._model, prompt_hash=ph)

        response = self._client.models.generate_content(
            model=self._model,
            contents=contents,
            config=types.GenerateContentConfig(
                temperature=temperature,
                response_mime_type="application/json",
                response_schema=response_schema,
            ),
        )

        usage = response.usage_metadata
        log.info(
            "llm_response",
            model=self._model,
            prompt_hash=ph,
            latency_s=round(time.perf_counter() - t0, 2),
            input_tokens=getattr(usage, "prompt_token_count", None),
            output_tokens=getattr(usage, "candidates_token_count", None),
        )
        return response.text, usage

    def _generate_contents(
        self,
        contents: Any,
        response_schema: type[BaseModel],
        temperature: float,
    ) -> BaseModel:
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
