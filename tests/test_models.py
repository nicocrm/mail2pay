"""Unit tests for PaymentDetails validators."""
import pytest
from pydantic import ValidationError

from mail2pay.models import PaymentDetails


# ---------------------------------------------------------------------------
# amount
# ---------------------------------------------------------------------------

def test_amount_valid():
    p = PaymentDetails(amount="50", iban="BE68539007547034", communication="ref")
    assert p.amount == "50.00"


def test_amount_with_decimals():
    p = PaymentDetails(amount="1250.5", iban="BE68539007547034", communication="ref")
    assert p.amount == "1250.50"


def test_amount_strips_whitespace():
    p = PaymentDetails(amount="  99.99  ", iban="BE68539007547034", communication="ref")
    assert p.amount == "99.99"


def test_amount_zero_rejected():
    with pytest.raises(ValidationError, match="positive"):
        PaymentDetails(amount="0", iban="BE68539007547034", communication="ref")


def test_amount_negative_rejected():
    with pytest.raises(ValidationError, match="positive"):
        PaymentDetails(amount="-10.00", iban="BE68539007547034", communication="ref")


def test_amount_non_numeric_rejected():
    with pytest.raises(ValidationError, match="Invalid amount"):
        PaymentDetails(amount="abc", iban="BE68539007547034", communication="ref")


# ---------------------------------------------------------------------------
# iban
# ---------------------------------------------------------------------------

def test_iban_valid():
    p = PaymentDetails(amount="10.00", iban="BE68539007547034", communication="ref")
    assert p.iban == "BE68539007547034"


def test_iban_strips_spaces():
    p = PaymentDetails(amount="10.00", iban="BE68 5390 0754 7034", communication="ref")
    assert p.iban == "BE68539007547034"


def test_iban_uppercased():
    p = PaymentDetails(amount="10.00", iban="be68539007547034", communication="ref")
    assert p.iban == "BE68539007547034"


def test_iban_non_belgian_rejected():
    with pytest.raises(ValidationError, match="BE"):
        PaymentDetails(amount="10.00", iban="NL91ABNA0417164300", communication="ref")


def test_iban_wrong_length_rejected():
    with pytest.raises(ValidationError, match="16 chars"):
        PaymentDetails(amount="10.00", iban="BE685390075470", communication="ref")


# ---------------------------------------------------------------------------
# communication
# ---------------------------------------------------------------------------

def test_communication_normal():
    p = PaymentDetails(amount="10.00", iban="BE68539007547034", communication="INV-001")
    assert p.communication == "INV-001"


def test_communication_stripped():
    p = PaymentDetails(amount="10.00", iban="BE68539007547034", communication="  ref  ")
    assert p.communication == "ref"


def test_communication_truncated_at_140():
    long_ref = "X" * 200
    p = PaymentDetails(amount="10.00", iban="BE68539007547034", communication=long_ref)
    assert len(p.communication) == 140
    assert p.communication == "X" * 140
