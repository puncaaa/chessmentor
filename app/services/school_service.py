import logging
import urllib.parse
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import select, func, and_, desc

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
from app.schemas.school import (
    SchoolCreate,
    SchoolUpdate,
    TeacherCreate,
    TeacherUpdate,
    GroupCreate,
    GroupUpdate,
    GroupWithStats,
    StudentCreate,
    StudentUpdate,
    StudentCockpitCard,
)

logger = logging.getLogger(__name__)


class SchoolService:
    """
    CRUD и бизнес-логика управления шахматной школой (мультитенантность B2B):
    - Управление школами, тренерами, группами и учениками;
    - Агрегированные метрики для рабочего кабинета тренера (Cockpit);
    - Групповая синхронизация партий и рассылка отчетов родителям.
    """

    # =========================================================================
    # 1. УПРАВЛЕНИЕ ШКОЛАМИ (SCHOOL / TENANT)
    # =========================================================================

    @staticmethod
    def get_or_create_default_school(
        session: Session,
        name: str = "Шахматная Академия 'Гамбит'",
        slug: str = "gambit-academy",
        subscription_tier: str = "pro",
        max_students: int = 100,
        logo_url: Optional[str] = None,
        contact_email: Optional[str] = "admin@gambit-chess.ru",
        contact_phone: Optional[str] = "+7 (999) 000-11-22",
    ) -> School:
        """
        Возвращает существующую школу по слагу или создает новую демо-школу.
        """
        stmt = select(School).where(School.slug == slug)
        school = session.execute(stmt).scalar_one_or_none()
        if school:
            return school

        school = School(
            name=name,
            slug=slug,
            subscription_tier=subscription_tier,
            max_students=max_students,
            logo_url=logo_url,
            contact_email=contact_email,
            contact_phone=contact_phone,
            is_active=True,
        )
        session.add(school)
        session.flush()
        logger.info(f"Создана школа: {school.name} (id={school.id}, slug={school.slug})")
        return school

    @staticmethod
    def create_school(session: Session, school_in: SchoolCreate) -> School:
        school = School(
            name=school_in.name,
            slug=school_in.slug,
            subscription_tier=school_in.subscription_tier,
            max_students=school_in.max_students,
            logo_url=school_in.logo_url,
            contact_email=school_in.contact_email,
            contact_phone=school_in.contact_phone,
            is_active=True,
        )
        session.add(school)
        session.flush()
        return school

    @staticmethod
    def get_school(session: Session, school_id: str) -> Optional[School]:
        return session.get(School, school_id)

    @staticmethod
    def get_school_by_slug(session: Session, slug: str) -> Optional[School]:
        stmt = select(School).where(School.slug == slug)
        return session.execute(stmt).scalar_one_or_none()

    @staticmethod
    def list_schools(session: Session) -> List[School]:
        stmt = select(School).where(School.is_active == True).order_by(School.name)
        return list(session.execute(stmt).scalars().all())

    # =========================================================================
    # 2. УПРАВЛЕНИЕ ТРЕНЕРАМИ (TEACHER / COACH)
    # =========================================================================

    @staticmethod
    def create_teacher(session: Session, teacher_in: TeacherCreate) -> Teacher:
        teacher = Teacher(
            school_id=teacher_in.school_id,
            first_name=teacher_in.first_name,
            last_name=teacher_in.last_name,
            email=teacher_in.email,
            phone=teacher_in.phone,
            fide_title=teacher_in.fide_title,
            avatar_url=teacher_in.avatar_url,
            bio=teacher_in.bio,
            is_active=True,
        )
        session.add(teacher)
        session.flush()
        return teacher

    @staticmethod
    def get_teacher(session: Session, teacher_id: str) -> Optional[Teacher]:
        return session.get(Teacher, teacher_id)

    @staticmethod
    def list_teachers(session: Session, school_id: str) -> List[Teacher]:
        stmt = select(Teacher).where(
            and_(Teacher.school_id == school_id, Teacher.is_active == True)
        ).order_by(Teacher.last_name, Teacher.first_name)
        return list(session.execute(stmt).scalars().all())

    @staticmethod
    def update_teacher(session: Session, teacher_id: str, teacher_in: TeacherUpdate) -> Optional[Teacher]:
        teacher = session.get(Teacher, teacher_id)
        if not teacher:
            return None
        for field, value in teacher_in.dict(exclude_unset=True).items():
            setattr(teacher, field, value)
        teacher.updated_at = datetime.utcnow()
        session.flush()
        return teacher

    @staticmethod
    def delete_teacher(session: Session, teacher_id: str) -> bool:
        teacher = session.get(Teacher, teacher_id)
        if not teacher:
            return False
        # Снимаем тренера с прикрепленных групп
        groups = session.execute(select(Group).where(Group.teacher_id == teacher_id)).scalars().all()
        for g in groups:
            g.teacher_id = None
        session.delete(teacher)
        session.flush()
        return True

    # =========================================================================
    # 3. УПРАВЛЕНИЕ ГРУППАМИ (STUDENT GROUPS)
    # =========================================================================

    @staticmethod
    def create_group(session: Session, group_in: GroupCreate) -> Group:
        group = Group(
            school_id=group_in.school_id,
            teacher_id=group_in.teacher_id,
            name=group_in.name,
            level=group_in.level,
            schedule=group_in.schedule,
            notes=group_in.notes,
            is_active=True,
        )
        session.add(group)
        session.flush()
        return group

    @staticmethod
    def get_group(session: Session, group_id: str) -> Optional[Group]:
        return session.get(Group, group_id)

    @staticmethod
    def list_groups(
        session: Session, school_id: str, teacher_id: Optional[str] = None
    ) -> List[Group]:
        conditions = [Group.school_id == school_id, Group.is_active == True]
        if teacher_id:
            conditions.append(Group.teacher_id == teacher_id)
        stmt = select(Group).where(and_(*conditions)).order_by(Group.name)
        return list(session.execute(stmt).scalars().all())

    @staticmethod
    def update_group(session: Session, group_id: str, group_in: GroupUpdate) -> Optional[Group]:
        group = session.get(Group, group_id)
        if not group:
            return None
        for field, value in group_in.dict(exclude_unset=True).items():
            setattr(group, field, value)
        group.updated_at = datetime.utcnow()
        session.flush()
        return group

    @staticmethod
    def delete_group(session: Session, group_id: str) -> bool:
        group = session.get(Group, group_id)
        if not group:
            return False
        # Открепляем учеников от группы
        students = session.execute(
            select(StudentProfile).where(StudentProfile.group_id == group_id)
        ).scalars().all()
        for s in students:
            s.group_id = None
        group.is_active = False
        group.updated_at = datetime.utcnow()
        session.flush()
        return True

    @staticmethod
    def get_group_with_stats(session: Session, group_id: str) -> Optional[GroupWithStats]:
        """
        Возвращает группу со сводной статистикой для тренера (количество учеников,
        средний рейтинг, сыгранные партии за неделю, средняя точность CAPS).
        """
        group = session.get(Group, group_id)
        if not group:
            return None

        teacher_name = None
        if group.teacher_id:
            t = session.get(Teacher, group.teacher_id)
            if t:
                teacher_name = t.full_name

        # Список учеников группы
        students_stmt = select(StudentProfile).where(
            and_(StudentProfile.group_id == group_id, StudentProfile.is_active == True)
        )
        students = list(session.execute(students_stmt).scalars().all())
        students_count = len(students)
        avg_rating = int(sum(s.current_rating or 1200 for s in students) / students_count) if students_count > 0 else 1200

        # Партии за последние 7 дней по всей группе
        seven_days_ago = datetime.utcnow() - timedelta(days=7)
        student_ids = [s.id for s in students]

        games_played_this_week = 0
        avg_caps = 0.0

        if student_ids:
            games_stmt = select(Game).where(
                and_(Game.student_profile_id.in_(student_ids), Game.played_at >= seven_days_ago)
            )
            recent_games = list(session.execute(games_stmt).scalars().all())
            games_played_this_week = len(recent_games)

            analyzed_caps = [float(g.accuracy_score) for g in recent_games if g.accuracy_score is not None]
            if analyzed_caps:
                avg_caps = round(sum(analyzed_caps) / len(analyzed_caps), 1)

        return GroupWithStats(
            id=group.id,
            school_id=group.school_id,
            teacher_id=group.teacher_id,
            name=group.name,
            level=group.level,
            schedule=group.schedule,
            notes=group.notes,
            is_active=group.is_active,
            created_at=group.created_at,
            teacher_name=teacher_name,
            students_count=students_count,
            avg_rating=avg_rating,
            games_played_this_week=games_played_this_week,
            avg_caps_accuracy=avg_caps,
            homework_completion_rate=85.0 if students_count > 0 else 0.0,
        )

    # =========================================================================
    # 4. УПРАВЛЕНИЕ УЧЕНИКАМИ (STUDENT MANAGEMENT)
    # =========================================================================

    @staticmethod
    def create_student(
        session: Session,
        student_in: StudentCreate,
    ) -> StudentProfile:
        """
        Создание профиля ученика и привязка шахматных аккаунтов (Lichess/Chess.com).
        """
        student = StudentProfile(
            school_id=student_in.school_id,
            group_id=student_in.group_id,
            first_name=student_in.first_name.strip(),
            last_name=student_in.last_name.strip(),
            birth_date=student_in.birth_date,
            current_rating=student_in.current_rating or 1200,
            parent_name=student_in.parent_name.strip() if student_in.parent_name else None,
            parent_phone=student_in.parent_phone.strip() if student_in.parent_phone else None,
            parent_telegram=student_in.parent_telegram.strip() if student_in.parent_telegram else None,
            notes=student_in.notes,
            is_active=True,
        )
        session.add(student)
        session.flush()

        # Привязка Lichess
        if student_in.lichess_username and student_in.lichess_username.strip():
            acc_lic = StudentChessAccount(
                student_profile_id=student.id,
                platform="lichess",
                username=student_in.lichess_username.strip(),
                is_active=True,
            )
            session.add(acc_lic)

        # Привязка Chess.com
        if student_in.chesscom_username and student_in.chesscom_username.strip():
            acc_com = StudentChessAccount(
                student_profile_id=student.id,
                platform="chesscom",
                username=student_in.chesscom_username.strip(),
                is_active=True,
            )
            session.add(acc_com)

        session.flush()
        logger.info(f"Создан ученик: {student.full_name} (id={student.id}, group_id={student.group_id})")
        return student

    @staticmethod
    def get_student(session: Session, student_id: str) -> Optional[StudentProfile]:
        return session.get(StudentProfile, student_id)

    @staticmethod
    def list_students(
        session: Session,
        school_id: Optional[str] = None,
        group_id: Optional[str] = None,
        teacher_id: Optional[str] = None,
    ) -> List[StudentProfile]:
        conditions = [StudentProfile.is_active == True]
        if school_id:
            conditions.append(StudentProfile.school_id == school_id)
        if group_id:
            conditions.append(StudentProfile.group_id == group_id)
        elif teacher_id:
            # Все группы данного тренера
            groups_subq = select(Group.id).where(Group.teacher_id == teacher_id)
            conditions.append(StudentProfile.group_id.in_(groups_subq))

        stmt = select(StudentProfile).where(and_(*conditions)).order_by(
            StudentProfile.last_name, StudentProfile.first_name
        )
        return list(session.execute(stmt).scalars().all())

    @staticmethod
    def update_student(
        session: Session, student_id: str, student_in: StudentUpdate
    ) -> Optional[StudentProfile]:
        student = session.get(StudentProfile, student_id)
        if not student:
            return None
        for field, value in student_in.dict(exclude_unset=True).items():
            setattr(student, field, value)
        student.updated_at = datetime.utcnow()
        session.flush()
        return student

    @staticmethod
    def delete_student(session: Session, student_id: str) -> bool:
        student = session.get(StudentProfile, student_id)
        if not student:
            return False
        session.delete(student)
        session.flush()
        return True

    @staticmethod
    def add_or_update_chess_account(
        session: Session, student_id: str, platform: str, username: str
    ) -> StudentChessAccount:
        stmt = select(StudentChessAccount).where(
            and_(
                StudentChessAccount.student_profile_id == student_id,
                StudentChessAccount.platform == platform,
            )
        )
        acc = session.execute(stmt).scalar_one_or_none()
        if acc:
            acc.username = username.strip()
            acc.is_active = True
        else:
            acc = StudentChessAccount(
                student_profile_id=student_id,
                platform=platform,
                username=username.strip(),
                is_active=True,
            )
            session.add(acc)
        session.flush()
        return acc

    @staticmethod
    def get_student_cockpit_card(session: Session, student_id: str) -> Optional[StudentCockpitCard]:
        """
        Генерирует полную карточку ученика для тренерского пульта (Cockpit):
        метрики за неделю, CAPS-точность, статус домашнего задания, ссылку в WhatsApp.
        """
        student = session.get(StudentProfile, student_id)
        if not student:
            return None

        group_name = None
        if student.group_id:
            grp = session.get(Group, student.group_id)
            if grp:
                group_name = grp.name

        # Аккаунты
        lichess_user = None
        chesscom_user = None
        last_synced = None
        for acc in student.chess_accounts:
            if acc.platform == "lichess":
                lichess_user = acc.username
            elif acc.platform == "chesscom":
                chesscom_user = acc.username
            if acc.last_synced_at and (not last_synced or acc.last_synced_at > last_synced):
                last_synced = acc.last_synced_at

        # Статистика партий
        seven_days_ago = datetime.utcnow() - timedelta(days=7)
        stmt_all_games = select(Game).where(Game.student_profile_id == student_id)
        all_games = list(session.execute(stmt_all_games).scalars().all())

        games_total = len(all_games)
        recent_games = [g for g in all_games if g.played_at >= seven_days_ago]
        games_this_week = len(recent_games)

        # Метрики качества
        analyzed_caps = [float(g.accuracy_score) for g in all_games if g.accuracy_score is not None]
        avg_caps = round(sum(analyzed_caps) / len(analyzed_caps), 1) if analyzed_caps else 0.0

        acpl_vals = [g.acpl for g in all_games if g.acpl is not None]
        avg_acpl = int(sum(acpl_vals) / len(acpl_vals)) if acpl_vals else 0

        # Зевки за последнюю неделю
        blunders_recent = sum(g.blunders_count or 0 for g in recent_games)

        # Топ тактическая слабость
        err_stmt = (
            select(ChessErrorEvent.tactical_tag, func.count(ChessErrorEvent.id))
            .where(
                and_(
                    ChessErrorEvent.student_profile_id == student_id,
                    ChessErrorEvent.tactical_tag != None,
                )
            )
            .group_by(ChessErrorEvent.tactical_tag)
            .order_by(desc(func.count(ChessErrorEvent.id)))
            .limit(1)
        )
        top_weakness = session.execute(err_stmt).first()
        top_weakness_tag = top_weakness[0] if top_weakness else None

        # Статус домашнего задания
        hw_status = "Выполнено" if games_this_week >= 5 else ("Выдано" if games_this_week > 0 else "Не задано")

        # Генерация WhatsApp-ссылки для родителя
        whatsapp_link = None
        if student.parent_phone:
            clean_phone = "".join(ch for ch in student.parent_phone if ch.isdigit())
            if clean_phone:
                if clean_phone.startswith("8") and len(clean_phone) == 11:
                    clean_phone = "7" + clean_phone[1:]
                greeting = f"Здравствуйте, {student.parent_name or 'уважаемый родитель'}! Отправляю недельный отчет об успехах {student.first_name} в шахматах. Сыграно партий за неделю: {games_this_week}, точность ходов: {avg_caps}%."
                encoded_msg = urllib.parse.quote(greeting)
                whatsapp_link = f"https://wa.me/{clean_phone}?text={encoded_msg}"

        return StudentCockpitCard(
            id=student.id,
            full_name=student.full_name,
            group_id=student.group_id,
            group_name=group_name,
            rating=student.current_rating or 1200,
            lichess_username=lichess_user,
            chesscom_username=chesscom_user,
            parent_name=student.parent_name,
            parent_phone=student.parent_phone,
            parent_telegram=student.parent_telegram,
            games_total=games_total,
            games_this_week=games_this_week,
            avg_caps_accuracy=avg_caps,
            avg_acpl=avg_acpl,
            blunders_count_recent=blunders_recent,
            top_weakness_tag=top_weakness_tag,
            opening_holes_count=0,
            homework_status=hw_status,
            last_synced_at=last_synced,
            whatsapp_link=whatsapp_link,
        )

    # =========================================================================
    # 5. ПАКЕТНАЯ ОБРАБОТКА (BATCH SYNC & REPORTS)
    # =========================================================================

    @staticmethod
    def sync_group_games(
        session: Session, group_id: str, max_games_per_student: int = 5
    ) -> Dict[str, Any]:
        """
        Синхронизирует партии для всех учеников группы в один клик.
        """
        from app.services.chess_sync import ChessSyncService
        from app.services.game_service import GameService

        students = session.execute(
            select(StudentProfile).where(
                and_(StudentProfile.group_id == group_id, StudentProfile.is_active == True)
            )
        ).scalars().all()

        total_synced = 0
        students_processed = 0
        details = []

        for student in students:
            synced_for_student = 0
            for acc in student.chess_accounts:
                if not acc.is_active or not acc.username:
                    continue
                try:
                    raw_games = ChessSyncService.fetch_recent_games(
                        platform=acc.platform,
                        username=acc.username,
                        max_games=max_games_per_student,
                    )
                    for rg in raw_games:
                        game = GameService.create_pending_game(
                            session=session,
                            student_profile_id=student.id,
                            chess_account_id=acc.id,
                            platform=rg.platform,
                            external_game_id=rg.external_id,
                            url=rg.url,
                            played_at=rg.played_at,
                            student_color=rg.student_color,
                            student_rating=rg.student_rating,
                            opponent_username=rg.opponent_username,
                            opponent_rating=rg.opponent_rating,
                            result=rg.result,
                            time_control=rg.time_control,
                            speed_category=rg.speed_category,
                            pgn=rg.pgn,
                            eco_code=rg.eco,
                            opening_name=rg.opening_name,
                        )
                        if game:
                            synced_for_student += 1
                            total_synced += 1

                    acc.last_synced_at = datetime.utcnow()
                except Exception as e:
                    logger.warning(f"Ошибка синхронизации для {student.full_name} ({acc.platform}:{acc.username}): {e}")

            students_processed += 1
            details.append({"student_name": student.full_name, "synced_games": synced_for_student})

        session.commit()
        return {
            "group_id": group_id,
            "students_processed": students_processed,
            "total_new_games": total_synced,
            "details": details,
        }

    # =========================================================================
    # 6. ХРАНЕНИЕ ОТЧЕТОВ (REPORTS PERSISTENCE)
    # =========================================================================

    @staticmethod
    def save_report(
        session: Session,
        student_profile_id: str,
        title: str,
        report_type: str,
        games_analyzed_count: int,
        school_id: Optional[str] = None,
        teacher_id: Optional[str] = None,
        period_start: Optional[datetime] = None,
        period_end: Optional[datetime] = None,
        executive_summary: Optional[str] = None,
        content_json: Optional[Dict[str, Any]] = None,
        pdf_path: Optional[str] = None,
    ) -> StudentReport:
        report = StudentReport(
            student_profile_id=student_profile_id,
            school_id=school_id,
            teacher_id=teacher_id,
            report_type=report_type,
            title=title,
            period_start=period_start or datetime.utcnow() - timedelta(days=7),
            period_end=period_end or datetime.utcnow(),
            games_analyzed_count=games_analyzed_count,
            executive_summary=executive_summary,
            content_json=content_json,
            pdf_path=pdf_path,
            is_sent_to_parent=False,
        )
        session.add(report)
        session.flush()
        return report

    @staticmethod
    def list_student_reports(
        session: Session, student_profile_id: str, report_type: Optional[str] = None
    ) -> List[StudentReport]:
        conditions = [StudentReport.student_profile_id == student_profile_id]
        if report_type:
            conditions.append(StudentReport.report_type == report_type)
        stmt = select(StudentReport).where(and_(*conditions)).order_by(desc(StudentReport.created_at))
        return list(session.execute(stmt).scalars().all())
