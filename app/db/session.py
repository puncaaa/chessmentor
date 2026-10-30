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
    """Создание всех таблиц в базе данных и автоматическая миграция схемы для SQLite."""
    Base.metadata.create_all(bind=engine)
    
    # Для SQLite проверяем и добавляем новые колонки student_profiles, если они еще не созданы
    if "sqlite" in sync_db_url:
        with engine.connect() as conn:
            cursor = conn.connection.cursor()
            cursor.execute("PRAGMA table_info(student_profiles)")
            existing_cols = {col[1] for col in cursor.fetchall()}
            
            new_columns = [
                ("school_id", "VARCHAR(36)"),
                ("group_id", "VARCHAR(36)"),
                ("birth_date", "DATETIME"),
                ("current_rating", "INTEGER DEFAULT 1200"),
                ("parent_name", "VARCHAR(100)"),
                ("parent_phone", "VARCHAR(50)"),
                ("parent_telegram", "VARCHAR(100)"),
                ("is_active", "BOOLEAN DEFAULT 1"),
                ("updated_at", "DATETIME"),
            ]
            for col_name, col_type in new_columns:
                if col_name not in existing_cols:
                    cursor.execute(f"ALTER TABLE student_profiles ADD COLUMN {col_name} {col_type}")
            conn.connection.commit()

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
