"""Shared fixtures for autocutter tests."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def sample_transcript() -> list[dict[str, Any]]:
    return [
        {"id": 0, "start": 0.0, "end": 2.0, "text": "Hello there."},
        {"id": 1, "start": 2.0, "end": 5.0, "text": "This is filler."},
        {"id": 2, "start": 5.0, "end": 8.5, "text": "A strong punchline."},
    ]


@pytest.fixture
def mock_anthropic_text_message():
    """Build a fake Anthropic messages.create response with one text block."""

    def _make(text: str) -> MagicMock:
        block = MagicMock()
        block.type = "text"
        block.text = text
        message = MagicMock()
        message.content = [block]
        return message

    return _make
