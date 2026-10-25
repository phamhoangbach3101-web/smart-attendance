import { useState, useRef, useEffect } from 'react'
import {
  AlertTriangle,
  ArrowRight,
  Check,
  CheckCircle2,
  Download,
  FileSpreadsheet,
  HelpCircle,
  Search,
  UploadCloud,
} from 'lucide-react'
import { api, ApiError } from '../api'
import { Badge, Button, Modal, useToast } from './ui'
import { cx } from '../lib'

interface PreviewRow {
  row_index: number
  student_id: string
  full_name: string
  class_code: string
  has_image: boolean
  image_preview: string | null
  det_score: number | null
  face_status: string
  face_message: string
  db_status: 'new' | 'already_in_class' | 'exists_in_other_class'
  existing_class: string | null
  existing_student_id: number | null
  action: 'create' | 'update' | 'skip' | 'error'
  error: string | null
}

interface PreviewSummary {
  total_rows: number
  new_students: number
  already_in_class: number
  exists_in_other_class: number
  valid_face: number
  missing_face: number
  issues_count: number
  classes: string[]
}

interface CommitSummary {
  total: number
  created: number
  updated: number
  skipped: number
  failed: number
}

interface Props {
  open: boolean
  onClose: () => void
  onSuccess: () => void
  currentClass?: string
}

