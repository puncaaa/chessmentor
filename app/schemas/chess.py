from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field

class GamePhase(str, Enum):
    OPENING = "opening"
    MIDDLEGAME = "middlegame"
    ENDGAME = "endgame"

class ErrorSeverity(str, Enum):
    INACCURACY = "inaccuracy"
    MISTAKE = "mistake"
    BLUNDER = "blunder"

class TacticalTag(str, Enum):
    HANGING_PIECE = "hanging_piece"
    MISSED_MATE = "missed_mate_sequence"
    TIME_TROUBLE_PANIC = "time_trouble_panic"
    TACTICAL_BLUNDER = "tactical_blunder"

class AnalyzedMove(BaseModel):
    ply: int
    move_number: int
    is_student_move: bool
    san: str
    uci: str
    best_move_san: str
    best_move_uci: str
    fen_before: str
    fen_after: str
    
    eval_before_cp: int
    eval_after_cp: int
    centipawn_loss: int = 0
    win_rate_drop: float = 0.0
    
    phase: GamePhase
    severity: Optional[ErrorSeverity] = None
    tactical_tag: Optional[TacticalTag] = None
    
    time_spent_seconds: Optional[float] = None
    clock_remaining_seconds: Optional[float] = None
    is_time_trouble: bool = False

class GameAnalysisResult(BaseModel):
    accuracy_score: float = Field(..., description="CAPS-подобная точность (0-100%)")
    acpl: int = Field(..., description="Average Centipawn Loss")
    blunders_count: int = 0
    mistakes_count: int = 0
    inaccuracies_count: int = 0
    time_blunders_count: int = 0
    errors: List[AnalyzedMove] = Field(default_factory=list, description="Список проблемных ходов для БД")
    moves_tree: List[AnalyzedMove] = Field(default_factory=list, description="Полный лог ходов для фронтенда")
