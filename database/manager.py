"""
database/manager.py
───────────────────
Capa de abstracción de base de datos.

Bases de datos soportadas:
  • SQLite    (por defecto, sin configuración extra)
  • PostgreSQL
  • MariaDB / MySQL

Variables de entorno (.env):
  DB_TYPE=sqlite | postgresql | mariadb
  DATABASE_URL=  (requerido si DB_TYPE != sqlite)
    PostgreSQL → postgresql://user:pass@host:5432/dbname
  Alternativa por variables separadas (MariaDB):
    DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME
"""

import json
import logging
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Database")

VALID_CONFIG_COLUMNS = frozenset(
    {
        "mute_role_id",
        "log_channel_id",
        "warn_mute_threshold",
        "warn_kick_threshold",
        "warn_ban_threshold",
        "warn_mute_enabled",
        "warn_kick_enabled",
        "warn_ban_enabled",
        "warn_mute_duration",
        "warn_embed_config",
        "staff_role_id",
    }
)

VALID_USER_COLUMNS = frozenset(
    {
        "warns",
        "mute_start",
        "mute_duration",
    }
)

VALID_CHANNEL_CONFIG_COLUMNS = frozenset(
    {
        "guild_id",
        "locked",
        "media_only",
        "media_config",
        "auto_react",
        "slowmode",
    }
)

VALID_SERVER_CONFIG_COLUMNS = frozenset(
    {
        "staff_role_id",
        "mod_role_id",
        "modlog_channel",
        "serverlog_channel",
        "log_events",
        "embed_role_id",
        "channels_role_id",
        "users_role_id",
        "modlog_enabled",
        "serverlog_enabled",
    }
)

VALID_AI_CONFIG_COLUMNS = frozenset(
    {
        "guild_id",
        "ai_channel_id",
        "ai_role_id",
        "ai_model",
        "ai_system_prompt",
        "ai_limit_requests",
        "ai_limit_hours",
        "ai_imagine_enabled",
        "ai_webhook_name",
        "ai_webhook_icon",
    }
)

VALID_TICKET_COLUMNS = frozenset(
    {
        "channel_id",
        "staff_id",
        "status",
        "ai_summary",
        "closed_at",
    }
)

VALID_GIVEAWAY_COLUMNS = frozenset(
    {
        "prize",
        "end_time",
        "winners_count",
        "req_roles",
        "deny_roles",
        "participants",
        "ended",
        "cancelled",
        "winners",
    }
)

VALID_SUGGESTION_COLUMNS = frozenset(
    {
        "message_id",
        "content",
        "status",
        "upvotes",
        "downvotes",
        "denial_reason",
    }
)


# ── Schema por tipo de base de datos ─────────────────────────────────────────

_SCHEMA_SQLITE = """
CREATE TABLE IF NOT EXISTS guild_config (
    guild_id     INTEGER PRIMARY KEY,
    mute_role_id INTEGER,
    log_channel_id INTEGER,
    warn_mute_threshold INTEGER DEFAULT 3,
    warn_kick_threshold INTEGER DEFAULT 5,
    warn_ban_threshold  INTEGER DEFAULT 7,
    warn_mute_enabled   INTEGER DEFAULT 1,
    warn_kick_enabled   INTEGER DEFAULT 0,
    warn_ban_enabled    INTEGER DEFAULT 0,
    warn_mute_duration  INTEGER DEFAULT 3600,
    warn_embed_config   TEXT,
    staff_role_id INTEGER
);

CREATE TABLE IF NOT EXISTS user_records (
    user_id      INTEGER NOT NULL,
    guild_id     INTEGER NOT NULL,
    warns        INTEGER DEFAULT 0,
    mute_start   TEXT,
    mute_duration INTEGER,
    PRIMARY KEY (user_id, guild_id)
);

CREATE TABLE IF NOT EXISTS mod_actions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id     INTEGER NOT NULL,
    target_id    INTEGER NOT NULL,
    moderator_id INTEGER NOT NULL,
    action_type  TEXT    NOT NULL,
    reason       TEXT    DEFAULT 'Sin razón especificada',
    extra_data   TEXT,
    created_at   TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS channel_config (
    channel_id   INTEGER PRIMARY KEY,
    guild_id     INTEGER NOT NULL,
    locked       INTEGER DEFAULT 0,
    media_only   INTEGER DEFAULT 0,
    media_config TEXT,
    auto_react   TEXT,
    slowmode     INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS server_config (
    guild_id          INTEGER PRIMARY KEY,
    staff_role_id     INTEGER,
    modlog_channel    INTEGER,
    serverlog_channel INTEGER,
    log_events        TEXT,
    embed_role_id     INTEGER,
    channels_role_id  INTEGER,
    users_role_id     INTEGER,
    modlog_enabled    INTEGER DEFAULT 1,
    serverlog_enabled INTEGER DEFAULT 1,
    mod_role_id       INTEGER
);

CREATE TABLE IF NOT EXISTS ai_config (
    guild_id            INTEGER PRIMARY KEY,
    ai_channel_id       INTEGER,
    ai_role_id          INTEGER,
    ai_model            TEXT    DEFAULT 'gemini-2.5-flash-lite',
    ai_system_prompt    TEXT,
    ai_limit_requests   INTEGER DEFAULT 50,
    ai_limit_hours      INTEGER DEFAULT 12,
    ai_imagine_enabled  INTEGER DEFAULT 1,
    ai_webhook_name     TEXT,
    ai_webhook_icon     TEXT
);

-- Pool de API keys de IA. Cada key puede cubrir hasta 2 guilds.
CREATE TABLE IF NOT EXISTS ai_api_keys (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    label       TEXT    NOT NULL,
    api_key     TEXT    NOT NULL UNIQUE,
    active      INTEGER DEFAULT 1,
    notes       TEXT,
    created_at  TEXT    NOT NULL
);

-- Asignación 1:1 guild → key. Restringido por aplicación a 2 guilds por key.
CREATE TABLE IF NOT EXISTS ai_guild_keys (
    guild_id    INTEGER PRIMARY KEY,
    key_id      INTEGER NOT NULL,
    assigned_at TEXT    NOT NULL,
    FOREIGN KEY (key_id) REFERENCES ai_api_keys(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS appeals (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id     INTEGER NOT NULL,
    user_id      INTEGER NOT NULL,
    action_type  TEXT NOT NULL,
    reason       TEXT,
    appeal_text  TEXT,
    status       TEXT DEFAULT 'PENDING',
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS saved_embeds (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id     INTEGER NOT NULL,
    creator_id   INTEGER NOT NULL,
    name         TEXT,
    embed_data   TEXT NOT NULL,
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS welcome_config (
    guild_id     INTEGER PRIMARY KEY,
    channel_id   INTEGER,
    embed_data   TEXT,
    enabled      INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS boost_config (
    guild_id     INTEGER PRIMARY KEY,
    channel_id   INTEGER,
    embed_data   TEXT,
    gif_url      TEXT,
    enabled      INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS suggestions_config (
    guild_id           INTEGER PRIMARY KEY,
    submit_channel_id  INTEGER,
    review_channel_id  INTEGER,
    public_channel_id  INTEGER,
    enabled            INTEGER DEFAULT 1,
    auto_publish       INTEGER DEFAULT 0,
    min_length         INTEGER DEFAULT 10,
    max_length         INTEGER DEFAULT 2000,
    cooldown_seconds   INTEGER DEFAULT 300
);

CREATE TABLE IF NOT EXISTS suggestions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id      INTEGER NOT NULL,
    user_id       INTEGER NOT NULL,
    message_id    INTEGER,
    content       TEXT NOT NULL,
    status        TEXT DEFAULT 'PENDING',
    upvotes       INTEGER DEFAULT 0,
    downvotes     INTEGER DEFAULT 0,
    denial_reason TEXT,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS suggestion_votes (
    suggestion_id INTEGER NOT NULL,
    user_id       INTEGER NOT NULL,
    vote          INTEGER NOT NULL,
    PRIMARY KEY (suggestion_id, user_id)
);

CREATE TABLE IF NOT EXISTS giveaways (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id       INTEGER NOT NULL,
    channel_id     INTEGER NOT NULL,
    message_id     INTEGER NOT NULL,
    prize          TEXT NOT NULL,
    end_time       INTEGER NOT NULL,
    winners_count  INTEGER DEFAULT 1,
    req_roles      TEXT,
    deny_roles     TEXT,
    participants   TEXT,
    ended          INTEGER DEFAULT 0,
    cancelled      INTEGER DEFAULT 0,
    winners        TEXT
);

CREATE TABLE IF NOT EXISTS autoroles (
    message_id   INTEGER PRIMARY KEY,
    guild_id     INTEGER NOT NULL,
    channel_id   INTEGER NOT NULL,
    mapping_data TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS join_autoroles (
    guild_id   INTEGER NOT NULL,
    role_id    INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, role_id)
);

CREATE TABLE IF NOT EXISTS lofi_config (
    guild_id        INTEGER PRIMARY KEY,
    channel_id      INTEGER,
    volume          INTEGER DEFAULT 100,
    enabled         INTEGER DEFAULT 0,
    stream_url      TEXT,
    station_name    TEXT,
    auto_reconnect  INTEGER DEFAULT 1,
    pause_on_empty  INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS schema_migrations (
    version     INTEGER PRIMARY KEY,
    description TEXT,
    applied_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bot_stats (
    id             INTEGER PRIMARY KEY DEFAULT 1,
    members_online INTEGER DEFAULT 0,
    total_members  INTEGER DEFAULT 0,
    open_tickets   INTEGER DEFAULT 0,
    uptime_seconds INTEGER DEFAULT 0,
    last_updated   TEXT
);

CREATE TABLE IF NOT EXISTS ticket_config (
    guild_id                INTEGER PRIMARY KEY,
    panel_channel_id        INTEGER,
    category_id             INTEGER,
    log_channel_id          INTEGER,
    allowed_roles           TEXT DEFAULT '[]',
    immune_roles            TEXT DEFAULT '[]',
    panel_embed_data        TEXT,
    channel_name_template   TEXT DEFAULT '{username}-{number}',
    max_tickets_per_user    INTEGER DEFAULT 0,
    ticket_cooldown_seconds INTEGER DEFAULT 0,
    -- Referencias opcionales a plantillas en ticket_template_embeds. NULL = inline.
    panel_select_template   TEXT,
    panel_inside_template   TEXT,
    msg_open_template       TEXT,
    msg_close_template      TEXT
);

CREATE TABLE IF NOT EXISTS ticket_categories (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id                    INTEGER NOT NULL,
    name                        TEXT NOT NULL,
    emoji                       TEXT,
    description                 TEXT,
    questions                   TEXT DEFAULT '[]',
    close_reasons               TEXT DEFAULT '[]',
    welcome_embed_data          TEXT,
    welcome_embed_template_key  TEXT,
    staff_role_id               INTEGER
);

-- Pool de plantillas reutilizables (panel_select, panel_inside, msg_open, msg_close, custom_*).
CREATE TABLE IF NOT EXISTS ticket_template_embeds (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id    INTEGER NOT NULL,
    template_key TEXT   NOT NULL,
    name         TEXT,
    embed_data   TEXT   NOT NULL,
    created_at   TEXT   NOT NULL,
    UNIQUE(guild_id, template_key)
);

CREATE TABLE IF NOT EXISTS tickets (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    global_number INTEGER NOT NULL,
    guild_id      INTEGER NOT NULL,
    channel_id    INTEGER,
    user_id       INTEGER NOT NULL,
    category_name TEXT NOT NULL,
    staff_id      INTEGER,
    status        TEXT DEFAULT 'OPEN',
    ai_summary    TEXT,
    created_at    TEXT NOT NULL,
    closed_at     TEXT
);

CREATE INDEX IF NOT EXISTS idx_ur_guild   ON user_records(guild_id);
CREATE INDEX IF NOT EXISTS idx_ma_target  ON mod_actions(target_id, guild_id);
CREATE INDEX IF NOT EXISTS idx_ma_time    ON mod_actions(guild_id, created_at);
CREATE INDEX IF NOT EXISTS idx_mute_active ON user_records(mute_start)
    WHERE mute_start IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_cc_guild   ON channel_config(guild_id);
CREATE INDEX IF NOT EXISTS idx_se_guild   ON saved_embeds(guild_id);

CREATE TABLE IF NOT EXISTS tags (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id   INTEGER NOT NULL,
    name       TEXT NOT NULL,
    content    TEXT NOT NULL,
    creator_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    uses       INTEGER DEFAULT 0,
    UNIQUE(guild_id, name)
);

CREATE TABLE IF NOT EXISTS reports (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id         INTEGER NOT NULL,
    reporter_id      INTEGER NOT NULL,
    reported_user_id INTEGER NOT NULL,
    reason           TEXT NOT NULL,
    ticket_id        INTEGER,
    status           TEXT DEFAULT 'PENDING',
    created_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scheduled_messages (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id         INTEGER NOT NULL,
    name             TEXT NOT NULL,
    channel_id       INTEGER NOT NULL,
    content          TEXT NOT NULL,
    interval_seconds INTEGER NOT NULL,
    last_sent        TEXT,
    enabled          INTEGER DEFAULT 1,
    created_by       INTEGER NOT NULL,
    created_at       TEXT NOT NULL,
    UNIQUE(guild_id, name)
);

CREATE TABLE IF NOT EXISTS user_levels (
    user_id       INTEGER NOT NULL,
    guild_id      INTEGER NOT NULL,
    xp            INTEGER DEFAULT 0,
    level         INTEGER DEFAULT 0,
    message_count INTEGER DEFAULT 0,
    PRIMARY KEY (user_id, guild_id)
);

CREATE TABLE IF NOT EXISTS xp_config (
    guild_id                     INTEGER PRIMARY KEY,
    enabled                      INTEGER DEFAULT 0,
    xp_min                       INTEGER DEFAULT 15,
    xp_max                       INTEGER DEFAULT 25,
    cooldown_seconds             INTEGER DEFAULT 60,
    ignored_channels             TEXT    DEFAULT '[]',
    channel_multipliers          TEXT    DEFAULT '{}',
    announcement_channel_id      INTEGER,
    announcement_message         TEXT,
    stack_rewards                INTEGER DEFAULT 1,
    -- Comportamiento del mensaje de subida de nivel.
    levelup_persist              INTEGER DEFAULT 1,   -- 0: se elimina; 1: queda en el canal
    levelup_autodelete           INTEGER DEFAULT 0,   -- 0: nunca; 1: aplica delete_after
    levelup_delete_after_seconds INTEGER DEFAULT 30,
    levelup_embed_config         TEXT                 -- JSON embed; NULL = texto plano
);

CREATE TABLE IF NOT EXISTS level_rewards (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    level    INTEGER NOT NULL,
    role_id  INTEGER NOT NULL,
    UNIQUE(guild_id, level)
);

CREATE INDEX IF NOT EXISTS idx_tags_guild  ON tags(guild_id);
CREATE INDEX IF NOT EXISTS idx_rep_guild   ON reports(guild_id, status);
CREATE INDEX IF NOT EXISTS idx_sched_guild ON scheduled_messages(guild_id, enabled);
CREATE INDEX IF NOT EXISTS idx_ul_guild    ON user_levels(guild_id, xp);
CREATE INDEX IF NOT EXISTS idx_lr_guild    ON level_rewards(guild_id);

CREATE TABLE IF NOT EXISTS custom_commands (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id      INTEGER NOT NULL,
    name          TEXT NOT NULL,
    enabled       INTEGER DEFAULT 1,
    trigger_type  TEXT NOT NULL,
    trigger_value TEXT NOT NULL,
    conditions    TEXT DEFAULT '{}',
    actions       TEXT DEFAULT '[]',
    creator_id    INTEGER NOT NULL,
    created_at    TEXT NOT NULL,
    uses          INTEGER DEFAULT 0,
    last_used     TEXT,
    UNIQUE(guild_id, name)
);

CREATE TABLE IF NOT EXISTS cc_variables (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id  INTEGER NOT NULL,
    key       TEXT NOT NULL,
    value     TEXT DEFAULT '0',
    scope     TEXT DEFAULT 'guild',
    UNIQUE(guild_id, key, scope)
);

CREATE INDEX IF NOT EXISTS idx_cc_guild  ON custom_commands(guild_id);
CREATE INDEX IF NOT EXISTS idx_cc_trigger ON custom_commands(guild_id, trigger_type, enabled);
CREATE INDEX IF NOT EXISTS idx_ccv_guild ON cc_variables(guild_id);
"""

