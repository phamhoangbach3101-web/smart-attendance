"""Attendance sessions and check-in recording.

A session is identified by (class, subject, date, slot); ``date`` is fixed when
the session is created, so a session running past midnight keeps its date.
The backend owns start time, deadline and status: reloading the browser only
reads them back. Recording happens inside one ``BEGIN IMMEDIATE`` transaction
that re-checks the session is still open, so results arriving after the end
or the deadline are rejected and two concurrent requests cannot both insert.
"""
import sqlite3
from datetime import timedelta

from backend import clock
from backend.errors import ServiceError, conflict, invalid, not_found
from functions.identity import IdentityError, normalize_class, normalize_subject

MAX_SLOT = 20
MAX_DURATION = 600


def session_state(row, now=None):
    now = now or clock.now()
    if row['status'] != 'active':
        return 'ended'
    deadline = clock.parse_ts(row['deadline_at'])
    if deadline is not None and now >= deadline:
        return 'expired'
    return 'active'


def _is_open(row, now=None):
    return session_state(row, now) == 'active'


class SessionService:
    def __init__(self, db, catalog):
        self.db = db
        self.catalog = catalog
        self.on_closed = []   # callbacks(session_dict) e.g. Excel sync

    # --------------------------------------------------------------- lifecycle
    def open(self, class_name, subject, slot, duration_minutes, camera_type='browser',
             reopen=False):
        try:
            cls = normalize_class(class_name)
            subj = normalize_subject(subject)
        except IdentityError as exc:
            raise ServiceError(422, str(exc), 'invalid_identity')
        if not isinstance(slot, int) or not 1 <= slot <= MAX_SLOT:
            raise invalid(f'Slot phải từ 1 đến {MAX_SLOT}.')
        if duration_minutes is not None and not 1 <= int(duration_minutes) <= MAX_DURATION:
            raise invalid(f'Thời lượng phải từ 1 đến {MAX_DURATION} phút, hoặc chọn không giới hạn.')
        if camera_type not in ('browser', 'rtsp'):
            raise invalid('Nguồn camera không hợp lệ.')
        if not any(c['subject'] == subj for c in self.catalog.list_courses(cls)):
            raise not_found(f'Chưa có cấu hình môn {subj} cho lớp {cls}. Hãy tạo ở trang Lớp & Môn học.')

        self.expire_due()
        now = clock.now()
        today = now.date().isoformat()
        with self.db.write() as conn:
            row = conn.execute('SELECT * FROM sessions WHERE class_name=? AND subject=? AND date=? AND slot=?',
                               (cls, subj, today, slot)).fetchone()
            if row is not None:
                state = session_state(row, now)
                if state == 'active':
                    return {**self._detail(conn, row['id']), 'created': False, 'reopened': False}
                if not reopen:
                    present = conn.execute('SELECT COUNT(*) FROM attendance WHERE session_id=?',
                                           (row['id'],)).fetchone()[0]
                    raise conflict(
                        f'Phiên {cls} – {subj} – Slot {slot} hôm nay đã kết thúc '
                        f'({present} sinh viên có mặt). Bạn có muốn mở lại không?',
                        'session_ended', {'session_id': row['id'], 'present': present})
                self._reopen(conn, row['id'], duration_minutes, camera_type, now)
                return {**self._detail(conn, row['id']), 'created': False, 'reopened': True}
            deadline = clock.ts(now + timedelta(minutes=int(duration_minutes))) if duration_minutes else None
            cur = conn.execute(
                'INSERT INTO sessions(class_name, subject, date, slot, duration_minutes, started_at, '
                "opened_at, deadline_at, status, camera_type) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)",
                (cls, subj, today, slot, duration_minutes, clock.ts(now), clock.ts(now), deadline, camera_type))
            sid = cur.lastrowid
            self._snapshot_roster(conn, sid, cls, now)
            return {**self._detail(conn, sid), 'created': True, 'reopened': False}

    def reopen(self, session_id, duration_minutes, camera_type='browser'):
        if duration_minutes is not None and not 1 <= int(duration_minutes) <= MAX_DURATION:
            raise invalid(f'Thời lượng phải từ 1 đến {MAX_DURATION} phút, hoặc chọn không giới hạn.')
        now = clock.now()
        with self.db.write() as conn:
            row = self._row(conn, session_id)
            if session_state(row, now) != 'active':
                self._reopen(conn, session_id, duration_minutes, camera_type, now)
            return self._detail(conn, session_id)

    def _reopen(self, conn, session_id, duration_minutes, camera_type, now):
        deadline = clock.ts(now + timedelta(minutes=int(duration_minutes))) if duration_minutes else None
        row = self._row(conn, session_id)
        conn.execute("UPDATE sessions SET status='active', opened_at=?, deadline_at=?, duration_minutes=?, "
                     'ended_at=NULL, end_reason=NULL, camera_type=?, roster_known=1 WHERE id=?',
                     (clock.ts(now), deadline, duration_minutes, camera_type, session_id))
        # Students enrolled since the last opening join the roster; nobody is removed.
        self._snapshot_roster(conn, session_id, row['class_name'], now)

    def _snapshot_roster(self, conn, session_id, class_name, now):
        conn.execute('INSERT OR IGNORE INTO session_roster(session_id, student_pk, student_id, student_name, added_at) '
                     'SELECT ?, id, student_id, full_name, ? FROM students WHERE class_name=? AND active=1',
                     (session_id, clock.ts(now), class_name))

    def add_to_active_rosters(self, class_name, student_pk, student_id, name):
        now = clock.now()
        with self.db.write() as conn:
            for row in conn.execute("SELECT * FROM sessions WHERE class_name=? AND status='active'",
                                    (class_name,)).fetchall():
                if _is_open(row, now):
                    conn.execute('INSERT OR IGNORE INTO session_roster(session_id, student_pk, student_id, '
                                 'student_name, added_at) VALUES (?, ?, ?, ?, ?)',
                                 (row['id'], student_pk, student_id, name, clock.ts(now)))

    def end(self, session_id, reason='manual'):
        now = clock.now()
        with self.db.write() as conn:
            row = self._row(conn, session_id)
            state = session_state(row, now)
            if state == 'active':
                conn.execute("UPDATE sessions SET status='ended', ended_at=?, end_reason=? WHERE id=?",
                             (clock.ts(now), reason, session_id))
            elif state == 'expired':
                conn.execute("UPDATE sessions SET status='ended', ended_at=deadline_at, end_reason='timeout' "
                             'WHERE id=?', (session_id,))
            detail = self._detail(conn, session_id)
        if state != 'ended':
            self._notify_closed(detail)
        return detail

    def expire_due(self):
        """Persist the end of sessions whose deadline passed (idempotent)."""
        now = clock.ts()
        with self.db.write() as conn:
            rows = conn.execute("SELECT id FROM sessions WHERE status='active' AND deadline_at IS NOT NULL "
                                'AND deadline_at <= ?', (now,)).fetchall()
            conn.execute("UPDATE sessions SET status='ended', ended_at=deadline_at, end_reason='timeout' "
                         "WHERE status='active' AND deadline_at IS NOT NULL AND deadline_at <= ?", (now,))
            details = [self._detail(conn, r['id']) for r in rows]
        for d in details:
            self._notify_closed(d)
        return details

    def _notify_closed(self, detail):
        for callback in self.on_closed:
            try:
                callback(detail)
            except Exception as exc:  # Excel sync must never break the session flow
                print(f'[WARNING] session close hook failed: {exc}')

    # ------------------------------------------------------------------- reads
    def _row(self, conn, session_id):
        row = conn.execute('SELECT * FROM sessions WHERE id=?', (session_id,)).fetchone()
        if row is None:
            raise not_found('Không tìm thấy phiên điểm danh.')
        return row

    def _detail(self, conn, session_id):
        row = self._row(conn, session_id)
        now = clock.now()
        d = dict(row)
        d['state'] = session_state(row, now)
        deadline = clock.parse_ts(row['deadline_at'])
        d['remaining_seconds'] = (max(0, int((deadline - now).total_seconds()))
                                  if deadline and d['state'] == 'active' else None)
        d['server_time'] = clock.ts(now)
        roster = conn.execute('SELECT COUNT(*) FROM session_roster WHERE session_id=?', (session_id,)).fetchone()[0]
        present = conn.execute('SELECT COUNT(DISTINCT student_id) FROM attendance WHERE session_id=?',
                               (session_id,)).fetchone()[0]
        d['roster_count'] = roster
        d['present_count'] = present
        d['absent_count'] = max(0, roster - present) if row['roster_known'] else None
        return d

    def get(self, session_id):
        with self.db.read() as conn:
            return self._detail(conn, session_id)

    def list(self, date=None, class_name=None, subject=None, state=None, limit=200):
        sql, params = 'SELECT id FROM sessions WHERE 1=1', []
        for col, val in (('date', date), ('class_name', class_name), ('subject', subject)):
            if val:
                sql += f' AND {col}=?'
                params.append(val)
        sql += ' ORDER BY date DESC, opened_at DESC LIMIT ?'
        params.append(limit)
        with self.db.read() as conn:
            items = [self._detail(conn, r['id']) for r in conn.execute(sql, params).fetchall()]
        if state:
            items = [i for i in items if (i['state'] == 'active') == (state == 'active')]
        return items

    def records(self, session_id):
        """Roster of a session with presence, ordered: present first (latest first)."""
        with self.db.read() as conn:
            session = self._detail(conn, session_id)
            rows = conn.execute(
                'SELECT r.student_id, r.student_name, r.student_pk, a.timestamp, a.confidence '
                'FROM session_roster r LEFT JOIN attendance a '
                'ON a.session_id=r.session_id AND a.student_id=r.student_id '
                'WHERE r.session_id=? '
                'UNION ALL '
                'SELECT a.student_id, a.student_name, a.student_pk, a.timestamp, a.confidence '
                'FROM attendance a WHERE a.session_id=? AND NOT EXISTS '
                '(SELECT 1 FROM session_roster r WHERE r.session_id=a.session_id AND r.student_id=a.student_id)',
                (session_id, session_id)).fetchall()
        items = []
        for r in rows:
            present = r['timestamp'] is not None
            status = 'present' if present else ('absent' if session['roster_known'] else 'unknown')
            items.append({**dict(r), 'status': status})
        present = sorted((i for i in items if i['timestamp']), key=lambda i: i['timestamp'], reverse=True)
        missing = sorted((i for i in items if not i['timestamp']), key=lambda i: i['student_id'])
        return {'session': session, 'records': present + missing}

    # --------------------------------------------------------------- recording
    def record(self, session_id, student_id, student_name, score):
        """Insert one check-in. Returns {'status': inserted|already|session_closed, ...}."""
        now = clock.now()
        try:
            with self.db.write() as conn:
                s = self._row(conn, session_id)
                if not _is_open(s, now):
                    return {'status': 'session_closed', 'timestamp': None}
                pk_row = conn.execute('SELECT id FROM students WHERE class_name=? AND student_id=? AND active=1',
                                      (s['class_name'], student_id)).fetchone()
                pk = pk_row['id'] if pk_row else None
                cur = conn.execute(
                    'INSERT INTO attendance(class_name, subject, student_id, student_name, timestamp, date, '
                    'confidence, slot, session_id, student_pk) '
                    'SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?, ? WHERE NOT EXISTS ('
                    'SELECT 1 FROM attendance WHERE class_name=? AND subject=? AND student_id=? AND date=? AND slot=?)',
                    (s['class_name'], s['subject'], student_id, student_name, clock.ts(now), s['date'],
                     float(score), s['slot'], session_id, pk,
                     s['class_name'], s['subject'], student_id, s['date'], s['slot']))
                if cur.rowcount == 1:
                    conn.execute('INSERT OR IGNORE INTO session_roster(session_id, student_pk, student_id, '
                                 'student_name, added_at) VALUES (?, ?, ?, ?, ?)',
                                 (session_id, pk, student_id, student_name, clock.ts(now)))
                    return {'status': 'inserted', 'timestamp': clock.ts(now)}
                existing = conn.execute(
                    'SELECT timestamp FROM attendance WHERE class_name=? AND subject=? AND student_id=? '
                    'AND date=? AND slot=? ORDER BY timestamp LIMIT 1',
                    (s['class_name'], s['subject'], student_id, s['date'], s['slot'])).fetchone()
                return {'status': 'already', 'timestamp': existing['timestamp'] if existing else None}
        except sqlite3.IntegrityError:
            return {'status': 'already', 'timestamp': None}
