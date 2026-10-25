"""Batch student enrollment from a single Excel (.xlsx) file with embedded photos.

Supports:
1. Template generation with styled headers, guidance, and embedded sample portraits.
2. Direct extraction of embedded images from worksheet anchors (openpyxl + XML fallback).
3. Image-to-row matching strictly by anchor cell coordinate (never by display name).
4. Face detection, alignment, quality checking, and ArcFace embedding generation using SCRFD + ArcFace.
5. Reconciliation with SQLite database (already in class, exists in other class, or new).
6. Cross-class face reuse when a student is already registered elsewhere.
7. User preview with thumbnail data URLs, status indicators, and override actions.
8. Batch commit with error isolation (one faulty row does not abort the rest).
"""
import base64
import io
import re
import time
import unicodedata
import uuid
import xml.etree.ElementTree as ET
import zipfile

import cv2
import numpy as np
import openpyxl
from openpyxl.drawing.image import Image as OpenpyxlImage
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from backend import clock
from backend.errors import ServiceError, not_found
from functions.identity import (IdentityError, normalize_class, normalize_name,
                                normalize_student_id)


def _strip_accents(s: str) -> str:
    s = unicodedata.normalize('NFD', s)
    return ''.join(c for c in s if unicodedata.category(c) != 'Mn').lower().strip()


def make_thumbnail_data_url(image_bytes: bytes, max_size=(100, 100)) -> str:
    """Generate a lightweight JPEG base64 data URL for frontend preview."""
    try:
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            return None
        h, w = img.shape[:2]
        scale = min(max_size[0] / max(1, w), max_size[1] / max(1, h), 1.0)
        nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
        resized = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA)
        _, buf = cv2.imencode('.jpg', resized, [cv2.IMWRITE_JPEG_QUALITY, 80])
        b64 = base64.b64encode(buf.tobytes()).decode('ascii')
        return f'data:image/jpeg;base64,{b64}'
    except Exception:
        return None


