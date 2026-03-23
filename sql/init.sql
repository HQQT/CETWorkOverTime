-- ============================================================
-- Email2Md 数据库初始化脚本
-- 执行方式: mysql -u root -p email2md < sql/init.sql
-- ============================================================

-- 创建数据库（如不存在）
CREATE DATABASE IF NOT EXISTS email2md
    DEFAULT CHARACTER SET utf8mb4
    DEFAULT COLLATE utf8mb4_unicode_ci;

USE email2md;

-- ============================================================
-- 1. 元数据表（不分表）
-- ============================================================
CREATE TABLE IF NOT EXISTS email_meta (
    id              INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    meta_key        VARCHAR(100) NOT NULL UNIQUE COMMENT '配置键',
    meta_value      TEXT COMMENT '配置值',
    updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='系统元数据(缓存、配置等)';

-- ============================================================
-- 2. 邮件年份表（按需创建，以下为示例年份）
--    应用运行时会通过 db.ensure_year_table() 自动创建
-- ============================================================

-- 2024 年
CREATE TABLE IF NOT EXISTS email_2024 (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    email_date      DATE NOT NULL COMMENT '邮件日期（工作日）',
    subject         VARCHAR(500) NOT NULL DEFAULT '' COMMENT '邮件主题',
    sender          VARCHAR(200) NOT NULL DEFAULT '' COMMENT '发件人',
    content         TEXT NOT NULL COMMENT '邮件正文（已清洗）',
    raw_content     MEDIUMTEXT COMMENT '邮件原始正文',
    diligence_start TIME DEFAULT NULL COMMENT '勤奋时间-开始',
    diligence_end   TIME DEFAULT NULL COMMENT '勤奋时间-结束',
    diligence_hours DECIMAL(5,2) DEFAULT 0 COMMENT '勤奋时长(小时)',
    message_id      VARCHAR(500) DEFAULT '' COMMENT 'Message-ID 去重',
    source_filename VARCHAR(500) DEFAULT '' COMMENT '来源 .eml 文件名',
    created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    UNIQUE KEY uk_email_date (email_date),
    INDEX idx_message_id (message_id),
    INDEX idx_year_month (email_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='邮件工作日志-2024年';

-- 2025 年
CREATE TABLE IF NOT EXISTS email_2025 LIKE email_2024;
ALTER TABLE email_2025 COMMENT='邮件工作日志-2025年';

-- 2026 年
CREATE TABLE IF NOT EXISTS email_2026 LIKE email_2024;
ALTER TABLE email_2026 COMMENT='邮件工作日志-2026年';

-- ============================================================
-- 初始化完成提示
-- ============================================================
SELECT '✅ Email2Md 数据库初始化完成!' AS message;
