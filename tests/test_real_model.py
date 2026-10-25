"""End-to-end check with the real InsightFace buffalo_sc model (no camera).

Uses an enrolment photo already present in attendance_system/dataset; the test
is skipped when the model files or such a photo are missing. It enrols the
face into a temporary data folder (the real dataset is only read), then sends
a frame through the same pipeline the web camera uses.
"""
import glob
import os

import cv2
import numpy as np
import pytest

from conftest import ROOT

DET_DIR = os.path.join(ROOT, 'attendance_system', 'models', 'insightface', 'models', 'buffalo_sc')
ADA_DIR = os.path.join(ROOT, 'attendance_system', 'models', 'cvlface_adaface_ir101_webface12m', 'pretrained_model')
PHOTOS = sorted(glob.glob(os.path.join(ROOT, 'attendance_system', 'dataset', '*', '*', 'img_01.jpg')))

pytestmark = pytest.mark.skipif(
    not (os.path.exists(os.path.join(DET_DIR, 'det_500m.onnx')) and os.path.exists(os.path.join(ADA_DIR, 'model.pt')) and PHOTOS),
    reason='real AdaFace model or enrolment photo not available')


def _frame_with(photo, size=(480, 640), x=200, y=60, width=220):
    img = cv2.imread(photo)
    face = cv2.resize(img, (width, int(width * img.shape[0] / img.shape[1])))
    frame = np.full((*size, 3), 128, np.uint8)
    h = min(face.shape[0], size[0] - y)
    frame[y:y + h, x:x + width] = face[:h]
    return cv2.imencode('.jpg', frame)[1].tobytes()


def test_real_model_enroll_and_recognise(data_dir, monkeypatch):
    import functions.face_recognizer as fr
    monkeypatch.setattr(fr, '_insight_app', None)     # force the real model
    from conftest import make_container
    c = make_container(data_dir)
    c.catalog.create_class('REAL1')
    c.catalog.create_course('REAL1', 'CPV301')
    jpg = _frame_with(PHOTOS[0])
    check = c.recognition.analyze_sample(jpg)
    assert check['ok'], check['message']
    st = c.students.enroll('REAL1', 'r001', '  Sinh   Viên Thử ', [jpg])
    assert st['student_id'] == 'R001' and st['face_status'] == 'enrolled'
    sid = c.sessions.open('REAL1', 'CPV301', 1, 10)['id']
    shifted = _frame_with(PHOTOS[0], x=260, y=90, width=200)    # different position/scale
    res = c.recognition.process_frame(sid, shifted, frame_id=1)
    assert res['status'] == 'recognized', res['message']
    assert res['student']['student_id'] == 'R001' and res['student']['score'] >= 0.45
    blank = cv2.imencode('.jpg', np.full((480, 640, 3), 128, np.uint8))[1].tobytes()
    assert c.recognition.process_frame(sid, blank, frame_id=2)['status'] == 'no_face'
