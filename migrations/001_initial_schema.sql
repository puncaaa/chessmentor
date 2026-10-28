-- PostgreSQL DDL for Chess B2B SaaS Platform
-- Migration: 001_initial_schema.sql

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ============================================================================
-- ENUM TYPES
-- ============================================================================
DO $$ BEGIN
    CREATE TYPE user_role AS ENUM ('superadmin', 'school_admin', 'trainer', 'student', 'parent');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE chess_platform AS ENUM ('lichess', 'chesscom', 'manual_pgn');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE time_speed_category AS ENUM ('bullet', 'blitz', 'rapid', 'classical');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE game_phase AS ENUM ('opening', 'middlegame', 'endgame');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE error_severity AS ENUM ('inaccuracy', 'mistake', 'blunder');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE tactical_tag AS ENUM (
        'hanging_piece',
        'missed_fork',
        'missed_pin',
        'missed_skewer',
        'missed_discovered_atk',
        'missed_mate_sequence',
        'back_rank_weakness',
        'time_trouble_panic',
        'opening_book_exit',
        'endgame_king_activity',
        'pawn_structure_ruin',
        'tactical_blunder'
    );
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE analysis_status AS ENUM ('pending', 'processing', 'completed', 'failed');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE homework_status AS ENUM ('assigned', 'in_progress', 'completed', 'expired');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

-- ============================================================================
-- 1. ORGANIZATIONS, USERS & RBAC
-- ============================================================================

CREATE TABLE IF NOT EXISTS organizations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    slug VARCHAR(100) UNIQUE NOT NULL,
    subscription_plan VARCHAR(50) DEFAULT 'starter',
    max_students INT NOT NULL DEFAULT 30,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role user_role NOT NULL,
    first_name VARCHAR(100) NOT NULL,
    last_name VARCHAR(100) NOT NULL,
    phone VARCHAR(30),
    avatar_url TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS organization_members (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role user_role NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_org_user UNIQUE (organization_id, user_id)
);

CREATE TABLE IF NOT EXISTS student_profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID UNIQUE REFERENCES users(id) ON DELETE SET NULL,
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    first_name VARCHAR(100) NOT NULL,
    last_name VARCHAR(100) NOT NULL,
    birth_date DATE,
    fide_id VARCHAR(20),
    current_fide_rating INT,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS trainer_students (
    trainer_user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    student_profile_id UUID NOT NULL REFERENCES student_profiles(id) ON DELETE CASCADE,
    is_primary BOOLEAN NOT NULL DEFAULT TRUE,
    assigned_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (trainer_user_id, student_profile_id)
);

CREATE TABLE IF NOT EXISTS parent_students (
    parent_user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    student_profile_id UUID NOT NULL REFERENCES student_profiles(id) ON DELETE CASCADE,
    relationship_type VARCHAR(50) DEFAULT 'parent',
    receive_weekly_reports BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (parent_user_id, student_profile_id)
);

CREATE TABLE IF NOT EXISTS student_chess_accounts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    student_profile_id UUID NOT NULL REFERENCES student_profiles(id) ON DELETE CASCADE,
    platform chess_platform NOT NULL,
    username VARCHAR(100) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    last_synced_at TIMESTAMPTZ,
    last_game_played_at TIMESTAMPTZ,
    sync_error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_platform_account UNIQUE (platform, username)
);

-- ============================================================================
-- 2. GAMES & ENGINE METRICS
-- ============================================================================

CREATE TABLE IF NOT EXISTS games (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    student_profile_id UUID NOT NULL REFERENCES student_profiles(id) ON DELETE CASCADE,
    chess_account_id UUID REFERENCES student_chess_accounts(id) ON DELETE SET NULL,
    
    platform chess_platform NOT NULL,
    external_game_id VARCHAR(100),
    url TEXT,
    played_at TIMESTAMPTZ NOT NULL,
    
    student_color VARCHAR(5) NOT NULL CHECK (student_color IN ('white', 'black')),
    student_rating INT,
    opponent_username VARCHAR(100) NOT NULL,
    opponent_rating INT,
    result VARCHAR(10) NOT NULL,
    winner VARCHAR(5) CHECK (winner IN ('white', 'black', 'draw')),
    termination_reason VARCHAR(100),
    
    time_control VARCHAR(50) NOT NULL,
    speed_category time_speed_category NOT NULL,
    
    eco_code VARCHAR(10),
    opening_name VARCHAR(255),
    
    pgn TEXT NOT NULL,
    final_fen TEXT,
    move_count INT NOT NULL DEFAULT 0,
    
    accuracy_score NUMERIC(5, 2),
    acpl INT,
    blunders_count INT DEFAULT 0,
    mistakes_count INT DEFAULT 0,
    inaccuracies_count INT DEFAULT 0,
    time_spent_blunders_count INT DEFAULT 0,
    
    analysis_status analysis_status NOT NULL DEFAULT 'pending',
    engine_depth_analyzed SMALLINT,
    analyzed_at TIMESTAMPTZ,
    analysis_json JSONB,
    
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_platform_game UNIQUE (platform, external_game_id, student_profile_id)
);

