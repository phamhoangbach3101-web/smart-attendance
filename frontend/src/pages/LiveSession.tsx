import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { AlertTriangle, ArrowLeft, Camera, CameraOff, CheckCircle2, Clock, Loader2, Power, RotateCcw, ScanFace, ShieldCheck, ShieldOff, UserPlus, Users, Video, XCircle } from 'lucide-react'
import { api, ApiError, type FrameResult, type RecordItem, type Session, type Settings } from '../api'
import { CameraPlaceholder, FaceOverlay, useBrowserCamera } from '../components/camera'
import { useHealth } from '../components/Layout'
import { Badge, Button, Card, ConfirmDialog, ErrorBox, Notice, Spinner, Toggle, useToast, type Tone } from '../components/ui'
import { cx, fmtDuration, fmtScore, fmtTime, useAsync, useInterval } from '../lib'

const STATUS_TONE: Record<string, Tone> = {
  recognized: 'green', already_recorded: 'green', preview: 'blue', no_face: 'gray', multiple_faces: 'amber',
  unknown: 'red', ambiguous: 'amber', unverifiable: 'amber', spoof_rejected: 'red', spoof_error: 'red',
  session_closed: 'gray', no_students: 'amber', model_loading: 'amber', model_unavailable: 'red', invalid_frame: 'red', error: 'red',
}
const RESULT_TIMEOUT_MS = 4000

function useCountdown(session: Session | null) {
  // Remaining time comes from the server; we only interpolate locally between polls.
  const [now, setNow] = useState(Date.now())
  const base = useRef<{ at: number; remaining: number | null }>({ at: Date.now(), remaining: null })
  useEffect(() => { base.current = { at: Date.now(), remaining: session?.remaining_seconds ?? null } }, [session])
  useInterval(() => setNow(Date.now()), 1000)
  if (!session || session.state !== 'active' || base.current.remaining === null) return null
  return Math.max(0, base.current.remaining - Math.floor((now - base.current.at) / 1000))
}

