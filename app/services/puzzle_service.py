from typing import List, Dict, Any, Optional

LICHESS_THEME_MAPPING = {
    "hanging_piece": {
        "theme": "hangingPiece",
        "title": "Защита и взятие висячих фигур (Hanging Pieces)",
        "description": "Тренировка привычки проверять защищенность каждой фигуры перед ходом.",
        "url": "https://lichess.org/training/hangingPiece"
    },
    "missed_fork": {
        "theme": "fork",
        "title": "Двойной удар и вилки (Forks)",
        "description": "Поиск геометрических слабостей и одновременного нападения на две цели.",
        "url": "https://lichess.org/training/fork"
    },
    "missed_pin": {
        "theme": "pin",
        "title": "Связка и обездвиживание фигур (Pins)",
        "description": "Использование абсолютных и относительных связок фигур соперника.",
        "url": "https://lichess.org/training/pin"
    },
    "missed_skewer": {
        "theme": "skewer",
        "title": "Линейный удар и рентген (Skewers)",
        "description": "Атака более ценной фигуры с последующим взятием фигуры за ней.",
        "url": "https://lichess.org/training/skewer"
    },
    "missed_discovered_atk": {
        "theme": "discoveredAttack",
        "title": "Вскрытое нападение и шах (Discovered Attacks)",
        "description": "Освобождение линии атаки с созданием двойной угрозы.",
        "url": "https://lichess.org/training/discoveredAttack"
    },
    "missed_mate_sequence": {
        "theme": "mateIn2",
        "title": "Форсированная матовая атака (Mate in 1-2)",
        "description": "Реализация решающего перевеса через серию шахов королю.",
        "url": "https://lichess.org/training/mateIn2"
    },
    "back_rank_weakness": {
        "theme": "backRankMate",
        "title": "Слабость 1-й и 8-й горизонтали (Back Rank)",
        "description": "Использование форточек и матование отрезанного короля ладьями/ферзем.",
        "url": "https://lichess.org/training/backRankMate"
    },
    "time_trouble_panic": {
        "theme": "short",
        "title": "Быстрый расчет короткой тактики (1-2 хода)",
        "description": "Развитие интуиции и точности при ограниченном времени на часах.",
        "url": "https://lichess.org/training/short"
    },
    "endgame_king_activity": {
        "theme": "pawnEndgame",
        "title": "Активность короля и пешечный эндшпиль",
        "description": "Централизация короля и создание проходных пешек в эндшпиле.",
        "url": "https://lichess.org/training/pawnEndgame"
    },
    "opening_book_exit": {
        "theme": "opening",
        "title": "Типовые идеи и ловушки в дебюте",
        "description": "Борьба за центр и безопасное развитие легких фигур.",
        "url": "https://lichess.org/training/opening"
    },
    "tactical_blunder": {
        "theme": "crushing",
        "title": "Решающий тактический удар (Crushing Tactics)",
        "description": "Нахождение форсированного опровержения ошибки соперника.",
        "url": "https://lichess.org/training/crushing"
    }
}

class PuzzleGeneratorService:
    """
    Генератор адаптивного набора шахматных задач под персональные уязвимости ученика.
    Формирует прямые ссылки на тренировочную базу Lichess Puzzle Database.
    """

    @staticmethod
    def get_theme_info(tag: str) -> Dict[str, str]:
        """Получить информацию о теме задач по тегу ошибки."""
        return LICHESS_THEME_MAPPING.get(
            tag, 
            {
                "theme": "mix",
                "title": "Комбинированная тактика и расчет",
                "description": "Общая тактическая зоркость и аккуратность расчета.",
                "url": "https://lichess.org/training"
            }
        )

    @classmethod
    def generate_recommendations(
        cls, 
        weaknesses: List[Dict[str, Any]], 
        max_themes: int = 4
    ) -> List[Dict[str, Any]]:
        """
        Генерирует список рекомендаций для ДЗ на основе топ-слабостей ученика.
        """
        recommendations = []
        seen_themes = set()

        for item in weaknesses:
            tag = item.get("tag", "tactical_blunder")
            info = cls.get_theme_info(tag)
            theme_key = info["theme"]

            if theme_key in seen_themes:
                continue
            seen_themes.add(theme_key)

            count = item.get("count", 1)
            pct = item.get("percentage", 0.0)

            recommendations.append({
                "tag": tag,
                "title": info["title"],
                "description": info["description"],
                "url": info["url"],
                "puzzles_recommended": 5 if pct > 20 else 3,
                "error_frequency": f"Встретилось {count} раз ({pct}% всех ошибок)",
            })

            if len(recommendations) >= max_themes:
                break

        # Если ошибок мало, добавляем базовую тактику
        if not recommendations:
            recommendations.append({
                "tag": "hanging_piece",
                "title": LICHESS_THEME_MAPPING["hanging_piece"]["title"],
                "description": LICHESS_THEME_MAPPING["hanging_piece"]["description"],
                "url": LICHESS_THEME_MAPPING["hanging_piece"]["url"],
                "puzzles_recommended": 5,
                "error_frequency": "Базовая профилактика зевков",
            })
            recommendations.append({
                "tag": "missed_fork",
                "title": LICHESS_THEME_MAPPING["missed_fork"]["title"],
                "description": LICHESS_THEME_MAPPING["missed_fork"]["description"],
                "url": LICHESS_THEME_MAPPING["missed_fork"]["url"],
                "puzzles_recommended": 5,
                "error_frequency": "Развитие тактического зрения",
            })

        return recommendations
