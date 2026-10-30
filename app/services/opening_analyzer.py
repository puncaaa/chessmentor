import io
import math
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
import chess.pgn

from app.models.chess import Game, ChessErrorEvent


@dataclass
class OpeningGapInfo:
    """Статистика и аналитика по конкретному дебюту ученика."""
    eco: str
    name: str
    color: str  # 'white' | 'black'
    games_count: int
    wins: int
    draws: int
    losses: int
    win_rate: float
    opening_acpl: int
    opening_accuracy: float
    early_errors_count: int
    early_blunders_count: int
    status: str  # 'Надежно' | 'Требует разбора' | 'Критическая дыра'
    status_color: str  # 'green' | 'amber' | 'red'
    coach_tip: str
    is_hole: bool = False
    sample_game_ids: List[str] = field(default_factory=list)


@dataclass
class RepertoireAnalysisResult:
    """Сводный результат анализа дебютного репертуара ученика."""
    student_name: str
    white_openings: List[OpeningGapInfo]
    black_openings: List[OpeningGapInfo]
    repertoire_holes: List[OpeningGapInfo]
    repertoire_strengths: List[OpeningGapInfo]
    total_games: int
    white_games_count: int
    black_games_count: int
    summary_insight: str


class OpeningAnalyzerService:
    """
    Сервис анализа дебютного дерева и поиска уязвимостей в репертуаре (Repertoire Gap Finder).
    """

    @staticmethod
    def extract_opening_info(game: Game) -> Dict[str, str]:
        """
        Извлечение ECO и названия дебюта из колонок модели или PGN-заголовков.
        """
        eco = (game.eco_code or "").strip()
        opening = (game.opening_name or "").strip()

        # Если не заполнено в модели — парсим из PGN-заголовков
        if (not eco or not opening) and game.pgn:
            try:
                pgn_game = chess.pgn.read_game(io.StringIO(game.pgn))
                if pgn_game:
                    if not eco:
                        eco = pgn_game.headers.get("ECO", "").strip()
                    if not opening:
                        opening = pgn_game.headers.get("Opening", "").strip()
            except Exception:
                pass

        if not eco:
            eco = "A00"
        if not opening:
            opening = "Неопределенный дебют"

        return {"eco": eco, "opening": opening}

    @staticmethod
    def calculate_opening_cpl_and_errors(game: Game) -> Dict[str, Any]:
        """
        Расчет среднего CPL и количества ошибок именно в дебюте (первые 10-12 ходов).
        """
        opening_cpls: List[int] = []
        early_errors = 0
        early_blunders = 0

        # Если доступен детальный moves_tree в analysis_json
        if game.analysis_json and isinstance(game.analysis_json, list):
            for move in game.analysis_json:
                if not isinstance(move, dict):
                    continue
                if not move.get("is_student_move", False):
                    continue

                move_num = move.get("move_number", 0)
                phase = move.get("phase", "")

                # Дебютная фаза: до 12 хода включительно или фаза 'opening'
                if move_num <= 12 or phase == "opening":
                    cpl = move.get("centipawn_loss")
                    if cpl is not None:
                        opening_cpls.append(int(cpl))

                # Ранние критические ошибки: ходы 1-15
                if move_num <= 15:
                    sev = move.get("severity")
                    if sev == "blunder":
                        early_blunders += 1
                        early_errors += 1
                    elif sev in ("mistake", "inaccuracy"):
                        early_errors += 1

        # Если детального analysis_json нет — используем общие метрики партии
        if not opening_cpls:
            base_acpl = game.acpl if game.acpl is not None else 30
            opening_cpls = [base_acpl]

        avg_opening_cpl = int(sum(opening_cpls) / len(opening_cpls)) if opening_cpls else 30
        
        # Конвертация CPL в процент точности (CAPS-like)
        opening_acc = max(0.0, min(100.0, round(100.0 - avg_opening_cpl * 0.75, 1)))

        return {
            "opening_acpl": avg_opening_cpl,
            "opening_accuracy": opening_acc,
            "early_errors": early_errors,
            "early_blunders": early_blunders,
        }

    @classmethod
    def analyze_repertoire(
        cls,
        games: List[Game],
        student_name: str = "Ученик"
    ) -> RepertoireAnalysisResult:
        """
        Полный анализ репертуара по пулу сыгранных партий.
        """
        if not games:
            return RepertoireAnalysisResult(
                student_name=student_name,
                white_openings=[],
                black_openings=[],
                repertoire_holes=[],
                repertoire_strengths=[],
                total_games=0,
                white_games_count=0,
                black_games_count=0,
                summary_insight="Нет сыгранных партий для анализа дебютного репертуара."
            )

        # Группировка по (color, eco, opening)
        grouped: Dict[tuple, List[Dict[str, Any]]] = {}

        for g in games:
            color = g.student_color.lower() if g.student_color else "white"
            info = cls.extract_opening_info(g)
            cpl_stats = cls.calculate_opening_cpl_and_errors(g)

            res = g.result or "*"
            is_win = (color == "white" and res == "1-0") or (color == "black" and res == "0-1")
            is_loss = (color == "white" and res == "0-1") or (color == "black" and res == "1-0")
            is_draw = res in ("1/2-1/2", "0.5-0.5", "1/2")

            key = (color, info["eco"], info["opening"])
            grouped.setdefault(key, []).append({
                "game_id": g.id,
                "is_win": is_win,
                "is_loss": is_loss,
                "is_draw": is_draw,
                "opening_acpl": cpl_stats["opening_acpl"],
                "opening_accuracy": cpl_stats["opening_accuracy"],
                "early_errors": cpl_stats["early_errors"],
                "early_blunders": cpl_stats["early_blunders"],
            })

        white_list: List[OpeningGapInfo] = []
        black_list: List[OpeningGapInfo] = []

        for (color, eco, name), records in grouped.items():
            total = len(records)
            wins = sum(1 for r in records if r["is_win"])
            draws = sum(1 for r in records if r["is_draw"])
            losses = sum(1 for r in records if r["is_loss"])
            win_rate = round((wins / total) * 100, 1)

            avg_cpl = int(sum(r["opening_acpl"] for r in records) / total)
            avg_acc = round(sum(r["opening_accuracy"] for r in records) / total, 1)
            total_early_errors = sum(r["early_errors"] for r in records)
            total_early_blunders = sum(r["early_blunders"] for r in records)
            sample_ids = [r["game_id"] for r in records]

            # Классификация надежности / дыры согласно требованиям:
            # Уязвимостью (дырой) считаются ТОЛЬКО варианты, где сыграно >= 2 партий
            # И (винрейт < 45% ИЛИ дебютный ACPL > 35).
            # При винрейте 100% дебют ОБЯЗАТЕЛЬНО помечается зеленым бейджем "Надежно".
            color_ru = "белых" if color == "white" else "черных"

            if win_rate >= 100.0 or total < 2:
                is_hole = False
                status = "Надежно"
                status_color = "green"
                if win_rate >= 100.0:
                    coach_tip = (
                        f"✅ Надежно: 100% побед в {name} за {color_ru} ({eco}) — "
                        f"дебютный ACPL {avg_cpl}, стабильное разыгрывание, надежный выбор."
                    )
                else:
                    coach_tip = (
                        f"✅ Надежно: {name} за {color_ru} ({eco}) — сыграна 1 партия (винрейт {win_rate}%), "
                        f"дебютный ACPL {avg_cpl}. Недостаточно партий для фиксации уязвимости."
                    )
            elif total >= 2 and (win_rate < 45.0 or avg_cpl > 35):
                is_hole = True
                if win_rate <= 30.0 or avg_cpl >= 45 or total_early_blunders >= 2:
                    status = "Критическая дыра"
                    status_color = "red"
                    coach_tip = (
                        f"⚠️ Критическая дыра: {name} за {color_ru} ({eco}) — {total} партий, винрейт {win_rate}%. "
                        f"Дебютный ACPL {avg_cpl}, ранних зевков: {total_early_blunders}. "
                        f"Рекомендуется разбор базовых планов и пешечных структур."
                    )
                else:
                    status = "Требует разбора"
                    status_color = "amber"
                    coach_tip = (
                        f"🔍 Требует разбора: {name} за {color_ru} ({eco}) — {total} партий, винрейт {win_rate}%, "
                        f"дебютный ACPL {avg_cpl}. Зафиксировано ранних ошибок: {total_early_errors}."
                    )
            else:
                is_hole = False
                status = "Надежно"
                status_color = "green"
                coach_tip = (
                    f"✅ Надежно: {name} за {color_ru} ({eco}) — {total} партий, винрейт {win_rate}%, "
                    f"дебютный ACPL {avg_cpl}, точность в дебюте {avg_acc}%, стабильное разыгрывание."
                )

            gap_info = OpeningGapInfo(
                eco=eco,
                name=name,
                color=color,
                games_count=total,
                wins=wins,
                draws=draws,
                losses=losses,
                win_rate=win_rate,
                opening_acpl=avg_cpl,
                opening_accuracy=avg_acc,
                early_errors_count=total_early_errors,
                early_blunders_count=total_early_blunders,
                status=status,
                status_color=status_color,
                coach_tip=coach_tip,
                is_hole=is_hole,
                sample_game_ids=sample_ids
            )

            if color == "white":
                white_list.append(gap_info)
            else:
                black_list.append(gap_info)

        # Сортировка: сначала самые популярные, затем с наименьшим винрейтом
        white_list.sort(key=lambda x: (x.games_count, -x.win_rate), reverse=True)
        black_list.sort(key=lambda x: (x.games_count, -x.win_rate), reverse=True)

        all_openings = white_list + black_list
        holes = [o for o in all_openings if o.is_hole]
        holes.sort(key=lambda x: (x.status == "Критическая дыра", x.games_count, -x.opening_acpl), reverse=True)

        strengths = [o for o in all_openings if not o.is_hole]
        strengths.sort(key=lambda x: (x.games_count, x.win_rate), reverse=True)

        # Сводный инсайт для тренера
        if holes:
            top_hole = holes[0]
            summary_insight = (
                f"Главная точка приложения усилий в дебюте — **{top_hole.name}** "
                f"за {'белых' if top_hole.color == 'white' else 'черных'} (винрейт {top_hole.win_rate}% при {top_hole.games_count} играх, "
                f"дебютный ACPL: {top_hole.opening_acpl})."
            )
        else:
            summary_insight = "Дебютный репертуар ученика сбалансирован: критических системных провалов на первых 15 ходах не выявлено."

        return RepertoireAnalysisResult(
            student_name=student_name,
            white_openings=white_list,
            black_openings=black_list,
            repertoire_holes=holes,
            repertoire_strengths=strengths,
            total_games=len(games),
            white_games_count=sum(o.games_count for o in white_list),
            black_games_count=sum(o.games_count for o in black_list),
            summary_insight=summary_insight
        )
