import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import {
  ArrowLeft,
  Camera,
  CameraOff,
  CheckCircle2,
  FileSpreadsheet,
  ImagePlus,
  Loader2,
  RefreshCw,
  Save,
  Trash2,
  Upload,
  UserCheck,
  XCircle,
} from 'lucide-react'
import { api, ApiError, type ClassItem, type SampleCheck, type Student } from '../api'
import { CameraPlaceholder, FaceOverlay, useBrowserCamera } from '../components/camera'
import { useHealth } from '../components/Layout'
import {
  Button,
  Card,
  CardHeader,
  ErrorBox,
  Field,
  Notice,
  Spinner,
  useToast,
} from '../components/ui'
import { cx, useAsync } from '../lib'

const MAX_SAMPLES = 5
const MAX_FILE_SIZE_BYTES = 3 * 1024 * 1024 // 3MB

export type Sample = {
  id: number
  blob: Blob
  url: string
  check: SampleCheck | null
  checking: boolean
  error?: string
  source?: 'webcam' | 'upload'
  name?: string
}

/**
 * Camera + file sample capture with two explicit choices:
 * 1. Quét trực tiếp bằng webcam
 * 2. Tải ảnh chân dung từ máy tính
 */
export function SampleCapture({
  samples,
  setSamples,
  disabled,
}: {
  samples: Sample[]
  setSamples: React.Dispatch<React.SetStateAction<Sample[]>>
  disabled?: boolean
}) {
  const [tab, setTab] = useState<'webcam' | 'upload'>('webcam')
  const cam = useBrowserCamera()
  const [busy, setBusy] = useState(false)
  const fileInputRef = useRef<HTMLInputElement | null>(null)
  const [dragOver, setDragOver] = useState(false)
  const [uploadError, setUploadError] = useState<string | null>(null)

  useEffect(() => () => samples.forEach((s) => URL.revokeObjectURL(s.url)), []) // eslint-disable-line

  const checkSample = async (s: Sample) => {
    setSamples((x) => x.map((i) => (i.id === s.id ? { ...i, checking: true, error: undefined } : i)))
    try {
      const fd = new FormData()
      fd.append('file', s.blob, s.name || 'sample.jpg')
      const res = await api.form<SampleCheck>('/api/enrollment/check', fd)
      setSamples((x) => x.map((i) => (i.id === s.id ? { ...i, check: res, checking: false } : i)))
    } catch (e) {
      setSamples((x) =>
        x.map((i) => (i.id === s.id ? { ...i, checking: false, error: (e as ApiError).message } : i))
      )
    }
  }

  // 1. Quét webcam
  const shoot = async () => {
    if (samples.length >= MAX_SAMPLES) return
    setBusy(true)
    const blob = await cam.capture(1280, 0.9)
    setBusy(false)
    if (!blob) return
    const s: Sample = {
      id: Date.now() + Math.random(),
      blob,
      url: URL.createObjectURL(blob),
      check: null,
      checking: true,
      source: 'webcam',
      name: `webcam_${samples.length + 1}.jpg`,
    }
    setSamples((x) => [...x, s])
    checkSample(s)
  }

  // 2. Tải ảnh từ máy tính
  const handleFiles = (files: FileList | File[]) => {
    setUploadError(null)
    const validExts = ['.jpg', '.jpeg', '.png']
    const added: Sample[] = []

    for (let i = 0; i < files.length; i++) {
      if (samples.length + added.length >= MAX_SAMPLES) break
      const f = files[i]
      const ext = f.name.slice(f.name.lastIndexOf('.')).toLowerCase()
      if (!validExts.includes(ext)) {
        setUploadError(`File "${f.name}" không hợp lệ. Chỉ chấp nhận định dạng JPG, JPEG, PNG.`)
        continue
      }
      if (f.size > MAX_FILE_SIZE_BYTES) {
        setUploadError(`Ảnh "${f.name}" quá lớn (${(f.size / (1024 * 1024)).toFixed(1)} MB). Dung lượng tối đa là 3 MB.`)
        continue
      }
      const s: Sample = {
        id: Date.now() + Math.random() + i,
        blob: f,
        url: URL.createObjectURL(f),
        check: null,
        checking: true,
        source: 'upload',
        name: f.name,
      }
      added.push(s)
    }

    if (added.length > 0) {
      setSamples((prev) => [...prev, ...added])
      added.forEach((s) => checkSample(s))
    }
  }

  const remove = (id: number) => {
    setSamples((x) => {
      x.filter((i) => i.id === id).forEach((i) => URL.revokeObjectURL(i.url))
      return x.filter((i) => i.id !== id)
    })
  }

  const lastWebcam = [...samples].reverse().find((s) => s.source === 'webcam')

  return (
    <div className="space-y-4">
      {/* LỰA CHỌN PHƯƠNG THỨC THU MẪU */}
      <div className="flex rounded-2xl border border-line bg-gray-50/80 p-1.5">
        <button
          type="button"
          onClick={() => {
            setTab('webcam')
          }}
          className={cx(
            'flex flex-1 items-center justify-center gap-2 rounded-xl py-2.5 text-sm font-bold transition',
            tab === 'webcam'
              ? 'bg-white text-primary-dark shadow-sm'
              : 'text-muted hover:text-ink'
          )}
        >
          <Camera className="size-4 text-primary" />
          1. Quét trực tiếp bằng webcam
        </button>
        <button
          type="button"
          onClick={() => {
            setTab('upload')
            cam.stop()
          }}
          className={cx(
            'flex flex-1 items-center justify-center gap-2 rounded-xl py-2.5 text-sm font-bold transition',
            tab === 'upload'
              ? 'bg-white text-primary-dark shadow-sm'
              : 'text-muted hover:text-ink'
          )}
        >
          <Upload className="size-4 text-primary" />
          2. Tải ảnh chân dung từ máy tính
        </button>
      </div>

      {/* TAB 1: WEBCAM */}
      {tab === 'webcam' && (
        <div className="space-y-3">
          <div className="relative aspect-video overflow-hidden rounded-2xl bg-gray-900 shadow-inner">
            <video
              ref={cam.videoRef}
              playsInline
              muted
              className={cx(
                'absolute inset-0 size-full -scale-x-100 object-contain',
                cam.state !== 'live' && 'invisible'
              )}
            />
            {cam.state !== 'live' && (
              <CameraPlaceholder state={cam.state} error={cam.error} onStart={() => cam.start()} />
            )}
            {cam.state === 'live' && lastWebcam?.check?.box && (
              <FaceOverlay
                mirrored
                width={lastWebcam.check.width}
                height={lastWebcam.check.height}
                faces={[
                  {
                    box: lastWebcam.check.box,
                    role: 'primary',
                    state: lastWebcam.check.ok ? 'recognized' : 'unverifiable',
                    label: lastWebcam.check.ok ? 'Mẫu vừa chụp hợp lệ' : lastWebcam.check.message,
                    det_score: lastWebcam.check.det_score ?? 0,
                  },
                ]}
              />
            )}
            {cam.state === 'live' && (
              <div className="pointer-events-none absolute inset-0 grid place-items-center">
                <div className="aspect-[3/4] h-[70%] rounded-[45%] border-2 border-dashed border-white/50" />
              </div>
            )}
          </div>

          <div className="flex flex-wrap items-center gap-2">
            {cam.state === 'live' ? (
              <Button variant="secondary" icon={<CameraOff className="size-4" />} onClick={cam.stop}>
                Tắt camera
              </Button>
            ) : (
              <Button variant="secondary" icon={<Camera className="size-4" />} onClick={() => cam.start()}>
                Bật camera
              </Button>
            )}

            {cam.devices.length > 1 && (
              <select
                className="input h-11 w-auto max-w-[220px]"
                value={cam.deviceId}
                onChange={(e) => {
                  cam.setDeviceId(e.target.value)
                  if (cam.state === 'live') cam.start(e.target.value)
                }}
              >
                {cam.devices.map((d, i) => (
                  <option key={d.deviceId} value={d.deviceId}>
                    {d.label || `Camera ${i + 1}`}
                  </option>
                ))}
              </select>
            )}

            <Button
              icon={<ImagePlus className="size-4" />}
              loading={busy}
              disabled={disabled || cam.state !== 'live' || samples.length >= MAX_SAMPLES}
              onClick={shoot}
            >
              Chụp mẫu ({samples.length}/{MAX_SAMPLES})
            </Button>
          </div>
          <p className="text-xs text-muted">
            Mẹo: Ngồi đối diện camera, nhìn thẳng, đủ sáng. Nên chụp 2–3 góc hơi nghiêng nhẹ để nhận diện chuẩn hơn.
          </p>
        </div>
      )}

      {/* TAB 2: TẢI ẢNH TỪ MÁY TÍNH */}
      {tab === 'upload' && (
        <div className="space-y-3">
          <input
            type="file"
            ref={fileInputRef}
            className="hidden"
            accept=".jpg,.jpeg,.png,image/jpeg,image/png"
            multiple
            onChange={(e) => {
              if (e.target.files) handleFiles(e.target.files)
              e.target.value = ''
            }}
          />

          <div
            onDragOver={(e) => {
              e.preventDefault()
              setDragOver(true)
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={(e) => {
              e.preventDefault()
              setDragOver(false)
              if (e.dataTransfer.files) handleFiles(e.dataTransfer.files)
            }}
            onClick={() => fileInputRef.current?.click()}
            className={cx(
              'flex cursor-pointer flex-col items-center justify-center rounded-2xl border-2 border-dashed p-8 text-center transition',
              dragOver
                ? 'border-primary bg-primary-light/40'
                : 'border-line hover:border-primary/60 hover:bg-primary-light/20',
              samples.length >= MAX_SAMPLES && 'pointer-events-none opacity-50'
            )}
          >
            <div className="grid size-14 place-items-center rounded-2xl bg-primary-light text-primary">
              <Upload className="size-7" />
            </div>
            <p className="mt-3 text-sm font-bold text-ink">
              Nhấn để chọn ảnh hoặc kéo thả file vào đây
            </p>
            <p className="mt-1 text-xs text-muted">
              Định dạng hỗ trợ: JPG, JPEG, PNG (Tối đa 3 MB/ảnh, tối đa {MAX_SAMPLES} ảnh mẫu).
            </p>
            <p className="mt-2 text-xs font-semibold text-primary">
              Đã tải: {samples.length}/{MAX_SAMPLES} mẫu
            </p>
          </div>

          {uploadError && <ErrorBox error={uploadError} />}
        </div>
      )}

      {/* DANH SÁCH CÁC MẪU ĐÃ THU THẬP */}
      {samples.length > 0 && (
        <div className="space-y-2 border-t border-line/80 pt-3">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold uppercase tracking-wider text-muted">
              Danh sách mẫu khuôn mặt ({samples.length}/{MAX_SAMPLES})
            </span>
            <span className="text-xs text-muted">
              {samples.filter((s) => s.check?.ok).length} mẫu hợp lệ
            </span>
          </div>

          <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3 md:grid-cols-5">
            {samples.map((s, i) => (
              <div
                key={s.id}
                className={cx(
                  'group relative overflow-hidden rounded-2xl border-2 transition',
                  s.check?.ok
                    ? 'border-primary'
                    : s.checking
                      ? 'border-line'
                      : 'border-danger'
                )}
              >
                <img
                  src={s.url}
                  alt={`Mẫu ${i + 1}`}
                  className={cx(
                    'aspect-square w-full object-cover',
                    s.source === 'webcam' && '-scale-x-100'
                  )}
                />

                <div
                  className={cx(
                    'absolute inset-x-0 bottom-0 flex items-center gap-1 px-2 py-1.5 text-[11px] font-semibold text-white',
                    s.check?.ok
                      ? 'bg-primary/95'
                      : s.checking
                        ? 'bg-gray-800/85'
                        : 'bg-danger/95'
                  )}
                >
                  {s.checking ? (
                    <Loader2 className="size-3 animate-spin shrink-0" />
                  ) : s.check?.ok ? (
                    <CheckCircle2 className="size-3 shrink-0" />
                  ) : (
                    <XCircle className="size-3 shrink-0" />
                  )}
                  <span className="truncate">
                    {s.checking
                      ? 'Đang kiểm tra…'
                      : s.error ?? (s.check?.ok ? 'Mẫu hợp lệ' : s.check?.message)}
                  </span>
                </div>

                <div className="absolute right-1.5 top-1.5 flex gap-1">
                  {!s.checking && !s.check?.ok && (
                    <button
                      type="button"
                      onClick={() => checkSample(s)}
                      className="grid size-7 place-items-center rounded-lg bg-white/95 text-gray-700 shadow hover:bg-white"
                      title="Kiểm tra lại mẫu này"
                    >
                      <RefreshCw className="size-3.5" />
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => remove(s.id)}
                    className="grid size-7 place-items-center rounded-lg bg-white/95 text-red-600 shadow hover:bg-white"
                    title="Xóa mẫu này"
                  >
                    <Trash2 className="size-3.5" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

export function samplesForm(samples: Sample[]) {
  const fd = new FormData()
  samples.forEach((s, i) => fd.append('files', s.blob, s.name || `sample_${i + 1}.jpg`))
  return fd
}

export default function Enroll() {
  const [params] = useSearchParams()
  const nav = useNavigate()
  const toast = useToast()
  const { health } = useHealth()
  const back = params.get('back')
  const classes = useAsync(() => api.get<ClassItem[]>('/api/classes'))
  const [cls, setCls] = useState(params.get('class') ?? '')
  const [sid, setSid] = useState('')
  const [name, setName] = useState('')
  const [samples, setSamples] = useState<Sample[]>([])
  const [err, setErr] = useState<ApiError | null>(null)
  const [saving, setSaving] = useState(false)
  const [done, setDone] = useState<Student | null>(null)

  // Face lookup state (kiểm tra xem sinh viên đã có khuôn mặt ở môn/lớp khác chưa)
  const [faceLookup, setFaceLookup] = useState<{
    has_face: boolean
    source_class?: string
    full_name?: string
    student_id?: string
  } | null>(null)

  useEffect(() => {
    if (!cls && classes.data?.[0]) setCls(classes.data[0].name)
  }, [classes.data, cls])

  // Khi nhập mã sinh viên, tự động kiểm tra xem đã từng đăng ký khuôn mặt chưa
  useEffect(() => {
    const cleanId = sid.trim().toUpperCase().replace(/\s+/g, '')
    if (cleanId.length < 3) {
      setFaceLookup(null)
      return
    }
    const timer = setTimeout(async () => {
      try {
        const res = await api.get<{
          has_face: boolean
          source_class?: string
          full_name?: string
          student_id?: string
        }>(`/api/students/lookup-face/${encodeURIComponent(cleanId)}`)
        setFaceLookup(res)
        if (res.has_face && res.full_name && !name) {
          setName(res.full_name)
        }
      } catch {
        setFaceLookup(null)
      }
    }, 400)
    return () => clearTimeout(timer)
  }, [sid]) // eslint-disable-line

  const okSamples = samples.filter((s) => s.check?.ok)
  const pending = samples.some((s) => s.checking)
  const idPreview = sid.trim().toUpperCase().replace(/\s+/g, '')
  const namePreview = name.trim().replace(/\s+/g, ' ')

  // Có thể lưu nếu:
  // - Có đủ thông tin lớp, mã, tên
  // - VÀ: có ít nhất 1 mẫu hợp lệ đã qua kiểm tra,
  // - HOẶC: sinh viên đã có sẵn dữ liệu khuôn mặt trong hệ thống (tái sử dụng)!
  const canSaveWithExistingFace = Boolean(
    cls && idPreview && namePreview && faceLookup?.has_face && samples.length === 0 && !saving
  )
  const canSaveWithNewSamples = Boolean(
    cls &&
      idPreview &&
      namePreview &&
      okSamples.length > 0 &&
      okSamples.length === samples.length &&
      !pending &&
      !saving &&
      health?.models.state === 'ready'
  )
  const canSave = canSaveWithNewSamples || canSaveWithExistingFace

  const save = async () => {
    setSaving(true)
    setErr(null)
    try {
      const fd = samplesForm(samples)
      fd.append('class_name', cls)
      fd.append('student_id', sid)
      fd.append('full_name', name)
      const st = await api.form<Student>('/api/students', fd)
      setDone(st)
      toast('success', `Đã lưu hồ sơ sinh viên ${st.full_name} (${st.student_id})`)
      st.warnings?.forEach((w) => toast('info', w))
    } catch (e) {
      setErr(e as ApiError)
    } finally {
      setSaving(false)
    }
  }

  const reset = () => {
    samples.forEach((s) => URL.revokeObjectURL(s.url))
    setSamples([])
    setSid('')
    setName('')
    setDone(null)
    setErr(null)
    setFaceLookup(null)
  }

  if (classes.error) return <ErrorBox error={classes.error} onRetry={() => classes.reload()} />
  if (!classes.data) return <Spinner />
  if (classes.data.length === 0)
    return (
      <Notice tone="amber" title="Chưa có lớp nào">
        Hãy{' '}
        <Link className="font-semibold underline" to="/classes">
          tạo lớp
        </Link>{' '}
        trước khi đăng ký sinh viên.
      </Notice>
    )

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <Button
          variant="ghost"
          size="sm"
          icon={<ArrowLeft className="size-4" />}
          onClick={() => nav(back ?? '/students')}
        >
          {back ? 'Quay lại phiên điểm danh' : 'Danh sách sinh viên'}
        </Button>
      </div>

      <div className="flex items-center justify-between rounded-2xl border border-primary/30 bg-primary-light/40 p-4">
        <div className="flex items-center gap-3">
          <FileSpreadsheet className="size-5 text-primary" />
          <p className="text-xs text-ink">
            Bạn có file Excel chứa danh sách sinh viên kèm ảnh chân dung?
          </p>
        </div>
        <Link to="/students">
          <Button size="sm" variant="secondary" icon={<FileSpreadsheet className="size-4" />}>
            Mở Import Excel
          </Button>
        </Link>
      </div>

      {done ? (
        <Card className="p-8 text-center">
          <div className="mx-auto grid size-16 place-items-center rounded-full bg-primary-light text-primary">
            <CheckCircle2 className="size-9" />
          </div>
          <h2 className="mt-4 text-xl font-bold">Đăng ký thành công</h2>
          <p className="mt-1 text-muted">
            {done.full_name} · {done.student_id} · lớp {done.class_name} ·{' '}
            {done.embedding_count} mẫu khuôn mặt
          </p>
          <div className="mt-6 flex flex-wrap justify-center gap-2">
            <Button onClick={reset} icon={<ImagePlus className="size-4" />}>
              Đăng ký sinh viên khác
            </Button>
            {back ? (
              <Button variant="secondary" onClick={() => nav(back)}>
                Quay lại điểm danh
              </Button>
            ) : (
              <Button variant="secondary" onClick={() => nav('/students')}>
                Xem danh sách sinh viên
              </Button>
            )}
          </div>
        </Card>
      ) : (
        <div className="grid gap-5 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
          <Card className="p-5 sm:p-6">
            <SampleCapture
              samples={samples}
              setSamples={setSamples}
              disabled={health?.models.state !== 'ready'}
            />
          </Card>

          <Card className="self-start">
            <CardHeader
              title="Thông tin sinh viên"
              subtitle="Mã sinh viên và khuôn mặt được lưu dùng chung cho mọi môn học"
            />

            <div className="space-y-4 p-5">
              <Field label="Lớp học">
                <select className="input" value={cls} onChange={(e) => setCls(e.target.value)}>
                  {classes.data.map((c) => (
                    <option key={c.id} value={c.name}>
                      {c.name}
                    </option>
                  ))}
                </select>
              </Field>

              <Field
                label="Mã sinh viên"
                hint={
                  idPreview ? (
                    <>
                      Sẽ lưu là <b className="font-mono">{idPreview}</b>
                    </>
                  ) : (
                    'VD: HE201068'
                  )
                }
              >
                <input
                  className="input font-mono uppercase"
                  value={sid}
                  onChange={(e) => setSid(e.target.value)}
                  placeholder="HE201068"
                  maxLength={32}
                />
              </Field>

              <Field
                label="Họ và tên"
                hint={namePreview && namePreview !== name ? `Sẽ lưu là “${namePreview}”` : undefined}
              >
                <input
                  className="input"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="Nguyễn Văn An"
                  maxLength={80}
                />
              </Field>

              {/* TỰ ĐỘNG TÁI SỬ DỤNG KHUÔN MẶT NẾU ĐÃ CÓ TRONG HỆ THỐNG */}
              {faceLookup?.has_face && (
                <div className="rounded-2xl border border-primary/40 bg-primary-light/50 p-3.5 text-xs text-primary-dark">
                  <div className="flex items-start gap-2">
                    <UserCheck className="size-4 shrink-0 text-primary mt-0.5" />
                    <div>
                      <p className="font-bold">Đã có khuôn mặt trong hệ thống!</p>
                      <p className="mt-0.5">
                        Sinh viên <b>{faceLookup.student_id}</b> ({faceLookup.full_name}) đã đăng ký khuôn mặt ở lớp{' '}
                        <b>{faceLookup.source_class}</b>.
                      </p>
                      <p className="mt-1 text-primary-dark/80">
                        Bạn có thể lưu ngay để tự động liên kết khuôn mặt, hoặc tải ảnh mới để cập nhật mẫu.
                      </p>
                    </div>
                  </div>
                </div>
              )}

              {health?.models.state !== 'ready' && (
                <Notice tone="amber">
                  Model AI đang tải — vui lòng chờ trạng thái “Model sẵn sàng”.
                </Notice>
              )}

              {samples.length > 0 && okSamples.length !== samples.length && !pending && (
                <Notice tone="amber">
                  Một số ảnh mẫu chưa hợp lệ. Vui lòng kiểm tra lại hoặc xóa ảnh lỗi trước khi lưu.
                </Notice>
              )}

              {err && <ErrorBox error={err} />}

              {saving && (
                <div className="flex items-center gap-2 text-sm text-muted">
                  <Loader2 className="size-4 animate-spin text-primary" />
                  Đang xử lý đặc trưng khuôn mặt, đối chiếu và lưu hồ sơ…
                </div>
              )}

              <Button
                className="w-full"
                size="lg"
                icon={<Save className="size-5" />}
                loading={saving}
                disabled={!canSave}
                onClick={save}
              >
                {samples.length > 0
                  ? `Lưu hồ sơ (${okSamples.length} mẫu)`
                  : faceLookup?.has_face
                    ? 'Lưu & Tái sử dụng khuôn mặt'
                    : 'Lưu hồ sơ sinh viên'}
              </Button>
            </div>
          </Card>
        </div>
      )}
    </div>
  )
}