export default function LiveSession() {
  const { id } = useParams()
  const sid = Number(id)
  const nav = useNavigate()
  const toast = useToast()
  const { health } = useHealth()
  const sessionQ = useAsync(() => api.get<Session>(`/api/sessions/${sid}`), [sid])
  const recordsQ = useAsync(() => api.get<{ session: Session; records: RecordItem[] }>(`/api/sessions/${sid}/records`), [sid])
  const settingsQ = useAsync(() => api.get<Settings>('/api/settings'))
  const session = sessionQ.data
  const remaining = useCountdown(session)
  const active = session?.state === 'active' && remaining !== 0
  const isRtsp = session?.camera_type === 'rtsp'

  useInterval(() => { sessionQ.reload(true); recordsQ.reload(true) }, active ? 4000 : null)
  useEffect(() => { if (remaining === 0) { sessionQ.reload(true); recordsQ.reload(true) } }, [remaining])  // eslint-disable-line

  const [autoRecognize, setAutoRecognize] = useState(true)
  const [result, setResult] = useState<FrameResult | null>(null)
  const [wsState, setWsState] = useState<'off' | 'connecting' | 'open' | 'closed'>('off')
  const [confirmEnd, setConfirmEnd] = useState(false)
  const [ending, setEnding] = useState(false)
  const [tab, setTab] = useState<'present' | 'absent'>('present')
  const [flash, setFlash] = useState<string | null>(null)

  const cam = useBrowserCamera()
  const wsRef = useRef<WebSocket | null>(null)
  const frameId = useRef(0)
  const inflight = useRef<{ id: number; at: number } | null>(null)
  const lastShown = useRef(0)
  const generation = useRef(0)       // bumped when camera stops: late results are discarded
  const autoRef = useRef(autoRecognize)
  autoRef.current = autoRecognize

  const onResult = useCallback((r: FrameResult, gen: number) => {
    if (gen !== generation.current || r.session_id !== sid || r.frame_id < lastShown.current) return
    lastShown.current = r.frame_id
    setResult(r)
    if (r.status === 'recognized' && r.student) {
      setFlash(`${r.student.student_name} (${r.student.student_id})`)
      setTimeout(() => setFlash(null), 2500)
      recordsQ.reload(true); sessionQ.reload(true)
    }
    if (r.status === 'session_closed') { sessionQ.reload(true); recordsQ.reload(true) }
  }, [sid]) // eslint-disable-line

  // ----- browser webcam → WebSocket (one frame in flight, newest wins on the server)
  useEffect(() => {
    if (isRtsp || cam.state !== 'live' || !active) return
    const gen = ++generation.current
    setWsState('connecting')
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    const ws = new WebSocket(`${proto}://${location.host}/ws/sessions/${sid}`)
    ws.binaryType = 'arraybuffer'
    wsRef.current = ws
    ws.onopen = () => setWsState('open')
    ws.onclose = () => { if (gen === generation.current) setWsState('closed') }
    ws.onmessage = (ev) => {
      try {
        const r = JSON.parse(ev.data)
        if (r.type === 'error') { toast('error', r.message); return }
        if (inflight.current && r.frame_id >= inflight.current.id) inflight.current = null
        onResult(r, gen)
      } catch { /* ignore */ }
    }
    let stopped = false
    let lastSent = 0
    const fps = Math.min(10, Math.max(1, settingsQ.data?.frame_rate ?? 4))
    const loop = async () => {
      while (!stopped) {
        await new Promise((r) => setTimeout(r, 60))
        if (ws.readyState !== WebSocket.OPEN) continue
        const now = performance.now()
        if (inflight.current && now - inflight.current.at < RESULT_TIMEOUT_MS) continue
        if (now - lastSent < 1000 / fps) continue
        const blob = await cam.capture(960, 0.8)
        if (!blob || stopped) continue
        const fid = ++frameId.current
        const head = new Uint8Array(5)
        new DataView(head.buffer).setUint32(0, fid, true)
        head[4] = autoRef.current ? 1 : 0
        const payload = new Uint8Array(5 + blob.size)
        payload.set(head, 0)
        payload.set(new Uint8Array(await blob.arrayBuffer()), 5)
        if (stopped || ws.readyState !== WebSocket.OPEN) continue
        ws.send(payload)
        inflight.current = { id: fid, at: now }
        lastSent = now
      }
    }
    loop()
    return () => { stopped = true; generation.current++; inflight.current = null; ws.close(); wsRef.current = null; setWsState('off') }
  }, [cam.state, active, isRtsp, sid, settingsQ.data?.frame_rate]) // eslint-disable-line

  // stop the webcam as soon as the session is no longer active
  useEffect(() => { if (!active && cam.state === 'live') { cam.stop(); setResult(null) } }, [active]) // eslint-disable-line

  // ----- RTSP: server-side worker; poll its newest result
  const [rtsp, setRtsp] = useState<any>(null)
  const [rtspUrl, setRtspUrl] = useState('')
  const [rtspBusy, setRtspBusy] = useState(false)
  const [streamKey, setStreamKey] = useState(0)
  useInterval(async () => {
    try {
      const st = await api.get<any>(`/api/sessions/${sid}/rtsp/status`)
      setRtsp(st)
      if (st.result) onResult(st.result, generation.current)
    } catch { /* ignore */ }
  }, isRtsp ? 400 : null)
  const rtspStart = async (useSaved: boolean) => {
    setRtspBusy(true)
    try {
      await api.post(`/api/sessions/${sid}/rtsp/start`, { url: useSaved ? null : rtspUrl.trim(), use_saved: useSaved, record: autoRecognize })
      setStreamKey((k) => k + 1); lastShown.current = 0
    } catch (e) { toast('error', (e as ApiError).message) } finally { setRtspBusy(false) }
  }
  const rtspStop = async () => { generation.current++; await api.post(`/api/sessions/${sid}/rtsp/stop`).catch(() => {}); setRtsp(null); setResult(null) }
  useEffect(() => { if (isRtsp && rtsp && rtsp.state !== 'stopped') api.patch(`/api/sessions/${sid}/rtsp`, { record: autoRecognize }).catch(() => {}) }, [autoRecognize]) // eslint-disable-line

  const toggleCamera = () => {
    if (cam.state === 'live' || cam.state === 'requesting') { generation.current++; cam.stop(); setResult(null) }
    else cam.start()
  }

  const endSession = async () => {
    setEnding(true)
    try {
      generation.current++
      cam.stop()
      if (isRtsp) await api.post(`/api/sessions/${sid}/rtsp/stop`).catch(() => {})
      await api.post(`/api/sessions/${sid}/end`)
      toast('success', 'Đã kết thúc phiên. Báo cáo đã được chốt từ SQLite.')
      setConfirmEnd(false)
      sessionQ.reload(true); recordsQ.reload(true)
    } catch (e) { toast('error', (e as ApiError).message) } finally { setEnding(false) }
  }
  const reopen = async () => {
    try {
      await api.post(`/api/sessions/${sid}/reopen`, { duration_minutes: session?.duration_minutes ?? null, camera_type: session?.camera_type ?? 'browser' })
      toast('success', 'Đã mở lại phiên')
      sessionQ.reload(true); recordsQ.reload(true)
    } catch (e) { toast('error', (e as ApiError).message) }
  }

  const records = recordsQ.data?.records ?? []
  const present = useMemo(() => records.filter((r) => r.status === 'present'), [records])
  const absent = useMemo(() => records.filter((r) => r.status !== 'present'), [records])

  if (sessionQ.error && !session) return <ErrorBox error={sessionQ.error} onRetry={() => sessionQ.reload()} />
  if (!session) return <Spinner />

  const modelReady = health?.models.state === 'ready'
  const spoof = health?.models.antispoof
  const camLive = isRtsp ? rtsp?.state === 'live' : cam.state === 'live'
  const frameW = result?.width ?? 0
  const frameH = result?.height ?? 0
  const faces = camLive && result ? result.faces : []
  const tone = result ? STATUS_TONE[result.status] ?? 'gray' : 'gray'

  return (
    <div className="space-y-4">
      {/* Session header */}
      <Card className="flex flex-wrap items-center gap-3 p-4">
        <Button variant="ghost" size="sm" aria-label="Quay lại" onClick={() => nav('/attendance')}><ArrowLeft className="size-5" /></Button>
        <div className="min-w-0 flex-1">
          <p className="truncate text-lg font-bold">{session.class_name} · {session.subject} · Slot {session.slot}</p>
          <p className="text-xs text-muted">Ngày {session.date.split('-').reverse().join('/')} · bắt đầu {fmtTime(session.started_at)} · {isRtsp ? 'Camera IP (RTSP)' : 'Webcam trình duyệt'}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {active ? <Badge tone="green" dot>Đang mở</Badge> : <Badge tone="gray">Đã kết thúc</Badge>}
          <span className={cx('inline-flex items-center gap-1.5 rounded-xl px-3 py-2 text-sm font-bold tabular-nums',
            !active ? 'bg-gray-100 text-gray-500' : remaining === null ? 'bg-primary-light text-primary-dark' : remaining < 60 ? 'bg-danger-light text-red-700' : remaining < 180 ? 'bg-warn-light text-amber-700' : 'bg-primary-light text-primary-dark')}>
            <Clock className="size-4" />
            {!active ? 'Hết giờ / đã chốt' : remaining === null ? 'Không giới hạn' : `Còn ${fmtDuration(remaining)}`}
          </span>
          {active && <Button variant="danger" size="sm" icon={<Power className="size-4" />} onClick={() => setConfirmEnd(true)}>Kết thúc phiên</Button>}
        </div>
      </Card>

      {!active && (
        <Notice tone="gray" title="Phiên đã kết thúc" icon={<CheckCircle2 className="size-5 text-primary" />}>
          Không nhận thêm kết quả nhận diện. <button className="font-semibold text-primary underline" onClick={reopen}><RotateCcw className="inline size-3.5" /> Mở lại phiên</button> hoặc{' '}
          <Link className="font-semibold text-primary underline" to={`/reports?date_from=${session.date}&date_to=${session.date}&class_name=${session.class_name}&subject=${session.subject}&slot=${session.slot}`}>xem báo cáo</Link>.
        </Notice>
      )}

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.75fr)_minmax(320px,1fr)]">
        {/* Camera column */}
        <div className="space-y-3">
          <Card className="overflow-hidden p-0">
            <div className="relative aspect-video w-full bg-gray-900">
              {isRtsp ? (
                rtsp && rtsp.state !== 'stopped' && rtsp.state !== 'error' ? (
                  <>
                    <img key={streamKey} src={`/api/sessions/${sid}/rtsp/stream?k=${streamKey}`} alt="RTSP" className="absolute inset-0 size-full object-contain" />
                    {rtsp.state !== 'live' && <div className="absolute inset-0 flex items-center justify-center gap-2 text-white"><Loader2 className="size-6 animate-spin" /> {rtsp.state === 'reconnecting' ? 'Mất kết nối, đang thử lại…' : 'Đang kết nối camera…'}</div>}
                  </>
                ) : (
                  <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 p-6 text-center text-white">
                    <Video className="size-9 text-white/60" />
                    <p className="font-semibold">{rtsp?.state === 'error' ? 'Không kết nối được camera IP' : 'Camera IP chưa chạy'}</p>
                    {rtsp?.error && <p className="max-w-md text-sm text-white/75">{rtsp.error}</p>}
                  </div>
                )
              ) : (
                <>
                  <video ref={cam.videoRef} playsInline muted className={cx('absolute inset-0 size-full -scale-x-100 object-contain', cam.state !== 'live' && 'invisible')} />
                  {cam.state !== 'live' && (active ? <CameraPlaceholder state={cam.state} error={cam.error} onStart={() => cam.start()} />
                    : <div className="absolute inset-0 flex items-center justify-center text-white/70">Phiên đã kết thúc</div>)}
                </>
              )}
              {camLive && <FaceOverlay faces={faces} width={frameW} height={frameH} mirrored={!isRtsp} />}
              {flash && (
                <div className="absolute inset-x-0 top-4 flex justify-center px-4">
                  <div className="flex animate-slide-up items-center gap-2 rounded-2xl bg-primary px-4 py-2.5 font-semibold text-white shadow-pop"><CheckCircle2 className="size-5" /> Đã điểm danh: {flash}</div>
                </div>
              )}
              {camLive && (
                <div className="absolute left-3 top-3 flex flex-wrap gap-1.5">
                  <span className="inline-flex items-center gap-1.5 rounded-full bg-black/55 px-2.5 py-1 text-xs font-semibold text-white"><span className="size-2 animate-pulse rounded-full bg-red-500" /> LIVE</span>
                  {!isRtsp && wsState !== 'open' && <span className="rounded-full bg-amber-500/90 px-2.5 py-1 text-xs font-semibold text-white">{wsState === 'connecting' ? 'Đang kết nối máy chủ…' : 'Mất kết nối máy chủ'}</span>}
                </div>
              )}
            </div>

            {/* Controls */}
            <div className="flex flex-wrap items-center gap-2 border-t border-line p-3">
              {isRtsp ? (
                rtsp && rtsp.state !== 'stopped' && rtsp.state !== 'error'
                  ? <Button variant="secondary" icon={<CameraOff className="size-4" />} onClick={rtspStop}>Tắt camera</Button>
                  : <Button icon={<Camera className="size-4" />} disabled={!active || !settingsQ.data?.has_rtsp_url} loading={rtspBusy} onClick={() => rtspStart(true)}>Kết nối camera đã lưu</Button>
              ) : (
                <Button variant={cam.state === 'live' ? 'secondary' : 'primary'} disabled={!active} icon={cam.state === 'live' ? <CameraOff className="size-4" /> : <Camera className="size-4" />} onClick={toggleCamera}>
                  {cam.state === 'live' ? 'Tắt camera' : 'Bật camera'}
                </Button>
              )}
              {!isRtsp && cam.devices.length > 1 && (
                <select className="input h-11 w-auto max-w-[220px]" value={cam.deviceId} onChange={(e) => { cam.setDeviceId(e.target.value); if (cam.state === 'live') cam.start(e.target.value) }}>
                  {cam.devices.map((d, i) => <option key={d.deviceId} value={d.deviceId}>{d.label || `Camera ${i + 1}`}</option>)}
                </select>
              )}
              <div className="rounded-xl border border-line px-3 py-1.5">
                <Toggle checked={autoRecognize} onChange={setAutoRecognize} disabled={!active} label={<span className="text-sm">Tự động nhận diện</span>} />
              </div>
              <Link to={`/students/enroll?class=${encodeURIComponent(session.class_name)}&back=/attendance/${sid}`} className="ml-auto">
                <Button variant="soft" icon={<UserPlus className="size-4" />}>Đăng ký sinh viên</Button>
              </Link>
            </div>
            {isRtsp && active && (!rtsp || rtsp.state === 'stopped' || rtsp.state === 'error') && (
              <div className="flex flex-col gap-2 border-t border-line p-3 sm:flex-row">
                <input className="input font-mono text-sm" placeholder="rtsp://user:password@192.168.1.10:554/stream" value={rtspUrl} onChange={(e) => setRtspUrl(e.target.value)} autoComplete="off" />
                <Button loading={rtspBusy} disabled={!/^rtsps?:\/\/\S+$/i.test(rtspUrl.trim())} onClick={() => rtspStart(false)}>Kết nối</Button>
              </div>
            )}
          </Card>

          {/* Status strip */}
          <div className="grid gap-3 sm:grid-cols-3">
            <div className={cx('card flex items-start gap-3 p-4 sm:col-span-2', tone === 'green' && 'border-primary/40 bg-primary-light/40', tone === 'red' && 'border-red-200 bg-danger-light/40', tone === 'amber' && 'border-amber-200 bg-warn-light/50')}>
              {tone === 'green' ? <CheckCircle2 className="mt-0.5 size-5 shrink-0 text-primary" /> : tone === 'red' ? <XCircle className="mt-0.5 size-5 shrink-0 text-danger" /> : tone === 'amber' ? <AlertTriangle className="mt-0.5 size-5 shrink-0 text-warn" /> : <ScanFace className="mt-0.5 size-5 shrink-0 text-muted" />}
              <div className="min-w-0">
                <p className="font-semibold">{!camLive ? 'Camera chưa bật' : result ? result.message : 'Đang chờ khung hình đầu tiên…'}</p>
                <p className="mt-0.5 text-xs text-muted">
                  {!modelReady ? (health?.models.state === 'error' ? 'Model không khả dụng — xem Cài đặt.' : 'Model đang tải…')
                    : result?.student ? <>Điểm tương đồng (cosine) <b>{fmtScore(result.student.score)}</b> · chênh lệch với người kế tiếp {fmtScore(result.student.margin)} — không phải xác suất.</>
                      : autoRecognize ? 'Chỉ một người đứng trước camera, nhìn thẳng.' : 'Tự động nhận diện đang tắt — chỉ hiển thị khung mặt.'}
                </p>
              </div>
            </div>
            <div className="card flex items-start gap-3 p-4">
              {spoof?.state === 'off' ? <ShieldOff className="mt-0.5 size-5 shrink-0 text-gray-400" /> : spoof?.state === 'missing_model' ? <ShieldOff className="mt-0.5 size-5 shrink-0 text-danger" /> : <ShieldCheck className="mt-0.5 size-5 shrink-0 text-primary" />}
              <div className="min-w-0 text-sm">
                <p className="font-semibold">Chống giả mạo</p>
                <p className="text-xs text-muted">{spoof?.text ?? '—'}</p>
                {result?.antispoof && result.antispoof.state !== 'off' && <p className="mt-1 text-xs font-semibold">Lần cuối: {result.antispoof.state === 'live' ? 'Xác minh thành công' : result.antispoof.state === 'spoof' ? 'Bị từ chối' : 'Không thể xác minh'}</p>}
              </div>
            </div>
          </div>
        </div>

        {/* Attendance column */}
        <Card className="flex max-h-[calc(100vh-140px)] flex-col self-start overflow-hidden xl:sticky xl:top-20">
          <div className="grid grid-cols-3 gap-2 p-4">
            <div className="rounded-2xl bg-primary-light p-3 text-center"><p className="text-2xl font-bold text-primary-dark">{session.present_count}</p><p className="text-xs font-medium text-primary-dark/80">Có mặt</p></div>
            <div className="rounded-2xl bg-danger-light/70 p-3 text-center"><p className="text-2xl font-bold text-red-700">{session.absent_count ?? '—'}</p><p className="text-xs font-medium text-red-700/80">Vắng</p></div>
            <div className="rounded-2xl bg-gray-100 p-3 text-center"><p className="text-2xl font-bold text-gray-700">{session.roster_count}</p><p className="text-xs font-medium text-gray-500">Sĩ số phiên</p></div>
          </div>
          <div className="flex gap-1 border-y border-line px-4 py-2">
            {(['present', 'absent'] as const).map((t) => (
              <button key={t} onClick={() => setTab(t)} className={cx('flex-1 rounded-xl py-2 text-sm font-semibold transition', tab === t ? 'bg-primary-light text-primary-dark' : 'text-muted hover:bg-gray-50')}>
                {t === 'present' ? `Vừa ghi nhận (${present.length})` : `Chưa điểm danh (${absent.length})`}
              </button>
            ))}
          </div>
          <div className="min-h-[200px] flex-1 overflow-y-auto p-2">
            {recordsQ.error ? <ErrorBox error={recordsQ.error} className="m-2" /> : !recordsQ.data ? <Spinner /> :
              (tab === 'present' ? present : absent).length === 0 ? (
                <div className="flex flex-col items-center gap-2 py-10 text-center text-sm text-muted">
                  <Users className="size-8 text-primary/50" />
                  {tab === 'present' ? 'Chưa có sinh viên nào được ghi nhận.' : session.roster_count ? 'Tất cả sinh viên đã có mặt 🎉' : 'Lớp chưa có sinh viên đăng ký.'}
                </div>
              ) : (
                <ul>
                  {(tab === 'present' ? present : absent).map((r) => (
                    <li key={r.student_id} className="flex animate-fade-in items-center gap-3 rounded-xl px-3 py-2.5 hover:bg-gray-50">
                      <span className={cx('grid size-9 shrink-0 place-items-center rounded-full text-sm font-bold', r.status === 'present' ? 'bg-primary-light text-primary-dark' : 'bg-gray-100 text-gray-500')}>
                        {r.student_name.split(' ').pop()?.[0] ?? '?'}
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm font-semibold">{r.student_name}</span>
                        <span className="block text-xs text-muted">{r.student_id}</span>
                      </span>
                      {r.status === 'present'
                        ? <span className="text-right text-xs"><span className="block font-semibold text-primary-dark">{fmtTime(r.timestamp)}</span><span className="text-muted">{fmtScore(r.confidence)}</span></span>
                        : <Badge tone={r.status === 'absent' ? 'red' : 'gray'}>{r.status === 'absent' ? 'Vắng' : 'Không rõ'}</Badge>}
                    </li>
                  ))}
                </ul>
              )}
          </div>
        </Card>
      </div>

      <ConfirmDialog open={confirmEnd} title="Kết thúc phiên điểm danh?" confirmLabel="Kết thúc phiên" danger loading={ending}
        message={<>Sau khi kết thúc, máy chủ từ chối mọi kết quả nhận diện đến muộn. Hiện có <b>{session.present_count}/{session.roster_count}</b> sinh viên có mặt. Bạn vẫn có thể mở lại phiên sau.</>}
        onClose={() => setConfirmEnd(false)} onConfirm={endSession} />
    </div>
  )
}
