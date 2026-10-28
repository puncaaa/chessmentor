"""
Демо-скрипт полного пайплайна:
1. Анализ пула партий ученика через Stockfish (python-chess).
2. Агрегация шахматных и тайминг-метрик через GameMetricsAggregator.
3. Генерация двухуровневого отчета через LLMReporterService:
   - Экспертный CoachReport (факты, паттерны, ДЗ, план уроков)
   - Эмпатичный ParentReport (без заумных терминов, поддержка, прогресс)

Запуск:
    source .venv/bin/activate
    python demo_analysis.py
"""
import shutil
import json
import chess

from app.services.chess_analyzer import ChessEngineAnalyzer
from app.services.llm_reporter import GameMetricsAggregator, LLMReporterService

# Пул из 3 партий ученика "Петя Смирнов"
GAMES_POOL = [
    {
        "student_color": "white",
        "result": "0-1",
        "opponent": "TacticsMaster",
        "pgn": """[Event "Rated Blitz game"]
[Site "Chess.com"]
[Date "2026.10.25"]
[White "Петя Смирнов"]
[Black "TacticsMaster"]
[Result "0-1"]
[TimeControl "180+2"]

1. e4 {[%clk 0:03:00]} 1... e5 {[%clk 0:03:00]} 
2. Nf3 {[%clk 0:02:58]} 2... Nc6 {[%clk 0:02:59]} 
3. Bc4 {[%clk 0:02:55]} 3... Bc5 {[%clk 0:02:56]} 
4. c3 {[%clk 0:02:50]} 4... Nf6 {[%clk 0:02:52]} 
5. d4 {[%clk 0:02:44]} 5... exd4 {[%clk 0:02:49]} 
6. cxd4 {[%clk 0:02:40]} 6... Bb4+ {[%clk 0:02:45]} 
7. Nc3 {[%clk 0:02:35]} 7... Nxe4 {[%clk 0:02:40]} 
8. O-O {[%clk 0:02:25]} 8... Bxc3 {[%clk 0:02:30]} 
9. d5 {[%clk 0:02:15]} 9... Ne5 {[%clk 0:02:20]} 
10. bxc3 {[%clk 0:02:00]} 10... Nxc4 {[%clk 0:02:10]} 
11. Qd4 {[%clk 0:01:45]} 11... O-O {[%clk 0:01:50]} 
12. Qxe4 {[%clk 0:01:30]} 12... Nd6 {[%clk 0:01:40]} 
13. Qd3 {[%clk 0:00:14]} 13... Qf6 {[%clk 0:01:25]} 
14. Ba3 {[%clk 0:00:04]} 14... b6 {[%clk 0:01:10]} 
15. Rfe1 {[%clk 0:00:03]} 15... Bb7 {[%clk 0:00:55]} 
0-1
"""
    },
    {
        "student_color": "white",
        "result": "1-0",
        "opponent": "JuniorKnight",
        "pgn": """[Event "Rated Blitz game"]
[Site "Chess.com"]
[Date "2026.10.26"]
[White "Петя Смирнов"]
[Black "JuniorKnight"]
[Result "1-0"]
[TimeControl "180+2"]

1. e4 {[%clk 0:03:00]} 1... d5 {[%clk 0:02:58]} 
2. exd5 {[%clk 0:02:57]} 2... Qxd5 {[%clk 0:02:55]} 
3. Nc3 {[%clk 0:02:54]} 3... Qa5 {[%clk 0:02:50]} 
4. d4 {[%clk 0:02:48]} 4... Nf6 {[%clk 0:02:45]} 
5. Nf3 {[%clk 0:02:42]} 5... Bg4 {[%clk 0:02:38]} 
6. h3 {[%clk 0:02:35]} 6... Bh5 {[%clk 0:02:30]} 
7. g4 {[%clk 0:02:25]} 7... Bg6 {[%clk 0:02:22]} 
8. Ne5 {[%clk 0:02:15]} 8... c6 {[%clk 0:02:10]} 
9. h4 {[%clk 0:02:05]} 9... Nbd7 {[%clk 0:02:00]} 
10. Nc4 {[%clk 0:01:55]} 10... Qc7 {[%clk 0:01:45]} 
11. h5 {[%clk 0:01:48]} 11... Be4 {[%clk 0:01:30]} 
12. Nxe4 {[%clk 0:01:40]} 12... Nxe4 {[%clk 0:01:25]} 
13. Qf3 {[%clk 0:01:30]} 13... Nd6 {[%clk 0:01:15]} 
14. Bf4 {[%clk 0:01:20]} 14... e6 {[%clk 0:01:05]} 
15. O-O-O {[%clk 0:01:10]} 15... O-O-O {[%clk 0:00:55]} 
1-0
"""
    },
    {
        "student_color": "black",
        "result": "0-1",
        "opponent": "SolidPawn",
        "pgn": """[Event "Rated Blitz game"]
[Site "Chess.com"]
[Date "2026.10.27"]
[White "SolidPawn"]
[Black "Петя Смирнов"]
[Result "0-1"]
[TimeControl "180+2"]

1. d4 {[%clk 0:03:00]} 1... d5 {[%clk 0:02:59]} 
2. c4 {[%clk 0:02:58]} 2... e6 {[%clk 0:02:56]} 
3. Nc3 {[%clk 0:02:55]} 3... Nf6 {[%clk 0:02:52]} 
4. Bg5 {[%clk 0:02:50]} 4... Be7 {[%clk 0:02:48]} 
5. e3 {[%clk 0:02:45]} 5... O-O {[%clk 0:02:42]} 
6. Nf3 {[%clk 0:02:40]} 6... h6 {[%clk 0:02:35]} 
7. Bh4 {[%clk 0:02:35]} 7... b6 {[%clk 0:02:28]} 
8. cxd5 {[%clk 0:02:30]} 8... Nxd5 {[%clk 0:02:20]} 
9. Bxe7 {[%clk 0:02:25]} 9... Qxe7 {[%clk 0:02:15]} 
10. Nxd5 {[%clk 0:02:20]} 10... exd5 {[%clk 0:02:10]} 
11. Bd3 {[%clk 0:02:15]} 11... Bg4 {[%clk 0:02:00]} 
12. O-O {[%clk 0:02:10]} 12... Nd7 {[%clk 0:01:50]} 
0-1
"""
    }
]

