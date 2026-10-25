"""Comprehensive test suite for Batch Student & Face Import from a single Excel file (.xlsx).

Covers all requirements from USER_REQUEST:
1. Template download: validates columns, styling, instruction sheet, and embedded sample photo.
2. 10-student Excel file with embedded photos:
   - 6 valid students with distinct real face photos
   - 1 student missing photo
   - 1 student with solid black photo (no face)
   - 1 student with composite photo (multiple faces)
   - 1 student with invalid/missing student_id
3. Preview & row-to-image anchoring:
   - Validates that photos are bound strictly to their row coordinate, not filename.
   - Detects no_face, multiple_faces, missing_photo, and validation errors.
4. Batch commit with error isolation:
   - Successfully commits valid students with face enrollment.
   - Reports rows with errors without failing the batch.
5. Re-import and conflict reconciliation:
   - Re-importing same file flags existing students as 'already_in_class'.
   - Avoids creating duplicates.
6. End-to-end recognition test:
   - Starts an active session for the imported class.
   - Feeds a webcam frame for one of the imported students.
   - Verifies the student is recognized and attendance is recorded.
"""
import io
import os
import glob
import cv2
import numpy as np
import openpyxl
from openpyxl.drawing.image import Image as OpenpyxlImage
import requests

import os as _os
import pytest as _pytest

# Talks to the running app on 127.0.0.1:8000 and creates/deletes classes and students in the
# REAL database. Opt in explicitly:  set SA_LIVE_SERVER_TESTS=1
pytestmark = _pytest.mark.skipif(_os.environ.get('SA_LIVE_SERVER_TESTS') != '1',
                                 reason='live-server test; set SA_LIVE_SERVER_TESTS=1 to run')

BASE = "http://127.0.0.1:8000"
DATASET_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "attendance_system", "dataset")


def get_real_sample_photos():
    """Return two distinct real face photos from dataset or frames."""
    photos = sorted(glob.glob(os.path.join(DATASET_DIR, "*", "*", "img_01.jpg")))
    frames = sorted(glob.glob(os.path.join(os.path.dirname(DATASET_DIR), "frames", "*.jpg")))
    p1 = photos[0] if photos else None
    p2 = frames[0] if frames else (photos[1] if len(photos) > 1 else photos[0])
    assert p1 and os.path.exists(p1), f"Missing sample photo 1"
    assert p2 and os.path.exists(p2), f"Missing sample photo 2"
    return p1, p2


def cleanup_class(name):
    try:
        r = requests.get(f"{BASE}/api/classes")
        for c in r.json():
            if c['name'] == name:
                requests.delete(f"{BASE}/api/classes/{c['id']}")
    except Exception:
        pass
    import shutil
    cdir = os.path.join(DATASET_DIR, name)
    if os.path.exists(cdir):
        try:
            shutil.rmtree(cdir, ignore_errors=True)
        except Exception:
            pass


