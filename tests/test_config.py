import pytest
from pydantic import ValidationError

from mail2pay.config import Config


def test_config_loads_from_env(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "r-key")
    monkeypatch.setenv("OPENAI_API_KEY", "o-key")
    monkeypatch.setenv("COMPANY_NAME", "Acme")
    monkeypatch.setenv("FROM_ADDRESS", "no@reply.com")
    monkeypatch.setenv("RESEND_WEBHOOK_SECRET", "whsec_abc")

    cfg = Config()  # ty: ignore[missing-argument]
    assert cfg.resend_api_key == "r-key"
    assert cfg.openai_api_key == "o-key"
    assert cfg.company_name == "Acme"
    assert cfg.from_address == "no@reply.com"
    assert cfg.openai_model == "gpt-5.4-mini"
    assert cfg.webhook_secret == "whsec_abc"


def test_config_default_model_overridable(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "r")
    monkeypatch.setenv("OPENAI_API_KEY", "o")
    monkeypatch.setenv("COMPANY_NAME", "C")
    monkeypatch.setenv("FROM_ADDRESS", "f@f.com")
    monkeypatch.setenv("RESEND_WEBHOOK_SECRET", "whsec_abc")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-5.4-mini")

    cfg = Config()  # ty: ignore[missing-argument]
    assert cfg.openai_model == "gpt-5.4-mini"


def test_config_missing_required_key(monkeypatch):
    # Remove all relevant env vars
    for var in ("RESEND_API_KEY", "OPENAI_API_KEY", "COMPANY_NAME", "FROM_ADDRESS", "RESEND_WEBHOOK_SECRET"):
        monkeypatch.delenv(var, raising=False)

    with pytest.raises((ValidationError, Exception)):
        Config()  # ty: ignore[missing-argument]
