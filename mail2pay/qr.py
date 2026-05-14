import base64
from io import BytesIO

import segno

from .models import PaymentDetails

# EPC QR Code version 002 – SCT (SEPA Credit Transfer)
_EPC_TEMPLATE = "\n".join([
    "BCD",       # Service Tag
    "002",       # Version
    "1",         # Encoding: UTF-8
    "SCT",       # Identification
    "{bic}",     # BIC (optional, left blank)
    "{name}",    # Beneficiary name
    "{iban}",    # IBAN
    "EUR{amount}",  # Amount
    "",          # Purpose (optional)
    "{communication}",  # Remittance (structured or free-form)
    "",          # Beneficiary to originator info (optional)
])


def generate_qr_base64(payment: PaymentDetails) -> str:
    """Generate an EPC QR code PNG and return it as a base64 string."""
    epc_data = _EPC_TEMPLATE.format(
        bic="",
        name=payment.beneficiary_name,
        iban=payment.iban,
        amount=payment.amount,
        communication=payment.communication,
    )
    qr = segno.make(epc_data, error="m")
    buf = BytesIO()
    qr.save(buf, kind="png", scale=4)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("ascii")
