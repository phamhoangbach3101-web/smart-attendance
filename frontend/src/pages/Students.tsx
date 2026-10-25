import { useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { Camera, Download, FileSpreadsheet, History, Pencil, RefreshCw, Search, Trash2, UserPlus, Users } from 'lucide-react'
import { api, ApiError, type ClassItem, type Student } from '../api'
import { Badge, Button, Card, ConfirmDialog, EmptyState, ErrorBox, Field, Modal, Spinner, useToast } from '../components/ui'
import { fmtDate, fmtScore, fmtTime, useAsync } from '../lib'
import { SampleCapture, samplesForm, type Sample } from './Enroll'
import { BatchImportModal } from '../components/BatchImportModal'

const FACE: Record<Student['face_status'], { tone: 'green' | 'amber' | 'red'; text: string }> = {
  enrolled: { tone: 'green', text: 'Đã đăng ký' }, missing: { tone: 'amber', text: 'Chưa đăng ký' }, invalid: { tone: 'red', text: 'Mẫu lỗi' },
}

export default function Students() {
  const [params] = useSearchParams()
  const toast = useToast()
  const [cls, setCls] = useState(params.get('class') ?? '')
  const [q, setQ] = useState('')
  const [face, setFace] = useState('')
  const classes = useAsync(() => api.get<ClassItem[]>('/api/classes'))
  const list = useAsync(() => api.get<Student[]>(`/api/students${cls ? `?class_name=${encodeURIComponent(cls)}` : ''}`), [cls])
  const [edit, setEdit] = useState<Student | null>(null)
  const [del, setDel] = useState<Student | null>(null)
  const [hist, setHist] = useState<Student | null>(null)
  const [faceEdit, setFaceEdit] = useState<Student | null>(null)
  const [importModal, setImportModal] = useState(false)
  const [busy, setBusy] = useState(false)

  const downloadTemplate = async () => {
    try {
      const res = await fetch('/api/students/import/template')
      if (!res.ok) throw new Error('Không thể tải file mẫu')
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = 'Mau_Import_Sinh_Vien.xlsx'
      a.click()
      setTimeout(() => URL.revokeObjectURL(url), 2000)
      toast('success', 'Đã tải file mẫu Excel.')
    } catch (e) {
      toast('error', 'Lỗi tải file mẫu: ' + (e as Error).message)
    }
  }

  const rows = useMemo(() => {
    const n = q.trim().toLowerCase()
    return (list.data ?? []).filter((s) => (!face || s.face_status === face) && (!n || s.student_id.toLowerCase().includes(n) || s.full_name.toLowerCase().includes(n)))
  }, [list.data, q, face])

  const sync = async () => {
    try { const r = await api.post<{ changed_classes: string[] }>('/api/students/sync'); toast('success', r.changed_classes.length ? `Đã đồng bộ: ${r.changed_classes.join(', ')}` : 'Dữ liệu đã khớp với thư mục dataset'); list.reload(true) }
    catch (e) { toast('error', (e as ApiError).message) }
  }
  const doDelete = async () => {
    if (!del) return
    setBusy(true)
    try { await api.del(`/api/students/${del.id}`); toast('success', `Đã xóa ${del.full_name}. Lịch sử điểm danh vẫn được giữ.`); setDel(null); list.reload(true) }
    catch (e) { toast('error', (e as ApiError).message) } finally { setBusy(false) }
  }

  return (
    <div className="space-y-4">
      <Card className="p-4">
        <div className="flex flex-col gap-2 md:flex-row md:flex-wrap">
          <div className="relative min-w-[240px] flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted" />
            <input className="input pl-9" placeholder="Tìm theo mã hoặc họ tên…" value={q} onChange={(e) => setQ(e.target.value)} />
          </div>
          <select className="input md:w-44" value={cls} onChange={(e) => setCls(e.target.value)}>
            <option value="">Tất cả lớp</option>
            {classes.data?.map((c) => <option key={c.id} value={c.name}>{c.name}</option>)}
          </select>
          <select className="input md:w-44" value={face} onChange={(e) => setFace(e.target.value)}>
            <option value="">Mọi trạng thái</option><option value="enrolled">Đã đăng ký</option><option value="missing">Thiếu mẫu</option><option value="invalid">Mẫu lỗi</option>
          </select>
          <div className="flex flex-wrap gap-2">
            <Button variant="secondary" icon={<Download className="size-4" />} onClick={downloadTemplate} title="Tải file Excel mẫu (.xlsx)">Tải mẫu Excel</Button>
            <Button variant="secondary" icon={<FileSpreadsheet className="size-4 text-primary" />} onClick={() => setImportModal(true)} title="Import danh sách và khuôn mặt từ Excel">Import sinh viên từ Excel</Button>
            <Button variant="secondary" icon={<RefreshCw className="size-4" />} onClick={sync} title="Quét lại thư mục dataset (vd. sinh viên thêm từ app desktop)">Đồng bộ</Button>
            <Link to={`/students/enroll${cls ? `?class=${cls}` : ''}`}><Button icon={<UserPlus className="size-4" />}>Đăng ký</Button></Link>
          </div>
        </div>
      </Card>

      <Card className="overflow-hidden">
        {list.error ? <ErrorBox error={list.error} onRetry={() => list.reload()} className="m-4" /> : !list.data ? <Spinner /> : rows.length === 0 ? (
          <EmptyState icon={<Users className="size-7" />} title={list.data.length ? 'Không có kết quả phù hợp' : 'Chưa có sinh viên'}
            action={<Link to="/students/enroll"><Button icon={<UserPlus className="size-4" />}>Đăng ký khuôn mặt</Button></Link>}>
            {list.data.length ? 'Thử đổi từ khoá hoặc bộ lọc.' : 'Đăng ký khuôn mặt để sinh viên được nhận diện khi điểm danh.'}
          </EmptyState>
        ) : (<>
          {/* Desktop table */}
          <table className="hidden w-full text-sm md:table">
            <thead className="table-head"><tr><th className="px-4 py-3">Sinh viên</th><th className="px-4 py-3">Lớp</th><th className="px-4 py-3">Khuôn mặt</th><th className="px-4 py-3 text-right">Lượt điểm danh</th><th className="px-4 py-3 text-right">Thao tác</th></tr></thead>
            <tbody className="divide-y divide-line">
              {rows.map((s) => (
                <tr key={s.id} className="hover:bg-primary-light/30">
                  <td className="px-4 py-3"><div className="flex items-center gap-3"><Avatar s={s} /><div><p className="font-semibold">{s.full_name}</p><p className="font-mono text-xs text-muted">{s.student_id}</p></div></div></td>
                  <td className="px-4 py-3"><Badge tone="blue">{s.class_name}</Badge></td>
                  <td className="px-4 py-3"><Badge tone={FACE[s.face_status].tone} dot>{FACE[s.face_status].text}</Badge><span className="ml-2 text-xs text-muted">{s.embedding_count} mẫu</span></td>
                  <td className="px-4 py-3 text-right font-semibold">{s.attendance_count ?? 0}</td>
                  <td className="px-4 py-3"><RowActions compact s={s} onHist={setHist} onEdit={setEdit} onFace={setFaceEdit} onDel={setDel} /></td>
                </tr>
              ))}
            </tbody>
          </table>
          {/* Mobile cards */}
          <ul className="divide-y divide-line md:hidden">
            {rows.map((s) => (
              <li key={s.id} className="p-4">
                <div className="flex items-center gap-3"><Avatar s={s} /><div className="min-w-0 flex-1"><p className="truncate font-semibold">{s.full_name}</p><p className="font-mono text-xs text-muted">{s.student_id} · {s.class_name}</p></div><Badge tone={FACE[s.face_status].tone}>{FACE[s.face_status].text}</Badge></div>
                <div className="mt-3"><RowActions s={s} onHist={setHist} onEdit={setEdit} onFace={setFaceEdit} onDel={setDel} /></div>
              </li>
            ))}
          </ul>
          <p className="border-t border-line px-4 py-3 text-xs text-muted">{rows.length} / {list.data.length} sinh viên</p>
        </>)}
      </Card>

      {edit && <EditStudent s={edit} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); list.reload(true) }} />}
      {hist && <StudentHistory s={hist} onClose={() => setHist(null)} />}
      {faceEdit && <UpdateFace s={faceEdit} onClose={() => setFaceEdit(null)} onSaved={() => { setFaceEdit(null); list.reload(true) }} />}
      <ConfirmDialog open={!!del} danger loading={busy} confirmLabel="Xóa sinh viên" onClose={() => setDel(null)} onConfirm={doDelete}
        title={`Xóa ${del?.full_name}?`}
        message={<>Sinh viên sẽ không còn được nhận diện. Ảnh và embeddings được chuyển vào thư mục <code>.deleted</code> của lớp (có thể khôi phục thủ công); <b>{del?.attendance_count ?? 0} lượt điểm danh cũ vẫn được giữ</b>.</>} />
      <BatchImportModal open={importModal} onClose={() => setImportModal(false)} onSuccess={() => { setImportModal(false); list.reload(true); classes.reload(true) }} currentClass={cls} />
    </div>
  )
}

