import { useEffect, useState } from 'react'
import { CheckCircle2, Cpu, Database, FolderOpen, RefreshCw, RotateCcw, Save, ScanFace, ShieldCheck, SlidersHorizontal, Sparkles, Video } from 'lucide-react'
import { api, ApiError, type CalibrationResult, type MigrationStatus, type ModelStatus, type Settings as SettingsT } from '../api'
import { useHealth } from '../components/Layout'
import { Badge, Button, Card, CardHeader, ErrorBox, Field, Notice, Spinner, Toggle, useToast } from '../components/ui'
import { cx, useAsync } from '../lib'

type Form = Omit<SettingsT, 'rtsp_url_masked' | 'has_rtsp_url'> & { rtsp_url: string }

function Slider({ label, hint, value, min, max, step, onChange, fmt = (v: number) => v.toFixed(2) }: { label: string; hint: string; value: number; min: number; max: number; step: number; onChange: (v: number) => void; fmt?: (v: number) => string }) {
  return (
    <div>
      <div className="mb-1.5 flex items-center justify-between"><span className="label !mb-0">{label}</span><span className="rounded-lg bg-primary-light px-2 py-0.5 font-mono text-sm font-semibold text-primary-dark">{fmt(value)}</span></div>
      <input type="range" min={min} max={max} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))} className="w-full accent-[#16C784]" />
      <p className="mt-1 text-xs text-muted">{hint}</p>
    </div>
  )
}

