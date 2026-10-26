"""Model loading and the per-frame recognition pipeline.

Upgraded to AdaFace IR101 WebFace12M (512-dim embedding):
- Face detection: SCRFD (InsightFace det_500m) with 5 facial landmarks.
- Face alignment: Similarity transform to 112x112 aligned face crop.
- Feature extraction: Official AdaFace IR101 WebFace12M in eval/inference mode.
- Matching: Open-set cosine similarity with candidate aggregation by student ID,
  top-1 vs top-2 distinct student margin, and session roster filtering.
- Anti-spoofing: MiniFASNet / texture heuristic.
"""
import os
import threading
import time

import cv2
import numpy as np

import config
from backend.errors import ServiceError
from functions.adaface_service import (
    DEFAULT_COSINE_THRESHOLD,
    DEFAULT_MIN_MARGIN,
    EMBEDDING_DIM,
    MODEL_ID,
    MODEL_NAME,
    PREPROCESSING_VERSION,
    REVISION,
    WEIGHTS_SHA256,
    embed_detected_face,
    get_adaface_service,
)
from functions.biometrics_logger import BiometricsLogger
from functions.preprocessor import Preprocessor

MAX_FRAME_BYTES = 3 * 1024 * 1024
# Face tracking: while the same face stays in place (box IoU >= threshold), reuse the
# last AdaFace decision instead of re-running the ~0.7 s CPU model on every frame.
TRACK_IOU = config.RECOGNITION_BOX_IOU_THRESHOLD
TRACK_MATCH_SECONDS = 2.5      # re-verify a recognised student at least this often
TRACK_REJECT_SECONDS = 1.0     # retry strangers / ambiguous faces sooner
# Mean grey-level difference (0-255) of 32x32 face thumbnails between consecutive
# frames above which the face is treated as a different person and re-verified.
TRACK_MAX_APPEARANCE_DIFF = 20.0
MIN_SIDE, MAX_SIDE = 64, 4096
MIN_ENROLL_FACE_RATIO = 0.03

MESSAGES = {
    'preview': 'Đang xem trước — bật "Tự động nhận diện" để ghi điểm danh.',
    'no_face': 'Không tìm thấy khuôn mặt trong khung hình.',
    'multiple_faces': 'Có nhiều khuôn mặt — chỉ một người đứng trước camera.',
    'unknown': 'Người lạ — không khớp sinh viên nào của lớp.',
    'ambiguous': 'Không thể xác minh — khuôn mặt giống nhiều sinh viên, chênh lệch quá nhỏ.',
    'unverifiable': 'Không thể xác minh khuôn mặt.',
    'spoof_rejected': 'Bị từ chối bởi kiểm tra chống giả mạo.',
    'spoof_error': 'Không thể xác minh chống giả mạo — không ghi điểm danh.',
    'recognized': 'Đã ghi nhận điểm danh.',
    'already_recorded': 'Sinh viên đã được điểm danh trong phiên này.',
    'session_closed': 'Phiên đã kết thúc — kết quả không được ghi.',
    'no_students': 'Lớp chưa có sinh viên nào đăng ký khuôn mặt.',
    'model_loading': 'Model đang tải, vui lòng chờ…',
    'model_unavailable': 'Model nhận diện không khả dụng.',
    'invalid_frame': 'Khung hình không hợp lệ.',
}


def decode_image(data):
    """Validate size and decode JPEG/PNG bytes to a BGR frame."""
    if isinstance(data, np.ndarray):
        frame = data
    else:
        if not data:
            raise ServiceError(422, 'Ảnh rỗng.', 'invalid_frame')
        if len(data) > MAX_FRAME_BYTES:
            raise ServiceError(413, 'Ảnh vượt quá 3 MB.', 'frame_too_large')
        frame = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    if frame is None or frame.ndim != 3 or frame.shape[2] != 3:
        raise ServiceError(422, 'Không đọc được ảnh (chỉ hỗ trợ JPEG/PNG).', 'invalid_frame')
    h, w = frame.shape[:2]
    if min(h, w) < MIN_SIDE or max(h, w) > MAX_SIDE:
        raise ServiceError(422, f'Kích thước ảnh phải từ {MIN_SIDE} đến {MAX_SIDE} px.', 'invalid_frame')
    return frame


