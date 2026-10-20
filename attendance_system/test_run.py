import os
import cv2
import numpy as np
import shutil
import traceback
from functions.face_detector import FaceDetector
from functions.face_recognizer import FaceRecognizer
from functions.biometrics_logger import BiometricsLogger

def run_test():
    print('Initializing...')
    det = FaceDetector()
    rec = FaceRecognizer('test_dataset')
    print('Detecting face...')
    frame = None
    for f in os.listdir('dataset'):
        for sub in os.listdir(os.path.join('dataset', f)):
            if sub.endswith('.jpg'):
                frame = cv2.imread(os.path.join('dataset', f, sub))
                break
        if frame is not None:
            break
    if frame is None:
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        cv2.circle(frame, (320, 240), 100, (255, 200, 200), -1)
    faces = det.detect_faces(frame)
    if not faces:
        print('No face detected in test frame, skipping test.')
        return
    face = faces[0]
    raw = face['raw']
    box = face['box']
    student_dir = 'test_dataset/TestClass_001_TestName'
    os.makedirs(student_dir, exist_ok=True)
    print('Testing create_enroll_log...')
    try:
        BiometricsLogger.create_enroll_log(student_dir, raw, box)
        print('create_enroll_log SUCCESS')
    except Exception as e:
        print(f'create_enroll_log FAILED: {e}')
        traceback.print_exc()
    print('Testing log_attendance...')
    try:
        BiometricsLogger.log_attendance(student_dir, raw, box)
        print('log_attendance SUCCESS')
    except Exception as e:
        print(f'log_attendance FAILED: {e}')
        traceback.print_exc()
    shutil.rmtree('test_dataset')
    print('Test complete.')
if __name__ == '__main__':
    run_test()
