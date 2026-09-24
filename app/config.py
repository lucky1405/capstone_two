"""Application configuration and pinned pricing constants."""
from typing import Dict, Any
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class PlanConfig:
    """Fixed quotas and configuration for subscription plans."""
    FREE = {
        "id": "free",
        "name": "Free Tier",
        "max_api_calls": 1000,
        "max_ai_tokens": 100000,
        "monthly_fee_cents": 0,
        "stripe_price_id": None,
    }
    PRO = {
        "id": "pro",
        "name": "Pro Tier",
        "max_api_calls": 50000,
        "max_ai_tokens": 5000000,
        "monthly_fee_cents": 2900,  # $29.00
        "stripe_price_id": "price_pro_monthly_test",
    }


class PricingConstants:
    """
    Pinned AI Token & Usage Pricing Constants.
    
    All rates are expressed as integer micro-units (µ$ = 10^-6 USD = 1/10,000th of a cent)
    per 1,000 tokens to eliminate floating-point drift:
    - Standard Input: $0.50 per 1M tokens => 500 micro-units per 1k tokens (0.5 micro-unit / token)
    - Cached Input:   $0.125 per 1M tokens => 125 micro-units per 1k tokens (0.125 micro-unit / token) [75% discount]
    - Output:         $1.50 per 1M tokens => 1500 micro-units per 1k tokens (1.5 micro-unit / token)
    - Reasoning:      $1.50 per 1M tokens => 1500 micro-units per 1k tokens (billed at output token rate)
    """
    # Rate per 1,000 tokens in micro-units ($10^-6 USD)
    INPUT_RATE_PER_1K: int = 500
    CACHED_INPUT_RATE_PER_1K: int = 125
    OUTPUT_RATE_PER_1K: int = 1500
    REASONING_RATE_PER_1K: int = 1500

    # Base cost per billable API call in micro-units (0 included in subscription)
    API_CALL_UNIT_COST: int = 0


class Settings(BaseSettings):
    """System runtime settings loaded from environment or .env file."""
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    APP_ENV: str = "development"
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    LOG_LEVEL: str = "INFO"

    # Database: SQLite with aiosqlite by default
    DATABASE_URL: str = "sqlite+aiosqlite:///./data/billing.db"
    DB_PATH: str = "./data/billing.db"

    # Stripe Test Mode credentials
    STRIPE_SECRET_KEY: str = "your_stripe_test_secret_key_here"
    STRIPE_PUBLISHABLE_KEY: str = "your_stripe_test_publishable_key_here"
    STRIPE_WEBHOOK_SECRET: str = "your_stripe_webhook_signing_secret_here"
    STRIPE_PRO_PRICE_ID: str = "price_pro_monthly_test"

    # Quota defaults
    DEFAULT_RETRY_AFTER_SECONDS: int = 60

    # Pricing & Plans references
    PRICING: PricingConstants = Field(default_factory=PricingConstants)
    PLANS: Dict[str, Dict[str, Any]] = {
        "free": PlanConfig.FREE,
        "pro": PlanConfig.PRO,
    }


settings = Settings()
