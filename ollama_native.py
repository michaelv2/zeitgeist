"""pydantic-ai model that speaks Ollama's native /api/chat endpoint.

pydantic-ai ships `OllamaModel`, but it subclasses `OpenAIChatModel` and talks
to Ollama's OpenAI-compatible `/v1/chat/completions`. That layer accepts and
then **silently discards** `think` and `reasoning_effort`, so a reasoning model
(qwen3.x) spends the whole `max_tokens` budget emitting `<think>` and returns no
answer at all — surfacing as `UnexpectedModelBehavior: Model token limit
exceeded before any response was generated`.

Measured against Ollama 0.20.0 with qwen3.8:27b on a one-word prompt:

    /v1/chat/completions  think=false   -> 26 output tokens, 88 chars reasoning
    /api/chat             think=false   ->  2 output tokens,  0 chars reasoning

The native endpoint is the only place the flag is honoured, hence this class.
It also takes a JSON schema in `format`, which llama.cpp enforces with
grammar-constrained decoding, so structured output still works.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    RetryPromptPart,
    SystemPromptPart,
    TextPart,
    ThinkingPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models import Model, ModelRequestParameters
from pydantic_ai.profiles import ModelProfile
from pydantic_ai.settings import ModelSettings
from pydantic_ai.usage import RequestUsage

__all__ = ("NativeOllamaModel",)

DEFAULT_BASE_URL = "http://localhost:11434"


def _part_to_text(part: Any) -> str:
    """Flatten a prompt part's content to text.

    Multi-modal content arrives as a list; this project only sends text, so
    anything else is stringified rather than silently dropped.
    """
    content = getattr(part, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(c if isinstance(c, str) else str(c) for c in content)
    return str(content)


def _map_messages(messages: list[ModelMessage]) -> list[dict[str, str]]:
    """Translate pydantic-ai messages into Ollama's chat format."""
    out: list[dict[str, str]] = []
    for message in messages:
        if isinstance(message, ModelRequest):
            if message.instructions:
                out.append({"role": "system", "content": message.instructions})
            for part in message.parts:
                if isinstance(part, SystemPromptPart):
                    out.append({"role": "system", "content": _part_to_text(part)})
                elif isinstance(part, UserPromptPart):
                    out.append({"role": "user", "content": _part_to_text(part)})
                elif isinstance(part, (ToolReturnPart, RetryPromptPart)):
                    # No tool-calling round trip here; fold the correction back
                    # in as a user turn so retries still reach the model.
                    out.append({"role": "user", "content": _part_to_text(part)})
        elif isinstance(message, ModelResponse):
            text = "".join(p.content for p in message.parts if isinstance(p, TextPart))
            if text:
                out.append({"role": "assistant", "content": text})
    return out


@dataclass(init=False)
class NativeOllamaModel(Model):
    """Ollama via the native API, with working reasoning control.

    Args:
        model_name: Ollama tag, e.g. ``qwen3.8:27b``.
        base_url: Ollama host root, without ``/v1``.
        think: ``False`` suppresses reasoning, ``True`` forces it on, ``None``
            leaves the model default. This is the whole point of the class.
        num_ctx: Context window. Ollama's server default is small (4096 unless
            ``OLLAMA_CONTEXT_LENGTH`` says otherwise) and the *prompt* counts
            against it, so a batch prompt can leave a reasoning model too few
            tokens to answer in — it spends them all on ``<think>`` and returns
            nothing. Default here is large enough for batch classification.
        timeout: Per-request timeout in seconds. Reasoning models are slow, so
            this defaults well above httpx's own default.
    """

    _model_name: str
    _base_url: str
    _think: bool | None
    _num_ctx: int | None
    _timeout: float

    def __init__(
        self,
        model_name: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        think: bool | None = None,
        num_ctx: int | None = 32768,
        timeout: float = 600.0,
        settings: ModelSettings | None = None,
    ) -> None:
        super().__init__(
            settings=settings,
            profile=ModelProfile(
                supports_json_schema_output=True,
                default_structured_output_mode="native",
                supports_thinking=True,
            ),
        )
        self._model_name = model_name
        self._base_url = base_url.rstrip("/").removesuffix("/v1")
        self._think = think
        self._num_ctx = num_ctx
        self._timeout = timeout

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def system(self) -> str:
        return "ollama"

    @property
    def base_url(self) -> str:
        return self._base_url

    def _build_payload(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        params: ModelRequestParameters,
    ) -> dict[str, Any]:
        settings = model_settings or {}
        options: dict[str, Any] = {}
        if (temperature := settings.get("temperature")) is not None:
            options["temperature"] = temperature
        # OpenAI calls it max_tokens; Ollama calls it num_predict.
        if (max_tokens := settings.get("max_tokens")) is not None:
            options["num_predict"] = max_tokens
        if self._num_ctx is not None:
            options["num_ctx"] = self._num_ctx

        payload: dict[str, Any] = {
            "model": self._model_name,
            "messages": _map_messages(messages),
            "stream": False,
        }
        if options:
            payload["options"] = options
        if self._think is not None:
            payload["think"] = self._think
        if params.output_object is not None:
            # llama.cpp enforces this with grammar-constrained decoding.
            payload["format"] = params.output_object.json_schema
        return payload

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        payload = self._build_payload(messages, model_settings, model_request_parameters)

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(f"{self._base_url}/api/chat", json=payload)
            if response.status_code == 400 and "does not support thinking" in response.text:
                # Asking a non-reasoning model to think is a 400. Drop the flag
                # and retry rather than failing a call the model could serve.
                payload.pop("think", None)
                response = await client.post(f"{self._base_url}/api/chat", json=payload)
            response.raise_for_status()
            data = response.json()

        message = data.get("message") or {}
        content = message.get("content") or ""
        thinking = message.get("thinking") or ""

        if not content:
            # The failure this class exists to prevent: budget spent thinking.
            # Say so, instead of returning an empty response that surfaces as an
            # opaque parse error downstream.
            raise RuntimeError(
                f"{self._model_name} returned no content "
                f"({len(thinking)} chars of reasoning, "
                f"{data.get('eval_count')} tokens). Raise max_tokens or set think=False."
            )

        parts: list[Any] = []
        if thinking:
            parts.append(ThinkingPart(content=thinking))
        parts.append(TextPart(content=content))

        return ModelResponse(
            parts=parts,
            usage=RequestUsage(
                input_tokens=data.get("prompt_eval_count") or 0,
                output_tokens=data.get("eval_count") or 0,
            ),
            model_name=self._model_name,
            timestamp=datetime.now(tz=timezone.utc),
            provider_name="ollama",
            provider_url=self._base_url,
            finish_reason="stop" if data.get("done") else None,
        )
