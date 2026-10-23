"""SQLite persistence for the VK conference moderation bot."""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


SCHEMA = r"""
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    first_seen INTEGER NOT NULL,
    message_count INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS chat_state (
    peer_id INTEGER PRIMARY KEY,
    owner_id INTEGER,
    amode INTEGER NOT NULL DEFAULT 0,
    updated_at INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS admins (
    peer_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    level INTEGER NOT NULL CHECK(level BETWEEN 0 AND 4),
    granted_by INTEGER,
    granted_at INTEGER NOT NULL,
    PRIMARY KEY(peer_id, user_id)
);
CREATE TABLE IF NOT EXISTS memberships (
    peer_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    first_join INTEGER,
    last_join INTEGER,
    session_start INTEGER,
    completed_seconds INTEGER NOT NULL DEFAULT 0,
    invited_by INTEGER,
    active INTEGER NOT NULL DEFAULT 0,
    return_pending INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(peer_id, user_id)
);
CREATE TABLE IF NOT EXISTS mutes (
    peer_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    until_ts INTEGER NOT NULL,
    reason TEXT NOT NULL,
    by_user INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    PRIMARY KEY(peer_id, user_id)
);
CREATE TABLE IF NOT EXISTS bans (
    peer_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    until_ts INTEGER,
    permanent INTEGER NOT NULL DEFAULT 0,
    reason TEXT NOT NULL,
    by_user INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    PRIMARY KEY(peer_id, user_id)
);
CREATE TABLE IF NOT EXISTS ban_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    peer_id INTEGER NOT NULL,
    localization_id INTEGER,
    user_id INTEGER NOT NULL,
    actor_id INTEGER NOT NULL,
    action TEXT NOT NULL DEFAULT 'Блокировка',
    duration_text TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    until_ts INTEGER,
    permanent INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS warnings (
    peer_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    strikes INTEGER NOT NULL DEFAULT 0,
    oral_pending INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(peer_id, user_id)
);
CREATE TABLE IF NOT EXISTS warning_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    peer_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    actor_id INTEGER NOT NULL,
    action TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS user_comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    localization_id INTEGER NOT NULL REFERENCES localizations(id) ON DELETE CASCADE,
    peer_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    actor_id INTEGER NOT NULL,
    comment TEXT NOT NULL,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS domains (
    user_id INTEGER NOT NULL,
    domain TEXT NOT NULL COLLATE NOCASE,
    added_by INTEGER NOT NULL,
    added_at INTEGER NOT NULL,
    PRIMARY KEY(user_id, domain)
);
CREATE TABLE IF NOT EXISTS command_rules (
    peer_id INTEGER NOT NULL,
    command TEXT NOT NULL,
    level INTEGER NOT NULL CHECK(level BETWEEN -1 AND 4),
    updated_by INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    PRIMARY KEY(peer_id, command)
);
CREATE TABLE IF NOT EXISTS user_command_grants (
    peer_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    command TEXT NOT NULL,
    granted_by INTEGER NOT NULL,
    granted_at INTEGER NOT NULL,
    PRIMARY KEY(peer_id, user_id, command)
);
CREATE TABLE IF NOT EXISTS localizations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL COLLATE NOCASE UNIQUE,
    main_peer_id INTEGER NOT NULL,
    created_by INTEGER NOT NULL,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS localization_chats (
    localization_id INTEGER NOT NULL REFERENCES localizations(id) ON DELETE CASCADE,
    peer_id INTEGER NOT NULL UNIQUE,
    is_main INTEGER NOT NULL DEFAULT 0,
    joined_at INTEGER NOT NULL,
    public_id INTEGER UNIQUE,
    PRIMARY KEY(localization_id, peer_id)
);
CREATE TABLE IF NOT EXISTS announcements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    localization_id INTEGER NOT NULL REFERENCES localizations(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    created_by INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS announcement_schedules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    announcement_id INTEGER NOT NULL REFERENCES announcements(id) ON DELETE CASCADE,
    localization_id INTEGER NOT NULL REFERENCES localizations(id) ON DELETE CASCADE,
    peer_id INTEGER NOT NULL REFERENCES localization_chats(peer_id) ON DELETE CASCADE,
    weekday INTEGER NOT NULL CHECK(weekday BETWEEN 0 AND 6),
    publish_time TEXT NOT NULL,
    cycle_enabled INTEGER NOT NULL DEFAULT 0,
    enabled INTEGER NOT NULL DEFAULT 1,
    last_sent_date TEXT,
    last_attempt_at INTEGER NOT NULL DEFAULT 0,
    created_by INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    UNIQUE(announcement_id, peer_id)
);
CREATE TABLE IF NOT EXISTS local_bans (
    localization_id INTEGER NOT NULL REFERENCES localizations(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL,
    reason TEXT NOT NULL,
    by_user INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    PRIMARY KEY(localization_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_warning_history_user ON warning_history(peer_id, user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ban_history_user ON ban_history(peer_id, user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ban_history_localization ON ban_history(localization_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_user_comments_target ON user_comments(localization_id, user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_domains_name ON domains(domain COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_local_chats_peer ON localization_chats(peer_id);
CREATE INDEX IF NOT EXISTS idx_announcement_schedules_due ON announcement_schedules(enabled, weekday, publish_time);
CREATE INDEX IF NOT EXISTS idx_user_command_grants_user ON user_command_grants(peer_id, user_id);
"""


