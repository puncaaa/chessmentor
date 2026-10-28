import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PROJECT_NAME: str = "Chess B2B SaaS"
    
    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/chess_db"
    
    # Redis & Celery
    REDIS_URL: str = "redis://localhost:6379/0"
    
    # Engine Settings
    STOCKFISH_PATH: str = os.getenv("STOCKFISH_PATH", "/opt/homebrew/bin/stockfish")
    STOCKFISH_DEPTH: int = 12
    STOCKFISH_TIME_LIMIT: float = 0.08
    STOCKFISH_THREADS: int = 2
    STOCKFISH_HASH_MB: int = 128
    
    # External APIs
    LICHESS_API_TOKEN: str = ""
    CHESSCOM_USER_AGENT: str = "ChessSaaSPlatform/1.0 (contact@example.com)"
    
    # LLM
    LLM_PROVIDER: str = "openai" # "openai" | "anthropic"
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o-mini"
    ANTHROPIC_API_KEY: str = ""
    ANTHROPIC_MODEL: str = "claude-3-5-sonnet-20241022"

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()
