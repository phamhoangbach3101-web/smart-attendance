import sys, os, cv2
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from functions.anti_spoof import AntiSpoof
from functions.face_detector import FaceDetector
from config import MODELS_DIR
spoof = AntiSpoof(MODELS_DIR, threshold=0.0)
detect = FaceDetector()
cap = cv2.VideoCapture(0)
print('\n=== Anti-Spoof Calibration ===')
print('Nhìn thẳng vào camera. Sau đó thử giơ điện thoại/ảnh vào.')
print("Xem cột 'live_score' để chọn ngưỡng phù hợp.")
print('Nhấn Q để thoát.\n')
frame_idx = 0
while True:
    ret, frame = cap.read()
    if not ret:
        break
    dets = detect.detect_faces(frame)
    display = frame.copy()
    for det in dets:
        x, y, w, h = det['box']
        res = spoof.predict(frame, det['box'])
        score = res['live_score']
        color = (0, 220, 80) if score >= 0.55 else (0, 50, 255)
        cv2.rectangle(display, (x, y), (x + w, y + h), color, 2)
        cv2.putText(display, f'Score: {score:.3f}', (x, y - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
        if frame_idx % 10 == 0:
            print(f'[Frame {frame_idx:04d}] live_score={score:.4f}  (Nếu mặt thật: ghi nhớ giá trị này)')
    cv2.putText(display, 'Q to quit | Score xem console', (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 1)
    cv2.imshow('Anti-Spoof Calibration', display)
    frame_idx += 1
    if cv2.waitKey(1) & 255 == ord('q'):
        break
cap.release()
cv2.destroyAllWindows()
