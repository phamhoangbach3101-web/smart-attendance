import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { Camera, CalendarClock, History, Infinity as InfinityIcon, MonitorSmartphone, PlayCircle, RotateCcw, Video } from 'lucide-react'
import { api, ApiError, type ClassItem, type Course, type Session, type Settings } from '../api'
import { Badge, Button, Card, CardHeader, ConfirmDialog, EmptyState, ErrorBox, Field, Notice, Spinner, Toggle, useToast } from '../components/ui'
import { useHealth } from '../components/Layout'
import { cx, fmtTime, todayISO, useAsync } from '../lib'

export default function AttendanceSetup() {
  const [params] = useSearchParams()
  const nav = useNavigate()
  const toast = useToast()
  const { health } = useHealth()
  const classes = useAsync(() => api.get<ClassItem[]>('/api/classes'))
  const courses = useAsync(() => api.get<Course[]>('/api/courses'))
  const settings = useAsync(() => api.get<Settings>('/api/settings'))
  const today = useAsync(() => api.get<Session[]>(`/api/sessions?date=${todayISO()}`))

  const [cls, setCls] = useState(params.get('class') ?? '')
  const [subject, setSubject] = useState(params.get('subject') ?? '')
  const [slot, setSlot] = useState(1)
  const [minutes, setMinutes] = useState(15)
  const [unlimited, setUnlimited] = useState(false)
  const [camType, setCamType] = useState<'browser' | 'rtsp'>('browser')
  const [rtspUrl, setRtspUrl] = useState('')
  const [useSaved, setUseSaved] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [reopenAsk, setReopenAsk] = useState<{ message: string } | null>(null)

  useEffect(() => { if (settings.data) { setMinutes(settings.data.default_duration_minutes || 15); setUnlimited(settings.data.default_duration_minutes === 0); setUseSaved(settings.data.has_rtsp_url) } }, [settings.data])
  const classesWithCourses = useMemo(() => (classes.data ?? []).filter((c) => (courses.data ?? []).some((k) => k.class_name === c.name)), [classes.data, courses.data])
  const subjects = useMemo(() => (courses.data ?? []).filter((k) => k.class_name === cls), [courses.data, cls])
  useEffect(() => { if (!cls && classesWithCourses[0]) setCls(classesWithCourses[0].name) }, [classesWithCourses, cls])
  useEffect(() => { if (subjects.length && !subjects.some((s) => s.subject === subject)) setSubject(subjects[0].subject) }, [subjects, subject])

  const selectedClass = classes.data?.find((c) => c.name === cls)
  const durationOk = unlimited || (minutes >= 1 && minutes <= 600)
  const rtspOk = camType === 'browser' || (useSaved && settings.data?.has_rtsp_url) || /^rtsps?:\/\/\S+$/i.test(rtspUrl.trim())
  const canStart = !!cls && !!subject && durationOk && !!rtspOk && !busy

  const open = async (reopen = false) => {
    setBusy(true); setErr(null)
    try {
      const s = await api.post<Session>('/api/sessions', { class_name: cls, subject, slot, duration_minutes: unlimited ? null : minutes, camera_type: camType, reopen })
      if (camType === 'rtsp') {
        try {
          await api.post(`/api/sessions/${s.id}/rtsp/start`, { url: useSaved ? null : rtspUrl.trim(), use_saved: useSaved, record: true })
        } catch (e) { toast('error', `Phiên đã mở nhưng chưa kết nối được camera: ${(e as ApiError).message}`) }
      }
      toast('success', s.created ? 'Đã tạo phiên điểm danh' : s.reopened ? 'Đã mở lại phiên — dữ liệu cũ được giữ nguyên' : 'Phiên đang mở — tiếp tục điểm danh')
      nav(`/attendance/${s.id}`)
    } catch (e) {
      const ae = e as ApiError
      if (ae.code === 'session_ended') setReopenAsk({ message: ae.message })
      else setErr(ae.message)
    } finally { setBusy(false) }
  }

  const loading = (classes.loading && !classes.data) || (courses.loading && !courses.data)
  if (classes.error || courses.error) return <ErrorBox error={(classes.error || courses.error)!} onRetry={() => { classes.reload(); courses.reload() }} />
  if (loading) return <Spinner />

  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
      <Card>
        <CardHeader title="Thiết lập phiên điểm danh" subtitle="Phiên được xác định theo Lớp + Môn + Ngày + Slot; mở lại cùng phiên sẽ tải dữ liệu đã có." icon={<CalendarClock className="size-5" />} />
        {classesWithCourses.length === 0 ? (
          <EmptyState icon={<Camera className="size-7" />} title="Chưa có lớp/môn để điểm danh" action={<Link to="/classes"><Button>Tạo lớp & môn học</Button></Link>}>
            Hãy tạo lớp, thêm môn học và đăng ký khuôn mặt sinh viên trước.
          </EmptyState>
        ) : (
          <form className="space-y-5 p-5" onSubmit={(e) => { e.preventDefault(); if (canStart) open() }}>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Lớp">
                <select className="input" value={cls} onChange={(e) => setCls(e.target.value)}>
                  {classesWithCourses.map((c) => <option key={c.id} value={c.name}>{c.name} ({c.student_count} SV)</option>)}
                </select>
              </Field>
              <Field label="Môn học">
                <select className="input" value={subject} onChange={(e) => setSubject(e.target.value)}>
                  {subjects.map((s) => <option key={s.id} value={s.subject}>{s.subject}{s.subject_name ? ` — ${s.subject_name}` : ''}</option>)}
                </select>
              </Field>
            </div>
            {selectedClass && selectedClass.student_count === 0 && (
              <Notice tone="amber" title="Lớp chưa có sinh viên đăng ký khuôn mặt">Mọi khuôn mặt sẽ bị coi là người lạ. <Link className="font-semibold underline" to={`/students/enroll?class=${cls}`}>Đăng ký sinh viên</Link></Notice>
            )}
            <div>
              <span className="label">Slot</span>
              <div className="grid grid-cols-5 gap-2 sm:grid-cols-10">
                {Array.from({ length: 20 }, (_, i) => i + 1).map((n) => (
                  <button type="button" key={n} onClick={() => setSlot(n)}
                    className={cx('h-11 rounded-xl border text-sm font-semibold transition', slot === n ? 'border-primary bg-primary text-white shadow-sm shadow-primary/30' : 'border-line bg-white hover:border-primary/50')}>{n}</button>
                ))}
              </div>
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Thời lượng (phút)" hint="Backend quản lý hạn kết thúc; tải lại trang không đặt lại bộ đếm." error={!durationOk ? 'Từ 1 đến 600 phút' : null}>
                <input type="number" className="input" min={1} max={600} value={minutes} disabled={unlimited} onChange={(e) => setMinutes(Number(e.target.value))} />
              </Field>
              <div className="flex items-end pb-1">
                <div className="w-full rounded-xl border border-line px-4 py-2.5">
                  <Toggle checked={unlimited} onChange={setUnlimited} label={<span className="inline-flex items-center gap-1.5"><InfinityIcon className="size-4" /> Không giới hạn</span>} />
                </div>
              </div>
            </div>
            <div>
              <span className="label">Nguồn camera</span>
              <div className="grid gap-3 sm:grid-cols-2">
                {[
                  { v: 'browser' as const, icon: MonitorSmartphone, t: 'Webcam của thiết bị này', d: 'Dùng camera của máy đang mở trình duyệt' },
                  { v: 'rtsp' as const, icon: Video, t: 'Camera IP (RTSP)', d: 'Máy chủ kết nối trực tiếp tới camera' },
                ].map(({ v, icon: Icon, t, d }) => (
                  <button type="button" key={v} onClick={() => setCamType(v)}
                    className={cx('flex items-start gap-3 rounded-2xl border p-4 text-left transition', camType === v ? 'border-primary bg-primary-light/60 ring-4 ring-primary/10' : 'border-line hover:border-primary/40')}>
                    <span className={cx('grid size-10 shrink-0 place-items-center rounded-xl', camType === v ? 'bg-primary text-white' : 'bg-gray-100 text-gray-500')}><Icon className="size-5" /></span>
                    <span><span className="block font-semibold">{t}</span><span className="block text-xs text-muted">{d}</span></span>
                  </button>
                ))}
              </div>
              {camType === 'rtsp' && (
                <div className="mt-3 space-y-3">
                  {settings.data?.has_rtsp_url && (
                    <div className="rounded-xl border border-line px-4 py-2.5"><Toggle checked={useSaved} onChange={setUseSaved} label="Dùng địa chỉ đã lưu" description={settings.data.rtsp_url_masked} /></div>
                  )}
                  {!useSaved && (
                    <Field label="Địa chỉ RTSP" hint="Mật khẩu trong địa chỉ không được ghi vào log hay hiển thị lại.">
                      <input className="input font-mono text-sm" value={rtspUrl} onChange={(e) => setRtspUrl(e.target.value)} placeholder="rtsp://user:password@192.168.1.10:554/stream" autoComplete="off" />
                    </Field>
                  )}
                </div>
              )}
            </div>
            {health && health.models.state !== 'ready' && (
              <Notice tone={health.models.state === 'error' ? 'red' : 'amber'} title={health.models.state === 'error' ? 'Model nhận diện lỗi' : 'Model đang tải'}>
                {health.models.state === 'error' ? health.models.error : 'Có thể mở phiên ngay; nhận diện bắt đầu khi model sẵn sàng.'}
              </Notice>
            )}
            {err && <ErrorBox error={err} />}
            <Button type="submit" size="lg" className="w-full sm:w-auto" icon={<PlayCircle className="size-5" />} loading={busy} disabled={!canStart}>Bắt đầu điểm danh</Button>
          </form>
        )}
      </Card>

      <Card className="self-start">
        <CardHeader title="Phiên hôm nay" subtitle="Chọn để tiếp tục hoặc xem lại" icon={<History className="size-5" />} />
        <div className="p-3 sm:p-4">
          {today.error ? <ErrorBox error={today.error} onRetry={() => today.reload()} /> : !today.data ? <Spinner /> : today.data.length === 0 ? (
            <EmptyState icon={<CalendarClock className="size-7" />} title="Chưa có phiên nào hôm nay">Phiên vừa tạo sẽ hiện ở đây.</EmptyState>
          ) : (
            <ul className="space-y-2">
              {today.data.map((s) => (
                <li key={s.id}>
                  <Link to={`/attendance/${s.id}`} className="flex items-center gap-3 rounded-2xl border border-line p-3 transition hover:border-primary/40 hover:bg-primary-light/30">
                    <span className="grid size-11 shrink-0 place-items-center rounded-xl bg-primary-light font-bold text-primary-dark">S{s.slot}</span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate font-semibold">{s.class_name} · {s.subject}</span>
                      <span className="block text-xs text-muted">Mở {fmtTime(s.opened_at)} · {s.present_count}/{s.roster_count} có mặt</span>
                    </span>
                    {s.state === 'active' ? <Badge tone="green" dot>Đang mở</Badge> : <Badge><RotateCcw className="size-3" /> Đã kết thúc</Badge>}
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </div>
      </Card>

      <ConfirmDialog open={!!reopenAsk} title="Mở lại phiên?" confirmLabel="Mở lại phiên" loading={busy}
        message={<><p>{reopenAsk?.message}</p><p className="mt-2 text-sm text-muted">Các lượt điểm danh đã lưu được giữ nguyên thời gian; bộ đếm mới bắt đầu từ bây giờ.</p></>}
        onClose={() => setReopenAsk(null)} onConfirm={() => { setReopenAsk(null); open(true) }} />
    </div>
  )
}
