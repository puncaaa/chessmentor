import uuid
from datetime import datetime
from typing import Optional, List
from sqlalchemy import (
    Column,
    String,
    Integer,
    Boolean,
    DateTime,
    ForeignKey,
    Numeric,
    Text,
    JSON,
    BigInteger,
    Index,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

def generate_uuid() -> str:
    return str(uuid.uuid4())


class School(Base):
    """
    Шахматная школа / организация (мультитенантность B2B).
    """
    __tablename__ = "schools"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    name = Column(String(255), nullable=False)
    slug = Column(String(100), unique=True, nullable=False, index=True)
    subscription_tier = Column(String(50), default="pro", nullable=False)  # starter, pro, enterprise
    max_students = Column(Integer, default=50, nullable=False)
    logo_url = Column(Text, nullable=True)  # URL, Base64 или локальный путь для брендинга PDF
    contact_email = Column(String(255), nullable=True)
    contact_phone = Column(String(50), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    teachers = relationship("Teacher", back_populates="school", cascade="all, delete-orphan")
    groups = relationship("Group", back_populates="school", cascade="all, delete-orphan")
    students = relationship("StudentProfile", back_populates="school", cascade="all, delete-orphan")
    reports = relationship("StudentReport", back_populates="school", cascade="all, delete-orphan")


class Teacher(Base):
    """
    Тренер / преподаватель шахматной школы.
    """
    __tablename__ = "teachers"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    school_id = Column(String(36), ForeignKey("schools.id", ondelete="CASCADE"), nullable=False, index=True)
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    email = Column(String(255), nullable=True)
    phone = Column(String(50), nullable=True)
    fide_title = Column(String(30), nullable=True)  # GM, IM, FM, КМС, Тренер высшей категории
    avatar_url = Column(Text, nullable=True)
    bio = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    school = relationship("School", back_populates="teachers")
    groups = relationship("Group", back_populates="teacher")
    reports = relationship("StudentReport", back_populates="teacher")

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()


class Group(Base):
    """
    Учебная группа в шахматной школе.
    """
    __tablename__ = "groups"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    school_id = Column(String(36), ForeignKey("schools.id", ondelete="CASCADE"), nullable=False, index=True)
    teacher_id = Column(String(36), ForeignKey("teachers.id", ondelete="SET NULL"), nullable=True, index=True)
    name = Column(String(100), nullable=False)  # "Младшая группа 2017 г.р.", "Разрядники 1400-1600"
    level = Column(String(50), nullable=False, default="Начинающие")
    schedule = Column(String(255), nullable=True)  # "Вт, Чт 16:00 - 17:30"
    notes = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    school = relationship("School", back_populates="groups")
    teacher = relationship("Teacher", back_populates="groups")
    students = relationship("StudentProfile", back_populates="group")


class StudentProfile(Base):
    """
    Профиль ученика в рамках школы и группы.
    """
    __tablename__ = "student_profiles"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    school_id = Column(String(36), ForeignKey("schools.id", ondelete="CASCADE"), nullable=True, index=True)
    group_id = Column(String(36), ForeignKey("groups.id", ondelete="SET NULL"), nullable=True, index=True)
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    birth_date = Column(DateTime, nullable=True)
    current_rating = Column(Integer, default=1200, nullable=True)
    parent_name = Column(String(100), nullable=True)
    parent_phone = Column(String(50), nullable=True)
    parent_telegram = Column(String(100), nullable=True)
    notes = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    school = relationship("School", back_populates="students")
    group = relationship("Group", back_populates="students")
    chess_accounts = relationship("StudentChessAccount", back_populates="student", cascade="all, delete-orphan")
    games = relationship("Game", back_populates="student", cascade="all, delete-orphan")
    reports = relationship("StudentReport", back_populates="student", cascade="all, delete-orphan")

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()


class StudentChessAccount(Base):
    """
    Игровой шахматный аккаунт ученика (Lichess или Chess.com).
    """
    __tablename__ = "student_chess_accounts"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    student_profile_id = Column(String(36), ForeignKey("student_profiles.id", ondelete="CASCADE"), nullable=False)
    platform = Column(String(20), nullable=False)  # 'lichess' | 'chesscom'
    username = Column(String(100), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    last_synced_at = Column(DateTime, nullable=True)
    last_game_played_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    student = relationship("StudentProfile", back_populates="chess_accounts")


class Game(Base):
    """
    Сыгранная партия и метаданные стокфиш-анализа.
    """
    __tablename__ = "games"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    student_profile_id = Column(String(36), ForeignKey("student_profiles.id", ondelete="CASCADE"), nullable=False)
    chess_account_id = Column(String(36), ForeignKey("student_chess_accounts.id", ondelete="SET NULL"), nullable=True)
    
    platform = Column(String(20), nullable=False)  # 'lichess' | 'chesscom'
    external_game_id = Column(String(100), nullable=False)
    url = Column(Text, nullable=True)
    played_at = Column(DateTime, nullable=False)
    
    student_color = Column(String(5), nullable=False)  # 'white' | 'black'
    student_rating = Column(Integer, nullable=True)
    opponent_username = Column(String(100), nullable=False)
    opponent_rating = Column(Integer, nullable=True)
    result = Column(String(10), nullable=False)  # '1-0', '0-1', '1/2-1/2'
    winner = Column(String(5), nullable=True)
    time_control = Column(String(50), nullable=True)
    speed_category = Column(String(20), nullable=True)
    
    eco_code = Column(String(10), nullable=True)
    opening_name = Column(String(255), nullable=True)
    
    pgn = Column(Text, nullable=False)
    
    # Engine analysis
    accuracy_score = Column(Numeric(5, 2), nullable=True)
    acpl = Column(Integer, nullable=True)
    blunders_count = Column(Integer, default=0)
    mistakes_count = Column(Integer, default=0)
    inaccuracies_count = Column(Integer, default=0)
    time_spent_blunders_count = Column(Integer, default=0)
    
    analysis_status = Column(String(20), default="pending", nullable=False)  # 'pending', 'processing', 'completed', 'failed'
    analyzed_at = Column(DateTime, nullable=True)
    analysis_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    student = relationship("StudentProfile", back_populates="games")
    error_events = relationship("ChessErrorEvent", back_populates="game", cascade="all, delete-orphan")

    __table_args__ = (
        Index("uq_platform_game", "platform", "external_game_id", unique=True),
        Index("idx_games_status", "analysis_status"),
    )


class ChessErrorEvent(Base):
    """
    Конкретная ошибка или неточность в ходе партии.
    """
    __tablename__ = "chess_error_events"

    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    game_id = Column(String(36), ForeignKey("games.id", ondelete="CASCADE"), nullable=False)
    student_profile_id = Column(String(36), ForeignKey("student_profiles.id", ondelete="CASCADE"), nullable=False)
    
    ply_number = Column(Integer, nullable=False)
    move_number = Column(Integer, nullable=False)
    played_move_san = Column(String(10), nullable=False)
    played_move_uci = Column(String(10), nullable=False)
    best_move_san = Column(String(10), nullable=False)
    best_move_uci = Column(String(10), nullable=False)
    
    fen_before = Column(Text, nullable=False)
    fen_after = Column(Text, nullable=False)
    
    eval_before = Column(Integer, nullable=False)
    eval_after = Column(Integer, nullable=False)
    centipawn_loss = Column(Integer, nullable=False)
    win_rate_drop = Column(Numeric(5, 2), nullable=True)
    
    severity = Column(String(20), nullable=False)  # 'inaccuracy', 'mistake', 'blunder'
    tactical_tag = Column(String(50), nullable=True)
    phase = Column(String(20), nullable=False)  # 'opening', 'middlegame', 'endgame'
    
    time_spent_seconds = Column(Numeric(6, 2), nullable=True)
    clock_remaining_seconds = Column(Numeric(8, 2), nullable=True)
    is_time_trouble = Column(Boolean, default=False)
    
    created_at = Column(DateTime, default=datetime.utcnow)

    game = relationship("Game", back_populates="error_events")


class StudentReport(Base):
    """
    Сгенерированные аналитические и учебные отчеты (Coach / Parent / Worksheet).
    """
    __tablename__ = "student_reports"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    student_profile_id = Column(String(36), ForeignKey("student_profiles.id", ondelete="CASCADE"), nullable=False, index=True)
    school_id = Column(String(36), ForeignKey("schools.id", ondelete="CASCADE"), nullable=True, index=True)
    teacher_id = Column(String(36), ForeignKey("teachers.id", ondelete="SET NULL"), nullable=True, index=True)
    
    report_type = Column(String(50), nullable=False)  # 'coach_technical', 'parent_weekly', 'worksheet_a4'
    title = Column(String(255), nullable=False)
    period_start = Column(DateTime, nullable=True)
    period_end = Column(DateTime, nullable=True)
    games_analyzed_count = Column(Integer, default=0)
    
    executive_summary = Column(Text, nullable=True)
    content_json = Column(JSON, nullable=True)
    pdf_path = Column(Text, nullable=True)
    
    is_sent_to_parent = Column(Boolean, default=False)
    sent_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    student = relationship("StudentProfile", back_populates="reports")
    school = relationship("School", back_populates="reports")
    teacher = relationship("Teacher", back_populates="reports")
