"""
Сид-скрипт демонстрационной шахматной школы:
Шахматная Академия "Гамбит"
2 тренера (GM Александр Морозевич, FM Елена Васильева)
3 группы (Начинающие, Разрядники, Юношеская сборная)
11 учеников с реальными партиями, ошибками Stockfish и контактами родителей.

Запуск:
    python scripts/seed_school.py
"""

import sys
import os
from datetime import datetime, timedelta
import random

# Добавляем корень проекта в sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.db.session import init_db, get_db_session
from app.models.chess import (
    School,
    Teacher,
    Group,
    StudentProfile,
    StudentChessAccount,
    Game,
    ChessErrorEvent,
    StudentReport,
)

# Шаблоны реалистичных PGN-партий
PGN_SAMPLES = [
    """[Event "Rated Rapid tournament"]
[Site "Lichess.org"]
[Date "{date}"]
[White "{white}"]
[Black "{black}"]
[Result "1-0"]
[ECO "C50"]
[Opening "Italian Game: Giuoco Piano"]
[TimeControl "600+5"]

1. e4 e5 2. Nf3 Nc6 3. Bc4 Bc5 4. O-O Nf6 5. d3 d6 6. c3 a6 7. Bb3 Ba7 8. Nbd2 O-O 9. Re1 Ne7 10. Nf1 Ng6 11. Ng3 c6 12. h3 d5 13. exd5 Nxd5 14. Nxe5 Nxe5 15. Rxe5 Bxf2+ 16. Kxf2 Qf6+ 17. Rf5 Bxf5 18. Qf3 Be6 19. Qxf6 Nxf6 20. Bxe6 fxe6 21. Ke2 Rad8 22. Bd2 Rd7 23. d4 e5 24. dxe5 Re8 25. Bf4 Nd5 1-0""",
    """[Event "Rated Blitz game"]
[Site "Chess.com"]
[Date "{date}"]
[White "{white}"]
[Black "{black}"]
[Result "0-1"]
[ECO "B01"]
[Opening "Scandinavian Defense: Mieses-Kotroc"]
[TimeControl "300+2"]

1. e4 d5 2. exd5 Qxd5 3. Nc3 Qa5 4. d4 Nf6 5. Nf3 c6 6. Bc4 Bf5 7. Bd2 e6 8. Nd5 Qd8 9. Nxf6+ Qxf6 10. Qe2 Bg4 11. O-O-O Bxf3 12. gxf3 Nd7 13. d5 cxd5 14. Bxd5 O-O-O 15. Be4 Nc5 16. Be3 Be7 17. Qc4 Qe5 18. Rhe1 Kb8 19. Kb1 Nxe4 20. fxe4 Rxd1+ 21. Rxd1 Rd8 22. Rxd8+ Bxd8 23. f4 Qd6 24. a4 Bb6 25. Bc1 Qd4 0-1""",
    """[Event "Rated Classical game"]
[Site "Lichess.org"]
[Date "{date}"]
[White "{white}"]
[Black "{black}"]
[Result "1/2-1/2"]
[ECO "D02"]
[Opening "Queen's Pawn Game: London System"]
[TimeControl "900+10"]

1. d4 d5 2. Bf4 Nf6 3. e3 c5 4. c3 Nc6 5. Nd2 Bf5 6. Ngf3 e6 7. Nh4 Bg6 8. Nxg6 hxg6 9. Bd3 Bd6 10. Bxd6 Qxd6 11. Nf3 O-O 12. O-O e5 13. dxe5 Nxe5 14. Nxe5 Qxe5 15. Qf3 Rad8 16. Rad1 Rd6 17. Bc2 Rfd8 18. Rd2 b6 19. Rfd1 a5 20. a4 Qe6 21. h3 Qe5 22. Bb3 Kf8 23. Bc2 Kg8 24. Bb3 Kf8 25. Bc2 1/2-1/2""",
    """[Event "Rated Rapid game"]
[Site "Lichess.org"]
[Date "{date}"]
[White "{white}"]
[Black "{black}"]
[Result "1-0"]
[ECO "C00"]
[Opening "French Defense: Normal Variation"]
[TimeControl "600+0"]

1. e4 e6 2. d4 d5 3. Nc3 Bb4 4. e5 c5 5. a3 Bxc3+ 6. bxc3 Ne7 7. Qg4 Qc7 8. Qxg7 Rg8 9. Qxh7 cxd4 10. Ne2 Nbc6 11. f4 Bd7 12. Qd3 dxc3 13. Qxc3 O-O-O 14. Rb1 Nf5 15. Rg1 d4 16. Qd3 Na5 17. g4 Nh4 18. Rg3 Ba4 19. Nxd4 Rxd4 20. Qxd4 Qxc2 21. Rc3+ Kb8 22. Be2 Qxb1 23. Qxa4 1-0""",
]

