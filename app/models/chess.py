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

def generate_uuid():
    return str(uuid.uuid4())

class StudentProfile(Base):
    __tablename__ = "student_profiles"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    chess_accounts = relationship("StudentChessAccount", back_populates="student", cascade="all, delete-orphan")
    games = relationship("Game", back_populates="student", cascade="all, delete-orphan")


class StudentChessAccount(Base):
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