class ModelManager:
    """Owns SCRFD detector, AdaFace IR101 recognizer, and anti-spoof module."""

    def __init__(self, paths, settings):
        self.paths = paths
        self.settings = settings
        self.state = 'idle'
        self.error = None
        self.loaded_at = None
        self.load_seconds = None
        self.detector = None
        self.adaface = None
        self.anti_spoof = None
        self.preprocessor = Preprocessor(
            config.FACE_SIZE, config.GAUSSIAN_KERNEL, config.CLAHE_CLIP, config.CLAHE_GRID
        )
        self.lock = threading.RLock()
        self._recognizers = {}
        self._state_lock = threading.Lock()
        self.invalidate_listeners = []      # called when a class gallery changes
        settings.listeners.append(self._apply_settings)

    # ------------------------------------------------------------------ loading
    def detector_files(self):
        base = os.path.join(self.paths.models_dir, 'insightface', 'models', 'buffalo_sc')
        files = {n: os.path.exists(os.path.join(base, n)) for n in ('det_500m.onnx',)}
        return base, files

    def adaface_files(self):
        base = os.path.join(self.paths.models_dir, 'cvlface_adaface_ir101_webface12m')
        files = {
            'model.pt': os.path.exists(os.path.join(base, 'pretrained_model', 'model.pt')),
            'model.yaml': os.path.exists(os.path.join(base, 'pretrained_model', 'model.yaml')),
        }
        return base, files

    def antispoof_model_path(self):
        return os.path.join(self.paths.models_dir, 'anti_spoof_minifas.onnx')

    def load_async(self):
        with self._state_lock:
            if self.state in ('loading', 'ready'):
                return
            self.state = 'loading'
            self.error = None
        threading.Thread(target=self._load, name='model-loader', daemon=True).start()

    def _load(self):
        started = time.time()
        try:
            from functions.anti_spoof import AntiSpoof
            from functions.face_detector import FaceDetector

            s = self.settings.get()
            with self.lock:
                # 1. Face Detector (SCRFD)
                self.detector = FaceDetector(s['detection_threshold'])
                # 2. Anti-Spoof
                self.anti_spoof = AntiSpoof(self.paths.models_dir, threshold=s['antispoof_threshold'])
                # 3. AdaFace IR101 WebFace12M
                ada_dir = os.path.join(self.paths.models_dir, 'cvlface_adaface_ir101_webface12m')
                self.adaface = get_adaface_service(ada_dir)

            self.load_seconds = round(time.time() - started, 1)
            self.loaded_at = time.strftime('%Y-%m-%d %H:%M:%S')
            self.state = 'ready'
            print(f'[INFO] Models ready in {self.load_seconds}s (AdaFace IR101 on {self.adaface.get_device_name()})')
        except Exception as exc:
            self.state = 'error'
            self.error = f'{type(exc).__name__}: {exc}'
            print(f'[ERROR] Model loading failed: {self.error}')

    def wait_ready(self, timeout=120):
        end = time.time() + timeout
        while self.state == 'loading' and time.time() < end:
            time.sleep(0.1)
        return self.state == 'ready'

    def require_ready(self):
        if self.state == 'ready':
            return
        if self.state in ('idle', 'loading'):
            raise ServiceError(503, MESSAGES['model_loading'], 'model_loading')
        raise ServiceError(
            503,
            f'{MESSAGES["model_unavailable"]} {self.error or ""}'.strip(),
            'model_unavailable',
        )

    def _apply_settings(self, s):
        with self.lock:
            if self.detector is not None:
                self.detector.score_threshold = s['detection_threshold']
            if self.anti_spoof is not None:
                self.anti_spoof.threshold = s['antispoof_threshold']
            threshold = s.get('adaface_cosine_threshold', s.get('cosine_threshold', DEFAULT_COSINE_THRESHOLD))
            for rec in self._recognizers.values():
                rec.threshold = threshold
                rec.min_margin = s['min_margin']

    # -------------------------------------------------------------- recognizers
    def recognizer(self, class_name):
        self.require_ready()
        from functions.face_recognizer import FaceRecognizer

        with self.lock:
            rec = self._recognizers.get(class_name)
            if rec is None:
                s = self.settings.get()
                threshold = s.get('adaface_cosine_threshold', s.get('cosine_threshold', DEFAULT_COSINE_THRESHOLD))
                rec = FaceRecognizer(
                    self.paths.class_dir(class_name),
                    threshold=threshold,
                    min_margin=s['min_margin'],
                    adaface_service=self.adaface,
                )
                self._recognizers[class_name] = rec
            return rec

    def invalidate(self, class_name=None):
        with self.lock:
            if class_name is None:
                self._recognizers.clear()
            else:
                self._recognizers.pop(class_name, None)
        for listener in self.invalidate_listeners:
            listener(class_name)

    # ------------------------------------------------------------------ status
    def antispoof_status(self):
        mode = self.settings.get()['antispoof_mode']
        has_model = bool(self.anti_spoof and self.anti_spoof.has_model)
        if mode == 'off':
            state, text = 'off', 'Đang tắt'
        elif mode == 'model':
            if self.state != 'ready':
                state, text = 'loading', 'Đang tải'
            elif has_model:
                state, text = 'ready', 'Đang bật — model MiniFASNet sẵn sàng'
            else:
                state, text = 'missing_model', (
                    'Được bật nhưng thiếu model anti_spoof_minifas.onnx — mọi lượt điểm danh sẽ bị chặn'
                )
        else:
            state, text = 'experimental', (
                'Đang bật thuật toán texture THỬ NGHIỆM (chưa được kiểm thử như model chống giả mạo)'
            )
        return {
            'mode': mode,
            'state': state,
            'text': text,
            'has_model': has_model,
            'model_path': self.antispoof_model_path(),
        }

    def status(self):
        det_dir, det_files = self.detector_files()
        ada_dir, ada_files = self.adaface_files()
        ada_info = self.adaface.info() if self.adaface else None
        return {
            'state': self.state,
            'error': self.error,
            'loaded_at': self.loaded_at,
            'load_seconds': self.load_seconds,
            'detector': {'dir': det_dir, 'files': det_files},
            'adaface': ada_info,
            'model_id': MODEL_ID,
            'model_name': MODEL_NAME,
            'revision': REVISION,
            'weights_sha256': WEIGHTS_SHA256,
            'device': self.adaface.get_device_name() if self.adaface else 'Chưa khởi tạo',
            'embedding_dim': EMBEDDING_DIM,
            'preprocessing': PREPROCESSING_VERSION,
            'model_dir': ada_dir,
            'files': ada_files,
            'antispoof': self.antispoof_status(),
        }


