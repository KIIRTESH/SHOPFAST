from typing import List, Union, Any
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import AnyHttpUrl, field_validator


class Settings(BaseSettings):
    PROJECT_NAME: str = "FASTSHOP API"
    VERSION: str = "2.0.0"
    API_V1_STR: str = "/api/v1"
    
    # Environment & Debug
    ENVIRONMENT: str = "development"
    DEBUG: bool = False
    
    # Production Seeding & Credential Security
    ALLOW_DEFAULT_CREDENTIALS: Union[bool, None] = None
    INITIAL_ADMIN_USERNAME: Union[str, None] = None
    INITIAL_ADMIN_PIN: Union[str, None] = None

    @property
    def should_seed_demo_accounts(self) -> bool:
        """
        Determines whether demo accounts (e.g. admin with PIN 1234) should be seeded.
        In development/testing, defaults to True for instant testing and fixture support.
        In production, defaults to False to prevent exposing default privileged credentials.
        """
        if self.ALLOW_DEFAULT_CREDENTIALS is not None:
            return self.ALLOW_DEFAULT_CREDENTIALS
        return self.ENVIRONMENT.lower() != "production"
    
    # Database configuration (Defaults to async SQLite for instant zero-config testing; easily switchable to PostgreSQL)
    DATABASE_URL: str = "sqlite+aiosqlite:///./fastshop.db"
    
    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def assemble_db_connection(cls, v: str | None) -> str:
        if not v:
            return "sqlite+aiosqlite:///./fastshop.db"
        # Render PostgreSQL uses postgres:// or postgresql://
        if v.startswith("postgres://"):
            return v.replace("postgres://", "postgresql+asyncpg://", 1)
        if v.startswith("postgresql://") and not v.startswith("postgresql+asyncpg://"):
            return v.replace("postgresql://", "postgresql+asyncpg://", 1)
        return v
    
    # In production with PostgreSQL:
    # DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/fastshop"
    
    # CORS Configuration - credentials require explicit origin whitelist, wildcard '*' is rejected by browsers
    CORS_ORIGINS: Union[List[str], str] = [
        "http://localhost",
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5500",
        "http://127.0.0.1:8000",
        "https://fastshop.onrender.com"
    ]

    @field_validator("CORS_ORIGINS", mode="after")
    @classmethod
    def assemble_cors_origins(cls, v: Any) -> List[str]:
        if isinstance(v, str):
            v = v.strip()
            if v.startswith("[") and v.endswith("]"):
                import json
                try:
                    return json.loads(v)
                except Exception:
                    pass
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        elif isinstance(v, (list, tuple)):
            return list(v)
        return v
    
    # Store Queue Intelligence Configuration
    BASE_ITEM_SCAN_SECONDS: float = 2.5   # Avg time to scan 1 item
    BASE_PAYMENT_SECONDS: float = 20.0     # Avg time for customer payment
    EXPRESS_LANE_MAX_ITEMS: int = 5        # Express limit
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True
    )


settings = Settings()
