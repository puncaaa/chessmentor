import os
from contextlib import contextmanager
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from app.core.config import settings
from app.models.chess import Base

# Поддержка PostgreSQL с fallback на локальный SQLite для локальной разработки и тестов
raw_db_url = os.getenv("DATABASE_URL", settings.DATABASE_URL)

# Для синхронного Celery и скриптов используем стандартный драйвер
if raw_db_url.startswith("postgresql+asyncpg://"):
    sync_db_url = raw_db_url.replace("postgresql+asyncpg://", "postgresql://")
else:
    sync_db_url = raw_db_url

# Если PostgreSQL не запущен или указан sqlite, используем SQLite
if "localhost" in sync_db_url or "sqlite" in sync_db_url:
    # Проверяем доступность или используем локальный файл
    if not os.getenv("TEST_WITH_POSTGRES"):
        sync_db_url = "sqlite:///./chess.db"

engine = create_engine(
    sync_db_url,
    connect_args={"check_same_thread": False} if "sqlite" in sync_db_url else {},
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)

def init_db():
    """Создание всех таблиц в базе данных."""
    Base.metadata.create_all(bind=engine)

@contextmanager
def get_db_session() -> Session:
    """Контекстный менеджер сессии SQLAlchemy с автоматическим rollback при ошибке."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
