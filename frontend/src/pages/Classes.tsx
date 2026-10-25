import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { BookOpen, Camera, GraduationCap, Pencil, Plus, Search, Trash2, Users } from 'lucide-react'
import { api, ApiError, type ClassItem, type Course } from '../api'
import { Badge, Button, Card, CardHeader, ConfirmDialog, EmptyState, ErrorBox, Field, Modal, Spinner, useToast } from '../components/ui'
import { cx, fmtDate, useAsync } from '../lib'

const CODE_HINT = 'Chữ, số, dấu "-" hoặc "."; không khoảng trắng hay "_". Tự chuyển thành chữ in hoa.'

export default function Classes() {
  const toast = useToast()
  const nav = useNavigate()
  const classes = useAsync(() => api.get<ClassItem[]>('/api/classes'))
  const courses = useAsync(() => api.get<Course[]>('/api/courses'))
  const [q, setQ] = useState('')
  const [classFilter, setClassFilter] = useState('')
  const [classModal, setClassModal] = useState<{ edit?: ClassItem } | null>(null)
  const [courseModal, setCourseModal] = useState<{ edit?: Course; className?: string } | null>(null)
  const [confirm, setConfirm] = useState<{ kind: 'class' | 'course'; item: any } | null>(null)
  const [busy, setBusy] = useState(false)

  const reloadAll = () => { classes.reload(true); courses.reload(true) }
  const filteredCourses = useMemo(() => {
    const n = q.trim().toLowerCase()
    return (courses.data ?? []).filter((c) => (!classFilter || c.class_name === classFilter) &&
      (!n || `${c.class_name} ${c.subject} ${c.subject_name}`.toLowerCase().includes(n)))
  }, [courses.data, q, classFilter])

  const doDelete = async () => {
    if (!confirm || busy) return
    setBusy(true)
    try {
      if (confirm.kind === 'class') {
        const res = await api.del<{ message?: string }>(`/api/classes/${confirm.item.id}`)
        toast('success', res.message || 'Đã xóa lớp và xử lý danh sách sinh viên liên quan thành công')
      } else {
        await api.del(`/api/courses/${confirm.item.id}`)
        toast('success', `Đã xóa cấu hình ${confirm.item.class_name} – ${confirm.item.subject}. Lịch sử điểm danh vẫn được giữ.`)
      }
      setConfirm(null)
      reloadAll()
    } catch (e) {
      toast('error', (e as ApiError).message)
    } finally { setBusy(false) }
  }

  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.6fr)]">
      <Card className="self-start">
        <CardHeader title="Lớp học" subtitle="Mỗi lớp có thư mục dữ liệu khuôn mặt riêng" icon={<GraduationCap className="size-5" />}
          action={<Button size="sm" icon={<Plus className="size-4" />} onClick={() => setClassModal({})}>Tạo lớp</Button>} />
        <div className="p-3 sm:p-4">
          {classes.error ? <ErrorBox error={classes.error} onRetry={() => classes.reload()} /> : classes.loading && !classes.data ? <Spinner /> :
            classes.data!.length === 0 ? (
              <EmptyState icon={<GraduationCap className="size-7" />} title="Chưa có lớp nào" action={<Button icon={<Plus className="size-4" />} onClick={() => setClassModal({})}>Tạo lớp đầu tiên</Button>}>
                Tạo lớp (VD: SE1501) rồi thêm môn học và đăng ký khuôn mặt sinh viên.
              </EmptyState>) : (
              <ul className="space-y-2">
                {classes.data!.map((c) => (
                  <li key={c.id} className={cx('flex items-center gap-3 rounded-2xl border p-3 transition', classFilter === c.name ? 'border-primary bg-primary-light/50' : 'border-line hover:border-primary/40')}>
                    <button className="flex min-w-0 flex-1 items-center gap-3 text-left" onClick={() => setClassFilter(classFilter === c.name ? '' : c.name)}>
                      <span className="grid size-11 shrink-0 place-items-center rounded-xl bg-primary-light font-bold text-primary-dark">{c.name.slice(0, 2)}</span>
                      <span className="min-w-0">
                        <span className="block truncate font-semibold">{c.name}</span>
                        <span className="block truncate text-xs text-muted">{c.description || 'Không có mô tả'}</span>
                        <span className="mt-1 flex flex-wrap gap-1.5">
                          <Badge tone="green"><Users className="size-3" /> {c.student_count} SV</Badge>
                          <Badge tone="blue"><BookOpen className="size-3" /> {c.course_count} môn</Badge>
                        </span>
                      </span>
                    </button>
                    <div className="flex shrink-0 items-center gap-1">
                      <Button size="sm" variant="ghost" title="Danh sách sinh viên & khuôn mặt" aria-label="Sinh viên" onClick={() => nav(`/students?class=${encodeURIComponent(c.name)}`)}><Users className="size-4 text-primary" /></Button>
                      <Button size="sm" variant="ghost" title="Điểm danh lớp này" aria-label="Điểm danh" onClick={() => nav(`/attendance?class=${encodeURIComponent(c.name)}`)}><Camera className="size-4 text-primary" /></Button>
                      <Button size="sm" variant="ghost" aria-label="Sửa" onClick={() => setClassModal({ edit: c })}><Pencil className="size-4" /></Button>
                      <Button size="sm" variant="ghost" aria-label="Xóa" className="hover:!bg-danger-light hover:!text-red-700" onClick={() => setConfirm({ kind: 'class', item: c })}><Trash2 className="size-4" /></Button>
                    </div>
                  </li>
                ))}
              </ul>)}
        </div>
      </Card>

      <Card className="self-start">
        <CardHeader title="Lớp & Môn học" subtitle="Cấu hình dùng để mở phiên điểm danh" icon={<BookOpen className="size-5" />}
          action={<Button size="sm" icon={<Plus className="size-4" />} disabled={!classes.data?.length} onClick={() => setCourseModal({ className: classFilter })}>Thêm môn</Button>} />
        <div className="flex flex-col gap-2 px-5 pt-4 sm:flex-row">
          <div className="relative flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted" />
            <input className="input pl-9" placeholder="Tìm lớp, mã môn, tên môn…" value={q} onChange={(e) => setQ(e.target.value)} />
          </div>
          <select className="input sm:w-48" value={classFilter} onChange={(e) => setClassFilter(e.target.value)}>
            <option value="">Tất cả lớp</option>
            {classes.data?.map((c) => <option key={c.id} value={c.name}>{c.name}</option>)}
          </select>
        </div>
        <div className="p-3 sm:p-4">
          {courses.error ? <ErrorBox error={courses.error} onRetry={() => courses.reload()} /> : courses.loading && !courses.data ? <Spinner /> :
            filteredCourses.length === 0 ? (
              <EmptyState icon={<BookOpen className="size-7" />} title={courses.data?.length ? 'Không có kết quả phù hợp' : 'Chưa có môn học'}
                action={classes.data?.length ? <Button icon={<Plus className="size-4" />} onClick={() => setCourseModal({ className: classFilter })}>Thêm môn học</Button> : undefined}>
                {classes.data?.length ? 'Thêm môn (VD: CPV301) cho lớp để bắt đầu điểm danh.' : 'Hãy tạo lớp trước.'}
              </EmptyState>) : (
              <div className="grid gap-3 sm:grid-cols-2">
                {filteredCourses.map((c) => (
                  <div key={c.id} className="rounded-2xl border border-line p-4 transition hover:border-primary/40 hover:shadow-card">
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <p className="text-xs font-semibold uppercase tracking-wide text-primary">{c.class_name}</p>
                        <p className="truncate text-lg font-bold">{c.subject}</p>
                        <p className="truncate text-sm text-muted">{c.subject_name || '—'}</p>
                      </div>
                      <div className="flex shrink-0">
                        <Button size="sm" variant="ghost" aria-label="Sửa" onClick={() => setCourseModal({ edit: c })}><Pencil className="size-4" /></Button>
                        <Button size="sm" variant="ghost" aria-label="Xóa" className="hover:!bg-danger-light hover:!text-red-700" onClick={() => setConfirm({ kind: 'course', item: c })}><Trash2 className="size-4" /></Button>
                      </div>
                    </div>
                    <div className="mt-3 flex flex-wrap gap-1.5 text-xs">
                      <Badge>{c.student_count} sinh viên</Badge>
                      <Badge>{c.session_count} phiên</Badge>
                      {c.last_session_date && <Badge tone="blue">Gần nhất {fmtDate(c.last_session_date)}</Badge>}
                    </div>
                    <Button className="mt-4 w-full" size="sm" icon={<Camera className="size-4" />}
                      onClick={() => nav(`/attendance?class=${encodeURIComponent(c.class_name)}&subject=${encodeURIComponent(c.subject)}`)}>Điểm danh</Button>
                  </div>
                ))}
              </div>)}
        </div>
      </Card>

      {classModal && <ClassForm edit={classModal.edit} onClose={() => setClassModal(null)} onSaved={() => { setClassModal(null); reloadAll() }} />}
      {courseModal && <CourseForm edit={courseModal.edit} classes={classes.data ?? []} defaultClass={courseModal.className}
        onClose={() => setCourseModal(null)} onSaved={() => { setCourseModal(null); reloadAll() }} />}
      <ConfirmDialog
        open={!!confirm}
        danger
        loading={busy}
        onClose={() => setConfirm(null)}
        onConfirm={doDelete}
        confirmLabel={confirm?.kind === 'class' ? 'Xóa lớp' : 'Xóa'}
        title={confirm?.kind === 'class' ? `Xóa lớp ${confirm?.item.name}?` : `Xóa ${confirm?.item.class_name} – ${confirm?.item.subject}?`}
        message={confirm?.kind === 'class'
          ? 'Bạn có chắc chắn muốn xóa lớp này không? Danh sách sinh viên chỉ thuộc lớp này và các cấu hình liên quan sẽ bị xóa. Thao tác này không thể hoàn tác. Lịch sử điểm danh sẽ được giữ lại nếu có thể bảo toàn an toàn.'
          : <>Chỉ xóa cấu hình lớp/môn. <b>{confirm?.item.session_count ?? 0} phiên và toàn bộ lịch sử điểm danh vẫn được giữ</b> trong báo cáo.</>}
      />
    </div>
  )
}