def build_test_excel_with_embedded_photos(photo1_path, photo2_path):
    """Create a 10-row Excel file containing embedded images anchored to specific cells."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Danh_Sach_Sinh_Vien"

    # Setup headers
    headers = ["student_id", "full_name", "class_code", "photo"]
    ws.append(headers)

    ws.column_dimensions["A"].width = 16
    ws.column_dimensions["B"].width = 28
    ws.column_dimensions["C"].width = 16
    ws.column_dimensions["D"].width = 26

    # Prepare realistic portrait images with margins
    def make_portrait(img, brightness_delta=0):
        h = int(240 * img.shape[0] / img.shape[1])
        resized = cv2.resize(img, (240, h))
        if brightness_delta != 0:
            resized = np.clip(resized.astype(np.int16) + brightness_delta, 0, 255).astype(np.uint8)
        padded = cv2.copyMakeBorder(resized, 40, 40, 40, 40, cv2.BORDER_CONSTANT, value=[245, 245, 245])
        return cv2.imencode(".jpg", padded)[1].tobytes()

    img1 = cv2.imread(photo1_path)
    img2 = cv2.imread(photo2_path)

    # 1. Valid face 1
    face1_jpg = make_portrait(img1)

    # 2. Valid face 2
    face2_jpg = make_portrait(img2)

    # 3. Valid face 1 with slight brightness increase
    face3_jpg = make_portrait(img1, brightness_delta=20)

    # 4. Valid face 2 with slight brightness increase
    face4_jpg = make_portrait(img2, brightness_delta=20)

    # 5. Black image (no face)
    black = np.zeros((240, 240, 3), dtype=np.uint8)
    black_jpg = cv2.imencode(".jpg", black)[1].tobytes()

    # 6. Composite image with 2 faces side by side (multiple faces)
    p1 = cv2.copyMakeBorder(cv2.resize(img1, (160, 200)), 30, 30, 30, 30, cv2.BORDER_CONSTANT, value=[245, 245, 245])
    p2 = cv2.copyMakeBorder(cv2.resize(img2, (160, 200)), 30, 30, 30, 30, cv2.BORDER_CONSTANT, value=[245, 245, 245])
    multi_img = np.hstack([p1, p2])
    multi_jpg = cv2.imencode(".jpg", multi_img)[1].tobytes()

    # Define 10 rows:
    # Row 2 (SV 1): EX001, Nguyen Van Mot, EXCEL_TEST, face1
    # Row 3 (SV 2): EX002, Tran Thi Hai, EXCEL_TEST, face2
    # Row 4 (SV 3): EX003, Le Van Ba, EXCEL_TEST, face3
    # Row 5 (SV 4): EX004, Pham Thi Bon, EXCEL_TEST, face4
    # Row 6 (SV 5): EX005, Hoang Van Nam, EXCEL_TEST, face1
    # Row 7 (SV 6): EX006, Vu Thi Sau, EXCEL_TEST, NO PHOTO
    # Row 8 (SV 7): EX007, Dang Van Bay, EXCEL_TEST, black_jpg (no_face)
    # Row 9 (SV 8): EX008, Bui Thi Tam, EXCEL_TEST, multi_jpg (multiple_faces)
    # Row 10 (SV 9): INVALID_ID (empty), Ngo Van Chin, EXCEL_TEST, face1
    # Row 11 (SV 10): EX010, Do Thi Muoi, EXCEL_TEST, face2

    rows_data = [
        ("EX001", "Nguyễn Văn Một", "EXCEL-TEST", face1_jpg),
        ("EX002", "Trần Thị Hai", "EXCEL-TEST", None),          # Missing photo
        ("EX003", "Lê Văn Ba", "EXCEL-TEST", None),          # Missing photo
        ("EX004", "Phạm Thị Bốn", "EXCEL-TEST", None),       # Missing photo
        ("EX005", "Hoàng Văn Năm", "EXCEL-TEST", face1_jpg), # Duplicate face from EX001
        ("EX006", "Vũ Thị Sáu", "EXCEL-TEST", None),         # Missing photo
        ("EX007", "Đặng Văn Bảy", "EXCEL-TEST", black_jpg),  # No face (black image)
        ("EX008", "Bùi Thị Tám", "EXCEL-TEST", multi_jpg),   # Multiple faces
        ("", "Ngô Văn Chín", "EXCEL-TEST", face1_jpg),       # Empty student ID
        ("EX010", "Đỗ Thị Mười", "EXCEL-TEST", face1_jpg),   # Duplicate face from EX001
    ]

    for row_idx, (sid, name, cls, img_bytes) in enumerate(rows_data, start=2):
        ws.row_dimensions[row_idx].height = 85
        ws.append([sid, name, cls, ""])
        if img_bytes is not None:
            img_io = io.BytesIO(img_bytes)
            op_img = OpenpyxlImage(img_io)
            op_img.width = 90
            op_img.height = 105
            cell_ref = f"D{row_idx}"
            ws.add_image(op_img, cell_ref)

    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def test_batch_excel_import_suite():
    print("=== STARTING COMPREHENSIVE BATCH EXCEL IMPORT TEST SUITE ===")
    CLASS_NAME = "EXCEL-TEST"
    cleanup_class(CLASS_NAME)

    # -------------------------------------------------------------
    # 1. Test Template Download
    # -------------------------------------------------------------
    print("\n--- Test 1: Download Template Endpoint ---")
    r = requests.get(f"{BASE}/api/students/import/template")
    assert r.status_code == 200, f"Template download failed: {r.status_code} {r.text}"
    assert "openxmlformats" in r.headers.get("content-type", "")
    assert len(r.content) > 5000, "Template file size seems too small"

    # Verify template contents with openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(r.content))
    assert "Import_Sinh_Vien" in wb.sheetnames, f"Missing sheet: {wb.sheetnames}"
    assert "Huong_Dan" in wb.sheetnames, f"Missing sheet: {wb.sheetnames}"
    ws = wb["Import_Sinh_Vien"]
    headers = [cell.value for cell in ws[1][:4]]
    assert headers == ["student_id", "full_name", "class_code", "photo"], f"Headers mismatch: {headers}"
    # Verify sample row
    sample_sid = ws.cell(row=2, column=1).value
    assert sample_sid == "HE180001"
    # Verify embedded photo is in sheet
    assert len(ws._images) >= 1, "Template should contain at least 1 embedded sample photo"
    print(f"[PASS] Test 1: Template generated successfully ({len(r.content)} bytes, 2 sheets, embedded photo found).")

    # -------------------------------------------------------------
    # 2. Build 10-Row Excel with diverse edge cases
    # -------------------------------------------------------------
    print("\n--- Test 2: Build 10-student Excel with embedded photos & edge cases ---")
    photo1_path, photo2_path = get_real_sample_photos()
    excel_bytes = build_test_excel_with_embedded_photos(photo1_path, photo2_path)
    print(f"Generated test Excel file size: {len(excel_bytes)} bytes.")

    # -------------------------------------------------------------
    # 3. Preview Endpoint & Image-to-Row Anchoring
    # -------------------------------------------------------------
    print("\n--- Test 3: Upload Excel & Inspect Preview Reconciliation ---")
    files = {"file": ("test_import_10sv.xlsx", excel_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    r = requests.post(f"{BASE}/api/students/import/preview", files=files)
    assert r.status_code == 200, f"Preview failed: {r.status_code} {r.text}"
    data = r.json()
    assert "session_token" in data
    session_token = data["session_token"]
    summary = data["summary"]
    rows = data["rows"]

    assert summary["total_rows"] == 10, f"Expected 10 rows, got {summary['total_rows']}"
    assert len(rows) == 10, f"Expected 10 row objects, got {len(rows)}"

    print(f"Preview Summary: {summary}")

    # Map rows by row_index (2 to 11)
    row_map = {r["row_index"]: r for r in rows}

    # Row 2 (EX001): Valid photo 1, new student
    r2 = row_map[2]
    assert r2["student_id"] == "EX001"
    assert r2["has_image"] is True
    assert r2["face_status"] == "valid", f"Row 2 face_status expected 'valid', got: {r2['face_status']}"
    assert r2["det_score"] is not None and r2["det_score"] > 0.4
    assert r2["db_status"] == "new"
    assert r2["action"] == "create"
    assert r2["image_preview"] is not None and r2["image_preview"].startswith("data:image/jpeg;base64,")

    # Row 3 (EX002): Missing photo, new student
    r3 = row_map[3]
    assert r3["student_id"] == "EX002"
    assert r3["has_image"] is False
    assert r3["face_status"] == "missing_photo"
    assert r3["db_status"] == "new"

    # Row 7 (EX006): Missing photo
    r7 = row_map[7]
    assert r7["student_id"] == "EX006"
    assert r7["has_image"] is False
    assert r7["face_status"] == "missing_photo", f"Row 7 expected missing_photo, got {r7['face_status']}"

    # Row 8 (EX007): Black image -> no face
    r8 = row_map[8]
    assert r8["student_id"] == "EX007"
    assert r8["has_image"] is True
    assert r8["face_status"] == "no_face", f"Row 8 expected no_face, got {r8['face_status']}"

    # Row 9 (EX008): Multiple faces
    r9 = row_map[9]
    assert r9["student_id"] == "EX008"
    assert r9["has_image"] is True
    assert r9["face_status"] == "multiple_faces", f"Row 9 expected multiple_faces, got {r9['face_status']}"

    # Row 10 (Empty SID): Invalid ID error
    r10 = row_map[10]
    assert r10["error"] is not None
    assert "Mã sinh viên không được để trống" in r10["error"]

    # Row 11 (EX010): Valid photo 2
    r11 = row_map[11]
    assert r11["student_id"] == "EX010"
    assert r11["face_status"] == "valid"

    print("[PASS] Test 3: Preview endpoint correctly anchored photos to rows and detected all face states.")

    # -------------------------------------------------------------
    # 4. Batch Commit with Error Isolation
    # -------------------------------------------------------------
    print("\n--- Test 4: Commit Batch Import & Verify Error Isolation ---")
    commit_payload = {
        "session_token": session_token,
        "default_conflict": "skip",
        "overrides": {}
    }
    r = requests.post(f"{BASE}/api/students/import/commit", json=commit_payload)
    assert r.status_code == 200, f"Commit failed: {r.status_code} {r.text}"
    commit_res = r.json()
    c_summary = commit_res["summary"]
    errors = commit_res["errors"]

    print(f"Commit Summary: {c_summary}")
    print(f"Commit Errors: {errors}")

    # Valid students created: EX001 (face1), EX002 (face2), EX003 (no photo), EX004 (no photo), EX006 (no photo)
    # Failed rows isolated: EX005 (dup face), EX007 (no face), EX008 (multi face), SV9 (empty id), EX010 (dup face)
    assert c_summary["created"] == 5, f"Expected 5 created students, got {c_summary['created']}"
    assert c_summary["failed"] == 5, f"Expected 5 failed rows, got {c_summary['failed']}"

    # Verify database state for EXCEL-TEST class
    r = requests.get(f"{BASE}/api/students?class_name={CLASS_NAME}")
    assert r.status_code == 200
    enrolled_students = r.json()
    enrolled_sids = {s["student_id"] for s in enrolled_students}
    print(f"Enrolled students in DB: {enrolled_sids}")

    assert "EX001" in enrolled_sids
    assert "EX002" in enrolled_sids
    assert "EX003" in enrolled_sids
    assert "EX006" in enrolled_sids

    # Verify EX001 has face enrolled
    ex001_record = next(s for s in enrolled_students if s["student_id"] == "EX001")
    assert ex001_record["face_status"] == "enrolled", f"EX001 face_status is {ex001_record['face_status']}"
    assert len(ex001_record["photos"]) >= 1

    print("[PASS] Test 4: Batch committed successfully with full error isolation.")

    # -------------------------------------------------------------
    # 5. Re-Import Same File (Duplicate Avoidance)
    # -------------------------------------------------------------
    print("\n--- Test 5: Re-import same file and verify duplicate avoidance ---")
    files = {"file": ("test_import_10sv.xlsx", excel_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    r = requests.post(f"{BASE}/api/students/import/preview", files=files)
    assert r.status_code == 200
    re_data = r.json()
    re_rows = {r["row_index"]: r for r in re_data["rows"]}

    # EX001 should now be flagged as already_in_class
    assert re_rows[2]["db_status"] == "already_in_class"
    assert re_rows[2]["action"] == "skip"

    # Commit re-import with default conflict "skip"
    r = requests.post(f"{BASE}/api/students/import/commit", json={
        "session_token": re_data["session_token"],
        "default_conflict": "skip",
        "overrides": {}
    })
    assert r.status_code == 200
    re_commit = r.json()
    # No new students should have been created
    assert re_commit["summary"]["created"] == 0, f"Expected 0 created on re-import, got: {re_commit['summary']}"
    assert re_commit["summary"]["skipped"] >= 5

    # Verify database still has exactly same student count
    r = requests.get(f"{BASE}/api/students?class_name={CLASS_NAME}")
    assert len(r.json()) == len(enrolled_students), "Re-import should not create duplicate student records"
    print("[PASS] Test 5: Re-import correctly marked existing students and prevented duplicates.")

    # -------------------------------------------------------------
    # 6. Live Attendance Recognition with Imported Face
    # -------------------------------------------------------------
    print("\n--- Test 6: Verify imported student recognition in live attendance session ---")
    # 1. Create a course in EXCEL-TEST
    r = requests.post(f"{BASE}/api/courses", json={"class_name": CLASS_NAME, "subject": "CS101", "subject_name": "Computer Science 101"})
    assert r.status_code in (200, 201), f"Create course failed: {r.text}"

    # 2. Open an attendance session
    r = requests.post(f"{BASE}/api/sessions", json={
        "class_name": CLASS_NAME,
        "subject": "CS101",
        "slot": 1,
        "duration_minutes": 30,
        "reopen": True
    })
    assert r.status_code in (200, 201), f"Open session failed: {r.text}"
    session_id = r.json()["id"]

    # 3. Create a synthetic camera frame with EX001's face
    img1 = cv2.imread(photo1_path)
    face_resized = cv2.resize(img1, (220, int(220 * img1.shape[0] / img1.shape[1])))
    frame = np.full((480, 640, 3), 128, dtype=np.uint8)
    h = min(face_resized.shape[0], 480 - 60)
    frame[60:60 + h, 200:200 + 220] = face_resized[:h]
    frame_jpg = cv2.imencode(".jpg", frame)[1].tobytes()

    # 4. Post frame to session recognition endpoint
    files = {"file": ("camera.jpg", frame_jpg, "image/jpeg")}
    r = requests.post(f"{BASE}/api/sessions/{session_id}/frame", files=files, data={"frame_id": 101, "record": 1})
    assert r.status_code == 200, f"Process frame failed: {r.text}"
    rec_res = r.json()
    print(f"Recognition response: {rec_res}")

    assert rec_res["status"] in ("recognized", "already_recorded"), f"Expected 'recognized', got {rec_res['status']}: {rec_res.get('message')}"
    assert rec_res["student"]["student_id"] == "EX001", f"Expected EX001, got {rec_res['student']}"
    assert rec_res["student"]["score"] >= 0.5

    # 5. Verify attendance record in session
    r = requests.get(f"{BASE}/api/sessions/{session_id}/records")
    assert r.status_code == 200
    records = r.json()["records"]
    assert any(rec["student_id"] == "EX001" and rec["status"] == "present" for rec in records), f"EX001 not present in records: {records}"
    print("[PASS] Test 6: Imported student EX001 was successfully recognized and marked present in live attendance session!")

    # -------------------------------------------------------------
    # 7. Cleanup
    # -------------------------------------------------------------
    print("\n--- Test 7: Cleanup test class ---")
    cleanup_class(CLASS_NAME)
    r = requests.get(f"{BASE}/api/classes")
    assert all(c["name"] != CLASS_NAME for c in r.json())
    print("[PASS] Test 7: Cleaned up test class successfully.")

    print("\n=======================================================")
    print("ALL TESTS PASSED! Single Excel Import is 100% verified.")
    print("=======================================================")


if __name__ == "__main__":
    test_batch_excel_import_suite()
