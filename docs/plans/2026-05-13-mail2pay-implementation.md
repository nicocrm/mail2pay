# Plan: Mail2Pay – Invoice → EPC QR Code Serverless Function

## Goal

Implement the serverless function described in `SPEC.md`: receive an inbound email webhook from Resend containing a PDF invoice, extract payment details via OpenAI, generate a Belgian EPC QR code, and reply to the sender with the QR code attached.

Deviations from SPEC:
- Use **OpenAI structured responses with a Pydantic model** instead of the loose `json_object` response format.
- Use **uv** for dependency management (project already initialized).

## Target Layout

```
mail2pay/
├── pyproject.toml          # updated deps
├── handler.py              # Scaleway entry point (`handle`)
├── mail2pay/
│   ├── __init__.py
│   ├── models.py           # Pydantic PaymentDetails
│   ├── pdf.py              # extract_pdf_text
│   ├── llm.py              # extract_details_via_llm (structured output)
│   ├── qr.py               # generate_qr_base64 (EPC format)
│   └── mailer.py           # send_reply via Resend
├── tests/
│   ├── __init__.py
│   ├── test_qr.py
│   ├── test_llm.py         # mocks OpenAI client
│   └── test_handler.py     # end-to-end with mocks
└── docs/plans/...
```

Alternative: single-file `handler.py` per spec. Proposed modular split keeps the file testable; final `handler.py` imports from the `mail2pay` package. Open question below.

## Proposed Changes

### 1. `pyproject.toml`
Add dependencies:
- `openai>=1.50` (supports `responses.parse` / `beta.chat.completions.parse`)
- `resend`
- `pypdf`
- `segno`
- `pydantic>=2`

Dev deps (optional group `dev`): `pytest`, `pytest-mock`.

### 2. `mail2pay/models.py`
```python
from pydantic import BaseModel, Field

class PaymentDetails(BaseModel):
    amount: str = Field(description='Total amount, e.g. "50.00", no currency symbol')
    iban: str  = Field(description="Belgian IBAN, no spaces")
    communication: str = Field(description="Structured or free-form payment reference")
```

### 3. `mail2pay/llm.py`
Use the OpenAI **structured outputs** API:
```python
from openai import OpenAI
from .models import PaymentDetails

def extract_details_via_llm(client: OpenAI, raw_text: str, model: str = "gpt-4o-mini") -> PaymentDetails:
    completion = client.beta.chat.completions.parse(
        model=model,
        messages=[
            {"role": "system", "content": "Precise invoice data extractor."},
            {"role": "user", "content": f"Extract amount, Belgian IBAN, and communication.\n\nInvoice:\n{raw_text}"},
        ],
        response_format=PaymentDetails,
    )
    return completion.choices[0].message.parsed
```
Note: SPEC mentions `gpt-5.4-mini` (non-existent). Default to `gpt-4o-mini`, overridable via env `OPENAI_MODEL`.

### 4. `mail2pay/pdf.py`
`extract_pdf_text(base64_pdf: str) -> str` — decode, read with `pypdf.PdfReader`, concatenate pages.

### 5. `mail2pay/qr.py`
`generate_qr_base64(payment: PaymentDetails, company_name: str) -> str` — build EPC v002 SCT string, `segno.make(..., error='M')`, save PNG to `BytesIO`, return base64.

### 6. `mail2pay/mailer.py`
`send_reply(to: str, qr_b64: str, from_addr: str)` — wraps `resend.Emails.send`.

### 7. `handler.py`
Scaleway entry point `handle(event, context)`:
1. Parse `event["body"]` JSON.
2. Pull `From` and `Attachments`; early-exit 200 when missing.
3. Pipeline: `extract_pdf_text → extract_details_via_llm → generate_qr_base64 → send_reply`.
4. Broad `except` → log + return 200 (prevent Resend retries).

Env vars read at module import: `RESEND_API_KEY`, `OPENAI_API_KEY`, `COMPANY_NAME`, optional `OPENAI_MODEL`, `FROM_ADDRESS`.

### 8. Tests
- `test_qr.py`: verify EPC string structure and that a PNG is produced & base64-decodable.
- `test_llm.py`: mock `client.beta.chat.completions.parse` returning a `PaymentDetails`.
- `test_handler.py`: feed a fake event (with a small generated PDF) and assert Resend send called with correct recipient/attachment.

### 9. README
Short section on: env vars, `uv sync`, `uv run pytest`, Scaleway deploy notes (zip with `requirements.txt` exported via `uv export`).

## Open Questions

1. **File layout**: keep single-file `handler.py` (matches spec closely, easier deploy) or modular package with tests (proposed)? 
-> use modular structure
2. **From address**: hard-code or env var `FROM_ADDRESS`? (proposing env var.)
-> read from env
3. **OpenAI model**: confirm replacement for the spec's `gpt-5.4-mini` → `gpt-4o-mini` default, configurable.
-> gpt-5.4-mini is correct (newer model you don't know about).  Make it a configuration variable read from env
4. **Multiple PDFs**: process only first attachment (per spec) or loop all? Spec says first; keep that.
-> first only
5. **Scaleway packaging**: do you want a `Makefile` / `build.sh` producing a deploy zip, or leave deployment manual?
-> include a Makefile to deploy, read creds etc from .env
6. **Tests**: include pytest scaffolding now or defer?
-> use pytest, include test, keep it simple
