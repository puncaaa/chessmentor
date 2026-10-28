from enum import Enum
from typing import List, Dict, Optional, Any
from pydantic import BaseModel, Field
from app.schemas.chess import TacticalTag, GamePhase

class SystemicPattern(BaseModel):
    title: str = Field(..., description="Название системного паттерна ошибки (например, 'Зевок пешечной вилки в центре')")
    description: str = Field(..., description="Детальное объяснение механики ошибки и контекста позиции")
    frequency: str = Field(..., description="Частота проявления (например, 'Встретилось в 4 из 10 партий')")
    severity: str = Field(..., description="Степень критичности: critical | moderate | minor")

class HomeworkRecommendation(BaseModel):
    topic: str = Field(..., description="Тема домашнего задания (например: 'Защита от двойного удара')")
    target_pattern: str = Field(..., description="Связанный паттерн ошибки ученика")
    recommended_puzzles_count: int = Field(default=5, description="Рекомендуемое количество задач")
    focus_description: str = Field(..., description="Инструкция для ученика: на что обращать внимание")

class PhaseBreakdown(BaseModel):
    opening_blunders: int = Field(default=0, description="Количество зевков в дебюте")
    middlegame_blunders: int = Field(default=0, description="Количество зевков в миттельшпиле")
    endgame_blunders: int = Field(default=0, description="Количество зевков в эндшпиле")
    total_inaccuracies: int = Field(default=0)
    total_mistakes: int = Field(default=0)
    total_blunders: int = Field(default=0)

class TimeManagementStats(BaseModel):
    total_moves: int = Field(default=0)
    moves_under_15s_rate: float = Field(default=0.0, description="Процент ходов в цейтноте (< 15 сек)")
    blunders_in_time_trouble_rate: float = Field(default=0.0, description="Доля зевков, совершенных в цейтноте (< 15 сек)")
    avg_seconds_per_move: float = Field(default=0.0)
    avg_seconds_on_blunders: float = Field(default=0.0)

class AggregatedStudentStats(BaseModel):
    student_name: str
    period_description: str
    total_games: int
    wins: int
    losses: int
    draws: int
    win_rate: float
    white_stats: Dict[str, int] = Field(default_factory=dict, description="{'wins': N, 'losses': N, 'draws': N}")
    black_stats: Dict[str, int] = Field(default_factory=dict, description="{'wins': N, 'losses': N, 'draws': N}")
    avg_accuracy: float
    avg_acpl: int
    phase_distribution: PhaseBreakdown
    time_management: TimeManagementStats
    top_tactical_weaknesses: List[Dict[str, Any]] = Field(default_factory=list, description="Распределение тегов ошибок")
    critical_error_samples: List[Dict[str, Any]] = Field(default_factory=list, description="Топ-3 характерных примера ошибок")

# ============================================================================
# LLM STRUCTURED OUTPUTS
# ============================================================================

class CoachReport(BaseModel):
    student_name: str = Field(..., description="Имя ученика")
    period: str = Field(..., description="Период анализа (например, '21 - 28 октября 2026')")
    executive_summary: str = Field(..., description="Краткий фактологический вывод для тренера (1-2 абзаца)")
    aggregated_metrics_summary: str = Field(..., description="Анализ динамики ACPL, точности и распределения по фазам партии")
    systemic_patterns: List[SystemicPattern] = Field(..., description="Топ-3 хронических паттерна ошибок")
    time_trouble_verdict: str = Field(..., description="Оценка дисциплины тайм-менеджмента и решений под флагом")
    next_lessons_plan: List[str] = Field(..., description="Конкретные темы и упражнения для следующих уроков")
    homework_assignment: List[HomeworkRecommendation] = Field(..., description="Рекомендованное ДЗ по слабым точкам")

class ParentReport(BaseModel):
    child_name: str = Field(..., description="Имя ребенка")
    period: str = Field(..., description="Период отчета")
    greeting_and_summary: str = Field(..., description="Теплое и понятное обращение к родителю о неделе в шахматах")
    achievements: List[str] = Field(..., description="2-4 конкретных успеха ребенка простым языком без шахматного жаргона")
    areas_for_growth: List[str] = Field(..., description="1-2 точки роста в мягкой позитивной форме")
    home_support_advice: str = Field(..., description="Практический совет родителю: как похвалить и поддержать дома")
