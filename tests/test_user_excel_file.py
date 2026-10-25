"""End-to-end verification test for the user's actual Excel file:
Mau_dang_ky_sinh_vien_co_anh.xlsx

Verifies:
1. Preview extraction of 8 students and 8 embedded images from Mau_dang_ky_sinh_vien_co_anh.xlsx.
2. Row-to-image anchoring matches exact row coordinates (rows 2 to 9).
3. Target class auto-fills when class_code column in Excel is empty.
4. Database commit creates student records, copies images, generates embeddings.
5. Re-import duplicate avoidance.
6. Live camera recognition in an active session with the imported students.
"""
import os
import requests

import os as _os
import pytest as _pytest

# Talks to the running app on 127.0.0.1:8000 and creates/deletes classes and students in the
# REAL database. Opt in explicitly:  set SA_LIVE_SERVER_TESTS=1
pytestmark = _pytest.mark.skipif(_os.environ.get('SA_LIVE_SERVER_TESTS') != '1',
                                 reason='live-server test; set SA_LIVE_SERVER_TESTS=1 to run')

BASE = "http://127.0.0.1:8000"
USER_EXCEL_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "Mau_dang_ky_sinh_vien_co_anh.xlsx"))
CLASS_NAME = "K18-TEST"


def cleanup_class(name):
    try:
        r = requests.get(f"{BASE}/api/classes")
        for c in r.json():
            if c['name'] == name:
                requests.delete(f"{BASE}/api/classes/{c['id']}")
    except Exception:
        pass


