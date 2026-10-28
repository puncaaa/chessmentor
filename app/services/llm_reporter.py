import os
import json
import logging
from typing import List, Dict, Any, Optional
from collections import Counter

from app.schemas.chess import GamePhase, ErrorSeverity, TacticalTag, GameAnalysisResult, AnalyzedMove
from app.schemas.reports import (
    AggregatedStudentStats,
    PhaseBreakdown,
    TimeManagementStats,
    CoachReport,
    ParentReport,
    SystemicPattern,
    HomeworkRecommendation,
)
from app.core.config import settings

logger = logging.getLogger(__name__)


class GameMetricsAggregator:
    """
    Сервис агрегации пула партий ученика за период.
    Рассчитывает объективные шахматные и поведенческие метрики
    без передачи сырых PGN в LLM.
    """

    @staticmethod
    def aggregate(
        student_name: str,
        period_description: str,
        games_data: List[Dict[str, Any]],
    ) -> AggregatedStudentStats:
        """
        games_data: список словарей с ключами:
            - "analysis": GameAnalysisResult
            - "student_color": "white" | "black"
            - "result": "1-0" | "0-1" | "1/2-1/2"
            - "opponent_username": str (optional)
            - "opponent_rating": int (optional)
        """
        if not games_data:
            raise ValueError("Список партий для агрегации пуст.")

        total_games = len(games_data)
        wins = 0
        losses = 0
        draws = 0

        white_stats = {"wins": 0, "losses": 0, "draws": 0}
        black_stats = {"wins": 0, "losses": 0, "draws": 0}

        total_accuracy = 0.0
        total_acpl = 0

        opening_blunders = 0
        middlegame_blunders = 0
        endgame_blunders = 0
        total_inaccuracies = 0
        total_mistakes = 0
        total_blunders = 0

        all_tactical_tags: List[str] = []
        critical_error_samples: List[Dict[str, Any]] = []

        # Тайм-менеджмент
        total_student_moves = 0
        moves_under_15s = 0
        blunders_under_15s = 0
        move_times: List[float] = []
        blunder_times: List[float] = []

        for item in games_data:
            analysis: GameAnalysisResult = item["analysis"]
            color = item.get("student_color", "white").lower()
            res = item.get("result", "")

            # Расчет побед/поражений
            is_win = (color == "white" and res == "1-0") or (color == "black" and res == "0-1")
            is_loss = (color == "white" and res == "0-1") or (color == "black" and res == "1-0")
            is_draw = res in ("1/2-1/2", "0.5-0.5", "draw")

            if is_win:
                wins += 1
                if color == "white":
                    white_stats["wins"] += 1
                else:
                    black_stats["wins"] += 1
            elif is_loss:
                losses += 1
                if color == "white":
                    white_stats["losses"] += 1
                else:
                    black_stats["losses"] += 1
            else:
                draws += 1
                if color == "white":
                    white_stats["draws"] += 1
                else:
                    black_stats["draws"] += 1

            total_accuracy += analysis.accuracy_score
            total_acpl += analysis.acpl
            total_inaccuracies += analysis.inaccuracies_count
            total_mistakes += analysis.mistakes_count
            total_blunders += analysis.blunders_count

            # Анализ ходов и ошибок
            for move in analysis.moves_tree:
                if not move.is_student_move:
                    continue

                total_student_moves += 1
                if move.clock_remaining_seconds is not None:
                    if move.clock_remaining_seconds < 15.0:
                        moves_under_15s += 1

                if move.time_spent_seconds is not None:
                    move_times.append(move.time_spent_seconds)

                if move.severity == ErrorSeverity.BLUNDER:
                    if move.phase == GamePhase.OPENING:
                        opening_blunders += 1
                    elif move.phase == GamePhase.MIDDLEGAME:
                        middlegame_blunders += 1
                    elif move.phase == GamePhase.ENDGAME:
                        endgame_blunders += 1

                    if move.is_time_trouble:
                        blunders_under_15s += 1

                    if move.time_spent_seconds is not None:
                        blunder_times.append(move.time_spent_seconds)

                if move.tactical_tag:
                    all_tactical_tags.append(move.tactical_tag.value)

            for err in analysis.errors:
                if len(critical_error_samples) < 5 and err.severity == ErrorSeverity.BLUNDER:
                    critical_error_samples.append({
                        "move_number": err.move_number,
                        "played_move": err.san,
                        "best_move": err.best_move_san,
                        "centipawn_loss": err.centipawn_loss,
                        "win_rate_drop_pct": round(err.win_rate_drop * 100, 1),
                        "phase": err.phase.value,
                        "tag": err.tactical_tag.value if err.tactical_tag else "tactical_blunder",
                        "time_spent": err.time_spent_seconds,
                        "time_remaining": err.clock_remaining_seconds,
                        "fen_before": err.fen_before,
                    })

        # Агрегирование тегов
        tag_counts = Counter(all_tactical_tags)
        total_tagged = len(all_tactical_tags) or 1
        top_tactical_weaknesses = [
            {
                "tag": tag,
                "count": count,
                "percentage": round((count / total_tagged) * 100, 1),
            }
            for tag, count in tag_counts.most_common(5)
        ]

        # Тайм-менеджмент метрики
        moves_under_15s_rate = (
            round((moves_under_15s / total_student_moves) * 100, 1)
            if total_student_moves
            else 0.0
        )
        blunders_in_time_trouble_rate = (
            round((blunders_under_15s / total_blunders) * 100, 1)
            if total_blunders
            else 0.0
        )
        avg_time = round(sum(move_times) / len(move_times), 1) if move_times else 0.0
        avg_blunder_time = (
            round(sum(blunder_times) / len(blunder_times), 1) if blunder_times else 0.0
        )

        return AggregatedStudentStats(
            student_name=student_name,
            period_description=period_description,
            total_games=total_games,
            wins=wins,
            losses=losses,
            draws=draws,
            win_rate=round((wins / total_games) * 100, 1) if total_games else 0.0,
            white_stats=white_stats,
            black_stats=black_stats,
            avg_accuracy=round(total_accuracy / total_games, 2),
            avg_acpl=int(total_acpl / total_games),
            phase_distribution=PhaseBreakdown(
                opening_blunders=opening_blunders,
                middlegame_blunders=middlegame_blunders,
                endgame_blunders=endgame_blunders,
                total_inaccuracies=total_inaccuracies,
                total_mistakes=total_mistakes,
                total_blunders=total_blunders,
            ),
            time_management=TimeManagementStats(
                total_moves=total_student_moves,
                moves_under_15s_rate=moves_under_15s_rate,
                blunders_in_time_trouble_rate=blunders_in_time_trouble_rate,
                avg_seconds_per_move=avg_time,
                avg_seconds_on_blunders=avg_blunder_time,
            ),
            top_tactical_weaknesses=top_tactical_weaknesses,
            critical_error_samples=critical_error_samples,
        )


