import os
import requests
import json

import os as _os
import pytest as _pytest

# Talks to the running app on 127.0.0.1:8000 and creates/deletes classes and students in the
# REAL database. Opt in explicitly:  set SA_LIVE_SERVER_TESTS=1
pytestmark = _pytest.mark.skipif(_os.environ.get('SA_LIVE_SERVER_TESTS') != '1',
                                 reason='live-server test; set SA_LIVE_SERVER_TESTS=1 to run')

BASE = "http://127.0.0.1:8000"

def test_all():
    print("=== STARTING COMPREHENSIVE REFACTOR TEST SUITE ===")
    
    # 1. Health check
    r = requests.get(f"{BASE}/api/health")
    assert r.status_code == 200, f"Health check failed: {r.text}"
    health = r.json()
    assert health['ok'] is True
    print("[PASS] 1. API Health is OK and models are loaded.")

    # 2. Favicons verification
    for fav_path in ['/favicon.svg', '/smart-attendance-favicon.png', '/favicon.ico', '/favicon-32x32.png', '/favicon-192x192.png']:
        r = requests.get(f"{BASE}{fav_path}")
        assert r.status_code == 200, f"Favicon {fav_path} not found"
        assert len(r.content) > 0, f"Favicon {fav_path} is empty"
    print("[PASS] 2. All favicon formats (SVG, PNG, ICO) served with 200 OK.")

    # 3. HTML index has updated title, navigation, and favicon links
    r = requests.get(f"{BASE}/")
    assert r.status_code == 200
    html = r.text
    assert 'rel="icon"' in html
    assert 'smart-attendance-favicon.png' in html
    assert 'favicon.svg' in html
    assert 'Smart Attendance' in html
    print("[PASS] 3. Index HTML contains all favicon links and proper metadata.")

    # 4. Classes list from database
    r = requests.get(f"{BASE}/api/classes")
    assert r.status_code == 200
    classes = r.json()
    assert len(classes) >= 1
    class_names = [c['name'] for c in classes]
    print(f"[PASS] 4. Classes loaded from database: {class_names}")

    # 5. Face check endpoint (/api/enrollment/check)
    # A) Valid face sample from dataset
    import numpy as np, cv2
    sample_face = "attendance_system/dataset/HE201068/HE201068_HE201068_Phạm_Hoàng_Bách/img_01.jpg"
    assert os.path.exists(sample_face), f"Missing test image: {sample_face}"
    img_data = cv2.imread(sample_face)
    if img_data is not None and (img_data.shape[0] < 64 or img_data.shape[1] < 64):
        img_data = cv2.resize(img_data, (200, 260))
    _, face_buf = cv2.imencode('.jpg', img_data)
    r = requests.post(f"{BASE}/api/enrollment/check", files={'file': ('img.jpg', face_buf.tobytes(), 'image/jpeg')})
    assert r.status_code == 200, f"Check face failed: {r.text}"
    res = r.json()
    assert res['ok'] is True, f"Face should be valid: {res}"
    assert res['box'] is not None
    print(f"[PASS] 5A. Face sample check successfully detected valid face: score={res.get('det_score')}")

    # B) No face sample (create black image)
    import numpy as np, cv2
    black_img = np.zeros((300, 300, 3), dtype=np.uint8)
    _, black_buf = cv2.imencode('.jpg', black_img)
    r = requests.post(f"{BASE}/api/enrollment/check", files={'file': ('black.jpg', black_buf.tobytes(), 'image/jpeg')})
    assert r.status_code == 200
    res = r.json()
    assert res['ok'] is False, "Black image should not have face"
    assert res['reason'] == 'no_face', f"Expected reason no_face, got {res.get('reason')}"
    print(f"[PASS] 5B. Non-face image rejected properly: {res['message']}")

    # 6. Face lookup and cross-class reuse
    # Student HE201068 is enrolled in class HE201068.
    r = requests.get(f"{BASE}/api/students/lookup-face/HE201068")
    assert r.status_code == 200
    lookup = r.json()
    assert lookup['has_face'] is True, f"Lookup should find HE201068 face: {lookup}"
    assert lookup['source_class'] in ('HE201068', '1323', 'HHH')
    print(f"[PASS] 6A. Lookup successfully found existing face for HE201068 in class {lookup['source_class']}")

    # 7. Add student HE201068 to another class (HHH or 1323) without uploading photos again
    target_class = '1323'
    # Ensure class exists
    requests.post(f"{BASE}/api/classes", json={'name': target_class, 'description': 'Lop 1323'})
    # Ensure course exists for target class
    requests.post(f"{BASE}/api/courses", json={'class_name': target_class, 'subject': 'MATH101', 'subject_name': 'Toán cao cấp'})
    
    # Check if student already in class 1323, if so delete first to test fresh enrollment
    r = requests.get(f"{BASE}/api/students?class_name={target_class}")
    for s in r.json():
        if s['student_id'] == 'HE201068':
            requests.delete(f"{BASE}/api/students/{s['id']}")

    # Enroll HE201068 in class 1323 without images: should automatically reuse existing face!
    r = requests.post(f"{BASE}/api/students", data={
        'class_name': target_class,
        'student_id': 'HE201068',
        'full_name': 'Phạm Hoàng Bách'
    })
    assert r.status_code == 201, f"Enrollment with face reuse failed: {r.text}"
    enrolled = r.json()
    assert enrolled['face_status'] == 'enrolled', f"Expected face_status enrolled, got {enrolled['face_status']}"
    assert enrolled['embedding_count'] > 0, "Embeddings should have been copied over"
    print(f"[PASS] 7. Successfully enrolled student in new class with automatic face reuse (status: {enrolled['face_status']}, {enrolled['embedding_count']} samples).")

    # 8. Start attendance session for class 1323, MATH101
    r = requests.post(f"{BASE}/api/sessions", json={
        'class_name': target_class,
        'subject': 'MATH101',
        'slot': 1,
        'duration_minutes': 30,
        'camera_type': 'browser',
        'reopen': True
    })
    assert r.status_code in (200, 201), f"Open session failed: {r.text}"
    sess = r.json()
    sid = sess['id']
    print(f"[PASS] 8. Opened attendance session #{sid} for {target_class} - MATH101 - Slot 1.")

    # 9. Attendance recognition
    # Frame with student HE201068
    r = requests.post(f"{BASE}/api/sessions/{sid}/frame", files={'file': ('frame.jpg', face_buf.tobytes(), 'image/jpeg')}, data={'record': 1})
    assert r.status_code == 200, f"Post frame failed: {r.text}"
    frame_res = r.json()
    assert frame_res['status'] in ('recognized', 'already_recorded'), f"Expected recognized, got {frame_res}"
    print(f"[PASS] 9A. Student recognized and recorded in new class/subject session: status={frame_res['status']}")

    # Post duplicate frame: should be 'already_recorded' and not insert duplicate!
    r = requests.post(f"{BASE}/api/sessions/{sid}/frame", files={'file': ('frame.jpg', face_buf.tobytes(), 'image/jpeg')}, data={'record': 1})
    assert r.status_code == 200
    assert r.json()['status'] == 'already_recorded', f"Expected already_recorded, got {r.json()}"
    print(f"[PASS] 9B. Duplicate frame correctly identified as already_recorded.")

    # Post frame with no face: returns 'no_face'
    r = requests.post(f"{BASE}/api/sessions/{sid}/frame", files={'file': ('black.jpg', black_buf.tobytes(), 'image/jpeg')}, data={'record': 1})
    assert r.status_code == 200
    assert r.json()['status'] == 'no_face'
    print(f"[PASS] 9C. Empty/black frame correctly returned no_face.")

    # 10. Check session records
    r = requests.get(f"{BASE}/api/sessions/{sid}/records")
    assert r.status_code == 200
    recs = r.json()
    present_students = [p['student_id'] for p in recs['records'] if p['status'] == 'present']
    assert 'HE201068' in present_students, f"HE201068 should be present: {present_students}"
    print(f"[PASS] 10. Attendance roster records presence accurately: {present_students}")

    # 11. Reports & Excel Export
    r = requests.get(f"{BASE}/api/reports/history")
    assert r.status_code == 200
    print(f"[PASS] 11A. Reports history endpoint works properly.")

    r = requests.get(f"{BASE}/api/reports/export/excel")
    assert r.status_code == 200
    assert len(r.content) > 100
    print(f"[PASS] 11B. Excel report export works properly ({len(r.content)} bytes).")

    print("\n>>> ALL 11 TEST SUITES PASSED PERFECTLY! <<<")

if __name__ == '__main__':
    test_all()