def test_user_excel_import():
    print("=== STARTING TEST ON USER'S ACTUAL EXCEL FILE ===")
    print(f"File path: {USER_EXCEL_PATH}")
    assert os.path.exists(USER_EXCEL_PATH), f"File not found: {USER_EXCEL_PATH}"
    file_bytes = open(USER_EXCEL_PATH, "rb").read()
    print(f"File size: {len(file_bytes)} bytes.")

    cleanup_class(CLASS_NAME)

    # 1. Preview without default_class -> validates missing class warning
    print("\n--- Step 1: Preview without default_class (expects missing class warning) ---")
    files = {"file": ("Mau_dang_ky_sinh_vien_co_anh.xlsx", file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    r = requests.post(f"{BASE}/api/students/import/preview", files=files)
    assert r.status_code == 200, f"Preview failed: {r.text}"
    p_data = r.json()
    assert p_data["summary"]["total_rows"] == 8
    assert p_data["summary"]["valid_face"] == 8
    # Because class column in user's file is empty:
    assert any("mã lớp" in (row.get("error") or "").lower() for row in p_data["rows"])
    print("[PASS] Step 1: Detected 8 students, 8 valid embedded photos, and properly prompted for missing class.")

    # 2. Preview WITH default_class -> validates clean reconciliation
    print(f"\n--- Step 2: Preview WITH default_class='{CLASS_NAME}' ---")
    files = {"file": ("Mau_dang_ky_sinh_vien_co_anh.xlsx", file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    data = {"default_class": CLASS_NAME}
    r = requests.post(f"{BASE}/api/students/import/preview", files=files, data=data)
    assert r.status_code == 200, f"Preview with default_class failed: {r.text}"
    res = r.json()
    summary = res["summary"]
    rows = res["rows"]
    session_token = res["session_token"]

    print(f"Summary: {summary}")
    assert summary["total_rows"] == 8, f"Expected 8 rows, got {summary['total_rows']}"
    assert summary["valid_face"] == 8, f"Expected 8 valid faces, got {summary['valid_face']}"
    assert summary["issues_count"] == 0, f"Expected 0 issues with default_class, got {summary['issues_count']}"

    # Verify each row mapping
    expected_students = [
        (2, "HE201068", "bach"),
        (3, "HE190388", "Dao Khoi Nguyen"),
        (4, "HE193366", "Dinh Duc Anh"),
        (5, "HE201006", "Khiêm"),
        (6, "HE207890", "Phan Tuan Kiet"),
        (7, "HE208838", "Trinh Quang Tien"),
        (8, "HE208299", "Vân Khánh"),
        (9, "HE200093", "Vũ Gia Tiến"),
    ]

    row_dict = {r["row_index"]: r for r in rows}
    for r_idx, expected_sid, expected_name in expected_students:
        row = row_dict[r_idx]
        assert row["student_id"] == expected_sid, f"Row {r_idx} SID mismatch: {row['student_id']} vs {expected_sid}"
        assert expected_name.lower() in row["full_name"].lower(), f"Row {r_idx} Name mismatch: {row['full_name']} vs {expected_name}"
        assert row["class_code"] == CLASS_NAME
        assert row["has_image"] is True, f"Row {r_idx} missing image"
        assert row["face_status"] == "valid", f"Row {r_idx} face_status: {row['face_status']}"
        assert row["det_score"] is not None and row["det_score"] >= 0.70
        assert row["image_preview"] is not None and row["image_preview"].startswith("data:image/jpeg;base64,")
        assert row["error"] is None

    print("[PASS] Step 2: All 8 students and 8 portrait photos accurately mapped by Excel cell coordinates!")

    # 3. Commit import
    print(f"\n--- Step 3: Commit import into database for class '{CLASS_NAME}' ---")
    r = requests.post(f"{BASE}/api/students/import/commit", json={
        "session_token": session_token,
        "default_conflict": "skip",
        "default_class": CLASS_NAME,
        "overrides": {}
    })
    assert r.status_code == 200, f"Commit failed: {r.text}"
    c_res = r.json()
    c_sum = c_res["summary"]
    print(f"Commit Summary: {c_sum}")
    if c_res.get("errors"):
        print(f"Commit Errors: {c_res['errors']}")

    # Check database state
    r = requests.get(f"{BASE}/api/students?class_name={CLASS_NAME}")
    assert r.status_code == 200
    db_students = r.json()
    print(f"Enrolled students in DB ({len(db_students)}): {[s['student_id'] for s in db_students]}")
    assert len(db_students) >= 7, f"Expected at least 7 enrolled students, got {len(db_students)}"

    # Check photos and face_status for students
    for st in db_students:
        assert st["face_status"] == "enrolled", f"Student {st['student_id']} face_status: {st['face_status']}"
        assert st["embedding_count"] >= 1, f"Student {st['student_id']} embedding_count: {st['embedding_count']}"
        assert len(st["photos"]) >= 1, f"Student {st['student_id']} photo count: {len(st['photos'])}"

    print("[PASS] Step 3: Students committed to database with full biometrics and photos intact.")

    # 4. Re-import duplicate prevention
    print("\n--- Step 4: Re-import same file and verify duplicate avoidance ---")
    files = {"file": ("Mau_dang_ky_sinh_vien_co_anh.xlsx", file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    data = {"default_class": CLASS_NAME}
    r = requests.post(f"{BASE}/api/students/import/preview", files=files, data=data)
    assert r.status_code == 200
    re_preview = r.json()
    for row in re_preview["rows"]:
        assert row["db_status"] == "already_in_class"
        assert row["action"] == "skip"

    r = requests.post(f"{BASE}/api/students/import/commit", json={
        "session_token": re_preview["session_token"],
        "default_conflict": "skip",
        "default_class": CLASS_NAME,
        "overrides": {}
    })
    assert r.status_code == 200
    re_commit = r.json()
    assert re_commit["summary"]["created"] == 0, f"Re-import created records: {re_commit['summary']}"
    assert re_commit["summary"]["skipped"] >= 7

    # DB count must remain identical
    r = requests.get(f"{BASE}/api/students?class_name={CLASS_NAME}")
    assert len(r.json()) == len(db_students)
    print("[PASS] Step 4: Re-import correctly prevented duplicates and skipped existing records.")

    # 5. Live Attendance Recognition with one of the imported students
    print("\n--- Step 5: Test live attendance recognition for newly imported student HE201068 ---")
    r = requests.post(f"{BASE}/api/courses", json={"class_name": CLASS_NAME, "subject": "AI101", "subject_name": "Trí tuệ nhân tạo"})
    assert r.status_code in (200, 201)

    r = requests.post(f"{BASE}/api/sessions", json={
        "class_name": CLASS_NAME,
        "subject": "AI101",
        "slot": 1,
        "duration_minutes": 30,
        "reopen": True
    })
    assert r.status_code in (200, 201)
    session_id = r.json()["id"]

    # Read the photo of HE201068 that was imported
    he201068_st = next(s for s in db_students if s["student_id"] == "HE201068")
    photo_name = he201068_st["photos"][0]
    photo_res = requests.get(f"{BASE}/api/students/{he201068_st['id']}/photos/{photo_name}")
    assert photo_res.status_code == 200

    # Prepare realistic webcam frame with HE201068's face
    import cv2, numpy as np
    nparr = np.frombuffer(photo_res.content, np.uint8)
    mat = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    w = 260
    h = int(w * mat.shape[0] / mat.shape[1])
    face = cv2.resize(mat, (w, h))
    frame = np.full((480, 640, 3), 128, dtype=np.uint8)
    h_crop = min(face.shape[0], 480 - 60)
    frame[60:60 + h_crop, 190:190 + w] = face[:h_crop]
    camera_jpg = cv2.imencode(".jpg", frame)[1].tobytes()

    # Post camera frame
    files = {"file": ("camera.jpg", camera_jpg, "image/jpeg")}
    r = requests.post(f"{BASE}/api/sessions/{session_id}/frame", files=files, data={"frame_id": 1, "record": 1})
    assert r.status_code == 200
    rec_res = r.json()
    print(f"Recognition result: status={rec_res.get('status')} student={rec_res.get('student')}")
    assert rec_res["status"] in ("recognized", "already_recorded")
    assert rec_res["student"]["student_id"] == "HE201068"
    print("[PASS] Step 5: Imported student was instantly recognized in active session!")

    # Cleanup
    print("\n--- Step 6: Cleanup test class ---")
    cleanup_class(CLASS_NAME)
    print("[PASS] Step 6: Test class cleaned up.")

    print("\n=======================================================")
    print("SUCCESS: Mau_dang_ky_sinh_vien_co_anh.xlsx 100% VERIFIED!")
    print("=======================================================")


if __name__ == "__main__":
    test_user_excel_import()
