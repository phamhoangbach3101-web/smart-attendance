"""FastAPI application: REST API, recognition WebSocket and the built frontend."""
import asyncio
import os
import platform
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import FastAPI, File, Form, Query, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from backend import schemas
from backend.container import Container
from backend.errors import ServiceError, invalid
from backend.services.recognition import MAX_FRAME_BYTES
from backend.services.settings import validate_rtsp

APP_VERSION = '1.0.0'
DEV_ORIGINS = ['http://127.0.0.1:5173', 'http://localhost:5173']
TICK_SECONDS = 10


def create_app(container: Optional[Container] = None, load_models: bool = True):
    holder = {}
    inference_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix='inference')

    @asynccontextmanager
    async def lifespan(app):
        c = holder.get('c') or Container()
        holder['c'] = c
        app.state.container = c
        if load_models:
            c.models.load_async()
        stop = asyncio.Event()

        async def ticker():
            while not stop.is_set():
                try:
                    await run_in_threadpool(c.tick)
                except Exception as exc:
                    print(f'[WARNING] tick failed: {exc}')
                try:
                    await asyncio.wait_for(stop.wait(), TICK_SECONDS)
                except asyncio.TimeoutError:
                    pass

        task = asyncio.create_task(ticker())
        yield
        stop.set()
        task.cancel()
        c.rtsp.stop_all()
        inference_pool.shutdown(wait=False, cancel_futures=True)

    if container is not None:
        holder['c'] = container
    app = FastAPI(title='Smart Attendance API', version=APP_VERSION, lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=DEV_ORIGINS, allow_credentials=False,
                       allow_methods=['*'], allow_headers=['*'])

    def C() -> Container:
        return holder['c']

    @app.exception_handler(ServiceError)
    async def service_error(_, exc: ServiceError):
        return JSONResponse(status_code=exc.status_code,
                            content={'detail': exc.message, 'code': exc.code, 'details': exc.details})

    @app.exception_handler(RequestValidationError)
    async def validation_error(_, exc: RequestValidationError):
        parts = []
        for err in exc.errors():
            loc = '.'.join(str(p) for p in err.get('loc', []) if p not in ('body', 'query', 'path'))
            parts.append(f'{loc}: {err.get("msg")}')
        return JSONResponse(status_code=422, content={'detail': 'Dữ liệu không hợp lệ — ' + '; '.join(parts),
                                                      'code': 'validation_error'})

    async def read_upload(f: UploadFile):
        data = await f.read(MAX_FRAME_BYTES + 1)
        if len(data) > MAX_FRAME_BYTES:
            raise ServiceError(413, f'Ảnh "{f.filename}" vượt quá 3 MB.', 'frame_too_large')
        return data

    # ------------------------------------------------------------ system
    @app.get('/api/health')
    def health():
        c = C()
        return {'ok': True, 'version': APP_VERSION, 'time': time.strftime('%Y-%m-%d %H:%M:%S'),
                'models': c.models.status(), 'migration': c.migration,
                'active_sessions': len(c.sessions.list(state='active', limit=50))}

    @app.get('/api/models/status')
    def model_status():
        return C().models.status()

    @app.post('/api/models/reload')
    def model_reload():
        c = C()
        if c.models.state == 'error':
            c.models.state = 'idle'
        c.models.load_async()
        return c.models.status()

    @app.get('/api/system')
    def system_info():
        c = C()
        versions = {}
        for mod in ('fastapi', 'uvicorn', 'numpy', 'cv2', 'insightface', 'onnxruntime', 'pandas', 'openpyxl'):
            try:
                versions[mod] = getattr(__import__(mod), '__version__', '?')
            except Exception:
                versions[mod] = None
        return {'python': sys.version.split()[0], 'platform': platform.platform(),
                'executable': sys.executable, 'packages': versions,
                'paths': {'database': c.paths.db_path, 'dataset': c.paths.dataset_dir,
                          'models': c.paths.models_dir, 'exports': c.paths.exports_dir,
                          'backups': c.paths.backups_dir, 'frontend': c.paths.frontend_dist},
                'frontend_built': os.path.exists(os.path.join(c.paths.frontend_dist, 'index.html'))}

    @app.get('/api/dashboard')
    def dashboard(date: Optional[str] = None):
        return C().reports.dashboard(date)

    # ----------------------------------------------------------- catalog
    @app.get('/api/classes')
    def list_classes(q: Optional[str] = None):
        return C().catalog.list_classes(q)

    @app.post('/api/classes', status_code=201)
    def create_class(body: schemas.ClassIn):
        return C().catalog.create_class(body.name, body.description)

    @app.patch('/api/classes/{class_id}')
    def update_class(class_id: int, body: schemas.ClassPatch):
        return C().catalog.update_class(class_id, body.description)

    @app.delete('/api/classes/{class_id}')
    def delete_class(class_id: int):
        return C().catalog.delete_class(class_id)

    @app.get('/api/courses')
    def list_courses(class_name: Optional[str] = None, q: Optional[str] = None):
        return C().catalog.list_courses(class_name, q)

    @app.post('/api/courses', status_code=201)
    def create_course(body: schemas.CourseIn):
        return C().catalog.create_course(body.class_name, body.subject, body.subject_name)

    @app.patch('/api/courses/{course_id}')
    def update_course(course_id: int, body: schemas.CoursePatch):
        return C().catalog.update_course(course_id, body.subject_name)

    @app.delete('/api/courses/{course_id}')
    def delete_course(course_id: int):
        return C().catalog.delete_course(course_id)

    # ---------------------------------------------------------- students
    @app.get('/api/students')
    def list_students(class_name: Optional[str] = None, q: Optional[str] = None,
                      face_status: Optional[str] = None):
        return C().students.list(class_name, q, face_status)

    @app.post('/api/students/sync')
    def sync_students():
        return {'changed_classes': C().students.sync()}

    @app.get('/api/students/lookup-face/{student_id}')
    def lookup_face(student_id: str):
        existing = C().students.find_existing_face(student_id)
        if not existing:
            return {'has_face': False}
        return {
            'has_face': True,
            'source_class': existing['class_name'],
            'full_name': existing['full_name'],
            'student_id': existing['student_id'],
            'photo_count': len(existing['photos']),
        }

    @app.post('/api/students', status_code=201)
    async def enroll(class_name: str = Form(...), student_id: str = Form(...), full_name: str = Form(...),
                     files: Optional[List[UploadFile]] = File(None)):
        images = []
        if files:
            for f in files:
                if f.filename:
                    images.append(await read_upload(f))
        return await run_in_threadpool(C().students.enroll, class_name, student_id, full_name, images)

    @app.post('/api/enrollment/check')
    async def check_sample(file: UploadFile = File(...)):
        data = await read_upload(file)
        res = await run_in_threadpool(C().recognition.analyze_sample, data)
        return {k: v for k, v in res.items() if k not in ('embedding', 'crop', 'raw', 'det_box')}

    @app.get('/api/students/import/template')
    def download_import_template():
        content = C().excel_import.generate_template(include_sample=True)
        return Response(
            content,
            media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            headers={'Content-Disposition': 'attachment; filename="Mau_Import_Sinh_Vien.xlsx"'}
        )

    @app.post('/api/students/import/preview')
    async def preview_import(file: UploadFile = File(...), default_class: Optional[str] = Form(None)):
        filename = file.filename or ''
        if not filename.lower().endswith(('.xlsx', '.xls')):
            raise ServiceError(400, 'Chỉ chấp nhận file định dạng Excel (.xlsx).', 'invalid_format')
        data = await file.read()
        if not data:
            raise ServiceError(422, 'File rỗng.', 'empty_file')
        if len(data) > 30 * 1024 * 1024:
            raise ServiceError(413, 'File Excel vượt quá 30 MB.', 'file_too_large')
        return await run_in_threadpool(C().excel_import.preview, data, default_class)

    @app.post('/api/students/import/commit')
    async def commit_import(body: schemas.ImportCommitIn):
        return await run_in_threadpool(
            C().excel_import.commit,
            body.session_token,
            body.overrides,
            body.default_conflict or 'skip',
            body.default_class
        )

    @app.get('/api/students/{pk}')
    def get_student(pk: int):
        return C().students.get(pk)

    @app.patch('/api/students/{pk}')
    def update_student(pk: int, body: schemas.StudentPatch):
        return C().students.update(pk, body.student_id, body.full_name)

    @app.delete('/api/students/{pk}')
    def delete_student(pk: int):
        return C().students.delete(pk)

    @app.get('/api/students/{pk}/history')
    def student_history(pk: int):
        return C().students.history(pk)

    @app.post('/api/students/{pk}/face')
    async def update_face(pk: int, files: List[UploadFile] = File(...)):
        images = [await read_upload(f) for f in files]
        return await run_in_threadpool(C().students.update_face, pk, images)

    @app.get('/api/students/{pk}/photos/{name}')
    def student_photo(pk: int, name: str):
        return FileResponse(C().students.photo_path(pk, name), headers={'Cache-Control': 'no-store'})

    # ---------------------------------------------------------- sessions
    @app.get('/api/sessions')
    def list_sessions(date: Optional[str] = None, class_name: Optional[str] = None,
                      subject: Optional[str] = None, state: Optional[str] = None):
        return C().sessions.list(date, class_name, subject, state)

    @app.post('/api/sessions', status_code=201)
    def open_session(body: schemas.SessionIn):
        return C().sessions.open(body.class_name, body.subject, body.slot, body.duration_minutes,
                                 body.camera_type, body.reopen)

    @app.get('/api/sessions/{sid}')
    def get_session(sid: int):
        return C().sessions.get(sid)

    @app.get('/api/sessions/{sid}/records')
    def session_records(sid: int):
        return C().sessions.records(sid)

    @app.post('/api/sessions/{sid}/end')
    def end_session(sid: int):
        return C().sessions.end(sid)

    @app.post('/api/sessions/{sid}/reopen')
    def reopen_session(sid: int, body: schemas.ReopenIn):
        return C().sessions.reopen(sid, body.duration_minutes, body.camera_type)

    @app.post('/api/sessions/{sid}/frame')
    async def post_frame(sid: int, file: UploadFile = File(...), frame_id: int = Form(0),
                         record: int = Form(1)):
        data = await read_upload(file)
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(inference_pool, C().recognition.process_frame, sid, data,
                                          frame_id, bool(record))

    @app.websocket('/ws/sessions/{sid}')
    async def ws_session(websocket: WebSocket, sid: int):
        """Binary frames: 4-byte little-endian frame id, 1 flag byte (bit0 = record), JPEG.

        Only the newest unprocessed frame is kept; older ones are dropped so
        latency never accumulates while inference is busy.
        """
        await websocket.accept()
        c = C()
        try:
            c.sessions.get(sid)
        except ServiceError as exc:
            await websocket.send_json({'type': 'error', 'status': 'session_not_found', 'message': exc.message})
            await websocket.close()
            return
        loop = asyncio.get_running_loop()
        slot = {'item': None, 'dropped': 0}
        ready = asyncio.Event()

        async def receiver():
            while True:
                msg = await websocket.receive()
                if msg['type'] == 'websocket.disconnect':
                    return
                data = msg.get('bytes')
                if not data:
                    continue
                if len(data) < 6 or len(data) > MAX_FRAME_BYTES + 5:
                    await websocket.send_json({'type': 'result', 'status': 'invalid_frame', 'frame_id': 0,
                                               'session_id': sid, 'faces': [],
                                               'message': 'Khung hình không hợp lệ.'})
                    continue
                if slot['item'] is not None:
                    slot['dropped'] += 1
                slot['item'] = (int.from_bytes(data[:4], 'little'), bool(data[4] & 1), data[5:])
                ready.set()

        async def processor():
            while True:
                await ready.wait()
                ready.clear()
                item, slot['item'] = slot['item'], None
                if item is None:
                    continue
                fid, record, payload = item
                try:
                    res = await loop.run_in_executor(inference_pool, c.recognition.process_frame,
                                                     sid, payload, fid, record)
                except ServiceError as exc:
                    res = {'status': 'error', 'frame_id': fid, 'session_id': sid, 'faces': [],
                           'message': exc.message}
                except Exception as exc:
                    res = {'status': 'error', 'frame_id': fid, 'session_id': sid, 'faces': [],
                           'message': f'Lỗi xử lý: {type(exc).__name__}'}
                res['type'] = 'result'
                res['dropped'] = slot['dropped']
                await websocket.send_json(res)

        recv = asyncio.create_task(receiver())
        proc = asyncio.create_task(processor())
        try:
            done, pending = await asyncio.wait({recv, proc}, return_when=asyncio.FIRST_COMPLETED)
            for t in pending:
                t.cancel()
            for t in done:
                if t.exception() and not isinstance(t.exception(), WebSocketDisconnect):
                    print(f'[WARNING] websocket task error: {t.exception()}')
        except WebSocketDisconnect:
            pass
        finally:
            recv.cancel()
            proc.cancel()

    # -------------------------------------------------------------- rtsp
    @app.post('/api/sessions/{sid}/rtsp/start')
    def rtsp_start(sid: int, body: schemas.RtspStartIn):
        c = C()
        session = c.sessions.get(sid)
        if session['state'] != 'active':
            raise ServiceError(409, 'Phiên đã kết thúc.', 'session_closed')
        c.models.require_ready()
        url = c.settings.get()['rtsp_url'] if body.use_saved else validate_rtsp(body.url)
        if not url:
            raise invalid('Chưa nhập địa chỉ RTSP (hoặc chưa lưu trong Cài đặt).')
        return c.rtsp.start(sid, url, body.record)

    @app.post('/api/sessions/{sid}/rtsp/stop')
    def rtsp_stop(sid: int):
        return {'stopped': C().rtsp.stop(sid)}

    @app.patch('/api/sessions/{sid}/rtsp')
    def rtsp_patch(sid: int, body: schemas.RtspPatch):
        worker = C().rtsp.get(sid)
        if worker is None:
            raise ServiceError(404, 'Camera RTSP chưa chạy.', 'rtsp_not_running')
        worker.record = body.record
        return worker.status()

    @app.get('/api/sessions/{sid}/rtsp/status')
    def rtsp_status(sid: int):
        worker = C().rtsp.get(sid)
        return worker.status() if worker else {'session_id': sid, 'state': 'stopped', 'result': None}

    @app.get('/api/sessions/{sid}/rtsp/stream')
    async def rtsp_stream(sid: int, request: Request):
        worker = C().rtsp.get(sid)
        if worker is None:
            raise ServiceError(404, 'Camera RTSP chưa chạy.', 'rtsp_not_running')

        async def gen():
            last = None
            while worker.state not in ('stopped', 'error'):
                if await request.is_disconnected():
                    break
                jpg = worker.jpeg()
                if jpg is not None and jpg is not last:
                    last = jpg
                    yield (b'--frame\r\nContent-Type: image/jpeg\r\nContent-Length: ' +
                           str(len(jpg)).encode() + b'\r\n\r\n' + jpg + b'\r\n')
                await asyncio.sleep(0.08)

        return StreamingResponse(gen(), media_type='multipart/x-mixed-replace; boundary=frame',
                                 headers={'Cache-Control': 'no-store'})

    # ----------------------------------------------------------- reports
    def _filters(date_from, date_to, class_name, subject, slot, q, status):
        if status not in (None, '', 'present', 'absent', 'unknown'):
            raise invalid('Trạng thái lọc không hợp lệ.')
        return {'date_from': date_from, 'date_to': date_to, 'class_name': class_name,
                'subject': subject, 'slot': slot, 'q': q, 'status': status or None}

    @app.get('/api/history')
    @app.get('/api/reports/history')
    def history(date_from: Optional[str] = None, date_to: Optional[str] = None,
                class_name: Optional[str] = None, subject: Optional[str] = None,
                slot: Optional[int] = Query(None, ge=1, le=20), q: Optional[str] = None,
                status: Optional[str] = None):
        return C().reports.history(_filters(date_from, date_to, class_name, subject, slot, q, status))

    @app.get('/api/reports/export')
    @app.get('/api/reports/export/excel')
    def export(date_from: Optional[str] = None, date_to: Optional[str] = None,
               class_name: Optional[str] = None, subject: Optional[str] = None,
               slot: Optional[int] = Query(None, ge=1, le=20), q: Optional[str] = None,
               status: Optional[str] = None):
        name, content, _ = C().reports.export_xlsx(
            _filters(date_from, date_to, class_name, subject, slot, q, status))
        return Response(content, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                        headers={'Content-Disposition': f'attachment; filename="{name}"'})

    # ---------------------------------------------------------- settings
    @app.get('/api/settings')
    def get_settings():
        return C().settings.public()

    @app.put('/api/settings')
    def put_settings(body: schemas.SettingsIn):
        return C().settings.update(body.model_dump(exclude_none=True))

    # ---------------------------------------------------------- models & migration
    @app.get('/api/models/info')
    def get_model_info():
        return C().models.status()

    @app.get('/api/models/migration/status')
    def get_migration_status():
        return C().migration_service.status()

    @app.post('/api/models/migrate')
    async def migrate_embeddings():
        return await run_in_threadpool(C().migration_service.migrate_dataset)

    @app.post('/api/models/rollback')
    async def rollback_embeddings():
        return await run_in_threadpool(C().migration_service.rollback)

    @app.get('/api/models/calibration')
    async def calibrate_thresholds():
        return await run_in_threadpool(
            C().models.adaface.calibrate_thresholds, C().paths.dataset_dir
        )

    # ---------------------------------------------------------- frontend
    dist = (container.paths if container else None)
    _mount_frontend(app, dist.frontend_dist if dist else None)
    return app


def _mount_frontend(app, dist_dir=None):
    from backend import ROOT_DIR
    dist_dir = dist_dir or os.environ.get('SA_FRONTEND_DIST') or os.path.join(ROOT_DIR, 'frontend', 'dist')
    assets = os.path.join(dist_dir, 'assets')
    if os.path.isdir(assets):
        app.mount('/assets', StaticFiles(directory=assets), name='assets')

    @app.get('/{full_path:path}', include_in_schema=False)
    def spa(full_path: str):
        if full_path.startswith(('api/', 'ws/')):
            return JSONResponse(status_code=404, content={'detail': 'Không tìm thấy API.'})
        candidate = os.path.abspath(os.path.join(dist_dir, full_path))
        if full_path and candidate.startswith(os.path.abspath(dist_dir)) and os.path.isfile(candidate):
            return FileResponse(candidate)
        index = os.path.join(dist_dir, 'index.html')
        if os.path.exists(index):
            return FileResponse(index, headers={'Cache-Control': 'no-cache'})
        return JSONResponse(status_code=503, content={
            'detail': 'Chưa build giao diện. Chạy setup.ps1 (hoặc: cd frontend; npm run build).'})
