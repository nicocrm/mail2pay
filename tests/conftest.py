"""
Shared fixtures for the test suite.
"""
from unittest.mock import MagicMock

import pytest

from mail2pay.config import Config
from mail2pay.llm import Extractor


def _make_cfg(**overrides) -> Config:
    defaults = dict(
        RESEND_API_KEY="test-resend-key",
        MISTRAL_API_KEY="test-mistral-key",
        COMPANY_NAME="Test Corp",
        FROM_ADDRESS="noreply@example.com",
        LLM_MODEL="mistral-small-latest",
        RESEND_WEBHOOK_SECRET="whsec_dGVzdHNlY3JldA==",
    )
    defaults.update(overrides)
    return Config(**defaults)


@pytest.fixture
def cfg():
    return _make_cfg()


@pytest.fixture
def mock_extractor(cfg):
    """Extractor backed by a MagicMock Mistral client."""
    client = MagicMock()
    extractor = Extractor(cfg, client=client)
    extractor._mock_client = client  # expose for assertions  # ty: ignore[unresolved-attribute]
    return extractor


@pytest.fixture
def real_extractor():
    """Extractor with a real Mistral client – reads MISTRAL_API_KEY from env or .env."""
    try:
        real_cfg = Config()  # ty: ignore[missing-argument]  # reads .env automatically
    except Exception as exc:
        pytest.skip(f"Config could not be loaded – skipping live LLM test ({exc})")
    if not real_cfg.mistral_api_key or real_cfg.mistral_api_key.startswith("test-"):
        pytest.skip("MISTRAL_API_KEY not set – skipping live LLM test")
    return Extractor(real_cfg)
