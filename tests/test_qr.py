import base64
import struct

import pytest

from mail2pay.models import PaymentDetails
from mail2pay.qr import generate_qr_base64

_VALID = dict(amount="50.00", iban="BE68539007547034", communication="INV-001")


def _payment(**overrides) -> PaymentDetails:
    data = {**_VALID, **overrides}
    return PaymentDetails(**data)


def test_generate_returns_base64_png():
    qr_b64 = generate_qr_base64(_payment(), company_name="Test Corp")
    raw = base64.b64decode(qr_b64)
    # PNG magic bytes: 8-byte signature
    assert raw[:8] == b"\x89PNG\r\n\x1a\n", "Output is not a valid PNG"


def test_generate_is_nonempty():
    qr_b64 = generate_qr_base64(_payment(), company_name="Test Corp")
    assert len(qr_b64) > 100


def test_epc_string_contains_iban():
    """The EPC data string embedded in the QR code must contain the IBAN."""
    from mail2pay.qr import _EPC_TEMPLATE

    payment = _payment()
    epc_data = _EPC_TEMPLATE.format(
        bic="",
        name="Acme",
        iban=payment.iban,
        amount=payment.amount,
        communication=payment.communication,
    )
    assert payment.iban in epc_data, f"IBAN {payment.iban!r} not found in EPC string"
    assert f"EUR{payment.amount}" in epc_data
    assert payment.communication in epc_data
