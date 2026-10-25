"""Classes and class/subject pairs ("courses").

A course is the configuration used to start attendance; deleting it never
touches sessions or attendance rows, which keep their own class/subject text.
``sessions.json`` is rewritten after each change so the desktop app sees the
same list.
"""
import json
import os
import sqlite3

from backend import clock
from backend.errors import ServiceError, conflict, not_found
from functions.identity import IdentityError, normalize_class, normalize_subject


def _identity(fn, value):
    try:
        return fn(value)
    except IdentityError as exc:
        raise ServiceError(422, str(exc), 'invalid_identity')


class CatalogService:
    def __init__(self, db, paths, models=None):
        self.db = db
        self.paths = paths
        self.models = models

    # ----------------------------------------------------------------- classes
    def list_classes(self, q=None):
        sql = ('SELECT c.*, '
               '(SELECT COUNT(*) FROM students s WHERE s.class_name=c.name AND s.active=1) AS student_count, '
               '(SELECT COUNT(*) FROM courses k WHERE k.class_name=c.name) AS course_count, '
               '(SELECT COUNT(*) FROM sessions x WHERE x.class_name=c.name) AS session_count '
               'FROM classes c')
        params = []
        if q:
            sql += ' WHERE c.name LIKE ? OR c.description LIKE ?'
            params = [f'%{q.strip()}%'] * 2
        with self.db.read() as conn:
            return [dict(r) for r in conn.execute(sql + ' ORDER BY c.name', params)]

    def get_class(self, name):
        with self.db.read() as conn:
            row = conn.execute('SELECT * FROM classes WHERE name=?', (name,)).fetchone()
        if row is None:
            raise not_found(f'Không tìm thấy lớp "{name}".')
        return dict(row)

    def require_class(self, name):
        cls = _identity(normalize_class, name)
        self.get_class(cls)
        return cls

    def create_class(self, name, description=''):
        cls = _identity(normalize_class, name)
        try:
            with self.db.write() as conn:
                conn.execute('INSERT INTO classes(name, description, created_at) VALUES (?, ?, ?)',
                             (cls, (description or '').strip()[:200], clock.ts()))
        except sqlite3.IntegrityError:
            raise conflict(f'Lớp "{cls}" đã tồn tại.')
        os.makedirs(self.paths.class_dir(cls), exist_ok=True)
        return self._class_row(cls)

    def update_class(self, class_id, description):
        with self.db.write() as conn:
            cur = conn.execute('UPDATE classes SET description=? WHERE id=?',
                               ((description or '').strip()[:200], class_id))
            if cur.rowcount == 0:
                raise not_found('Không tìm thấy lớp.')
            name = conn.execute('SELECT name FROM classes WHERE id=?', (class_id,)).fetchone()['name']
        return self._class_row(name)

    def delete_class(self, class_id):
        import shutil
        import time
        with self.db.write() as conn:
            row = conn.execute('SELECT id, name FROM classes WHERE id=?', (class_id,)).fetchone()
            if row is None:
                raise not_found('Không tìm thấy lớp.')
            class_name = row['name']

            # Lấy danh sách tất cả sinh viên thuộc lớp đang xóa
            students = conn.execute(
                'SELECT id, student_id, full_name, folder FROM students WHERE class_name=? AND active=1',
                (class_name,)
            ).fetchall()

            now = clock.ts()
            # Đóng bất kỳ phiên điểm danh nào đang mở của lớp này
            conn.execute(
                'UPDATE sessions SET status="ended", ended_at=?, end_reason="class_deleted" '
                'WHERE class_name=? AND status="active"',
                (now, class_name)
            )

            # Chuyển active=0 (soft delete) cho tất cả sinh viên thuộc lớp này để bảo toàn lịch sử điểm danh
            conn.execute('UPDATE students SET active=0, updated_at=? WHERE class_name=?', (now, class_name))

            # Xóa các cấu hình môn học (courses) thuộc lớp này
            conn.execute('DELETE FROM courses WHERE class_name=?', (class_name,))

            # Xóa lớp học khỏi bảng classes
            conn.execute('DELETE FROM classes WHERE id=?', (class_id,))

        # Cập nhật sessions.json cho desktop app
        self._write_sessions_json()

        # Hủy recognizer trong bộ nhớ của lớp bị xóa
        if self.models is not None:
            self.models.invalidate(class_name)

        # Di chuyển thư mục dữ liệu khuôn mặt của lớp vào .deleted_classes để giải phóng nhận diện
        # đồng thời bảo vệ dữ liệu sinh viên
        class_dataset_dir = self.paths.class_dir(class_name)
        if os.path.exists(class_dataset_dir):
            try:
                trash_dir = os.path.join(self.paths.dataset_dir, '.deleted_classes')
                os.makedirs(trash_dir, exist_ok=True)
                stamp = time.strftime('%Y%m%d_%H%M%S')
                target_trash = os.path.join(trash_dir, f'{class_name}__{stamp}')
                shutil.move(class_dataset_dir, target_trash)
            except Exception as exc:
                print(f'[WARNING] Không thể di chuyển thư mục dataset lớp {class_name}: {exc}')

        return {
            'deleted': class_name,
            'students_count': len(students),
            'message': 'Đã xóa lớp và xử lý danh sách sinh viên liên quan thành công'
        }

    def _class_row(self, name):
        return next(c for c in self.list_classes() if c['name'] == name)

    # ----------------------------------------------------------------- courses
    def list_courses(self, class_name=None, q=None):
        sql = ('SELECT k.*, '
               '(SELECT COUNT(*) FROM sessions x WHERE x.class_name=k.class_name AND x.subject=k.subject) AS session_count, '
               '(SELECT MAX(x.date) FROM sessions x WHERE x.class_name=k.class_name AND x.subject=k.subject) AS last_session_date, '
               '(SELECT COUNT(*) FROM students s WHERE s.class_name=k.class_name AND s.active=1) AS student_count '
               'FROM courses k WHERE 1=1')
        params = []
        if class_name:
            sql += ' AND k.class_name=?'
            params.append(class_name.strip().upper())
        if q:
            sql += ' AND (k.class_name LIKE ? OR k.subject LIKE ? OR k.subject_name LIKE ?)'
            params += [f'%{q.strip()}%'] * 3
        with self.db.read() as conn:
            return [dict(r) for r in conn.execute(sql + ' ORDER BY k.class_name, k.subject', params)]

    def create_course(self, class_name, subject, subject_name=''):
        cls = self.require_class(class_name)
        subj = _identity(normalize_subject, subject)
        try:
            with self.db.write() as conn:
                cur = conn.execute('INSERT INTO courses(class_name, subject, subject_name, created_at) '
                                   'VALUES (?, ?, ?, ?)',
                                   (cls, subj, (subject_name or '').strip()[:120], clock.ts()))
                course_id = cur.lastrowid
        except sqlite3.IntegrityError:
            raise conflict(f'Lớp {cls} đã có môn {subj}.')
        self._write_sessions_json()
        return self.get_course(course_id)

    def get_course(self, course_id):
        rows = [c for c in self.list_courses() if c['id'] == course_id]
        if not rows:
            raise not_found('Không tìm thấy cấu hình lớp/môn.')
        return rows[0]

    def update_course(self, course_id, subject_name):
        with self.db.write() as conn:
            cur = conn.execute('UPDATE courses SET subject_name=? WHERE id=?',
                               ((subject_name or '').strip()[:120], course_id))
            if cur.rowcount == 0:
                raise not_found('Không tìm thấy cấu hình lớp/môn.')
        return self.get_course(course_id)

    def delete_course(self, course_id):
        course = self.get_course(course_id)
        with self.db.write() as conn:
            conn.execute('DELETE FROM courses WHERE id=?', (course_id,))
        self._write_sessions_json()
        return {'deleted': course_id, 'history_kept': course['session_count']}

    def _write_sessions_json(self):
        with self.db.read() as conn:
            items = [{'class': r['class_name'], 'subject': r['subject']}
                     for r in conn.execute('SELECT class_name, subject FROM courses ORDER BY id')]
        tmp = self.paths.sessions_file + '.tmp'
        try:
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(items, f, ensure_ascii=False, indent=4)
            os.replace(tmp, self.paths.sessions_file)
        except OSError as exc:
            print(f'[WARNING] Cannot update sessions.json: {exc}')
