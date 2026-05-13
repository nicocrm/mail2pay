import pytest
from pydantic import ValidationError

from mail2pay.config import Config


def test_config_loads_from_env(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "r-key")
    monkeypatch.setenv("MISTRAL_API_KEY", "mi-key")
    monkeypatch.setenv("COMPANY_NAME", "Acme")
    monkeypatch.setenv("FROM_ADDRESS", "no@reply.com")
    monkeypatch.setenv("RESEND_WEBHOOK_SECRET", "whsec_abc")

    cfg = Config()  # ty: ignore[missing-argument]
    assert cfg.resend_api_key == "r-key"
    assert cfg.mistral_api_key == "mi-key"
    assert cfg.company_name == "Acme"
    assert cfg.from_address == "no@reply.com"
    assert cfg.llm_model == "mistral-small-latest"
    assert cfg.webhook_secret == "whsec_abc"


def test_config_default_model_overridable(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "r")
    monkeypatch.setenv("MISTRAL_API_KEY", "mi")
    monkeypatch.setenv("COMPANY_NAME", "C")
    monkeypatch.setenv("FROM_ADDRESS", "f@f.com")
    monkeypatch.setenv("RESEND_WEBHOOK_SECRET", "whsec_abc")
    monkeypatch.setenv("LLM_MODEL", "mistral-large-latest")

    cfg = Config()  # ty: ignore[missing-argument]
    assert cfg.llm_model == "mistral-large-latest"


def test_config_missing_required_key(monkeypatch):
    # Remove all relevant env vars
    for var in ("RESEND_API_KEY", "MISTRAL_API_KEY", "COMPANY_NAME", "FROM_ADDRESS", "RESEND_WEBHOOK_SECRET"):
        monkeypatch.delenv(var, raising=False)

    with pytest.raises((ValidationError, Exception)):
        Config()  # ty: ignore[missing-argument]


def test_config_mistral_fields(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "r")
    monkeypatch.setenv("MISTRAL_API_KEY", "mi-key")
    monkeypatch.setenv("COMPANY_NAME", "C")
    monkeypatch.setenv("FROM_ADDRESS", "f@f.com")
    monkeypatch.setenv("RESEND_WEBHOOK_SECRET", "wh")

    cfg = Config()  # ty: ignore[missing-argument]
    assert cfg.mistral_api_key == "mi-key"
    assert cfg.llm_model == "mistral-small-latest"


def test_config_no_longer_has_openai_api_key():
    assert "openai_api_key" not in Config.model_fields
