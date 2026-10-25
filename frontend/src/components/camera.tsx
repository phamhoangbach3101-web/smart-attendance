import { useCallback, useEffect, useRef, useState } from 'react'
import { CameraOff, Loader2, ShieldAlert, VideoOff } from 'lucide-react'
import type { FaceBox } from '../api'
import { Button } from './ui'

export type CamState = 'idle' | 'requesting' | 'live' | 'denied' | 'notfound' | 'busy' | 'insecure' | 'error'

const CAM_KEY = 'sa.cameraDevice'

/** Browser webcam: permission flow, device choice, track cleanup, JPEG capture. */
export function useBrowserCamera() {
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const [state, setState] = useState<CamState>('idle')
  const [error, setError] = useState<string | null>(null)
  const [devices, setDevices] = useState<MediaDeviceInfo[]>([])
  const [deviceId, setDeviceId] = useState<string>(() => { try { return localStorage.getItem(CAM_KEY) || '' } catch { return '' } })

  const refreshDevices = useCallback(async () => {
    try {
      const all = await navigator.mediaDevices.enumerateDevices()
      setDevices(all.filter((d) => d.kind === 'videoinput'))
    } catch { /* ignore */ }
  }, [])

  const stop = useCallback(() => {
    streamRef.current?.getTracks().forEach((t) => t.stop())
    streamRef.current = null
    if (videoRef.current) videoRef.current.srcObject = null
    setState('idle')
  }, [])

  const start = useCallback(async (id?: string) => {
    if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
      setState('insecure')
      setError('Trình duyệt chỉ cho dùng camera trên http://127.0.0.1 / localhost hoặc HTTPS.')
      return false
    }
    streamRef.current?.getTracks().forEach((t) => t.stop())
    setState('requesting')
    setError(null)
    const want = id ?? deviceId
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { ...(want ? { deviceId: { exact: want } } : { facingMode: 'user' }), width: { ideal: 1280 }, height: { ideal: 720 } },
        audio: false,
      })
      streamRef.current = stream
      const track = stream.getVideoTracks()[0]
      track.addEventListener('ended', () => { setState('error'); setError('Camera bị ngắt kết nối.') })
      const actual = track.getSettings().deviceId
      if (actual) { setDeviceId(actual); try { localStorage.setItem(CAM_KEY, actual) } catch { /* ignore */ } }
      if (videoRef.current) {
        videoRef.current.srcObject = stream
        await videoRef.current.play().catch(() => {})
      }
      setState('live')
      refreshDevices()
      return true
    } catch (e: any) {
      const name = e?.name
      if (name === 'NotAllowedError' || name === 'SecurityError') { setState('denied'); setError('Bạn đã từ chối quyền camera.') }
      else if (name === 'NotFoundError' || name === 'OverconstrainedError') {
        if (want) { try { localStorage.removeItem(CAM_KEY) } catch { /* ignore */ } setDeviceId(''); return start('') }
        setState('notfound'); setError('Không tìm thấy camera nào trên thiết bị.')
      } else if (name === 'NotReadableError' || name === 'AbortError') { setState('busy'); setError('Camera đang được ứng dụng khác sử dụng (Zoom, Teams, ứng dụng desktop…).') }
      else { setState('error'); setError(`Không mở được camera: ${e?.message || name || e}`) }
      return false
    }
  }, [deviceId, refreshDevices])

  useEffect(() => {
    refreshDevices()
    navigator.mediaDevices?.addEventListener?.('devicechange', refreshDevices)
    return () => {
      navigator.mediaDevices?.removeEventListener?.('devicechange', refreshDevices)
      streamRef.current?.getTracks().forEach((t) => t.stop())   // release camera when leaving the page
      streamRef.current = null
    }
  }, [refreshDevices])

  /** Encode the current video frame as JPEG (downscaled to keep uploads small). */
  const capture = useCallback((maxWidth = 960, quality = 0.82): Promise<Blob | null> => {
    const v = videoRef.current
    if (!v || !v.videoWidth || state !== 'live') return Promise.resolve(null)
    const scale = Math.min(1, maxWidth / v.videoWidth)
    const w = Math.round(v.videoWidth * scale)
    const h = Math.round(v.videoHeight * scale)
    const c = canvasRef.current ?? (canvasRef.current = document.createElement('canvas'))
    c.width = w
    c.height = h
    c.getContext('2d')!.drawImage(v, 0, 0, w, h)
    return new Promise((res) => c.toBlob((b) => res(b), 'image/jpeg', quality))
  }, [state])

  return { videoRef, state, error, devices, deviceId, setDeviceId, start, stop, capture }
}

