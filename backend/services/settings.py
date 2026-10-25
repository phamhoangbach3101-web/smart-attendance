"""Recognition settings persisted in the SQLite ``settings`` table.

Defaults come from ``attendance_system/config.py`` so the web app starts with
exactly the behaviour of the desktop app until the user changes something.
"""
import json
import re
import threading

import config
from backend.errors import invalid

ANTISPOOF_MODES = ('off', 'model', 'texture_experimental')

DEFAULTS = {
    'cosine_threshold': float(config.RECOGNITION_COSINE_THRESHOLD),
    'adaface_cosine_threshold': 0.45,
    'min_margin': float(config.RECOGNITION_MIN_MARGIN),
    'detection_threshold': float(config.DETECTION_SCORE_THRESHOLD),
    'preprocessing': bool(config.ENABLE_PREPROCESSING),
    # config.ANTISPOOF_ENABLED=True meant "run AntiSpoof", which without the
    # ONNX file is the CV texture heuristic, hence the mapping below.
    'antispoof_mode': 'texture_experimental' if config.ANTISPOOF_ENABLED else 'off',
    'antispoof_threshold': float(config.ANTISPOOF_THRESHOLD),
    'frame_rate': 4.0,
    'default_duration_minutes': 15,
    'rtsp_url': '',
}

LIMITS = {
    'cosine_threshold': (0.3, 0.95),
    'adaface_cosine_threshold': (0.2, 0.95),
    'min_margin': (0.0, 0.5),
    'detection_threshold': (0.2, 0.95),
    'antispoof_threshold': (0.05, 0.99),
    'frame_rate': (1.0, 10.0),
    'default_duration_minutes': (0, 600),
}



def mask_rtsp(url):
    """Hide credentials: rtsp://user:pass@host -> rtsp://user:***@host."""
    if not url:
        return ''
    return re.sub(r'(rtsp://[^:/@\s]+):[^@\s]*@', r'\1:***@', re.sub(r'(rtsp://)[^:/@\s]+@', r'\1***@', url))


def validate_rtsp(url):
    url = (url or '').strip()
    if url and not re.match(r'^rtsps?://[^\s]+$', url, re.I):
        raise invalid('Địa chỉ camera phải bắt đầu bằng rtsp:// và không chứa khoảng trắng.')
    return url


class SettingsService:
    def __init__(self, db):
        self.db = db
        self._lock = threading.Lock()
        self._cache = None
        self.listeners = []

    def get(self):
        with self._lock:
            if self._cache is None:
                values = dict(DEFAULTS)
                with self.db.read() as conn:
                    for row in conn.execute('SELECT key, value FROM settings'):
                        if row['key'] in DEFAULTS:
                            try:
                                values[row['key']] = json.loads(row['value'])
                            except json.JSONDecodeError:
                                pass
                self._cache = values
            return dict(self._cache)

    def public(self):
        values = self.get()
        url = values.pop('rtsp_url')
        values['rtsp_url_masked'] = mask_rtsp(url)
        values['has_rtsp_url'] = bool(url)
        return values

    def update(self, changes):
        current = self.get()
        clean = {}
        for key, value in changes.items():
            if value is None or key not in DEFAULTS:
                continue
            if key in LIMITS:
                lo, hi = LIMITS[key]
                value = int(value) if key == 'default_duration_minutes' else float(value)
                if not lo <= value <= hi:
                    raise invalid(f'Giá trị "{key}" phải nằm trong khoảng {lo} – {hi}.')
            elif key == 'antispoof_mode':
                if value not in ANTISPOOF_MODES:
                    raise invalid('Chế độ chống giả mạo không hợp lệ.')
            elif key == 'preprocessing':
                value = bool(value)
            elif key == 'rtsp_url':
                value = validate_rtsp(value)
            clean[key] = value
        if not clean:
            return self.public()
        with self.db.write() as conn:
            for key, value in clean.items():
                conn.execute('INSERT INTO settings(key, value) VALUES (?, ?) '
                             'ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                             (key, json.dumps(value)))
        with self._lock:
            self._cache = {**current, **clean}
        for listener in self.listeners:
            listener(self.get())
        return self.public()
