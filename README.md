# Smart Attendance System

Face-recognition attendance for classrooms: a webcam or IP camera (RTSP) stream is processed in real time, each student is identified with ArcFace embeddings, and attendance (student ID, name, confidence, timestamp) is written to SQLite and exported to Excel.

Team project for the Computer Vision course (CPV301) at FPT University Hanoi, Group 5, 06/2026.
**My role:** team lead; I built the face detection and face recognition pipeline.

## How it works

```
Camera (webcam / RTSP)
   │  background thread, keeps only the latest frame, auto-reconnects
   ▼
Face detection ── SCRFD (InsightFace buffalo_sc): boxes + 5 landmarks
   │  primary-face selection: tiny background faces are ignored,
   │  a second significant face blocks the decision
   ▼
Face recognition ── ArcFace 512-d embedding + cosine similarity
   │  accept only if  best score ≥ 0.60  AND  best − second-best ≥ 0.08
   ▼
Attendance log ── SQLite + Excel export, PyQt5 desktop UI
```

Key design choices:

- **Open-set decision.** An unknown person must be rejected, not matched to the closest student. Two conditions are required: an absolute cosine threshold and a margin over the second-best identity, so that two look-alike students do not get confused.
- **Duplicate enrollment check.** A new student is rejected if their embedding already matches an enrolled identity.
- **Bystander handling.** A face smaller than 1.2% of the frame and 22% of the primary face is treated as incidental. Any larger second face blocks enrollment and recognition, so attendance is never assigned to the wrong person.
- **Robust streaming.** Frame capture runs in its own thread with a 1-frame buffer and automatic RTSP reconnection.

All thresholds live in [`attendance_system/config.py`](attendance_system/config.py).

## Project structure

```
attendance_system/
├── main.py                  # PyQt5 entry point
├── config.py                # thresholds, paths, camera source
├── functions/
│   ├── face_detector.py     # SCRFD detection, primary-face selection
│   ├── face_recognizer.py   # ArcFace embeddings, enrollment
│   ├── matching.py          # open-set decision rule (shared with evaluate.py)
│   ├── stream.py            # threaded camera / RTSP capture
│   ├── preprocessor.py      # Gaussian denoise + CLAHE (optional)
│   ├── anti_spoof.py        # liveness check (experimental, off by default)
│   ├── database.py          # SQLite attendance store
│   └── biometrics_logger.py # enrollment / attendance image logs
├── ui/                      # screens and dialogs
├── evaluate.py              # offline evaluation + threshold sweep
├── tools/capture_eval.py    # record evaluation images from a webcam
└── tests/                   # unit tests
docs/EVALUATION.md           # evaluation protocol
```

## Run it

Requires Python 3.11 and a webcam (or an RTSP URL).

```bash
cd attendance_system
python -m venv .venv
.venv\Scripts\activate          # Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

The InsightFace `buffalo_sc` weights are downloaded automatically into `attendance_system/models/` on the first run.

Demo flow: create a class and subject, then start the camera. Press **C** or **Capture Face** to enroll a student with their ID and name. Turn on **Auto Recognize**; recognized students appear in the attendance log with confidence and time.

## Evaluation

The decision rule lives in [`functions/matching.py`](attendance_system/functions/matching.py) and is shared by the app and the offline evaluator, so the reported numbers describe exactly what the app does.

```bash
cd attendance_system
pip install -r requirements-dev.txt
python -m pytest tests                                  # unit tests, no camera needed
python -m tools.capture_eval --person P01 --split enroll  # record evaluation data
python evaluate.py --data ../eval_data --out ../results/baseline
```

Protocol, metrics and planned experiments: [docs/EVALUATION.md](docs/EVALUATION.md). Results will be added here once the dataset is recorded.

Unit tests: 8/8 passing on Windows 11, Python 3.11.9 (20/10/2026).

## Privacy

Face images and embeddings are biometric personal data. This repository contains **no faces, embeddings or attendance records**: `dataset/`, `attendance.db` and exports are git-ignored. Only enroll people who have given consent.

## Limitations and roadmap

Current status, stated honestly:

- **No quantitative evaluation yet.** The thresholds were chosen manually.
- **Anti-spoofing is experimental and disabled** (`ANTISPOOF_ENABLED = False`). Without the MiniFASNet ONNX model it falls back to a hand-crafted texture heuristic.
- **Preprocessing (Gaussian + CLAHE) is optional and off by default.**

Planned:

1. Evaluation set recorded in separate sessions (lighting, pose, unknown people). Metrics: identification accuracy, false-accept, false-reject, unknown-rejection rate, FPS on stated hardware. Threshold chosen from the data.
2. Multi-sample enrollment, quality filtering and multi-frame confirmation, each measured before vs. after.
3. Real anti-spoofing (MiniFASNet) tested against printed photos and phone screens.
4. Recognition core separated from the UI and exposed as a REST API, packaged with Docker.
