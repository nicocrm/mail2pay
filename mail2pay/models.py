from decimal import Decimal, InvalidOperation
from pydantic import BaseModel, Field, field_validator


class PaymentDetails(BaseModel):
    amount: str = Field(description='Total amount, e.g. "50.00", no currency symbol')
    iban: str = Field(description="Belgian IBAN, no spaces")
    communication: str = Field(description="Structured or free-form payment reference")

    @field_validator("amount", mode="before")
    @classmethod
    def validate_amount(cls, v: str) -> str:
        try:
            d = Decimal(str(v).strip())
        except InvalidOperation:
            raise ValueError(f"Invalid amount: {v!r}")
        if d <= 0:
            raise ValueError(f"Amount must be positive, got {d}")
        return f"{d:.2f}"

    @field_validator("iban", mode="before")
    @classmethod
    def validate_iban(cls, v: str) -> str:
        cleaned = str(v).replace(" ", "").upper()
        if not cleaned.startswith("BE"):
            raise ValueError(f"IBAN must start with 'BE', got {cleaned!r}")
        if len(cleaned) != 16:
            raise ValueError(f"Belgian IBAN must be 16 chars, got {len(cleaned)}")
        return cleaned

    @field_validator("communication", mode="before")
    @classmethod
    def validate_communication(cls, v: str) -> str:
        return str(v).strip()[:140]
