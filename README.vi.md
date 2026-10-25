# Smart Attendance — Web app điểm danh bằng khuôn mặt

Chạy trên máy Windows, mở trình duyệt tại **http://127.0.0.1:8000** và thao tác trực tiếp trên web.
Nhận diện, lưu trữ và báo cáo đều chạy cục bộ: ảnh khuôn mặt không được gửi ra ngoài.

App desktop PyQt5 cũ (`attendance_system/main.py`) vẫn chạy được trên cùng dữ liệu.

---

## 1. Cài đặt và chạy

**Yêu cầu:** Windows 10/11 và Python **3.11** (đã kiểm thử với 3.11.9; 3.12 có thể dùng được).
Node.js không bắt buộc: nếu máy chưa có, setup sẽ tải bản Node.js portable v24.22.1 vào `tools\node` (có kiểm tra checksum, không cài vào hệ thống).

```bash
Cai-Dat.cmd
```
Lệnh tương đương: `powershell -ExecutionPolicy Bypass -File setup.ps1`. Chỉ cần chạy một lần. Setup làm các việc sau:

1. Dùng môi trường `attendance_system\.venv` sẵn có. Nếu chưa có, tạo mới bằng Python 3.11.
2. Cài `attendance_system/requirements.txt` và `requirements-web.txt`.
3. Kiểm tra model `buffalo_sc`. Nếu thiếu, thử tải tự động.
4. Cài thư viện frontend (`npm ci`) và build vào `frontend\dist`.
5. Import thử backend.

Setup **không xoá** môi trường, database, dataset hay model sẵn có.

```bash
Chay-SmartAttendance.cmd
```
Lệnh tương đương: `powershell -ExecutionPolicy Bypass -File run.ps1`. Có thể thêm `-Port 8010` hoặc `-NoBrowser`.
Trình duyệt tự mở `http://127.0.0.1:8000`. Đóng cửa sổ PowerShell (hoặc nhấn Ctrl+C) để dừng.

