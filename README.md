# Smart Attendance System - Computer Vision Assignment

## Run

```powershell
cd attendance_system
pip install -r requirements.txt
python main.py
```

Create/select a class and subject, choose a slot, then select either **Webcam**
or **IP Camera (RTSP)**. For RTSP, enter a URL beginning with `rtsp://`.

## Demo sequence

1. Start the camera and show the live RTSP/webcam stream.
2. Click **Capture Face** or press **C** to crop and save the primary face frame.
3. Use **Enroll** to register one stable face with MSSV and full name.
4. Enable **Auto Recognize** and show name, MSSV, confidence, date and time.
5. Show `attendance.xlsx` and the on-screen attendance log.
6. Let a distant bystander enter the background: a tiny face is ignored, while a
   second significant face safely blocks enrollment/recognition.

## Assignment coverage

| Requirement | Implementation |
|---|---|
| RTSP stream | Selectable RTSP source, FFmpeg backend, reconnect loop |
| Video to image frames | Face crop via button or `C`, timestamped JPEG output |
| Face detection | SCRFD detector, bounding boxes and five landmarks |
| Face recognition | ArcFace embeddings and cosine similarity |
| Student/time output | MSSV, name, confidence, date/time in SQLite and Excel |
| Preprocessing | Gaussian denoise and CLAHE light balancing |
| Presentation | `outputs/Smart_Attendance_System_Presentation.pptx` |

## Important thresholds

- Recognition cosine score: `0.60`
- Minimum best-vs-second identity margin: `0.08`
- Incidental background face: at most `1.2%` of the frame and `22%` of the
  primary face area

These values are in `attendance_system/config.py` and should be calibrated with
the actual classroom camera before the final demonstration.
