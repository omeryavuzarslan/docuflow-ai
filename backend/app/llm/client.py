"""The one place the app talks to Claude.

- Structured output: `messages.parse(output_format=Model)` returns a validated Pydantic
  object, so there is no hand-written JSON parsing.
- Disk cache keyed by (file sha256, prompt version, model): re-running an evaluation, or
  re-processing a file, costs nothing unless the prompt or the model changes.
- Cost: every call reports its tokens and USD cost (Decimal, like all money here).

The Anthropic client is created on the first real call, so tests and cache-only runs work
without an API key.
"""

import hashlib
import json
import os
import time
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from backend.app.domain.types import DomainModel

# USD per million tokens: (input, output, cache read, cache write). Anthropic list prices,
# checked 2026-11-01. Haiku 5.5 doubles above 100K-token prompts; ours are far smaller.
PRICES: dict[str, tuple[Decimal, Decimal, Decimal, Decimal]] = {
    "claude-opus-5-5": (Decimal("4"), Decimal("20"), Decimal("0.20"), Decimal("5")),
    "claude-sonnet-5-5": (Decimal("2"), Decimal("10"), Decimal("0.20"), Decimal("2.50")),
    "claude-haiku-5-5": (Decimal("0.10"), Decimal("0.50"), Decimal("0.01"), Decimal("0.125")),
}
_PER_TOKEN = Decimal(1_000_000)


def cost_usd(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_input_tokens: int = 0,
    cache_creation_input_tokens: int = 0,
) -> Decimal:
    inp, out, read, write = PRICES[model]
    return (
        input_tokens * inp
        + output_tokens * out
        + cache_read_input_tokens * read
        + cache_creation_input_tokens * write
    ) / _PER_TOKEN


class LLMUsage(DomainModel):
    input_tokens: int
    output_tokens: int  # includes thinking tokens, which are billed as output
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cost_usd: Decimal


@dataclass(frozen=True)
class CacheKey:
    """What a cached response depends on.

    `file_sha256` names the source document; `input_sha256` is the hash of the text actually
    sent. The second is needed because the same file can produce different input when the
    parser changes, and a cache keyed on the file alone would then return stale answers.
    """

    file_sha256: str
    input_sha256: str
    prompt_version: str
    model: str

    def digest(self) -> str:
        raw = f"{self.file_sha256}|{self.input_sha256}|{self.prompt_version}|{self.model}"
        return hashlib.sha256(raw.encode()).hexdigest()


@dataclass(frozen=True)
class LLMResult[T: BaseModel]:
    output: T
    usage: LLMUsage
    model: str
    cached: bool  # True: served from disk, nothing was spent on this call
    seconds: float


class LLMError(RuntimeError):
    pass


class LLMRefusalError(LLMError):
    """The model declined (stop_reason "refusal"). Not cached, so a retry can succeed."""


class CacheOnlyClient:
    """Use in place of the Anthropic client to guarantee no paid call is made: any request
    that is not already cached fails instead of reaching the API."""

    @property
    def messages(self) -> "CacheOnlyClient":
        return self

    def parse(self, **_: Any) -> Any:
        raise LLMError("response not cached and --cache-only is set; no API call made")


class LLMClient:
    def __init__(self, cache_dir: Path, anthropic_client: Any = None) -> None:
        self.cache_dir = cache_dir
        self._anthropic_client = anthropic_client

    def parse[T: BaseModel](
        self,
        *,
        model: str,
        system: str,
        user: str,
        output_format: type[T],
        cache_key: CacheKey,
        effort: str = "low",
        max_tokens: int = 16_000,
    ) -> LLMResult[T]:
        path = self.cache_dir / f"{cache_key.digest()}.json"
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            return LLMResult(
                output=output_format.model_validate(data["output"]),
                usage=LLMUsage.model_validate(data["usage"]),
                model=model,
                cached=True,
                seconds=data["seconds"],
            )

        start = time.perf_counter()
        response = self._client().messages.parse(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_format=output_format,
            # Extraction is copying, not reasoning: low effort keeps thinking (and cost) small.
            output_config={"effort": effort},
        )
        seconds = round(time.perf_counter() - start, 2)

        if response.stop_reason == "refusal":
            raise LLMRefusalError(f"{model} declined the request")
        if response.stop_reason == "max_tokens" or response.parsed_output is None:
            raise LLMError(
                f"{model} returned no usable output (stop_reason={response.stop_reason})"
            )

        u = response.usage
        tokens = {
            "input_tokens": u.input_tokens,
            "output_tokens": u.output_tokens,
            "cache_read_input_tokens": u.cache_read_input_tokens or 0,
            "cache_creation_input_tokens": u.cache_creation_input_tokens or 0,
        }
        usage = LLMUsage(**tokens, cost_usd=cost_usd(model, **tokens))
        output: T = response.parsed_output
        self._write_cache(path, cache_key, output, usage, seconds)
        return LLMResult(output=output, usage=usage, model=model, cached=False, seconds=seconds)

    def _client(self) -> Any:
        if self._anthropic_client is None:
            import anthropic

            if not os.environ.get("ANTHROPIC_API_KEY"):
                raise LLMError("ANTHROPIC_API_KEY is not set; run with `uv run --env-file .env`")
            self._anthropic_client = anthropic.Anthropic()
        return self._anthropic_client

    def _write_cache(
        self, path: Path, key: CacheKey, output: BaseModel, usage: LLMUsage, seconds: float
    ) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        data = {
            "key": {
                "file_sha256": key.file_sha256,
                "input_sha256": key.input_sha256,
                "prompt_version": key.prompt_version,
                "model": key.model,
            },
            "output": output.model_dump(mode="json"),
            "usage": usage.model_dump(mode="json"),
            "seconds": seconds,
        }
        # Write then rename, so an interrupted run never leaves a half-written cache entry.
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