class ExcelImportService:
    def __init__(self, db, paths, catalog, students, recognition, models):
        self.db = db
        self.paths = paths
        self.catalog = catalog
        self.students = students
        self.recognition = recognition
        self.models = models
        self._sessions_cache = {}  # token -> {created_at, rows, summary}

    # ------------------------------------------------------------- template
    def generate_template(self, include_sample=True) -> bytes:
        """Create a professional Excel template with styled columns and sample embedded portraits."""
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = 'Import_Sinh_Vien'

        # Colors & Fonts
        header_fill = PatternFill(start_color='16C784', end_color='16C784', fill_type='solid')
        header_font = Font(name='Segoe UI', size=11, bold=True, color='FFFFFF')
        align_center = Alignment(horizontal='center', vertical='center', wrap_text=True)
        align_left = Alignment(horizontal='left', vertical='center')
        thin_border = Border(
            left=Side(style='thin', color='E5E7EB'),
            right=Side(style='thin', color='E5E7EB'),
            top=Side(style='thin', color='E5E7EB'),
            bottom=Side(style='thin', color='E5E7EB')
        )

        headers = ['student_id', 'full_name', 'class_code', 'photo']
        titles = [
            'Mã sinh viên (*)\n(student_id)',
            'Họ và tên (*)\n(full_name)',
            'Mã lớp (*)\n(class_code)',
            'Ảnh chân dung (*)\n(Chèn ảnh vào ô)'
        ]

        ws.row_dimensions[1].height = 36
        for col_idx, (h, t) in enumerate(zip(headers, titles), 1):
            cell = ws.cell(row=1, column=col_idx, value=h)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = align_center

        ws.column_dimensions['A'].width = 22
        ws.column_dimensions['B'].width = 30
        ws.column_dimensions['C'].width = 20
        ws.column_dimensions['D'].width = 26

        # Sample rows
        sample_rows = [
            ('HE180001', 'Nguyễn Văn Mẫu', 'SE1501'),
            ('HE180002', 'Trần Thị Mai', 'SE1501'),
            ('HE180003', 'Lê Hoàng Long', 'SE1501'),
        ]

        # Try to find a real sample face in dataset
        import glob
        import os
        candidates = sorted(glob.glob(os.path.join(self.paths.dataset_dir, '*', '*', 'img_01.jpg')))
        sample_face_path = candidates[0] if candidates else None
        if sample_face_path and os.path.exists(sample_face_path):
            try:
                with open(sample_face_path, 'rb') as f:
                    sample_face_bytes = f.read()
            except Exception:
                pass

        for i, row_data in enumerate(sample_rows):
            r_idx = i + 2
            ws.row_dimensions[r_idx].height = 85
            for c_idx, val in enumerate(row_data, 1):
                c = ws.cell(row=r_idx, column=c_idx, value=val)
                c.font = Font(name='Segoe UI', size=11)
                c.alignment = align_left
                c.border = thin_border

            photo_cell = ws.cell(row=r_idx, column=4, value='')
            photo_cell.border = thin_border
            photo_cell.alignment = align_center

            # If sample face available and include_sample requested, embed in row 2
            if include_sample and sample_face_bytes and i == 0:
                try:
                    img_stream = io.BytesIO(sample_face_bytes)
                    img = OpenpyxlImage(img_stream)
                    img.width = 75
                    img.height = 75
                    ws.add_image(img, f'D{r_idx}')
                except Exception as exc:
                    print(f'[WARNING] cannot embed sample image: {exc}')
            else:
                photo_cell.value = '[Chèn ảnh tại đây]'
                photo_cell.font = Font(name='Segoe UI', size=9, italic=True, color='9CA3AF')

        # Add Instruction Sheet
        ws_guide = wb.create_sheet(title='Huong_Dan')
        ws_guide.column_dimensions['A'].width = 80
        instructions = [
            'HƯỚNG DẪN IMPORT SINH VIÊN & ĐĂNG KÝ KHUÔN MẶT BẰNG FILE EXCEL',
            '',
            '1. Quy định các cột thông tin:',
            '   - student_id: Mã sinh viên (chữ không dấu, số, dấu "-" hoặc ".", tối đa 32 ký tự).',
            '   - full_name: Họ và tên sinh viên (đầy đủ tiếng Việt có dấu hoặc không dấu).',
            '   - class_code: Mã lớp sinh viên theo học (ví dụ: SE1501, 1323, CPV301...).',
            '   - photo: Ô chứa ảnh chân dung của sinh viên.',
            '',
            '2. Cách chèn ảnh chân dung vào cột photo:',
            '   - Bước 1: Nhấp chuột chọn ô tương ứng tại cột photo của sinh viên (VD: ô D2, D3...).',
            '   - Bước 2: Trên thanh menu Excel, chọn "Insert" (Chèn) > "Pictures" (Hình ảnh) > "Place in Cell" hoặc "Place over Cells".',
            '   - Bước 3: Chọn file ảnh chân dung (JPG, JPEG hoặc PNG) và căn chỉnh ảnh nằm gọn trong ô.',
            '',
            '3. Lưu ý về chất lượng ảnh:',
            '   - Ảnh chân dung chụp thẳng, thấy rõ khuôn mặt, không bị che khuất mắt hoặc đeo khẩu trang.',
            '   - Mỗi ô photo chỉ chèn 01 ảnh duy nhất của sinh viên đó.',
            '   - Nếu sinh viên đã có khuôn mặt trong hệ thống từ lớp khác, hệ thống sẽ tự động kế thừa mà không bắt buộc có ảnh mới.',
            '',
            '4. Tải lên hệ thống:',
            '   - Lưu file dưới định dạng Excel (.xlsx).',
            '   - Vào màn hình "Sinh viên" > Chọn "Import Excel" và tải file vừa chuẩn bị lên.'
        ]
        for r, line in enumerate(instructions, 1):
            cell = ws_guide.cell(row=r, column=1, value=line)
            if r == 1:
                cell.font = Font(name='Segoe UI', size=13, bold=True, color='16C784')
            elif line.startswith(('1.', '2.', '3.', '4.')):
                cell.font = Font(name='Segoe UI', size=11, bold=True)
            else:
                cell.font = Font(name='Segoe UI', size=10, color='374151')

        out = io.BytesIO()
        wb.save(out)
        return out.getvalue()

    # -------------------------------------------------------- image extraction
    def extract_embedded_images(self, file_bytes: bytes) -> dict:
        """Extract all embedded images and map them by Excel row number (1-indexed).

        Returns:
            dict of { row_number: [{'data': bytes, 'col': int}, ...] }
        """
        row_images = {}

        # Strategy 1: openpyxl ws._images
        try:
            wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
            ws = self._find_data_sheet(wb)
            if ws and getattr(ws, '_images', None):
                for img in ws._images:
                    row_idx, col_idx = self._get_image_anchor_coords(img)
                    if row_idx is not None:
                        data = self._get_image_data(img)
                        if data:
                            row_images.setdefault(row_idx, []).append({'data': data, 'col': col_idx})
        except Exception as exc:
            print(f'[DEBUG] openpyxl image extraction error: {exc}')

        # Strategy 2: Fallback to direct XML drawing parsing if openpyxl found nothing
        if not row_images:
            try:
                fallback_map = self._extract_images_from_zip_xml(file_bytes)
                for r_idx, items in fallback_map.items():
                    row_images.setdefault(r_idx, []).extend(items)
            except Exception as exc:
                print(f'[DEBUG] XML drawing fallback extraction error: {exc}')

        return row_images

    @staticmethod
    def _find_data_sheet(wb):
        """Find the main data sheet."""
        for name in ['Import_Sinh_Vien', 'Danh sách sinh viên', 'Students', 'Sheet1']:
            if name in wb.sheetnames:
                return wb[name]
        return wb.active

    @staticmethod
    def _get_image_anchor_coords(img):
        """Get 1-indexed (row, col) from openpyxl Image anchor."""
        anchor = getattr(img, 'anchor', None)
        if anchor is None:
            return None, None
        if isinstance(anchor, str):
            from openpyxl.utils import coordinate_to_tuple
            try:
                r, c = coordinate_to_tuple(anchor)
                return r, c
            except Exception:
                return None, None
        if hasattr(anchor, '_from'):
            r = getattr(anchor._from, 'row', None)
            c = getattr(anchor._from, 'col', None)
            if r is not None and c is not None:
                return int(r) + 1, int(c) + 1
        if hasattr(anchor, 'row') and hasattr(anchor, 'col'):
            return int(anchor.row), int(anchor.col)
        return None, None

    @staticmethod
    def _get_image_data(img):
        """Retrieve raw bytes of an openpyxl image object."""
        if hasattr(img, '_data') and callable(img._data):
            return img._data()
        if hasattr(img, 'ref') and isinstance(img.ref, (bytes, bytearray)):
            return bytes(img.ref)
        if hasattr(img, 'ref') and hasattr(img.ref, 'read'):
            img.ref.seek(0)
            return img.ref.read()
        if hasattr(img, 'image') and hasattr(img.image, 'save'):
            b = io.BytesIO()
            img.image.save(b, format='JPEG')
            return b.getvalue()
        return None

    @staticmethod
    def _extract_images_from_zip_xml(file_bytes: bytes) -> dict:
        """Parse drawing XML directly from the .xlsx ZIP archive."""
        zf = zipfile.ZipFile(io.BytesIO(file_bytes))
        rels = {}
        for name in zf.namelist():
            if 'drawings/_rels/' in name and name.endswith('.rels'):
                try:
                    tree = ET.fromstring(zf.read(name))
                    for rel in tree:
                        rId = rel.attrib.get('Id')
                        target = rel.attrib.get('Target', '')
                        if target.startswith('/'):
                            target = target.lstrip('/')
                        elif target.startswith('../'):
                            target = 'xl/' + target[3:]
                        elif not target.startswith('xl/'):
                            target = 'xl/' + target
                        rels[rId] = target
                except Exception:
                    pass

        row_images = {}
        for name in zf.namelist():
            if 'drawings/drawing' in name and not name.endswith('.rels'):
                try:
                    tree = ET.fromstring(zf.read(name))
                    for elem in tree.iter():
                        if elem.tag.endswith('Anchor'):
                            from_elem = None
                            blip_elem = None
                            for child in elem.iter():
                                if child.tag.endswith('from'):
                                    from_elem = child
                                elif child.tag.endswith('blip'):
                                    blip_elem = child
                            if from_elem is not None and blip_elem is not None:
                                row_el, col_el = None, None
                                for c in from_elem:
                                    if c.tag.endswith('row'):
                                        row_el = c
                                    elif c.tag.endswith('col'):
                                        col_el = c
                                if row_el is not None and col_el is not None:
                                    row_idx = int(row_el.text) + 1
                                    col_idx = int(col_el.text) + 1
                                    embed_id = None
                                    for k, v in blip_elem.attrib.items():
                                        if k.endswith('embed'):
                                            embed_id = v
                                    if embed_id and embed_id in rels and rels[embed_id] in zf.namelist():
                                        img_data = zf.read(rels[embed_id])
                                        row_images.setdefault(row_idx, []).append({'col': col_idx, 'data': img_data})
                except Exception:
                    pass
        return row_images

    # ------------------------------------------------------------- preview
    def preview(self, file_bytes: bytes, default_class: str = None) -> dict:
        """Parse Excel rows, match embedded photos by cell anchor, analyze faces, and reconcile with DB."""
        wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
        ws = self._find_data_sheet(wb)
        if ws is None:
            raise ServiceError(422, 'Không tìm thấy trang tính dữ liệu trong file Excel.', 'invalid_excel')

        # 1. Map columns from header row
        header_row_idx = 1
        col_map = {}
        for r_num in range(1, 4):
            cols = {c: ws.cell(row=r_num, column=c).value for c in range(1, ws.max_column + 1)}
            cleaned = {_strip_accents(str(v or '')): c for c, v in cols.items()}
            matched_sid = next((c for k, c in cleaned.items() if any(x in k for x in ['student_id', 'masv', 'ma sv', 'ma sinh vien'])), None)
            matched_name = next((c for k, c in cleaned.items() if any(x in k for x in ['full_name', 'hoten', 'ho va ten', 'ho ten', 'name'])), None)
            matched_cls = next((c for k, c in cleaned.items() if any(x in k for x in ['class_code', 'class_name', 'malop', 'ma lop', 'lop', 'class'])), None)
            matched_photo = next((c for k, c in cleaned.items() if any(x in k for x in ['photo', 'anh', 'hinh', 'avatar', 'image'])), None)
            if matched_sid and matched_name:
                header_row_idx = r_num
                col_map = {
                    'student_id': matched_sid,
                    'full_name': matched_name,
                    'class_code': matched_cls or 3,
                    'photo': matched_photo or 4,
                }
                break

        if not col_map:
            col_map = {'student_id': 1, 'full_name': 2, 'class_code': 3, 'photo': 4}

        # 2. Extract embedded images
        row_images = self.extract_embedded_images(file_bytes)

        # 3. Read data rows
        parsed_rows = []
        raw_image_cache = {}  # row_index -> bytes

        with self.db.read() as conn:
            for r_idx in range(header_row_idx + 1, ws.max_row + 1):
                sid_raw = ws.cell(row=r_idx, column=col_map['student_id']).value
                name_raw = ws.cell(row=r_idx, column=col_map['full_name']).value
                cls_raw = ws.cell(row=r_idx, column=col_map['class_code']).value

                # Skip completely blank rows
                if sid_raw is None and name_raw is None and cls_raw is None:
                    continue

                sid_str = str(sid_raw or '').strip()
                name_str = str(name_raw or '').strip()
                cls_str = str(cls_raw or '').strip()
                if not cls_str and default_class:
                    cls_str = str(default_class).strip()

                row_item = {
                    'row_index': r_idx,
                    'student_id': sid_str,
                    'full_name': name_str,
                    'class_code': cls_str,
                    'has_image': False,
                    'image_preview': None,
                    'det_score': None,
                    'face_status': 'missing_photo',
                    'face_message': 'Chưa có ảnh chân dung',
                    'db_status': 'new',
                    'existing_class': None,
                    'existing_student_id': None,
                    'action': 'create',
                    'error': None,
                }

                # Validation of text fields
                try:
                    norm_sid = normalize_student_id(sid_str)
                    norm_name = normalize_name(name_str)
                    norm_cls = normalize_class(cls_str) if cls_str else ''
                    row_item['student_id'] = norm_sid
                    row_item['full_name'] = norm_name
                    row_item['class_code'] = norm_cls
                    if not norm_cls:
                        row_item['error'] = 'Chưa có mã lớp. Vui lòng chọn hoặc nhập mã lớp học mục tiêu.'
                        row_item['action'] = 'error'
                except IdentityError as exc:
                    row_item['error'] = str(exc)
                    row_item['action'] = 'error'

                # Database reconciliation
                if not row_item['error']:
                    # Check if student is already in target class
                    existing_in_class = conn.execute(
                        'SELECT id, student_id, full_name FROM students WHERE class_name=? AND active=1 '
                        'AND UPPER(REPLACE(student_id, " ", "")) = ?',
                        (norm_cls, norm_sid.upper())
                    ).fetchone()

                    if existing_in_class:
                        row_item['db_status'] = 'already_in_class'
                        row_item['existing_student_id'] = existing_in_class['id']
                        row_item['action'] = 'skip'  # default is skip, user can choose update
                    else:
                        # Check if student exists in another class
                        existing_other = conn.execute(
                            'SELECT id, class_name FROM students WHERE active=1 '
                            'AND UPPER(REPLACE(student_id, " ", "")) = ? AND class_name <> ?',
                            (norm_sid.upper(), norm_cls)
                        ).fetchone()
                        if existing_other:
                            row_item['db_status'] = 'exists_in_other_class'
                            row_item['existing_class'] = existing_other['class_name']
                            row_item['action'] = 'create'
                        else:
                            row_item['db_status'] = 'new'
                            row_item['action'] = 'create'

                # Embedded image handling
                imgs_in_row = row_images.get(r_idx, [])
                if len(imgs_in_row) > 1:
                    row_item['has_image'] = True
                    row_item['face_status'] = 'multiple_photos_in_row'
                    row_item['face_message'] = f'Có {len(imgs_in_row)} ảnh cùng nằm ở dòng này. Hãy để 1 ảnh duy nhất.'
                    row_item['image_preview'] = make_thumbnail_data_url(imgs_in_row[0]['data'])
                    raw_image_cache[r_idx] = imgs_in_row[0]['data']
                    row_item['error'] = row_item['face_message']
                    row_item['action'] = 'error'
                elif len(imgs_in_row) == 1:
                    img_bytes = imgs_in_row[0]['data']
                    row_item['has_image'] = True
                    raw_image_cache[r_idx] = img_bytes
                    row_item['image_preview'] = make_thumbnail_data_url(img_bytes)

                    # Analyze face using SCRFD & ArcFace
                    try:
                        analysis = self.recognition.analyze_sample(img_bytes)
                        if analysis.get('ok'):
                            score = analysis.get('det_score', 0.0)
                            row_item['det_score'] = score
                            row_item['face_status'] = 'valid'
                            row_item['face_message'] = f'Khuôn mặt rõ ràng (độ tin cậy {score:.0%})'
                        else:
                            reason = analysis.get('reason', 'no_face')
                            row_item['face_status'] = reason
                            row_item['face_message'] = analysis.get('message', 'Không tìm thấy khuôn mặt hợp lệ.')
                            row_item['error'] = f"Ảnh không hợp lệ: {row_item['face_message']}"
                            row_item['action'] = 'error'
                    except Exception as exc:
                        row_item['face_status'] = 'invalid_image'
                        row_item['face_message'] = f'Lỗi phân tích ảnh: {exc}'
                        row_item['error'] = row_item['face_message']
                        row_item['action'] = 'error'
                else:
                    # No image in Excel row
                    if row_item['db_status'] == 'exists_in_other_class':
                        row_item['face_status'] = 'reused_from_db'
                        row_item['face_message'] = f"Kế thừa khuôn mặt đã có từ lớp {row_item['existing_class']}"
                    else:
                        row_item['face_status'] = 'missing_photo'
                        row_item['face_message'] = 'Không có ảnh trong ô photo'

                parsed_rows.append(row_item)

        # Summary statistics
        total = len(parsed_rows)
        new_cnt = sum(1 for r in parsed_rows if r['db_status'] == 'new')
        already_cnt = sum(1 for r in parsed_rows if r['db_status'] == 'already_in_class')
        other_cnt = sum(1 for r in parsed_rows if r['db_status'] == 'exists_in_other_class')
        valid_face_cnt = sum(1 for r in parsed_rows if r['face_status'] in ('valid', 'reused_from_db'))
        missing_face_cnt = sum(1 for r in parsed_rows if r['face_status'] == 'missing_photo')
        error_cnt = sum(1 for r in parsed_rows if r['error'] or r['face_status'] in ('no_face', 'multiple_faces', 'multiple_photos_in_row'))
        distinct_classes = sorted(list(set(r['class_code'] for r in parsed_rows if r['class_code'])))

        summary = {
            'total_rows': total,
            'new_students': new_cnt,
            'already_in_class': already_cnt,
            'exists_in_other_class': other_cnt,
            'valid_face': valid_face_cnt,
            'missing_face': missing_face_cnt,
            'issues_count': error_cnt,
            'classes': distinct_classes,
        }

        # Cache preview session
        session_token = str(uuid.uuid4())
        self._sessions_cache[session_token] = {
            'created_at': time.time(),
            'rows': parsed_rows,
            'images': raw_image_cache,
            'summary': summary,
        }

        # Clean old sessions (> 30 min)
        now_ts = time.time()
        for tok in list(self._sessions_cache.keys()):
            if now_ts - self._sessions_cache[tok]['created_at'] > 1800:
                self._sessions_cache.pop(tok, None)

        return {
            'session_token': session_token,
            'summary': summary,
            'rows': parsed_rows,
        }

    # ------------------------------------------------------------- commit
    def commit(self, session_token: str, overrides: dict = None, default_conflict: str = 'skip', default_class: str = None) -> dict:
        """Execute batch enrollment based on confirmed preview rows."""
        sess = self._sessions_cache.get(session_token)
        if not sess:
            raise not_found('Phiên import đã hết hạn hoặc không tồn tại. Vui lòng tải lại file Excel.')

        overrides = overrides or {}
        rows = sess['rows']
        images = sess['images']

        created_count = 0
        updated_count = 0
        skipped_count = 0
        failed_count = 0
        details = []
        errors = []
        affected_classes = set()

        for r in rows:
            r_idx = r['row_index']
            sid = r['student_id']
            name = r['full_name']
            cls = r['class_code']
            if not cls and default_class:
                try:
                    cls = normalize_class(default_class)
                except Exception:
                    pass

            # Determine action: explicit override > row action
            action = overrides.get(str(r_idx), r['action'])

            if action == 'skip':
                skipped_count += 1
                details.append({'row': r_idx, 'student_id': sid, 'status': 'skipped', 'message': 'Người dùng chọn bỏ qua.'})
                continue

            if not cls:
                failed_count += 1
                errors.append(f"Dòng {r_idx} ({sid}): Chưa có mã lớp.")
                details.append({'row': r_idx, 'student_id': sid, 'status': 'failed', 'message': 'Chưa có mã lớp.'})
                continue

            if r['error'] and 'mã lớp' not in r['error'].lower():
                failed_count += 1
                errors.append(f"Dòng {r_idx} ({sid}): {r['error']}")
                details.append({'row': r_idx, 'student_id': sid, 'status': 'failed', 'message': r['error']})
                continue

            try:
                # 1. Ensure class exists
                try:
                    self.catalog.get_class(cls)
                except Exception:
                    self.catalog.create_class(cls, description='Tạo tự động từ import Excel')

                affected_classes.add(cls)
                img_data = images.get(r_idx)
                face_is_valid = (r['face_status'] == 'valid' and img_data is not None)

                if r.get('has_image') and not face_is_valid:
                    failed_count += 1
                    err_msg = r.get('error') or f"Ảnh không hợp lệ: {r.get('face_message', 'Khuôn mặt không đạt yêu cầu')}"
                    errors.append(f"Dòng {r_idx} ({sid}): {err_msg}")
                    details.append({'row': r_idx, 'student_id': sid, 'status': 'failed', 'message': err_msg})
                    continue

                # 2. Execute Action
                if action == 'create':
                    if r['db_status'] == 'already_in_class':
                        # If row was already in class but user forced create -> treat as update
                        action = 'update'

                if action == 'create':
                    if face_is_valid:
                        self.students.enroll(cls, sid, name, images=[img_data])
                        created_count += 1
                        details.append({
                            'row': r_idx, 'student_id': sid, 'status': 'created',
                            'message': f'Đã thêm vào lớp {cls} với khuôn mặt mới.'
                        })
                    else:
                        # Enroll without photo (or reuses face if exists in other class)
                        self.students.enroll(cls, sid, name, images=[])
                        created_count += 1
                        if r['db_status'] == 'exists_in_other_class':
                            details.append({
                                'row': r_idx, 'student_id': sid, 'status': 'created',
                                'message': f'Đã thêm vào lớp {cls} và tái sử dụng khuôn mặt từ lớp {r["existing_class"]}.'
                            })
                        else:
                            details.append({
                                'row': r_idx, 'student_id': sid, 'status': 'created',
                                'message': f'Đã thêm vào lớp {cls} (chưa có ảnh khuôn mặt).'
                            })

                elif action == 'update':
                    pk = r.get('existing_student_id')
                    if not pk:
                        with self.db.read() as conn:
                            found = conn.execute(
                                'SELECT id FROM students WHERE class_name=? AND active=1 AND UPPER(REPLACE(student_id, " ", "")) = ?',
                                (cls, sid.upper())
                            ).fetchone()
                            pk = found['id'] if found else None

                    if pk:
                        # Update full_name if changed
                        self.students.update(pk, full_name=name)
                        # Update face if new photo provided and valid
                        if face_is_valid:
                            self.students.update_face(pk, images=[img_data])
                            updated_count += 1
                            details.append({
                                'row': r_idx, 'student_id': sid, 'status': 'updated',
                                'message': f'Đã cập nhật thông tin và khuôn mặt mới cho {sid}.'
                            })
                        else:
                            updated_count += 1
                            details.append({
                                'row': r_idx, 'student_id': sid, 'status': 'updated',
                                'message': f'Đã cập nhật thông tin cho {sid}.'
                            })
                    else:
                        failed_count += 1
                        err_msg = f'Không tìm thấy sinh viên ID {sid} để cập nhật.'
                        errors.append(f'Dòng {r_idx}: {err_msg}')
                        details.append({'row': r_idx, 'student_id': sid, 'status': 'failed', 'message': err_msg})

            except Exception as exc:
                failed_count += 1
                errors.append(f'Dòng {r_idx} ({sid}): {exc}')
                details.append({'row': r_idx, 'student_id': sid, 'status': 'failed', 'message': str(exc)})

        # Invalidate recognition caches for all affected classes
        for c in affected_classes:
            self.models.invalidate(c)

        # Clear session from cache after commit
        self._sessions_cache.pop(session_token, None)

        return {
            'ok': True,
            'summary': {
                'total': len(rows),
                'created': created_count,
                'updated': updated_count,
                'skipped': skipped_count,
                'failed': failed_count,
            },
            'details': details,
            'errors': errors,
        }
