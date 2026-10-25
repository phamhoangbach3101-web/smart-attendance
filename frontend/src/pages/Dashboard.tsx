import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import {
  BookOpen,
  Camera,
  GraduationCap,
  PlayCircle,
  Plus,
  Search,
  Sparkles,
  Users,
  Video,
} from 'lucide-react'
import { api, ApiError, type ClassItem, type Course, type Session, type Settings } from '../api'
import { useHealth, ModelPill } from '../components/Layout'
import {
  Badge,
  Button,
  Card,
  CardHeader,
  ConfirmDialog,
  EmptyState,
  ErrorBox,
  Field,
  Modal,
  Spinner,
  useToast,
} from '../components/ui'
import { cx, todayISO, useAsync, useInterval } from '../lib'

export default function Dashboard() {
  const nav = useNavigate()
  const toast = useToast()
  const health = useHealth()

  // Data queries
  const classesQ = useAsync(() => api.get<ClassItem[]>('/api/classes'))
  const coursesQ = useAsync(() => api.get<Course[]>('/api/courses'))
  const settingsQ = useAsync(() => api.get<Settings>('/api/settings'))
  const activeSessionsQ = useAsync(() => api.get<Session[]>(`/api/sessions?date=${todayISO()}&state=active`))

  useInterval(() => {
    activeSessionsQ.reload(true)
    classesQ.reload(true)
  }, 8000)

  // Local state for Start Attendance Modal / Drawer
  const [startModalOpen, setStartModalOpen] = useState(false)
  const [selectedClass, setSelectedClass] = useState('')
  const [selectedSubject, setSelectedSubject] = useState('')
  const [selectedSlot, setSelectedSlot] = useState(1)
  const [durationMinutes, setDurationMinutes] = useState(15)
  const [unlimitedDuration, setUnlimitedDuration] = useState(false)
  const [cameraType, setCameraType] = useState<'browser' | 'rtsp'>('browser')
  const [rtspUrl, setRtspUrl] = useState('')
  const [useSavedRtsp, setUseSavedRtsp] = useState(false)
  const [startBusy, setStartBusy] = useState(false)
  const [startError, setStartError] = useState<string | null>(null)
  const [reopenAsk, setReopenAsk] = useState<{ message: string; session_id?: number } | null>(null)

  // State for Create Class Modal
  const [createClassModalOpen, setCreateClassModalOpen] = useState(false)
  const [newClassName, setNewClassName] = useState('')
  const [newClassDesc, setNewClassDesc] = useState('')
  const [createClassBusy, setCreateClassBusy] = useState(false)
  const [createClassError, setCreateClassError] = useState<string | null>(null)

  // Filter for class list
  const [searchClass, setSearchClass] = useState('')

  // Sync settings when available
  useEffect(() => {
    if (settingsQ.data) {
      setDurationMinutes(settingsQ.data.default_duration_minutes || 15)
      setUnlimitedDuration(settingsQ.data.default_duration_minutes === 0)
      setUseSavedRtsp(Boolean(settingsQ.data.has_rtsp_url))
    }
  }, [settingsQ.data])

  // Derive courses for selected class
  const classSubjects = useMemo(() => {
    return (coursesQ.data ?? []).filter((c) => c.class_name === selectedClass)
  }, [coursesQ.data, selectedClass])

  // Auto-select class & subject when classes load or selectedClass changes
  useEffect(() => {
    if (!selectedClass && classesQ.data && classesQ.data.length > 0) {
      setSelectedClass(classesQ.data[0].name)
    }
  }, [classesQ.data, selectedClass])

  useEffect(() => {
    if (classSubjects.length > 0 && !classSubjects.some((s) => s.subject === selectedSubject)) {
      setSelectedSubject(classSubjects[0].subject)
    } else if (classSubjects.length === 0) {
      setSelectedSubject('')
    }
  }, [classSubjects, selectedSubject])

  const openAttendanceModalForClass = (clsName: string) => {
    setSelectedClass(clsName)
    setStartError(null)
    setStartModalOpen(true)
  }

  const handleStartAttendance = async (reopen = false) => {
    if (!selectedClass || !selectedSubject) return
    setStartBusy(true)
    setStartError(null)
    try {
      const s = await api.post<Session>('/api/sessions', {
        class_name: selectedClass,
        subject: selectedSubject,
        slot: selectedSlot,
        duration_minutes: unlimitedDuration ? null : durationMinutes,
        camera_type: cameraType,
        reopen,
      })
      if (cameraType === 'rtsp') {
        try {
          await api.post(`/api/sessions/${s.id}/rtsp/start`, {
            url: useSavedRtsp ? null : rtspUrl.trim(),
            use_saved: useSavedRtsp,
            record: true,
          })
        } catch (e) {
          toast('error', `Phiên đã mở nhưng chưa kết nối được camera: ${(e as ApiError).message}`)
        }
      }
      toast('success', s.created ? 'Đã tạo phiên điểm danh' : 'Tiếp tục phiên điểm danh')
      setStartModalOpen(false)
      nav(`/attendance/${s.id}`)
    } catch (e) {
      const ae = e as ApiError
      if (ae.code === 'session_ended') {
        setReopenAsk({ message: ae.message, session_id: (ae as any).session_id })
      } else {
        setStartError(ae.message)
      }
    } finally {
      setStartBusy(false)
    }
  }

  const handleCreateClass = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!newClassName.trim()) return
    setCreateClassBusy(true)
    setCreateClassError(null)
    try {
      const created = await api.post<ClassItem>('/api/classes', {
        name: newClassName.trim().toUpperCase(),
        description: newClassDesc.trim(),
      })
      toast('success', `Đã tạo lớp ${created.name}`)
      setCreateClassModalOpen(false)
      setNewClassName('')
      setNewClassDesc('')
      classesQ.reload(true)
    } catch (e) {
      setCreateClassError((e as ApiError).message)
    } finally {
      setCreateClassBusy(false)
    }
  }

  const activeSession = activeSessionsQ.data?.[0]
  const allClasses = classesQ.data ?? []
  const filteredClasses = useMemo(() => {
    const q = searchClass.trim().toLowerCase()
    if (!q) return allClasses
    return allClasses.filter(
      (c) => c.name.toLowerCase().includes(q) || (c.description && c.description.toLowerCase().includes(q))
    )
  }, [allClasses, searchClass])

  const durationValid = unlimitedDuration || (durationMinutes >= 1 && durationMinutes <= 600)
  const rtspValid =
    cameraType === 'browser' ||
    (useSavedRtsp && settingsQ.data?.has_rtsp_url) ||
    /^rtsps?:\/\/\S+$/i.test(rtspUrl.trim())
  const canSubmitAttendance = Boolean(selectedClass && selectedSubject && durationValid && rtspValid && !startBusy)

  return (
    <div className="space-y-6">
      {/* ========================================================
          KHU VỰC A: BẮT ĐẦU ĐIỂM DANH (HERO CARD NỔI BẬT)
         ======================================================== */}
      <div className="relative overflow-hidden rounded-3xl bg-gradient-to-br from-primary via-[#11b778] to-[#0d9963] p-6 text-white shadow-xl shadow-primary/20 md:p-8">
        {/* Soft decorative background circles */}
        <div className="pointer-events-none absolute -right-16 -top-16 size-72 rounded-full bg-white/10 blur-xl" />
        <div className="pointer-events-none absolute -bottom-20 right-28 size-60 rounded-full bg-white/10 blur-lg" />

        <div className="relative z-10 flex flex-col justify-between gap-6 lg:flex-row lg:items-center">
          <div className="max-w-2xl space-y-3">
            <div className="flex flex-wrap items-center gap-2.5">
              <span className="inline-flex items-center gap-1.5 rounded-full bg-white/20 px-3 py-1 text-xs font-semibold tracking-wide text-white backdrop-blur-sm">
                <Sparkles className="size-3.5 text-white" /> HỆ THỐNG ĐIỂM DANH THÔNG MINH
              </span>
              <ModelPill health={health.health} offline={health.offline} />
            </div>

            <h1 className="text-2xl font-black tracking-tight sm:text-3xl lg:text-4xl">
              Điểm danh nhận diện khuôn mặt
            </h1>
            <p className="text-sm leading-relaxed text-white/90 sm:text-base">
              Chọn lớp và môn học để mở phiên điểm danh. Hệ thống tự động nhận diện sinh viên qua camera thời gian thực,
              đối chiếu dữ liệu sinh trắc học và cập nhật dữ liệu tức thì.
            </p>
          </div>

          <div className="shrink-0 space-y-3">
            {activeSession ? (
              <div className="rounded-2xl border border-white/25 bg-white/15 p-4 text-white backdrop-blur-md">
                <div className="flex items-center gap-2">
                  <span className="size-2.5 animate-pulse rounded-full bg-emerald-300" />
                  <p className="text-xs font-bold uppercase tracking-wider text-emerald-200">Đang có phiên mở</p>
                </div>
                <p className="mt-1 font-bold text-white">
                  {activeSession.class_name} · {activeSession.subject} · Slot {activeSession.slot}
                </p>
                <p className="text-xs text-white/80">
                  {activeSession.present_count}/{activeSession.roster_count} sinh viên đã có mặt
                </p>
                <div className="mt-3 flex gap-2">
                  <Button
                    onClick={() => nav(`/attendance/${activeSession.id}`)}
                    className="!bg-white !text-primary-dark font-bold hover:!bg-white/90"
                    icon={<PlayCircle className="size-5 text-primary" />}
                  >
                    Tiếp tục điểm danh
                  </Button>
                  <Button
                    variant="ghost"
                    onClick={() => setStartModalOpen(true)}
                    className="!border !border-white/30 !text-white hover:!bg-white/15"
                  >
                    Phiên mới
                  </Button>
                </div>
              </div>
            ) : (
              <Button
                size="lg"
                onClick={() => setStartModalOpen(true)}
                className="!h-13 w-full !bg-white px-7 text-base font-bold !text-primary-dark shadow-lg shadow-black/10 transition hover:!bg-white/90 hover:scale-[1.02] sm:w-auto"
                icon={<Camera className="size-5 text-primary" />}
              >
                Bắt đầu điểm danh
              </Button>
            )}
          </div>
        </div>
      </div>

      {/* ========================================================
          KHU VỰC B: DANH SÁCH LỚP HỌC (THỰC TẾ TỪ DATABASE)
         ======================================================== */}
      <Card className="overflow-hidden">
        <CardHeader
          title="Danh sách lớp học"
          subtitle="Quản lý các lớp thực tế trong hệ thống và bắt đầu điểm danh theo lớp"
          icon={<GraduationCap className="size-5" />}
          action={
            <Button
              size="sm"
              icon={<Plus className="size-4" />}
              onClick={() => setCreateClassModalOpen(true)}
            >
              Tạo lớp mới
            </Button>
          }
        />

        {/* Thanh tìm kiếm lớp */}
        <div className="border-b border-line p-4 sm:p-5">
          <div className="relative max-w-md">
            <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted" />
            <input
              className="input pl-9"
              placeholder="Tìm kiếm theo mã lớp hoặc mô tả…"
              value={searchClass}
              onChange={(e) => setSearchClass(e.target.value)}
            />
          </div>
        </div>

        {/* Nội dung danh sách lớp */}
        <div className="p-4 sm:p-6">
          {classesQ.error ? (
            <ErrorBox error={classesQ.error} onRetry={() => classesQ.reload()} />
          ) : classesQ.loading && !classesQ.data ? (
            <Spinner />
          ) : allClasses.length === 0 ? (
            <EmptyState
              icon={<GraduationCap className="size-8" />}
              title="Chưa có lớp học nào"
              action={
                <Button icon={<Plus className="size-4" />} onClick={() => setCreateClassModalOpen(true)}>
                  Tạo lớp học đầu tiên
                </Button>
              }
            >
              Tạo lớp học mới (ví dụ: SE1701) để quản lý sinh viên và bắt đầu các phiên điểm danh.
            </EmptyState>
          ) : filteredClasses.length === 0 ? (
            <EmptyState
              icon={<Search className="size-7" />}
              title="Không tìm thấy lớp học phù hợp"
            >
              Thử tìm với từ khóa khác hoặc xóa bộ lọc tìm kiếm.
            </EmptyState>
          ) : (
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {filteredClasses.map((cls) => (
                <div
                  key={cls.id}
                  className="card group flex flex-col justify-between border border-line p-5 transition-all hover:border-primary/50 hover:shadow-card"
                >
                  <div>
                    <div className="flex items-start justify-between gap-3">
                      <div className="grid size-12 shrink-0 place-items-center rounded-2xl bg-primary-light font-bold text-primary-dark">
                        {cls.name.slice(0, 2)}
                      </div>
                      <div className="flex flex-wrap gap-1.5">
                        <Badge tone="green">
                          <Users className="size-3" /> {cls.student_count} sinh viên
                        </Badge>
                        <Badge tone="blue">
                          <BookOpen className="size-3" /> {cls.course_count} môn
                        </Badge>
                      </div>
                    </div>

                    <h3 className="mt-4 text-lg font-bold text-ink">{cls.name}</h3>
                    <p className="mt-1 line-clamp-2 text-xs text-muted">
                      {cls.description ? cls.description : 'Chưa có mô tả cho lớp học này.'}
                    </p>
                  </div>

                  <div className="mt-5 flex items-center gap-2 border-t border-line/80 pt-4">
                    <Button
                      size="sm"
                      variant="secondary"
                      className="flex-1"
                      icon={<Users className="size-4" />}
                      onClick={() => nav(`/students?class=${encodeURIComponent(cls.name)}`)}
                    >
                      Sinh viên
                    </Button>
                    <Button
                      size="sm"
                      className="flex-1"
                      icon={<Camera className="size-4" />}
                      onClick={() => openAttendanceModalForClass(cls.name)}
                    >
                      Điểm danh
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </Card>

      {/* ========================================================
          MODAL: THIẾT LẬP VÀ BẮT ĐẦU ĐIỂM DANH
         ======================================================== */}
      {startModalOpen && (
        <Modal
          open
          onClose={() => setStartModalOpen(false)}
          title="Bắt đầu phiên điểm danh"
          size="lg"
          footer={
            <>
              <Button variant="secondary" onClick={() => setStartModalOpen(false)}>
                Hủy
              </Button>
              <Button
                loading={startBusy}
                disabled={!canSubmitAttendance}
                onClick={() => handleStartAttendance(false)}
                icon={<Camera className="size-4" />}
              >
                Vào điểm danh
              </Button>
            </>
          }
        >
          <div className="space-y-4">
            {/* Lớp & Môn học */}
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Lớp học">
                <select
                  className="input"
                  value={selectedClass}
                  onChange={(e) => setSelectedClass(e.target.value)}
                >
                  {allClasses.map((c) => (
                    <option key={c.id} value={c.name}>
                      {c.name} ({c.student_count} SV)
                    </option>
                  ))}
                </select>
              </Field>

              <Field label="Môn học">
                {classSubjects.length === 0 ? (
                  <div className="flex h-11 items-center justify-between rounded-xl border border-dashed border-amber-300 bg-amber-50 px-3 text-xs text-amber-800">
                    <span>Lớp chưa có môn học nào</span>
                    <Link
                      to="/classes"
                      className="font-bold underline"
                      onClick={() => setStartModalOpen(false)}
                    >
                      Thêm môn
                    </Link>
                  </div>
                ) : (
                  <select
                    className="input"
                    value={selectedSubject}
                    onChange={(e) => setSelectedSubject(e.target.value)}
                  >
                    {classSubjects.map((s) => (
                      <option key={s.id} value={s.subject}>
                        {s.subject}
                        {s.subject_name ? ` — ${s.subject_name}` : ''}
                      </option>
                    ))}
                  </select>
                )}
              </Field>
            </div>

            {/* Buổi học (Slot) */}
            <div>
              <span className="label">Buổi học (Slot)</span>
              <div className="grid grid-cols-5 gap-2 sm:grid-cols-10">
                {Array.from({ length: 10 }, (_, i) => i + 1).map((n) => (
                  <button
                    type="button"
                    key={n}
                    onClick={() => setSelectedSlot(n)}
                    className={cx(
                      'h-10 rounded-xl border text-sm font-semibold transition',
                      selectedSlot === n
                        ? 'border-primary bg-primary text-white shadow-sm shadow-primary/30'
                        : 'border-line bg-white hover:border-primary/50'
                    )}
                  >
                    {n}
                  </button>
                ))}
              </div>
            </div>

            {/* Thời lượng */}
            <div className="grid gap-4 sm:grid-cols-2">
              <Field
                label="Thời lượng (phút)"
                hint="Thời gian mở phiên điểm danh"
                error={!durationValid ? 'Từ 1 đến 600 phút' : null}
              >
                <input
                  type="number"
                  className="input"
                  min={1}
                  max={600}
                  value={durationMinutes}
                  disabled={unlimitedDuration}
                  onChange={(e) => setDurationMinutes(Number(e.target.value))}
                />
              </Field>

              <div className="flex flex-col justify-end pb-1.5">
                <label className="flex cursor-pointer items-center gap-2.5">
                  <input
                    type="checkbox"
                    className="size-4 rounded accent-primary"
                    checked={unlimitedDuration}
                    onChange={(e) => setUnlimitedDuration(e.target.checked)}
                  />
                  <span className="text-sm font-medium text-ink">Không giới hạn thời gian</span>
                </label>
              </div>
            </div>

            {/* Nguồn Camera */}
            <Field label="Nguồn camera điểm danh">
              <div className="grid grid-cols-2 gap-3">
                <button
                  type="button"
                  onClick={() => setCameraType('browser')}
                  className={cx(
                    'flex items-center gap-2.5 rounded-xl border p-3 text-left transition',
                    cameraType === 'browser'
                      ? 'border-primary bg-primary-light/50 text-primary-dark font-semibold'
                      : 'border-line text-muted hover:border-primary/40'
                  )}
                >
                  <Camera className="size-4 shrink-0 text-primary" />
                  <span className="text-sm">Webcam máy tính</span>
                </button>
                <button
                  type="button"
                  onClick={() => setCameraType('rtsp')}
                  className={cx(
                    'flex items-center gap-2.5 rounded-xl border p-3 text-left transition',
                    cameraType === 'rtsp'
                      ? 'border-primary bg-primary-light/50 text-primary-dark font-semibold'
                      : 'border-line text-muted hover:border-primary/40'
                  )}
                >
                  <Video className="size-4 shrink-0 text-primary" />
                  <span className="text-sm">Camera IP (RTSP)</span>
                </button>
              </div>
            </Field>

            {cameraType === 'rtsp' && (
              <Field label="Địa chỉ luồng RTSP" error={!rtspValid ? 'Định dạng rtsp://...' : null}>
                <input
                  className="input font-mono text-sm"
                  placeholder="rtsp://admin:password@192.168.1.100:554/live"
                  value={rtspUrl}
                  onChange={(e) => setRtspUrl(e.target.value)}
                />
              </Field>
            )}

            {/* Trạng thái Model & Cảnh báo */}
            <div className="rounded-xl border border-line bg-gray-50/70 p-3 text-xs text-muted">
              <div className="flex items-center justify-between">
                <span>Trạng thái Model nhận diện:</span>
                <ModelPill health={health.health} offline={health.offline} />
              </div>
            </div>

            {startError && <ErrorBox error={startError} />}
          </div>
        </Modal>
      )}

      {/* MODAL: MỞ LẠI PHIÊN CŨ KHI TRÙNG SLOT */}
      {reopenAsk && (
        <ConfirmDialog
          open
          title="Phiên hôm nay đã kết thúc"
          message={reopenAsk.message}
          confirmLabel="Mở lại phiên này"
          onClose={() => setReopenAsk(null)}
          onConfirm={() => {
            setReopenAsk(null)
            handleStartAttendance(true)
          }}
        />
      )}

      {/* ========================================================
          MODAL: TẠO LỚP HỌC MỚI
         ======================================================== */}
      {createClassModalOpen && (
        <Modal
          open
          onClose={() => setCreateClassModalOpen(false)}
          title="Tạo lớp học mới"
          size="sm"
        >
          <form onSubmit={handleCreateClass} className="space-y-4">
            <Field
              label="Mã lớp"
              hint="Ví dụ: SE1701, AI1802 (Tự động viết hoa, không dấu cách)"
            >
              <input
                className="input font-mono uppercase"
                placeholder="SE1701"
                value={newClassName}
                onChange={(e) => setNewClassName(e.target.value)}
                maxLength={32}
                autoFocus
              />
            </Field>

            <Field label="Mô tả lớp học (Tùy chọn)">
              <input
                className="input"
                placeholder="Ví dụ: Kỹ thuật phần mềm - Khóa 17"
                value={newClassDesc}
                onChange={(e) => setNewClassDesc(e.target.value)}
                maxLength={120}
              />
            </Field>

            {createClassError && <ErrorBox error={createClassError} />}

            <div className="flex justify-end gap-2 pt-2">
              <Button
                type="button"
                variant="secondary"
                onClick={() => setCreateClassModalOpen(false)}
              >
                Hủy
              </Button>
              <Button
                type="submit"
                loading={createClassBusy}
                disabled={!newClassName.trim()}
              >
                Tạo lớp
              </Button>
            </div>
          </form>
        </Modal>
      )}
    </div>
  )
}