function Avatar({ s }: { s: Student }) {
  return s.photos[0]
    ? <img src={`/api/students/${s.id}/photos/${encodeURIComponent(s.photos[0])}`} alt="" className="size-10 shrink-0 rounded-full object-cover ring-2 ring-primary-light" loading="lazy" />
    : <span className="grid size-10 shrink-0 place-items-center rounded-full bg-primary-light font-bold text-primary-dark">{s.full_name.split(' ').pop()?.[0]}</span>
}

function RowActions({ s, compact, onHist, onEdit, onFace, onDel }: { s: Student; compact?: boolean; onHist: (s: Student) => void; onEdit: (s: Student) => void; onFace: (s: Student) => void; onDel: (s: Student) => void }) {
  const isEnrolled = s.face_status === 'enrolled'
  const items = [
    { label: 'Lịch sử', icon: History, fn: onHist },
    { label: 'Sửa', icon: Pencil, fn: onEdit },
    {
      label: isEnrolled ? 'Cập nhật khuôn mặt' : 'Đăng ký khuôn mặt',
      short: isEnrolled ? 'Mẫu mặt' : 'Đăng ký mặt',
      icon: isEnrolled ? Camera : UserPlus,
      fn: onFace,
      highlight: !isEnrolled,
    },
    { label: 'Xóa', icon: Trash2, fn: onDel, danger: true },
  ]
  return (
    <div className={compact ? 'flex items-center justify-end gap-1' : 'grid grid-cols-4 gap-1'}>
      {items.map(({ label, short, icon: Icon, fn, danger, highlight }: any) => (
        <Button key={label} size="sm" variant={highlight ? 'primary' : 'ghost'} title={label} aria-label={label} onClick={() => fn(s)}
          className={(danger ? 'hover:!bg-danger-light hover:!text-red-700 ' : '') + (highlight ? '!px-3 text-xs font-bold ' : '') + (compact ? (highlight ? '!px-2.5' : '!px-2') : 'flex-col !h-auto py-2 text-xs')}
          icon={<Icon className="size-4" />}>{compact ? (highlight ? short : null) : short ?? label}</Button>
      ))}
    </div>
  )
}

