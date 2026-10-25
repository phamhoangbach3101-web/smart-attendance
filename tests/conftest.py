"""Shared fixtures for the web backend tests.

Most tests replace the neural networks with fakes: ``FakeInsightApp`` (SCRFD)
maps each solid-colour test frame to pre-registered faces, and ``FakeAdaFace``
returns the AdaFace embedding registered for each face's landmarks. Like the
real buffalo_sc model, every fake face also carries an unrelated ArcFace
vector in ``.embedding``; recognition only works if the code ignores it and
uses AdaFace. The real FaceDetector, FaceRecognizer, matching rule, AntiSpoof
and SQLite code all run unchanged. test_real_model.py uses the real models.
"""
import os
import sys

import cv2
import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import backend  # noqa: E402,F401  (puts attendance_system/ on sys.path)
import functions.face_recognizer as fr  # noqa: E402
from backend.app import create_app  # noqa: E402
from backend.container import Container  # noqa: E402
from backend.paths import AppPaths  # noqa: E402


def unit(v):
    v = np.asarray(v, dtype=np.float32)
    return v / np.linalg.norm(v)


class FakeFace:
    """Detector output: box, 5 landmarks and a decoy ArcFace vector (like buffalo_sc)."""

    def __init__(self, box, kps, arcface, det_score=0.9):
        x, y, w, h = box
        self.bbox = np.array([x, y, x + w, y + h], dtype=np.float32)
        self.kps = kps
        self.embedding = arcface
        self.det_score = det_score


class FakeAdaFace:
    """Stands in for AdaFaceService: returns the embedding registered for a face's landmarks."""

    state = 'ready'

    def __init__(self):
        self.by_kps = {}
        self.calls = 0

    def register(self, kps, embedding):
        self.by_kps[np.asarray(kps, dtype=np.float32).tobytes()] = embedding

    def extract_embedding(self, img_bgr, kps=None):
        self.calls += 1
        if kps is None:
            raise ValueError('no landmarks')
        emb = self.by_kps.get(np.asarray(kps, dtype=np.float32).tobytes())
        if emb is None:
            raise ValueError('unknown face')
        return np.asarray(emb, dtype=np.float32)

    def get_device_name(self):
        return 'CPU (fake)'

    def info(self):
        return {'model_id': 'fake-adaface', 'state': self.state, 'device': self.get_device_name()}


class FakeInsightApp:
    """Looks up faces by the frame's (rounded) background grey level."""

    def __init__(self, adaface):
        self.adaface = adaface
        self.scenes = {}
        self._next = 20
        self._uid = 0
        self.rng = np.random.default_rng(7)

    def scene(self, faces, size=(480, 640)):
        """Register faces [(box, adaface_embedding)], return JPEG bytes of a matching frame."""
        key = self._next
        self._next += 20
        assert key < 250, 'too many scenes'
        registered = []
        for box, emb in faces:
            self._uid += 1
            x, y, w, h = box
            # Unique landmarks per face so FakeAdaFace can tell faces apart.
            kps = np.array([[x + .3 * w, y + .4 * h], [x + .7 * w, y + .4 * h], [x + .5 * w, y + .6 * h],
                            [x + .35 * w, y + .8 * h], [x + .65 * w, y + .8 * h]], dtype=np.float32)
            kps += np.float32(self._uid * 1e-3)
            self.adaface.register(kps, emb)
            decoy = self.rng.normal(size=512).astype(np.float32)   # buffalo_sc's ArcFace vector
            registered.append((box, kps, decoy / np.linalg.norm(decoy)))
        self.scenes[key] = registered
        frame = np.full((*size, 3), key, dtype=np.uint8)
        ok, jpg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
        assert ok
        return jpg.tobytes()

    def get(self, frame):
        level = int(round(float(np.median(frame[:8, :8])) / 20.0) * 20)
        return [FakeFace(box, kps.copy(), arc) for box, kps, arc in self.scenes.get(level, [])]


@pytest.fixture
def fake_app(monkeypatch):
    import backend.services.recognition as rec
    adaface = FakeAdaFace()
    app = FakeInsightApp(adaface)
    monkeypatch.setattr(fr, '_insight_app', app)
    monkeypatch.setattr(rec, 'get_adaface_service', lambda *a, **k: adaface)
    return app


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    d = tmp_path / 'data'
    d.mkdir()
    monkeypatch.setenv('SA_FRONTEND_DIST', str(tmp_path / 'no_dist'))
    return str(d)


def make_container(data_dir, load=True):
    c = Container(AppPaths.from_env(data_dir))
    if load:
        c.models._load()
        assert c.models.state == 'ready', c.models.error
    return c


@pytest.fixture
def container(data_dir, fake_app):
    return make_container(data_dir)


@pytest.fixture
def client(container):
    from fastapi.testclient import TestClient
    app = create_app(container, load_models=False)
    with TestClient(app) as cl:
        cl.container = container
        yield cl


class Helpers:
    """Small API helpers so tests read like the user flow."""

    def __init__(self, client, fake):
        self.c = client
        self.fake = fake
        self.rng = np.random.default_rng(42)

    def course(self, cls, subject):
        self.c.post('/api/classes', json={'name': cls})
        r = self.c.post('/api/courses', json={'class_name': cls, 'subject': subject})
        assert r.status_code in (201, 409), r.text
        return r

    def new_embedding(self):
        return unit(self.rng.normal(size=512))

    def face_frame(self, emb, box=(200, 100, 200, 240), extra=()):
        return self.fake.scene([(box, emb), *extra])

    def enroll(self, cls, sid, name, emb=None, samples=2):
        emb = self.new_embedding() if emb is None else emb
        files = []
        for i in range(samples):
            noisy = unit(emb + 0.02 * self.rng.normal(size=512))
            files.append(('files', (f's{i}.jpg', self.face_frame(noisy), 'image/jpeg')))
        r = self.c.post('/api/students', data={'class_name': cls, 'student_id': sid, 'full_name': name}, files=files)
        return r, emb

    def open(self, cls, subject, slot=1, minutes=15, **kw):
        return self.c.post('/api/sessions', json={'class_name': cls, 'subject': subject, 'slot': slot,
                                                  'duration_minutes': minutes, **kw})

    def frame(self, session_id, jpg, record=True, frame_id=1):
        r = self.c.post(f'/api/sessions/{session_id}/frame',
                        files={'file': ('f.jpg', jpg, 'image/jpeg')},
                        data={'frame_id': str(frame_id), 'record': '1' if record else '0'})
        assert r.status_code == 200, r.text
        return r.json()


@pytest.fixture
def h(client, fake_app):
    return Helpers(client, fake_app)
