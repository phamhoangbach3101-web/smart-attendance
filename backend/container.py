"""Wires paths, database and services together (one instance per app)."""
import threading

from backend.db import Database
from backend.paths import AppPaths
from backend.services.catalog import CatalogService
from backend.services.excel_import import ExcelImportService
from backend.services.migration import MigrationService
from backend.services.recognition import ModelManager, RecognitionService

from backend.services.reports import ReportService
from backend.services.rtsp import RtspManager
from backend.services.sessions import SessionService
from backend.services.settings import SettingsService
from backend.services.students import StudentService


class Container:
    def __init__(self, paths=None):
        self.paths = paths or AppPaths.from_env()
        self.db = Database(self.paths.db_path)
        self.migration = self.db.migrate(self.paths)
        self.settings = SettingsService(self.db)
        self.models = ModelManager(self.paths, self.settings)
        self.catalog = CatalogService(self.db, self.paths, models=self.models)
        self.sessions = SessionService(self.db, self.catalog)
        self.students = StudentService(self.db, self.paths, self.catalog, self.sessions, self.models)
        self.recognition = RecognitionService(self.models, self.settings, self.sessions, self.students)
        self.students.recognition = self.recognition
        self.excel_import = ExcelImportService(self.db, self.paths, self.catalog, self.students, self.recognition, self.models)
        self.migration_service = MigrationService(self.db, self.paths, self.models)
        self.reports = ReportService(self.db, self.paths, self.sessions)
        self.rtsp = RtspManager(self.recognition, self.settings, self.sessions)
        self.sessions.on_closed.append(self._on_session_closed)
        self.students.sync()

    def _on_session_closed(self, session):
        if self.rtsp.get(session['id']):
            threading.Thread(target=self.rtsp.stop, args=(session['id'],), daemon=True).start()
        threading.Thread(target=self._sync_sheet, args=(session,), daemon=True).start()

    def _sync_sheet(self, session):
        try:
            self.reports.sync_class_sheet(session)
        except Exception as exc:  # SQLite stays the source of truth
            print(f'[WARNING] Excel sync failed for session {session["id"]}: {exc}')

    def tick(self):
        """Periodic housekeeping: close expired sessions, adopt desktop-written rows."""
        self.sessions.expire_due()
        self.db.link_orphan_attendance()
