from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from mail2pay.llm import Extractor
from mail2pay.models import PaymentDetails


# ---------------------------------------------------------------------------
# Mock-based tests (always run)
# ---------------------------------------------------------------------------

def test_mock_extractor_calls_responses_parse(mock_extractor):
    """Verify the correct API call shape."""
    expected = PaymentDetails(amount="50.00", iban="BE68539007547034", communication="INV-001")
    mock_extractor._mock_client.responses.parse.return_value.output_parsed = expected

    result = mock_extractor.extract("some invoice text")

    call_kwargs = mock_extractor._mock_client.responses.parse.call_args
    assert call_kwargs.kwargs.get("text_format") is PaymentDetails or \
           (call_kwargs.args and PaymentDetails in call_kwargs.args)
    assert result is expected


def test_mock_extractor_passes_correct_roles(mock_extractor):
    mock_extractor._mock_client.responses.parse.return_value.output_parsed = PaymentDetails(
        amount="10.00", iban="BE68539007547034", communication="ref"
    )
    mock_extractor.extract("invoice text here")

    call_kwargs = mock_extractor._mock_client.responses.parse.call_args
    # Accept both positional and keyword 'input'
    input_messages = call_kwargs.kwargs.get("input") or call_kwargs.kwargs.get("messages")
    roles = [m["role"] for m in input_messages]
    assert roles == ["system", "user"]
    user_content = input_messages[1]["content"]
    assert "invoice text here" in user_content


def test_mock_extractor_uses_configured_model(mock_extractor, cfg):
    mock_extractor._mock_client.responses.parse.return_value.output_parsed = PaymentDetails(
        amount="1.00", iban="BE68539007547034", communication="x"
    )
    mock_extractor.extract("t")

    call_kwargs = mock_extractor._mock_client.responses.parse.call_args
    model_arg = call_kwargs.kwargs.get("model") or call_kwargs.args[0]
    assert model_arg == cfg.openai_model


# ---------------------------------------------------------------------------
# Live tests (skipped without OPENAI_API_KEY)
# ---------------------------------------------------------------------------

def test_real_extractor_returns_plausible_result(real_extractor):
    from tests.fixtures.sample_invoice import SAMPLE_INVOICE

    result = real_extractor.extract(SAMPLE_INVOICE)

    assert result.iban.startswith("BE"), f"Expected Belgian IBAN, got {result.iban}"
    assert len(result.iban) == 16, f"IBAN wrong length: {result.iban}"
    assert Decimal(result.amount) > 0, f"Non-positive amount: {result.amount}"
    assert result.communication, "Empty communication"
