from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    resend_api_key: str = Field(alias="RESEND_API_KEY")
    openrouter_api_key: str = Field(alias="OPENROUTER_API_KEY")
    company_name: str = Field(alias="COMPANY_NAME")
    from_address: str = Field(alias="FROM_ADDRESS")
    webhook_secret: str = Field(alias="RESEND_WEBHOOK_SECRET")
    openrouter_model: str = Field(default="mistralai/mistral-small-2603", alias="OPENROUTER_MODEL")
    openrouter_base_url: str = Field(
        default="https://openrouter.ai/api/v1", alias="OPENROUTER_BASE_URL"
    )
    app_url: str = Field(
        default="https://github.com/ngaller/mail2pay", alias="APP_URL"
    )
    app_title: str = Field(default="mail2pay", alias="APP_TITLE")


def get_config() -> Config:
    return Config()  # ty: ignore[missing-argument]
