import sys
import os
import traceback

def global_exception_handler(exc_type, exc_value, exc_traceback):
    with open('error_log.txt', 'a', encoding='utf-8') as f:
        f.write('Uncaught exception:\\n')
        traceback.print_exception(exc_type, exc_value, exc_traceback, file=f)
    sys.__excepthook__(exc_type, exc_value, exc_traceback)
sys.excepthook = global_exception_handler
import warnings
warnings.filterwarnings('ignore', category=FutureWarning)
warnings.filterwarnings('ignore', category=DeprecationWarning)
import onnxruntime

from PyQt5.QtWidgets import QApplication, QMainWindow, QStackedWidget
from config import (APP_MIN_HEIGHT, APP_MIN_WIDTH, APP_TITLE,
                    COLOR_BG_CARD, COLOR_BG_DARK, COLOR_BORDER, COLOR_TEXT,
                    COLOR_TEXT_DIM, DATASET_DIR, DB_PATH,
                    RECOGNITION_MIN_MARGIN)
# Galleries now hold AdaFace embeddings; use AdaFace's threshold, not ArcFace's 0.6.
from functions.adaface_service import DEFAULT_COSINE_THRESHOLD
from functions.database import Database
from functions.face_recognizer import FaceRecognizer
from ui.screens import SetupScreen, AttendanceApp
from ui.styles import GLOBAL_STYLE

class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.setMinimumSize(APP_MIN_WIDTH, APP_MIN_HEIGHT)
        self.setStyleSheet(f'\n            QMainWindow {{ background-color: {COLOR_BG_DARK}; }}\n            QPushButton {{\n                background-color: {COLOR_BG_CARD}; color: {COLOR_TEXT};\n                border: 1px solid {COLOR_BORDER}; border-radius: 6px; font-weight: bold;\n            }}\n            QPushButton:hover {{ background-color: {COLOR_BORDER}; }}\n            QLineEdit, QComboBox {{\n                background-color: {COLOR_BG_CARD}; color: {COLOR_TEXT};\n                border: 1px solid {COLOR_BORDER}; border-radius: 6px; padding: 5px;\n            }}\n            QTableWidget {{\n                background-color: {COLOR_BG_CARD}; color: {COLOR_TEXT};\n                gridline-color: {COLOR_BORDER}; border: none;\n            }}\n            QHeaderView::section {{\n                background-color: {COLOR_BG_DARK}; color: {COLOR_TEXT_DIM}; border: none; font-weight: bold;\n            }}\n            QScrollBar:vertical {{\n                background-color: {COLOR_BG_DARK}; width: 14px;\n            }}\n            QScrollBar::handle:vertical {{\n                background-color: {COLOR_BORDER}; border-radius: 7px;\n            }}\n        ')
        self.db = Database(DB_PATH)
        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)
        self.setup_screen = SetupScreen(self)
        self.stack.addWidget(self.setup_screen)

    def start_session(self, class_name, subject, slot_number=1, slot_minutes=15,
                      camera_source=0):
        class_dataset_dir = os.path.join(DATASET_DIR, class_name)
        self.face_recognizer = FaceRecognizer(
            class_dataset_dir,
            threshold=DEFAULT_COSINE_THRESHOLD,
            min_margin=RECOGNITION_MIN_MARGIN,
        )
        self.app_screen = AttendanceApp(
            self, class_name, subject, self.face_recognizer, self.db,
            slot_number, slot_minutes, camera_source
        )
        self.stack.addWidget(self.app_screen)
        self.stack.setCurrentIndex(1)

    def show_setup(self):
        self.stack.setCurrentIndex(0)
        if hasattr(self, 'app_screen'):
            self.stack.removeWidget(self.app_screen)
            self.app_screen.deleteLater()
            del self.app_screen
        self.setup_screen.refresh_sessions()

    def closeEvent(self, event):
        if hasattr(self, 'app_screen'):
            self.app_screen._finalize_attendance_sheet()
        event.accept()
if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setStyleSheet(GLOBAL_STYLE)
    os.makedirs(DATASET_DIR, exist_ok=True)
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