def seed_database():
    print("=" * 70)
    print("♟️ НАЧАЛО СИДИРОВАНИЯ ДЕМО-ШКОЛЫ: «Шахматная Академия 'Гамбит'»")
    print("=" * 70)

    init_db()

    with get_db_session() as session:
        # 1. ШКОЛА
        slug = "gambit-academy"
        school = session.query(School).filter_by(slug=slug).first()
        if not school:
            school = School(
                name='Шахматная Академия "Гамбит"',
                slug=slug,
                subscription_tier="pro",
                max_students=50,
                logo_url="https://img.icons8.com/color/96/chess-knight.png",
                contact_email="admin@gambit-academy.ru",
                contact_phone="+7 (999) 777-11-22",
                is_active=True,
            )
            session.add(school)
            session.flush()
            print(f"✅ Создана школа: {school.name} (id={school.id})")
        else:
            print(f"ℹ️ Школа уже существует: {school.name} (id={school.id})")

        # 2. ТРЕНЕРЫ
        # Тренер 1: Александр Морозевич (GM)
        coach_gm = session.query(Teacher).filter_by(school_id=school.id, last_name="Морозевич").first()
        if not coach_gm:
            coach_gm = Teacher(
                school_id=school.id,
                first_name="Александр",
                last_name="Морозевич",
                fide_title="GM",
                email="morozevich@gambit-academy.ru",
                phone="+7 (999) 111-22-33",
                avatar_url="https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=150",
                bio="Международный гроссмейстер, старший тренер академии, автор тактических методик.",
                is_active=True,
            )
            session.add(coach_gm)

        # Тренер 2: Елена Васильева (FM)
        coach_fm = session.query(Teacher).filter_by(school_id=school.id, last_name="Васильева").first()
        if not coach_fm:
            coach_fm = Teacher(
                school_id=school.id,
                first_name="Елена",
                last_name="Васильева",
                fide_title="FM",
                email="vasilieva@gambit-academy.ru",
                phone="+7 (999) 222-33-44",
                avatar_url="https://images.unsplash.com/photo-1580489944761-15a19d654956?w=150",
                bio="Мастер ФИДЕ, педагог высшей категории, куратор детских и начальных групп.",
                is_active=True,
            )
            session.add(coach_fm)

        session.flush()
        print(f"✅ Тренеры: {coach_gm.full_name} ({coach_gm.fide_title}), {coach_fm.full_name} ({coach_fm.fide_title})")

        # 3. ГРУППЫ
        groups_data = [
            {
                "name": "Младшая группа 2017–2018 (Начинающие)",
                "level": "3-й юношеский разряд (900–1100)",
                "schedule": "Пн, Ср 15:30 - 17:00",
                "teacher_id": coach_fm.id,
                "notes": "Базовые тактические мотивы, защита фигур от простых зевков в 1 ход.",
            },
            {
                "name": "Разрядники 1400–1600 (Тактика)",
                "level": "2-й / 1-й юношеский разряд (1400–1600)",
                "schedule": "Вт, Чт 17:00 - 18:30",
                "teacher_id": coach_gm.id,
                "notes": "Позиционная игра, расчет комбинаций на 3-4 хода, миттельшпиль.",
            },
            {
                "name": "Юношеская сборная (КМС / 1800+)",
                "level": "1-й взрослый / КМС (1800+)",
                "schedule": "Ср, Сб 18:30 - 20:30",
                "teacher_id": coach_gm.id,
                "notes": "Глубокая дебютная подготовка, игра в цейтнотах, ладейный эндшпиль.",
            },
        ]

        groups_map = {}
        for gdata in groups_data:
            grp = session.query(Group).filter_by(school_id=school.id, name=gdata["name"]).first()
            if not grp:
                grp = Group(
                    school_id=school.id,
                    teacher_id=gdata["teacher_id"],
                    name=gdata["name"],
                    level=gdata["level"],
                    schedule=gdata["schedule"],
                    notes=gdata["notes"],
                    is_active=True,
                )
                session.add(grp)
                session.flush()
            else:
                grp.teacher_id = gdata["teacher_id"]
                grp.is_active = True
                session.flush()
            groups_map[gdata["name"]] = grp

        print(f"✅ Группы сформированы: {len(groups_map)} учебные группы")

        # 4. УЧЕНИКИ
        students_roster = [
            # Группа 1: Младшая (Начинающие)
            {
                "group_name": "Младшая группа 2017–2018 (Начинающие)",
                "first_name": "Михаил",
                "last_name": "Смирнов",
                "rating": 940,
                "parent_name": "Анна Смирнова",
                "parent_phone": "+7 (916) 123-45-67",
                "parent_tg": "@anna_smirnova",
                "platform": "lichess",
                "username": "MishaChess2018",
                "chronic_weakness": "hanging_piece",
                "weakness_title": "Зевок фигур под бой",
                "avg_caps": 73.5,
                "avg_acpl": 68,
            },
            {
                "group_name": "Младшая группа 2017–2018 (Начинающие)",
                "first_name": "София",
                "last_name": "Кузнецова",
                "rating": 1050,
                "parent_name": "Дмитрий Кузнецов",
                "parent_phone": "+7 (916) 234-56-78",
                "parent_tg": "@dmitry_kuz",
                "platform": "lichess",
                "username": "SofiaKuz2017",
                "chronic_weakness": "hanging_piece",
                "weakness_title": "Оставление ладьи без защиты",
                "avg_caps": 77.2,
                "avg_acpl": 54,
            },
            {
                "group_name": "Младшая группа 2017–2018 (Начинающие)",
                "first_name": "Артем",
                "last_name": "Попов",
                "rating": 990,
                "parent_name": "Ирина Попова",
                "parent_phone": "+7 (916) 345-67-89",
                "parent_tg": "@irina_popova",
                "platform": "chesscom",
                "username": "ArtemPopovChess",
                "chronic_weakness": "hanging_piece",
                "weakness_title": "Потеря коня в центре",
                "avg_caps": 71.8,
                "avg_acpl": 72,
            },
            {
                "group_name": "Младшая группа 2017–2018 (Начинающие)",
                "first_name": "Алиса",
                "last_name": "Новикова",
                "rating": 1090,
                "parent_name": "Сергей Новиков",
                "parent_phone": "+7 (916) 456-78-90",
                "parent_tg": "@sergey_novikov",
                "platform": "lichess",
                "username": "AlisaNov_2018",
                "chronic_weakness": "hanging_piece",
                "weakness_title": "Зевок легкой фигуры",
                "avg_caps": 79.1,
                "avg_acpl": 49,
            },

            # Группа 2: Разрядники 1400–1600 (Тактика)
            {
                "group_name": "Разрядники 1400–1600 (Тактика)",
                "first_name": "Даниил",
                "last_name": "Дубов",
                "rating": 1560,
                "parent_name": "Ольга Дубова",
                "parent_phone": "+7 (926) 111-22-33",
                "parent_tg": "@olga_dubova",
                "platform": "lichess",
                "username": "DrNykterstein",
                "chronic_weakness": "tactical_blunder",
                "weakness_title": "Тактический просчет в центре",
                "avg_caps": 89.4,
                "avg_acpl": 28,
            },
            {
                "group_name": "Разрядники 1400–1600 (Тактика)",
                "first_name": "Максим",
                "last_name": "Федоров",
                "rating": 1475,
                "parent_name": "Игорь Федоров",
                "parent_phone": "+7 (926) 222-33-44",
                "parent_tg": "@igor_fedorov",
                "platform": "lichess",
                "username": "MaxFedChess",
                "chronic_weakness": "missed_fork",
                "weakness_title": "Пропуск вилки конем",
                "avg_caps": 83.2,
                "avg_acpl": 39,
            },
            {
                "group_name": "Разрядники 1400–1600 (Тактика)",
                "first_name": "Варвара",
                "last_name": "Морозова",
                "rating": 1520,
                "parent_name": "Екатерина Морозова",
                "parent_phone": "+7 (926) 333-44-55",
                "parent_tg": "@katya_morozova",
                "platform": "chesscom",
                "username": "VaryaChessMaster",
                "chronic_weakness": "missed_pin",
                "weakness_title": "Зевок связки по диагонали",
                "avg_caps": 85.0,
                "avg_acpl": 34,
            },
            {
                "group_name": "Разрядники 1400–1600 (Тактика)",
                "first_name": "Тимофей",
                "last_name": "Волков",
                "rating": 1420,
                "parent_name": "Денис Волков",
                "parent_phone": "+7 (926) 444-55-66",
                "parent_tg": "@denis_volkov",
                "platform": "lichess",
                "username": "TimVolkov_Chess",
                "chronic_weakness": "tactical_blunder",
                "weakness_title": "Недооценка скрытого шаха",
                "avg_caps": 81.7,
                "avg_acpl": 44,
            },

            # Группа 3: Юношеская сборная (КМС / 1800+)
            {
                "group_name": "Юношеская сборная (КМС / 1800+)",
                "first_name": "Глеб",
                "last_name": "Захаров",
                "rating": 1910,
                "parent_name": "Виктор Захаров",
                "parent_phone": "+7 (903) 111-22-33",
                "parent_tg": "@victor_zakharov",
                "platform": "lichess",
                "username": "GlebZ_Master",
                "chronic_weakness": "time_trouble_panic",
                "weakness_title": "Спешка на последних 30 секундах",
                "avg_caps": 93.8,
                "avg_acpl": 18,
            },
            {
                "group_name": "Юношеская сборная (КМС / 1800+)",
                "first_name": "Полина",
                "last_name": "Белова",
                "rating": 1840,
                "parent_name": "Марина Белова",
                "parent_phone": "+7 (903) 222-33-44",
                "parent_tg": "@marina_belova",
                "platform": "lichess",
                "username": "PolinaBelova_WFM",
                "chronic_weakness": "endgame_king_activity",
                "weakness_title": "Пассивный король в эндшпиле",
                "avg_caps": 91.2,
                "avg_acpl": 22,
            },
            {
                "group_name": "Юношеская сборная (КМС / 1800+)",
                "first_name": "Кирилл",
                "last_name": "Медведев",
                "rating": 1965,
                "parent_name": "Андрей Медведев",
                "parent_phone": "+7 (903) 333-44-55",
                "parent_tg": "@andrey_medvedev",
                "platform": "chesscom",
                "username": "KirillMedv_Candidate",
                "chronic_weakness": "time_trouble_panic",
                "weakness_title": "Зевок пешки в цейтноте",
                "avg_caps": 94.5,
                "avg_acpl": 16,
            },
        ]

        total_games_created = 0
        total_errors_created = 0

        for sdata in students_roster:
            grp = groups_map[sdata["group_name"]]
            student = session.query(StudentProfile).filter_by(
                school_id=school.id,
                first_name=sdata["first_name"],
                last_name=sdata["last_name"]
            ).first()

            if not student:
                student = StudentProfile(
                    school_id=school.id,
                    group_id=grp.id,
                    first_name=sdata["first_name"],
                    last_name=sdata["last_name"],
                    current_rating=sdata["rating"],
                    parent_name=sdata["parent_name"],
                    parent_phone=sdata["parent_phone"],
                    parent_telegram=sdata["parent_tg"],
                    notes=f"Слабость: {sdata['weakness_title']}",
                    is_active=True,
                )
                session.add(student)
                session.flush()

            # Привязка игрового аккаунта
            acc = session.query(StudentChessAccount).filter_by(
                student_profile_id=student.id,
                platform=sdata["platform"]
            ).first()
            if not acc:
                acc = StudentChessAccount(
                    student_profile_id=student.id,
                    platform=sdata["platform"],
                    username=sdata["username"],
                    is_active=True,
                    last_synced_at=datetime.utcnow() - timedelta(hours=random.randint(1, 8)),
                )
                session.add(acc)
                session.flush()

            # Создание 3-4 партий за последнюю неделю
            existing_games = session.query(Game).filter_by(student_profile_id=student.id).count()
            if existing_games < 3:
                for idx in range(3):
                    played_date = datetime.utcnow() - timedelta(days=idx * 2 + 1, hours=random.randint(1, 10))
                    pgn_tmpl = PGN_SAMPLES[idx % len(PGN_SAMPLES)]
                    
                    student_color = "white" if idx % 2 == 0 else "black"
                    opp_color = "black" if student_color == "white" else "white"
                    opponent = f"Opponent_{random.randint(100, 999)}"
                    
                    white_player = student.full_name if student_color == "white" else opponent
                    black_player = opponent if student_color == "white" else student.full_name

                    formatted_pgn = pgn_tmpl.format(
                        date=played_date.strftime("%Y.%m.%d"),
                        white=white_player,
                        black=black_player,
                    )

                    caps = round(sdata["avg_caps"] + random.uniform(-3.5, 3.5), 1)
                    caps = max(55.0, min(99.0, caps))
                    acpl = int(sdata["avg_acpl"] + random.randint(-6, 8))
                    blunders = random.randint(1, 3) if caps < 85 else random.randint(0, 1)

                    game = Game(
                        student_profile_id=student.id,
                        chess_account_id=acc.id,
                        platform=acc.platform,
                        external_game_id=f"seed_{student.id[:8]}_{idx}",
                        url=f"https://lichess.org/seed_{student.id[:8]}_{idx}" if acc.platform == "lichess" else f"https://chess.com/game/{student.id[:8]}_{idx}",
                        played_at=played_date,
                        student_color=student_color,
                        student_rating=student.current_rating,
                        opponent_username=opponent,
                        opponent_rating=student.current_rating + random.randint(-50, 60),
                        result="1-0" if idx % 3 != 1 else "0-1",
                        time_control="600+5" if idx % 2 == 0 else "300+2",
                        speed_category="rapid" if idx % 2 == 0 else "blitz",
                        eco_code="C50" if idx % 2 == 0 else "B01",
                        opening_name="Italian Game: Giuoco Piano" if idx % 2 == 0 else "Scandinavian Defense",
                        pgn=formatted_pgn,
                        accuracy_score=caps,
                        acpl=acpl,
                        blunders_count=blunders,
                        mistakes_count=random.randint(1, 3),
                        inaccuracies_count=random.randint(1, 4),
                        analysis_status="completed",
                        analyzed_at=datetime.utcnow(),
                    )
                    session.add(game)
                    session.flush()
                    total_games_created += 1

                    # Добавление ошибки в chess_error_events
                    error_event = ChessErrorEvent(
                        game_id=game.id,
                        student_profile_id=student.id,
                        ply_number=18 + idx * 4,
                        move_number=9 + idx * 2,
                        played_move_san="Nxd5?",
                        played_move_uci="e7d5",
                        best_move_san="O-O",
                        best_move_uci="e8g8",
                        fen_before="r1bqk2r/pppp1ppp/2n5/2b1p3/2B1P3/2NP1N2/PPP2PPP/R1BQK2R b KQkq - 0 5",
                        fen_after="r1bqk2r/pppp1ppp/2n5/3np3/2B1P3/2NP1N2/PPP2PPP/R1BQK2R w KQkq - 0 6",
                        eval_before=15,
                        eval_after=-240,
                        centipawn_loss=255,
                        win_rate_drop=38.5,
                        severity="blunder",
                        tactical_tag=sdata["chronic_weakness"],
                        phase="middlegame" if idx != 2 else "endgame",
                        time_spent_seconds=4.2 if sdata["chronic_weakness"] != "time_trouble_panic" else 1.1,
                        clock_remaining_seconds=12.5 if sdata["chronic_weakness"] == "time_trouble_panic" else 185.0,
                        is_time_trouble=True if sdata["chronic_weakness"] == "time_trouble_panic" else False,
                    )
                    session.add(error_event)
                    total_errors_created += 1

            # Создание предзаполненного отчета
            rep_count = session.query(StudentReport).filter_by(student_profile_id=student.id).count()
            if rep_count == 0:
                report = StudentReport(
                    student_profile_id=student.id,
                    school_id=school.id,
                    teacher_id=grp.teacher_id,
                    report_type="coach_technical",
                    title=f"Аналитический срез: {student.full_name}",
                    period_start=datetime.utcnow() - timedelta(days=7),
                    period_end=datetime.utcnow(),
                    games_analyzed_count=3,
                    executive_summary=f"Ученик {student.full_name} демонстрирует стабильную точность {sdata['avg_caps']}%. Основной фокус работы: устранение слабости '{sdata['weakness_title']}'.",
                    is_sent_to_parent=False,
                )
                session.add(report)

        session.commit()

        print(f"✅ Создано учеников: {len(students_roster)}")
        print(f"✅ Добавлено партий: {total_games_created}")
        print(f"✅ Зафиксировано тактических ошибок: {total_errors_created}")
        print("=" * 70)
        print("🎉 ДЕМО-ШКОЛА УСПЕШНО ЗАГРУЖЕНА И ГОТОВА К ПОКАЗУ!")
        print("=" * 70)

if __name__ == "__main__":
    seed_database()
