"""Dashboard numbers, history queries and Excel export, all computed from SQLite.

Absences are always counted against a session's roster (students of the class
when the session was opened, plus anyone who checked in). Legacy desktop
sessions have no stored roster, so their absences are reported as unknown
instead of being guessed from today's student list.
"""
import io
import os
import threading
from datetime import date as date_cls, timedelta

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from backend import clock
from backend.errors import invalid
from backend.services.sessions import session_state

_sheet_lock = threading.Lock()

STATUS_VI = {'present': 'Có mặt', 'absent': 'Vắng', 'unknown': 'Không rõ (dữ liệu cũ)'}


def _parse_date(value, label):
    if not value:
        return None
    try:
        return date_cls.fromisoformat(value).isoformat()
    except ValueError:
        raise invalid(f'{label} không đúng định dạng YYYY-MM-DD.')


class ReportService:
    def __init__(self, db, paths, sessions):
        self.db = db
        self.paths = paths
        self.sessions = sessions

    # ----------------------------------------------------------------- history
    def _session_filter(self, f):
        sql, params = ' WHERE 1=1', []
        d_from = _parse_date(f.get('date_from'), 'Từ ngày')
        d_to = _parse_date(f.get('date_to'), 'Đến ngày')
        if d_from and d_to and d_from > d_to:
            raise invalid('"Từ ngày" phải trước "Đến ngày".')
        for clause, val in ((' AND s.date>=?', d_from), (' AND s.date<=?', d_to),
                            (' AND s.class_name=?', (f.get('class_name') or '').strip().upper() or None),
                            (' AND s.subject=?', (f.get('subject') or '').strip().upper() or None),
                            (' AND s.slot=?', f.get('slot'))):
            if val not in (None, ''):
                sql += clause
                params.append(val)
        return sql, params

    def history(self, filters):
        where, params = self._session_filter(filters)
        with self.db.read() as conn:
            sessions = [dict(r) for r in conn.execute(
                'SELECT s.* FROM sessions s' + where + ' ORDER BY s.date DESC, s.slot DESC, s.class_name, s.subject',
                params)]
            ids = [s['id'] for s in sessions]
            rows = []
            if ids:
                marks = ','.join('?' * len(ids))
                rows = conn.execute(
                    'SELECT r.session_id, r.student_id, r.student_name, a.timestamp, a.confidence '
                    'FROM session_roster r LEFT JOIN attendance a '
                    'ON a.session_id=r.session_id AND a.student_id=r.student_id '
                    f'WHERE r.session_id IN ({marks}) '
                    'UNION ALL '
                    'SELECT a.session_id, a.student_id, a.student_name, a.timestamp, a.confidence '
                    f'FROM attendance a WHERE a.session_id IN ({marks}) AND NOT EXISTS ('
                    'SELECT 1 FROM session_roster r WHERE r.session_id=a.session_id AND r.student_id=a.student_id)',
                    ids + ids).fetchall()
        by_id = {s['id']: s for s in sessions}
        now = clock.now()
        for s in sessions:
            s.update(present=0, absent=0, roster=0)
            s['state'] = session_state(s, now)
        records = []
        q = (filters.get('q') or '').strip().casefold()
        status_filter = filters.get('status') or None
        for r in rows:
            s = by_id[r['session_id']]
            status = 'present' if r['timestamp'] else ('absent' if s['roster_known'] else 'unknown')
            s['roster'] += 1
            s['present'] += status == 'present'
            s['absent'] += status == 'absent'
            rec = {'session_id': s['id'], 'date': s['date'], 'class_name': s['class_name'],
                   'subject': s['subject'], 'slot': s['slot'], 'student_id': r['student_id'],
                   'student_name': r['student_name'], 'status': status, 'timestamp': r['timestamp'],
                   'score': r['confidence']}
            if q and q not in rec['student_id'].casefold() and q not in rec['student_name'].casefold():
                continue
            if status_filter and status != status_filter:
                continue
            records.append(rec)
        records.sort(key=lambda r: (r['date'], r['slot'], r['class_name'], r['subject'],
                                    r['status'] != 'present', r['student_id']))
        records.sort(key=lambda r: r['date'], reverse=True)
        for s in sessions:
            if not s['roster_known']:
                s['absent'] = None
        known = [s for s in sessions if s['roster_known']]
        summary = {
            'sessions': len(sessions),
            'present': sum(s['present'] for s in sessions),
            'absent': sum(s['absent'] for s in known),
            'roster': sum(s['roster'] for s in known),
            'legacy_sessions': len(sessions) - len(known),
            'records': len(records),
        }
        denom = summary['roster']
        summary['rate'] = round(sum(s['present'] for s in known) / denom, 4) if denom else None
        return {'sessions': sessions, 'records': records, 'summary': summary}

    # --------------------------------------------------------------- dashboard
    def dashboard(self, day=None):
        day = _parse_date(day, 'Ngày') or clock.now().date().isoformat()
        d = date_cls.fromisoformat(day)
        week_start = d - timedelta(days=d.weekday())
        week = [(week_start + timedelta(days=i)).isoformat() for i in range(7)]
        with self.db.read() as conn:
            totals = {
                'students': conn.execute('SELECT COUNT(*) FROM students WHERE active=1').fetchone()[0],
                'classes': conn.execute('SELECT COUNT(*) FROM classes').fetchone()[0],
                'courses': conn.execute('SELECT COUNT(*) FROM courses').fetchone()[0],
            }
            per_day = {r['date']: dict(r) for r in conn.execute(
                'SELECT s.date, COUNT(DISTINCT s.id) AS sessions, '
                '(SELECT COUNT(*) FROM attendance a WHERE a.date=s.date) AS checkins '
                'FROM sessions s WHERE s.date BETWEEN ? AND ? GROUP BY s.date', (week[0], week[-1]))}
            recent = [dict(r) for r in conn.execute(
                'SELECT a.id, a.student_id, a.student_name, a.class_name, a.subject, a.slot, a.timestamp, '
                'a.confidence, a.session_id FROM attendance a ORDER BY a.timestamp DESC, a.id DESC LIMIT 8')]
        hist = self.history({'date_from': day, 'date_to': day})
        active = [s for s in self.sessions.list(state='active', limit=50)]
        return {
            'date': day,
            'totals': totals,
            'day': {**hist['summary'], 'checkins': hist['summary']['present']},
            'day_sessions': hist['sessions'],
            'week': [{'date': w, 'sessions': per_day.get(w, {}).get('sessions', 0),
                      'checkins': per_day.get(w, {}).get('checkins', 0)} for w in week],
            'recent': recent,
            'active_sessions': active,
        }

    # ------------------------------------------------------------------ export
    def export_xlsx(self, filters):
        data = self.history(filters)
        wb = Workbook()
        head_font = Font(bold=True, color='FFFFFF')
        head_fill = PatternFill('solid', fgColor='16C784')

        ws = wb.active
        ws.title = 'Tổng hợp'
        scope = ', '.join(f'{k}={v}' for k, v in filters.items() if v not in (None, '')) or 'toàn bộ'
        ws.append(['Báo cáo điểm danh — Smart Attendance'])
        ws.append([f'Phạm vi lọc: {scope}'])
        ws.append([f'Xuất lúc: {clock.ts()} (nguồn: SQLite)'])
        ws.append([])
        header = ['Mã phiên', 'Ngày', 'Lớp', 'Môn', 'Slot', 'Bắt đầu', 'Kết thúc', 'Sĩ số phiên',
                  'Có mặt', 'Vắng', 'Ghi chú']
        ws.append(header)
        for s in data['sessions']:
            ws.append([s['id'], s['date'], s['class_name'], s['subject'], s['slot'], s['started_at'],
                       s['ended_at'] or '', s['roster'] if s['roster_known'] else '', s['present'],
                       s['absent'] if s['absent'] is not None else '',
                       'Dữ liệu cũ: không có danh sách lớp' if not s['roster_known'] else ''])
        self._style(ws, 5, len(header), head_font, head_fill)
        ws['A1'].font = Font(bold=True, size=14)

        ws2 = wb.create_sheet('Chi tiết')
        header2 = ['Mã phiên', 'Ngày', 'Lớp', 'Môn', 'Slot', 'Mã SV', 'Họ tên', 'Trạng thái',
                   'Giờ điểm danh', 'Điểm tương đồng']
        ws2.append(header2)
        for r in data['records']:
            ws2.append([r['session_id'], r['date'], r['class_name'], r['subject'], r['slot'],
                        r['student_id'], r['student_name'], STATUS_VI[r['status']],
                        r['timestamp'] or '', round(r['score'], 4) if r['score'] is not None else ''])
        self._style(ws2, 1, len(header2), head_font, head_fill)
        ws2.column_dimensions['F'].number_format = '@'
        for row in ws2.iter_rows(min_row=2, min_col=6, max_col=6):
            for cell in row:
                cell.number_format = '@'   # keep leading zeros in student IDs

        buf = io.BytesIO()
        wb.save(buf)
        content = buf.getvalue()
        name = f"diem_danh_{clock.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        try:
            with open(os.path.join(self.paths.exports_dir, name), 'wb') as f:
                f.write(content)
        except OSError as exc:
            print(f'[WARNING] cannot keep export copy: {exc}')
        return name, content, data['summary']

    @staticmethod
    def _style(ws, header_row, ncols, font, fill):
        for col in range(1, ncols + 1):
            cell = ws.cell(row=header_row, column=col)
            cell.font, cell.fill = font, fill
            cell.alignment = Alignment(horizontal='center', vertical='center')
            width = max(len(str(c.value or '')) for c in ws[get_column_letter(col)])
            ws.column_dimensions[get_column_letter(col)].width = min(max(12, width + 2), 40)
        ws.freeze_panes = ws.cell(row=header_row + 1, column=1)

    # ------------------------------------------------- desktop master sheet
    def sync_class_sheet(self, session):
        """Write this session's column into dataset/<CLASS>/attendance.xlsx from SQLite.

        Same layout as the desktop app (one row per student, one column per
        class/subject/slot/date), so both apps keep producing the same file.
        """
        cdir = self.paths.class_dir(session['class_name'])
        if not os.path.isdir(cdir):
            return None
        path = os.path.join(cdir, 'attendance.xlsx')
        d = date_cls.fromisoformat(session['date'])
        col = f"{session['class_name']} - {session['subject']} - Slot {session['slot']} - {d.strftime('%d/%m/%Y')}"
        records = self.sessions.records(session['id'])['records']
        with _sheet_lock:
            if os.path.exists(path):
                wb = load_workbook(path)
                ws = wb.active
            else:
                wb = Workbook()
                ws = wb.active
                ws.append(['Student ID', 'Student Name'])
            headers = [c.value for c in ws[1]]
            if 'Student ID' not in headers:
                return None
            id_col = headers.index('Student ID') + 1
            if col in headers:
                target = headers.index(col) + 1
            else:
                target = len(headers) + 1
                ws.cell(row=1, column=target, value=col)
            row_of = {str(ws.cell(row=r, column=id_col).value): r for r in range(2, ws.max_row + 1)}
            for rec in records:
                if str(rec['student_id']) not in row_of:
                    r = ws.max_row + 1
                    ws.cell(row=r, column=id_col, value=rec['student_id'])
                    ws.cell(row=r, column=id_col + 1, value=rec['student_name'])
                    row_of[str(rec['student_id'])] = r
            present = {r['student_id']: r['timestamp'] for r in records if r['timestamp']}
            for sid, r in row_of.items():
                ts = present.get(sid)
                ws.cell(row=r, column=target,
                        value=f'Present ({ts.split(" ")[1]})' if ts else 'X (Absent)')
            tmp = path + '.tmp.xlsx'
            wb.save(tmp)
            os.replace(tmp, path)
        return path
