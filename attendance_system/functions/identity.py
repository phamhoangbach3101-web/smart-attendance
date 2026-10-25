"""Single place that normalises class names, subjects, student IDs and names.

The enrolment folder of a student is ``{CLASS}_{ID}_{Name_With_Underscores}``
and is parsed back with ``split('_', 2)``, so class names and IDs must never
contain an underscore, and every writer (desktop UI, web backend, Excel export)
has to use the same normalised values. All of them go through this module.
"""
import re
import unicodedata

_PATH_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_WINDOWS_RESERVED = {'CON', 'PRN', 'AUX', 'NUL',
                     *(f'COM{i}' for i in range(1, 10)),
                     *(f'LPT{i}' for i in range(1, 10))}
_ID_RE = re.compile(r'^[0-9A-Z][0-9A-Z.\-]{0,31}$')
MAX_CODE_LEN = 32
MAX_NAME_LEN = 80


class IdentityError(ValueError):
    """Raised with a Vietnamese message suitable for the UI."""


def _nfc(value):
    return unicodedata.normalize('NFC', str(value if value is not None else ''))


def _collapse(value):
    return re.sub(r'\s+', ' ', _nfc(value)).strip()


def normalize_code(value, label='Mã'):
    """Class name or subject code: trimmed, upper-case, letters/digits/-/. only."""
    code = _collapse(value).upper()
    if not code:
        raise IdentityError(f'{label} không được để trống.')
    if len(code) > MAX_CODE_LEN:
        raise IdentityError(f'{label} tối đa {MAX_CODE_LEN} ký tự.')
    if code in {'.', '..'} or code.startswith('.') or code.endswith('.'):
        raise IdentityError(f'{label} không được bắt đầu hoặc kết thúc bằng dấu chấm.')
    if code in _WINDOWS_RESERVED:
        raise IdentityError(f'{label} "{code}" là tên dành riêng của Windows.')
    for ch in code:
        if not (ch.isalnum() or ch in '-.'):
            raise IdentityError(
                f'{label} chỉ gồm chữ, số, dấu gạch ngang (-) hoặc dấu chấm (.); '
                f'không dùng khoảng trắng, "_" hay ký tự "{ch}".')
    return code


def normalize_class(value):
    return normalize_code(value, 'Tên lớp')


def normalize_subject(value):
    return normalize_code(value, 'Mã môn')


def normalize_student_id(value):
    """Upper-case ASCII ID; leading zeros are kept (IDs are strings)."""
    sid = _collapse(value).upper().replace(' ', '')
    if not sid:
        raise IdentityError('Mã sinh viên không được để trống.')
    if not _ID_RE.match(sid):
        raise IdentityError('Mã sinh viên chỉ gồm chữ không dấu, số, "-" hoặc "." '
                            f'(tối đa {MAX_CODE_LEN} ký tự).')
    return sid


def normalize_name(value):
    """Full name with single spaces; Vietnamese diacritics kept in NFC form."""
    name = _collapse(value)
    if not name:
        raise IdentityError('Họ tên không được để trống.')
    if len(name) > MAX_NAME_LEN:
        raise IdentityError(f'Họ tên tối đa {MAX_NAME_LEN} ký tự.')
    if '_' in name or _PATH_CHARS.search(name):
        raise IdentityError('Họ tên không được chứa ký tự _ \\ / : * ? " < > |')
    return name


def student_folder(class_name, student_id, name):
    """Folder name for already-normalised values."""
    return f'{class_name}_{student_id}_{name.replace(" ", "_")}'


def parse_student_folder(folder):
    parts = folder.split('_', 2)
    return {
        'class': parts[0] if len(parts) > 0 else 'Unknown',
        'id': parts[1] if len(parts) > 1 else folder,
        'name': unicodedata.normalize('NFC', parts[2].replace('_', ' ')) if len(parts) > 2 else '',
    }
