"""
Shared fixtures for the test suite.
"""
import os
from unittest.mock import MagicMock

import pytest

from mail2pay.config import Config
from mail2pay.llm import Extractor


def _make_cfg(**overrides) -> Config:
    defaults = dict(
        RESEND_API_KEY="test-resend-key",
        OPENROUTER_API_KEY="test-openrouter-key",
        COMPANY_NAME="Test Corp",
        FROM_ADDRESS="noreply@example.com",
        OPENROUTER_MODEL="mistralai/mistral-small-2603",
        RESEND_WEBHOOK_SECRET="whsec_dGVzdHNlY3JldA==",
    )
    defaults.update(overrides)
    return Config(**defaults)


@pytest.fixture
def cfg():
    return _make_cfg()


@pytest.fixture
def mock_extractor(cfg):
    """Extractor backed by a MagicMock OpenAI client."""
    client = MagicMock()
    extractor = Extractor(cfg, client=client)
    extractor._mock_client = client  # expose for assertions  # ty: ignore[unresolved-attribute]
    return extractor


@pytest.fixture
def real_extractor(cfg):
    """Extractor with a real OpenRouter client – skipped when key absent."""
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        pytest.skip("OPENROUTER_API_KEY not set – skipping live LLM test")
    real_cfg = _make_cfg(OPENROUTER_API_KEY=api_key)
    return Extractor(real_cfg)
