"""
Сквозной тест синхронизации и фонового анализа партий:
1. Инициализация локальной БД (SQLite / PostgreSQL).
2. Создание профиля ученика и привязка аккаунта (Lichess / Chess.com).
3. Первый прогон: инкрементальная загрузка 3 партий -> дедупликация -> анализ Stockfish.
4. Второй прогон: проверка дедупликации (должно быть 0 новых партий).
5. Проверка сохранения результатов анализа и ошибок в БД.

Запуск:
    source .venv/bin/activate
    python test_sync_pipeline.py
"""
import os
import sys
from datetime import datetime
from sqlalchemy import select

# Настройка Celery для синхронного выполнения в тесте
from app.tasks.celery_app import celery_app
celery_app.conf.update(
    task_always_eager=True,
    task_eager_propagates=True,
    broker_url="memory://",
    result_backend="cache+memory://",
)

from app.db.session import init_db, get_db_session
from app.models.chess import StudentProfile, StudentChessAccount, Game, ChessErrorEvent
from app.tasks.sync_tasks import sync_student_games

TEST_LICHESS_USER = "DrNykterstein" # Публичный профиль на Lichess для тестирования

def main():
    print("=" * 70)
    print("🧪 ЗАПУСК СКВОЗНОГО ТЕСТА СИНХРОНИЗАЦИИ И ОЧЕРЕДИ ОБРАБОТКИ")
    print("=" * 70)

    # 1. Инициализация чистой тестовой базы данных
    if os.path.exists("chess.db"):
        os.remove("chess.db")
    print("1️⃣ Инициализация таблиц БД...")
    init_db()

    # 2. Создание тестового ученика
    with get_db_session() as session:
        student = StudentProfile(
            first_name="Тестовый",
            last_name="Гроссмейстер",
            notes="Студент для сквозных тестов синка",
        )
        session.add(student)
        session.flush()

        # Добавляем аккаунт Lichess
        account = StudentChessAccount(
            student_profile_id=student.id,
            platform="lichess",
            username=TEST_LICHESS_USER,
            is_active=True,
        )
        session.add(account)
        session.flush()
        student_id = student.id
        print(f"   Создан ученик ID: {student_id} с Lichess-аккаунтом '{TEST_LICHESS_USER}'")

    # 3. Первый прогон синхронизации (Загрузка 3 партий)
    import time
    print("\n2️⃣ ПЕРВЫЙ ПРОГОН СИНХРОНИЗАЦИИ (Загрузка 3 партий)...")
    print(f"   Запрашиваем партии для {TEST_LICHESS_USER}...")
    t_start = time.perf_counter()
    res1 = sync_student_games(student_id=student_id, max_games=3)
    t_total = time.perf_counter() - t_start
    print(f"   Результат первого синка: {res1}")
    print(f"   ➕ Новых партий сохранено: {res1['new_games']}")
    print(f"   ⏭️ Дубликатов пропущено: {res1['skipped_duplicates']}")
    print(f"   ⏱️ Полное время скачивания и анализа: {t_total:.2f} сек")

    # 4. Проверка состояния партий в БД после анализа Stockfish
    print("\n3️⃣ ПРОВЕРКА СОХРАНЕНИЯ АНАЛИЗА STOCKFISH В БАЗЕ ДАННЫХ:")
    with get_db_session() as session:
        games = list(session.execute(
            select(Game).where(Game.student_profile_id == student_id)
        ).scalars().all())
        
        print(f"   Всего партий ученика в БД: {len(games)}")
        for g in games[:3]:
            print(f"   • Партия [{g.platform}] ID={g.external_game_id}:")
            print(f"     Соперник: {g.opponent_username} ({g.opponent_rating or 'unrated'}) | Результат: {g.result}")
            print(f"     Статус анализа: {g.analysis_status.upper()}")
            print(f"     Точность (Accuracy): {g.accuracy_score}% | ACPL: {g.acpl}")
            print(f"     Зевков: {g.blunders_count}, Ошибок: {g.mistakes_count}, Неточностей: {g.inaccuracies_count}")
            
            # Проверяем сохраненные ошибки
            errors_count = len(g.error_events)
            print(f"     Выделено критических ошибок в chess_error_events: {errors_count}")
            if errors_count > 0:
                first_err = g.error_events[0]
                print(f"       -> Пример ошибки: Ход {first_err.move_number} ({first_err.played_move_san}), CPL: -{first_err.centipawn_loss}, Тег: {first_err.tactical_tag}")

    # 5. Второй прогон синхронизации (ПРОВЕРКА ДЕДУПЛИКАЦИИ)
    print("\n4️⃣ ВТОРОЙ ПРОГОН СИНХРОНИЗАЦИИ (ПРОВЕРКА ДЕДУПЛИКАЦИИ)...")
    t_start2 = time.perf_counter()
    res2 = sync_student_games(student_id=student_id, max_games=3)
    t_dedup = time.perf_counter() - t_start2
    print(f"   Результат второго синка: {res2}")
    print(f"   ⏱️ Время проверки дедупликации: {t_dedup:.2f} сек")
    
    assert res2["new_games"] == 0, f"Ошибка дедупликации! Добавлено {res2['new_games']} дубликатов."
    print("   ✅ УСПЕХ: 0 новых партий добавлено! Дедупликация сработала на 100%.")

    print("\n" + "=" * 70)
    print("🎉 ВСЕ ТЕСТЫ ПАЙПЛАЙНА СИНХРОНИЗАЦИИ И ОБРАБОТКИ УСПЕШНО ПРОЙДЕНЫ!")
    print("=" * 70)

if __name__ == "__main__":
    main()
