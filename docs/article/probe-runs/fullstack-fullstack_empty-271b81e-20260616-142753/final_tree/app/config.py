from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg2://app:secret@localhost:5432/apikeys"
    redis_url: str = "redis://localhost:6379/0"
    rate_limit_requests: int = 10
    rate_limit_window: int = 60  # seconds


settings = Settings()