function ClassForm({ edit, onClose, onSaved }: { edit?: ClassItem; onClose: () => void; onSaved: () => void }) {
  const toast = useToast()
  const [name, setName] = useState(edit?.name ?? '')
  const [desc, setDesc] = useState(edit?.description ?? '')
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true); setErr(null)
    try {
      if (edit) await api.patch(`/api/classes/${edit.id}`, { description: desc })
      else await api.post('/api/classes', { name, description: desc })
      toast('success', edit ? 'Đã lưu lớp' : `Đã tạo lớp ${name.trim().toUpperCase()}`)
      onSaved()
    } catch (e) { setErr((e as ApiError).message) } finally { setBusy(false) }
  }
  return (
    <Modal open onClose={onClose} title={edit ? `Sửa lớp ${edit.name}` : 'Tạo lớp mới'} size="sm">
      <form onSubmit={submit} className="space-y-4">
        <Field label="Tên lớp" hint={edit ? 'Không đổi được tên lớp vì đã gắn với thư mục dữ liệu và lịch sử.' : CODE_HINT}>
          <input className="input uppercase" value={name} onChange={(e) => setName(e.target.value)} disabled={!!edit} placeholder="VD: SE1501" autoFocus maxLength={32} />
        </Field>
        <Field label="Mô tả (tuỳ chọn)"><input className="input" value={desc} onChange={(e) => setDesc(e.target.value)} placeholder="VD: Kỳ Fall 2026" maxLength={200} /></Field>
        {err && <ErrorBox error={err} />}
        <div className="flex justify-end gap-2"><Button type="button" variant="secondary" onClick={onClose}>Hủy</Button><Button type="submit" loading={busy} disabled={!name.trim()}>{edit ? 'Lưu' : 'Tạo lớp'}</Button></div>
      </form>
    </Modal>
  )
}

