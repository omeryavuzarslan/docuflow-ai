"""Base class for every model the LLM fills in through structured output."""

from typing import Any

from pydantic import ConfigDict

from backend.app.domain.types import DomainModel


def _all_required(schema: dict[str, Any]) -> None:
    schema["required"] = list(schema.get("properties", {}))


class LLMOutput(DomainModel):
    """Every property is listed as required in the JSON schema the model sees (the API
    limits optional fields and rejects schemas with many `anyOf`s as too complex), while
    Python code may still omit fields thanks to the defaults. Use "" / () for "absent"
    rather than None for the same reason."""

    model_config = ConfigDict(json_schema_extra=_all_required)
