"""FastAPI web backend for Smart Attendance.

The recognition modules live in ``attendance_system/`` and import each other as
top-level packages (``from functions.x import ...``, ``from config import ...``),
so that directory is put on ``sys.path`` before anything else is imported.
"""
import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORE_DIR = os.path.join(ROOT_DIR, 'attendance_system')
if CORE_DIR not in sys.path:
    sys.path.insert(0, CORE_DIR)
