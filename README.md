# mail2pay

Serverless function that receives inbound email webhooks from [Resend](https://resend.com), extracts payment details from attached PDF invoices via OpenAI, generates a Belgian EPC QR code, and replies to the sender with the QR code attached.

## How it works

1. Resend delivers an inbound email event (JSON) to the function endpoint.
2. The function picks the first PDF attachment and extracts its text with `pypdf`.
3. OpenAI (`gpt-5.4-mini` by default) identifies the amount, IBAN, and communication reference using structured outputs.
4. A SEPA Credit Transfer (EPC) QR code is generated with `segno`.
5. The QR code PNG is emailed back to the original sender via Resend.

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `RESEND_API_KEY` | ✅ | Resend API key |
| `OPENAI_API_KEY` | ✅ | OpenAI API key |
| `COMPANY_NAME` | ✅ | Beneficiary name embedded in the QR code |
| `FROM_ADDRESS` | ✅ | Reply-from address (must be verified in Resend) |
| `RESEND_WEBHOOK_SECRET` | ✅ | Resend webhook signing secret (found in Resend dashboard → Webhooks) |
| `OPENAI_MODEL` | ✗ | OpenAI model (default: `gpt-5.4-mini`) |

Copy `.env.example` to `.env` and fill in the values:

```bash
cp .env.example .env
```

## Development

```bash
# Install dependencies (including dev)
uv sync --dev

# Run tests
uv run pytest

# or via make
make test
```

## Deployment (Scaleway Serverless Functions)

### Prerequisites

- [Scaleway CLI](https://github.com/scaleway/scaleway-cli) installed and configured
- A Scaleway namespace already created; set `SCW_NAMESPACE_ID` in `.env`

### Build & deploy

```bash
# Export requirements.txt for Scaleway
make requirements.txt

# Build deployment zip
make build

# Deploy (reads creds from .env)
make deploy
```

The `handle` function in `handler.py` is the Scaleway entry point.

## Project structure

```
handler.py          # Scaleway entry point
mail2pay/
  config.py         # Pydantic Settings (env-based)
  models.py         # PaymentDetails with validators
  llm.py            # OpenAI Extractor
  pdf.py            # PDF text extraction
  qr.py             # EPC QR code generator
  mailer.py         # Resend reply sender
tests/
  conftest.py
  test_config.py
  test_qr.py
  test_llm.py
  test_handler.py
```
