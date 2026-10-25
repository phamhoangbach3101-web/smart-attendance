"""Backend-side IP camera (RTSP) workers.

The backend opens the stream with connection/read timeouts, keeps only the
newest frame, runs the shared recognition pipeline at the configured rate and
exposes the newest JPEG for an MJPEG preview. Credentials in the URL are never
logged or returned; messages use the masked form.
"""
import threading
import time

import cv2

from backend.services.settings import mask_rtsp

OPEN_TIMEOUT_MS = 8000
READ_TIMEOUT_MS = 5000
MAX_RECONNECTS = 5
PREVIEW_MAX_WIDTH = 1280


class RtspWorker:
    def __init__(self, session_id, url, recognition, settings, sessions):
        self.session_id = session_id
        self._url = url
        self.masked_url = mask_rtsp(url)
        self.recognition = recognition
        self.settings = settings
        self.sessions = sessions
        self.state = 'connecting'
        self.error = None
        self.record = True
        self.frame_id = 0
        self.last_result = None
        self.last_jpeg = None
        self.fps = 0.0
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._run, name=f'rtsp-{session_id}', daemon=True)

    def start(self):
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()
        self._thread.join(timeout=3)
        self.state = 'stopped'

    def _open(self):
        params = [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, OPEN_TIMEOUT_MS, cv2.CAP_PROP_READ_TIMEOUT_MSEC, READ_TIMEOUT_MS]
        try:
            cap = cv2.VideoCapture(self._url, cv2.CAP_FFMPEG, params)
        except Exception:
            cap = cv2.VideoCapture(self._url, cv2.CAP_FFMPEG)
        if cap is not None and cap.isOpened():
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            return cap
        if cap is not None:
            cap.release()
        return None

    def _run(self):
        attempts = 0
        cap = None
        last_proc = 0.0
        frames, fps_t = 0, time.time()
        try:
            while not self._stop.is_set():
                if cap is None:
                    self.state = 'connecting' if attempts == 0 else 'reconnecting'
                    cap = self._open()
                    if cap is None:
                        attempts += 1
                        if attempts > MAX_RECONNECTS:
                            self.state = 'error'
                            self.error = f'Không kết nối được camera {self.masked_url} sau {MAX_RECONNECTS} lần thử.'
                            return
                        self._stop.wait(min(2 * attempts, 8))
                        continue
                    attempts = 0
                    self.state, self.error = 'live', None
                ok, frame = cap.read()
                if not ok or frame is None:
                    cap.release()
                    cap = None
                    attempts += 1
                    self.error = 'Mất kết nối camera, đang thử kết nối lại…'
                    continue
                if frame.shape[1] > PREVIEW_MAX_WIDTH:
                    scale = PREVIEW_MAX_WIDTH / frame.shape[1]
                    frame = cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
                frames += 1
                if time.time() - fps_t >= 1:
                    self.fps, frames, fps_t = round(frames / (time.time() - fps_t), 1), 0, time.time()
                ok, jpg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
                if ok:
                    with self._lock:
                        self.last_jpeg = jpg.tobytes()
                interval = 1.0 / max(1.0, float(self.settings.get()['frame_rate']))
                if time.time() - last_proc >= interval:
                    last_proc = time.time()
                    self.frame_id += 1
                    try:
                        res = self.recognition.process_frame(self.session_id, frame, self.frame_id,
                                                             record=self.record)
                    except Exception as exc:
                        res = {'frame_id': self.frame_id, 'session_id': self.session_id,
                               'status': 'error', 'message': f'Lỗi xử lý: {type(exc).__name__}', 'faces': []}
                    with self._lock:
                        self.last_result = res
                    if res.get('status') == 'session_closed':
                        self.state = 'stopped'
                        self.error = 'Phiên đã kết thúc.'
                        return
        finally:
            if cap is not None:
                cap.release()

    def jpeg(self):
        with self._lock:
            return self.last_jpeg

    def status(self):
        with self._lock:
            result = self.last_result
        return {'session_id': self.session_id, 'state': self.state, 'error': self.error,
                'url': self.masked_url, 'record': self.record, 'fps': self.fps,
                'frame_id': self.frame_id, 'result': result}


class RtspManager:
    def __init__(self, recognition, settings, sessions):
        self.recognition = recognition
        self.settings = settings
        self.sessions = sessions
        self._workers = {}
        self._lock = threading.Lock()

    def start(self, session_id, url, record=True):
        self.stop(session_id)
        worker = RtspWorker(session_id, url, self.recognition, self.settings, self.sessions)
        worker.record = record
        with self._lock:
            self._workers[session_id] = worker
        return worker.start().status()

    def get(self, session_id):
        with self._lock:
            return self._workers.get(session_id)

    def stop(self, session_id):
        with self._lock:
            worker = self._workers.pop(session_id, None)
        if worker:
            worker.stop()
        return worker is not None

    def stop_all(self):
        for sid in list(self._workers):
            self.stop(sid)
