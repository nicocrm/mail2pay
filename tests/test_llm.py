from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from mail2pay.llm import Extractor
from mail2pay.models import PaymentDetails


# ---------------------------------------------------------------------------
# Mock-based tests (always run)
# ---------------------------------------------------------------------------

def test_mock_extractor_calls_chat_completions_parse(mock_extractor):
    """Verify the correct API call shape."""
    expected = PaymentDetails(amount="50.00", iban="BE68539007547034", communication="INV-001")
    mock_extractor._mock_client.chat.parse.return_value.choices[0].message.parsed = expected

    result = mock_extractor.extract("some invoice text")

    call_kwargs = mock_extractor._mock_client.chat.parse.call_args
    assert call_kwargs.kwargs.get("response_format") is PaymentDetails
    assert result is expected


def test_mock_extractor_passes_correct_roles(mock_extractor):
    mock_extractor._mock_client.chat.parse.return_value.choices[0].message.parsed = PaymentDetails(
        amount="10.00", iban="BE68539007547034", communication="ref"
    )
    mock_extractor.extract("invoice text here")

    call_kwargs = mock_extractor._mock_client.chat.parse.call_args
    messages = call_kwargs.kwargs.get("messages")
    roles = [m["role"] for m in messages]
    assert roles == ["system", "user"]
    assert "invoice text here" in messages[1]["content"]


def test_mock_extractor_uses_configured_model(mock_extractor, cfg):
    mock_extractor._mock_client.chat.parse.return_value.choices[0].message.parsed = PaymentDetails(
        amount="1.00", iban="BE68539007547034", communication="x"
    )
    mock_extractor.extract("t")

    call_kwargs = mock_extractor._mock_client.chat.parse.call_args
    assert call_kwargs.kwargs.get("model") == cfg.llm_model


def test_mock_extractor_truncates_long_text(mock_extractor):
    mock_extractor._mock_client.chat.parse.return_value.choices[0].message.parsed = PaymentDetails(
        amount="1.00", iban="BE68539007547034", communication="x"
    )
    mock_extractor.extract("Z" * 20_000)

    messages = mock_extractor._mock_client.chat.parse.call_args.kwargs["messages"]
    assert messages[1]["content"].count("Z") == 10_000


def test_mock_extractor_raises_on_none_parsed(mock_extractor):
    mock_extractor._mock_client.chat.parse.return_value.choices[0].message.parsed = None
    with pytest.raises(ValueError):
        mock_extractor.extract("t")


# ---------------------------------------------------------------------------
# Live tests (skipped without MISTRAL_API_KEY)
# ---------------------------------------------------------------------------

def test_real_extractor_returns_plausible_result(real_extractor):
    from tests.fixtures.sample_invoice import SAMPLE_INVOICE

    result = real_extractor.extract(SAMPLE_INVOICE)

    assert result.iban.startswith("BE"), f"Expected Belgian IBAN, got {result.iban}"
    assert len(result.iban) == 16, f"IBAN wrong length: {result.iban}"
    assert Decimal(result.amount) > 0, f"Non-positive amount: {result.amount}"
    assert result.communication, "Empty communication"
