from os import environ


class Settings:
    database_url: str = environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://postgres:postgres@localhost:5432/keys",
    )
    redis_url: str = environ.get("REDIS_URL", "redis://localhost:6379/0")

    rate_limit_requests: int = int(environ.get("RATE_LIMIT_REQUESTS", "10"))
    rate_limit_window_seconds: int = int(
        environ.get("RATE_LIMIT_WINDOW_SECONDS", "60")
    )


settings = Settings()
