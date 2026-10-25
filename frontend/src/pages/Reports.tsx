import { useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { CalendarCheck, Download, FileSpreadsheet, Filter, Percent, RotateCcw, Search, UserCheck, UserX } from 'lucide-react'
import { api, ApiError, qs, type ClassItem, type Course, type HistoryResponse } from '../api'
import { Badge, Button, Card, CardHeader, EmptyState, ErrorBox, Field, Notice, Spinner, Stat, useToast } from '../components/ui'
import { cx, fmtDate, fmtScore, fmtTime, pct, toISO, useAsync } from '../lib'

type Filters = { date_from: string; date_to: string; class_name: string; subject: string; slot: string; q: string; status: string }

function weekAgo() { const d = new Date(); d.setDate(d.getDate() - 6); return toISO(d) }

export default function Reports() {
  const [params, setParams] = useSearchParams()
  const toast = useToast()
  const initial: Filters = {
    date_from: params.get('date_from') ?? weekAgo(), date_to: params.get('date_to') ?? toISO(new Date()),
    class_name: params.get('class_name') ?? '', subject: params.get('subject') ?? '', slot: params.get('slot') ?? '',
    q: params.get('q') ?? '', status: params.get('status') ?? '',
  }
  const [draft, setDraft] = useState<Filters>(initial)
  const [applied, setApplied] = useState<Filters>(initial)
  const [view, setView] = useState<'records' | 'sessions'>('records')
  const [exporting, setExporting] = useState(false)
  const classes = useAsync(() => api.get<ClassItem[]>('/api/classes'))
  const courses = useAsync(() => api.get<Course[]>('/api/courses'))
  const query = qs(applied)
  const data = useAsync(() => api.get<HistoryResponse>(`/api/history${query}`), [query])

  const subjects = useMemo(() => Array.from(new Set((courses.data ?? []).filter((c) => !draft.class_name || c.class_name === draft.class_name).map((c) => c.subject))).sort(), [courses.data, draft.class_name])
  const set = (k: keyof Filters, v: string) => setDraft((d) => ({ ...d, [k]: v }))
  const apply = (f = draft) => { setApplied(f); setParams(Object.fromEntries(Object.entries(f).filter(([, v]) => v)) as any, { replace: true }) }
  const reset = () => { const f = { date_from: weekAgo(), date_to: toISO(new Date()), class_name: '', subject: '', slot: '', q: '', status: '' }; setDraft(f); apply(f) }

  const exportXlsx = async () => {
    setExporting(true)
    try {
      const res = await fetch(`/api/reports/export${query}`)
      if (!res.ok) throw new ApiError(res.status, (await res.json().catch(() => ({}))).detail ?? 'Xuất Excel thất bại')
      const blob = await res.blob()
      const name = /filename="([^"]+)"/.exec(res.headers.get('content-disposition') ?? '')?.[1] ?? 'diem_danh.xlsx'
      const a = document.createElement('a')
      a.href = URL.createObjectURL(blob); a.download = name; a.click()
      setTimeout(() => URL.revokeObjectURL(a.href), 2000)
      toast('success', `Đã xuất ${name} (bản sao lưu trong thư mục exports)`)
    } catch (e) { toast('error', e instanceof ApiError ? e.message : 'Không kết nối được máy chủ') } finally { setExporting(false) }
  }

  const s = data.data?.summary
  const dirty = JSON.stringify(draft) !== JSON.stringify(applied)

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader title="Bộ lọc" subtitle="Báo cáo và file Excel dùng đúng phạm vi đang chọn" icon={<Filter className="size-5" />} />
        <form className="grid grid-cols-2 gap-3 p-4 sm:p-5 lg:grid-cols-4" onSubmit={(e) => { e.preventDefault(); apply() }}>
          <Field label="Từ ngày"><input type="date" className="input" value={draft.date_from} onChange={(e) => set('date_from', e.target.value)} /></Field>
          <Field label="Đến ngày"><input type="date" className="input" value={draft.date_to} onChange={(e) => set('date_to', e.target.value)} /></Field>
          <Field label="Lớp">
            <select className="input" value={draft.class_name} onChange={(e) => { set('class_name', e.target.value); set('subject', '') }}>
              <option value="">Tất cả</option>{classes.data?.map((c) => <option key={c.id} value={c.name}>{c.name}</option>)}
            </select>
          </Field>
          <Field label="Môn">
            <select className="input" value={draft.subject} onChange={(e) => set('subject', e.target.value)}>
              <option value="">Tất cả</option>{subjects.map((x) => <option key={x} value={x}>{x}</option>)}
            </select>
          </Field>
          <Field label="Slot">
            <select className="input" value={draft.slot} onChange={(e) => set('slot', e.target.value)}>
              <option value="">Tất cả</option>{Array.from({ length: 20 }, (_, i) => <option key={i + 1} value={i + 1}>Slot {i + 1}</option>)}
            </select>
          </Field>
          <Field label="Trạng thái">
            <select className="input" value={draft.status} onChange={(e) => set('status', e.target.value)}>
              <option value="">Tất cả</option><option value="present">Có mặt</option><option value="absent">Vắng</option><option value="unknown">Không rõ (dữ liệu cũ)</option>
            </select>
          </Field>
          <Field label="Sinh viên" className="col-span-2">
            <div className="relative"><Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted" />
              <input className="input pl-9" placeholder="Mã hoặc họ tên" value={draft.q} onChange={(e) => set('q', e.target.value)} /></div>
          </Field>
          <div className="col-span-2 flex flex-wrap items-end gap-2 lg:col-span-4">
            <Button type="submit" icon={<Filter className="size-4" />} variant={dirty ? 'primary' : 'soft'}>Áp dụng</Button>
            <Button type="button" variant="ghost" icon={<RotateCcw className="size-4" />} onClick={reset}>Đặt lại</Button>
            <Button type="button" variant="secondary" className="ml-auto" icon={<Download className="size-4" />} loading={exporting} disabled={!data.data || dirty} onClick={exportXlsx} title={dirty ? 'Bấm Áp dụng trước khi xuất' : undefined}>Xuất Excel</Button>
          </div>
        </form>
      </Card>

      {data.error ? <ErrorBox error={data.error} onRetry={() => data.reload()} /> : !data.data || !s ? <Spinner /> : (
        <div className={cx('space-y-4 transition-opacity', data.loading && 'opacity-60')}>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Stat label="Phiên" value={s.sessions} icon={<CalendarCheck className="size-5" />} hint={s.legacy_sessions ? `${s.legacy_sessions} phiên dữ liệu cũ (không có sĩ số)` : 'trong phạm vi lọc'} />
            <Stat label="Lượt có mặt" value={s.present} icon={<UserCheck className="size-5" />} hint="mỗi sinh viên tối đa 1 lượt/phiên" />
            <Stat label="Lượt vắng" value={s.absent} tone="red" icon={<UserX className="size-5" />} hint={`theo sĩ số ${s.roster} lượt của các phiên`} />
            <Stat label="Tỉ lệ có mặt" value={pct(s.rate)} tone="blue" icon={<Percent className="size-5" />} hint="chỉ tính phiên có danh sách lớp" />
          </div>
          {s.legacy_sessions > 0 && <Notice tone="blue">Có {s.legacy_sessions} phiên tạo từ app desktop cũ chưa lưu danh sách lớp — chỉ hiển thị sinh viên có mặt, không suy đoán số vắng.</Notice>}

          <Card className="overflow-hidden">
            <div className="flex gap-1 border-b border-line p-2">
              {(['records', 'sessions'] as const).map((v) => (
                <button key={v} onClick={() => setView(v)} className={cx('rounded-xl px-4 py-2 text-sm font-semibold transition', view === v ? 'bg-primary-light text-primary-dark' : 'text-muted hover:bg-gray-50')}>
                  {v === 'records' ? `Chi tiết (${data.data!.records.length})` : `Theo phiên (${data.data!.sessions.length})`}
                </button>
              ))}
            </div>
            {view === 'records' ? (
              data.data.records.length === 0 ? <EmptyState icon={<FileSpreadsheet className="size-7" />} title="Không có dữ liệu">Không có bản ghi nào trong phạm vi lọc.</EmptyState> : (<>
                <div className="hidden overflow-x-auto md:block">
                  <table className="w-full text-sm">
                    <thead className="table-head"><tr><th className="px-4 py-3">Ngày</th><th className="px-4 py-3">Lớp · Môn</th><th className="px-4 py-3">Slot</th><th className="px-4 py-3">Sinh viên</th><th className="px-4 py-3">Trạng thái</th><th className="px-4 py-3">Giờ điểm danh</th><th className="px-4 py-3 text-right">Điểm tương đồng</th></tr></thead>
                    <tbody className="divide-y divide-line">
                      {data.data.records.slice(0, 1000).map((r, i) => (
                        <tr key={i} className="hover:bg-primary-light/30">
                          <td className="px-4 py-2.5 whitespace-nowrap">{fmtDate(r.date)}</td>
                          <td className="px-4 py-2.5">{r.class_name} · {r.subject}</td>
                          <td className="px-4 py-2.5">{r.slot}</td>
                          <td className="px-4 py-2.5"><p className="font-semibold">{r.student_name}</p><p className="font-mono text-xs text-muted">{r.student_id}</p></td>
                          <td className="px-4 py-2.5"><StatusBadge s={r.status} /></td>
                          <td className="px-4 py-2.5">{fmtTime(r.timestamp)}</td>
                          <td className="px-4 py-2.5 text-right tabular-nums">{fmtScore(r.score)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <ul className="divide-y divide-line md:hidden">
                  {data.data.records.slice(0, 500).map((r, i) => (
                    <li key={i} className="flex items-center gap-3 p-4">
                      <div className="min-w-0 flex-1"><p className="truncate font-semibold">{r.student_name} <span className="font-mono text-xs font-normal text-muted">{r.student_id}</span></p>
                        <p className="truncate text-xs text-muted">{fmtDate(r.date)} · {r.class_name} · {r.subject} · Slot {r.slot}{r.timestamp ? ` · ${fmtTime(r.timestamp)}` : ''}</p></div>
                      <StatusBadge s={r.status} />
                    </li>
                  ))}
                </ul>
                {data.data.records.length > 1000 && <p className="border-t border-line px-4 py-3 text-xs text-muted">Hiển thị 1000 dòng đầu — file Excel chứa đầy đủ {data.data.records.length} dòng.</p>}
              </>)
            ) : (
              data.data.sessions.length === 0 ? <EmptyState icon={<CalendarCheck className="size-7" />} title="Không có phiên">Không có phiên nào trong phạm vi lọc.</EmptyState> : (
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[640px] text-sm">
                    <thead className="table-head"><tr><th className="px-4 py-3">Ngày</th><th className="px-4 py-3">Lớp · Môn</th><th className="px-4 py-3">Slot</th><th className="px-4 py-3">Bắt đầu</th><th className="px-4 py-3 text-right">Có mặt</th><th className="px-4 py-3 text-right">Vắng</th><th className="px-4 py-3">Trạng thái</th></tr></thead>
                    <tbody className="divide-y divide-line">
                      {data.data.sessions.map((x) => (
                        <tr key={x.id} className="hover:bg-primary-light/30">
                          <td className="px-4 py-2.5">{fmtDate(x.date)}</td><td className="px-4 py-2.5 font-semibold">{x.class_name} · {x.subject}</td><td className="px-4 py-2.5">{x.slot}</td>
                          <td className="px-4 py-2.5">{fmtTime(x.started_at)}</td>
                          <td className="px-4 py-2.5 text-right font-semibold text-primary-dark">{x.present}{x.roster_known ? ` / ${x.roster}` : ''}</td>
                          <td className="px-4 py-2.5 text-right">{x.absent ?? '—'}</td>
                          <td className="px-4 py-2.5">{x.state === 'active' ? <Badge tone="green" dot>Đang mở</Badge> : x.legacy ? <Badge>Dữ liệu cũ</Badge> : <Badge>Đã kết thúc</Badge>}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )
            )}
          </Card>
        </div>
      )}
    </div>
  )
}

function StatusBadge({ s }: { s: 'present' | 'absent' | 'unknown' }) {
  return s === 'present' ? <Badge tone="green" dot>Có mặt</Badge> : s === 'absent' ? <Badge tone="red" dot>Vắng</Badge> : <Badge>Không rõ</Badge>
}
