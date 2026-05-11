from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "BallPredict"
    environment: str = "development"
    cors_origins: list[str] = ["http://localhost:5173"]
    postgres_url: str = "postgresql+psycopg://ballpredict:ballpredict@db:5432/ballpredict"
    redis_url: str = "redis://redis:6379/0"
    nba_live_base_url: str = "https://cdn.nba.com/static/json/liveData"
    nba_stats_base_url: str = "https://stats.nba.com/stats"
    websocket_tick_seconds: int = 8
    default_simulation_runs: int = 2500

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()