class LLMReporterService:
    """
    Генератор двухуровневых отчетов (CoachReport и ParentReport)
    через Structured Outputs (OpenAI / fallback).
    """

    def __init__(self):
        self.provider = settings.LLM_PROVIDER
        self.openai_key = settings.OPENAI_API_KEY or os.getenv("OPENAI_API_KEY", "")
        self.model = settings.OPENAI_MODEL
        self._openai_client = None

    def _get_openai_client(self):
        if not self._openai_client and self.openai_key:
            from openai import OpenAI
            self._openai_client = OpenAI(api_key=self.openai_key)
        return self._openai_client

    def generate_coach_report(self, stats: AggregatedStudentStats) -> CoachReport:
        """
        Генерация экспертного фактологического отчета для тренера.
        """
        client = self._get_openai_client()
        if not client:
            logger.info("OpenAI API key не настроен. Используем эвристический fallback-генератор CoachReport.")
            return self._fallback_coach_report(stats)

        system_prompt = (
            "Ты — Senior Chess Coach & Data Analyst в профессиональной шахматной академии.\n"
            "Твоя задача — составить строгий фактологический аудит игры ученика на основе агрегированных данных.\n"
            "ПРАВИЛА:\n"
            "1. Тон: экспертный, педагогический, четкий, без воды.\n"
            "2. Выдели ровно топ-3 системных хронических паттерна ошибок ученика на основе фаз и тактических тегов.\n"
            "3. Оцени поведение в цейтноте: как меняется качество решений при < 15 сек на часах.\n"
            "4. Предложи конкретные темы для следующих занятий и сфокусированное домашнее задание."
        )

        user_prompt = f"""
Данные игры ученика:
Имя: {stats.student_name}
Период: {stats.period_description}
Всего партий: {stats.total_games} (Побед: {stats.wins}, Поражений: {stats.losses}, Ничьих: {stats.draws}, Винрейт: {stats.win_rate}%)
Баланс цветов: Белыми: {stats.white_stats}, Черными: {stats.black_stats}
Средняя точность (CAPS): {stats.avg_accuracy}% | Средняя потеря сантипешек (ACPL): {stats.avg_acpl}

Распределение ошибок по фазам:
- Дебютные зевки: {stats.phase_distribution.opening_blunders}
- Миттельшпильные зевки: {stats.phase_distribution.middlegame_blunders}
- Эндшпильные зевки: {stats.phase_distribution.endgame_blunders}
- Всего зевков: {stats.phase_distribution.total_blunders}, ошибок: {stats.phase_distribution.total_mistakes}, неточностей: {stats.phase_distribution.total_inaccuracies}

Тайм-менеджмент:
- Доля ходов в цейтноте (< 15с): {stats.time_management.moves_under_15s_rate}%
- Доля зевков под флагом: {stats.time_management.blunders_in_time_trouble_rate}%
- Среднее время на обычный ход: {stats.time_management.avg_seconds_per_move}с, на зевке: {stats.time_management.avg_seconds_on_blunders}с

Топ тактических слабостей:
{json.dumps(stats.top_tactical_weaknesses, ensure_ascii=False, indent=2)}

Примеры критических сбоев:
{json.dumps(stats.critical_error_samples, ensure_ascii=False, indent=2)}
"""

        try:
            completion = client.beta.chat.completions.parse(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format=CoachReport,
                temperature=0.2,
            )
            return completion.choices[0].message.parsed
        except Exception as exc:
            logger.error(f"Ошибка при вызове OpenAI Structured Output: {exc}. Переход на fallback.")
            return self._fallback_coach_report(stats)

    def generate_parent_report(self, stats: AggregatedStudentStats) -> ParentReport:
        """
        Генерация эмпатичного отчета для родителей без шахматной терминологии.
        """
        client = self._get_openai_client()
        if not client:
            logger.info("OpenAI API key не настроен. Используем эвристический fallback-генератор ParentReport.")
            return self._fallback_parent_report(stats)

        system_prompt = (
            "Ты — заботливый детский шахматный наставник и психолог.\n"
            "Твоя задача — составить отчет для родителей ученика простым, поддерживающим и понятным языком.\n"
            "КРИТИЧЕСКИЕ ПРАВИЛА:\n"
            "1. ЗАПРЕЩЕНО использовать шахматный жаргон: слова 'сантипешки', 'ACPL', 'CAPS', 'миттельшпиль', 'эндшпиль', 'гамбит', 'зевок пешки на c4'.\n"
            "2. Переводить на понятный язык: вместо 'эндшпиль' говорить 'завершающая стадия партии', вместо 'зевок легкой фигуры' говорить 'потеря защитников'.\n"
            "3. Фокус на прогрессе, психологической выдержке, дисциплине и внимательности.\n"
            "4. Зону роста описать доброжелательно, а не как упрек.\n"
            "5. Дать родителю один теплый и применимый совет для дома."
        )

        user_prompt = f"""
Данные ученика:
Имя ребенка: {stats.student_name}
Период: {stats.period_description}
Сыграно партий: {stats.total_games} (Побед: {stats.wins})
Точность игры: {stats.avg_accuracy}%
Ошибки: чаще всего в середине игры ({stats.phase_distribution.middlegame_blunders} случаев), в цейтноте ({stats.time_management.blunders_in_time_trouble_rate}% зевков)
Топ уязвимостей: {', '.join([w['tag'] for w in stats.top_tactical_weaknesses])}
"""

        try:
            completion = client.beta.chat.completions.parse(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format=ParentReport,
                temperature=0.3,
            )
            return completion.choices[0].message.parsed
        except Exception as exc:
            logger.error(f"Ошибка при вызове OpenAI Structured Output: {exc}. Переход на fallback.")
            return self._fallback_parent_report(stats)

    # ========================================================================
    # РЕЗЕРВНЫЕ ЭВРИСТИЧЕСКИЕ ГЕНЕРАТОРЫ (Гарантируют работоспособность без ключей)
    # ========================================================================

    def _fallback_coach_report(self, stats: AggregatedStudentStats) -> CoachReport:
        patterns: List[SystemicPattern] = []

        # Детекция паттерна 1: Цейтнот
        if stats.time_management.blunders_in_time_trouble_rate > 30:
            patterns.append(
                SystemicPattern(
                    title="Коллапс качества в цейтноте (< 15 секунд)",
                    description=(
                        f"Ученик допускает {stats.time_management.blunders_in_time_trouble_rate}% всех критических зевков, "
                        f"когда на часах остается менее 15 секунд. Среднее время на ход снижается до {stats.time_management.avg_seconds_on_blunders}с."
                    ),
                    frequency=f"{stats.time_management.blunders_in_time_trouble_rate}% всех зевков",
                    severity="critical",
                )
            )

        # Детекция паттерна 2: Висячие фигуры / зевки тактики
        hanging_tag = next((w for w in stats.top_tactical_weaknesses if w["tag"] == "hanging_piece"), None)
        if hanging_tag:
            patterns.append(
                SystemicPattern(
                    title="Оставление фигур без защиты под ударом",
                    description=(
                        f"Хроническая потеря материала: {hanging_tag['count']} случаев подбоя легких или тяжелых фигур "
                        "без адекватного тактического обоснования."
                    ),
                    frequency=f"{hanging_tag['percentage']}% от всех тактических ошибок",
                    severity="critical" if hanging_tag["percentage"] > 25 else "moderate",
                )
            )

        # Паттерн 3: Фазовая специфика
        if stats.phase_distribution.middlegame_blunders >= stats.phase_distribution.opening_blunders:
            patterns.append(
                SystemicPattern(
                    title="Снижение концентрации в сложном миттельшпиле",
                    description=(
                        f"Основная масса грубых ошибок ({stats.phase_distribution.middlegame_blunders}) приходится на разгар борьбы "
                        "при переходе из дебюта в тактический миттельшпиль."
                    ),
                    frequency=f"{stats.phase_distribution.middlegame_blunders} ошибок за период",
                    severity="moderate",
                )
            )

        if not patterns:
            patterns.append(
                SystemicPattern(
                    title="Стабильная позиционная игра",
                    description="Грубых системных аномалий не зафиксировано, ошибки носят стохастический характер.",
                    frequency="Редкие эпизоды",
                    severity="minor",
                )
            )

        # Домашнее задание
        homework = [
            HomeworkRecommendation(
                topic="Двойные удары и защита незащищенных фигур",
                target_pattern="hanging_piece",
                recommended_puzzles_count=10,
                focus_description="Перед каждым ходом задавать себе контрольный вопрос: 'Что атаковал соперник своим последним ходом?'",
            ),
            HomeworkRecommendation(
                topic="Управление временем в классике и рапиде",
                target_pattern="time_trouble_panic",
                recommended_puzzles_count=5,
                focus_description="Играть тренировочные партии с инкрементом +2/3 секунды, не опускать флаг ниже 30 секунд.",
            ),
        ]

        return CoachReport(
            student_name=stats.student_name,
            period=stats.period_description,
            executive_summary=(
                f"За отчетный период ученик сыграл {stats.total_games} партий с общим винрейтом {stats.win_rate}%. "
                f"Средняя точность составила {stats.avg_accuracy}%, ACPL: {stats.avg_acpl}. "
                "Ключевая проблема недели — распределение времени в эндшпиле и зевки фигур при нехватке времени."
            ),
            aggregated_metrics_summary=(
                f"Дебют: {stats.phase_distribution.opening_blunders} зевков. "
                f"Миттельшпиль: {stats.phase_distribution.middlegame_blunders} зевков. "
                f"Эндшпиль: {stats.phase_distribution.endgame_blunders} зевков. "
                f"Потери очков белыми: {stats.white_stats.get('losses', 0)}, черными: {stats.black_stats.get('losses', 0)}."
            ),
            systemic_patterns=patterns[:3],
            time_trouble_verdict=(
                f"В цейтноте совершено {stats.time_management.blunders_in_time_trouble_rate}% всех зевков. "
                "Требуется работа над дозированием времени на критических развилках партии."
            ),
            next_lessons_plan=[
                "Разбор типовых структур в миттельшпиле и методы защиты висячих фигур",
                "Тренировка тактической зоркости на зевки 1-2 ходовка",
                "Психология и расчет ходов в условиях ограниченного времени (< 30 секунд)",
            ],
            homework_assignment=homework,
        )

    def _fallback_parent_report(self, stats: AggregatedStudentStats) -> ParentReport:
        achievements = [
            f"Сыграл {stats.total_games} полноценных партий и одержал {stats.wins} уверенных побед!",
            f"Показал отличную среднюю аккуратность в игре ({int(stats.avg_accuracy)}% точности решений).",
            "Уверенно разыгрывает стартовую часть партии, быстро выводя фигуры на рабочие позиции.",
        ]

        areas_for_growth = [
            "Приучаемся не спешить, когда на часах остается мало времени — шахматы любят спокойное дыхание.",
            "Перед каждым ходом вырабатываем привычку внимательно смотреть, не нацелилась ли фигура соперника на нашего защитника.",
        ]

        return ParentReport(
            child_name=stats.student_name,
            period=stats.period_description,
            greeting_and_summary=(
                f"Здравствуйте! Делимся успехами {stats.student_name} в шахматах за прошедшую неделю ({stats.period_description}). "
                f"Ребенок провел очень активную неделю, проявил боевой характер и выиграл {stats.wins} партий!"
            ),
            achievements=achievements,
            areas_for_growth=areas_for_growth,
            home_support_advice=(
                f"Хвалите {stats.student_name} не только за победы, но и за партии, где он долго и вдумчиво думал над сложными ходами. "
                "Если играете дома, попробуйте поиграть без строгих часов или просто спросите: 'Какая фигура у тебя сейчас самая любимая?'"
            ),
        )