export default function Settings() {
  const toast = useToast()
  const { refresh } = useHealth()
  const s = useAsync(() => api.get<SettingsT>('/api/settings'))
  const models = useAsync(() => api.get<ModelStatus>('/api/models/status'))
  const mig = useAsync(() => api.get<MigrationStatus>('/api/models/migration/status'))
  const sys = useAsync(() => api.get<any>('/api/system'))
  const [form, setForm] = useState<Form | null>(null)
  const [saving, setSaving] = useState(false)
  const [migrating, setMigrating] = useState(false)
  const [rollingBack, setRollingBack] = useState(false)
  const [calibrating, setCalibrating] = useState(false)
  const [calibrationData, setCalibrationData] = useState<CalibrationResult | null>(null)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    if (s.data) {
      const { rtsp_url_masked: _m, has_rtsp_url: _h, ...rest } = s.data
      setForm({ ...rest, rtsp_url: '' })
    }
  }, [s.data])
  const set = <K extends keyof Form>(k: K, v: Form[K]) => setForm((f) => (f ? { ...f, [k]: v } : f))

  const save = async () => {
    if (!form) return
    setSaving(true); setErr(null)
    try {
      const body: any = { ...form }
      if (!body.rtsp_url) delete body.rtsp_url
      await api.put('/api/settings', body)
      toast('success', 'Đã lưu cài đặt')
      s.reload(true); models.reload(true); refresh()
    } catch (e) { setErr((e as ApiError).message) } finally { setSaving(false) }
  }
  const clearRtsp = async () => { try { await api.put('/api/settings', { rtsp_url: '' }); toast('success', 'Đã xóa địa chỉ RTSP đã lưu'); s.reload(true) } catch (e) { toast('error', (e as ApiError).message) } }
  const reload = async () => { await api.post('/api/models/reload'); models.reload(true); refresh() }

  const runMigration = async () => {
    setMigrating(true)
    try {
      const res = await api.post<any>('/api/models/migrate')
      toast('success', `Đã chuyển đổi ${res.summary.migrated_students} sinh viên sang AdaFace IR101!`)
      mig.reload(true); models.reload(true); refresh()
    } catch (e) {
      toast('error', (e as ApiError).message)
    } finally {
      setMigrating(false)
    }
  }

  const runRollback = async () => {
    if (!confirm('Bạn có chắc muốn rollback về embedding model trước?')) return
    setRollingBack(true)
    try {
      const res = await api.post<any>('/api/models/rollback')
      toast('success', `Đã rollback ${res.restored_count} sinh viên về model trước.`)
      mig.reload(true); models.reload(true); refresh()
    } catch (e) {
      toast('error', (e as ApiError).message)
    } finally {
      setRollingBack(false)
    }
  }

  const runCalibration = async () => {
    setCalibrating(true)
    try {
      const res = await api.get<CalibrationResult>('/api/models/calibration')
      setCalibrationData(res)
      toast('success', 'Đã phân tích phân phối tương đồng thực nghiệm')
    } catch (e) {
      toast('error', (e as ApiError).message)
    } finally {
      setCalibrating(false)
    }
  }

  if (s.error) return <ErrorBox error={s.error} onRetry={() => s.reload()} />
  if (!form || !s.data) return <Spinner />
  const m = models.data

  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
      <div className="space-y-5">
        <Card>
          <CardHeader title="Nhận diện AdaFace IR101" subtitle="Quy tắc tập mở: chấp nhận khi điểm tương đồng ≥ ngưỡng VÀ hơn người thứ hai ít nhất một khoảng margin" icon={<SlidersHorizontal className="size-5" />} />
          <div className="space-y-5 p-5">
            <Slider
              label="Ngưỡng điểm tương đồng (cosine)"
              hint="Mặc định 0.45 cho AdaFace IR101. Cao hơn = yêu cầu tương đồng cao hơn. Điểm tương đồng dao động [-1, 1], không phải phần trăm."
              value={form.adaface_cosine_threshold ?? form.cosine_threshold}
              min={0.2}
              max={0.85}
              step={0.01}
              onChange={(v) => {
                set('adaface_cosine_threshold' as any, v)
                set('cosine_threshold', v)
              }}
            />
            <Slider label="Khoảng cách tối thiểu giữa 2 người (margin)" hint="Chênh lệch tối thiểu giữa ứng viên top-1 và top-2 (thuộc 2 mã sinh viên khác nhau). Mặc định 0.08." value={form.min_margin} min={0} max={0.5} step={0.01} onChange={(v) => set('min_margin', v)} />
            <Slider label="Ngưỡng phát hiện khuôn mặt" hint="Điểm tối thiểu của SCRFD để coi là một khuôn mặt. Mặc định 0.50." value={form.detection_threshold} min={0.2} max={0.95} step={0.01} onChange={(v) => set('detection_threshold', v)} />
            <Slider label="Tốc độ gửi khung hình" hint="Số khung hình/giây gửi lên máy chủ khi điểm danh. Máy yếu nên để 2–4." value={form.frame_rate} min={1} max={10} step={1} onChange={(v) => set('frame_rate', v)} fmt={(v) => `${v} fps`} />
            <div className="rounded-xl border border-line px-4 py-3"><Toggle checked={form.preprocessing} onChange={(v) => set('preprocessing', v)} label="Tiền xử lý ảnh (khử nhiễu + CLAHE)" description="Tăng cường tương phản khi ánh sáng yếu." /></div>
            <Field label="Thời lượng phiên mặc định (phút)" hint="0 = mặc định chọn không giới hạn.">
              <input type="number" className="input sm:w-40" min={0} max={600} value={form.default_duration_minutes} onChange={(e) => set('default_duration_minutes', Number(e.target.value))} />
            </Field>
          </div>
        </Card>

        <Card>
          <CardHeader title="Chuyển đổi dữ liệu & Rollback" subtitle="Quản lý an toàn dữ liệu embedding AdaFace IR101" icon={<Database className="size-5" />} />
          <div className="space-y-4 p-5 text-sm">
            <div className="flex items-center justify-between rounded-xl bg-gray-50 p-3">
              <div>
                <p className="font-semibold">Trạng thái dữ liệu nhận dạng</p>
                <p className="text-xs text-muted">Đã tạo embedding AdaFace: <b>{mig.data?.adaface_enrolled ?? '…'} / {mig.data?.total_students ?? '…'}</b> sinh viên</p>
              </div>
              <Badge tone={mig.data?.is_migrated ? 'green' : 'amber'}>{mig.data?.is_migrated ? 'AdaFace IR101' : 'Cần chuyển đổi'}</Badge>
            </div>

            {calibrationData && (
              <div className="rounded-xl border border-line bg-gray-50 p-3">
                <p className="flex items-center gap-1.5 font-semibold text-primary"><CheckCircle2 className="size-4" /> Kết quả kiểm tra phân bố tương đồng</p>
                <p className="mt-1 text-xs text-muted">{calibrationData.message}</p>
                <div className="mt-2 grid grid-cols-2 gap-2 text-xs">
                  <div className="rounded-lg bg-white p-2"><b>Số cặp cùng người:</b> {calibrationData.genuine_count}</div>
                  <div className="rounded-lg bg-white p-2"><b>Số cặp khác người:</b> {calibrationData.impostor_count}</div>
                  {calibrationData.impostor_max !== undefined && <div className="rounded-lg bg-white p-2"><b>Điểm khác người cao nhất:</b> {calibrationData.impostor_max}</div>}
                  {calibrationData.impostor_mean !== undefined && <div className="rounded-lg bg-white p-2"><b>Điểm khác người trung bình:</b> {calibrationData.impostor_mean}</div>}
                </div>
              </div>
            )}

            <div className="flex flex-wrap gap-2 pt-1">
              <Button size="sm" variant="secondary" icon={<Sparkles className="size-4" />} loading={calibrating} onClick={runCalibration}>Hiệu chuẩn ngưỡng thực nghiệm</Button>
              <Button size="sm" variant="secondary" icon={<RefreshCw className="size-4" />} loading={migrating} onClick={runMigration}>Tạo lại embedding hàng loạt</Button>
              {mig.data?.can_rollback && (
                <Button size="sm" variant="ghost" icon={<RotateCcw className="size-4 text-warn" />} loading={rollingBack} onClick={runRollback}>Rollback về bản trước</Button>
              )}
            </div>
            {mig.data?.db_backups && mig.data.db_backups.length > 0 && (
              <p className="text-xs text-muted">Bản sao lưu DB gần nhất: <code className="font-mono text-gray-700">{mig.data.db_backups[0]}</code></p>
            )}
          </div>
        </Card>

        <Card>
          <CardHeader title="Chống giả mạo" subtitle="Khi bật, mọi lỗi hoặc thiếu model đều chặn ghi điểm danh" icon={<ShieldCheck className="size-5" />} />
          <div className="space-y-3 p-5">
            {([
              ['off', 'Tắt', 'Mặc định của dự án gốc. Không kiểm tra liveness.'],
              ['model', 'Model MiniFASNet (ONNX)', 'Cần file anti_spoof_minifas.onnx trong thư mục models. Thiếu model → không thể xác minh, chặn điểm danh.'],
              ['texture_experimental', 'Thuật toán texture (THỬ NGHIỆM)', 'Heuristic độ nét/LBP/màu/FFT, chưa được kiểm thử như model chống giả mạo. Có thể từ chối người thật hoặc bỏ lọt ảnh in.'],
            ] as const).map(([v, t, d]) => (
              <button key={v} type="button" onClick={() => set('antispoof_mode', v)} className={cx('flex w-full items-start gap-3 rounded-2xl border p-4 text-left transition', form.antispoof_mode === v ? 'border-primary bg-primary-light/50 ring-4 ring-primary/10' : 'border-line hover:border-primary/40')}>
                <span className={cx('mt-0.5 grid size-5 shrink-0 place-items-center rounded-full border-2', form.antispoof_mode === v ? 'border-primary' : 'border-gray-300')}>{form.antispoof_mode === v && <span className="size-2.5 rounded-full bg-primary" />}</span>
                <span><span className="block font-semibold">{t}</span><span className="block text-sm text-muted">{d}</span></span>
              </button>
            ))}
            {form.antispoof_mode !== 'off' && <Slider label="Ngưỡng liveness" hint="Điểm live tối thiểu. Mặc định 0.40." value={form.antispoof_threshold} min={0.05} max={0.99} step={0.01} onChange={(v) => set('antispoof_threshold', v)} />}
          </div>
        </Card>

        <Card>
          <CardHeader title="Camera IP (RTSP)" subtitle="Địa chỉ mặc định khi chọn nguồn camera RTSP" icon={<Video className="size-5" />} />
          <div className="space-y-3 p-5">
            {s.data.has_rtsp_url && <div className="flex flex-wrap items-center gap-2 text-sm"><span className="text-muted">Đã lưu:</span><code className="rounded-lg bg-gray-100 px-2 py-1">{s.data.rtsp_url_masked}</code><Button size="sm" variant="ghost" onClick={clearRtsp}>Xóa</Button></div>}
            <Field label={s.data.has_rtsp_url ? 'Thay địa chỉ mới (để trống = giữ nguyên)' : 'Địa chỉ RTSP'} hint="Mật khẩu không được hiển thị lại hay ghi vào log.">
              <input className="input font-mono text-sm" value={form.rtsp_url} onChange={(e) => set('rtsp_url', e.target.value)} placeholder="rtsp://user:password@192.168.1.10:554/stream" autoComplete="off" />
            </Field>
            <p className="text-xs text-muted">Webcam: trình duyệt sẽ hỏi quyền và cho chọn camera ngay trên trang Điểm danh.</p>
          </div>
        </Card>

        {err && <ErrorBox error={err} />}
        <div className="sticky bottom-20 z-10 flex justify-end lg:bottom-4"><Button size="lg" icon={<Save className="size-5" />} loading={saving} onClick={save} className="shadow-pop">Lưu cài đặt</Button></div>
      </div>

      <div className="space-y-5">
        <Card>
          <CardHeader title="Tình trạng model nhận diện" icon={<ScanFace className="size-5" />} action={<Button size="sm" variant="secondary" icon={<RefreshCw className="size-4" />} onClick={reload}>Tải lại</Button>} />
          <div className="space-y-3 p-5 text-sm">
            {!m ? <Spinner /> : (<>
              <div className="flex items-center justify-between">
                <div>
                  <span className="font-semibold text-gray-900">{m.model_name || 'AdaFace IR101 WebFace12M'}</span>
                  <span className="ml-2 text-xs text-muted font-mono">rev: {m.revision ? m.revision.substring(0, 7) : '54f602a'}</span>
                </div>
                {m.state === 'ready' ? <Badge tone="green" dot>Sẵn sàng</Badge> : m.state === 'error' ? <Badge tone="red" dot>Lỗi</Badge> : <Badge tone="amber" dot>Đang tải</Badge>}
              </div>

              <div className="rounded-xl border border-line bg-gray-50/70 p-3 space-y-1.5 text-xs">
                <div className="flex justify-between"><span className="text-muted">Thiết bị chạy:</span><span className="font-semibold text-gray-800">{m.device || 'CPU'}</span></div>
                <div className="flex justify-between"><span className="text-muted">Embedding vector:</span><span className="font-mono">{m.embedding_dim || 512} chiều</span></div>
                <div className="flex justify-between"><span className="text-muted">Tiền xử lý:</span><span>112×112 (RGB, norm 0.5)</span></div>
                <div className="flex justify-between"><span className="text-muted">Trọng số (SHA-256):</span><span className="font-mono text-gray-600">{m.weights_sha256 ? m.weights_sha256.substring(0, 16) + '…' : 'e312d79222…'}</span></div>
              </div>

              {m.error && <Notice tone="red">{m.error}</Notice>}
              {Object.entries(m.files).map(([f, ok]) => <div key={f} className="flex items-center justify-between"><code className="text-xs">{f}</code><Badge tone={ok ? 'green' : 'red'}>{ok ? 'Có' : 'Thiếu'}</Badge></div>)}
              {m.load_seconds !== null && <p className="text-xs text-muted">Tải xong lúc {m.loaded_at} ({m.load_seconds}s)</p>}

              <div className="border-t border-line pt-3">
                <div className="flex items-center justify-between"><span className="text-muted">Chống giả mạo</span>
                  <Badge tone={m.antispoof.state === 'off' ? 'gray' : m.antispoof.state === 'ready' ? 'green' : m.antispoof.state === 'missing_model' ? 'red' : 'amber'}>{m.antispoof.state === 'off' ? 'Tắt' : m.antispoof.state === 'ready' ? 'Sẵn sàng' : m.antispoof.state === 'missing_model' ? 'Thiếu model' : m.antispoof.state === 'experimental' ? 'Thử nghiệm' : 'Đang tải'}</Badge></div>
                <p className="mt-1 text-xs text-muted">{m.antispoof.text}</p>
                <p className="mt-1 text-xs text-muted">Model MiniFASNet: {m.antispoof.has_model ? 'đã có' : 'chưa có'} — <code className="break-all">{m.antispoof.model_path}</code></p>
              </div>
            </>)}
          </div>
        </Card>
        <Card>
          <CardHeader title="Môi trường" icon={<Cpu className="size-5" />} />
          <div className="space-y-2 p-5 text-sm">
            {!sys.data ? <Spinner /> : (<>
              <div className="flex justify-between gap-2"><span className="text-muted">Python</span><span className="font-mono">{sys.data.python}</span></div>
              {Object.entries(sys.data.packages).map(([k, v]) => <div key={k} className="flex justify-between gap-2"><span className="text-muted">{k}</span><span className="font-mono">{(v as string) ?? 'chưa cài'}</span></div>)}
              <div className="border-t border-line pt-3">
                <p className="mb-2 flex items-center gap-1.5 font-semibold"><FolderOpen className="size-4 text-primary" /> Thư mục dữ liệu</p>
                {Object.entries(sys.data.paths).map(([k, v]) => <div key={k} className="mb-1.5"><p className="text-xs text-muted">{k}</p><code className="block break-all text-xs">{v as string}</code></div>)}
              </div>
            </>)}
          </div>
        </Card>
      </div>
    </div>
  )
}
