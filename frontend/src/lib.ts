import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError } from './api'

export function cx(...parts: (string | false | null | undefined)[]) {
  return parts.filter(Boolean).join(' ')
}

/** Load data with loading/error states; `reload` re-runs the loader. */
export function useAsync<T>(loader: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<ApiError | null>(null)
  const [loading, setLoading] = useState(true)
  const seq = useRef(0)
  const run = useCallback(async (silent = false) => {
    const id = ++seq.current
    if (!silent) setLoading(true)
    try {
      const value = await loader()
      if (id === seq.current) { setData(value); setError(null) }
    } catch (e) {
      if (id === seq.current) setError(e instanceof ApiError ? e : new ApiError(0, String(e)))
    } finally {
      if (id === seq.current) setLoading(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
  useEffect(() => { run() }, [run])
  return { data, error, loading, reload: run, setData }
}

export function useInterval(fn: () => void, ms: number | null) {
  const ref = useRef(fn)
  ref.current = fn
  useEffect(() => {
    if (ms === null) return
    const t = setInterval(() => ref.current(), ms)
    return () => clearInterval(t)
  }, [ms])
}

export const todayISO = () => toISO(new Date())
export function toISO(d: Date) {
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}
export function fmtDate(iso: string | null | undefined, opts: Intl.DateTimeFormatOptions = { day: '2-digit', month: '2-digit', year: 'numeric' }) {
  if (!iso) return '—'
  const d = new Date(iso.length <= 10 ? iso + 'T00:00:00' : iso.replace(' ', 'T'))
  return d.toLocaleDateString('vi-VN', opts)
}
export const fmtTime = (ts: string | null | undefined) => (ts ? ts.slice(11, 19) : '—')
export function fmtDuration(sec: number) {
  const h = Math.floor(sec / 3600)
  const m = Math.floor((sec % 3600) / 60)
  const s = sec % 60
  const p = (n: number) => String(n).padStart(2, '0')
  return h ? `${h}:${p(m)}:${p(s)}` : `${p(m)}:${p(s)}`
}
export const fmtScore = (v: number | null | undefined) => (v === null || v === undefined ? '—' : v.toFixed(3))
export const pct = (v: number | null | undefined) => (v === null || v === undefined ? '—' : `${Math.round(v * 100)}%`)
