import json
import os
import re
import shutil
import threading
import time
from typing import Dict, List, Optional, Set

import cv2
import numpy as np
from insightface.app import FaceAnalysis

from functions.adaface_service import (
    DEFAULT_COSINE_THRESHOLD,
    DEFAULT_MIN_MARGIN,
    EMBEDDING_DIM,
    MODEL_ID,
    PREPROCESSING_VERSION,
    REVISION,
    WEIGHTS_SHA256,
    embed_detected_face,
    get_adaface_service,
)
from functions.identity import (
    normalize_class,
    normalize_name,
    normalize_student_id,
    parse_student_folder,
    student_folder,
)
from functions.matching import match

_insight_app = None
_insight_lock = threading.Lock()


def get_insight_app(det_size=(640, 640)):
    with _insight_lock:
        return _get_insight_app_locked(det_size)


def _get_insight_app_locked(det_size):
    global _insight_app
    if _insight_app is None:
        root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'models', 'insightface')
        # Detection only: identity embeddings come from AdaFace, so buffalo_sc's
        # ArcFace head would only cost time (and its vectors must not be matched).
        app = FaceAnalysis(name='buffalo_sc', root=root, providers=['CPUExecutionProvider'],
                           allowed_modules=['detection'])
        app.prepare(ctx_id=0, det_size=det_size)
        _disable_ort_spinning(app)
        _insight_app = app
    return _insight_app


def _disable_ort_spinning(app):
    """Stop ONNX Runtime threads from busy-waiting after each run.

    Spinning threads keep the CPU busy right when PyTorch runs AdaFace on the
    same cores; measured on an i5-13420H this made detect+AdaFace ~1.4 s
    instead of ~0.8 s per frame.
    """
    try:
        import onnxruntime as ort
        opts = ort.SessionOptions()
        opts.add_session_config_entry('session.intra_op.allow_spinning', '0')
        opts.intra_op_num_threads = 4
        for model in app.models.values():
            model.session = ort.InferenceSession(model.model_file, sess_options=opts,
                                                 providers=['CPUExecutionProvider'])
    except Exception as exc:  # keep the default sessions if this ORT build differs
        print(f'[WARNING] Could not disable ONNX Runtime spinning: {exc}')


def _move_with_retry(src, dst, attempts=20, delay=0.15):
    """Rename a folder; on Windows a file inside may be briefly locked."""
    for i in range(attempts):
        try:
            return shutil.move(src, dst)
        except PermissionError:
            if i == attempts - 1:
                raise
            time.sleep(delay)


