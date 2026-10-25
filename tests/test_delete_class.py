import requests
import json

import os as _os
import pytest as _pytest

# Talks to the running app on 127.0.0.1:8000 and creates/deletes classes and students in the
# REAL database. Opt in explicitly:  set SA_LIVE_SERVER_TESTS=1
pytestmark = _pytest.mark.skipif(_os.environ.get('SA_LIVE_SERVER_TESTS') != '1',
                                 reason='live-server test; set SA_LIVE_SERVER_TESTS=1 to run')

BASE = "http://127.0.0.1:8000"

def cleanup_class(name):
    try:
        r = requests.get(f"{BASE}/api/classes")
        for c in r.json():
            if c['name'] == name:
                requests.delete(f"{BASE}/api/classes/{c['id']}")
    except Exception:
        pass

def test_delete_class():
    print("=== STARTING TEST SUITE: DELETE CLASS & STUDENT CLEANUP ===")
    for name in ['TESTEMPTY', 'TESTMANY', 'CLSALPHA', 'CLSBETA']:
        cleanup_class(name)

    # 1. Test deleting class without students
    print("\n--- Test 1: Delete class without students ---")
    r = requests.post(f"{BASE}/api/classes", json={'name': 'TESTEMPTY', 'description': 'Lop rong'})
    assert r.status_code in (200, 201), f"Create class failed: {r.text}"
    empty_class = r.json()
    empty_id = empty_class['id']

    # Delete empty class
    r = requests.delete(f"{BASE}/api/classes/{empty_id}")
    assert r.status_code == 200, f"Delete empty class failed: {r.text}"
    del_res = r.json()
    assert del_res['deleted'] == 'TESTEMPTY'
    assert 'Đã xóa lớp và xử lý danh sách sinh viên liên quan thành công' in del_res['message']
    
    # Verify class is gone from classes list
    r = requests.get(f"{BASE}/api/classes")
    assert all(c['name'] != 'TESTEMPTY' for c in r.json())
    print("[PASS] 1. Class without students deleted cleanly.")

    # 2. Test deleting class with multiple students
    print("\n--- Test 2: Delete class with multiple students ---")
    r = requests.post(f"{BASE}/api/classes", json={'name': 'TESTMANY', 'description': 'Lop nhieu sinh vien'})
    assert r.status_code in (200, 201)
    many_id = r.json()['id']

    # Enroll 2 students into TESTMANY
    # Student 1 (reuse HE201068 face)
    r = requests.post(f"{BASE}/api/students", data={
        'class_name': 'TESTMANY',
        'student_id': 'HE201068',
        'full_name': 'Phạm Hoàng Bách'
    })
    assert r.status_code == 201, f"Enroll S1 failed: {r.text}"
    # Student 2 (without photo)
    r = requests.post(f"{BASE}/api/students", data={
        'class_name': 'TESTMANY',
        'student_id': 'TESTSV02',
        'full_name': 'Nguyễn Văn Test'
    })
    assert r.status_code == 201, f"Enroll S2 failed: {r.text}"

    # Also add a course to TESTMANY
    r = requests.post(f"{BASE}/api/courses", json={
        'class_name': 'TESTMANY',
        'subject': 'PRJ301',
        'subject_name': 'Java Web'
    })
    assert r.status_code in (200, 201)

    # Check student count is 2
    r = requests.get(f"{BASE}/api/students?class_name=TESTMANY")
    assert len(r.json()) == 2

    # Delete class TESTMANY (previously this failed with 'Lớp còn 2 sinh viên...')
    r = requests.delete(f"{BASE}/api/classes/{many_id}")
    assert r.status_code == 200, f"Delete class with students failed: {r.text}"
    del_res = r.json()
    assert del_res['deleted'] == 'TESTMANY'
    assert del_res['students_count'] == 2
    assert 'Đã xóa lớp và xử lý danh sách sinh viên liên quan thành công' in del_res['message']

    # Verify class and courses are gone
    r = requests.get(f"{BASE}/api/classes")
    assert all(c['name'] != 'TESTMANY' for c in r.json())
    r = requests.get(f"{BASE}/api/courses?class_name=TESTMANY")
    assert len(r.json()) == 0
    # Active students for this class are now 0
    r = requests.get(f"{BASE}/api/students?class_name=TESTMANY")
    assert len(r.json()) == 0
    print("[PASS] 2. Class with multiple students deleted automatically without forcing manual student deletion.")

    # 3. Test multi-class student isolation:
    # Student HE201068 is in class HE201068. We enroll them into CLASS_A and CLASS_B.
    # Deleting CLASS_A must NOT remove HE201068 from CLASS_B or HE201068!
    print("\n--- Test 3: Multi-class student isolation ---")
    r = requests.post(f"{BASE}/api/classes", json={'name': 'CLSALPHA'})
    assert r.status_code in (200, 201)
    cls_a_id = r.json()['id']
    
    r = requests.post(f"{BASE}/api/classes", json={'name': 'CLSBETA'})
    assert r.status_code in (200, 201)
    cls_b_id = r.json()['id']

    # Enroll HE201068 into both CLSALPHA and CLSBETA
    requests.post(f"{BASE}/api/students", data={'class_name': 'CLSALPHA', 'student_id': 'HE201068', 'full_name': 'Phạm Hoàng Bách'})
    requests.post(f"{BASE}/api/students", data={'class_name': 'CLSBETA', 'student_id': 'HE201068', 'full_name': 'Phạm Hoàng Bách'})

    # Verify both classes have student HE201068
    r_a = requests.get(f"{BASE}/api/students?class_name=CLSALPHA").json()
    r_b = requests.get(f"{BASE}/api/students?class_name=CLSBETA").json()
    assert any(s['student_id'] == 'HE201068' for s in r_a)
    assert any(s['student_id'] == 'HE201068' for s in r_b)

    # Now delete CLSALPHA
    r = requests.delete(f"{BASE}/api/classes/{cls_a_id}")
    assert r.status_code == 200

    # CLSBETA must STILL have student HE201068 active with face status enrolled!
    r_b_after = requests.get(f"{BASE}/api/students?class_name=CLSBETA").json()
    student_in_beta = next((s for s in r_b_after if s['student_id'] == 'HE201068'), None)
    assert student_in_beta is not None, "Student HE201068 must still exist in CLSBETA!"
    assert student_in_beta['face_status'] == 'enrolled', "Face status must remain enrolled in CLSBETA!"
    print("[PASS] 3. Deleting one class preserved the student in their other classes with face embeddings intact.")

    # 4. Test attendance history preservation
    print("\n--- Test 4: Attendance history preservation ---")
    # Add course to CLSBETA
    requests.post(f"{BASE}/api/courses", json={'class_name': 'CLSBETA', 'subject': 'AI301', 'subject_name': 'Trí tuệ nhân tạo'})
    # Open attendance session in CLSBETA
    r = requests.post(f"{BASE}/api/sessions", json={
        'class_name': 'CLSBETA', 'subject': 'AI301', 'slot': 2, 'duration_minutes': 45, 'camera_type': 'browser', 'reopen': True
    })
    assert r.status_code in (200, 201)
    sess_id = r.json()['id']

    # Record attendance in this session
    import cv2, glob, os
    candidates = sorted(glob.glob("attendance_system/dataset/**/img_01.jpg", recursive=True))
    bach_photos = [p for p in candidates if 'HE201068' in p and not '.deleted_classes' in p]
    sample_face = bach_photos[0] if bach_photos else candidates[0]
    assert sample_face and os.path.exists(sample_face), "No sample photo found"
    img_data = cv2.imread(sample_face)
    if img_data is not None and (img_data.shape[0] < 64 or img_data.shape[1] < 64):
        img_data = cv2.resize(img_data, (200, 260))
    _, buf = cv2.imencode('.jpg', img_data)
    r = requests.post(f"{BASE}/api/sessions/{sess_id}/frame", files={'file': ('f.jpg', buf.tobytes(), 'image/jpeg')}, data={'record': 1})
    assert r.status_code == 200
    print("Frame result:", r.json())
    assert r.json()['status'] in ('recognized', 'already_recorded')

    # Verify history shows attendance before deleting class
    r = requests.get(f"{BASE}/api/history?class_name=CLSBETA")
    assert r.status_code == 200
    hist_before = r.json()
    assert hist_before['summary']['records'] >= 1

    # Now DELETE CLSBETA!
    r = requests.delete(f"{BASE}/api/classes/{cls_b_id}")
    assert r.status_code == 200

    # History MUST still be preserved for CLSBETA!
    r = requests.get(f"{BASE}/api/history?class_name=CLSBETA")
    assert r.status_code == 200
    hist_after = r.json()
    assert hist_after['summary']['records'] == hist_before['summary']['records'], "Past attendance records must not be deleted!"

    # Excel export must still work for CLSBETA
    r = requests.get(f"{BASE}/api/reports/export?class_name=CLSBETA")
    assert r.status_code == 200
    assert len(r.content) > 100, "Excel export must contain preserved history data!"
    print(f"[PASS] 4. Attendance history ({hist_after['summary']['records']} records) and Excel export safely preserved after class deletion.")

    # 5. Non-existent class handling
    print("\n--- Test 5: Error handling ---")
    r = requests.delete(f"{BASE}/api/classes/9999999")
    assert r.status_code == 404, f"Expected 404, got {r.status_code}"
    print(f"[PASS] 5. Non-existent class returns 404 Not Found: {r.json()['detail']}")

    print("\n>>> ALL TESTS FOR DELETE CLASS & STUDENT WORKFLOW PASSED! <<<")

if __name__ == '__main__':
    test_delete_class()