_SCHEMA_POSTGRESQL = """
CREATE TABLE IF NOT EXISTS guild_config (
    guild_id     BIGINT PRIMARY KEY,
    mute_role_id BIGINT,
    log_channel_id BIGINT,
    warn_mute_threshold INTEGER DEFAULT 3,
    warn_kick_threshold INTEGER DEFAULT 5,
    warn_ban_threshold  INTEGER DEFAULT 7,
    warn_mute_enabled   SMALLINT DEFAULT 1,
    warn_kick_enabled   SMALLINT DEFAULT 0,
    warn_ban_enabled    SMALLINT DEFAULT 0,
    warn_mute_duration  INTEGER DEFAULT 3600,
    warn_embed_config   TEXT,
    staff_role_id BIGINT
);

CREATE TABLE IF NOT EXISTS user_records (
    user_id      BIGINT NOT NULL,
    guild_id     BIGINT NOT NULL,
    warns        INTEGER DEFAULT 0,
    mute_start   TEXT,
    mute_duration INTEGER,
    PRIMARY KEY (user_id, guild_id)
);

CREATE TABLE IF NOT EXISTS mod_actions (
    id           BIGSERIAL PRIMARY KEY,
    guild_id     BIGINT NOT NULL,
    target_id    BIGINT NOT NULL,
    moderator_id BIGINT NOT NULL,
    action_type  TEXT   NOT NULL,
    reason       TEXT   DEFAULT 'Sin razón especificada',
    extra_data   TEXT,
    created_at   TEXT   NOT NULL
);

CREATE TABLE IF NOT EXISTS channel_config (
    channel_id   BIGINT PRIMARY KEY,
    guild_id     BIGINT NOT NULL,
    locked       SMALLINT DEFAULT 0,
    media_only   SMALLINT DEFAULT 0,
    media_config TEXT,
    auto_react   TEXT,
    slowmode     INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS server_config (
    guild_id          BIGINT PRIMARY KEY,
    staff_role_id     BIGINT,
    modlog_channel    BIGINT,
    serverlog_channel BIGINT,
    log_events        TEXT,
    embed_role_id     BIGINT,
    channels_role_id  BIGINT,
    users_role_id     BIGINT,
    modlog_enabled    SMALLINT DEFAULT 1,
    serverlog_enabled SMALLINT DEFAULT 1,
    mod_role_id       BIGINT
);

CREATE TABLE IF NOT EXISTS ai_config (
    guild_id            BIGINT  PRIMARY KEY,
    ai_channel_id       BIGINT,
    ai_role_id          BIGINT,
    ai_model            TEXT    DEFAULT 'gemini-2.5-flash-lite',
    ai_system_prompt    TEXT,
    ai_limit_requests   INTEGER DEFAULT 50,
    ai_limit_hours      INTEGER DEFAULT 12,
    ai_imagine_enabled  SMALLINT DEFAULT 1,
    ai_webhook_name     TEXT,
    ai_webhook_icon     TEXT
);

-- Pool de API keys de IA. Cada key puede cubrir hasta 2 guilds.
CREATE TABLE IF NOT EXISTS ai_api_keys (
    id          BIGSERIAL PRIMARY KEY,
    label       TEXT     NOT NULL,
    api_key     TEXT     NOT NULL UNIQUE,
    active      SMALLINT DEFAULT 1,
    notes       TEXT,
    created_at  TEXT     NOT NULL
);

-- Asignación 1:1 guild → key. Restringido por aplicación a 2 guilds por key.
CREATE TABLE IF NOT EXISTS ai_guild_keys (
    guild_id    BIGINT PRIMARY KEY,
    key_id      BIGINT NOT NULL REFERENCES ai_api_keys(id) ON DELETE CASCADE,
    assigned_at TEXT   NOT NULL
);

CREATE TABLE IF NOT EXISTS appeals (
    id           BIGSERIAL PRIMARY KEY,
    guild_id     BIGINT NOT NULL,
    user_id      BIGINT NOT NULL,
    action_type  TEXT NOT NULL,
    reason       TEXT,
    appeal_text  TEXT,
    status       TEXT DEFAULT 'PENDING',
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS saved_embeds (
    id           BIGSERIAL PRIMARY KEY,
    guild_id     BIGINT NOT NULL,
    creator_id   BIGINT NOT NULL,
    name         TEXT,
    embed_data   TEXT NOT NULL,
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS welcome_config (
    guild_id     BIGINT PRIMARY KEY,
    channel_id   BIGINT,
    embed_data   TEXT,
    enabled      SMALLINT DEFAULT 0
);

CREATE TABLE IF NOT EXISTS boost_config (
    guild_id     BIGINT PRIMARY KEY,
    channel_id   BIGINT,
    embed_data   TEXT,
    gif_url      TEXT,
    enabled      SMALLINT DEFAULT 0
);

CREATE TABLE IF NOT EXISTS suggestions_config (
    guild_id           BIGINT PRIMARY KEY,
    submit_channel_id  BIGINT,
    review_channel_id  BIGINT,
    public_channel_id  BIGINT,
    enabled            SMALLINT DEFAULT 1,
    auto_publish       SMALLINT DEFAULT 0,
    min_length         INTEGER  DEFAULT 10,
    max_length         INTEGER  DEFAULT 2000,
    cooldown_seconds   INTEGER  DEFAULT 300
);

CREATE TABLE IF NOT EXISTS suggestions (
    id            BIGSERIAL PRIMARY KEY,
    guild_id      BIGINT NOT NULL,
    user_id       BIGINT NOT NULL,
    message_id    BIGINT,
    content       TEXT NOT NULL,
    status        TEXT DEFAULT 'PENDING',
    upvotes       INTEGER DEFAULT 0,
    downvotes     INTEGER DEFAULT 0,
    denial_reason TEXT,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS suggestion_votes (
    suggestion_id BIGINT  NOT NULL,
    user_id       BIGINT  NOT NULL,
    vote          INTEGER NOT NULL,
    PRIMARY KEY (suggestion_id, user_id)
);

CREATE TABLE IF NOT EXISTS giveaways (
    id             BIGSERIAL PRIMARY KEY,
    guild_id       BIGINT NOT NULL,
    channel_id     BIGINT NOT NULL,
    message_id     BIGINT NOT NULL,
    prize          TEXT NOT NULL,
    end_time       BIGINT NOT NULL,
    winners_count  INTEGER DEFAULT 1,
    req_roles      TEXT,
    deny_roles     TEXT,
    participants   TEXT,
    ended          SMALLINT DEFAULT 0,
    cancelled      SMALLINT DEFAULT 0,
    winners        TEXT
);

CREATE TABLE IF NOT EXISTS autoroles (
    message_id   BIGINT PRIMARY KEY,
    guild_id     BIGINT NOT NULL,
    channel_id   BIGINT NOT NULL,
    mapping_data TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS join_autoroles (
    guild_id   BIGINT    NOT NULL,
    role_id    BIGINT    NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, role_id)
);

CREATE TABLE IF NOT EXISTS lofi_config (
    guild_id        BIGINT PRIMARY KEY,
    channel_id      BIGINT,
    volume          INTEGER  DEFAULT 100,
    enabled         SMALLINT DEFAULT 0,
    stream_url      TEXT,
    station_name    TEXT,
    auto_reconnect  SMALLINT DEFAULT 1,
    pause_on_empty  SMALLINT DEFAULT 0
);

CREATE TABLE IF NOT EXISTS schema_migrations (
    version     INTEGER PRIMARY KEY,
    description TEXT,
    applied_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bot_stats (
    id             INTEGER PRIMARY KEY DEFAULT 1,
    members_online INTEGER DEFAULT 0,
    total_members  INTEGER DEFAULT 0,
    open_tickets   INTEGER DEFAULT 0,
    uptime_seconds INTEGER DEFAULT 0,
    last_updated   TEXT
);

CREATE TABLE IF NOT EXISTS ticket_config (
    guild_id                BIGINT PRIMARY KEY,
    panel_channel_id        BIGINT,
    category_id             BIGINT,
    log_channel_id          BIGINT,
    allowed_roles           TEXT DEFAULT '[]',
    immune_roles            TEXT DEFAULT '[]',
    panel_embed_data        TEXT,
    channel_name_template   TEXT    DEFAULT '{username}-{number}',
    max_tickets_per_user    INTEGER DEFAULT 0,
    ticket_cooldown_seconds INTEGER DEFAULT 0,
    panel_select_template   TEXT,
    panel_inside_template   TEXT,
    msg_open_template       TEXT,
    msg_close_template      TEXT
);

CREATE TABLE IF NOT EXISTS ticket_categories (
    id                          BIGSERIAL PRIMARY KEY,
    guild_id                    BIGINT NOT NULL,
    name                        TEXT NOT NULL,
    emoji                       TEXT,
    description                 TEXT,
    questions                   TEXT DEFAULT '[]',
    close_reasons               TEXT DEFAULT '[]',
    welcome_embed_data          TEXT,
    welcome_embed_template_key  TEXT,
    staff_role_id               BIGINT
);

CREATE TABLE IF NOT EXISTS ticket_template_embeds (
    id           BIGSERIAL PRIMARY KEY,
    guild_id     BIGINT NOT NULL,
    template_key TEXT   NOT NULL,
    name         TEXT,
    embed_data   TEXT   NOT NULL,
    created_at   TEXT   NOT NULL,
    UNIQUE(guild_id, template_key)
);

CREATE TABLE IF NOT EXISTS tickets (
    id            BIGSERIAL PRIMARY KEY,
    global_number INTEGER NOT NULL,
    guild_id      BIGINT NOT NULL,
    channel_id    BIGINT,
    user_id       BIGINT NOT NULL,
    category_name TEXT NOT NULL,
    staff_id      BIGINT,
    status        TEXT DEFAULT 'OPEN',
    ai_summary    TEXT,
    created_at    TEXT NOT NULL,
    closed_at     TEXT
);

CREATE INDEX IF NOT EXISTS idx_ur_guild  ON user_records(guild_id);
CREATE INDEX IF NOT EXISTS idx_ma_target ON mod_actions(target_id, guild_id);
CREATE INDEX IF NOT EXISTS idx_ma_time   ON mod_actions(guild_id, created_at);
CREATE INDEX IF NOT EXISTS idx_cc_guild  ON channel_config(guild_id);
CREATE INDEX IF NOT EXISTS idx_se_guild  ON saved_embeds(guild_id);

CREATE TABLE IF NOT EXISTS tags (
    id         BIGSERIAL PRIMARY KEY,
    guild_id   BIGINT NOT NULL,
    name       TEXT NOT NULL,
    content    TEXT NOT NULL,
    creator_id BIGINT NOT NULL,
    created_at TEXT NOT NULL,
    uses       INTEGER DEFAULT 0,
    UNIQUE(guild_id, name)
);

CREATE TABLE IF NOT EXISTS reports (
    id               BIGSERIAL PRIMARY KEY,
    guild_id         BIGINT NOT NULL,
    reporter_id      BIGINT NOT NULL,
    reported_user_id BIGINT NOT NULL,
    reason           TEXT NOT NULL,
    ticket_id        BIGINT,
    status           TEXT DEFAULT 'PENDING',
    created_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scheduled_messages (
    id               BIGSERIAL PRIMARY KEY,
    guild_id         BIGINT NOT NULL,
    name             TEXT NOT NULL,
    channel_id       BIGINT NOT NULL,
    content          TEXT NOT NULL,
    interval_seconds INTEGER NOT NULL,
    last_sent        TEXT,
    enabled          SMALLINT DEFAULT 1,
    created_by       BIGINT NOT NULL,
    created_at       TEXT NOT NULL,
    UNIQUE(guild_id, name)
);

CREATE TABLE IF NOT EXISTS user_levels (
    user_id       BIGINT NOT NULL,
    guild_id      BIGINT NOT NULL,
    xp            INTEGER DEFAULT 0,
    level         INTEGER DEFAULT 0,
    message_count INTEGER DEFAULT 0,
    PRIMARY KEY (user_id, guild_id)
);

CREATE TABLE IF NOT EXISTS xp_config (
    guild_id                     BIGINT PRIMARY KEY,
    enabled                      SMALLINT DEFAULT 0,
    xp_min                       INTEGER  DEFAULT 15,
    xp_max                       INTEGER  DEFAULT 25,
    cooldown_seconds             INTEGER  DEFAULT 60,
    ignored_channels             TEXT     DEFAULT '[]',
    channel_multipliers          TEXT     DEFAULT '{}',
    announcement_channel_id      BIGINT,
    announcement_message         TEXT,
    stack_rewards                SMALLINT DEFAULT 1,
    levelup_persist              SMALLINT DEFAULT 1,
    levelup_autodelete           SMALLINT DEFAULT 0,
    levelup_delete_after_seconds INTEGER  DEFAULT 30,
    levelup_embed_config         TEXT
);

CREATE TABLE IF NOT EXISTS level_rewards (
    id       BIGSERIAL PRIMARY KEY,
    guild_id BIGINT NOT NULL,
    level    INTEGER NOT NULL,
    role_id  BIGINT NOT NULL,
    UNIQUE(guild_id, level)
);

CREATE INDEX IF NOT EXISTS idx_tags_guild  ON tags(guild_id);
CREATE INDEX IF NOT EXISTS idx_rep_guild   ON reports(guild_id, status);
CREATE INDEX IF NOT EXISTS idx_sched_guild ON scheduled_messages(guild_id, enabled);
CREATE INDEX IF NOT EXISTS idx_ul_guild    ON user_levels(guild_id, xp);
CREATE INDEX IF NOT EXISTS idx_lr_guild    ON level_rewards(guild_id);

CREATE TABLE IF NOT EXISTS custom_commands (
    id            BIGSERIAL PRIMARY KEY,
    guild_id      BIGINT NOT NULL,
    name          TEXT NOT NULL,
    enabled       SMALLINT DEFAULT 1,
    trigger_type  TEXT NOT NULL,
    trigger_value TEXT NOT NULL,
    conditions    TEXT DEFAULT '{}',
    actions       TEXT DEFAULT '[]',
    creator_id    BIGINT NOT NULL,
    created_at    TEXT NOT NULL,
    uses          INTEGER DEFAULT 0,
    last_used     TEXT,
    UNIQUE(guild_id, name)
);

CREATE TABLE IF NOT EXISTS cc_variables (
    id        BIGSERIAL PRIMARY KEY,
    guild_id  BIGINT NOT NULL,
    key       TEXT NOT NULL,
    value     TEXT DEFAULT '0',
    scope     TEXT DEFAULT 'guild',
    UNIQUE(guild_id, key, scope)
);

CREATE INDEX IF NOT EXISTS idx_cc_guild  ON custom_commands(guild_id);
CREATE INDEX IF NOT EXISTS idx_cc_trigger ON custom_commands(guild_id, trigger_type, enabled);
CREATE INDEX IF NOT EXISTS idx_ccv_guild ON cc_variables(guild_id);
"""

