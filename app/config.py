from __future__ import annotations

from dataclasses import dataclass, field
import os

from dotenv import load_dotenv


# Local development convenience. Existing OS environment variables always win.
load_dotenv(override=False)


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    host: str = field(default_factory=lambda: os.getenv("STOCKS_HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: _int("STOCKS_PORT", 8790))
    primary_provider: str = field(
        default_factory=lambda: os.getenv("STOCKS_PROVIDER_PRIMARY", "ssi").strip().lower()
    )
    fallback_provider: str = field(
        default_factory=lambda: os.getenv("STOCKS_PROVIDER_FALLBACK", "vnstock").strip().lower()
    )
    request_timeout: int = field(default_factory=lambda: _int("STOCKS_REQUEST_TIMEOUT", 15))
    default_limit: int = field(default_factory=lambda: _int("STOCKS_DEFAULT_LIMIT", 300))
    max_limit: int = field(default_factory=lambda: _int("STOCKS_MAX_LIMIT", 2000))
    min_prepared_candles: int = field(default_factory=lambda: _int("STOCKS_MIN_PREPARED_CANDLES", 100))

    ssi_consumer_id: str = field(default_factory=lambda: os.getenv("SSI_CONSUMER_ID", "").strip())
    ssi_consumer_secret: str = field(default_factory=lambda: os.getenv("SSI_CONSUMER_SECRET", "").strip())
    ssi_public_key: str = field(default_factory=lambda: os.getenv("SSI_PUBLIC_KEY", "").strip())
    ssi_private_key: str = field(default_factory=lambda: os.getenv("SSI_PRIVATE_KEY", "").strip())
    database_url: str = field(
        default_factory=lambda: os.getenv("STOCKS_DATABASE_URL", "").strip()
    )
    db_connect_timeout: int = field(default_factory=lambda: _int("STOCKS_DB_CONNECT_TIMEOUT", 5))

    @property
    def database_enabled(self) -> bool:
        return bool(self.database_url)


settings = Settings()