class RecognitionService:
    def __init__(self, models, settings, sessions, students):
        self.models = models
        self.settings = settings
        self.sessions = sessions
        self.students = students
        self._bio_logged = set()
        self._tracks = {}                    # session_id -> last AdaFace decision for the tracked face
        self._track_lock = threading.Lock()
        self._clock = time.monotonic
        models.invalidate_listeners.append(lambda _cls: self._clear_tracks())

    # ------------------------------------------------------------- detection
    def _detect(self, frame, s):
        if s['preprocessing']:
            enhanced = self.models.preprocessor.enhance(frame)
            frame = enhanced if enhanced is not None else frame
        dets = self.models.detector.detect_faces(frame)
        primary, blockers, incidental = self.models.detector.select_primary_face(
            dets, frame.shape, config.INCIDENTAL_FACE_MAX_FRAME_RATIO, config.INCIDENTAL_FACE_MAX_PRIMARY_RATIO
        )
        return frame, dets, primary, blockers, incidental

    @staticmethod
    def _face(det, role, state, label, score=None):
        x, y, w, h = (int(v) for v in det['box'])
        f = {
            'box': [x, y, w, h],
            'role': role,
            'state': state,
            'label': label,
            'det_score': round(float(det['confidence']), 3),
        }
        if score is not None:
            f['score'] = score
        return f

    def _antispoof(self, frame, det, s):
        mode = s['antispoof_mode']
        if mode == 'off':
            return {'state': 'off', 'ok': True}
        spoof = self.models.anti_spoof
        if spoof is None:
            return {'state': 'error', 'ok': False, 'error': 'anti-spoof not loaded'}
        if mode == 'model' and not spoof.has_model:
            return {'state': 'missing_model', 'ok': False, 'error': 'anti-spoof model missing'}
        res = spoof.predict(frame, det['box'], allow_texture=(mode == 'texture_experimental'))
        if res.get('label') == 'ERROR':
            return {'state': 'error', 'ok': False, 'error': res.get('error'), 'live_score': None}
        return {
            'state': 'live' if res['is_real'] else 'spoof',
            'ok': bool(res['is_real']),
            'live_score': res.get('live_score'),
            'experimental': mode == 'texture_experimental',
        }

    # ---------------------------------------------------------------- pipeline
    def process_frame(self, session_id, data, frame_id=0, record=True):
        """Run the full AdaFace IR101 pipeline on one frame of an attendance session."""
        out = {
            'frame_id': frame_id,
            'session_id': session_id,
            'status': None,
            'faces': [],
            'student': None,
            'attendance': None,
            'antispoof': None,
            'width': None,
            'height': None,
        }

        def done(status, message=None):
            out['status'] = status
            out['message'] = message or MESSAGES.get(status, '')
            out['processed_at'] = time.strftime('%H:%M:%S')
            return out

        session = self.sessions.get(session_id)
        out['class_name'] = session['class_name']
        if session['state'] != 'active':
            return done('session_closed')
        try:
            frame = decode_image(data)
        except ServiceError as exc:
            return done('invalid_frame', exc.message)
        out['height'], out['width'] = frame.shape[:2]
        if self.models.state != 'ready':
            return done('model_loading' if self.models.state in ('idle', 'loading') else 'model_unavailable')

        s = self.settings.get()
        with self.models.lock:
            frame, dets, primary, blockers, incidental = self._detect(frame, s)
            if not dets or blockers:
                self._clear_tracks(session_id)      # face left or someone joined: verify again
            if not dets:
                return done('no_face')
            if blockers:
                out['faces'] = [
                    self._face(
                        d,
                        'primary' if d is primary else 'blocker',
                        'multiple',
                        'Nhiều khuôn mặt',
                    )
                    for d in dets
                ]
                return done('multiple_faces')

            out['faces'] = [self._face(d, 'incidental', 'ignored', 'Bỏ qua (xa camera)') for d in incidental]
            face = self._face(primary, 'primary', 'pending', 'Đang xử lý')
            out['faces'].insert(0, face)
            if not record:
                self._clear_tracks(session_id)
                face.update(state='detected', label='Đã phát hiện')
                return done('preview')

            thumb = self._thumb(frame, primary['box'])
            cached = self._track_hit(session_id, primary['box'], thumb)
            if cached is not None:
                out['cached'] = True
                face.update(state=cached['face_state'], label=cached['label'], score=cached['score'])
                out['student'] = cached['student']
                out['attendance'] = cached['attendance']
                return done(cached['status'], cached['message'])

            spoof = self._antispoof(frame, primary, s)
            out['antispoof'] = spoof
            if not spoof['ok']:
                if spoof['state'] == 'spoof':
                    face.update(state='spoof', label='Giả mạo')
                    return done('spoof_rejected')
                face.update(state='unverifiable', label='Không thể xác minh')
                return done(
                    'spoof_error',
                    MESSAGES['spoof_error'] + (' (thiếu model)' if spoof['state'] == 'missing_model' else ''),
                )

            # Feature extraction with AdaFace IR101
            try:
                emb = embed_detected_face(self.models.adaface, frame, primary.get('raw'))
            except Exception as exc:
                face.update(state='unverifiable', label='Lỗi trích xuất')
                return done('unverifiable', f'Lỗi trích xuất đặc trưng AdaFace: {exc}')

            if emb is None or not np.isfinite(emb).all() or float(np.linalg.norm(emb)) == 0:
                face.update(state='unverifiable', label='Không thể xác minh')
                return done('unverifiable', 'Không trích xuất được đặc trưng khuôn mặt.')

            recognizer = self.models.recognizer(session['class_name'])
            if not recognizer.embeddings_db:
                face.update(state='unknown', label='Chưa có dữ liệu lớp')
                return done('no_students')

            # Filter gallery to active session roster
            records = self.sessions.records(session_id).get('records', [])
            roster_sids = {r['student_id'].strip().upper() for r in records} if records else None

            result = recognizer.recognize_embedding(np.asarray(emb).reshape(1, -1), allowed_student_ids=roster_sids)

        score = round(float(result.get('score', 0.0)), 4)
        face['score'] = score
        if not result['matched']:
            if result.get('ambiguous'):
                face.update(state='unverifiable', label='Không thể xác minh')
                self._remember(session_id, primary['box'], thumb, 'ambiguous', face, None, None,
                               MESSAGES['ambiguous'], TRACK_REJECT_SECONDS)
                return done('ambiguous')
            face.update(state='unknown', label='Người lạ')
            self._remember(session_id, primary['box'], thumb, 'unknown', face, None, None,
                           MESSAGES['unknown'], TRACK_REJECT_SECONDS)
            return done('unknown')

        student = {
            'student_id': result['student_id'],
            'student_name': result['student_name'],
            'score': score,
            'margin': round(float(result.get('margin', 0.0)), 4),
            'folder': result['folder'],
        }
        out['student'] = student
        saved = self.sessions.record(session_id, student['student_id'], student['student_name'], score)
        out['attendance'] = saved
        if saved['status'] == 'session_closed':
            face.update(state='unverifiable', label='Phiên đã kết thúc')
            return done('session_closed')

        face.update(state='recognized', label=f"{student['student_id']} · {student['student_name']}")
        self._remember(session_id, primary['box'], thumb, 'already_recorded', face, student, saved,
                       f"{student['student_name']} đã điểm danh lúc {(saved['timestamp'] or '')[-8:]} "
                       f"· Điểm tương đồng: {score:.2f}", TRACK_MATCH_SECONDS)
        if saved['status'] == 'inserted':
            self._log_biometrics(session, student, primary)
            return done(
                'recognized',
                f"Đã điểm danh: {student['student_name']} ({student['student_id']}) · Điểm tương đồng: {score:.2f}",
            )
        return done(
            'already_recorded',
            f"{student['student_name']} đã điểm danh lúc {(saved['timestamp'] or '')[-8:]} · Điểm tương đồng: {score:.2f}",
        )

    # ---------------------------------------------------------------- tracking
    @staticmethod
    def _iou(a, b):
        ax, ay, aw, ah = a
        bx, by, bw, bh = b
        iw = max(0, min(ax + aw, bx + bw) - max(ax, bx))
        ih = max(0, min(ay + ah, by + bh) - max(ay, by))
        inter = iw * ih
        union = aw * ah + bw * bh - inter
        return inter / union if union > 0 else 0.0

    def _clear_tracks(self, session_id=None):
        with self._track_lock:
            if session_id is None:
                self._tracks.clear()
            else:
                self._tracks.pop(session_id, None)

    @staticmethod
    def _thumb(frame, box):
        x, y, w, h = (int(v) for v in box)
        crop = frame[max(0, y):y + h, max(0, x):x + w]
        if crop.size == 0:
            return None
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        return cv2.resize(gray, (32, 32), interpolation=cv2.INTER_AREA).astype(np.float32)

    def _track_hit(self, session_id, box, thumb):
        """Last decision for this session if the same face is still in place, unchanged and fresh.

        A cache hit never records attendance; at worst a swapped face shows the
        previous label until the next AdaFace check (at most TRACK_MATCH_SECONDS).
        """
        with self._track_lock:
            track = self._tracks.get(session_id)
            if track is None:
                return None
            same_place = self._iou(track['box'], box) >= TRACK_IOU
            same_look = (thumb is not None and track['thumb'] is not None and
                         float(np.abs(track['thumb'] - thumb).mean()) <= TRACK_MAX_APPEARANCE_DIFF)
            if self._clock() >= track['expires'] or not (same_place and same_look):
                self._tracks.pop(session_id, None)
                return None
            track['box'], track['thumb'] = tuple(box), thumb    # follow the face frame to frame
            return track

    def _remember(self, session_id, box, thumb, status, face, student, attendance, message, seconds):
        with self._track_lock:
            self._tracks[session_id] = {
                'box': tuple(box), 'thumb': thumb, 'expires': self._clock() + seconds, 'status': status,
                'face_state': face['state'], 'label': face['label'], 'score': face.get('score'),
                'student': student, 'attendance': attendance, 'message': message,
            }

    def _log_biometrics(self, session, student, det):
        key = (session['id'], student['folder'])
        if key in self._bio_logged or det.get('raw') is None:
            return
        self._bio_logged.add(key)
        student_dir = os.path.join(self.models.paths.class_dir(session['class_name']), student['folder'])
        threading.Thread(target=self._safe_bio, args=(student_dir, det['raw'], det['box']), daemon=True).start()

    @staticmethod
    def _safe_bio(student_dir, raw, box):
        try:
            BiometricsLogger.log_attendance(student_dir, raw, box)
        except Exception as exc:
            print(f'[WARNING] biometrics log failed: {exc}')

    # -------------------------------------------------------------- enrollment
    def analyze_sample(self, data):
        """Check one enrollment photo: single face, landmarks, and AdaFace IR101 embedding."""
        frame = decode_image(data)
        self.models.require_ready()
        s = self.settings.get()
        with self.models.lock:
            frame, dets, primary, blockers, _ = self._detect(frame, s)
        h, w = frame.shape[:2]
        base = {'ok': False, 'width': w, 'height': h, 'box': None}
        if not dets:
            return {**base, 'reason': 'no_face', 'message': 'Không tìm thấy khuôn mặt.'}
        if blockers:
            return {
                **base,
                'reason': 'multiple_faces',
                'message': 'Có nhiều khuôn mặt — chỉ một người trong khung hình.',
            }
        x, y, bw, bh = (int(v) for v in primary['box'])
        base['box'] = [x, y, bw, bh]
        if (bw * bh) / float(w * h) <= MIN_ENROLL_FACE_RATIO:
            return {**base, 'reason': 'too_small', 'message': 'Khuôn mặt quá nhỏ — lại gần camera hơn.'}

        try:
            with self.models.lock:
                emb = embed_detected_face(self.models.adaface, frame, primary.get('raw'))
        except Exception as exc:
            return {**base, 'reason': 'bad_embedding', 'message': f'Lỗi trích xuất AdaFace: {exc}'}

        if emb is None or not np.isfinite(emb).all() or float(np.linalg.norm(emb)) == 0:
            return {**base, 'reason': 'bad_embedding', 'message': 'Không trích xuất được đặc trưng khuôn mặt.'}

        crop = frame[max(0, y) : y + bh, max(0, x) : x + bw].copy()
        return {
            **base,
            'ok': True,
            'reason': None,
            'message': 'Mẫu hợp lệ.',
            'det_score': round(float(primary['confidence']), 3),
            'embedding': np.asarray(emb, dtype=np.float32).flatten(),
            'crop': crop,
            'raw': primary['raw'],
            'det_box': primary['box'],
        }