function EditStudent({ s, onClose, onSaved }: { s: Student; onClose: () => void; onSaved: () => void }) {
  const toast = useToast()
  const [sid, setSid] = useState(s.student_id)
  const [name, setName] = useState(s.full_name)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const submit = async (e: React.FormEvent) => {
    e.preventDefault(); setBusy(true); setErr(null)
    try { await api.patch(`/api/students/${s.id}`, { student_id: sid, full_name: name }); toast('success', 'Đã cập nhật sinh viên'); onSaved() }
    catch (e) { setErr((e as ApiError).message) } finally { setBusy(false) }
  }
  return (
    <Modal open onClose={onClose} title="Sửa thông tin sinh viên" size="sm">
      <form onSubmit={submit} className="space-y-4">
        <Field label="Lớp" hint="Chỉ lịch sử điểm danh của lớp này được cập nhật theo."><input className="input" value={s.class_name} disabled /></Field>
        <Field label="Mã sinh viên"><input className="input font-mono" value={sid} onChange={(e) => setSid(e.target.value)} maxLength={32} /></Field>
        <Field label="Họ và tên"><input className="input" value={name} onChange={(e) => setName(e.target.value)} maxLength={80} /></Field>
        {err && <ErrorBox error={err} />}
        <div className="flex justify-end gap-2"><Button type="button" variant="secondary" onClick={onClose}>Hủy</Button><Button type="submit" loading={busy} disabled={!sid.trim() || !name.trim()}>Lưu</Button></div>
      </form>
    </Modal>
  )
}

