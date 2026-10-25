"""Filesystem locations used by the web backend.

Defaults point at the existing desktop data in ``attendance_system/`` so both
apps share the same database, dataset folders and models. Every path can be
overridden with an environment variable (used by the tests).
"""
import os
from dataclasses import dataclass

from backend import CORE_DIR, ROOT_DIR


@dataclass
class AppPaths:
    data_dir: str
    db_path: str
    dataset_dir: str
    models_dir: str
    exports_dir: str
    backups_dir: str
    sessions_file: str
    frontend_dist: str

    @classmethod
    def from_env(cls, data_dir=None):
        data_dir = data_dir or os.environ.get('SA_DATA_DIR') or CORE_DIR
        paths = cls(
            data_dir=data_dir,
            db_path=os.environ.get('SA_DB_PATH') or os.path.join(data_dir, 'attendance.db'),
            dataset_dir=os.path.join(data_dir, 'dataset'),
            models_dir=os.environ.get('SA_MODELS_DIR') or os.path.join(CORE_DIR, 'models'),
            exports_dir=os.path.join(data_dir, 'exports'),
            backups_dir=os.path.join(data_dir, 'backups'),
            sessions_file=os.path.join(data_dir, 'sessions.json'),
            frontend_dist=os.environ.get('SA_FRONTEND_DIST') or os.path.join(ROOT_DIR, 'frontend', 'dist'),
        )
        for d in (paths.dataset_dir, paths.exports_dir, paths.backups_dir):
            os.makedirs(d, exist_ok=True)
        return paths

    def class_dir(self, class_name):
        """Dataset folder of a class; class_name must already be normalised."""
        path = os.path.abspath(os.path.join(self.dataset_dir, class_name))
        if os.path.dirname(path) != os.path.abspath(self.dataset_dir):
            raise ValueError('Invalid class path')
        return path
