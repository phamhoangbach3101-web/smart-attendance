"""SQLite access and idempotent schema migration.

The legacy ``attendance`` table written by the desktop app is kept unchanged
(new columns are only added), so ``attendance_system/main.py`` keeps working on
the same file. New tables hold classes, class/subject pairs, students,
attendance sessions with their roster, and settings.
"""
import json
import os
import shutil
import sqlite3
from contextlib import contextmanager

from backend import clock
from functions.identity import (IdentityError, normalize_class, normalize_subject,
                                parse_student_folder)

SCHEMA_VERSION = 1

_TABLES = """
CREATE TABLE IF NOT EXISTS attendance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    class_name TEXT NOT NULL,
    subject TEXT NOT NULL,
    student_id TEXT NOT NULL,
    student_name TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    date TEXT NOT NULL,
    confidence REAL DEFAULT 0.0,
    slot INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS classes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS courses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    class_name TEXT NOT NULL,
    subject TEXT NOT NULL,
    subject_name TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE (class_name, subject)
);
CREATE TABLE IF NOT EXISTS students (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    class_name TEXT NOT NULL,
    student_id TEXT NOT NULL,
    full_name TEXT NOT NULL,
    folder TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_students_active_id
    ON students(class_name, student_id) WHERE active = 1;
CREATE UNIQUE INDEX IF NOT EXISTS ux_students_active_folder
    ON students(class_name, folder) WHERE active = 1;
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    class_name TEXT NOT NULL,
    subject TEXT NOT NULL,
    date TEXT NOT NULL,
    slot INTEGER NOT NULL,
    duration_minutes INTEGER,
    started_at TEXT NOT NULL,
    opened_at TEXT NOT NULL,
    deadline_at TEXT,
    ended_at TEXT,
    end_reason TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    camera_type TEXT NOT NULL DEFAULT 'browser',
    legacy INTEGER NOT NULL DEFAULT 0,
    roster_known INTEGER NOT NULL DEFAULT 1,
    UNIQUE (class_name, subject, date, slot)
);
CREATE TABLE IF NOT EXISTS session_roster (
    session_id INTEGER NOT NULL,
    student_pk INTEGER,
    student_id TEXT NOT NULL,
    student_name TEXT NOT NULL,
    added_at TEXT NOT NULL,
    PRIMARY KEY (session_id, student_id)
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class Database:
    def __init__(self, path):
        self.path = path
        self.migration_report = {}

    def connect(self):
        conn = sqlite3.connect(self.path, timeout=15, isolation_level=None,
                               check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA busy_timeout = 15000')
        conn.execute('PRAGMA foreign_keys = ON')
        return conn

    @contextmanager
    def read(self):
        conn = self.connect()
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def write(self):
        """Serialised write transaction (BEGIN IMMEDIATE takes the write lock up front)."""
        conn = self.connect()
        try:
            conn.execute('BEGIN IMMEDIATE')
            yield conn
            conn.execute('COMMIT')
        except BaseException:
            if conn.in_transaction:
                conn.execute('ROLLBACK')
            raise
        finally:
            conn.close()

    # ------------------------------------------------------------------ migrate
    def migrate(self, paths):
        report = {'backup': None, 'imported_courses': 0, 'skipped_courses': [],
                  'legacy_sessions': 0, 'duplicates': [], 'unique_index': False}
        existed = os.path.exists(self.path) and os.path.getsize(self.path) > 0
        with self.read() as conn:
            version = conn.execute('PRAGMA user_version').fetchone()[0]
        if existed and version < SCHEMA_VERSION:
            report['backup'] = self._backup(paths.backups_dir, version)

        with self.read() as conn:
            conn.execute('PRAGMA journal_mode = WAL')
        with self.write() as conn:
            for stmt in _split_sql(_TABLES):
                conn.execute(stmt)
            cols = {r['name'] for r in conn.execute('PRAGMA table_info(attendance)')}
            for col, ddl in (('slot', 'INTEGER DEFAULT 0'), ('session_id', 'INTEGER'),
                             ('student_pk', 'INTEGER')):
                if col not in cols:
                    conn.execute(f'ALTER TABLE attendance ADD COLUMN {col} {ddl}')
            conn.execute('CREATE INDEX IF NOT EXISTS ix_attendance_session ON attendance(session_id)')
            conn.execute('CREATE INDEX IF NOT EXISTS ix_attendance_date ON attendance(date)')

        report['imported_courses'], report['skipped_courses'] = self._import_sessions_json(paths)
        self._import_dataset_classes(paths)
        report['legacy_sessions'] = self.link_orphan_attendance()

        with self.write() as conn:
            dups = conn.execute(
                'SELECT class_name, subject, student_id, date, slot, COUNT(*) AS n '
                'FROM attendance GROUP BY class_name, subject, student_id, date, slot '
                'HAVING n > 1').fetchall()
            report['duplicates'] = [dict(r) for r in dups]
            if not dups:
                conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS ux_attendance_once '
                             'ON attendance(class_name, subject, student_id, date, slot)')
                report['unique_index'] = True
            else:
                print(f'[WARNING] {len(dups)} duplicate attendance groups found; '
                      'unique index not created, nothing was deleted.')
            conn.execute(f'PRAGMA user_version = {SCHEMA_VERSION}')
        self.migration_report = report
        return report

    def _backup(self, backups_dir, version):
        os.makedirs(backups_dir, exist_ok=True)
        stamp = clock.now().strftime('%Y%m%d_%H%M%S')
        target = os.path.join(backups_dir, f'attendance_v{version}_{stamp}.db')
        src = sqlite3.connect(self.path)
        dst = sqlite3.connect(target)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        print(f'[INFO] Database backed up to {target}')
        return target

    def _import_sessions_json(self, paths):
        """Copy class/subject pairs from the desktop sessions.json (kept as is)."""
        imported, skipped = 0, []
        if not os.path.exists(paths.sessions_file):
            return imported, skipped
        try:
            with open(paths.sessions_file, encoding='utf-8') as f:
                items = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            return imported, [f'sessions.json: {exc}']
        with self.write() as conn:
            for item in items if isinstance(items, list) else []:
                try:
                    cls = normalize_class(item.get('class'))
                    subj = normalize_subject(item.get('subject'))
                except (IdentityError, AttributeError) as exc:
                    skipped.append(f'{item}: {exc}')
                    continue
                now = clock.ts()
                conn.execute('INSERT OR IGNORE INTO classes(name, created_at) VALUES (?, ?)', (cls, now))
                cur = conn.execute('INSERT OR IGNORE INTO courses(class_name, subject, created_at) '
                                   'VALUES (?, ?, ?)', (cls, subj, now))
                imported += cur.rowcount
        return imported, skipped

    def _import_dataset_classes(self, paths):
        if not os.path.isdir(paths.dataset_dir):
            return
        with self.write() as conn:
            for name in sorted(os.listdir(paths.dataset_dir)):
                if name.startswith('.') or not os.path.isdir(os.path.join(paths.dataset_dir, name)):
                    continue
                try:
                    cls = normalize_class(name)
                except IdentityError:
                    continue
                if cls == name:
                    conn.execute('INSERT OR IGNORE INTO classes(name, created_at) VALUES (?, ?)',
                                 (cls, clock.ts()))

    def link_orphan_attendance(self):
        """Attach rows written without a session (desktop app) to a session row.

        Rows whose (class, subject, date, slot) has no session yet get a
        'legacy' ended session whose roster is unknown, so the history page can
        show them without inventing absences.
        """
        created = 0
        with self.write() as conn:
            groups = conn.execute(
                'SELECT class_name, subject, date, COALESCE(slot, 0) AS slot, '
                'MIN(timestamp) AS first_ts, MAX(timestamp) AS last_ts '
                'FROM attendance WHERE session_id IS NULL '
                'GROUP BY class_name, subject, date, COALESCE(slot, 0)').fetchall()
            for g in groups:
                cur = conn.execute(
                    'INSERT OR IGNORE INTO sessions(class_name, subject, date, slot, duration_minutes, '
                    'started_at, opened_at, ended_at, end_reason, status, camera_type, legacy, roster_known) '
                    "VALUES (?, ?, ?, ?, NULL, ?, ?, ?, 'legacy', 'ended', 'desktop', 1, 0)",
                    (g['class_name'], g['subject'], g['date'], g['slot'],
                     g['first_ts'], g['first_ts'], g['last_ts']))
                created += cur.rowcount
                sid = conn.execute('SELECT id FROM sessions WHERE class_name=? AND subject=? '
                                   'AND date=? AND slot=?',
                                   (g['class_name'], g['subject'], g['date'], g['slot'])).fetchone()['id']
                conn.execute('UPDATE attendance SET session_id=? WHERE session_id IS NULL AND '
                             'class_name=? AND subject=? AND date=? AND COALESCE(slot, 0)=?',
                             (sid, g['class_name'], g['subject'], g['date'], g['slot']))
                # Make sure students recorded by the desktop app appear on the roster.
                conn.execute(
                    'INSERT OR IGNORE INTO session_roster(session_id, student_pk, student_id, student_name, added_at) '
                    'SELECT session_id, student_pk, student_id, student_name, timestamp FROM attendance '
                    'WHERE session_id=?', (sid,))
        return created


def _split_sql(script):
    return [s.strip() for s in script.split(';') if s.strip()]


def row_dict(row):
    return dict(row) if row is not None else None


def parse_folder(folder):
    return parse_student_folder(folder)