> Lần chạy đầu trên dữ liệu cũ, backend **sao lưu** `attendance.db` vào `attendance_system\backups\` rồi mới thêm bảng mới (migration chạy lại an toàn, không xoá bản ghi).

---

## 2. Quy trình sử dụng

1. **Lớp & Môn học** → *Tạo lớp* (VD: `SE1501`) → *Thêm môn* (VD: `CPV301`).
2. **Sinh viên** → *Đăng ký*: chọn lớp, nhập mã và họ tên, bật camera, *Chụp mẫu* 3–5 lần. Mỗi mẫu được máy chủ kiểm tra: có đúng một khuôn mặt, đủ lớn, đặc trưng hợp lệ. Sau đó bấm *Lưu hồ sơ*.
3. **Điểm danh**: chọn lớp, môn, Slot 1–20, thời lượng (hoặc *Không giới hạn*), nguồn camera (webcam hoặc RTSP) → *Bắt đầu điểm danh*.
4. Trên trang điểm danh trực tiếp: *Bật camera* và giữ *Tự động nhận diện* bật. Từng sinh viên đứng trước camera; bảng bên phải cập nhật ngay khi SQLite ghi thành công.
5. *Kết thúc phiên* (hoặc để hết giờ). Máy chủ từ chối mọi kết quả đến muộn và cập nhật cột của phiên vào `dataset\<LỚP>\attendance.xlsx`.
6. **Lịch sử & Báo cáo**: lọc theo ngày, lớp, môn, slot, sinh viên, trạng thái → *Xuất Excel*. File xuất theo đúng bộ lọc từ SQLite; bản sao nằm trong `attendance_system\exports`.

Mở lại cùng Lớp + Môn + Ngày + Slot sẽ tải lại dữ liệu đã có. Nếu phiên đã kết thúc, app hỏi trước khi mở lại. Tải lại trang (F5) **không** đặt lại bộ đếm thời gian.

---

## 3. Kiến trúc

```
Trình duyệt (React + TS + Tailwind)
   │  REST /api/*            │  WebSocket /ws/sessions/{id}: khung JPEG ~4 fps,
   │                         │  mỗi lần 1 khung, máy chủ chỉ giữ khung mới nhất
   ▼                         ▼
FastAPI (backend/app.py)  ── phục vụ luôn frontend/dist tại cùng một địa chỉ
   │
   ├─ services/sessions.py     phiên (lớp, môn, ngày, slot), hạn giờ, ghi điểm danh (BEGIN IMMEDIATE)
   ├─ services/recognition.py  pipeline nhận diện, dùng lại module cũ, một khoá inference, ngoài event loop
   ├─ services/students.py     đăng ký, sửa, xoá, đồng bộ với thư mục dataset
   ├─ services/catalog.py      lớp & lớp/môn (đồng bộ sessions.json cho app desktop)
   ├─ services/reports.py      tổng quan, lịch sử, Excel từ SQLite, sheet lớp kiểu desktop
   ├─ services/rtsp.py         camera IP: timeout, tự kết nối lại, preview MJPEG, ẩn mật khẩu
   └─ services/settings.py     cài đặt lưu trong SQLite
        │
        ▼
attendance_system/functions/  (dùng lại: FaceDetector SCRFD, FaceRecognizer ArcFace,
                               matching.py ngưỡng + margin, AntiSpoof, Preprocessor)
SQLite attendance.db  +  dataset/<LỚP>/<LỚP>_<MÃ>_<Tên>/embeddings.npy, img_XX.jpg
```

**Pipeline cho mỗi khung hình** (`RecognitionService.process_frame`):
kiểm tra ảnh (≤ 3 MB, 64–4096 px) → tiền xử lý (nếu bật) → phát hiện khuôn mặt → chọn mặt chính.
Nếu có mặt thứ hai đáng kể thì dừng với trạng thái *Nhiều khuôn mặt*; mặt rất nhỏ ở xa được bỏ qua.
Tiếp theo: chống giả mạo (nếu bật) → dùng embedding có sẵn từ bước phát hiện → so khớp với lớp (cosine ≥ ngưỡng **và** margin ≥ min_margin) → kiểm tra phiên còn mở **trong cùng transaction** → ghi SQLite → trả kết quả.

### Dữ liệu (SQLite)

| Bảng | Vai trò |
|---|---|
| `attendance` (cũ, thêm cột `session_id`, `student_pk`) | lượt điểm danh; chỉ mục duy nhất `(lớp, môn, mã SV, ngày, slot)` |
| `classes`, `courses` | lớp; cặp lớp/môn (thay `sessions.json`, file này vẫn được ghi lại cho app desktop) |
| `students` | khoá ổn định cho mỗi thư mục dataset |
| `sessions`, `session_roster` | phiên và danh sách sinh viên chốt khi mở phiên, dùng để tính vắng |
| `settings` | ngưỡng, margin, anti-spoof, RTSP… |

Bản ghi cũ do app desktop tạo được gắn vào phiên *dữ liệu cũ*. Các phiên này không có danh sách lớp, nên báo cáo chỉ hiện người có mặt và **không suy đoán** số vắng. Nếu DB cũ có bản ghi trùng, migration báo cáo và không xoá; khi đó không tạo chỉ mục duy nhất.

---

## 4. Các trang

| Trang | Chức năng |
|---|---|
| Tổng quan | dải lịch theo tuần, thẻ “Bắt đầu / Tiếp tục điểm danh”, thống kê theo ngày (phiên, lượt có mặt, vắng theo sĩ số phiên, số SV toàn hệ thống), thao tác nhanh, phiên trong ngày, hoạt động gần đây |
| Lớp & Môn học | tạo, sửa mô tả, xoá lớp (chỉ khi không còn SV); tạo, sửa tên, xoá môn (giữ lịch sử); tìm kiếm, lọc; nút Điểm danh |
| Điểm danh | thiết lập phiên (lớp, môn, slot 1–20, phút hoặc không giới hạn, webcam/RTSP), danh sách phiên hôm nay |
| Điểm danh trực tiếp | camera lớn và khung nhận diện có nhãn chữ và màu; đếm ngược do máy chủ quản lý; có mặt/vắng/sĩ số; bật/tắt camera, chọn camera, tự động nhận diện; đăng ký SV; kết thúc hoặc mở lại phiên |
| Sinh viên | tìm theo mã/tên, lọc lớp và trạng thái mẫu mặt, sửa, xoá, lịch sử, cập nhật mẫu khuôn mặt, đồng bộ với dataset |
| Đăng ký khuôn mặt | xem trước camera, chụp tối đa 5 mẫu, kiểm tra từng mẫu, xoá/chụp lại, lưu |
| Lịch sử & Báo cáo | bộ lọc, tổng hợp, bảng chi tiết hoặc theo phiên, xuất Excel đúng bộ lọc |
| Cài đặt | ngưỡng cosine, margin, ngưỡng phát hiện, fps, tiền xử lý, chống giả mạo, RTSP, tình trạng model, môi trường và thư mục dữ liệu |

Giao diện có sidebar trên desktop. Trên điện thoại có thanh điều hướng dưới (Tổng quan, Điểm danh, Sinh viên, Báo cáo) và menu *Thêm* cho các trang còn lại; bảng dài chuyển thành dạng thẻ.

---

## 5. API

| Nhóm | Endpoint |
|---|---|
| Hệ thống | `GET /api/health`, `GET /api/models/status`, `POST /api/models/reload`, `GET /api/system` |
| Tổng quan | `GET /api/dashboard?date=YYYY-MM-DD` |
| Lớp | `GET/POST /api/classes`, `PATCH/DELETE /api/classes/{id}` |
| Lớp/Môn | `GET/POST /api/courses`, `PATCH/DELETE /api/courses/{id}` |
| Sinh viên | `GET /api/students`, `POST /api/students` (multipart: class_name, student_id, full_name, files[]), `GET/PATCH/DELETE /api/students/{id}`, `GET /api/students/{id}/history`, `POST /api/students/{id}/face`, `GET /api/students/{id}/photos/{tên}`, `POST /api/students/sync`, `POST /api/enrollment/check` |
| Phiên | `GET/POST /api/sessions`, `GET /api/sessions/{id}`, `GET /api/sessions/{id}/records`, `POST /api/sessions/{id}/end`, `POST /api/sessions/{id}/reopen` |
| Nhận diện | `WS /ws/sessions/{id}` (nhị phân: 4 byte frame_id LE + 1 byte cờ ghi + JPEG), `POST /api/sessions/{id}/frame` |
| RTSP | `POST /api/sessions/{id}/rtsp/start`, `POST …/rtsp/stop`, `PATCH …/rtsp`, `GET …/rtsp/status`, `GET …/rtsp/stream` (MJPEG) |
| Báo cáo | `GET /api/history?date_from&date_to&class_name&subject&slot&q&status`, `GET /api/reports/export?…` |
| Cài đặt | `GET/PUT /api/settings` |

Tài liệu tương tác: http://127.0.0.1:8000/docs

---

## 6. Chống giả mạo

| Chế độ | Ý nghĩa |
|---|---|
| **Tắt** (mặc định, như dự án gốc) | không kiểm tra liveness |
| **Model MiniFASNet** | cần `attendance_system\models\anti_spoof_minifas.onnx`. Nếu thiếu model, mọi lượt hiện *Không thể xác minh* và **không ghi điểm danh** |
| **Texture (THỬ NGHIỆM)** | heuristic độ nét/LBP/màu/FFT, chưa được kiểm thử như model chống giả mạo |

Đã sửa các nhánh lỗi trong `anti_spoof.py` (ảnh lỗi, vùng mặt rỗng, exception) vốn trả `LIVE` / `is_real=True`. Giờ các nhánh này trả `ERROR`, và pipeline chặn ghi điểm danh.

---

## 7. Kiểm thử

```bash
attendance_system\.venv\Scripts\python -m pytest tests
```
Kết quả trên máy phát triển (Windows 11, Python 3.11.9): **44 passed**. Test cũ chạy bằng `cd attendance_system` rồi `python -m pytest tests`: **8 passed**.

- **Tự động, model giả** (`tests/test_web_backend.py`, 43 test): mạng nơ-ron được thay bằng bảng tra cứu khuôn mặt. Detector, recognizer, quy tắc so khớp, AntiSpoof, SQLite và API đều là code thật. Các test bao phủ: tạo lớp/môn, tên không hợp lệ, hai lớp cùng môn/slot/ngày, hai môn một lớp, mở lại phiên, nhận diện nhiều lần, 12 luồng ghi đồng thời, ID chữ thường hoặc có số 0 ở đầu, tên tiếng Việt (NFD/NFC, khoảng trắng thừa), sửa SV không đụng lớp khác (cả hàm desktop), người lạ, danh tính mơ hồ, nhiều khuôn mặt, người đứng xa bị bỏ qua, anti-spoof lỗi/thiếu model/từ chối, kết quả sau khi kết thúc hoặc hết giờ, phiên qua nửa đêm, thiếu model, frame hỏng hoặc quá lớn, WebSocket, RTSP (validate, ẩn mật khẩu), cài đặt, Excel khớp SQLite, vắng theo sĩ số phiên, khởi động lại giữ dữ liệu, migration DB cũ (sao lưu, trùng lặp, chạy lại), phục vụ frontend.
- **Model thật, không camera** (`tests/test_real_model.py`): đăng ký từ ảnh trong `dataset`, nhận diện ở vị trí và tỉ lệ khác qua đúng pipeline (điểm tương đồng ≈ 0.96), ảnh trống → *Không tìm thấy khuôn mặt*.
- **Kiểm thử thủ công trong trình duyệt** (đã làm): giao diện desktop 1024px và mobile 375px. Webcam được giả lập bằng ảnh đã đăng ký qua `canvas.captureStream()`: WebSocket → nhận diện thật → khung xanh đúng vị trí → SQLite → bảng cập nhật không cần tải lại. F5 không đặt lại bộ đếm. Trạng thái *Quyền camera bị từ chối* hiển thị đúng.
- **Chưa kiểm thử:** webcam vật lý và camera RTSP thật, vì môi trường phát triển không có camera.

### Tự kiểm tra webcam/RTSP trên máy bạn
1. Chạy `Chay-SmartAttendance.cmd`, mở **http://127.0.0.1:8000**. Phải dùng 127.0.0.1/localhost: trình duyệt chặn camera trên địa chỉ IP LAN không có HTTPS.
2. Đăng ký 1–2 sinh viên (3–5 mẫu mỗi người). Thử đăng ký lại cùng khuôn mặt bằng mã khác → phải báo *Khuôn mặt đã được đăng ký*.
3. Mở phiên, bật camera và cho phép quyền. Kiểm tra các trường hợp:
   - Một người → *Đã điểm danh*.
   - Đứng lại lần nữa → *đã điểm danh lúc …*.
   - Hai người cùng khung → *Nhiều khuôn mặt*.
   - Người chưa đăng ký → *Người lạ*.
   - Che camera → *Không tìm thấy khuôn mặt*.
4. Tắt quyền camera trong trình duyệt → trang hướng dẫn bật lại. Rút webcam → *Camera bị ngắt kết nối*.
5. F5 giữa phiên → thời gian còn lại không bị đặt lại. *Kết thúc phiên* → camera tắt, kết quả mới bị từ chối.
6. RTSP: chọn *Camera IP*, nhập `rtsp://user:pass@ip:554/...`. Sai địa chỉ → sau vài lần thử sẽ báo lỗi, mật khẩu được ẩn thành `***`.
7. Báo cáo → *Xuất Excel*, mở file và đối chiếu với bảng trên web.

---

## 8. Hạn chế đã biết

- Webcam và RTSP thật chưa được kiểm thử trong môi trường phát triển (xem mục 7).
- Không có model MiniFASNet đi kèm. Chế độ texture chỉ là thử nghiệm.
- Không đổi được tên lớp và mã môn sau khi tạo, vì chúng gắn với thư mục dataset và lịch sử. Chỉ sửa được mô tả và tên môn.
- Xoá sinh viên chuyển thư mục vào `dataset\<LỚP>\.deleted\` (có thể khôi phục thủ công). Cập nhật mẫu mặt giữ mẫu cũ trong `.previous\`.
- Ứng dụng chỉ nghe trên `127.0.0.1`, không có đăng nhập; không mở ra mạng LAN khi chưa thêm xác thực.
- Không nên ghi điểm danh cùng lúc bằng app desktop và web cho **cùng** một phiên. Dữ liệu vẫn an toàn nhờ chỉ mục duy nhất, nhưng file Excel lớp sẽ được ghi bởi cả hai.

## 9. File đã tạo/sửa

- **Mới:** `backend/` (app, services, schemas, db, migration), `frontend/` (React), `tests/`, `setup.ps1`, `run.ps1`, `Cai-Dat.cmd`, `Chay-SmartAttendance.cmd`, `requirements-web.txt`, `README.vi.md`, `attendance_system/functions/identity.py` (chuẩn hoá mã lớp, mã SV, họ tên, thư mục dùng chung).
- **Sửa:**
  - `functions/anti_spoof.py`: lỗi không còn bị coi là LIVE; thêm `has_model`, `allow_texture`.
  - `functions/face_recognizer.py`: dùng `identity.py`; `enroll_student` trả tên thư mục chuẩn hoá; xoá vào `.deleted`; thêm `update_student_samples`; khoá khi tải model; đổi tên thư mục có thử lại khi file bị khoá trên Windows.
  - `functions/database.py`: `update_student_info` chỉ sửa trong lớp của sinh viên.
  - `ui/dialogs.py`: dùng tên thư mục chuẩn hoá khi ghi log và sheet.
  - `requirements-dev.txt`, `.gitignore`.