const FACE_STYLE: Record<FaceBox['state'], { color: string; text: string }> = {
  recognized: { color: '#16C784', text: 'Đã nhận diện' },
  unknown: { color: '#EF4444', text: 'Người lạ' },
  multiple: { color: '#F59E0B', text: 'Nhiều khuôn mặt' },
  unverifiable: { color: '#F97316', text: 'Không thể xác minh' },
  spoof: { color: '#DC2626', text: 'Giả mạo — bị từ chối' },
  pending: { color: '#3B82F6', text: 'Đang xử lý' },
  detected: { color: '#3B82F6', text: 'Đã phát hiện' },
  ignored: { color: '#9CA3AF', text: 'Bỏ qua' },
}

/** SVG overlay sized in frame pixels; preserveAspectRatio matches object-contain. */
export function FaceOverlay({ faces, width, height, mirrored }: { faces: FaceBox[]; width: number; height: number; mirrored?: boolean }) {
  if (!width || !height) return null
  const fs = Math.max(12, Math.round(width / 42))
  return (
    <svg className="pointer-events-none absolute inset-0 size-full" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="xMidYMid meet">
      {faces.map((f, i) => {
        const st = FACE_STYLE[f.state] ?? FACE_STYLE.pending
        const [x0, y, w, h] = f.box
        const x = mirrored ? width - x0 - w : x0
        const label = f.state === 'recognized' ? f.label : `${st.text}${f.score !== undefined && f.state !== 'multiple' ? ` · ${f.score.toFixed(2)}` : ''}`
        const tw = label.length * fs * 0.56 + 16
        const ty = y - fs - 12 < 0 ? y + h : y - fs - 12
        return (
          <g key={i}>
            <rect x={x} y={y} width={w} height={h} rx={10} fill="none" stroke={st.color} strokeWidth={Math.max(3, width / 300)} strokeDasharray={f.state === 'ignored' ? '8 6' : undefined} />
            <rect x={x} y={ty} width={Math.min(tw, width - x)} height={fs + 12} rx={8} fill={st.color} />
            <text x={x + 8} y={ty + fs + 2} fill="#fff" fontSize={fs} fontWeight={600} fontFamily="Be Vietnam Pro, Segoe UI, sans-serif">{label}</text>
          </g>
        )
      })}
    </svg>
  )
}

/** Placeholder shown instead of the video when the camera is not live. */
export function CameraPlaceholder({ state, error, onStart }: { state: CamState; error: string | null; onStart: () => void }) {
  const box = 'absolute inset-0 flex flex-col items-center justify-center gap-3 p-6 text-center text-white'
  if (state === 'requesting') return <div className={box}><Loader2 className="size-8 animate-spin" /><p className="font-medium">Đang xin quyền camera…</p><p className="text-sm text-white/70">Chọn “Cho phép” trên hộp thoại của trình duyệt.</p></div>
  if (state === 'denied') return (
    <div className={box}><ShieldAlert className="size-9 text-amber-300" /><p className="font-semibold">Quyền camera bị từ chối</p>
      <p className="max-w-sm text-sm text-white/75">Bấm biểu tượng ổ khóa/camera trên thanh địa chỉ → cho phép Camera → bấm “Thử lại”.</p>
      <Button size="sm" onClick={onStart}>Thử lại</Button></div>)
  if (state === 'notfound' || state === 'busy' || state === 'insecure' || state === 'error') return (
    <div className={box}><VideoOff className="size-9 text-red-300" /><p className="font-semibold">{state === 'notfound' ? 'Không tìm thấy camera' : state === 'busy' ? 'Camera đang bận' : 'Không mở được camera'}</p>
      <p className="max-w-sm text-sm text-white/75">{error}</p>
      {state !== 'insecure' && <Button size="sm" onClick={onStart}>Thử lại</Button>}</div>)
  return (
    <div className={box}><CameraOff className="size-9 text-white/60" /><p className="font-medium">Camera đang tắt</p>
      <Button onClick={onStart}>Bật camera</Button></div>)
}