-- ============================================================================
-- 3. ERROR EVENTS (Granular mistakes table)
-- ============================================================================

CREATE TABLE IF NOT EXISTS chess_error_events (
    id BIGSERIAL PRIMARY KEY,
    game_id UUID NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    student_profile_id UUID NOT NULL REFERENCES student_profiles(id) ON DELETE CASCADE,
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    
    ply_number INT NOT NULL,
    move_number INT NOT NULL,
    played_move_san VARCHAR(10) NOT NULL,
    played_move_uci VARCHAR(10) NOT NULL,
    best_move_san VARCHAR(10) NOT NULL,
    best_move_uci VARCHAR(10) NOT NULL,
    
    fen_before TEXT NOT NULL,
    fen_after TEXT NOT NULL,
    
    eval_before INT NOT NULL,
    eval_after INT NOT NULL,
    centipawn_loss INT NOT NULL,
    win_rate_drop NUMERIC(5, 2),
    
    severity error_severity NOT NULL,
    tactical_tag tactical_tag,
    phase game_phase NOT NULL,
    
    time_spent_seconds NUMERIC(6, 2),
    clock_remaining_seconds NUMERIC(8, 2),
    is_time_trouble BOOLEAN NOT NULL DEFAULT FALSE,
    
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================================
-- 4. AGGREGATED METRICS & LLM REPORTS
-- ============================================================================

CREATE TABLE IF NOT EXISTS student_weekly_metrics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    student_profile_id UUID NOT NULL REFERENCES student_profiles(id) ON DELETE CASCADE,
    week_start DATE NOT NULL,
    week_end DATE NOT NULL,
    games_played INT NOT NULL DEFAULT 0,
    avg_accuracy NUMERIC(5, 2),
    avg_acpl INT,
    opening_blunders INT DEFAULT 0,
    middlegame_blunders INT DEFAULT 0,
    endgame_blunders INT DEFAULT 0,
    time_trouble_rate NUMERIC(5, 2),
    blunders_in_panic_rate NUMERIC(5, 2),
    top_tactical_weaknesses JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_student_week UNIQUE (student_profile_id, week_start)
);

CREATE TABLE IF NOT EXISTS llm_progress_reports (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    student_profile_id UUID NOT NULL REFERENCES student_profiles(id) ON DELETE CASCADE,
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    trainer_id UUID REFERENCES users(id) ON DELETE SET NULL,
    report_type VARCHAR(20) NOT NULL CHECK (report_type IN ('trainer_technical', 'parent_empathic')),
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    games_analyzed_count INT NOT NULL,
    title VARCHAR(255) NOT NULL,
    summary_markdown TEXT NOT NULL,
    key_takeaways JSONB,
    homework_recommendation TEXT,
    model_name VARCHAR(50) NOT NULL,
    prompt_tokens INT,
    completion_tokens INT,
    is_sent_to_parent BOOLEAN DEFAULT FALSE,
    sent_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================================
-- 5. HOMEWORK & PUZZLES
-- ============================================================================

CREATE TABLE IF NOT EXISTS homework_assignments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    trainer_id UUID REFERENCES users(id) ON DELETE SET NULL,
    student_profile_id UUID NOT NULL REFERENCES student_profiles(id) ON DELETE CASCADE,
    title VARCHAR(255) NOT NULL,
    description TEXT,
    status homework_status NOT NULL DEFAULT 'assigned',
    due_date TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS homework_puzzles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    assignment_id UUID NOT NULL REFERENCES homework_assignments(id) ON DELETE CASCADE,
    source_error_event_id BIGINT REFERENCES chess_error_events(id) ON DELETE SET NULL,
    fen_initial TEXT NOT NULL,
    correct_solution_uci VARCHAR(20)[] NOT NULL,
    tactical_tag tactical_tag,
    hint_text TEXT,
    is_solved BOOLEAN DEFAULT FALSE,
    attempts_count INT DEFAULT 0,
    time_spent_seconds INT DEFAULT 0,
    solved_at TIMESTAMPTZ,
    order_index INT NOT NULL DEFAULT 0
);

-- ============================================================================
-- INDEXES
-- ============================================================================
CREATE INDEX IF NOT EXISTS idx_games_student_played_at ON games (student_profile_id, played_at DESC);
CREATE INDEX IF NOT EXISTS idx_games_pending_analysis ON games (analysis_status, played_at ASC) WHERE analysis_status = 'pending';
CREATE INDEX IF NOT EXISTS idx_chess_errors_student_phase_tag ON chess_error_events (student_profile_id, phase, tactical_tag, severity);
CREATE INDEX IF NOT EXISTS idx_chess_errors_fen ON chess_error_events (fen_before);
CREATE INDEX IF NOT EXISTS idx_student_profiles_org ON student_profiles (organization_id);
CREATE INDEX IF NOT EXISTS idx_games_org ON games (organization_id);