class Database:
    """Small synchronous SQLite wrapper; each operation is protected by a lock."""

    def __init__(self, filename: str = "bot.db") -> None:
        # Resolve relative DB_PATH values against the project directory, not the
        # shell's current working directory. This prevents a restart/service
        # launch from silently opening a different, empty bot.db.
        db_path = Path(filename).expanduser()
        if not db_path.is_absolute():
            project_candidate = Path(__file__).resolve().parent / db_path
            legacy_working_directory_candidate = Path.cwd() / db_path
            # Preserve an existing database created by older versions, where a
            # relative filename was resolved from the current working directory.
            if legacy_working_directory_candidate.exists() and not project_candidate.exists():
                db_path = legacy_working_directory_candidate
            else:
                db_path = project_candidate
        self.filename = str(db_path.resolve())
        Path(self.filename).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.filename, check_same_thread=False, timeout=15)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.execute("PRAGMA busy_timeout = 15000")
        self.lock = threading.RLock()
        with self.lock:
            self.conn.executescript(SCHEMA)
            # Safe migration for databases created by older bot versions.
            columns = {row[1] for row in self.conn.execute("PRAGMA table_info(localization_chats)").fetchall()}
            if "public_id" not in columns:
                self.conn.execute("ALTER TABLE localization_chats ADD COLUMN public_id INTEGER")
            self.conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_localization_public_id ON localization_chats(public_id)")
            # Preserve the currently active bans when upgrading an older database.
            self.conn.execute(
                "INSERT INTO ban_history(peer_id,localization_id,user_id,actor_id,action,duration_text,reason,created_at,until_ts,permanent) "
                "SELECT b.peer_id,lc.localization_id,b.user_id,b.by_user,'Блокировка (сохранена при обновлении)',"
                "CASE WHEN b.permanent=1 THEN 'навсегда' ELSE 'до ' || datetime(b.until_ts,'unixepoch','localtime') END,"
                "b.reason,b.created_at,b.until_ts,b.permanent FROM bans b "
                "LEFT JOIN localization_chats lc ON lc.peer_id=b.peer_id "
                "WHERE NOT EXISTS (SELECT 1 FROM ban_history h WHERE h.peer_id=b.peer_id AND h.user_id=b.user_id AND h.created_at=b.created_at)"
            )
            # Migrate active localization-wide bans as well; older versions did not
            # keep their own history table for these restrictions.
            self.conn.execute(
                "INSERT INTO ban_history(peer_id,localization_id,user_id,actor_id,action,duration_text,reason,created_at,until_ts,permanent) "
                "SELECT l.main_peer_id,lb.localization_id,lb.user_id,lb.by_user,"
                "'Локальная блокировка (сохранена при обновлении)','во всех конференциях локализации',"
                "lb.reason,lb.created_at,NULL,1 FROM local_bans lb "
                "JOIN localizations l ON l.id=lb.localization_id "
                "WHERE NOT EXISTS (SELECT 1 FROM ban_history h WHERE h.peer_id=l.main_peer_id "
                "AND h.localization_id=lb.localization_id AND h.user_id=lb.user_id AND h.created_at=lb.created_at)"
            )
            # Upgrade legacy randomized conference IDs once to compact sequential
            # IDs (1, 2, 3, ...). After this migration IDs stay stable across restarts.
            legacy_random_ids = self.conn.execute(
                "SELECT 1 FROM localization_chats WHERE public_id>=10000 LIMIT 1"
            ).fetchone()
            if legacy_random_ids:
                linked = self.conn.execute(
                    "SELECT peer_id FROM localization_chats ORDER BY joined_at, peer_id"
                ).fetchall()
                self.conn.execute("UPDATE localization_chats SET public_id=NULL")
                for sequence, row in enumerate(linked, start=1):
                    self.conn.execute(
                        "UPDATE localization_chats SET public_id=? WHERE peer_id=?",
                        (sequence, int(row[0])),
                    )
            # Fill any NULL IDs with the first free positive integer.
            rows = self.conn.execute(
                "SELECT peer_id FROM localization_chats WHERE public_id IS NULL ORDER BY joined_at, peer_id"
            ).fetchall()
            for row in rows:
                candidate = 1
                while self.conn.execute(
                    "SELECT 1 FROM localization_chats WHERE public_id=?", (candidate,)
                ).fetchone():
                    candidate += 1
                self.conn.execute(
                    "UPDATE localization_chats SET public_id=? WHERE peer_id=?",
                    (candidate, int(row[0])),
                )
            self.conn.commit()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self.lock:
            try:
                self.conn.execute("BEGIN")
                yield self.conn
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Cursor:
        with self.lock:
            cur = self.conn.execute(sql, params)
            self.conn.commit()
            return cur

    def fetchone(self, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Row | None:
        with self.lock:
            return self.conn.execute(sql, params).fetchone()

    def fetchall(self, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        with self.lock:
            return self.conn.execute(sql, params).fetchall()

    def close(self) -> None:
        with self.lock:
            self.conn.close()
