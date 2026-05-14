# Plan: Extract Beneficiary Name from Invoice

## Goal

Currently the EPC QR code beneficiary name is a static config value (`COMPANY_NAME` env var).
Instead, it should be extracted from the invoice by the LLM, like the other payment fields.

## Proposed Changes

### 1. `mail2pay/models.py`

Add `beneficiary_name` field to `PaymentDetails`:

```python
beneficiary_name: str = Field(description="Name of the payment beneficiary / creditor as it appears on the invoice")
```

### 2. `mail2pay/llm.py`

Update the system/user prompt so the LLM knows to extract the beneficiary name.
No structural change needed — `PaymentDetails` is passed as `text_format` so the new field is picked up automatically.
The user message should mention "beneficiary name" explicitly, e.g.:

> "Extract the beneficiary name, amount, Belgian IBAN, and communication."

### 3. `mail2pay/qr.py`

Change signature:

```python
def generate_qr_base64(payment: PaymentDetails) -> str:
```

Use `payment.beneficiary_name` for the `name` field in the EPC template (instead of the `company_name` parameter).

### 4. `mail2pay/config.py`

Remove `company_name` / `COMPANY_NAME`.

### 5. `handler.py`

Remove `cfg.company_name` from the `generate_qr_base64(...)` call.

### 6. Tests

- `test_qr.py`: remove `company_name` arg; add `beneficiary_name` to the `PaymentDetails` fixture; assert the EPC string contains the beneficiary name.
- `test_config.py`: remove assertion on `company_name`.
- `test_llm.py` (real path): assert `beneficiary_name` is non-empty.
- `test_handler.py`: update stub / mock accordingly.

## Open Questions

- None — straightforward field addition + config removal.