function StudentHistory({ s, onClose }: { s: Student; onClose: () => void }) {
  const h = useAsync(() => api.get<any>(`/api/students/${s.id}/history`), [s.id])
  return (
    <Modal open onClose={onClose} title={`Lịch sử điểm danh — ${s.full_name}`} size="lg">
      {h.error ? <ErrorBox error={h.error} /> : !h.data ? <Spinner /> : (
        <div className="space-y-4">
          <div className="flex flex-wrap gap-2"><Badge tone="blue">{s.class_name}</Badge><Badge tone="green">{h.data.present} có mặt</Badge><Badge tone="red">{h.data.absent} vắng</Badge></div>
          {h.data.history.length === 0 ? <p className="py-6 text-center text-sm text-muted">Chưa có phiên nào.</p> : (
            <div className="overflow-x-auto rounded-2xl border border-line">
              <table className="w-full min-w-[480px] text-sm">
                <thead className="table-head"><tr><th className="px-3 py-2.5">Ngày</th><th className="px-3 py-2.5">Môn</th><th className="px-3 py-2.5">Slot</th><th className="px-3 py-2.5">Trạng thái</th><th className="px-3 py-2.5">Giờ</th><th className="px-3 py-2.5">Điểm tương đồng</th></tr></thead>
                <tbody className="divide-y divide-line">
                  {h.data.history.map((r: any) => (
                    <tr key={r.session_id}><td className="px-3 py-2.5">{fmtDate(r.date)}</td><td className="px-3 py-2.5">{r.subject}</td><td className="px-3 py-2.5">{r.slot}</td>
                      <td className="px-3 py-2.5"><Badge tone={r.status === 'present' ? 'green' : r.status === 'absent' ? 'red' : 'gray'}>{r.status === 'present' ? 'Có mặt' : r.status === 'absent' ? 'Vắng' : 'Không rõ'}</Badge></td>
                      <td className="px-3 py-2.5">{fmtTime(r.timestamp)}</td><td className="px-3 py-2.5">{fmtScore(r.confidence)}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </Modal>
  )
}

function UpdateFace({ s, onClose, onSaved }: { s: Student; onClose: () => void; onSaved: () => void }) {
  const toast = useToast()
  const [samples, setSamples] = useState<Sample[]>([])
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const isEnrolled = s.face_status === 'enrolled'
  const ok = samples.length > 0 && samples.every((x) => x.check?.ok)
  const save = async () => {
    setBusy(true); setErr(null)
    try {
      await api.form(`/api/students/${s.id}/face`, samplesForm(samples))
      toast('success', isEnrolled ? 'Đã cập nhật mẫu khuôn mặt (mẫu cũ lưu trong .previous)' : 'Đã đăng ký khuôn mặt thành công!')
      onSaved()
    }
    catch (e) { setErr((e as ApiError).message) } finally { setBusy(false) }
  }
  return (
    <Modal open onClose={onClose}
      title={isEnrolled ? `Cập nhật mẫu khuôn mặt — ${s.full_name}` : `Đăng ký khuôn mặt — ${s.full_name} (${s.student_id})`}
      size="lg"
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>Hủy</Button>
          <Button loading={busy} disabled={!ok} onClick={save}>
            {isEnrolled ? 'Thay mẫu khuôn mặt' : 'Xác nhận đăng ký khuôn mặt'}
          </Button>
        </>
      }>
      <SampleCapture samples={samples} setSamples={setSamples} />
      {err && <ErrorBox error={err} className="mt-3" />}
    </Modal>
  )
}