function CourseForm({ edit, classes, defaultClass, onClose, onSaved }: { edit?: Course; classes: ClassItem[]; defaultClass?: string; onClose: () => void; onSaved: () => void }) {
  const toast = useToast()
  const [cls, setCls] = useState(edit?.class_name ?? defaultClass ?? classes[0]?.name ?? '')
  const [subject, setSubject] = useState(edit?.subject ?? '')
  const [sname, setSname] = useState(edit?.subject_name ?? '')
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true); setErr(null)
    try {
      if (edit) await api.patch(`/api/courses/${edit.id}`, { subject_name: sname })
      else await api.post('/api/courses', { class_name: cls, subject, subject_name: sname })
      toast('success', edit ? 'Đã lưu môn học' : `Đã thêm môn ${subject.trim().toUpperCase()} cho lớp ${cls}`)
      onSaved()
    } catch (e) { setErr((e as ApiError).message) } finally { setBusy(false) }
  }
  return (
    <Modal open onClose={onClose} title={edit ? `Sửa ${edit.class_name} – ${edit.subject}` : 'Thêm môn học cho lớp'} size="sm">
      <form onSubmit={submit} className="space-y-4">
        <Field label="Lớp">
          <select className="input" value={cls} onChange={(e) => setCls(e.target.value)} disabled={!!edit}>
            {classes.map((c) => <option key={c.id} value={c.name}>{c.name}</option>)}
          </select>
        </Field>
        <Field label="Mã môn" hint={edit ? 'Mã môn gắn với lịch sử điểm danh nên không đổi được.' : CODE_HINT}>
          <input className="input uppercase" value={subject} onChange={(e) => setSubject(e.target.value)} disabled={!!edit} placeholder="VD: CPV301" maxLength={32} autoFocus />
        </Field>
        <Field label="Tên môn (tuỳ chọn)"><input className="input" value={sname} onChange={(e) => setSname(e.target.value)} placeholder="VD: Thị giác máy tính" maxLength={120} /></Field>
        {err && <ErrorBox error={err} />}
        <div className="flex justify-end gap-2"><Button type="button" variant="secondary" onClick={onClose}>Hủy</Button><Button type="submit" loading={busy} disabled={!cls || !subject.trim()}>{edit ? 'Lưu' : 'Thêm môn'}</Button></div>
      </form>
    </Modal>
  )
}
