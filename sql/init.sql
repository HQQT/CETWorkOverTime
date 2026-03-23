-- ============================================================
-- CETWorkOverTime PostgreSQL 初始化脚本
-- 执行方式: psql -U postgres -d postgres -f sql/init.sql
-- ============================================================

SELECT 'CREATE DATABASE cetworkovertime'
WHERE NOT EXISTS (
    SELECT 1 FROM pg_database WHERE datname = 'cetworkovertime'
)\gexec

\connect cetworkovertime

-- ============================================================
-- 1. 元数据表
-- ============================================================
CREATE TABLE IF NOT EXISTS email_meta (
    id          BIGSERIAL PRIMARY KEY,
    meta_key    VARCHAR(100) NOT NULL UNIQUE,
    meta_value  TEXT,
    updated_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================
-- 2. 邮件单表
-- ============================================================
CREATE TABLE IF NOT EXISTS emails (
    id              BIGSERIAL PRIMARY KEY,
    email_date      DATE NOT NULL UNIQUE,
    subject         VARCHAR(500) NOT NULL DEFAULT '',
    sender          VARCHAR(200) NOT NULL DEFAULT '',
    content         TEXT NOT NULL,
    raw_content     TEXT,
    diligence_start TIME DEFAULT NULL,
    diligence_end   TIME DEFAULT NULL,
    diligence_hours NUMERIC(5, 2) DEFAULT 0,
    message_id      VARCHAR(500) DEFAULT '',
    source_filename VARCHAR(500) DEFAULT '',
    created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_emails_message_id ON emails (message_id);
CREATE INDEX IF NOT EXISTS idx_emails_email_date ON emails (email_date);

-- ============================================================
-- 初始化完成提示
-- ============================================================
SELECT '✅ CETWorkOverTime PostgreSQL 初始化完成!' AS message;
