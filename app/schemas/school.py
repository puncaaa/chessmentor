from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field


# ============================================================================
# SCHOOL SCHEMAS
# ============================================================================

class SchoolBase(BaseModel):
    name: str = Field(..., description="Название школы (например: Шахматная Академия 'Гамбит')")
    slug: str = Field(..., description="Уникальный слаг школы для URL")
    subscription_tier: str = Field(default="pro", description="Тариф: starter | pro | enterprise")
    max_students: int = Field(default=50, description="Лимит учеников по тарифу")
    logo_url: Optional[str] = Field(default=None, description="Логотип школы для брендинга PDF-отчетов")
    contact_email: Optional[str] = Field(default=None, description="Контактный email")
    contact_phone: Optional[str] = Field(default=None, description="Контактный телефон")


class SchoolCreate(SchoolBase):
    pass


class SchoolUpdate(BaseModel):
    name: Optional[str] = None
    subscription_tier: Optional[str] = None
    max_students: Optional[int] = None
    logo_url: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    is_active: Optional[bool] = None


class SchoolRead(SchoolBase):
    id: str
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ============================================================================
# TEACHER SCHEMAS
# ============================================================================

class TeacherBase(BaseModel):
    first_name: str
    last_name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    fide_title: Optional[str] = Field(default=None, description="Титул: GM, IM, FM, КМС, Тренер высшей категории")
    avatar_url: Optional[str] = None
    bio: Optional[str] = None


class TeacherCreate(TeacherBase):
    school_id: str


class TeacherUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    fide_title: Optional[str] = None
    avatar_url: Optional[str] = None
    bio: Optional[str] = None
    is_active: Optional[bool] = None


class TeacherRead(TeacherBase):
    id: str
    school_id: str
    is_active: bool
    created_at: datetime
    full_name: str

    class Config:
        from_attributes = True


# ============================================================================
# GROUP SCHEMAS
# ============================================================================

class GroupBase(BaseModel):
    name: str = Field(..., description="Название группы (например: Младшая группа 2017 г.р.)")
    level: str = Field(default="Начинающие", description="Уровень: Начинающие, 3-й юношеский, 1-й разряд")
    schedule: Optional[str] = Field(default=None, description="Расписание (например: Вт, Чт 16:00 - 17:30)")
    notes: Optional[str] = None


class GroupCreate(GroupBase):
    school_id: str
    teacher_id: Optional[str] = None


class GroupUpdate(BaseModel):
    name: Optional[str] = None
    level: Optional[str] = None
    teacher_id: Optional[str] = None
    schedule: Optional[str] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None


class GroupRead(GroupBase):
    id: str
    school_id: str
    teacher_id: Optional[str] = None
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class GroupWithStats(GroupRead):
    teacher_name: Optional[str] = None
    students_count: int = 0
    avg_rating: int = 1200
    games_played_this_week: int = 0
    avg_caps_accuracy: float = 0.0
    homework_completion_rate: float = 0.0


# ============================================================================
# STUDENT SCHEMAS
# ============================================================================

class StudentBase(BaseModel):
    first_name: str
    last_name: str
    birth_date: Optional[datetime] = None
    current_rating: int = 1200
    parent_name: Optional[str] = None
    parent_phone: Optional[str] = None
    parent_telegram: Optional[str] = None
    notes: Optional[str] = None


class StudentCreate(StudentBase):
    school_id: str
    group_id: Optional[str] = None
    lichess_username: Optional[str] = None
    chesscom_username: Optional[str] = None


class StudentUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    group_id: Optional[str] = None
    birth_date: Optional[datetime] = None
    current_rating: Optional[int] = None
    parent_name: Optional[str] = None
    parent_phone: Optional[str] = None
    parent_telegram: Optional[str] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None


class StudentRead(StudentBase):
    id: str
    school_id: Optional[str] = None
    group_id: Optional[str] = None
    is_active: bool
    created_at: datetime
    full_name: str

    class Config:
        from_attributes = True


class StudentCockpitCard(BaseModel):
    """
    Агрегированная карточка ученика для кабинета тренера (Cockpit).
    """
    id: str
    full_name: str
    group_id: Optional[str] = None
    group_name: Optional[str] = None
    rating: int = 1200
    lichess_username: Optional[str] = None
    chesscom_username: Optional[str] = None
    parent_name: Optional[str] = None
    parent_phone: Optional[str] = None
    parent_telegram: Optional[str] = None
    
    # Игровая активность и аналитика
    games_total: int = 0
    games_this_week: int = 0
    avg_caps_accuracy: float = 0.0
    avg_acpl: int = 0
    blunders_count_recent: int = 0
    top_weakness_tag: Optional[str] = None
    opening_holes_count: int = 0
    
    # Статус домашнего задания
    homework_status: str = "Не задано"  # 'Не задано', 'Выдано', 'Выполнено'
    last_synced_at: Optional[datetime] = None
    whatsapp_link: Optional[str] = None
