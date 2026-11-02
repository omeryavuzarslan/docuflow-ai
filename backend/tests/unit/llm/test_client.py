from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel

from backend.app.llm.client import CacheKey, LLMClient, LLMRefusalError, cost_usd


class Answer(BaseModel):
    value: str


class FakeMessages:
    """Stands in for `anthropic.Anthropic().messages`; records calls, never hits the network."""

    def __init__(self, stop_reason: str = "end_turn") -> None:
        self.calls: list[dict[str, Any]] = []
        self.stop_reason = stop_reason

    def parse(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        return SimpleNamespace(
            parsed_output=Answer(value="42") if self.stop_reason == "end_turn" else None,
            stop_reason=self.stop_reason,
            usage=SimpleNamespace(
                input_tokens=1000,
                output_tokens=500,
                cache_read_input_tokens=0,
                cache_creation_input_tokens=0,
            ),
        )


def _client(tmp_path: Path, messages: FakeMessages) -> LLMClient:
    return LLMClient(cache_dir=tmp_path, anthropic_client=SimpleNamespace(messages=messages))


def _call(
    client: LLMClient, model: str = "claude-haiku-5-5", file: str = "a" * 64, text: str = "doc"
) -> Any:
    return client.parse(
        model=model,
        system="sys",
        user=text,
        output_format=Answer,
        cache_key=CacheKey(
            file_sha256=file, input_sha256=text, prompt_version="test-v1", model=model
        ),
    )


def test_first_call_hits_the_api_and_reports_cost(tmp_path: Path) -> None:
    messages = FakeMessages()
    result = _call(_client(tmp_path, messages))
    assert result.output == Answer(value="42")
    assert result.cached is False
    assert len(messages.calls) == 1
    assert messages.calls[0]["output_config"] == {"effort": "low"}
    # Haiku 5.5: $0.10 / $0.50 per million tokens
    assert result.usage.cost_usd == Decimal("0.00035")


def test_second_identical_call_is_served_from_disk_for_free(tmp_path: Path) -> None:
    messages = FakeMessages()
    _call(_client(tmp_path, messages))
    again = _call(_client(tmp_path, messages))  # new client: proves it's on disk
    assert again.cached is True
    assert again.output == Answer(value="42")
    assert len(messages.calls) == 1


@pytest.mark.parametrize("change", ["model", "file", "input"])
def test_cache_key_parts_each_force_a_new_call(tmp_path: Path, change: str) -> None:
    messages = FakeMessages()
    client = _client(tmp_path, messages)
    _call(client)
    if change == "model":
        _call(client, model="claude-opus-5-5")
    elif change == "file":
        _call(client, file="b" * 64)
    else:
        # Same file, different parser output: must not reuse the old answer.
        _call(client, text="doc parsed differently")
    assert len(messages.calls) == 2


def test_refusal_raises_and_is_not_cached(tmp_path: Path) -> None:
    messages = FakeMessages(stop_reason="refusal")
    client = _client(tmp_path, messages)
    with pytest.raises(LLMRefusalError):
        _call(client)
    assert list(tmp_path.iterdir()) == []


def test_cost_table() -> None:
    usage = {"input_tokens": 2_000_000, "output_tokens": 1_000_000}
    assert cost_usd("claude-opus-5-5", **usage) == Decimal("28.00")
    assert cost_usd("claude-sonnet-5-5", **usage) == Decimal("14.00")
    with pytest.raises(KeyError):
        cost_usd("gpt-4", **usage)
