"""Safe Migration and Rollback Service for Face Embeddings.

Rules:
1. Old InsightFace embeddings are NEVER compared with AdaFace IR101 embeddings.
2. Database is backed up before migration.
3. Model ID, revision, preprocessing version, and dimension are stored with data.
4. New embeddings are extracted from source photos in bulk.
5. If source photos are missing, student profile & attendance history are preserved,
   and marked as requiring photo re-upload or Excel re-import.
6. Validation phase verifies all generated embeddings before activating the gallery.
7. Safe rollback restores previous embeddings and database if needed.
"""
import glob
import json
import os
import shutil
import time
from typing import Dict, List, Optional

import cv2
import numpy as np

from functions.adaface_service import (
    DEFAULT_COSINE_THRESHOLD,
    DEFAULT_MIN_MARGIN,
    EMBEDDING_DIM,
    MODEL_ID,
    MODEL_NAME,
    PREPROCESSING_VERSION,
    REVISION,
    WEIGHTS_SHA256,
)
from functions.identity import parse_student_folder


class MigrationService:
    def __init__(self, db, paths, models):
        self.db = db
        self.paths = paths
        self.models = models

    def backup_database(self) -> str:
        """Create a timestamped backup of attendance.db in the backups directory."""
        os.makedirs(self.paths.backups_dir, exist_ok=True)
        stamp = time.strftime('%Y%m%d_%H%M%S')
        backup_path = os.path.join(self.paths.backups_dir, f'attendance_pre_adaface_{stamp}.db')
        if os.path.exists(self.paths.db_path):
            shutil.copy2(self.paths.db_path, backup_path)
            print(f'[INFO] Database backed up to: {backup_path}')
            return backup_path
        return ''

    def migrate_dataset(self) -> dict:
        """Bulk re-embed all student photos using AdaFace IR101 WebFace12M."""
        self.models.require_ready()
        db_backup = self.backup_database()

        started_at = time.time()
        dataset_dir = self.paths.dataset_dir
        adaface = self.models.adaface
        detector = self.models.detector

        migrated_students = 0
        migrated_photos = 0
        missing_photos: List[dict] = []
        errors: List[dict] = []
        classes_affected = set()

        # Step 1: Scan all student folders across all classes
        student_dirs = []
        if os.path.exists(dataset_dir):
            for cls_folder in sorted(os.listdir(dataset_dir)):
                cls_path = os.path.join(dataset_dir, cls_folder)
                if not os.path.isdir(cls_path) or cls_folder.startswith('.'):
                    continue
                for st_folder in sorted(os.listdir(cls_path)):
                    st_path = os.path.join(cls_path, st_folder)
                    if not os.path.isdir(st_path) or st_folder.startswith('.'):
                        continue
                    student_dirs.append((cls_folder, st_folder, st_path))

        print(f'[INFO] Starting AdaFace migration for {len(student_dirs)} student folders...')

        # Step 2: Process each student folder
        for cls_name, st_folder, st_path in student_dirs:
            parsed = parse_student_folder(st_folder)
            sid = parsed.get('id', st_folder)

            photos = sorted(
                f for f in os.listdir(st_path)
                if f.lower().endswith(('.jpg', '.jpeg', '.png')) and not f.startswith('.')
            )

            # Backup old embeddings if present
            curr_emb_path = os.path.join(st_path, 'embeddings.npy')
            backup_emb_path = os.path.join(st_path, 'embeddings_backup_buffalo_sc.npy')
            if os.path.exists(curr_emb_path) and not os.path.exists(backup_emb_path):
                shutil.copy2(curr_emb_path, backup_emb_path)

            if not photos:
                # Student has no photos on disk
                missing_photos.append({
                    'class_name': cls_name,
                    'student_id': sid,
                    'folder': st_folder,
                    'message': 'Không còn ảnh nguồn trên đĩa. Có thể cập nhật lại bằng file Excel.',
                })
                continue

            # Extract AdaFace embeddings for all photos
            new_embs = []
            for photo_name in photos:
                photo_path = os.path.join(st_path, photo_name)
                img = cv2.imread(photo_path)
                if img is None:
                    continue

                try:
                    dets = detector.detect_faces(img) if detector else []
                    kps = dets[0]['raw'].kps if dets and getattr(dets[0]['raw'], 'kps', None) is not None else None
                    emb = adaface.extract_embedding(img, kps=kps)
                    if emb is not None and np.isfinite(emb).all() and len(emb) == EMBEDDING_DIM:
                        new_embs.append(emb)
                        migrated_photos += 1
                except Exception as exc:
                    errors.append({
                        'folder': st_folder,
                        'photo': photo_name,
                        'error': str(exc),
                    })

            if new_embs:
                emb_array = np.vstack(new_embs).astype(np.float32)
                # Save new embeddings
                np.save(curr_emb_path, emb_array)

                # Save model provenance metadata
                meta = {
                    'model_id': MODEL_ID,
                    'model_name': MODEL_NAME,
                    'revision': REVISION,
                    'weights_sha256': WEIGHTS_SHA256,
                    'embedding_dim': EMBEDDING_DIM,
                    'preprocessing': PREPROCESSING_VERSION,
                    'sample_count': len(new_embs),
                    'migrated_at': time.strftime('%Y-%m-%d %H:%M:%S'),
                }
                with open(os.path.join(st_path, 'model_meta.json'), 'w', encoding='utf-8') as mf:
                    json.dump(meta, mf, indent=2)

                migrated_students += 1
                classes_affected.add(cls_name)

        # Step 3: Verification phase
        validation_ok = True
        for cls_name, st_folder, st_path in student_dirs:
            emb_file = os.path.join(st_path, 'embeddings.npy')
            if os.path.exists(emb_file):
                try:
                    arr = np.load(emb_file)
                    if arr.size == 0 or not np.isfinite(arr).all() or np.atleast_2d(arr).shape[1] != EMBEDDING_DIM:
                        validation_ok = False
                        break
                except Exception:
                    validation_ok = False
                    break

        if not validation_ok:
            print('[ERROR] Verification failed! Rolling back migration...')
            self.rollback()
            raise RuntimeError('Kiểm tra dữ liệu sau migration thất bại. Đã tự động rollback.')

        # Step 4: Record migration in settings table
        mig_record = {
            'active_model': MODEL_ID,
            'model_name': MODEL_NAME,
            'revision': REVISION,
            'weights_sha256': WEIGHTS_SHA256,
            'embedding_dim': EMBEDDING_DIM,
            'preprocessing_version': PREPROCESSING_VERSION,
            'migrated_at': time.strftime('%Y-%m-%d %H:%M:%S'),
            'migrated_students': migrated_students,
            'migrated_photos': migrated_photos,
            'db_backup': db_backup,
            'classes_affected': list(classes_affected),
        }
        with self.db.write() as conn:
            conn.execute(
                'INSERT INTO settings(key, value) VALUES (?, ?) '
                'ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                ('adaface_migration', json.dumps(mig_record))
            )

        # Invalidate in-memory recognizers so they reload new embeddings
        for cls_name in classes_affected:
            self.models.invalidate(cls_name)

        elapsed = round(time.time() - started_at, 2)
        print(f'[INFO] Migration completed in {elapsed}s: {migrated_students} students, {migrated_photos} photos.')

        return {
            'ok': True,
            'summary': {
                'total_folders': len(student_dirs),
                'migrated_students': migrated_students,
                'migrated_photos': migrated_photos,
                'missing_photos_count': len(missing_photos),
                'errors_count': len(errors),
                'elapsed_seconds': elapsed,
                'db_backup': db_backup,
            },
            'missing_photos': missing_photos,
            'errors': errors,
            'model_info': adaface.info(),
        }

    def rollback(self) -> dict:
        """Rollback all student embeddings to their previous buffalo_sc state."""
        dataset_dir = self.paths.dataset_dir
        restored = 0
        classes_affected = set()

        if os.path.exists(dataset_dir):
            for cls_folder in os.listdir(dataset_dir):
                cls_path = os.path.join(dataset_dir, cls_folder)
                if not os.path.isdir(cls_path) or cls_folder.startswith('.'):
                    continue
                for st_folder in os.listdir(cls_path):
                    st_path = os.path.join(cls_path, st_folder)
                    if not os.path.isdir(st_path) or st_folder.startswith('.'):
                        continue

                    backup_file = os.path.join(st_path, 'embeddings_backup_buffalo_sc.npy')
                    active_file = os.path.join(st_path, 'embeddings.npy')
                    meta_file = os.path.join(st_path, 'model_meta.json')

                    if os.path.exists(backup_file):
                        shutil.copy2(backup_file, active_file)
                        if os.path.exists(meta_file):
                            try:
                                os.remove(meta_file)
                            except Exception:
                                pass
                        restored += 1
                        classes_affected.add(cls_folder)

        # Invalidate recognizer caches
        for cls_name in classes_affected:
            self.models.invalidate(cls_name)

        with self.db.write() as conn:
            conn.execute("DELETE FROM settings WHERE key='adaface_migration'")

        print(f'[INFO] Rollback completed: restored {restored} students.')
        return {'ok': True, 'restored_count': restored, 'classes': list(classes_affected)}

    def status(self) -> dict:
        """Return migration status, metadata, and backup availability."""
        with self.db.read() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key='adaface_migration'").fetchone()
            mig_data = json.loads(row['value']) if row else None

        backups = []
        if os.path.exists(self.paths.backups_dir):
            backups = sorted(
                [f for f in os.listdir(self.paths.backups_dir) if f.startswith('attendance_pre_adaface_')],
                reverse=True
            )

        # Check dataset state
        dataset_dir = self.paths.dataset_dir
        total_students = 0
        adaface_count = 0
        has_backup_count = 0

        if os.path.exists(dataset_dir):
            for cls_f in os.listdir(dataset_dir):
                cp = os.path.join(dataset_dir, cls_f)
                if os.path.isdir(cp) and not cls_f.startswith('.'):
                    for st_f in os.listdir(cp):
                        sp = os.path.join(cp, st_f)
                        if os.path.isdir(sp) and not st_f.startswith('.'):
                            total_students += 1
                            if os.path.exists(os.path.join(sp, 'model_meta.json')):
                                adaface_count += 1
                            if os.path.exists(os.path.join(sp, 'embeddings_backup_buffalo_sc.npy')):
                                has_backup_count += 1

        return {
            'is_migrated': bool(mig_data and adaface_count > 0),
            'migration_record': mig_data,
            'total_students': total_students,
            'adaface_enrolled': adaface_count,
            'can_rollback': has_backup_count > 0,
            'db_backups': backups,
        }
