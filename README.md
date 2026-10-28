# Chess B2B SaaS Platform

B2B SaaS-платформа для шахматных тренеров и школ: автоматическая синхронизация партий с Lichess/Chess.com, глубокий анализ через Stockfish, выявление хронических паттернов ошибок, генерация адаптивного ДЗ и двухуровневых отчетов (для тренера и родителей).

## Архитектура и структура проекта
```
chess/
├── migrations/
│   └── 001_initial_schema.sql      # DDL-схема PostgreSQL (RBAC, Multi-tenancy, Games, Error Events)
├── app/
│   ├── core/
│   │   └── config.py               # Конфигурация (Pydantic Settings: БД, Redis, движок, LLM)
│   ├── db/
│   │   ├── __init__.py
│   │   └── session.py              # Сессии SQLAlchemy (PostgreSQL / SQLite fallback)
│   ├── models/
│   │   ├── __init__.py
│   │   └── chess.py                # ORM-модели (StudentProfile, ChessAccount, Game, ChessErrorEvent)
│   ├── schemas/
│   │   ├── chess.py                # Pydantic-схемы анализа партий и ходов
│   │   └── reports.py              # Pydantic-схемы отчетов (CoachReport, ParentReport, AggregatedStats)
│   ├── services/
│   │   ├── chess_analyzer.py       # Анализатор Stockfish (Win Rate Drop, CPL, фазы, висячие фигуры)
│   │   ├── chess_sync.py           # Синхронизация партий с Lichess и Chess.com с контролем HTTP 429
│   │   ├── game_service.py         # Сервис дедупликации, сохранения партий и ошибок
│   │   └── llm_reporter.py         # Агрегатор метрик и Structured Outputs генератор отчетов
│   └── tasks/
│       ├── celery_app.py           # Конфигурация очередей ('sync' и 'engine'), лимитов CPU и Beat
│       ├── sync_tasks.py           # Фоновая синхронизация аккаунтов учеников
│       └── analysis_tasks.py       # Фоновый движковый анализ партий
├── demo_analysis.py                # Демо анализа пула партий и генерации отчетов тренеру/родителям
├── test_sync_pipeline.py           # Сквозной тест синхронизации с Lichess, дедупликации и анализа
├── requirements.txt
└── .env.example
```

## Быстрый старт

1. Активировать окружение и зависимости:
```bash
source .venv/bin/activate
pip install -r requirements.txt
```

2. Запустить сквозной тест синхронизации и очередей:
```bash
python test_sync_pipeline.py
```

3. Запустить демо анализа пула партий и генерации отчетов:
```bash
python demo_analysis.py
```

## Запуск веб-дашборда (Streamlit UI)

Запуск интерактивного интерфейса тренера и родителя:
```bash
streamlit run app/ui/dashboard.py
```
Интерфейс доступен по адресу: `http://localhost:8501`.

### Ключевые возможности:
1. **Синхронизация в 1 клик**: загрузка и движковый анализ партий с Lichess и Chess.com.
2. **Интерактивная доска**: разбор критических ошибок со стрелками лучшего хода движка и хода ученика.
3. **Генератор задач (Lichess Puzzle Database)**: автоматический подбор тренировок под персональные слабости (`hanging_piece`, `fork`, `pin`, `mateIn2` и др.).
4. **Экспорт в PDF для родителей**: презентабельный отчет с инфографикой, балансом качества игры и рекомендациями для дома, готовый к отправке в WhatsApp/Telegram.

## Запуск воркеров Celery в Production

1. Легкий сетевой воркер (синхронизация API):
```bash
celery -A app.tasks.celery_app worker -Q sync -c 4 --loglevel=info
```

2. Тяжелый движковый воркер (Stockfish с защитой CPU):
```bash
celery -A app.tasks.celery_app worker -Q engine -c 1 --prefetch-multiplier=1 --loglevel=info
```

3. Планировщик периодических задач (Celery Beat каждые 2 часа):
```bash
celery -A app.tasks.celery_app beat --loglevel=info
```
