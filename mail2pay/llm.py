import logging
from typing import Optional

from openai import OpenAI

from .config import Config
from .models import PaymentDetails

logger = logging.getLogger(__name__)

_MAX_TEXT_CHARS = 10_000


class Extractor:
    _SYSTEM_PROMPT = (
        "You extract structured payment data from invoice text. "
        "Return exactly three fields (amount, Belgian IBAN, communication) "
        "in the required JSON schema. Do not include any other text."
    )

    def __init__(self, cfg: Config, client: Optional[OpenAI] = None):
        self._model = cfg.openrouter_model
        self._client = client or OpenAI(
            api_key=cfg.openrouter_api_key,
            base_url=cfg.openrouter_base_url,
            default_headers={
                "HTTP-Referer": cfg.app_url,
                "X-Title": cfg.app_title,
            },
        )

    def extract(self, raw_text: str) -> PaymentDetails:
        if len(raw_text) > _MAX_TEXT_CHARS:
            logger.warning(
                "Invoice text truncated from %d to %d chars before LLM call.",
                len(raw_text),
                _MAX_TEXT_CHARS,
            )
            raw_text = raw_text[:_MAX_TEXT_CHARS]

        response = self._client.chat.completions.parse(
            model=self._model,
            messages=[
                {"role": "system", "content": self._SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        "Extract amount, Belgian IBAN, and communication.\n\n"
                        f"Invoice:\n{raw_text}"
                    ),
                },
            ],
            response_format=PaymentDetails,
        )
        parsed = response.choices[0].message.parsed
        if parsed is None:
            raise ValueError(
                "LLM returned no structured output "
                "(refusal, content filter, or model lacks structured-output support)"
            )
        return parsed