_SCHEMA_MARIADB = """
CREATE TABLE IF NOT EXISTS guild_config (
    guild_id     BIGINT PRIMARY KEY,
    mute_role_id BIGINT,
    log_channel_id BIGINT,
    warn_mute_threshold INT DEFAULT 3,
    warn_kick_threshold INT DEFAULT 5,
    warn_ban_threshold  INT DEFAULT 7,
    warn_mute_enabled   TINYINT DEFAULT 1,
    warn_kick_enabled   TINYINT DEFAULT 0,
    warn_ban_enabled    TINYINT DEFAULT 0,
    warn_mute_duration  INT DEFAULT 3600,
    warn_embed_config   TEXT,
    staff_role_id BIGINT
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS user_records (
    user_id      BIGINT NOT NULL,
    guild_id     BIGINT NOT NULL,
    warns        INT DEFAULT 0,
    mute_start   VARCHAR(50),
    mute_duration INT,
    PRIMARY KEY (user_id, guild_id)
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS mod_actions (
    id           BIGINT NOT NULL AUTO_INCREMENT,
    guild_id     BIGINT NOT NULL,
    target_id    BIGINT NOT NULL,
    moderator_id BIGINT NOT NULL,
    action_type  VARCHAR(30) NOT NULL,
    reason       TEXT,
    extra_data   TEXT,
    created_at   VARCHAR(50) NOT NULL,
    PRIMARY KEY (id),
    INDEX idx_ma_target (target_id, guild_id),
    INDEX idx_ma_time   (guild_id, created_at)
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS channel_config (
    channel_id   BIGINT PRIMARY KEY,
    guild_id     BIGINT NOT NULL,
    locked       TINYINT DEFAULT 0,
    media_only   TINYINT DEFAULT 0,
    media_config TEXT,
    auto_react   TEXT,
    slowmode     INT DEFAULT 0,
    INDEX idx_cc_guild (guild_id)
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS server_config (
    guild_id          BIGINT PRIMARY KEY,
    staff_role_id     BIGINT,
    modlog_channel    BIGINT,
    serverlog_channel BIGINT,
    log_events        TEXT,
    embed_role_id     BIGINT,
    channels_role_id  BIGINT,
    users_role_id     BIGINT,
    modlog_enabled    TINYINT DEFAULT 1,
    serverlog_enabled TINYINT DEFAULT 1,
    mod_role_id       BIGINT
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS ai_config (
    guild_id            BIGINT      PRIMARY KEY,
    ai_channel_id       BIGINT,
    ai_role_id          BIGINT,
    ai_model            VARCHAR(60) DEFAULT 'gemini-2.5-flash-lite',
    ai_system_prompt    TEXT,
    ai_limit_requests   INT         DEFAULT 50,
    ai_limit_hours      INT         DEFAULT 12,
    ai_imagine_enabled  TINYINT     DEFAULT 1,
    ai_webhook_name     TEXT,
    ai_webhook_icon     TEXT
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- Pool de API keys de IA. Cada key puede cubrir hasta 2 guilds.
CREATE TABLE IF NOT EXISTS ai_api_keys (
    id          BIGINT       NOT NULL AUTO_INCREMENT,
    label       VARCHAR(100) NOT NULL,
    api_key     VARCHAR(255) NOT NULL UNIQUE,
    active      TINYINT      DEFAULT 1,
    notes       TEXT,
    created_at  VARCHAR(50)  NOT NULL,
    PRIMARY KEY (id)
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- Asignación 1:1 guild → key. Restringido por aplicación a 2 guilds por key.
CREATE TABLE IF NOT EXISTS ai_guild_keys (
    guild_id    BIGINT      PRIMARY KEY,
    key_id      BIGINT      NOT NULL,
    assigned_at VARCHAR(50) NOT NULL,
    CONSTRAINT fk_ai_guild_key FOREIGN KEY (key_id) REFERENCES ai_api_keys(id) ON DELETE CASCADE
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS appeals (
    id           BIGINT NOT NULL AUTO_INCREMENT,
    guild_id     BIGINT NOT NULL,
    user_id      BIGINT NOT NULL,
    action_type  VARCHAR(30) NOT NULL,
    reason       TEXT,
    appeal_text  TEXT,
    status       VARCHAR(20) DEFAULT 'PENDING',
    created_at   VARCHAR(50) NOT NULL,
    PRIMARY KEY (id)
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS saved_embeds (
    id           BIGINT NOT NULL AUTO_INCREMENT,
    guild_id     BIGINT NOT NULL,
    creator_id   BIGINT NOT NULL,
    name         VARCHAR(100),
    embed_data   TEXT NOT NULL,
    created_at   VARCHAR(50) NOT NULL,
    PRIMARY KEY (id)
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS welcome_config (
    guild_id     BIGINT PRIMARY KEY,
    channel_id   BIGINT,
    embed_data   TEXT,
    enabled      TINYINT DEFAULT 0
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS boost_config (
    guild_id     BIGINT PRIMARY KEY,
    channel_id   BIGINT,
    embed_data   TEXT,
    gif_url      TEXT,
    enabled      TINYINT DEFAULT 0
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS suggestions_config (
    guild_id           BIGINT PRIMARY KEY,
    submit_channel_id  BIGINT,
    review_channel_id  BIGINT,
    public_channel_id  BIGINT,
    enabled            TINYINT DEFAULT 1,
    auto_publish       TINYINT DEFAULT 0,
    min_length         INT     DEFAULT 10,
    max_length         INT     DEFAULT 2000,
    cooldown_seconds   INT     DEFAULT 300
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS suggestions (
    id           BIGINT NOT NULL AUTO_INCREMENT,
    guild_id     BIGINT NOT NULL,
    user_id       BIGINT NOT NULL,
    message_id    BIGINT,
    content       TEXT NOT NULL,
    status        VARCHAR(20) DEFAULT 'PENDING',
    upvotes       INT DEFAULT 0,
    downvotes     INT DEFAULT 0,
    denial_reason TEXT,
    created_at    VARCHAR(50) NOT NULL,
    PRIMARY KEY (id)
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS suggestion_votes (
    suggestion_id BIGINT NOT NULL,
    user_id       BIGINT NOT NULL,
    vote          INT    NOT NULL,
    PRIMARY KEY (suggestion_id, user_id)
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS giveaways (
    id             BIGINT NOT NULL AUTO_INCREMENT,
    guild_id       BIGINT NOT NULL,
    channel_id     BIGINT NOT NULL,
    message_id     BIGINT NOT NULL,
    prize          TEXT NOT NULL,
    end_time       BIGINT NOT NULL,
    winners_count  INT DEFAULT 1,
    req_roles      TEXT,
    deny_roles     TEXT,
    participants   TEXT,
    ended          TINYINT DEFAULT 0,
    cancelled      TINYINT DEFAULT 0,
    winners        TEXT,
    PRIMARY KEY (id)
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS autoroles (
    message_id   BIGINT PRIMARY KEY,
    guild_id     BIGINT NOT NULL,
    channel_id   BIGINT NOT NULL,
    mapping_data TEXT NOT NULL
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS join_autoroles (
    guild_id   BIGINT    NOT NULL,
    role_id    BIGINT    NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, role_id)
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS lofi_config (
    guild_id        BIGINT  PRIMARY KEY,
    channel_id      BIGINT,
    volume          INT     DEFAULT 100,
    enabled         TINYINT DEFAULT 0,
    stream_url      TEXT,
    station_name    TEXT,
    auto_reconnect  TINYINT DEFAULT 1,
    pause_on_empty  TINYINT DEFAULT 0
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version     INTEGER PRIMARY KEY,
    description TEXT,
    applied_at  VARCHAR(50) NOT NULL
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS bot_stats (
    id             INT PRIMARY KEY DEFAULT 1,
    members_online INT DEFAULT 0,
    total_members  INT DEFAULT 0,
    open_tickets   INT DEFAULT 0,
    uptime_seconds INT DEFAULT 0,
    last_updated   VARCHAR(50)
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS ticket_config (
    guild_id                BIGINT PRIMARY KEY,
    panel_channel_id        BIGINT,
    category_id             BIGINT,
    log_channel_id          BIGINT,
    allowed_roles           TEXT,
    immune_roles            TEXT,
    panel_embed_data        TEXT,
    channel_name_template   VARCHAR(100) DEFAULT '{username}-{number}',
    max_tickets_per_user    INT DEFAULT 0,
    ticket_cooldown_seconds INT DEFAULT 0,
    panel_select_template   VARCHAR(100),
    panel_inside_template   VARCHAR(100),
    msg_open_template       VARCHAR(100),
    msg_close_template      VARCHAR(100)
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS ticket_categories (
    id                          BIGINT NOT NULL AUTO_INCREMENT,
    guild_id                    BIGINT NOT NULL,
    name                        VARCHAR(100) NOT NULL,
    emoji                       VARCHAR(50),
    description                 TEXT,
    questions                   TEXT,
    close_reasons               TEXT,
    welcome_embed_data          TEXT,
    welcome_embed_template_key  VARCHAR(100),
    staff_role_id               BIGINT,
    PRIMARY KEY (id)
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS ticket_template_embeds (
    id           BIGINT NOT NULL AUTO_INCREMENT,
    guild_id     BIGINT NOT NULL,
    template_key VARCHAR(100) NOT NULL,
    name         VARCHAR(150),
    embed_data   TEXT NOT NULL,
    created_at   VARCHAR(50) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY ux_tpl_guild_key (guild_id, template_key)
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS tickets (
    id            BIGINT NOT NULL AUTO_INCREMENT,
    global_number INT NOT NULL,
    guild_id      BIGINT NOT NULL,
    channel_id    BIGINT,
    user_id       BIGINT NOT NULL,
    category_name VARCHAR(100) NOT NULL,
    staff_id      BIGINT,
    status        VARCHAR(20) DEFAULT 'OPEN',
    ai_summary    TEXT,
    created_at    VARCHAR(50) NOT NULL,
    closed_at     VARCHAR(50),
    PRIMARY KEY (id)
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS tags (
    id         BIGINT NOT NULL AUTO_INCREMENT,
    guild_id   BIGINT NOT NULL,
    name       VARCHAR(100) NOT NULL,
    content    TEXT NOT NULL,
    creator_id BIGINT NOT NULL,
    created_at VARCHAR(50) NOT NULL,
    uses       INT DEFAULT 0,
    PRIMARY KEY (id),
    UNIQUE KEY unique_tag (guild_id, name)
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS reports (
    id               BIGINT NOT NULL AUTO_INCREMENT,
    guild_id         BIGINT NOT NULL,
    reporter_id      BIGINT NOT NULL,
    reported_user_id BIGINT NOT NULL,
    reason           TEXT NOT NULL,
    ticket_id        BIGINT,
    status           VARCHAR(20) DEFAULT 'PENDING',
    created_at       VARCHAR(50) NOT NULL,
    PRIMARY KEY (id)
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS scheduled_messages (
    id               BIGINT NOT NULL AUTO_INCREMENT,
    guild_id         BIGINT NOT NULL,
    name             VARCHAR(100) NOT NULL,
    channel_id       BIGINT NOT NULL,
    content          TEXT NOT NULL,
    interval_seconds INT NOT NULL,
    last_sent        VARCHAR(50),
    enabled          TINYINT DEFAULT 1,
    created_by       BIGINT NOT NULL,
    created_at       VARCHAR(50) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY unique_schedule (guild_id, name)
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS user_levels (
    user_id       BIGINT NOT NULL,
    guild_id      BIGINT NOT NULL,
    xp            INT DEFAULT 0,
    level         INT DEFAULT 0,
    message_count INT DEFAULT 0,
    PRIMARY KEY (user_id, guild_id)
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS xp_config (
    guild_id                     BIGINT PRIMARY KEY,
    enabled                      TINYINT DEFAULT 0,
    xp_min                       INT     DEFAULT 15,
    xp_max                       INT     DEFAULT 25,
    cooldown_seconds             INT     DEFAULT 60,
    ignored_channels             TEXT,
    channel_multipliers          TEXT,
    announcement_channel_id      BIGINT,
    announcement_message         TEXT,
    stack_rewards                TINYINT DEFAULT 1,
    levelup_persist              TINYINT DEFAULT 1,
    levelup_autodelete           TINYINT DEFAULT 0,
    levelup_delete_after_seconds INT     DEFAULT 30,
    levelup_embed_config         TEXT
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS level_rewards (
    id       BIGINT NOT NULL AUTO_INCREMENT,
    guild_id BIGINT NOT NULL,
    level    INT NOT NULL,
    role_id  BIGINT NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY unique_reward (guild_id, level)
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS custom_commands (
    id            BIGINT NOT NULL AUTO_INCREMENT,
    guild_id      BIGINT NOT NULL,
    name          VARCHAR(100) NOT NULL,
    enabled       TINYINT DEFAULT 1,
    trigger_type  VARCHAR(50) NOT NULL,
    trigger_value TEXT NOT NULL,
    conditions    TEXT,
    actions       TEXT,
    creator_id    BIGINT NOT NULL,
    created_at    VARCHAR(50) NOT NULL,
    uses          INT DEFAULT 0,
    last_used     VARCHAR(50),
    PRIMARY KEY (id),
    UNIQUE KEY unique_cc (guild_id, name)
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS cc_variables (
    id        BIGINT NOT NULL AUTO_INCREMENT,
    guild_id  BIGINT NOT NULL,
    `key`     VARCHAR(100) NOT NULL,
    value     TEXT,
    scope     VARCHAR(100) DEFAULT 'guild',
    PRIMARY KEY (id),
    UNIQUE KEY unique_ccv (guild_id, `key`, scope)
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
"""


