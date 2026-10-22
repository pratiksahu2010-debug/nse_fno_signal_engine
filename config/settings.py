"""Typed environment-backed runtime settings."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Sequence

from config import defaults


def _csv_ints(value: str) -> tuple[int, ...]:
    result: list[int] = []
    for part in value.split(","):
        part = part.strip()
        if part:
            try:
                result.append(int(part))
            except ValueError as exc:
                raise ValueError(f"Expected comma-separated integer IDs, got {part!r}") from exc
    return tuple(result)


def _bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class Settings:
    app_env: str = "production"
    tz: str = defaults.TZ
    log_level: str = "INFO"
    host: str = "0.0.0.0"
    port: int = 8000
    upstox_api_key: str = ""
    upstox_api_secret: str = ""
    upstox_access_token: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    telegram_admin_ids: tuple[int, ...] = ()
    min_score: int = defaults.MIN_SCORE
    filter_profile: str = "strict"
    explosion_min_score: int = defaults.EXPLOSION_MIN_SCORE
    entry_mode: str = defaults.ENTRY_MODE
    db_backend: str = "memory"
    database_url: str = ""
    redis_url: str = ""
    capital: float = defaults.CAPITAL
    risk_pct: float = defaults.RISK_PCT
    signal_only: bool = True

    @classmethod
    def from_env(cls) -> "Settings":
        min_score = int(os.getenv("MIN_SCORE", str(defaults.MIN_SCORE)))
        if min_score < defaults.MIN_SCORE_FLOOR or min_score > 100:
            raise ValueError(f"MIN_SCORE must be between {defaults.MIN_SCORE_FLOOR} and 100")
        profile = os.getenv("FILTER_PROFILE", "strict").strip().lower()
        if profile not in {"strict", "balanced"}:
            raise ValueError("FILTER_PROFILE must be strict or balanced")
        explosion_score = int(os.getenv("EXPLOSION_MIN_SCORE", str(defaults.EXPLOSION_MIN_SCORE)))
        if not 0 <= explosion_score <= 100:
            raise ValueError("EXPLOSION_MIN_SCORE must be between 0 and 100")
        entry_mode = os.getenv("ENTRY_MODE", defaults.ENTRY_MODE).strip().lower()
        if entry_mode not in {"close", "breakout"}:
            raise ValueError("ENTRY_MODE must be 'close' or 'breakout'")
        db_backend = os.getenv("DB_BACKEND", "memory").strip().lower()
        if db_backend not in {"memory", "sqlite", "postgres", "redis"}:
            raise ValueError("DB_BACKEND must be memory, sqlite, postgres, or redis")
        return cls(
            app_env=os.getenv("APP_ENV", "production"),
            tz=os.getenv("TZ", defaults.TZ),
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
            host=os.getenv("HOST", "0.0.0.0"),
            port=int(os.getenv("PORT", "8000")),
            upstox_api_key=os.getenv("UPSTOX_API_KEY", ""),
            upstox_api_secret=os.getenv("UPSTOX_API_SECRET", ""),
            upstox_access_token=os.getenv("UPSTOX_ACCESS_TOKEN", ""),
            telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
            telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", ""),
            telegram_admin_ids=_csv_ints(os.getenv("TELEGRAM_ADMIN_IDS", "")),
            min_score=min_score, filter_profile=profile, explosion_min_score=explosion_score,
            entry_mode=entry_mode, db_backend=db_backend,
            database_url=os.getenv("DATABASE_URL", ""), redis_url=os.getenv("REDIS_URL", ""),
            capital=float(os.getenv("CAPITAL", str(defaults.CAPITAL))),
            risk_pct=float(os.getenv("RISK_PCT", str(defaults.RISK_PCT))),
            signal_only=_bool("SIGNAL_ONLY", True),
        )

    def validate_deployment(self) -> Sequence[str]:
        """Return non-fatal deployment warnings; credentials are not required for unit tests."""
        warnings: list[str] = []
        if not self.upstox_access_token:
            warnings.append("UPSTOX_ACCESS_TOKEN is not configured; live market data will remain disabled")
        if not self.telegram_bot_token or not self.telegram_chat_id:
            warnings.append("Telegram credentials are incomplete; outbound alerts are disabled")
        if self.db_backend == "postgres" and not self.database_url:
            warnings.append("DB_BACKEND=postgres but DATABASE_URL is empty")
        if self.db_backend == "redis" and not self.redis_url:
            warnings.append("DB_BACKEND=redis but REDIS_URL is empty")
        if not self.signal_only:
            warnings.append("This project is designed for signal-only operation; order execution is not implemented")
        return warnings