def main():
    stockfish_bin = shutil.which("stockfish") or "/opt/homebrew/bin/stockfish"
    print("=" * 70)
    print("🚀 СТАРТ ПАЙПЛАЙНА АНАЛИЗА И ГЕНЕРАЦИИ ДВУХУРОВНЕВЫХ ОТЧЕТОВ")
    print(f"♟️ Stockfish binary: {stockfish_bin}")
    print("=" * 70)

    # 1. Запуск движка и анализ каждой партии
    analyzed_games = []
    with ChessEngineAnalyzer(stockfish_path=stockfish_bin, depth=12, threads=2) as analyzer:
        for idx, g in enumerate(GAMES_POOL, 1):
            color = chess.WHITE if g["student_color"] == "white" else chess.BLACK
            print(f"▶️ Анализ партии {idx}/{len(GAMES_POOL)} (Соперник: {g['opponent']}, Цвет: {g['student_color']})...")
            analysis_res = analyzer.analyze_game(g["pgn"], student_color=color)
            analyzed_games.append({
                "analysis": analysis_res,
                "student_color": g["student_color"],
                "result": g["result"],
                "opponent_username": g["opponent"]
            })
            print(f"   Точность: {analysis_res.accuracy_score}%, ACPL: {analysis_res.acpl}, Зевков: {analysis_res.blunders_count}")

    # 2. Агрегация метрик по пулу партий
    print("\n" + "=" * 70)
    print("📊 АГРЕГАЦИЯ ДАННЫХ ЧЕРЕЗ GameMetricsAggregator")
    print("=" * 70)
    aggregator = GameMetricsAggregator()
    stats = aggregator.aggregate(
        student_name="Петя Смирнов",
        period_description="21 - 28 октября 2026",
        games_data=analyzed_games
    )

    print(f"Ученик: {stats.student_name} | Период: {stats.period_description}")
    print(f"Всего партий: {stats.total_games} | Побед: {stats.wins} | Поражений: {stats.losses} | Винрейт: {stats.win_rate}%")
    print(f"Средняя точность: {stats.avg_accuracy}% | Средний ACPL: {stats.avg_acpl}")
    print(f"Зевки по фазам: Дебют={stats.phase_distribution.opening_blunders}, Миттельшпиль={stats.phase_distribution.middlegame_blunders}, Эндшпиль={stats.phase_distribution.endgame_blunders}")
    print(f"Тайм-менеджмент: Ходов < 15с = {stats.time_management.moves_under_15s_rate}%, Зевков под флагом = {stats.time_management.blunders_in_time_trouble_rate}%")

    # 3. Генерация отчетов через LLM
    reporter = LLMReporterService()

    print("\n" + "=" * 70)
    print("🎓 1. ОТЧЕТ ДЛЯ ТРЕНЕРА (CoachReport) — ФАКТЫ, ПАТТЕРНЫ, ДЗ")
    print("=" * 70)
    coach_report = reporter.generate_coach_report(stats)
    print(f"Ученик: {coach_report.student_name} | Период: {coach_report.period}\n")
    print("Резюме тренеру:")
    print(f"{coach_report.executive_summary}\n")
    print("Динамика метрик:")
    print(f"{coach_report.aggregated_metrics_summary}\n")
    print("Хронические паттерны ошибок:")
    for p in coach_report.systemic_patterns:
        print(f"  • [{p.severity.upper()}] {p.title} ({p.frequency})")
        print(f"    {p.description}")
    print(f"\nВердикт по цейтноту: {coach_report.time_trouble_verdict}")
    print("\nПлан следующих уроков:")
    for lesson in coach_report.next_lessons_plan:
        print(f"  - {lesson}")
    print("\nРекомендованное ДЗ:")
    for hw in coach_report.homework_assignment:
        print(f"  • Тема: {hw.topic} ({hw.recommended_puzzles_count} задач)")
        print(f"    Паттерн: {hw.target_pattern}")
        print(f"    Фокус: {hw.focus_description}")

    print("\n" + "=" * 70)
    print("👨‍👩‍👦 2. ОТЧЕТ ДЛЯ РОДИТЕЛЯ (ParentReport) — ЭМПАТИЯ, БЕЗ ЖАРГОНА")
    print("=" * 70)
    parent_report = reporter.generate_parent_report(stats)
    print(f"Ребенок: {parent_report.child_name} | Период: {parent_report.period}\n")
    print(parent_report.greeting_and_summary)
    print("\nДостижения и победы:")
    for ach in parent_report.achievements:
        print(f"  ✅ {ach}")
    print("\nНад чем поработаем (зоны роста):")
    for growth in parent_report.areas_for_growth:
        print(f"  🌱 {growth}")
    print("\nСовет для родителей дома:")
    print(f"  💡 {parent_report.home_support_advice}")
    print("=" * 70)

if __name__ == "__main__":
    main()
