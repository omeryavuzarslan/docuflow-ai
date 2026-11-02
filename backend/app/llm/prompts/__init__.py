"""Versioned prompts. A prompt file is never edited once results depend on it: changes go
into a new version (extract-v2.md, ...), so cached responses and recorded experiments stay
tied to the exact text that produced them."""

from pathlib import Path

PROMPT_DIR = Path(__file__).parent


def load_prompt(version: str) -> str:
    return (PROMPT_DIR / f"{version}.md").read_text(encoding="utf-8")