export function BatchImportModal({ open, onClose, onSuccess, currentClass }: Props) {
  const toast = useToast()
  const [step, setStep] = useState<'upload' | 'preview' | 'result'>('upload')
  const [file, setFile] = useState<File | null>(null)
  const [busy, setBusy] = useState(false)
  const [sessionToken, setSessionToken] = useState<string | null>(null)
  const [summary, setSummary] = useState<PreviewSummary | null>(null)
  const [rows, setRows] = useState<PreviewRow[]>([])
  const [overrides, setOverrides] = useState<Record<number, 'create' | 'update' | 'skip'>>({})
  const [filter, setFilter] = useState<'all' | 'valid' | 'issues' | 'exists'>('all')
  const [q, setQ] = useState('')
  const [conflictAction, setConflictAction] = useState<'skip' | 'update'>('skip')
  const [targetClass, setTargetClass] = useState<string>(currentClass || '')
  const [classList, setClassList] = useState<Array<{ id: number; name: string }>>([])
  const [resultSummary, setResultSummary] = useState<CommitSummary | null>(null)
  const [resultErrors, setResultErrors] = useState<string[]>([])
  const fileInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (open) {
      if (currentClass) setTargetClass(currentClass)
      api.get<Array<{ id: number; name: string }>>('/api/classes')
        .then(setClassList)
        .catch(() => {})
    }
  }, [open, currentClass])

  const resetAll = () => {
    setStep('upload')
    setFile(null)
    setBusy(false)
    setSessionToken(null)
    setSummary(null)
    setRows([])
    setOverrides({})
    setFilter('all')
    setQ('')
    setConflictAction('skip')
    setResultSummary(null)
    setResultErrors([])
  }

  const handleClose = () => {
    if (busy) return
    resetAll()
    onClose()
  }

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
      toast('success', 'Đã tải file mẫu Excel (.xlsx).')
    } catch (e) {
      toast('error', 'Lỗi tải file mẫu: ' + (e as Error).message)
    }
  }

  const handleFileSelect = (f: File) => {
    if (!f.name.toLowerCase().endsWith('.xlsx') && !f.name.toLowerCase().endsWith('.xls')) {
      toast('error', 'Vui lòng chọn file Excel (.xlsx).')
      return
    }
    setFile(f)
  }

  const handlePreview = async () => {
    if (!file) return
    setBusy(true)
    try {
      const fd = new FormData()
      fd.append('file', file)
      if (targetClass.trim()) {
        fd.append('default_class', targetClass.trim())
      }
      const res = await api.form<{ session_token: string; summary: PreviewSummary; rows: PreviewRow[] }>(
        '/api/students/import/preview',
        fd
      )
      setSessionToken(res.session_token)
      setSummary(res.summary)
      setRows(res.rows)
      // Initialize overrides based on default conflict action
      const initialOverrides: Record<number, 'create' | 'update' | 'skip'> = {}
      res.rows.forEach((r) => {
        if (r.db_status === 'already_in_class') {
          initialOverrides[r.row_index] = 'skip'
        }
      })
      setOverrides(initialOverrides)
      setStep('preview')
    } catch (e) {
      toast('error', (e as ApiError).message || 'Không đọc được file Excel.')
    } finally {
      setBusy(false)
    }
  }

  const handleConflictChange = (strat: 'skip' | 'update') => {
    setConflictAction(strat)
    setOverrides((prev) => {
      const next = { ...prev }
      rows.forEach((r) => {
        if (r.db_status === 'already_in_class') {
          next[r.row_index] = strat
        }
      })
      return next
    })
  }

  const setRowAction = (rowIndex: number, act: 'create' | 'update' | 'skip') => {
    setOverrides((prev) => ({ ...prev, [rowIndex]: act }))
  }

  const handleCommit = async () => {
    if (!sessionToken) return
    setBusy(true)
    try {
      const payloadOverrides: Record<string, string> = {}
      Object.entries(overrides).forEach(([k, v]) => {
        payloadOverrides[k] = v
      })

      const res = await api.post<{ ok: boolean; summary: CommitSummary; errors: string[] }>(
        '/api/students/import/commit',
        {
          session_token: sessionToken,
          overrides: payloadOverrides,
          default_conflict: conflictAction,
          default_class: targetClass.trim() || undefined,
        }
      )

      setResultSummary(res.summary)
      setResultErrors(res.errors || [])
      setStep('result')
      onSuccess()
    } catch (e) {
      toast('error', (e as ApiError).message || 'Lỗi khi ghi nhận dữ liệu.')
    } finally {
      setBusy(false)
    }
  }

  // Filter rows for display
  const filteredRows = rows.filter((r) => {
    const textMatch =
      !q.trim() ||
      r.student_id.toLowerCase().includes(q.toLowerCase()) ||
      r.full_name.toLowerCase().includes(q.toLowerCase()) ||
      r.class_code.toLowerCase().includes(q.toLowerCase())

    if (!textMatch) return false

    if (filter === 'valid') return r.face_status === 'valid' || r.face_status === 'reused_from_db'
    if (filter === 'issues')
      return (
        !!r.error ||
        r.face_status === 'no_face' ||
        r.face_status === 'multiple_faces' ||
        r.face_status === 'missing_photo' ||
        r.face_status === 'multiple_photos_in_row'
      )
    if (filter === 'exists') return r.db_status === 'already_in_class' || r.db_status === 'exists_in_other_class'

    return true
  })

  return (
    <Modal open={open} onClose={handleClose} title="Import sinh viên & đăng ký khuôn mặt từ Excel" size="xl">
      {/* Step 1: Upload */}
      {step === 'upload' && (
        <div className="space-y-5 py-2">
          <div className="flex items-center justify-between rounded-2xl border border-primary/30 bg-primary-light/40 p-4">
            <div className="flex items-center gap-3">
              <FileSpreadsheet className="size-6 text-primary" />
              <div>
                <p className="font-semibold text-ink">File Excel mẫu chuẩn (.xlsx)</p>
                <p className="text-xs text-muted">
                  Bao gồm cột mã SV, họ tên, mã lớp và ô chèn ảnh chân dung trực tiếp.
                </p>
              </div>
            </div>
            <Button size="sm" variant="secondary" icon={<Download className="size-4" />} onClick={downloadTemplate}>
              Tải mẫu Excel
            </Button>
          </div>

          <div
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault()
              if (e.dataTransfer.files?.[0]) handleFileSelect(e.dataTransfer.files[0])
            }}
            onClick={() => fileInputRef.current?.click()}
            className={cx(
              'flex cursor-pointer flex-col items-center justify-center rounded-3xl border-2 border-dashed p-8 text-center transition',
              file ? 'border-primary bg-primary-light/30' : 'border-line hover:border-primary/50 hover:bg-gray-50'
            )}
          >
            <input
              type="file"
              ref={fileInputRef}
              className="hidden"
              accept=".xlsx,.xls"
              onChange={(e) => e.target.files?.[0] && handleFileSelect(e.target.files[0])}
            />
            <div className="grid size-14 place-items-center rounded-2xl bg-primary-light text-primary">
              <UploadCloud className="size-7" />
            </div>
            {file ? (
              <div className="mt-4">
                <p className="text-base font-semibold text-ink">{file.name}</p>
                <p className="text-xs text-muted">{(file.size / 1024).toFixed(1)} KB · Nhấp để đổi file khác</p>
              </div>
            ) : (
              <div className="mt-4">
                <p className="text-base font-semibold text-ink">Kéo thả file Excel vào đây hoặc nhấp để chọn</p>
                <p className="mt-1 text-xs text-muted">Hỗ trợ định dạng .xlsx chứa thông tin và ảnh nhúng</p>
              </div>
            )}
          </div>

          <div className="rounded-2xl border border-line bg-gray-50/70 p-4 space-y-2">
            <label className="block text-xs font-semibold text-ink">
              Mã lớp học mục tiêu (tự động áp dụng nếu file Excel để trống cột lớp):
            </label>
            <div className="flex gap-2">
              <input
                type="text"
                placeholder="Nhập hoặc chọn mã lớp (ví dụ: SE1501, K18...)"
                value={targetClass}
                onChange={(e) => setTargetClass(e.target.value)}
                list="batch-import-classes-list"
                className="input text-xs flex-1"
              />
              <datalist id="batch-import-classes-list">
                {classList.map((c) => (
                  <option key={c.id} value={c.name} />
                ))}
              </datalist>
            </div>
            <p className="text-[11px] text-muted">
              💡 Nếu file Excel của bạn (như file mẫu có ảnh) để trống cột Mã lớp, hệ thống sẽ tự động gán toàn bộ sinh viên vào lớp học này.
            </p>
          </div>

          <div className="rounded-2xl border border-line bg-gray-50/70 p-4 text-xs text-muted space-y-1.5">
            <p className="font-semibold text-ink flex items-center gap-1.5">
              <HelpCircle className="size-4 text-primary" /> Hướng dẫn chèn ảnh trong Excel:
            </p>
            <p>
              1. Mở file mẫu Excel, chọn ô tại cột <b>photo</b> tương ứng với sinh viên.
            </p>
            <p>
              2. Chọn <b>Insert (Chèn) &gt; Pictures (Hình ảnh)</b> &gt; Chọn ảnh chân dung rõ mặt của sinh viên đó.
            </p>
            <p>
              3. Hệ thống sẽ tự động ghép ảnh với đúng dòng dựa trên tọa độ neo của ô Excel.
            </p>
          </div>

          <div className="flex justify-end gap-2 pt-2 border-t border-line">
            <Button variant="secondary" onClick={handleClose}>
              Hủy
            </Button>
            <Button loading={busy} disabled={!file} onClick={handlePreview} icon={<ArrowRight className="size-4" />}>
              Tiếp tục &amp; Xem trước
            </Button>
          </div>
        </div>
      )}

      {/* Step 2: Preview & Reconciliation */}
      {step === 'preview' && summary && (
        <div className="space-y-4">
          {/* Summary Badges */}
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-6">
            <div className="rounded-2xl border border-line bg-gray-50 p-2.5 text-center">
              <span className="block text-xs text-muted">Tổng số dòng</span>
              <span className="text-lg font-bold text-ink">{summary.total_rows}</span>
            </div>
            <div className="rounded-2xl border border-primary/30 bg-primary-light/50 p-2.5 text-center">
              <span className="block text-xs text-primary-dark">Sinh viên mới</span>
              <span className="text-lg font-bold text-primary-dark">{summary.new_students}</span>
            </div>
            <div className="rounded-2xl border border-amber-200 bg-amber-50 p-2.5 text-center">
              <span className="block text-xs text-amber-800">Đã có trong lớp</span>
              <span className="text-lg font-bold text-amber-800">{summary.already_in_class}</span>
            </div>
            <div className="rounded-2xl border border-blue-200 bg-blue-50 p-2.5 text-center">
              <span className="block text-xs text-blue-800">Có ở lớp khác</span>
              <span className="text-lg font-bold text-blue-800">{summary.exists_in_other_class}</span>
            </div>
            <div className="rounded-2xl border border-emerald-200 bg-emerald-50 p-2.5 text-center">
              <span className="block text-xs text-emerald-800">Khuôn mặt hợp lệ</span>
              <span className="text-lg font-bold text-emerald-800">{summary.valid_face}</span>
            </div>
            <div className="rounded-2xl border border-red-200 bg-red-50 p-2.5 text-center">
              <span className="block text-xs text-red-800">Cần lưu ý / Lỗi</span>
              <span className="text-lg font-bold text-red-800">{summary.issues_count}</span>
            </div>
          </div>

          {targetClass && (
            <div className="flex items-center justify-between rounded-xl border border-primary/30 bg-primary-light/40 px-3.5 py-2 text-xs text-ink">
              <span>
                Lớp áp dụng cho các dòng trống mã lớp: <b className="font-bold text-primary-dark">{targetClass}</b>
              </span>
              <span className="text-[11px] text-muted">
                (Tự động điền mã lớp vào hồ sơ sinh viên)
              </span>
            </div>
          )}

          {/* Conflict Strategy & Filter Bar */}
          <div className="flex flex-col gap-3 rounded-2xl border border-line p-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-center gap-2">
              <span className="text-xs font-semibold text-ink">Khi sinh viên đã có trong lớp:</span>
              <div className="inline-flex rounded-xl border border-line p-0.5 bg-gray-100 text-xs font-medium">
                <button
                  type="button"
                  className={cx(
                    'rounded-lg px-2.5 py-1 transition',
                    conflictAction === 'skip' ? 'bg-white shadow-sm font-semibold text-ink' : 'text-muted'
                  )}
                  onClick={() => handleConflictChange('skip')}
                >
                  Bỏ qua (Giữ nguyên)
                </button>
                <button
                  type="button"
                  className={cx(
                    'rounded-lg px-2.5 py-1 transition',
                    conflictAction === 'update' ? 'bg-white shadow-sm font-semibold text-primary' : 'text-muted'
                  )}
                  onClick={() => handleConflictChange('update')}
                >
                  Cập nhật ảnh &amp; tên
                </button>
              </div>
            </div>

            <div className="flex items-center gap-2">
              <div className="relative">
                <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted" />
                <input
                  type="text"
                  placeholder="Lọc mã, tên, lớp…"
                  value={q}
                  onChange={(e) => setQ(e.target.value)}
                  className="input h-8 pl-8 text-xs sm:w-44"
                />
              </div>

              <select
                value={filter}
                onChange={(e) => setFilter(e.target.value as any)}
                className="input h-8 text-xs sm:w-36"
              >
                <option value="all">Tất cả ({rows.length})</option>
                <option value="valid">Ảnh hợp lệ ({summary.valid_face})</option>
                <option value="issues">Cần kiểm tra ({summary.issues_count})</option>
                <option value="exists">Đã có trong DB ({summary.already_in_class + summary.exists_in_other_class})</option>
              </select>
            </div>
          </div>

          {/* Interactive Table */}
          <div className="max-h-[50vh] overflow-y-auto rounded-2xl border border-line">
            <table className="w-full text-left text-xs">
              <thead className="sticky top-0 z-10 bg-gray-50 border-b border-line text-muted font-semibold">
                <tr>
                  <th className="px-3 py-2.5 w-12 text-center">Dòng</th>
                  <th className="px-3 py-2.5 w-16 text-center">Ảnh</th>
                  <th className="px-3 py-2.5">Mã SV</th>
                  <th className="px-3 py-2.5">Họ và tên</th>
                  <th className="px-3 py-2.5">Lớp</th>
                  <th className="px-3 py-2.5">Đối chiếu DB</th>
                  <th className="px-3 py-2.5">Khuôn mặt</th>
                  <th className="px-3 py-2.5 w-32 text-center">Hành động</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line bg-white">
                {filteredRows.map((r) => {
                  const currentAction = overrides[r.row_index] ?? r.action
                  return (
                    <tr
                      key={r.row_index}
                      className={cx(
                        'hover:bg-gray-50/80 transition',
                        r.error ? 'bg-red-50/30' : r.db_status === 'already_in_class' ? 'bg-amber-50/20' : ''
                      )}
                    >
                      <td className="px-3 py-2 text-center font-mono text-muted">{r.row_index}</td>
                      <td className="px-3 py-2 text-center">
                        {r.image_preview ? (
                          <img
                            src={r.image_preview}
                            alt={r.student_id}
                            className="size-11 rounded-xl object-cover border border-line mx-auto shadow-sm"
                          />
                        ) : (
                          <div className="size-11 rounded-xl bg-gray-100 grid place-items-center text-muted font-semibold mx-auto border border-line">
                            {r.student_id ? r.student_id.slice(-2) : '—'}
                          </div>
                        )}
                      </td>
                      <td className="px-3 py-2 font-mono font-bold text-ink">{r.student_id}</td>
                      <td className="px-3 py-2 font-semibold text-ink">{r.full_name}</td>
                      <td className="px-3 py-2">
                        <Badge tone="blue">{r.class_code}</Badge>
                      </td>
                      <td className="px-3 py-2">
                        {r.db_status === 'new' && <Badge tone="green">Mới</Badge>}
                        {r.db_status === 'already_in_class' && <Badge tone="amber">Đã có trong lớp</Badge>}
                        {r.db_status === 'exists_in_other_class' && (
                          <Badge tone="blue">Có ở lớp {r.existing_class}</Badge>
                        )}
                      </td>
                      <td className="px-3 py-2">
                        {r.face_status === 'valid' && (
                          <div>
                            <Badge tone="green">Hợp lệ ({((r.det_score || 0) * 100).toFixed(0)}%)</Badge>
                          </div>
                        )}
                        {r.face_status === 'reused_from_db' && (
                          <div>
                            <Badge tone="blue">Kế thừa</Badge>
                            <span className="block text-[11px] text-muted truncate max-w-[140px]">
                              Từ lớp {r.existing_class}
                            </span>
                          </div>
                        )}
                        {r.face_status === 'missing_photo' && <Badge tone="amber">Thiếu ảnh</Badge>}
                        {r.face_status === 'no_face' && (
                          <div>
                            <Badge tone="red">Không có mặt</Badge>
                            <span className="block text-[10px] text-red-600 truncate max-w-[130px]">
                              {r.face_message}
                            </span>
                          </div>
                        )}
                        {r.face_status === 'multiple_faces' && (
                          <div>
                            <Badge tone="red">Nhiều mặt</Badge>
                            <span className="block text-[10px] text-red-600 truncate max-w-[130px]">
                              {r.face_message}
                            </span>
                          </div>
                        )}
                        {r.face_status === 'multiple_photos_in_row' && (
                          <Badge tone="red">Nhiều ảnh/dòng</Badge>
                        )}
                      </td>
                      <td className="px-3 py-2 text-center">
                        {r.error ? (
                          <span className="text-[11px] font-semibold text-red-600">{r.error}</span>
                        ) : (
                          <select
                            value={currentAction}
                            onChange={(e) => setRowAction(r.row_index, e.target.value as any)}
                            className={cx(
                              'h-7 rounded-lg border px-1.5 text-xs font-semibold focus:outline-none',
                              currentAction === 'create'
                                ? 'border-primary/40 bg-primary-light/40 text-primary-dark'
                                : currentAction === 'update'
                                ? 'border-blue-300 bg-blue-50 text-blue-700'
                                : 'border-gray-200 bg-gray-100 text-gray-600'
                            )}
                          >
                            <option value="create">Thêm mới</option>
                            <option value="update">Cập nhật</option>
                            <option value="skip">Bỏ qua</option>
                          </select>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>

          <div className="flex items-center justify-between pt-2 border-t border-line">
            <Button variant="secondary" onClick={() => setStep('upload')}>
              Chọn file khác
            </Button>
            <div className="flex gap-2">
              <Button variant="secondary" onClick={handleClose}>
                Hủy
              </Button>
              <Button
                loading={busy}
                onClick={handleCommit}
                icon={<Check className="size-4" />}
                className="shadow-sm shadow-primary/30"
              >
                Xác nhận Import ({rows.filter((r) => !r.error && (overrides[r.row_index] ?? r.action) !== 'skip').length}{' '}
                SV)
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Step 3: Result Summary */}
      {step === 'result' && resultSummary && (
        <div className="space-y-5 py-4 text-center">
          <div className="grid size-16 place-items-center rounded-3xl bg-primary-light text-primary mx-auto">
            <CheckCircle2 className="size-8" />
          </div>
          <div>
            <h3 className="text-xl font-bold text-ink">Import hoàn tất!</h3>
            <p className="mt-1 text-sm text-muted">Dữ liệu sinh viên và khuôn mặt đã được cập nhật vào hệ thống.</p>
          </div>

          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 max-w-lg mx-auto">
            <div className="rounded-2xl border border-emerald-200 bg-emerald-50 p-3">
              <span className="block text-xs text-emerald-800">Đã thêm mới</span>
              <span className="text-2xl font-bold text-emerald-800">{resultSummary.created}</span>
            </div>
            <div className="rounded-2xl border border-blue-200 bg-blue-50 p-3">
              <span className="block text-xs text-blue-800">Đã cập nhật</span>
              <span className="text-2xl font-bold text-blue-800">{resultSummary.updated}</span>
            </div>
            <div className="rounded-2xl border border-gray-200 bg-gray-50 p-3">
              <span className="block text-xs text-gray-600">Đã bỏ qua</span>
              <span className="text-2xl font-bold text-gray-700">{resultSummary.skipped}</span>
            </div>
            <div className="rounded-2xl border border-red-200 bg-red-50 p-3">
              <span className="block text-xs text-red-800">Thất bại</span>
              <span className="text-2xl font-bold text-red-800">{resultSummary.failed}</span>
            </div>
          </div>

          {resultErrors.length > 0 && (
            <div className="rounded-2xl border border-red-200 bg-red-50/60 p-4 text-left max-w-lg mx-auto">
              <p className="text-xs font-semibold text-red-800 flex items-center gap-1.5 mb-2">
                <AlertTriangle className="size-4" /> Danh sách lỗi gặp phải ({resultErrors.length}):
              </p>
              <ul className="text-xs text-red-700 space-y-1 max-h-32 overflow-y-auto">
                {resultErrors.map((err, idx) => (
                  <li key={idx}>• {err}</li>
                ))}
              </ul>
            </div>
          )}

          <div className="pt-2">
            <Button onClick={handleClose} className="min-w-[140px]">
              Hoàn tất &amp; Đóng
            </Button>
          </div>
        </div>
      )}
    </Modal>
  )
}
