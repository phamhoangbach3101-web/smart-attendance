"""Students: the ``students`` table mirrors the dataset folders.

Embeddings and photos stay in ``dataset/<CLASS>/<CLASS>_<ID>_<Name>/`` exactly
as the desktop app writes them; the table gives each student a stable integer
key used by sessions and attendance. ``sync`` reconciles the two, so students
enrolled from the desktop app also show up here.
"""
import os
import shutil
import sqlite3

import numpy as np

from backend import clock
from backend.errors import ServiceError, conflict, invalid, not_found
from functions.biometrics_logger import BiometricsLogger
from functions.identity import (IdentityError, normalize_name, normalize_student_id,
                                parse_student_folder, student_folder)

MAX_SAMPLES = 5
CONSISTENCY_MIN = 0.45   # every sample must look like the same person


def _ident(fn, value):
    try:
        return fn(value)
    except IdentityError as exc:
        raise ServiceError(422, str(exc), 'invalid_identity')


class StudentService:
    def __init__(self, db, paths, catalog, sessions, models):
        self.db = db
        self.paths = paths
        self.catalog = catalog
        self.sessions = sessions
        self.models = models
        self.recognition = None    # set by the app container (avoids a cycle)

    # -------------------------------------------------------------------- sync
    def _scan_class(self, class_name):
        cdir = self.paths.class_dir(class_name)
        found = {}
        if os.path.isdir(cdir):
            for folder in os.listdir(cdir):
                fp = os.path.join(cdir, folder)
                if folder.startswith('.') or not os.path.isdir(fp):
                    continue
                parsed = parse_student_folder(folder)
                if parsed['class'] != class_name:
                    continue
                found[folder] = parsed
        return found

    def sync(self, class_name=None):
        """Reconcile table rows with dataset folders; returns classes that changed."""
        classes = [class_name] if class_name else [c['name'] for c in self.catalog.list_classes()]
        changed = set()
        now = clock.ts()
        for cls in classes:
            found = self._scan_class(cls)
            with self.db.write() as conn:
                rows = {r['folder']: r for r in conn.execute(
                    'SELECT * FROM students WHERE class_name=? AND active=1', (cls,))}
                for folder, row in rows.items():
                    if folder not in found:
                        conn.execute('UPDATE students SET active=0, updated_at=? WHERE id=?', (now, row['id']))
                        changed.add(cls)
                for folder, parsed in found.items():
                    if folder in rows:
                        continue
                    try:
                        conn.execute('INSERT INTO students(class_name, student_id, full_name, folder, active, '
                                     'created_at, updated_at) VALUES (?, ?, ?, ?, 1, ?, ?)',
                                     (cls, parsed['id'], parsed['name'], folder, now, now))
                        changed.add(cls)
                    except sqlite3.IntegrityError:
                        print(f'[WARNING] Duplicate student ID folder skipped: {cls}/{folder}')
        for cls in changed:
            self.models.invalidate(cls)
        return sorted(changed)

    # ------------------------------------------------------------------- reads
    def _face_info(self, row):
        sdir = os.path.join(self.paths.class_dir(row['class_name']), row['folder'])
        photos = sorted(f for f in os.listdir(sdir) if f.lower().endswith(('.jpg', '.jpeg', '.png'))) \
            if os.path.isdir(sdir) else []
        n_emb, status = 0, 'missing'
        emb_path = os.path.join(sdir, 'embeddings.npy')
        if os.path.exists(emb_path):
            try:
                arr = np.load(emb_path)
                n_emb = int(np.atleast_2d(arr).shape[0])
                ok = arr.size and np.isfinite(arr).all() and np.atleast_2d(arr).shape[1] == 512
                status = 'enrolled' if ok else 'invalid'
            except (OSError, ValueError):
                status = 'invalid'
        return {'photos': photos, 'embedding_count': n_emb, 'face_status': status}

    def _public(self, row, conn=None):
        d = dict(row)
        d.update(self._face_info(row))
        if conn is not None:
            d['attendance_count'] = conn.execute(
                'SELECT COUNT(*) FROM attendance WHERE class_name=? AND student_id=?',
                (row['class_name'], row['student_id'])).fetchone()[0]
        return d

    def list(self, class_name=None, q=None, face_status=None):
        sql, params = 'SELECT * FROM students WHERE active=1', []
        if class_name:
            sql += ' AND class_name=?'
            params.append(class_name.strip().upper())
        with self.db.read() as conn:
            rows = conn.execute(sql + ' ORDER BY class_name, student_id', params).fetchall()
            items = [self._public(r, conn) for r in rows]
        if q:
            needle = q.strip().casefold()
            items = [i for i in items if needle in i['student_id'].casefold() or needle in i['full_name'].casefold()]
        if face_status:
            items = [i for i in items if i['face_status'] == face_status]
        return items

    def get(self, pk):
        with self.db.read() as conn:
            row = conn.execute('SELECT * FROM students WHERE id=? AND active=1', (pk,)).fetchone()
            if row is None:
                raise not_found('Không tìm thấy sinh viên.')
            return self._public(row, conn)

    def history(self, pk):
        """Sessions of the student's own class only; same ID in another class is excluded."""
        st = self.get(pk)
        with self.db.read() as conn:
            rows = conn.execute(
                'SELECT s.id AS session_id, s.subject, s.date, s.slot, s.roster_known, '
                'a.timestamp, a.confidence FROM sessions s '
                'LEFT JOIN attendance a ON a.session_id=s.id AND a.student_id=? '
                'WHERE s.class_name=? AND (a.id IS NOT NULL OR EXISTS ('
                'SELECT 1 FROM session_roster r WHERE r.session_id=s.id AND r.student_id=?)) '
                'ORDER BY s.date DESC, s.slot DESC',
                (st['student_id'], st['class_name'], st['student_id'])).fetchall()
        items = [{**dict(r), 'status': 'present' if r['timestamp'] else
                  ('absent' if r['roster_known'] else 'unknown')} for r in rows]
        return {'student': st, 'history': items,
                'present': sum(i['status'] == 'present' for i in items),
                'absent': sum(i['status'] == 'absent' for i in items)}

    def photo_path(self, pk, name):
        st = self.get(pk)
        if name not in st['photos']:
            raise not_found('Không tìm thấy ảnh.')
        return os.path.join(self.paths.class_dir(st['class_name']), st['folder'], name)

    # -------------------------------------------------------------- enrollment
    def _analyze_all(self, images):
        if not images:
            raise invalid('Cần ít nhất 1 ảnh mẫu khuôn mặt.')
        if len(images) > MAX_SAMPLES:
            raise invalid(f'Tối đa {MAX_SAMPLES} ảnh mẫu.')
        samples = [self.recognition.analyze_sample(img) for img in images]
        bad = [{'index': i, 'reason': s['reason'], 'message': s['message']}
               for i, s in enumerate(samples) if not s['ok']]
        if bad:
            raise ServiceError(422, 'Có ảnh mẫu không hợp lệ: ' +
                               '; '.join(f"ảnh {b['index'] + 1}: {b['message']}" for b in bad),
                               'invalid_samples', {'samples': bad})
        embs = np.vstack([s['embedding'] for s in samples])
        unit = embs / (np.linalg.norm(embs, axis=1, keepdims=True) + 1e-6)
        mean = unit.mean(axis=0)
        mean /= np.linalg.norm(mean) + 1e-6
        sims = unit @ mean
        if len(samples) > 1 and float(sims.min()) < CONSISTENCY_MIN:
            worst = int(sims.argmin())
            raise ServiceError(422, f'Ảnh {worst + 1} có vẻ không cùng một người với các ảnh khác.',
                               'inconsistent_samples', {'samples': [{'index': worst, 'reason': 'inconsistent'}]})
        return samples, embs

    def find_existing_face(self, student_id, exclude_class=None):
        """Find existing face embeddings and photos for student_id in any active class."""
        norm_id = student_id.strip().upper().replace(' ', '')
        with self.db.read() as conn:
            rows = conn.execute(
                'SELECT * FROM students WHERE active=1 AND UPPER(REPLACE(student_id, " ", "")) = ?',
                (norm_id,)
            ).fetchall()
        for r in rows:
            if exclude_class and r['class_name'] == exclude_class:
                continue
            sdir = os.path.join(self.paths.class_dir(r['class_name']), r['folder'])
            emb_path = os.path.join(sdir, 'embeddings.npy')
            if os.path.exists(emb_path):
                try:
                    arr = np.load(emb_path)
                    if arr.size and np.isfinite(arr).all() and np.atleast_2d(arr).shape[1] == 512:
                        photos = sorted(f for f in os.listdir(sdir) if f.lower().endswith(('.jpg', '.jpeg', '.png')))
                        return {
                            'class_name': r['class_name'],
                            'folder': r['folder'],
                            'dir': sdir,
                            'emb_path': emb_path,
                            'photos': photos,
                            'student_id': r['student_id'],
                            'full_name': r['full_name'],
                        }
                except Exception:
                    pass
        return None

    def _sync_face_to_all_classes(self, student_id, source_folder, source_class):
        """Replicate face embeddings and photos to all other active classes where this student is registered."""
        src_dir = os.path.join(self.paths.class_dir(source_class), source_folder)
        emb_file = os.path.join(src_dir, 'embeddings.npy')
        if not os.path.exists(emb_file):
            return
        norm_id = student_id.strip().upper().replace(' ', '')
        src_name = parse_student_folder(source_folder).get('name', '')
        with self.db.read() as conn:
            other_rows = conn.execute(
                'SELECT * FROM students WHERE active=1 AND UPPER(REPLACE(student_id, " ", "")) = ? AND class_name<>?',
                (norm_id, source_class)
            ).fetchall()
        for r in other_rows:
            if src_name and r['full_name'] and normalize_name(src_name).casefold() != normalize_name(r['full_name']).casefold():
                continue
            target_class = r['class_name']

            target_dir = os.path.join(self.paths.class_dir(target_class), r['folder'])
            os.makedirs(target_dir, exist_ok=True)
            backup = os.path.join(target_dir, '.previous')
            os.makedirs(backup, exist_ok=True)
            for fname in os.listdir(target_dir):
                if fname != '.previous' and fname.lower().endswith(('.jpg', '.jpeg', '.png', '.npy')):
                    try:
                        shutil.copy2(os.path.join(target_dir, fname), os.path.join(backup, fname))
                    except Exception:
                        pass
            shutil.copy2(emb_file, os.path.join(target_dir, 'embeddings.npy'))
            for f in os.listdir(src_dir):
                if f.lower().endswith(('.jpg', '.jpeg', '.png')):
                    try:
                        shutil.copy2(os.path.join(src_dir, f), os.path.join(target_dir, f))
                    except Exception:
                        pass
            self.models.invalidate(target_class)

    def _duplicate_face(self, recognizer, embs, exclude_folder=None, allow_student_id=None):
        gallery = {k: v for k, v in recognizer.embeddings_db.items() if k != exclude_folder}
        if not gallery:
            return None
        from functions.matching import match
        decision = match(embs.mean(axis=0), gallery, recognizer.threshold, recognizer.min_margin)
        if decision['matched'] or decision['score'] >= recognizer.threshold:
            who = parse_student_folder(decision['best_identity'])
            if allow_student_id and who['id'].casefold() == allow_student_id.casefold():
                return None  # Matches the student themselves, which is allowed!
            return {'student_id': who['id'], 'student_name': who['name'], 'score': decision['score']}
        return None

    def enroll(self, class_name, student_id, full_name, images):
        cls = self.catalog.require_class(class_name)
        sid = _ident(normalize_student_id, student_id)
        name = _ident(normalize_name, full_name)
        self.sync(cls)
        with self.db.read() as conn:
            if conn.execute('SELECT 1 FROM students WHERE class_name=? AND student_id=? AND active=1',
                            (cls, sid)).fetchone():
                raise conflict(f'Mã sinh viên {sid} đã tồn tại trong lớp {cls}.', 'duplicate_id')

        folder = student_folder(cls, sid, name)
        cdir = self.paths.class_dir(cls)
        target_dir = os.path.join(cdir, folder)
        warnings = []

        if not images:
            # Check if student already has face enrolled in another class
            existing = self.find_existing_face(sid, exclude_class=cls)
            if existing:
                os.makedirs(target_dir, exist_ok=True)
                shutil.copy2(existing['emb_path'], os.path.join(target_dir, 'embeddings.npy'))
                for p in existing['photos']:
                    src_p = os.path.join(existing['dir'], p)
                    if os.path.exists(src_p):
                        try:
                            shutil.copy2(src_p, os.path.join(target_dir, p))
                        except Exception:
                            pass
                warnings.append(f"Đã tự động tái sử dụng dữ liệu khuôn mặt đã đăng ký từ lớp {existing['class_name']}.")
            else:
                os.makedirs(target_dir, exist_ok=True)
                warnings.append('Sinh viên đã được thêm vào lớp. Vui lòng đăng ký khuôn mặt để điểm danh.')
        else:
            samples, embs = self._analyze_all(images)
            recognizer = self.models.recognizer(cls)
            with self.models.lock:
                dup = self._duplicate_face(recognizer, embs, allow_student_id=sid)
                if dup:
                    raise conflict(f"Khuôn mặt này đã được đăng ký cho sinh viên khác: {dup['student_id']} – {dup['student_name']} "
                                   f"(điểm tương đồng {dup['score']:.2f}).", 'duplicate_face', dup)
                try:
                    folder = recognizer.enroll_student(cls, sid, name, list(embs), [s['crop'] for s in samples])
                except (OSError, ValueError) as exc:
                    raise ServiceError(500, f'Không ghi được dữ liệu khuôn mặt: {exc}', 'write_failed')
            if not folder:
                folder = student_folder(cls, sid, name)
                ok = recognizer.update_student_samples(folder, list(embs), [s['crop'] for s in samples])
                if not ok:
                    raise conflict('Không thể đăng ký: khuôn mặt hoặc mã sinh viên trùng lặp.', 'enroll_rejected')
            try:
                BiometricsLogger.create_enroll_log(os.path.join(cdir, folder), samples[0]['raw'], samples[0]['det_box'])
                BiometricsLogger.add_student_to_master_sheet(cdir, sid, name)
            except Exception as exc:
                warnings.append(f'Không cập nhật được file Excel phụ: {exc}')
            # Sync to all other classes of this student
            self._sync_face_to_all_classes(sid, folder, cls)

        self.sync(cls)
        self.models.invalidate(cls)
        with self.db.read() as conn:
            row = conn.execute('SELECT * FROM students WHERE class_name=? AND folder=? AND active=1',
                               (cls, folder)).fetchone()
        if row is None:
            raise ServiceError(500, 'Đã lưu khuôn mặt nhưng không đọc lại được hồ sơ.', 'write_failed')
        self.sessions.add_to_active_rosters(cls, row['id'], sid, name)
        return {**self.get(row['id']), 'warnings': warnings}

    def update_face(self, pk, images):
        st = self.get(pk)
        samples, embs = self._analyze_all(images)
        recognizer = self.models.recognizer(st['class_name'])
        with self.models.lock:
            dup = self._duplicate_face(recognizer, embs, exclude_folder=st['folder'], allow_student_id=st['student_id'])
            if dup:
                raise conflict(f"Khuôn mặt giống sinh viên khác: {dup['student_id']} – {dup['student_name']}.",
                               'duplicate_face', dup)
            ok = recognizer.update_student_samples(st['folder'], list(embs), [s['crop'] for s in samples])
        if not ok:
            raise ServiceError(500, 'Không cập nhật được mẫu khuôn mặt.', 'write_failed')
        self.models.invalidate(st['class_name'])
        # Replicate new face samples to all other classes where this student is enrolled!
        self._sync_face_to_all_classes(st['student_id'], st['folder'], st['class_name'])
        return self.get(pk)

    # ------------------------------------------------------------ edit/delete
    def update(self, pk, student_id=None, full_name=None):
        st = self.get(pk)
        new_id = _ident(normalize_student_id, student_id) if student_id is not None else st['student_id']
        new_name = _ident(normalize_name, full_name) if full_name is not None else st['full_name']
        if new_id == st['student_id'] and new_name == st['full_name']:
            return st
        cls = st['class_name']
        with self.db.read() as conn:
            if new_id != st['student_id'] and conn.execute(
                    'SELECT 1 FROM students WHERE class_name=? AND student_id=? AND active=1 AND id<>?',
                    (cls, new_id, pk)).fetchone():
                raise conflict(f'Mã sinh viên {new_id} đã tồn tại trong lớp {cls}.', 'duplicate_id')
        new_folder = student_folder(cls, new_id, new_name)
        recognizer = self.models.recognizer(cls) if self.models.state == 'ready' else None
        if recognizer is not None:
            ok = recognizer.edit_student(st['folder'], cls, new_id, new_name)
        else:
            old_dir = os.path.join(self.paths.class_dir(cls), st['folder'])
            new_dir = os.path.join(self.paths.class_dir(cls), new_folder)
            ok = os.path.isdir(old_dir) and (new_dir == old_dir or not os.path.exists(new_dir))
            if ok and new_dir != old_dir:
                from functions.face_recognizer import _move_with_retry
                _move_with_retry(old_dir, new_dir)
        if not ok:
            raise conflict('Không đổi tên được thư mục dữ liệu (đã tồn tại hoặc bị khóa).', 'rename_failed')
        now = clock.ts()
        with self.db.write() as conn:
            conn.execute('UPDATE students SET student_id=?, full_name=?, folder=?, updated_at=? WHERE id=?',
                         (new_id, new_name, new_folder, now, pk))
            # Only this class's history follows the edit; same ID elsewhere is untouched.
            conn.execute('UPDATE attendance SET student_id=?, student_name=?, student_pk=? '
                         'WHERE class_name=? AND (student_pk=? OR (student_pk IS NULL AND student_id=?))',
                         (new_id, new_name, pk, cls, pk, st['student_id']))
            conn.execute('UPDATE session_roster SET student_id=?, student_name=?, student_pk=? '
                         'WHERE session_id IN (SELECT id FROM sessions WHERE class_name=?) '
                         'AND (student_pk=? OR (student_pk IS NULL AND student_id=?))',
                         (new_id, new_name, pk, cls, pk, st['student_id']))
        self.models.invalidate(cls)
        self._rename_in_master_sheet(cls, st['student_id'], new_id, new_name)
        return self.get(pk)

    def _rename_in_master_sheet(self, cls, old_id, new_id, new_name):
        path = os.path.join(self.paths.class_dir(cls), 'attendance.xlsx')
        if not os.path.exists(path):
            return
        try:
            import pandas as pd
            df = pd.read_excel(path)
            df['Student ID'] = df['Student ID'].astype(str)
            mask = df['Student ID'] == str(old_id)
            df.loc[mask, 'Student ID'] = new_id
            df.loc[mask, 'Student Name'] = new_name
            df.to_excel(path, index=False)
        except Exception as exc:
            print(f'[WARNING] master sheet rename failed: {exc}')

    def delete(self, pk):
        st = self.get(pk)
        cls = st['class_name']
        if self.models.state == 'ready':
            ok = self.models.recognizer(cls).remove_student(st['folder'])
        else:
            from functions.face_recognizer import FaceRecognizer
            ok = FaceRecognizer.remove_student.__get__(_FolderOnly(self.paths.class_dir(cls)))(st['folder'])
        if not ok:
            raise ServiceError(500, 'Không xóa được thư mục dữ liệu khuôn mặt.', 'delete_failed')
        with self.db.write() as conn:
            conn.execute('UPDATE students SET active=0, updated_at=? WHERE id=?', (clock.ts(), pk))
        self.models.invalidate(cls)
        return {'deleted': pk, 'history_kept': st.get('attendance_count', 0)}


class _FolderOnly:
    """Minimal stand-in so remove_student works before the models are loaded."""

    def __init__(self, dataset_dir):
        import threading
        self.dataset_dir = dataset_dir
        self.embeddings_db = {}
        self._db_lock = threading.RLock()
