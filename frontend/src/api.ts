// Typed client for the FastAPI backend. All errors surface as ApiError with the
// backend's Vietnamese message, so pages can show them directly.

export class ApiError extends Error {
  status: number
  code?: string
  details?: any
  constructor(status: number, message: string, code?: string, details?: any) {
    super(message)
    this.status = status
    this.code = code
    this.details = details
  }
}

async function request<T>(method: string, url: string, body?: unknown): Promise<T> {
  let res: Response
  const init: RequestInit = { method, headers: {} }
  if (body instanceof FormData) init.body = body
  else if (body !== undefined) {
    init.body = JSON.stringify(body)
    ;(init.headers as Record<string, string>)['Content-Type'] = 'application/json'
  }
  try {
    res = await fetch(url, init)
  } catch {
    throw new ApiError(0, 'Không kết nối được máy chủ. Kiểm tra cửa sổ chạy ứng dụng (run.ps1) còn mở không.', 'network')
  }
  if (!res.ok) {
    let msg = `Lỗi máy chủ (${res.status})`
    let code: string | undefined
    let details: any
    try {
      const j = await res.json()
      msg = j.detail || msg
      code = j.code
      details = j.details
    } catch { /* not JSON */ }
    throw new ApiError(res.status, msg, code, details)
  }
  const type = res.headers.get('content-type') || ''
  return (type.includes('json') ? res.json() : (res.blob() as any)) as Promise<T>
}

export const api = {
  get: <T>(url: string) => request<T>('GET', url),
  post: <T>(url: string, body?: unknown) => request<T>('POST', url, body ?? {}),
  put: <T>(url: string, body?: unknown) => request<T>('PUT', url, body),
  patch: <T>(url: string, body?: unknown) => request<T>('PATCH', url, body),
  del: <T>(url: string) => request<T>('DELETE', url),
  form: <T>(url: string, form: FormData) => request<T>('POST', url, form),
}

export function qs(params: Record<string, string | number | null | undefined>) {
  const p = new URLSearchParams()
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') p.set(k, String(v))
  })
  const s = p.toString()
  return s ? `?${s}` : ''
}

// ------------------------------------------------------------------ types
export interface ClassItem {
  id: number; name: string; description: string; created_at: string
  student_count: number; course_count: number; session_count: number
}
export interface Course {
  id: number; class_name: string; subject: string; subject_name: string; created_at: string
  session_count: number; last_session_date: string | null; student_count: number
}
export interface Student {
  id: number; class_name: string; student_id: string; full_name: string; folder: string
  photos: string[]; embedding_count: number; face_status: 'enrolled' | 'missing' | 'invalid'
  attendance_count?: number; created_at: string; updated_at: string; warnings?: string[]
}
export type SessionState = 'active' | 'expired' | 'ended'
export interface Session {
  id: number; class_name: string; subject: string; date: string; slot: number
  duration_minutes: number | null; started_at: string; opened_at: string; deadline_at: string | null
  ended_at: string | null; end_reason: string | null; status: string; camera_type: string
  legacy: number; roster_known: number; state: SessionState; remaining_seconds: number | null
  server_time: string; roster_count: number; present_count: number; absent_count: number | null
  created?: boolean; reopened?: boolean
}
export interface RecordItem {
  student_id: string; student_name: string; student_pk: number | null
  timestamp: string | null; confidence: number | null; status: 'present' | 'absent' | 'unknown'
}
export interface FaceBox {
  box: [number, number, number, number]
  role: 'primary' | 'blocker' | 'incidental'
  state: 'recognized' | 'unknown' | 'multiple' | 'unverifiable' | 'spoof' | 'pending' | 'detected' | 'ignored'
  label: string; det_score: number; score?: number
}
export interface FrameResult {
  type?: string; frame_id: number; session_id: number; status: string; message: string
  faces: FaceBox[]; width: number | null; height: number | null
  student: { student_id: string; student_name: string; score: number; margin: number } | null
  attendance: { status: string; timestamp: string | null } | null
  antispoof: { state: string; ok: boolean; live_score?: number | null; experimental?: boolean } | null
  processed_at?: string; dropped?: number
}
export interface ModelStatus {
  state: 'idle' | 'loading' | 'ready' | 'error'; error: string | null; loaded_at: string | null
  load_seconds: number | null; model_dir: string; files: Record<string, boolean>
  antispoof: { mode: string; state: string; text: string; has_model: boolean; model_path: string }
  model_id?: string
  model_name?: string
  revision?: string
  weights_sha256?: string
  device?: string
  embedding_dim?: number
  preprocessing?: string
}
export interface MigrationStatus {
  is_migrated: boolean
  migration_record: any
  total_students: number
  adaface_enrolled: number
  can_rollback: boolean
  db_backups: string[]
}
export interface CalibrationResult {
  validated: boolean
  message: string
  recommended_threshold: number
  default_threshold: number
  genuine_count: number
  impostor_count: number
  genuine_mean?: number
  genuine_min?: number
  impostor_mean?: number
  impostor_max?: number
}
export interface Health {
  ok: boolean; version: string; time: string; models: ModelStatus; migration: any; active_sessions: number
}
export interface Settings {
  adaface_cosine_threshold?: number
  cosine_threshold: number; min_margin: number; detection_threshold: number; preprocessing: boolean
  antispoof_mode: 'off' | 'model' | 'texture_experimental'; antispoof_threshold: number
  frame_rate: number; default_duration_minutes: number; rtsp_url_masked: string; has_rtsp_url: boolean
}
export interface HistorySession extends Omit<Session, 'remaining_seconds' | 'server_time' | 'roster_count' | 'present_count' | 'absent_count'> {
  present: number; absent: number | null; roster: number
}
export interface HistoryRecord {
  session_id: number; date: string; class_name: string; subject: string; slot: number
  student_id: string; student_name: string; status: 'present' | 'absent' | 'unknown'
  timestamp: string | null; score: number | null
}
export interface HistorySummary {
  sessions: number; present: number; absent: number; roster: number; legacy_sessions: number
  records: number; rate: number | null
}
export interface HistoryResponse { sessions: HistorySession[]; records: HistoryRecord[]; summary: HistorySummary }
export interface Dashboard {
  date: string
  totals: { students: number; classes: number; courses: number }
  day: HistorySummary & { checkins: number }
  day_sessions: HistorySession[]
  week: { date: string; sessions: number; checkins: number }[]
  recent: { id: number; student_id: string; student_name: string; class_name: string; subject: string; slot: number; timestamp: string; confidence: number; session_id: number }[]
  active_sessions: Session[]
}
export interface SampleCheck {
  ok: boolean; reason: string | null; message: string; width: number; height: number
  box: [number, number, number, number] | null; det_score?: number
}