class DatabaseManager:
    """Gestor de base de datos con soporte multi-proveedor."""

    DEFAULT_CONFIG: Dict[str, Any] = {
        "guild_id": None,
        "mute_role_id": None,
        "log_channel_id": None,
        "warn_mute_threshold": 3,
        "warn_kick_threshold": 5,
        "warn_ban_threshold": 7,
        "warn_mute_enabled": 1,
        "warn_kick_enabled": 0,
        "warn_ban_enabled": 0,
        "warn_mute_duration": 3600,
        "warn_embed_config": None,
        "staff_role_id": None,
    }

    DEFAULT_SERVER_CONFIG: Dict[str, Any] = {
        "guild_id": None,
        "staff_role_id": None,
        "modlog_channel": None,
        "serverlog_channel": None,
        "log_events": None,
        "embed_role_id": None,
        "channels_role_id": None,
        "users_role_id": None,
        "modlog_enabled": 1,
        "serverlog_enabled": 1,
    }

    DEFAULT_CHANNEL_CONFIG: Dict[str, Any] = {
        "channel_id": None,
        "guild_id": None,
        "locked": 0,
        "media_only": 0,
        "media_config": None,
        "auto_react": None,
        "slowmode": 0,
    }

    def __init__(self):
        import threading

        self.db_type = os.getenv("DB_TYPE", "sqlite").lower()

        if self.db_type == "sqlite":
            import sqlite3

            data_dir = Path(__file__).parent.parent / "data"
            data_dir.mkdir(exist_ok=True)
            self.db_path = str(data_dir / "bot.db")
            # Conexión persistente con lock para acceso concurrente seguro
            self._sqlite_lock = threading.Lock()
            self._sqlite_conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._sqlite_conn.row_factory = sqlite3.Row
            self._sqlite_conn.execute("PRAGMA journal_mode=WAL")
            self._sqlite_conn.execute("PRAGMA foreign_keys=ON")
            self._sqlite_conn.commit()
            logger.info(f"Base de datos: SQLite → {self.db_path}")

        elif self.db_type in ("postgresql", "mariadb"):
            self.connection_url = os.getenv("DATABASE_URL")
            if not self.connection_url and self.db_type == "postgresql":
                raise ValueError(
                    "DB_TYPE='postgresql' requiere DATABASE_URL en .env\n"
                    "Ejemplo: postgresql://usuario:contraseña@localhost:5432/bot_db"
                )
            logger.info(f"Base de datos: {self.db_type.upper()}")
        else:
            raise ValueError(
                f"DB_TYPE inválido: '{self.db_type}'. "
                "Usa 'sqlite', 'postgresql' o 'mariadb'."
            )

        self._init_schema()

    def __del__(self):
        """Cierra la conexión persistente de SQLite al destruir el objeto."""
        if self.db_type == "sqlite" and hasattr(self, "_sqlite_conn"):
            try:
                self._sqlite_conn.close()
            except Exception:
                pass

    # ── Utilidades internas ───────────────────────────────────────────────────

    @property
    def ph(self) -> str:
        """Placeholder de parámetro: '?' para SQLite, '%s' para los demás."""
        return "?" if self.db_type == "sqlite" else "%s"

    def _adapt(self, query: str) -> str:
        """Adapta los placeholders '?' según el tipo de DB."""
        if self.db_type == "sqlite":
            return query
        return query.replace("?", "%s")

    # ── Conexión ──────────────────────────────────────────────────────────────

    @contextmanager
    def _conn(self):
        """
        Context manager de conexión.
        SQLite: reutiliza la conexión persistente con lock de hilo.
        PostgreSQL/MariaDB: abre y cierra por operación.
        """
        if self.db_type == "sqlite":
            # Conexión compartida protegida por lock
            with self._sqlite_lock:
                try:
                    yield self._sqlite_conn
                    self._sqlite_conn.commit()
                except Exception as exc:
                    self._sqlite_conn.rollback()
                    logger.error(f"Error de base de datos: {exc}")
                    raise
            return

        # PostgreSQL y MariaDB: conexión por operación
        connection = None
        try:
            if self.db_type == "postgresql":
                import psycopg2
                from psycopg2.extras import RealDictCursor

                connection = psycopg2.connect(self.connection_url)
                connection.cursor_factory = RealDictCursor

            elif self.db_type == "mariadb":
                import pymysql
                import pymysql.cursors

                connection = pymysql.connect(
                    host=os.getenv("DB_HOST", "localhost"),
                    port=int(os.getenv("DB_PORT", "3306")),
                    user=os.getenv("DB_USER"),
                    password=os.getenv("DB_PASSWORD"),
                    database=os.getenv("DB_NAME"),
                    charset="utf8mb4",
                    cursorclass=pymysql.cursors.DictCursor,
                )

            yield connection
            connection.commit()

        except Exception as exc:
            if connection:
                connection.rollback()
            logger.error(f"Error de base de datos: {exc}")
            raise
        finally:
            if connection:
                connection.close()

    # ── Helpers de ejecución ──────────────────────────────────────────────────

    def _execute(self, query: str, params: tuple = ()) -> None:
        with self._conn() as conn:
            if self.db_type == "postgresql":
                from psycopg2.extras import RealDictCursor

                cur = conn.cursor(cursor_factory=RealDictCursor)
            else:
                cur = conn.cursor()
            cur.execute(self._adapt(query), params)

    def _fetchone(self, query: str, params: tuple = ()) -> Optional[Dict]:
        with self._conn() as conn:
            if self.db_type == "postgresql":
                from psycopg2.extras import RealDictCursor

                cur = conn.cursor(cursor_factory=RealDictCursor)
            else:
                cur = conn.cursor()
            cur.execute(self._adapt(query), params)
            row = cur.fetchone()
            return dict(row) if row else None

    def _fetchall(self, query: str, params: tuple = ()) -> List[Dict]:
        with self._conn() as conn:
            if self.db_type == "postgresql":
                from psycopg2.extras import RealDictCursor

                cur = conn.cursor(cursor_factory=RealDictCursor)
            else:
                cur = conn.cursor()
            cur.execute(self._adapt(query), params)
            return [dict(r) for r in cur.fetchall()]

    def _executemany(self, queries_params: List[tuple]) -> None:
        """Ejecuta múltiples queries en una única transacción."""
        with self._conn() as conn:
            if self.db_type == "postgresql":
                from psycopg2.extras import RealDictCursor

                cur = conn.cursor(cursor_factory=RealDictCursor)
            else:
                cur = conn.cursor()
            for query, params in queries_params:
                cur.execute(self._adapt(query), params)

    # ── Schema ────────────────────────────────────────────────────────────────

    def _init_schema(self):
        schema_map = {
            "sqlite": _SCHEMA_SQLITE,
            "postgresql": _SCHEMA_POSTGRESQL,
            "mariadb": _SCHEMA_MARIADB,
        }
        schema = schema_map[self.db_type]

        with self._conn() as conn:
            if self.db_type == "postgresql":
                from psycopg2.extras import RealDictCursor

                cur = conn.cursor(cursor_factory=RealDictCursor)
            else:
                cur = conn.cursor()
            # SQLite soporta executescript; los demás ejecutan statement a statement
            if self.db_type == "sqlite":
                conn.executescript(schema)
            else:
                for stmt in schema.split(";"):
                    stmt = stmt.strip()
                    if stmt:
                        cur.execute(stmt)

        logger.info("Schema de base de datos inicializado correctamente.")
        self._migrate_ai_config()
        self._migrate_tickets()
        self._run_migrations()

    def _migrate_tickets(self) -> None:
        """
        Migración no destructiva de tablas de tickets para BBDDs creadas
        antes de Fase 7 del refactor.
        """
        cfg_cols = [
            ("max_tickets_per_user", "INTEGER DEFAULT 0"),
            ("ticket_cooldown_seconds", "INTEGER DEFAULT 0"),
            ("panel_select_template", "TEXT"),
            ("panel_inside_template", "TEXT"),
            ("msg_open_template", "TEXT"),
            ("msg_close_template", "TEXT"),
        ]
        for col, col_def in cfg_cols:
            try:
                self.ensure_column("ticket_config", col, col_def)
            except Exception as e:
                logger.warning("ensure_column ticket_config.%s: %s", col, e)

        cat_cols = [
            ("description", "TEXT"),
            ("welcome_embed_template_key", "TEXT"),
            ("staff_role_id", "INTEGER"),
        ]
        for col, col_def in cat_cols:
            try:
                self.ensure_column("ticket_categories", col, col_def)
            except Exception as e:
                logger.warning("ensure_column ticket_categories.%s: %s", col, e)

        # Niveles (Fase 9): comportamiento del mensaje de subida.
        xp_cols = [
            ("levelup_persist", "INTEGER DEFAULT 1"),
            ("levelup_autodelete", "INTEGER DEFAULT 0"),
            ("levelup_delete_after_seconds", "INTEGER DEFAULT 30"),
            ("levelup_embed_config", "TEXT"),
        ]
        for col, col_def in xp_cols:
            try:
                self.ensure_column("xp_config", col, col_def)
            except Exception as e:
                logger.warning("ensure_column xp_config.%s: %s", col, e)

        # Sorteos (Fase 11): cancelled flag + winners persistidos.
        gw_cols = [
            ("cancelled", "INTEGER DEFAULT 0"),
            ("winners", "TEXT"),
        ]
        for col, col_def in gw_cols:
            try:
                self.ensure_column("giveaways", col, col_def)
            except Exception as e:
                logger.warning("ensure_column giveaways.%s: %s", col, e)

        # Sugerencias (Fase 15): flexibilidad de config + razón de denegación.
        sug_cfg_cols = [
            ("enabled", "INTEGER DEFAULT 1"),
            ("auto_publish", "INTEGER DEFAULT 0"),
            ("min_length", "INTEGER DEFAULT 10"),
            ("max_length", "INTEGER DEFAULT 2000"),
            ("cooldown_seconds", "INTEGER DEFAULT 300"),
        ]
        for col, col_def in sug_cfg_cols:
            try:
                self.ensure_column("suggestions_config", col, col_def)
            except Exception as e:
                logger.warning("ensure_column suggestions_config.%s: %s", col, e)
        try:
            self.ensure_column("suggestions", "denial_reason", "TEXT")
        except Exception as e:
            logger.warning("ensure_column suggestions.denial_reason: %s", e)

        # Radio (Fase 5): flags auto_reconnect / pause_on_empty.
        lofi_cols = [
            ("auto_reconnect", "INTEGER DEFAULT 1"),
            ("pause_on_empty", "INTEGER DEFAULT 0"),
        ]
        for col, col_def in lofi_cols:
            try:
                self.ensure_column("lofi_config", col, col_def)
            except Exception as e:
                logger.warning("ensure_column lofi_config.%s: %s", col, e)
        # Nota: voice_gen_config ya tiene su propia migración idempotente
        # en _ensure_voice_gen_tables (Fase 6).

    def _migrate_ai_config(self) -> None:
        """
        Migración no destructiva de ai_config.
        Añade columnas nuevas a bases de datos existentes sin perder datos.
        Seguro de ejecutar múltiples veces (ignora si la columna ya existe).
        """
        migrations = [
            ("ai_imagine_enabled", "INTEGER DEFAULT 1"),  # SQLite / genérico
        ]
        for col, col_def in migrations:
            try:
                if self.db_type == "mariadb":
                    # MariaDB: verificar antes de alterar
                    exists = self._fetchone(
                        "SELECT COUNT(*) as c FROM information_schema.COLUMNS "
                        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'ai_config' "
                        "AND COLUMN_NAME = ?",
                        (col,),
                    )
                    if exists and exists.get("c", 0):
                        continue
                else:
                    # SQLite: verificar con PRAGMA antes de alterar
                    cols = self._fetchall("PRAGMA table_info(ai_config)", ())
                    if any(r["name"] == col for r in cols):
                        continue
                self._execute(f"ALTER TABLE ai_config ADD COLUMN {col} {col_def}", ())
                logger.info(f"Migración ai_config: columna '{col}' añadida.")
            except Exception:
                pass  # Seguridad extra para otros motores

    # ── Sistema de Migraciones ──────────────────────────────────────────────

    # Lista de migraciones: (version, descripcion, sql)
    # El SQL es el mismo para los 3 motores; se adaptan placeholders automáticamente.
    _MIGRATIONS: List[tuple] = [
        (
            1,
            "lofi_config: añadir stream_url",
            "ALTER TABLE lofi_config ADD COLUMN stream_url TEXT",
        ),
        (
            2,
            "lofi_config: añadir station_name",
            "ALTER TABLE lofi_config ADD COLUMN station_name TEXT",
        ),
        (
            3,
            "ticket_config: máx tickets por usuario",
            "ALTER TABLE ticket_config ADD COLUMN max_tickets_per_user INTEGER DEFAULT 0",
        ),
        (
            4,
            "ticket_config: cooldown entre tickets",
            "ALTER TABLE ticket_config ADD COLUMN ticket_cooldown_seconds INTEGER DEFAULT 0",
        ),
        (
            5,
            "invite_config: tabla de configuración de invitaciones",
            "CREATE TABLE IF NOT EXISTS invite_config (guild_id INTEGER PRIMARY KEY, channel_id INTEGER, enabled INTEGER DEFAULT 1)",
        ),
        (
            6,
            "invite_stats: tabla de estadísticas de invitaciones",
            "CREATE TABLE IF NOT EXISTS invite_stats (id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER NOT NULL, inviter_id INTEGER NOT NULL, invited_id INTEGER NOT NULL, invite_code TEXT, created_at TEXT, UNIQUE(guild_id, invited_id))",
        ),
        (
            7,
            "server_config: server_log_channel para eventos del servidor",
            "ALTER TABLE server_config ADD COLUMN server_log_channel INTEGER",
        ),
        (
            8,
            "server_config: server_log_enabled",
            "ALTER TABLE server_config ADD COLUMN server_log_enabled INTEGER DEFAULT 0",
        ),
    ]

    def _run_migrations(self) -> None:
        """
        Ejecuta las migraciones pendientes de forma secuencial e idempotente.
        Cada migración se registra en la tabla schema_migrations para no repetirse.
        """
        try:
            applied = {
                r["version"]
                for r in self._fetchall("SELECT version FROM schema_migrations", ())
            }
        except Exception:
            applied = set()

        for version, description, sql in self._MIGRATIONS:
            if version in applied:
                continue
            try:
                self._execute(sql, ())
                self._execute(
                    "INSERT INTO schema_migrations (version, description, applied_at) VALUES (?, ?, ?)",
                    (version, description, datetime.now(timezone.utc).isoformat()),
                )
                logger.info(f"Migración v{version} aplicada: {description}")
            except Exception as exc:
                # Ignorar si la columna ya existe (bases de datos antiguas con ensure_column aplicado)
                if (
                    "duplicate column" in str(exc).lower()
                    or "already exists" in str(exc).lower()
                ):
                    # Registrar igualmente para no reintentar
                    try:
                        self._execute(
                            "INSERT INTO schema_migrations (version, description, applied_at) VALUES (?, ?, ?)",
                            (
                                version,
                                description,
                                datetime.now(timezone.utc).isoformat(),
                            ),
                        )
                    except Exception:
                        pass
                else:
                    logger.warning(
                        f"Error en migración v{version} ('{description}'): {exc}"
                    )

    def _has_column(self, table: str, column: str) -> bool:
        """Comprueba si una tabla tiene una columna (multi-DB)."""
        try:
            if self.db_type == "sqlite":
                rows = self._fetchall(f"PRAGMA table_info('{table}')")
                return any(r.get("name") == column for r in rows)

            if self.db_type == "mariadb":
                row = self._fetchone(
                    "SELECT COUNT(*) as c FROM information_schema.COLUMNS "
                    "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = ? AND COLUMN_NAME = ?",
                    (table, column),
                )
                return bool(row and row.get("c", 0))

            if self.db_type == "postgresql":
                row = self._fetchone(
                    "SELECT COUNT(*) as c FROM information_schema.columns "
                    "WHERE table_name = ? AND column_name = ?",
                    (table, column),
                )
                return bool(row and row.get("c", 0))

        except Exception:
            return False

        return False

    def ensure_column(self, table: str, column: str, column_def: str) -> None:
        """Añade una columna si no existe (silencioso si ya existe).

        Uso seguro desde código que puede ejecutarse repetidamente.
        """
        try:
            if self._has_column(table, column):
                return
            self._execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_def}", ())
            logger.info(f"Columna '{column}' añadida en tabla '{table}'")
        except Exception:
            # Ignorar si ya existe o si no es soportado por el motor
            pass

    # ── Guild Config ──────────────────────────────────────────────────────────

    def get_config(self, guild_id: int) -> Dict:
        """Retorna la config del servidor, con valores por defecto si no existe."""
        row = self._fetchone(
            "SELECT * FROM guild_config WHERE guild_id = ?", (guild_id,)
        )
        result = dict(self.DEFAULT_CONFIG)
        result["guild_id"] = guild_id
        if row:
            result.update(row)
        return result

    def set_config(self, guild_id: int, **kwargs) -> None:
        """Crea o actualiza campos de configuración de un servidor."""
        invalid = set(kwargs) - VALID_CONFIG_COLUMNS
        if invalid:
            raise ValueError(f"Columnas inválidas: {invalid}")

        ops = []
        # Asegurar que el registro exista
        if self.db_type == "sqlite":
            ops.append(
                (
                    "INSERT OR IGNORE INTO guild_config (guild_id) VALUES (?)",
                    (guild_id,),
                )
            )
        elif self.db_type == "postgresql":
            ops.append(
                (
                    "INSERT INTO guild_config (guild_id) VALUES (?) "
                    "ON CONFLICT (guild_id) DO NOTHING",
                    (guild_id,),
                )
            )
        else:  # mariadb
            ops.append(
                (
                    "INSERT IGNORE INTO guild_config (guild_id) VALUES (?)",
                    (guild_id,),
                )
            )

        for col, val in kwargs.items():
            ops.append(
                (
                    f"UPDATE guild_config SET {col} = ? WHERE guild_id = ?",
                    (val, guild_id),
                )
            )

        self._executemany(ops)

    # ── User Records ──────────────────────────────────────────────────────────

    def get_user(self, user_id: int, guild_id: int) -> Dict:
        row = self._fetchone(
            "SELECT * FROM user_records WHERE user_id = ? AND guild_id = ?",
            (user_id, guild_id),
        )
        if row:
            return row
        return {
            "user_id": user_id,
            "guild_id": guild_id,
            "warns": 0,
            "mute_start": None,
            "mute_duration": None,
        }

    def _upsert_user(self, user_id: int, guild_id: int, **kwargs) -> None:
        invalid = set(kwargs) - VALID_USER_COLUMNS
        if invalid:
            raise ValueError(f"Columnas inválidas: {invalid}")

        ops = []
        if self.db_type == "sqlite":
            ops.append(
                (
                    "INSERT OR IGNORE INTO user_records (user_id, guild_id) VALUES (?, ?)",
                    (user_id, guild_id),
                )
            )
        elif self.db_type == "postgresql":
            ops.append(
                (
                    "INSERT INTO user_records (user_id, guild_id) VALUES (?, ?) "
                    "ON CONFLICT (user_id, guild_id) DO NOTHING",
                    (user_id, guild_id),
                )
            )
        else:
            ops.append(
                (
                    "INSERT IGNORE INTO user_records (user_id, guild_id) VALUES (?, ?)",
                    (user_id, guild_id),
                )
            )

        for col, val in kwargs.items():
            ops.append(
                (
                    f"UPDATE user_records SET {col} = ? WHERE user_id = ? AND guild_id = ?",
                    (val, user_id, guild_id),
                )
            )

        self._executemany(ops)

    def add_warn(self, user_id: int, guild_id: int) -> int:
        """Incrementa el contador de warns y retorna el nuevo total."""
        current = self.get_user(user_id, guild_id)
        new_count = current["warns"] + 1
        self._upsert_user(user_id, guild_id, warns=new_count)
        return new_count

    def clear_warns(self, user_id: int, guild_id: int) -> None:
        self._upsert_user(user_id, guild_id, warns=0)

    def set_mute(
        self, user_id: int, guild_id: int, duration_secs: Optional[int]
    ) -> None:
        self._upsert_user(
            user_id,
            guild_id,
            mute_start=datetime.now(timezone.utc).isoformat(),
            mute_duration=duration_secs,
        )

    def clear_mute(self, user_id: int, guild_id: int) -> None:
        self._upsert_user(user_id, guild_id, mute_start=None, mute_duration=None)

    def get_active_mutes(self) -> List[Dict]:
        """Retorna todos los registros con mutes activos y duración definida."""
        return self._fetchall(
            "SELECT * FROM user_records "
            "WHERE mute_start IS NOT NULL AND mute_duration IS NOT NULL"
        )

    # ── Mod Actions ───────────────────────────────────────────────────────────

    def log_action(
        self,
        guild_id: int,
        target_id: int,
        moderator_id: int,
        action_type: str,
        reason: str = "Sin razón especificada",
        extra: Optional[Dict] = None,
    ) -> None:
        self._execute(
            "INSERT INTO mod_actions "
            "(guild_id, target_id, moderator_id, action_type, reason, extra_data, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                guild_id,
                target_id,
                moderator_id,
                action_type,
                reason,
                json.dumps(extra, ensure_ascii=False) if extra else None,
                datetime.now(timezone.utc).isoformat(),
            ),
        )

    def get_user_history(
        self, user_id: int, guild_id: int, limit: int = 10
    ) -> List[Dict]:
        return self._fetchall(
            "SELECT * FROM mod_actions "
            "WHERE target_id = ? AND guild_id = ? "
            "ORDER BY created_at DESC LIMIT ?",
            (user_id, guild_id, limit),
        )

    def get_user_action_summary(self, user_id: int, guild_id: int) -> Dict[str, int]:
        """Cuenta warns, kicks, bans, mutes de un usuario para /userinfo."""
        rows = self._fetchall(
            "SELECT action_type, COUNT(*) as cnt FROM mod_actions "
            "WHERE target_id = ? AND guild_id = ? "
            "GROUP BY action_type",
            (user_id, guild_id),
        )
        summary = {"WARN": 0, "KICK": 0, "BAN": 0, "MUTE": 0, "UNMUTE": 0}
        for r in rows:
            if r["action_type"] in summary:
                summary[r["action_type"]] = r["cnt"]
        return summary

    # ── Channel Config ────────────────────────────────────────────────────────

    def get_channel_config(self, channel_id: int) -> Dict:
        row = self._fetchone(
            "SELECT * FROM channel_config WHERE channel_id = ?", (channel_id,)
        )
        result = dict(self.DEFAULT_CHANNEL_CONFIG)
        result["channel_id"] = channel_id
        if row:
            result.update(row)
        return result

    def set_channel_config(self, channel_id: int, guild_id: int, **kwargs) -> None:
        invalid = set(kwargs) - VALID_CHANNEL_CONFIG_COLUMNS
        if invalid:
            raise ValueError(f"Columnas inválidas: {invalid}")

        ops = []
        if self.db_type == "sqlite":
            ops.append(
                (
                    "INSERT OR IGNORE INTO channel_config (channel_id, guild_id) VALUES (?, ?)",
                    (channel_id, guild_id),
                )
            )
        elif self.db_type == "postgresql":
            ops.append(
                (
                    "INSERT INTO channel_config (channel_id, guild_id) VALUES (?, ?) "
                    "ON CONFLICT (channel_id) DO NOTHING",
                    (channel_id, guild_id),
                )
            )
        else:
            ops.append(
                (
                    "INSERT IGNORE INTO channel_config (channel_id, guild_id) VALUES (?, ?)",
                    (channel_id, guild_id),
                )
            )

        for col, val in kwargs.items():
            ops.append(
                (
                    f"UPDATE channel_config SET {col} = ? WHERE channel_id = ?",
                    (val, channel_id),
                )
            )

        self._executemany(ops)

    def delete_channel_config(self, channel_id: int) -> None:
        self._execute("DELETE FROM channel_config WHERE channel_id = ?", (channel_id,))

    def get_all_channel_configs(self, guild_id: int) -> List[Dict]:
        return self._fetchall(
            "SELECT * FROM channel_config WHERE guild_id = ?", (guild_id,)
        )

    # ── Server Config ─────────────────────────────────────────────────────────

    def get_server_config(self, guild_id: int) -> Dict:
        row = self._fetchone(
            "SELECT * FROM server_config WHERE guild_id = ?", (guild_id,)
        )
        result = dict(self.DEFAULT_SERVER_CONFIG)
        result["guild_id"] = guild_id
        if row:
            result.update(row)
        return result

    def set_server_config(self, guild_id: int, **kwargs) -> None:
        invalid = set(kwargs) - VALID_SERVER_CONFIG_COLUMNS
        if invalid:
            raise ValueError(f"Columnas inválidas: {invalid}")

        ops = []
        if self.db_type == "sqlite":
            ops.append(
                (
                    "INSERT OR IGNORE INTO server_config (guild_id) VALUES (?)",
                    (guild_id,),
                )
            )
        elif self.db_type == "postgresql":
            ops.append(
                (
                    "INSERT INTO server_config (guild_id) VALUES (?) "
                    "ON CONFLICT (guild_id) DO NOTHING",
                    (guild_id,),
                )
            )
        else:
            ops.append(
                (
                    "INSERT IGNORE INTO server_config (guild_id) VALUES (?)",
                    (guild_id,),
                )
            )

        for col, val in kwargs.items():
            ops.append(
                (
                    f"UPDATE server_config SET {col} = ? WHERE guild_id = ?",
                    (val, guild_id),
                )
            )

        self._executemany(ops)

    # ── Saved Embeds ──────────────────────────────────────────────────────────

    def save_embed(
        self, guild_id: int, creator_id: int, name: str, embed_data: str
    ) -> None:
        self._execute(
            "INSERT INTO saved_embeds (guild_id, creator_id, name, embed_data, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                guild_id,
                creator_id,
                name,
                embed_data,
                datetime.now(timezone.utc).isoformat(),
            ),
        )

    def get_saved_embeds(self, guild_id: int) -> List[Dict]:
        return self._fetchall(
            "SELECT * FROM saved_embeds WHERE guild_id = ? ORDER BY created_at DESC",
            (guild_id,),
        )

    def get_saved_embed_by_name(self, guild_id: int, name: str) -> Optional[Dict]:
        return self._fetchone(
            "SELECT * FROM saved_embeds WHERE guild_id = ? AND name = ?",
            (guild_id, name),
        )

    def delete_saved_embed(self, embed_id: int) -> None:
        self._execute("DELETE FROM saved_embeds WHERE id = ?", (embed_id,))

    # ── AI Config ─────────────────────────────────────────────────────────────

    DEFAULT_AI_CONFIG: Dict[str, Any] = {
        "guild_id": None,
        "ai_channel_id": None,
        "ai_role_id": None,
        "ai_model": "gemini-2.5-flash-lite",  # free-tier: 15 RPM / 1000 RPD
        "ai_system_prompt": None,
        "ai_limit_requests": 50,
        "ai_limit_hours": 12,
        "ai_imagine_enabled": 1,
        "ai_webhook_name": None,
        "ai_webhook_icon": None,
    }

    def get_ai_config(self, guild_id: int) -> Dict:
        row = self._fetchone("SELECT * FROM ai_config WHERE guild_id = ?", (guild_id,))
        result = dict(self.DEFAULT_AI_CONFIG)
        result["guild_id"] = guild_id
        if row:
            result.update(row)
        return result

    def set_ai_config(self, guild_id: int, **kwargs) -> None:
        invalid = set(kwargs) - VALID_AI_CONFIG_COLUMNS
        if invalid:
            raise ValueError(f"Columnas inválidas en ai_config: {invalid}")

        ops = []
        if self.db_type == "sqlite":
            ops.append(
                (
                    "INSERT OR IGNORE INTO ai_config (guild_id) VALUES (?)",
                    (guild_id,),
                )
            )
        elif self.db_type == "postgresql":
            ops.append(
                (
                    "INSERT INTO ai_config (guild_id) VALUES (?) ON CONFLICT (guild_id) DO NOTHING",
                    (guild_id,),
                )
            )
        else:
            ops.append(
                (
                    "INSERT IGNORE INTO ai_config (guild_id) VALUES (?)",
                    (guild_id,),
                )
            )

        for col, val in kwargs.items():
            ops.append(
                (
                    f"UPDATE ai_config SET {col} = ? WHERE guild_id = ?",
                    (val, guild_id),
                )
            )

        self._executemany(ops)

    # ── AI API Keys (multi-tenant pool) ───────────────────────────────────────
    #
    # Reglas de negocio:
    #   • Cada guild tiene asignada como máximo una key (PK en ai_guild_keys).
    #   • Cada key cubre como máximo 2 guilds (validado al asignar).
    #   • Soft-disable vía `active` en lugar de borrar (preserva auditoría).

    AI_KEY_MAX_GUILDS_PER_KEY = 2

    def list_ai_keys(self) -> List[Dict]:
        """
        Lista todas las API keys del pool con su uso (cuántos guilds tienen
        cada key asignada). No expone la api_key completa al caller — eso queda
        a cargo de la capa API; aquí devolvemos el campo crudo.
        """
        rows = self._fetchall(
            """
            SELECT k.id, k.label, k.api_key, k.active, k.notes, k.created_at,
                   COUNT(g.guild_id) AS guilds_assigned
              FROM ai_api_keys k
              LEFT JOIN ai_guild_keys g ON g.key_id = k.id
             GROUP BY k.id
             ORDER BY k.created_at DESC
            """,
            (),
        )
        return [dict(r) for r in rows]

    def get_ai_key(self, key_id: int) -> Optional[Dict]:
        row = self._fetchone(
            "SELECT * FROM ai_api_keys WHERE id = ?", (key_id,)
        )
        return dict(row) if row else None

    def add_ai_key(self, label: str, api_key: str, notes: Optional[str] = None) -> int:
        """Inserta una nueva key. Devuelve el id insertado."""
        now = datetime.now(timezone.utc).isoformat()
        if self.db_type == "postgresql":
            row = self._fetchone(
                "INSERT INTO ai_api_keys (label, api_key, notes, created_at) "
                "VALUES (?, ?, ?, ?) RETURNING id",
                (label, api_key, notes, now),
            )
            return int(row["id"]) if row else 0
        # sqlite + mariadb: insertar y leer last_insert_rowid / LAST_INSERT_ID()
        self._execute(
            "INSERT INTO ai_api_keys (label, api_key, notes, created_at) VALUES (?, ?, ?, ?)",
            (label, api_key, notes, now),
        )
        if self.db_type == "sqlite":
            row = self._fetchone("SELECT last_insert_rowid() AS id", ())
        else:  # mariadb
            row = self._fetchone("SELECT LAST_INSERT_ID() AS id", ())
        return int(row["id"]) if row else 0

    def update_ai_key(self, key_id: int, **kwargs) -> None:
        """Actualiza label, active, notes. api_key se actualiza por separado por seguridad."""
        allowed = {"label", "active", "notes", "api_key"}
        invalid = set(kwargs) - allowed
        if invalid:
            raise ValueError(f"Campos inválidos en update_ai_key: {invalid}")
        if not kwargs:
            return
        ops = [
            (f"UPDATE ai_api_keys SET {col} = ? WHERE id = ?", (val, key_id))
            for col, val in kwargs.items()
        ]
        self._executemany(ops)

    def delete_ai_key(self, key_id: int) -> None:
        """Borra una key. ON DELETE CASCADE limpia ai_guild_keys."""
        self._execute("DELETE FROM ai_api_keys WHERE id = ?", (key_id,))

    def get_ai_key_for_guild(self, guild_id: int) -> Optional[Dict]:
        """Devuelve la key asignada al guild (o None)."""
        row = self._fetchone(
            """
            SELECT k.id, k.label, k.api_key, k.active, g.assigned_at
              FROM ai_guild_keys g
              JOIN ai_api_keys k ON k.id = g.key_id
             WHERE g.guild_id = ?
            """,
            (guild_id,),
        )
        return dict(row) if row else None

    def count_guilds_for_key(self, key_id: int) -> int:
        row = self._fetchone(
            "SELECT COUNT(*) AS n FROM ai_guild_keys WHERE key_id = ?", (key_id,)
        )
        return int(row["n"]) if row else 0

    def assign_ai_key_to_guild(self, guild_id: int, key_id: int) -> None:
        """
        Asigna una key a un guild. Aplica las reglas:
          • Si el guild ya tiene una key, se reemplaza (PK garantiza unicidad).
          • Antes de asignar, valida que la key tenga capacidad (< 2 guilds).
        """
        key = self.get_ai_key(key_id)
        if not key:
            raise ValueError(f"Key {key_id} no existe")
        if not int(key.get("active", 0)):
            raise ValueError(f"Key {key_id} está inactiva")

        # Si el guild ya tenía la misma key, no contamos doble.
        existing = self.get_ai_key_for_guild(guild_id)
        if existing and int(existing["id"]) == int(key_id):
            return  # idempotente

        # Cuenta cuántos guilds usan esta key actualmente.
        current = self.count_guilds_for_key(key_id)
        if current >= self.AI_KEY_MAX_GUILDS_PER_KEY:
            raise ValueError(
                f"La key '{key['label']}' ya cubre el máximo de "
                f"{self.AI_KEY_MAX_GUILDS_PER_KEY} servidores"
            )

        now = datetime.now(timezone.utc).isoformat()
        if self.db_type == "sqlite":
            sql = (
                "INSERT OR REPLACE INTO ai_guild_keys (guild_id, key_id, assigned_at) "
                "VALUES (?, ?, ?)"
            )
        elif self.db_type == "postgresql":
            sql = (
                "INSERT INTO ai_guild_keys (guild_id, key_id, assigned_at) "
                "VALUES (?, ?, ?) "
                "ON CONFLICT (guild_id) DO UPDATE SET "
                "key_id = EXCLUDED.key_id, assigned_at = EXCLUDED.assigned_at"
            )
        else:  # mariadb
            sql = (
                "INSERT INTO ai_guild_keys (guild_id, key_id, assigned_at) "
                "VALUES (?, ?, ?) "
                "ON DUPLICATE KEY UPDATE key_id = VALUES(key_id), "
                "assigned_at = VALUES(assigned_at)"
            )
        self._execute(sql, (guild_id, key_id, now))

    def unassign_ai_key_from_guild(self, guild_id: int) -> None:
        self._execute("DELETE FROM ai_guild_keys WHERE guild_id = ?", (guild_id,))

    def list_guilds_for_key(self, key_id: int) -> List[int]:
        rows = self._fetchall(
            "SELECT guild_id FROM ai_guild_keys WHERE key_id = ?", (key_id,)
        )
        return [int(r["guild_id"]) for r in rows]

    def ai_key_pool_health(self) -> Dict:
        """
        Reporte rápido del pool. Útil para alertar al admin si:
          • hay más guilds que (keys * 2) → faltan keys.
        """
        keys = self._fetchall("SELECT COUNT(*) AS n FROM ai_api_keys WHERE active = 1", ())
        active_keys = int(keys[0]["n"]) if keys else 0
        guilds = self._fetchall("SELECT COUNT(*) AS n FROM ai_guild_keys", ())
        assigned_guilds = int(guilds[0]["n"]) if guilds else 0
        capacity = active_keys * self.AI_KEY_MAX_GUILDS_PER_KEY
        return {
            "active_keys": active_keys,
            "assigned_guilds": assigned_guilds,
            "capacity": capacity,
            "deficit": max(0, assigned_guilds - capacity),
        }

    # ── Appeals ───────────────────────────────────────────────────────────────

    def create_appeal(
        self,
        guild_id: int,
        user_id: int,
        action_type: str,
        reason: str,
        appeal_text: str,
    ) -> int:
        """Crea una nueva apelación y retorna su ID (aproximado o ejecutado)."""
        ops = [
            (
                "INSERT INTO appeals (guild_id, user_id, action_type, reason, appeal_text, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    guild_id,
                    user_id,
                    action_type,
                    reason,
                    appeal_text,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
        ]
        self._executemany(ops)
        # Buscar el ID más reciente
        row = self._fetchone(
            "SELECT id FROM appeals WHERE guild_id = ? AND user_id = ? ORDER BY id DESC LIMIT 1",
            (guild_id, user_id),
        )
        return row["id"] if row else 0

    def get_appeal(self, appeal_id: int) -> Optional[Dict]:
        return self._fetchone("SELECT * FROM appeals WHERE id = ?", (appeal_id,))

    def update_appeal_status(self, appeal_id: int, status: str) -> None:
        self._execute("UPDATE appeals SET status = ? WHERE id = ?", (status, appeal_id))

    # ── Configuración Genérica ────────────────────────────────────────────────
    def _upsert_config(self, table: str, guild_id: int, **kwargs):
        ops = []
        if self.db_type == "sqlite":
            ops.append(
                (f"INSERT OR IGNORE INTO {table} (guild_id) VALUES (?)", (guild_id,))
            )
        elif self.db_type == "postgresql":
            ops.append(
                (
                    f"INSERT INTO {table} (guild_id) VALUES (?) ON CONFLICT (guild_id) DO NOTHING",
                    (guild_id,),
                )
            )
        else:
            ops.append(
                (f"INSERT IGNORE INTO {table} (guild_id) VALUES (?)", (guild_id,))
            )

        for col, val in kwargs.items():
            ops.append(
                (f"UPDATE {table} SET {col} = ? WHERE guild_id = ?", (val, guild_id))
            )
        self._executemany(ops)

    # ── Welcomes ──────────────────────────────────────────────────────────────
    def get_welcome_config(self, guild_id: int) -> Dict:
        row = self._fetchone(
            "SELECT * FROM welcome_config WHERE guild_id = ?", (guild_id,)
        )
        return row or {
            "guild_id": guild_id,
            "channel_id": None,
            "embed_data": None,
            "enabled": 0,
        }

    def set_welcome_config(self, guild_id: int, **kwargs) -> None:
        self._upsert_config("welcome_config", guild_id, **kwargs)

    # ── Boosts ────────────────────────────────────────────────────────────────
    def get_boost_config(self, guild_id: int) -> Dict:
        row = self._fetchone(
            "SELECT * FROM boost_config WHERE guild_id = ?", (guild_id,)
        )
        return row or {
            "guild_id": guild_id,
            "channel_id": None,
            "embed_data": None,
            "gif_url": None,
            "enabled": 0,
        }

    def set_boost_config(self, guild_id: int, **kwargs) -> None:
        self._upsert_config("boost_config", guild_id, **kwargs)

    # ── Suggestions ───────────────────────────────────────────────────────────
    def get_suggestions_config(self, guild_id: int) -> Dict:
        row = self._fetchone(
            "SELECT * FROM suggestions_config WHERE guild_id = ?", (guild_id,)
        )
        return row or {
            "guild_id": guild_id,
            "submit_channel_id": None,
            "review_channel_id": None,
            "public_channel_id": None,
        }

    def set_suggestions_config(self, guild_id: int, **kwargs) -> None:
        self._upsert_config("suggestions_config", guild_id, **kwargs)

    def create_suggestion(self, guild_id: int, user_id: int, content: str) -> int:
        ops = [
            (
                "INSERT INTO suggestions (guild_id, user_id, content, created_at) VALUES (?, ?, ?, ?)",
                (guild_id, user_id, content, datetime.now(timezone.utc).isoformat()),
            )
        ]
        self._executemany(ops)
        row = self._fetchone(
            "SELECT id FROM suggestions WHERE guild_id = ? AND user_id = ? ORDER BY id DESC LIMIT 1",
            (guild_id, user_id),
        )
        return row["id"] if row else 0

    def get_suggestion(self, suggestion_id: int) -> Optional[Dict]:
        return self._fetchone(
            "SELECT * FROM suggestions WHERE id = ?", (suggestion_id,)
        )

    def update_suggestion(self, suggestion_id: int, **kwargs) -> None:
        if not kwargs:
            return
        invalid = set(kwargs) - VALID_SUGGESTION_COLUMNS
        if invalid:
            raise ValueError(f"Columnas inválidas en suggestions: {invalid}")
        ops = [
            (f"UPDATE suggestions SET {col} = ? WHERE id = ?", (val, suggestion_id))
            for col, val in kwargs.items()
        ]
        self._executemany(ops)

    # ── Suggestion votes (tracking por usuario, idempotente) ──────────────────
    def get_user_vote(self, suggestion_id: int, user_id: int) -> int:
        """Retorna 1, -1 o 0 según el voto del usuario."""
        row = self._fetchone(
            "SELECT vote FROM suggestion_votes WHERE suggestion_id = ? AND user_id = ?",
            (suggestion_id, user_id),
        )
        return int(row["vote"]) if row else 0

    def cast_vote(self, suggestion_id: int, user_id: int, vote: int) -> Dict:
        """
        Aplica un voto (vote ∈ {-1, +1}). Si el usuario re-vota igual → quita.
        Devuelve los nuevos counts {upvotes, downvotes}.
        """
        if vote not in (-1, 1):
            raise ValueError("vote debe ser 1 o -1")

        prev = self.get_user_vote(suggestion_id, user_id)
        if prev == vote:
            self._execute(
                "DELETE FROM suggestion_votes WHERE suggestion_id = ? AND user_id = ?",
                (suggestion_id, user_id),
            )
        elif prev == 0:
            if self.db_type == "sqlite":
                sql = "INSERT OR REPLACE INTO suggestion_votes (suggestion_id, user_id, vote) VALUES (?, ?, ?)"
            elif self.db_type == "postgresql":
                sql = (
                    "INSERT INTO suggestion_votes (suggestion_id, user_id, vote) VALUES (?, ?, ?) "
                    "ON CONFLICT (suggestion_id, user_id) DO UPDATE SET vote = EXCLUDED.vote"
                )
            else:
                sql = (
                    "INSERT INTO suggestion_votes (suggestion_id, user_id, vote) VALUES (?, ?, ?) "
                    "ON DUPLICATE KEY UPDATE vote = VALUES(vote)"
                )
            self._execute(sql, (suggestion_id, user_id, vote))
        else:
            self._execute(
                "UPDATE suggestion_votes SET vote = ? WHERE suggestion_id = ? AND user_id = ?",
                (vote, suggestion_id, user_id),
            )

        ups = self._fetchone(
            "SELECT COUNT(*) AS c FROM suggestion_votes WHERE suggestion_id = ? AND vote = 1",
            (suggestion_id,),
        )
        downs = self._fetchone(
            "SELECT COUNT(*) AS c FROM suggestion_votes WHERE suggestion_id = ? AND vote = -1",
            (suggestion_id,),
        )
        upvotes = int(ups["c"]) if ups else 0
        downvotes = int(downs["c"]) if downs else 0
        self._executemany([
            ("UPDATE suggestions SET upvotes = ? WHERE id = ?", (upvotes, suggestion_id)),
            ("UPDATE suggestions SET downvotes = ? WHERE id = ?", (downvotes, suggestion_id)),
        ])
        return {"upvotes": upvotes, "downvotes": downvotes}

    def get_last_user_suggestion_ts(self, guild_id: int, user_id: int) -> Optional[str]:
        """Timestamp ISO de la última sugerencia del usuario (para cooldown)."""
        row = self._fetchone(
            "SELECT created_at FROM suggestions WHERE guild_id = ? AND user_id = ? "
            "ORDER BY id DESC LIMIT 1",
            (guild_id, user_id),
        )
        return row["created_at"] if row else None

    # ── Giveaways ─────────────────────────────────────────────────────────────
    def create_giveaway(
        self,
        guild_id: int,
        channel_id: int,
        message_id: int,
        prize: str,
        end_time: int,
        winners_count: int,
        req_roles: str,
        deny_roles: str,
    ) -> None:
        self._execute(
            "INSERT INTO giveaways (guild_id, channel_id, message_id, prize, end_time, winners_count, req_roles, deny_roles, participants) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                guild_id,
                channel_id,
                message_id,
                prize,
                end_time,
                winners_count,
                req_roles,
                deny_roles,
                "[]",
            ),
        )

    def get_giveaway(self, message_id: int) -> Optional[Dict]:
        return self._fetchone(
            "SELECT * FROM giveaways WHERE message_id = ?", (message_id,)
        )

    def get_active_giveaways(self) -> List[Dict]:
        return self._fetchall("SELECT * FROM giveaways WHERE ended = 0", ())

    def update_giveaway(self, message_id: int, **kwargs) -> None:
        if not kwargs:
            return
        invalid = set(kwargs) - VALID_GIVEAWAY_COLUMNS
        if invalid:
            raise ValueError(f"Columnas inválidas en giveaways: {invalid}")
        ops = [
            (f"UPDATE giveaways SET {col} = ? WHERE message_id = ?", (val, message_id))
            for col, val in kwargs.items()
        ]
        self._executemany(ops)

    # ── AutoRoles ─────────────────────────────────────────────────────────────
    def set_autorole(
        self, message_id: int, guild_id: int, channel_id: int, mapping_data: str
    ) -> None:
        ops = []
        if self.db_type == "sqlite":
            ops.append(
                (
                    "INSERT OR REPLACE INTO autoroles (message_id, guild_id, channel_id, mapping_data) VALUES (?, ?, ?, ?)",
                    (message_id, guild_id, channel_id, mapping_data),
                )
            )
        elif self.db_type == "postgresql":
            ops.append(
                (
                    "INSERT INTO autoroles (message_id, guild_id, channel_id, mapping_data) VALUES (?, ?, ?, ?) ON CONFLICT (message_id) DO UPDATE SET mapping_data = EXCLUDED.mapping_data",
                    (message_id, guild_id, channel_id, mapping_data),
                )
            )
        else:
            ops.append(
                (
                    "INSERT INTO autoroles (message_id, guild_id, channel_id, mapping_data) VALUES (?, ?, ?, ?) ON DUPLICATE KEY UPDATE mapping_data=VALUES(mapping_data)",
                    (message_id, guild_id, channel_id, mapping_data),
                )
            )
        self._executemany(ops)

    def get_autorole(self, message_id: int) -> Optional[Dict]:
        return self._fetchone(
            "SELECT * FROM autoroles WHERE message_id = ?", (message_id,)
        )

    def get_guild_autoroles(self, guild_id: int) -> List[Dict]:
        return self._fetchall("SELECT * FROM autoroles WHERE guild_id = ?", (guild_id,))

    def delete_autorole(self, message_id: int) -> None:
        self._execute("DELETE FROM autoroles WHERE message_id = ?", (message_id,))

    # ── Join Autoroles (rol al unirse al servidor) ────────────────────────────
    def get_join_autoroles(self, guild_id: int) -> List[Dict]:
        """Lista de roles que se asignan automáticamente cuando un usuario entra."""
        return self._fetchall(
            "SELECT role_id, created_at FROM join_autoroles WHERE guild_id = ? ORDER BY created_at",
            (guild_id,),
        )

    def add_join_autorole(self, guild_id: int, role_id: int) -> None:
        """Agrega un rol a la lista de auto-asignación al unirse. Idempotente."""
        if self.db_type == "sqlite":
            sql = "INSERT OR IGNORE INTO join_autoroles (guild_id, role_id) VALUES (?, ?)"
        elif self.db_type == "postgresql":
            sql = "INSERT INTO join_autoroles (guild_id, role_id) VALUES (?, ?) ON CONFLICT DO NOTHING"
        else:
            sql = "INSERT IGNORE INTO join_autoroles (guild_id, role_id) VALUES (?, ?)"
        self._execute(sql, (guild_id, role_id))

    def remove_join_autorole(self, guild_id: int, role_id: int) -> None:
        """Quita un rol de la lista de auto-asignación al unirse."""
        self._execute(
            "DELETE FROM join_autoroles WHERE guild_id = ? AND role_id = ?",
            (guild_id, role_id),
        )

    # ── Lofi Config ───────────────────────────────────────────────────────────
    def get_lofi_config(self, guild_id: int) -> Dict:
        row = self._fetchone(
            "SELECT * FROM lofi_config WHERE guild_id = ?", (guild_id,)
        )
        if row:
            # Defaults para columnas añadidas en migraciones (BBDDs viejas pueden no tenerlas).
            row.setdefault("auto_reconnect", 1)
            row.setdefault("pause_on_empty", 0)
            return row
        return {
            "guild_id": guild_id,
            "channel_id": None,
            "volume": 100,
            "enabled": 0,
            "stream_url": None,
            "station_name": "Lofi Radio 24/7",
            "auto_reconnect": 1,
            "pause_on_empty": 0,
        }

    def set_lofi_config(self, guild_id: int, **kwargs) -> None:
        self._upsert_config("lofi_config", guild_id, **kwargs)

    # ── Bot Stats (Web Panel IPC) ─────────────────────────────────────────────
    def update_bot_stats(
        self,
        members_online: int,
        total_members: int,
        open_tickets: int,
        uptime_seconds: int,
    ) -> None:
        ops = []
        now = datetime.now(timezone.utc).isoformat()
        if self.db_type == "sqlite":
            ops.append(("INSERT OR IGNORE INTO bot_stats (id) VALUES (1)", ()))
        elif self.db_type == "postgresql":
            ops.append(
                (
                    "INSERT INTO bot_stats (id) VALUES (1) ON CONFLICT (id) DO NOTHING",
                    (),
                )
            )
        else:
            ops.append(("INSERT IGNORE INTO bot_stats (id) VALUES (1)", ()))

        ops.append(
            (
                "UPDATE bot_stats SET members_online = ?, total_members = ?, open_tickets = ?, uptime_seconds = ?, last_updated = ? WHERE id = 1",
                (members_online, total_members, open_tickets, uptime_seconds, now),
            )
        )
        self._executemany(ops)

    def get_bot_stats(self) -> Dict:
        row = self._fetchone("SELECT * FROM bot_stats WHERE id = 1", ())
        return row or {
            "members_online": 0,
            "total_members": 0,
            "open_tickets": 0,
            "uptime_seconds": 0,
            "last_updated": "",
        }

    # ── Tickets ───────────────────────────────────────────────────────────────
    def get_ticket_config(self, guild_id: int) -> Dict:
        row = self._fetchone(
            "SELECT * FROM ticket_config WHERE guild_id = ?", (guild_id,)
        )
        return row or {
            "guild_id": guild_id,
            "panel_channel_id": None,
            "category_id": None,
            "log_channel_id": None,
            "allowed_roles": "[]",
            "immune_roles": "[]",
        }

    def set_ticket_config(self, guild_id: int, **kwargs) -> None:
        self._upsert_config("ticket_config", guild_id, **kwargs)

    def get_ticket_categories(self, guild_id: int) -> List[Dict]:
        return self._fetchall(
            "SELECT * FROM ticket_categories WHERE guild_id = ?", (guild_id,)
        )

    def add_ticket_category(
        self,
        guild_id: int,
        name: str,
        emoji: str,
        questions: str,
        close_reasons: str,
        welcome_embed_data: Optional[str] = None,
        description: Optional[str] = None,
        welcome_embed_template_key: Optional[str] = None,
        staff_role_id: Optional[int] = None,
    ) -> None:
        self._execute(
            "INSERT INTO ticket_categories (guild_id, name, emoji, description, "
            "questions, close_reasons, welcome_embed_data, welcome_embed_template_key, "
            "staff_role_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                guild_id, name, emoji, description,
                questions, close_reasons, welcome_embed_data,
                welcome_embed_template_key, staff_role_id,
            ),
        )

    def update_ticket_category(self, category_id: int, **kwargs) -> None:
        """Actualiza campos de una categoría. Allowlist por seguridad."""
        allowed = {
            "name", "emoji", "description", "questions", "close_reasons",
            "welcome_embed_data", "welcome_embed_template_key", "staff_role_id",
        }
        invalid = set(kwargs) - allowed
        if invalid:
            raise ValueError(f"Campos inválidos en update_ticket_category: {invalid}")
        if not kwargs:
            return
        ops = [
            (f"UPDATE ticket_categories SET {col} = ? WHERE id = ?", (val, category_id))
            for col, val in kwargs.items()
        ]
        self._executemany(ops)

    def delete_ticket_category(self, category_id: int) -> None:
        self._execute("DELETE FROM ticket_categories WHERE id = ?", (category_id,))

    # ── Ticket Template Embeds (pool reutilizable) ────────────────────────────
    #
    # `template_key` agrupa plantillas por uso (panel_select, panel_inside,
    # msg_open, msg_close, custom_<x>). UNIQUE(guild_id, template_key) → upsert
    # por key. Usar `name` para distinguir plantillas custom.

    def list_ticket_templates(self, guild_id: int) -> List[Dict]:
        return self._fetchall(
            "SELECT * FROM ticket_template_embeds WHERE guild_id = ? ORDER BY created_at DESC",
            (guild_id,),
        )

    def get_ticket_template(self, guild_id: int, template_key: str) -> Optional[Dict]:
        row = self._fetchone(
            "SELECT * FROM ticket_template_embeds WHERE guild_id = ? AND template_key = ?",
            (guild_id, template_key),
        )
        return dict(row) if row else None

    def upsert_ticket_template(
        self,
        guild_id: int,
        template_key: str,
        embed_data: str,
        name: Optional[str] = None,
    ) -> None:
        """Crea o reemplaza la plantilla identificada por (guild_id, template_key)."""
        now = datetime.now(timezone.utc).isoformat()
        if self.db_type == "sqlite":
            self._execute(
                "INSERT INTO ticket_template_embeds "
                "(guild_id, template_key, name, embed_data, created_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(guild_id, template_key) DO UPDATE SET "
                "embed_data = excluded.embed_data, name = excluded.name",
                (guild_id, template_key, name, embed_data, now),
            )
        elif self.db_type == "postgresql":
            self._execute(
                "INSERT INTO ticket_template_embeds "
                "(guild_id, template_key, name, embed_data, created_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT (guild_id, template_key) DO UPDATE SET "
                "embed_data = EXCLUDED.embed_data, name = EXCLUDED.name",
                (guild_id, template_key, name, embed_data, now),
            )
        else:  # mariadb
            self._execute(
                "INSERT INTO ticket_template_embeds "
                "(guild_id, template_key, name, embed_data, created_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON DUPLICATE KEY UPDATE "
                "embed_data = VALUES(embed_data), name = VALUES(name)",
                (guild_id, template_key, name, embed_data, now),
            )

    def delete_ticket_template(self, guild_id: int, template_key: str) -> None:
        self._execute(
            "DELETE FROM ticket_template_embeds WHERE guild_id = ? AND template_key = ?",
            (guild_id, template_key),
        )

    def create_ticket(self, guild_id: int, user_id: int, category_name: str) -> Dict:
        # Generate global number
        row = self._fetchone(
            "SELECT MAX(global_number) as max_num FROM tickets WHERE guild_id = ?",
            (guild_id,),
        )
        global_num = (row["max_num"] or 0) + 1 if row else 1

        now = datetime.now(timezone.utc).isoformat()
        self._execute(
            "INSERT INTO tickets (global_number, guild_id, user_id, category_name, created_at) VALUES (?, ?, ?, ?, ?)",
            (global_num, guild_id, user_id, category_name, now),
        )

        last = self._fetchone(
            "SELECT * FROM tickets WHERE guild_id = ? AND user_id = ? ORDER BY id DESC LIMIT 1",
            (guild_id, user_id),
        )
        return last  # type: ignore

    def get_ticket_by_channel(self, channel_id: int) -> Optional[Dict]:
        return self._fetchone(
            "SELECT * FROM tickets WHERE channel_id = ?", (channel_id,)
        )

    def get_ticket(self, ticket_id: int) -> Optional[Dict]:
        return self._fetchone("SELECT * FROM tickets WHERE id = ?", (ticket_id,))

    def update_ticket(self, ticket_id: int, **kwargs) -> None:
        if not kwargs:
            return
        invalid = set(kwargs) - VALID_TICKET_COLUMNS
        if invalid:
            raise ValueError(f"Columnas inválidas en tickets: {invalid}")
        ops = [
            (f"UPDATE tickets SET {col} = ? WHERE id = ?", (val, ticket_id))
            for col, val in kwargs.items()
        ]
        self._executemany(ops)

    def count_open_tickets_by_user(self, guild_id: int, user_id: int) -> int:
        row = self._fetchone(
            "SELECT COUNT(*) as cnt FROM tickets WHERE guild_id = ? AND user_id = ? AND status = 'OPEN'",
            (guild_id, user_id),
        )
        return int(row["cnt"]) if row else 0

    def get_last_ticket_time(self, guild_id: int, user_id: int) -> Optional[str]:
        row = self._fetchone(
            "SELECT MAX(created_at) as last FROM tickets WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        return row["last"] if row else None

    # ── Tags ──────────────────────────────────────────────────────────────────

    def get_tag(self, guild_id: int, name: str) -> Optional[Dict]:
        return self._fetchone(
            "SELECT * FROM tags WHERE guild_id = ? AND name = ?",
            (guild_id, name.lower()),
        )

    def get_all_tags(self, guild_id: int) -> List[Dict]:
        return self._fetchall(
            "SELECT * FROM tags WHERE guild_id = ? ORDER BY name ASC", (guild_id,)
        )

    def create_tag(
        self, guild_id: int, name: str, content: str, creator_id: int
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self._execute(
            "INSERT INTO tags (guild_id, name, content, creator_id, created_at) VALUES (?, ?, ?, ?, ?)",
            (guild_id, name.lower(), content, creator_id, now),
        )

    def update_tag(self, guild_id: int, name: str, content: str) -> None:
        self._execute(
            "UPDATE tags SET content = ? WHERE guild_id = ? AND name = ?",
            (content, guild_id, name.lower()),
        )

    def delete_tag(self, guild_id: int, name: str) -> None:
        self._execute(
            "DELETE FROM tags WHERE guild_id = ? AND name = ?", (guild_id, name.lower())
        )

    def increment_tag_uses(self, guild_id: int, name: str) -> None:
        self._execute(
            "UPDATE tags SET uses = uses + 1 WHERE guild_id = ? AND name = ?",
            (guild_id, name.lower()),
        )

    # ── Reports ───────────────────────────────────────────────────────────────

    def create_report(
        self, guild_id: int, reporter_id: int, reported_user_id: int, reason: str
    ) -> int:
        now = datetime.now(timezone.utc).isoformat()
        self._execute(
            "INSERT INTO reports (guild_id, reporter_id, reported_user_id, reason, created_at) VALUES (?, ?, ?, ?, ?)",
            (guild_id, reporter_id, reported_user_id, reason, now),
        )
        row = self._fetchone(
            "SELECT id FROM reports WHERE guild_id = ? AND reporter_id = ? ORDER BY id DESC LIMIT 1",
            (guild_id, reporter_id),
        )
        return int(row["id"]) if row else 0

    def get_reports(self, guild_id: int, status: str = None) -> List[Dict]:
        if status:
            return self._fetchall(
                "SELECT * FROM reports WHERE guild_id = ? AND status = ? ORDER BY id DESC",
                (guild_id, status),
            )
        return self._fetchall(
            "SELECT * FROM reports WHERE guild_id = ? ORDER BY id DESC", (guild_id,)
        )

    def get_report(self, report_id: int) -> Optional[Dict]:
        """Obtiene un reporte por su ID."""
        return self._fetchone("SELECT * FROM reports WHERE id = ?", (report_id,))

    def update_report(self, report_id: int, **kwargs) -> None:
        valid = frozenset({"status", "ticket_id"})
        invalid = set(kwargs) - valid
        if invalid:
            raise ValueError(f"Columnas inválidas en reports: {invalid}")
        ops = [
            (f"UPDATE reports SET {col} = ? WHERE id = ?", (val, report_id))
            for col, val in kwargs.items()
        ]
        self._executemany(ops)

    # ── Scheduled Messages ────────────────────────────────────────────────────

    def create_schedule(
        self,
        guild_id: int,
        name: str,
        channel_id: int,
        content: str,
        interval_seconds: int,
        created_by: int,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self._execute(
            "INSERT INTO scheduled_messages (guild_id, name, channel_id, content, interval_seconds, created_by, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (guild_id, name, channel_id, content, interval_seconds, created_by, now),
        )

    def get_schedules(self, guild_id: int) -> List[Dict]:
        return self._fetchall(
            "SELECT * FROM scheduled_messages WHERE guild_id = ? ORDER BY name ASC",
            (guild_id,),
        )

    def get_all_active_schedules(self) -> List[Dict]:
        return self._fetchall("SELECT * FROM scheduled_messages WHERE enabled = 1", ())

    def update_schedule(self, schedule_id: int, **kwargs) -> None:
        valid = frozenset(
            {"enabled", "channel_id", "content", "interval_seconds", "last_sent"}
        )
        invalid = set(kwargs) - valid
        if invalid:
            raise ValueError(f"Columnas inválidas en scheduled_messages: {invalid}")
        ops = [
            (
                f"UPDATE scheduled_messages SET {col} = ? WHERE id = ?",
                (val, schedule_id),
            )
            for col, val in kwargs.items()
        ]
        self._executemany(ops)

    def delete_schedule(self, guild_id: int, name: str) -> None:
        self._execute(
            "DELETE FROM scheduled_messages WHERE guild_id = ? AND name = ?",
            (guild_id, name),
        )

    def get_schedule_by_name(self, guild_id: int, name: str) -> Optional[Dict]:
        return self._fetchone(
            "SELECT * FROM scheduled_messages WHERE guild_id = ? AND name = ?",
            (guild_id, name),
        )

    # ── Levels / XP ───────────────────────────────────────────────────────────

    def get_user_level(self, user_id: int, guild_id: int) -> Dict:
        row = self._fetchone(
            "SELECT * FROM user_levels WHERE user_id = ? AND guild_id = ?",
            (user_id, guild_id),
        )
        return row or {
            "user_id": user_id,
            "guild_id": guild_id,
            "xp": 0,
            "level": 0,
            "message_count": 0,
        }

    @staticmethod
    def _xp_for_level(n: int) -> int:
        """XP total acumulado necesario para alcanzar el nivel n (fórmula MEE6)."""
        total = 0
        for k in range(1, n + 1):
            total += 5 * k * k + 50 * k + 100
        return total

    @staticmethod
    def _compute_level(total_xp: int) -> int:
        """Calcula el nivel para un XP total dado."""
        level = 0
        needed = 0
        while True:
            needed += 5 * (level + 1) ** 2 + 50 * (level + 1) + 100
            if total_xp < needed:
                break
            level += 1
        return level

    def add_xp(self, user_id: int, guild_id: int, amount: int) -> Dict:
        """Añade XP y devuelve dict con nuevo estado y si hubo level-up."""
        row = self.get_user_level(user_id, guild_id)
        new_xp = int(row["xp"]) + amount
        new_level = self._compute_level(new_xp)
        old_level = int(row["level"])
        leveled_up = new_level > old_level
        new_count = int(row["message_count"]) + 1

        if self.db_type == "sqlite":
            self._execute(
                "INSERT INTO user_levels (user_id, guild_id, xp, level, message_count) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(user_id, guild_id) DO UPDATE SET xp = ?, level = ?, message_count = ?",
                (
                    user_id,
                    guild_id,
                    new_xp,
                    new_level,
                    new_count,
                    new_xp,
                    new_level,
                    new_count,
                ),
            )
        elif self.db_type == "postgresql":
            self._execute(
                "INSERT INTO user_levels (user_id, guild_id, xp, level, message_count) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT (user_id, guild_id) DO UPDATE SET xp = EXCLUDED.xp, level = EXCLUDED.level, message_count = EXCLUDED.message_count",
                (user_id, guild_id, new_xp, new_level, new_count),
            )
        else:
            self._execute(
                "INSERT INTO user_levels (user_id, guild_id, xp, level, message_count) VALUES (?, ?, ?, ?, ?) "
                "ON DUPLICATE KEY UPDATE xp = VALUES(xp), level = VALUES(level), message_count = VALUES(message_count)",
                (user_id, guild_id, new_xp, new_level, new_count),
            )
        return {
            "xp": new_xp,
            "level": new_level,
            "old_level": old_level,
            "leveled_up": leveled_up,
        }

    def reset_user_level(self, user_id: int, guild_id: int) -> None:
        self._execute(
            "UPDATE user_levels SET xp = 0, level = 0, message_count = 0 WHERE user_id = ? AND guild_id = ?",
            (user_id, guild_id),
        )

    def get_leaderboard(self, guild_id: int, limit: int = 10) -> List[Dict]:
        return self._fetchall(
            "SELECT user_id, xp, level, message_count, "
            "ROW_NUMBER() OVER (ORDER BY xp DESC) as position "
            "FROM user_levels WHERE guild_id = ? ORDER BY xp DESC LIMIT ?",
            (guild_id, limit),
        )

    def get_xp_config(self, guild_id: int) -> Dict:
        row = self._fetchone("SELECT * FROM xp_config WHERE guild_id = ?", (guild_id,))
        return row or {
            "guild_id": guild_id,
            "enabled": 0,
            "xp_min": 15,
            "xp_max": 25,
            "cooldown_seconds": 60,
            "ignored_channels": "[]",
            "channel_multipliers": "{}",
            "announcement_channel_id": None,
            "announcement_message": None,
            "stack_rewards": 1,
        }

    def set_xp_config(self, guild_id: int, **kwargs) -> None:
        self._upsert_config("xp_config", guild_id, **kwargs)

    def get_level_rewards(self, guild_id: int) -> List[Dict]:
        return self._fetchall(
            "SELECT * FROM level_rewards WHERE guild_id = ? ORDER BY level ASC",
            (guild_id,),
        )

    def set_level_reward(self, guild_id: int, level: int, role_id: int) -> None:
        if self.db_type == "sqlite":
            self._execute(
                "INSERT INTO level_rewards (guild_id, level, role_id) VALUES (?, ?, ?) "
                "ON CONFLICT(guild_id, level) DO UPDATE SET role_id = ?",
                (guild_id, level, role_id, role_id),
            )
        elif self.db_type == "postgresql":
            self._execute(
                "INSERT INTO level_rewards (guild_id, level, role_id) VALUES (?, ?, ?) "
                "ON CONFLICT (guild_id, level) DO UPDATE SET role_id = EXCLUDED.role_id",
                (guild_id, level, role_id),
            )
        else:
            self._execute(
                "INSERT INTO level_rewards (guild_id, level, role_id) VALUES (?, ?, ?) "
                "ON DUPLICATE KEY UPDATE role_id = VALUES(role_id)",
                (guild_id, level, role_id),
            )

    def delete_level_reward(self, guild_id: int, level: int) -> None:
        self._execute(
            "DELETE FROM level_rewards WHERE guild_id = ? AND level = ?",
            (guild_id, level),
        )

    def get_level_reward(self, guild_id: int, level: int) -> Optional[Dict]:
        return self._fetchone(
            "SELECT * FROM level_rewards WHERE guild_id = ? AND level = ?",
            (guild_id, level),
        )

    # ── Web Panel helpers ─────────────────────────────────────────────────────

    def get_user_rank(self, user_id: int, guild_id: int) -> int:
        """Retorna la posición del usuario en el leaderboard (1-indexed). 0 si no tiene XP."""
        row = self._fetchone(
            "SELECT COUNT(*) + 1 AS rank FROM user_levels "
            "WHERE guild_id = ? AND xp > (SELECT COALESCE(xp, 0) FROM user_levels WHERE user_id = ? AND guild_id = ?)",
            (guild_id, user_id, guild_id),
        )
        if row:
            return int(row["rank"])
        return 0

    def count_all_open_tickets(self) -> int:
        """Cuenta todos los tickets abiertos en todos los servidores."""
        row = self._fetchone(
            "SELECT COUNT(*) AS cnt FROM tickets WHERE status = 'OPEN'", ()
        )
        return int(row["cnt"]) if row else 0

    def count_open_tickets_by_guild(self, guild_id: int) -> int:
        """Cuenta tickets abiertos de un servidor específico."""
        row = self._fetchone(
            "SELECT COUNT(*) AS cnt FROM tickets WHERE guild_id = ? AND status = 'OPEN'",
            (guild_id,),
        )
        return int(row["cnt"]) if row else 0

    def get_all_tickets(
        self,
        guild_id: int,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict]:
        """Retorna tickets de un servidor con paginación y filtro opcional."""
        if status:
            return self._fetchall(
                "SELECT * FROM tickets WHERE guild_id = ? AND status = ? "
                "ORDER BY id DESC LIMIT ? OFFSET ?",
                (guild_id, status, limit, offset),
            )
        return self._fetchall(
            "SELECT * FROM tickets WHERE guild_id = ? ORDER BY id DESC LIMIT ? OFFSET ?",
            (guild_id, limit, offset),
        )

    def get_guild_giveaways(
        self, guild_id: int, active_only: bool = True
    ) -> List[Dict]:
        """Retorna sorteos de un servidor, opcionalmente solo activos."""
        if active_only:
            return self._fetchall(
                "SELECT * FROM giveaways WHERE guild_id = ? AND ended = 0 ORDER BY end_time ASC",
                (guild_id,),
            )
        return self._fetchall(
            "SELECT * FROM giveaways WHERE guild_id = ? ORDER BY id DESC",
            (guild_id,),
        )

    def get_mod_actions(
        self, guild_id: int, limit: int = 50, offset: int = 0
    ) -> List[Dict]:
        """Retorna acciones de moderación de un servidor con paginación."""
        return self._fetchall(
            "SELECT * FROM mod_actions WHERE guild_id = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (guild_id, limit, offset),
        )

    def get_users_with_warns(self, guild_id: int) -> List[Dict]:
        """Retorna usuarios con warns activos en un servidor."""
        return self._fetchall(
            "SELECT * FROM user_records WHERE guild_id = ? AND warns > 0 ORDER BY warns DESC",
            (guild_id,),
        )

    # ── Custom Commands ───────────────────────────────────────────────────────

    def get_custom_commands(self, guild_id: int) -> List[Dict]:
        """Retorna todos los custom commands de un servidor."""
        return self._fetchall(
            "SELECT * FROM custom_commands WHERE guild_id = ? ORDER BY name ASC",
            (guild_id,),
        )

    def get_custom_command(self, guild_id: int, name: str) -> Optional[Dict]:
        """Obtiene un custom command por nombre."""
        return self._fetchone(
            "SELECT * FROM custom_commands WHERE guild_id = ? AND name = ?",
            (guild_id, name.lower()),
        )

    def get_custom_command_by_id(self, cc_id: int) -> Optional[Dict]:
        """Obtiene un custom command por su ID."""
        return self._fetchone("SELECT * FROM custom_commands WHERE id = ?", (cc_id,))

    def get_enabled_custom_commands(
        self, guild_id: int, trigger_type: str = None
    ) -> List[Dict]:
        """Retorna CCs habilitados, opcionalmente filtrados por tipo de trigger."""
        if trigger_type:
            return self._fetchall(
                "SELECT * FROM custom_commands WHERE guild_id = ? AND enabled = 1 AND trigger_type = ?",
                (guild_id, trigger_type),
            )
        return self._fetchall(
            "SELECT * FROM custom_commands WHERE guild_id = ? AND enabled = 1",
            (guild_id,),
        )

    def create_custom_command(
        self,
        guild_id: int,
        name: str,
        trigger_type: str,
        trigger_value: str,
        conditions: str,
        actions: str,
        creator_id: int,
    ) -> Optional[Dict]:
        """Crea un nuevo custom command y retorna el registro."""
        now = datetime.now(timezone.utc).isoformat()
        self._execute(
            "INSERT INTO custom_commands (guild_id, name, trigger_type, trigger_value, "
            "conditions, actions, creator_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                guild_id,
                name.lower(),
                trigger_type,
                trigger_value,
                conditions,
                actions,
                creator_id,
                now,
            ),
        )
        return self.get_custom_command(guild_id, name)

    def update_custom_command(self, guild_id: int, name: str, **kwargs) -> None:
        """Actualiza campos de un custom command."""
        valid = frozenset(
            {
                "enabled",
                "trigger_type",
                "trigger_value",
                "conditions",
                "actions",
                "uses",
                "last_used",
            }
        )
        invalid = set(kwargs) - valid
        if invalid:
            raise ValueError(f"Columnas inválidas en custom_commands: {invalid}")
        ops = [
            (
                f"UPDATE custom_commands SET {col} = ? WHERE guild_id = ? AND name = ?",
                (val, guild_id, name.lower()),
            )
            for col, val in kwargs.items()
        ]
        self._executemany(ops)

    def delete_custom_command(self, guild_id: int, name: str) -> None:
        """Elimina un custom command."""
        self._execute(
            "DELETE FROM custom_commands WHERE guild_id = ? AND name = ?",
            (guild_id, name.lower()),
        )

    def increment_cc_uses(self, guild_id: int, name: str) -> None:
        """Incrementa el contador de usos y actualiza last_used."""
        now = datetime.now(timezone.utc).isoformat()
        self._execute(
            "UPDATE custom_commands SET uses = uses + 1, last_used = ? WHERE guild_id = ? AND name = ?",
            (now, guild_id, name.lower()),
        )

    # ── CC Variables (persistentes) ───────────────────────────────────────────

    def get_cc_variable(
        self, guild_id: int, key: str, scope: str = "guild"
    ) -> Optional[str]:
        """Obtiene el valor de una variable. Retorna None si no existe."""
        row = self._fetchone(
            "SELECT value FROM cc_variables WHERE guild_id = ? AND key = ? AND scope = ?",
            (guild_id, key, scope),
        )
        return row["value"] if row else None

    def set_cc_variable(
        self, guild_id: int, key: str, value: str, scope: str = "guild"
    ) -> None:
        """Crea o actualiza una variable persistente."""
        if self.db_type == "sqlite":
            self._execute(
                "INSERT INTO cc_variables (guild_id, key, value, scope) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(guild_id, key, scope) DO UPDATE SET value = ?",
                (guild_id, key, value, scope, value),
            )
        elif self.db_type == "postgresql":
            self._execute(
                "INSERT INTO cc_variables (guild_id, key, value, scope) VALUES (?, ?, ?, ?) "
                "ON CONFLICT (guild_id, key, scope) DO UPDATE SET value = EXCLUDED.value",
                (guild_id, key, value, scope),
            )
        else:
            self._execute(
                "INSERT INTO cc_variables (guild_id, `key`, value, scope) VALUES (?, ?, ?, ?) "
                "ON DUPLICATE KEY UPDATE value = VALUES(value)",
                (guild_id, key, value, scope),
            )

    def get_all_cc_variables(self, guild_id: int) -> List[Dict]:
        """Retorna todas las variables de un servidor."""
        return self._fetchall(
            "SELECT * FROM cc_variables WHERE guild_id = ? ORDER BY key ASC",
            (guild_id,),
        )

    def delete_cc_variable(self, guild_id: int, key: str, scope: str = "guild") -> None:
        """Elimina una variable persistente."""
        self._execute(
            "DELETE FROM cc_variables WHERE guild_id = ? AND key = ? AND scope = ?",
            (guild_id, key, scope),
        )

    def increment_cc_variable(
        self, guild_id: int, key: str, amount: int = 1, scope: str = "guild"
    ) -> str:
        """Incrementa una variable numérica y retorna el nuevo valor."""
        current = self.get_cc_variable(guild_id, key, scope)
        try:
            new_val = str(int(current or "0") + amount)
        except ValueError:
            new_val = str(amount)
        self.set_cc_variable(guild_id, key, new_val, scope)
        return new_val

    # ═══════════════════════════════════════════════════════════════════════════
    # VOICE GEN — Generador dinámico de canales de voz (Join To Create)
    # ═══════════════════════════════════════════════════════════════════════════

    def _ensure_voice_gen_tables(self) -> None:
        """
        Crea las tablas del Generador de VCs si no existen y añade columnas
        nuevas a tablas viejas vía ensure_column (idempotente).
        """
        self._execute("""
            CREATE TABLE IF NOT EXISTS voice_gen_config (
                guild_id             INTEGER PRIMARY KEY,
                generator_channel_id INTEGER,
                category_id          INTEGER,
                panel_channel_id     INTEGER,
                name_template        TEXT    DEFAULT '{username}''s VC',
                default_limit        INTEGER DEFAULT 0,
                enabled              INTEGER DEFAULT 0,
                panel_title          TEXT,
                panel_description    TEXT,
                panel_color          TEXT,
                auto_send_panel      INTEGER DEFAULT 1
            )
        """)
        # Migración no destructiva para BBDDs creadas antes de Fase 6.
        try:
            self.ensure_column("voice_gen_config", "panel_title", "TEXT")
            self.ensure_column("voice_gen_config", "panel_description", "TEXT")
            self.ensure_column("voice_gen_config", "panel_color", "TEXT")
            self.ensure_column("voice_gen_config", "auto_send_panel", "INTEGER DEFAULT 1")
        except Exception as e:
            logger.warning("ensure_column en voice_gen_config falló: %s", e)
        self._execute("""
            CREATE TABLE IF NOT EXISTS voice_gen_channels (
                channel_id   INTEGER PRIMARY KEY,
                guild_id     INTEGER NOT NULL,
                owner_id     INTEGER NOT NULL,
                created_at   INTEGER DEFAULT (strftime('%s', 'now'))
            )
        """)

    def get_voice_gen_config(self, guild_id: int) -> Dict:
        """Retorna la configuración del generador de voz de un servidor."""
        self._ensure_voice_gen_tables()
        row = self._fetchone(
            "SELECT * FROM voice_gen_config WHERE guild_id = ?", (guild_id,)
        )
        return (
            dict(row)
            if row
            else {
                "guild_id": guild_id,
                "generator_channel_id": None,
                "category_id": None,
                "panel_channel_id": None,
                "name_template": "{username}'s VC",
                "default_limit": 0,
                "enabled": 0,
            }
        )

    def set_voice_gen_config(self, guild_id: int, **kwargs) -> None:
        """Crea o actualiza la configuración del generador de voz."""
        self._ensure_voice_gen_tables()
        self._upsert_config("voice_gen_config", guild_id, **kwargs)

    def create_voice_gen_channel(
        self, channel_id: int, guild_id: int, owner_id: int
    ) -> None:
        """Registra un canal de voz generado."""
        self._ensure_voice_gen_tables()
        self._execute(
            "INSERT OR REPLACE INTO voice_gen_channels (channel_id, guild_id, owner_id) VALUES (?, ?, ?)",
            (channel_id, guild_id, owner_id),
        )

    def get_voice_gen_channel(self, channel_id: int) -> Optional[Dict]:
        """Retorna un canal generado por su ID, o None si no existe."""
        self._ensure_voice_gen_tables()
        row = self._fetchone(
            "SELECT * FROM voice_gen_channels WHERE channel_id = ?", (channel_id,)
        )
        return dict(row) if row else None

    def get_all_voice_gen_channels(self) -> List[Dict]:
        """Retorna todos los canales generados activos."""
        self._ensure_voice_gen_tables()
        return self._fetchall("SELECT * FROM voice_gen_channels")

    def get_voice_gen_channels_by_guild(self, guild_id: int) -> List[Dict]:
        """Retorna los canales generados de un servidor."""
        self._ensure_voice_gen_tables()
        return self._fetchall(
            "SELECT * FROM voice_gen_channels WHERE guild_id = ? ORDER BY created_at DESC",
            (guild_id,),
        )

    def update_voice_gen_channel_owner(
        self, channel_id: int, new_owner_id: int
    ) -> None:
        """Cambia el dueño de un canal generado."""
        self._ensure_voice_gen_tables()
        self._execute(
            "UPDATE voice_gen_channels SET owner_id = ? WHERE channel_id = ?",
            (new_owner_id, channel_id),
        )

    def delete_voice_gen_channel(self, channel_id: int) -> None:
        """Elimina el registro de un canal generado."""
        self._ensure_voice_gen_tables()
        self._execute(
            "DELETE FROM voice_gen_channels WHERE channel_id = ?", (channel_id,)
        )

    # ── Invites ───────────────────────────────────────────────────────────────

    def get_invite_config(self, guild_id: int) -> Dict:
        """Obtiene la configuración de invitaciones de un servidor."""
        row = self._fetchone(
            "SELECT * FROM invite_config WHERE guild_id = ?", (guild_id,)
        )
        return row or {"guild_id": guild_id, "channel_id": None, "enabled": 1}

    def set_invite_config(self, guild_id: int, **kwargs) -> None:
        """Crea o actualiza la configuración de invitaciones."""
        self._upsert_config("invite_config", guild_id, **kwargs)

    def record_invite(
        self, guild_id: int, inviter_id: int, invited_id: int, invite_code: str
    ) -> None:
        """Registra un evento de invitación (quién invitó a quién)."""
        from datetime import datetime, timezone

        try:
            self._execute(
                "INSERT OR REPLACE INTO invite_stats "
                "(guild_id, inviter_id, invited_id, invite_code, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    guild_id,
                    inviter_id,
                    invited_id,
                    invite_code,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
        except Exception:
            pass

    def get_user_invite_count(self, guild_id: int, user_id: int) -> int:
        """Devuelve cuántas personas ha invitado un usuario en este servidor."""
        row = self._fetchone(
            "SELECT COUNT(*) as c FROM invite_stats "
            "WHERE guild_id = ? AND inviter_id = ?",
            (guild_id, user_id),
        )
        return row["c"] if row else 0

    def get_invite_leaderboard(self, guild_id: int, limit: int = 10) -> List[Dict]:
        """Devuelve los top inviters de un servidor ordenados por total de invitaciones."""
        return self._fetchall(
            "SELECT inviter_id, COUNT(*) as total "
            "FROM invite_stats WHERE guild_id = ? "
            "GROUP BY inviter_id ORDER BY total DESC LIMIT ?",
            (guild_id, limit),
        )

    def get_all_suggestions(self, guild_id: int, status: str = None) -> List[Dict]:
        """Devuelve sugerencias de un servidor, opcionalmente filtradas por estado."""
        if status:
            return self._fetchall(
                "SELECT * FROM suggestions WHERE guild_id = ? AND status = ? "
                "ORDER BY created_at DESC",
                (guild_id, status),
            )
        return self._fetchall(
            "SELECT * FROM suggestions WHERE guild_id = ? "
            "ORDER BY created_at DESC LIMIT 50",
            (guild_id,),
        )