class FaceRecognizer:
    def __init__(
        self,
        dataset_dir: str,
        threshold: float = DEFAULT_COSINE_THRESHOLD,
        min_margin: float = DEFAULT_MIN_MARGIN,
        adaface_service=None,
    ):
        self.dataset_dir = dataset_dir
        self.threshold = threshold
        self.min_margin = min_margin
        self.embeddings_db: Dict[str, np.ndarray] = {}
        self._db_lock = threading.RLock()
        os.makedirs(dataset_dir, exist_ok=True)
        self._app = get_insight_app()
        self.adaface = adaface_service or get_adaface_service()
        self._load_all_embeddings()
        print(f'[INFO] AdaFace Recognizer initialized for {os.path.basename(dataset_dir)}. {len(self.embeddings_db)} students loaded.')

    def recognize(self, frame: np.ndarray, face_raw=None, allowed_student_ids: Optional[Set[str]] = None) -> dict:
        """Extract AdaFace embedding from frame and match against class gallery."""
        try:
            if face_raw is None:
                faces = self._app.get(frame)
                if not faces:
                    return {'matched': False, 'score': 0.0, 'margin': 0.0, 'ambiguous': False}
                face_raw = faces[0]
            # Never face_raw.embedding: that is buffalo_sc's ArcFace vector, not AdaFace.
            embedding = embed_detected_face(self.adaface, frame, face_raw).reshape(1, -1)

            return self.recognize_embedding(embedding, allowed_student_ids=allowed_student_ids)
        except Exception as e:
            print(f'[ERROR] AdaFace recognize: {e}')
            return {'matched': False, 'score': 0.0, 'margin': 0.0, 'ambiguous': False}

    def recognize_embedding(self, embedding: np.ndarray, allowed_student_ids: Optional[Set[str]] = None) -> dict:
        """Match an embedding against the class gallery with open-set candidate & margin rules."""
        if not self.embeddings_db:
            return {'matched': False, 'score': 0.0, 'margin': 0.0, 'ambiguous': False}

        with self._db_lock:
            database = dict(self.embeddings_db)

        dim = np.asarray(embedding).reshape(-1).shape[0]
        valid_database = {}
        for folder, stored in database.items():
            if stored.shape[1] != dim:
                print(
                    f'[WARNING] Skipping {folder} due to dimension mismatch '
                    f'({stored.shape[1]} vs {dim}). Please run migration or re-enroll!'
                )
            else:
                valid_database[folder] = stored

        decision = match(
            embedding,
            valid_database,
            self.threshold,
            self.min_margin,
            allowed_student_ids=allowed_student_ids,
        )

        if decision['matched']:
            best_match = decision['identity']
            parsed = parse_student_folder(best_match)
            return {
                'class_name': parsed['class'],
                'student_id': parsed['id'],
                'student_name': parsed['name'] or 'Unknown',
                'score': decision['score'],
                'margin': decision['margin'],
                'matched': True,
                'folder': best_match,
                'ambiguous': False,
            }

        return {
            'matched': False,
            'score': decision['score'],
            'margin': decision.get('margin', 0.0),
            'ambiguous': decision['ambiguous'],
            'student_id': decision.get('best_student_id'),
        }

    def enroll_student(self, class_name, student_id, student_name, aligned_faces, face_crops=None):
        class_name = normalize_class(class_name)
        student_id = normalize_student_id(student_id)
        student_name = normalize_name(student_name)
        folder = student_folder(class_name, student_id, student_name)
        student_dir = os.path.join(self.dataset_dir, folder)

        with self._db_lock:
            if os.path.exists(student_dir) or any(
                s['id'].casefold() == student_id.casefold() for s in self.get_all_students()
            ):
                return False

            embeddings = self._extract_embeddings(aligned_faces)
            if not embeddings:
                return False

            emb_array = np.vstack(embeddings)
            # Duplicate check across class
            duplicate = self.recognize_embedding(emb_array.mean(axis=0, keepdims=True))
            if duplicate['matched'] or duplicate['score'] >= self.threshold:
                return False

            os.makedirs(student_dir)
            try:
                np.save(os.path.join(student_dir, 'embeddings.npy'), emb_array)
                # Save metadata for model provenance
                meta = {
                    'model_id': MODEL_ID,
                    'revision': REVISION,
                    'weights_sha256': WEIGHTS_SHA256,
                    'embedding_dim': EMBEDDING_DIM,
                    'preprocessing': PREPROCESSING_VERSION,
                    'sample_count': len(embeddings),
                    'enrolled_at': time.strftime('%Y-%m-%d %H:%M:%S'),
                }
                with open(os.path.join(student_dir, 'model_meta.json'), 'w', encoding='utf-8') as mf:
                    json.dump(meta, mf, indent=2)

                for i, img_or_emb in enumerate(aligned_faces):
                    save_img = (
                        face_crops[i]
                        if face_crops and i < len(face_crops)
                        else img_or_emb
                        if getattr(img_or_emb, 'ndim', 0) == 3
                        else np.zeros((112, 112, 3), dtype=np.uint8)
                    )
                    if not cv2.imwrite(os.path.join(student_dir, f'img_{i + 1:02d}.jpg'), save_img):
                        raise OSError('Cannot save enrollment image')

                self.embeddings_db[folder] = emb_array
            except Exception:
                shutil.rmtree(student_dir, ignore_errors=True)
                raise

        print(f'[INFO] Enrolled: {class_name} - {student_id} - {student_name} ({len(embeddings)} images)')
        return folder

    def _extract_embeddings(self, samples):
        embeddings = []
        for sample in samples:
            if isinstance(sample, np.ndarray) and sample.ndim == 1:
                emb = sample
            elif isinstance(sample, np.ndarray) and sample.ndim == 3:
                # Real face image: exactly one face, embedded with AdaFace.
                faces = self._app.get(sample)
                emb = embed_detected_face(self.adaface, sample, faces[0]) if len(faces) == 1 else None
            else:
                emb = None

            if emb is not None and np.isfinite(emb).all() and np.linalg.norm(emb) > 0:
                norm = float(np.linalg.norm(emb))
                unit_emb = (np.asarray(emb).flatten() / norm).astype(np.float32)
                embeddings.append(unit_emb)

        return embeddings

    def get_all_students(self):
        students = []
        if not os.path.exists(self.dataset_dir):
            return students
        for folder in sorted(os.listdir(self.dataset_dir)):
            fp = os.path.join(self.dataset_dir, folder)
            if not os.path.isdir(fp) or folder.startswith('.'):
                continue
            parsed = parse_student_folder(folder)
            photo_count = len([f for f in os.listdir(fp) if f.lower().endswith(('.jpg', '.jpeg', '.png'))])
            students.append({**parsed, 'folder': folder, 'photo_count': photo_count})
        return students

    def remove_student(self, folder_name):
        path = os.path.join(self.dataset_dir, folder_name)
        if not folder_name or os.path.dirname(folder_name) or not os.path.isdir(path):
            return False
        trash = os.path.join(self.dataset_dir, '.deleted')
        os.makedirs(trash, exist_ok=True)
        stamp = time.strftime('%Y%m%d_%H%M%S')
        with self._db_lock:
            _move_with_retry(path, os.path.join(trash, f'{folder_name}__{stamp}'))
            self.embeddings_db.pop(folder_name, None)
        print(f'[INFO] Removed student: {folder_name}')
        return True

    def update_student_samples(self, folder, samples, face_crops=None):
        student_dir = os.path.join(self.dataset_dir, folder)
        if not folder or os.path.dirname(folder):
            return False
        os.makedirs(student_dir, exist_ok=True)

        with self._db_lock:
            embeddings = self._extract_embeddings(samples)
            if not embeddings:
                return False

            emb_array = np.vstack(embeddings)
            parsed_curr = parse_student_folder(folder)
            others = {
                k: v
                for k, v in self.embeddings_db.items()
                if k != folder and parse_student_folder(k)['id'].casefold() != parsed_curr['id'].casefold()
            }
            if others:
                decision = match(emb_array.mean(axis=0, keepdims=True), others, self.threshold, self.min_margin)
                if decision['matched'] or decision['score'] >= self.threshold:
                    return False

            backup = os.path.join(student_dir, '.previous')
            shutil.rmtree(backup, ignore_errors=True)
            os.makedirs(backup)
            for name in os.listdir(student_dir):
                if name.lower().endswith(('.jpg', '.jpeg', '.png', '.npy', '.json')):
                    shutil.move(os.path.join(student_dir, name), os.path.join(backup, name))

            np.save(os.path.join(student_dir, 'embeddings.npy'), emb_array)
            meta = {
                'model_id': MODEL_ID,
                'revision': REVISION,
                'weights_sha256': WEIGHTS_SHA256,
                'embedding_dim': EMBEDDING_DIM,
                'preprocessing': PREPROCESSING_VERSION,
                'sample_count': len(embeddings),
                'updated_at': time.strftime('%Y-%m-%d %H:%M:%S'),
            }
            with open(os.path.join(student_dir, 'model_meta.json'), 'w', encoding='utf-8') as mf:
                json.dump(meta, mf, indent=2)

            for i, sample in enumerate(samples):
                img = (
                    face_crops[i]
                    if face_crops and i < len(face_crops)
                    else sample
                    if getattr(sample, 'ndim', 0) == 3
                    else np.zeros((112, 112, 3), dtype=np.uint8)
                )
                cv2.imwrite(os.path.join(student_dir, f'img_{i + 1:02d}.jpg'), img)

            self.embeddings_db[folder] = emb_array

        return True

    def edit_student(self, old_folder, new_class, new_id, new_name):
        new_class = normalize_class(new_class)
        new_id = normalize_student_id(new_id)
        new_name = normalize_name(new_name)
        new_folder = student_folder(new_class, new_id, new_name)
        old_dir = os.path.join(self.dataset_dir, old_folder)
        new_dir = os.path.join(self.dataset_dir, new_folder)

        with self._db_lock:
            if not os.path.exists(old_dir) or (new_dir != old_dir and os.path.exists(new_dir)):
                return False
            if new_dir != old_dir:
                _move_with_retry(old_dir, new_dir)
            if old_folder in self.embeddings_db:
                self.embeddings_db[new_folder] = self.embeddings_db.pop(old_folder)

        print(f'[INFO] Edited student: {old_folder} -> {new_folder}')
        return True

    def _load_all_embeddings(self):
        if not os.path.exists(self.dataset_dir):
            return
        for folder in os.listdir(self.dataset_dir):
            fp = os.path.join(self.dataset_dir, folder)
            if os.path.isdir(fp) and (not folder.startswith('.')):
                emb_file = os.path.join(fp, 'embeddings.npy')
                if os.path.exists(emb_file):
                    try:
                        arr = np.load(emb_file)
                        if arr.size and np.isfinite(arr).all():
                            self.embeddings_db[folder] = arr
                    except Exception as e:
                        print(f'[WARNING] Failed to load embeddings for {folder}: {e}')
