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
│   ├── config.py           # Pydantic Settings (env-based Config)
│   ├── models.py           # Pydantic PaymentDetails
│   ├── pdf.py              # extract_pdf_text
│   ├── llm.py              # extract_details_via_llm (structured output)
│   ├── qr.py               # generate_qr_base64 (EPC format)
│   └── mailer.py           # send_reply via Resend
├── tests/
│   ├── __init__.py
│   ├── test_config.py
│   ├── test_qr.py
│   ├── test_llm.py         # mocks OpenAI client
│   └── test_handler.py     # end-to-end with mocks
└── docs/plans/...
```

Alternative: single-file `handler.py` per spec. Proposed modular split keeps the file testable; final `handler.py` imports from the `mail2pay` package. Open question below.

## Proposed Changes

### 1. `pyproject.toml`
Add dependencies:
- `openai` 
- `resend`
- `pypdf`
- `segno`
- `pydantic`
- `pydantic-settings`

Dev deps (optional group `dev`): `pytest`, `pytest-mock`.

### 2. `mail2pay/config.py`

Centralised configuration via `pydantic-settings`. All env-var reads live here — no `os.environ` calls elsewhere in the package.

```python
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class Config(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    resend_api_key: str       = Field(alias="RESEND_API_KEY")
    openai_api_key: str       = Field(alias="OPENAI_API_KEY")
    company_name: str         = Field(alias="COMPANY_NAME")
    from_address: str         = Field(alias="FROM_ADDRESS")
    openai_model: str         = Field(default="gpt-5.4-mini", alias="OPENAI_MODEL")

def get_config() -> Config:
    return Config()  # instantiated lazily by handler
```

**Cold-start caching**: `handler.py` holds module-level globals `_cfg = None` and `_extractor = None`. On first `handle()` call, `handle()` calls a `_bootstrap()` helper that populates them; subsequent invocations reuse. Nothing is built at import time, so tests can monkeypatch env vars or the `Extractor` symbol before the first call.

### 3. `mail2pay/models.py`
```python
from pydantic import BaseModel, Field

class PaymentDetails(BaseModel):
    amount: str = Field(description='Total amount, e.g. "50.00", no currency symbol')
    iban: str  = Field(description="Belgian IBAN, no spaces")
    communication: str = Field(description="Structured or free-form payment reference")
```

### 3a. `mail2pay/models.py` – amount & communication normalization

`PaymentDetails` performs light validation so downstream code can trust the data:
- `amount`: validator parses to `Decimal`, rejects non-positive, formats back to 2-decimal string (`"50.00"`).
- `iban`: validator strips spaces, uppercases, asserts `startswith("BE")` and `len == 16`.
- `communication`: validator truncates to 140 chars (EPC max) and strips whitespace.

This keeps `qr.py` a pure formatter.

### 4. `mail2pay/llm.py`

Expose an `Extractor` class that owns the OpenAI client. The client is created lazily if not injected — tests pass a mock, production code just does `Extractor(cfg)`.

```python
from typing import Optional
from openai import OpenAI
from .config import Config
from .models import PaymentDetails

class Extractor:
    def __init__(self, cfg: Config, client: Optional[OpenAI] = None):
        self._model = cfg.openai_model
        self._client = client or OpenAI(api_key=cfg.openai_api_key)

    def extract(self, raw_text: str) -> PaymentDetails:
        response = self._client.responses.parse(
            model=self._model,
            input=[
                {"role": "system", "content": "Precise invoice data extractor."},
                {"role": "user", "content":
                    f"Extract amount, Belgian IBAN, and communication.\n\nInvoice:\n{raw_text}"},
            ],
            text_format=PaymentDetails,
        )
        return response.output_parsed
```

### 5. `mail2pay/pdf.py`
`extract_pdf_text(base64_pdf: str) -> str` — decode, read with `pypdf.PdfReader`, concatenate pages.

`pick_pdf_attachment(attachments: list[dict]) -> dict | None` — returns the first attachment whose `ContentType` is `application/pdf` or whose `Filename` ends in `.pdf` (case-insensitive). Used by `handler.py` so non-PDF attachments (signature images, logos) are skipped instead of crashing `pypdf`.

### 6. `mail2pay/qr.py`
`generate_qr_base64(payment: PaymentDetails, company_name: str) -> str` — build EPC v002 SCT string, `segno.make(..., error='M')`, save PNG to `BytesIO`, return base64.

### 7. `mail2pay/mailer.py`
`send_reply(cfg: Config, to: str, qr_b64: str)` — wraps `resend.Emails.send`, using `cfg.resend_api_key` and `cfg.from_address`.

### 8. `handler.py`
Scaleway entry point `handle(event, context)`:
1. `_bootstrap()` lazily builds and caches `_cfg` and `_extractor` on first call.
2. Parse `event["body"]` JSON.
3. Pull `From` and `Attachments`; early-exit 200 when missing.
4. `pick_pdf_attachment(attachments)`; early-exit 200 if no PDF.
5. Pipeline: `extract_pdf_text → _extractor.extract(text) → generate_qr_base64(..., cfg.company_name) → send_reply(cfg, ...)`.
6. Broad `except Exception` → `logging.exception("mail2pay failure")` (full stack trace) + return 200 to suppress Resend retries.

Use the stdlib `logging` module configured at module load (`logging.basicConfig(level=logging.INFO)`); no bare `print`.

All configuration flows through the `Config` object — no `os.environ` in business modules.

### 9. Tests
- `test_config.py`: verify `Config` loads from env and rejects missing required vars.
- `test_qr.py`: verify EPC string structure and that a PNG is produced & base64-decodable.
- `test_llm.py`: two fixtures in `conftest.py`:
  - `real_extractor`: builds `Extractor(cfg)` with a real OpenAI client. Calls `pytest.skip(...)` when `OPENAI_API_KEY` is not set.
  - `mock_extractor`: builds `Extractor(cfg, client=MagicMock())` and exposes the mock so tests can configure `client.responses.parse.return_value.output_parsed` and assert call args (`model`, `text_format=PaymentDetails`, `input` messages).

  Tests split by fixture:
  - Mock-based: verify the call shape (model, input roles, `text_format=PaymentDetails`) and that `output_parsed` is returned unchanged.
  - Real-based (skipped without key): run against `tests/fixtures/sample_invoice.txt` and assert plausibility — `iban` starts with `BE` and is 16 chars, `amount` parses as positive `Decimal`, `communication` non-empty.
- `test_handler.py`: feed a fake event (with a small generated PDF) through the full pipeline.
  - Resend is **always mocked** (monkeypatch `resend.Emails.send`) — no outbound email ever in tests.
  - LLM path mirrors `test_llm.py`: live `Extractor` when `OPENAI_API_KEY` is present, else a simple stub class with an `extract(raw_text)` method is injected by monkeypatching the handler's `Extractor` symbol.
  - Asserts Resend called once with correct `to`, subject, and a base64 PNG attachment (verify PNG magic bytes after decode).

### 10. README & Makefile
README covers: env vars, `uv sync`, `uv run pytest`, Scaleway deploy.

`Makefile` targets:
- `requirements.txt`: `uv export --no-hashes --format requirements-txt -o requirements.txt` (Scaleway consumes this).
- `build`: produces `dist/mail2pay.zip` containing `handler.py`, the `mail2pay/` package, and `requirements.txt`.
- `deploy`: loads `.env` and invokes Scaleway CLI to upload the zip.
- `test`: `uv run pytest`.

## Resolved Decisions

1. **File layout**: modular package (`mail2pay/` + thin `handler.py`).
2. **From address**: `FROM_ADDRESS` env var via `Config`.
3. **OpenAI model**: default `gpt-5.4-mini`, overridable via `OPENAI_MODEL` env var.
4. **Multiple PDFs**: process first attachment only.
5. **Scaleway packaging**: include a `Makefile` that builds/deploys, reading creds from `.env`.
6. **Tests**: pytest, kept simple; live OpenAI when key present, mocked otherwise; Resend always mocked.

No open questions remaining — ready to implement on your signal.
