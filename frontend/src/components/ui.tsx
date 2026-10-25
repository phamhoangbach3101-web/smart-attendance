import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'
import { AlertTriangle, CheckCircle2, Info, Loader2, RefreshCw, X, XCircle } from 'lucide-react'
import { cx } from '../lib'
import type { ApiError } from '../api'

// ------------------------------------------------------------------ Button
type Variant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'soft'
export function Button({ variant = 'primary', size = 'md', loading, icon, className, children, ...rest }:
  React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: 'sm' | 'md' | 'lg'; loading?: boolean; icon?: ReactNode }) {
  const styles: Record<Variant, string> = {
    primary: 'bg-primary text-white hover:bg-primary-hover shadow-sm shadow-primary/30',
    secondary: 'bg-white text-ink border border-line hover:border-primary/40 hover:bg-primary-light/40',
    ghost: 'text-muted hover:bg-primary-light/60 hover:text-primary-dark',
    danger: 'bg-danger text-white hover:bg-red-600',
    soft: 'bg-primary-light text-primary-dark hover:bg-primary/20',
  }
  const sizes = { sm: 'h-9 px-3 text-sm gap-1.5', md: 'h-11 px-4 text-[15px] gap-2', lg: 'h-12 px-5 text-base gap-2' }
  return (
    <button
      {...rest}
      disabled={rest.disabled || loading}
      className={cx('inline-flex shrink-0 items-center justify-center rounded-xl font-semibold transition active:scale-[0.98]',
        'focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-primary/25 disabled:cursor-not-allowed disabled:opacity-50 disabled:active:scale-100',
        styles[variant], sizes[size], className)}
    >
      {loading ? <Loader2 className="size-4 animate-spin" /> : icon}
      {children}
    </button>
  )
}

export function Card({ className, children, ...rest }: React.HTMLAttributes<HTMLDivElement>) {
  return <div {...rest} className={cx('card', className)}>{children}</div>
}

export function CardHeader({ title, subtitle, action, icon }: { title: ReactNode; subtitle?: ReactNode; action?: ReactNode; icon?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3 px-5 pt-5">
      <div className="flex min-w-0 items-start gap-3">
        {icon && <div className="grid size-10 shrink-0 place-items-center rounded-xl bg-primary-light text-primary">{icon}</div>}
        <div className="min-w-0">
          <h2 className="text-base font-semibold text-ink">{title}</h2>
          {subtitle && <p className="mt-0.5 text-sm text-muted">{subtitle}</p>}
        </div>
      </div>
      {action}
    </div>
  )
}

// ------------------------------------------------------------------ Badge
export type Tone = 'green' | 'gray' | 'amber' | 'red' | 'blue'
export function Badge({ tone = 'gray', children, dot, className }: { tone?: Tone; children: ReactNode; dot?: boolean; className?: string }) {
  const t: Record<Tone, string> = {
    green: 'bg-primary-light text-primary-dark', gray: 'bg-gray-100 text-gray-600',
    amber: 'bg-warn-light text-amber-700', red: 'bg-danger-light text-red-700', blue: 'bg-info-light text-blue-700',
  }
  const d: Record<Tone, string> = { green: 'bg-primary', gray: 'bg-gray-400', amber: 'bg-warn', red: 'bg-danger', blue: 'bg-info' }
  return (
    <span className={cx('inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-1 text-xs font-semibold', t[tone], className)}>
      {dot && <span className={cx('size-1.5 rounded-full', d[tone])} />}
      {children}
    </span>
  )
}

// ------------------------------------------------------------------ Form fields
export function Field({ label, hint, error, children, className }: { label?: ReactNode; hint?: ReactNode; error?: string | null; children: ReactNode; className?: string }) {
  return (
    <label className={cx('block', className)}>
      {label && <span className="label">{label}</span>}
      {children}
      {error ? <span className="mt-1 block text-sm text-red-600">{error}</span> : hint ? <span className="mt-1 block text-xs text-muted">{hint}</span> : null}
    </label>
  )
}

export function Toggle({ checked, onChange, label, disabled, description }: { checked: boolean; onChange: (v: boolean) => void; label: ReactNode; disabled?: boolean; description?: ReactNode }) {
  return (
    <button type="button" role="switch" aria-checked={checked} disabled={disabled} onClick={() => onChange(!checked)}
      className="flex w-full items-center justify-between gap-4 rounded-xl text-left disabled:opacity-50">
      <span>
        <span className="block text-[15px] font-medium text-ink">{label}</span>
        {description && <span className="mt-0.5 block text-sm text-muted">{description}</span>}
      </span>
      <span className={cx('relative h-7 w-12 shrink-0 rounded-full transition', checked ? 'bg-primary' : 'bg-gray-300')}>
        <span className={cx('absolute top-1 size-5 rounded-full bg-white shadow transition-all', checked ? 'left-6' : 'left-1')} />
      </span>
    </button>
  )
}

// ------------------------------------------------------------------ States
export function Spinner({ label = 'Đang tải…', className }: { label?: string; className?: string }) {
  return (
    <div className={cx('flex items-center justify-center gap-2 py-10 text-sm text-muted', className)}>
      <Loader2 className="size-5 animate-spin text-primary" /> {label}
    </div>
  )
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cx('animate-pulse rounded-xl bg-primary-light/70', className)} />
}

export function ErrorBox({ error, onRetry, className }: { error: ApiError | string; onRetry?: () => void; className?: string }) {
  const msg = typeof error === 'string' ? error : error.message
  return (
    <div className={cx('flex flex-wrap items-start gap-3 rounded-2xl border border-red-200 bg-danger-light/60 p-4 text-sm text-red-800', className)}>
      <XCircle className="mt-0.5 size-5 shrink-0" />
      <p className="min-w-0 flex-1">{msg}</p>
      {onRetry && <Button size="sm" variant="secondary" icon={<RefreshCw className="size-4" />} onClick={onRetry}>Thử lại</Button>}
    </div>
  )
}

export function Notice({ tone = 'blue', title, children, className, icon }: { tone?: Tone; title?: ReactNode; children?: ReactNode; className?: string; icon?: ReactNode }) {
  const t: Record<Tone, string> = {
    blue: 'border-blue-200 bg-info-light/60 text-blue-900', amber: 'border-amber-200 bg-warn-light/70 text-amber-900',
    red: 'border-red-200 bg-danger-light/60 text-red-900', green: 'border-primary/30 bg-primary-light text-primary-dark',
    gray: 'border-line bg-gray-50 text-gray-700',
  }
  const I = tone === 'amber' ? AlertTriangle : tone === 'red' ? XCircle : tone === 'green' ? CheckCircle2 : Info
  return (
    <div className={cx('flex gap-3 rounded-2xl border p-4 text-sm', t[tone], className)}>
      <span className="mt-0.5 shrink-0">{icon ?? <I className="size-5" />}</span>
      <div className="min-w-0">
        {title && <p className="font-semibold">{title}</p>}
        {children && <div className={cx(!!title && 'mt-0.5', 'opacity-90')}>{children}</div>}
      </div>
    </div>
  )
}

export function EmptyState({ icon, title, children, action }: { icon: ReactNode; title: ReactNode; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center px-6 py-12 text-center">
      <div className="mb-4 grid size-16 place-items-center rounded-2xl bg-primary-light text-primary">{icon}</div>
      <h3 className="text-base font-semibold text-ink">{title}</h3>
      {children && <p className="mt-1 max-w-md text-sm text-muted">{children}</p>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  )
}

// ------------------------------------------------------------------ Modal
export function Modal({ open, onClose, title, children, footer, size = 'md' }: { open: boolean; onClose: () => void; title: ReactNode; children: ReactNode; footer?: ReactNode; size?: 'sm' | 'md' | 'lg' | 'xl' }) {
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => { window.removeEventListener('keydown', onKey); document.body.style.overflow = prev }
  }, [open, onClose])
  if (!open) return null
  const w = { sm: 'sm:max-w-md', md: 'sm:max-w-lg', lg: 'sm:max-w-3xl', xl: 'sm:max-w-5xl' }[size]
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center sm:items-center sm:p-4" role="dialog" aria-modal="true">
      <div className="absolute inset-0 animate-fade-in bg-gray-900/40 backdrop-blur-[2px]" onClick={onClose} />
      <div className={cx('relative flex max-h-[92vh] w-full animate-slide-up flex-col rounded-t-3xl bg-white shadow-pop sm:rounded-3xl', w)}>
        <div className="flex items-center justify-between gap-4 border-b border-line px-5 py-4">
          <h3 className="text-lg font-semibold">{title}</h3>
          <button onClick={onClose} className="grid size-9 place-items-center rounded-xl text-muted hover:bg-gray-100" aria-label="Đóng"><X className="size-5" /></button>
        </div>
        <div className="overflow-y-auto px-5 py-5">{children}</div>
        {footer && <div className="flex flex-wrap justify-end gap-2 border-t border-line px-5 py-4">{footer}</div>}
      </div>
    </div>
  )
}

export function ConfirmDialog({ open, title, message, confirmLabel = 'Xác nhận', danger, loading, onConfirm, onClose }:
  { open: boolean; title: ReactNode; message: ReactNode; confirmLabel?: string; danger?: boolean; loading?: boolean; onConfirm: () => void; onClose: () => void }) {
  return (
    <Modal open={open} onClose={onClose} title={title} size="sm"
      footer={<>
        <Button variant="secondary" onClick={onClose} disabled={loading}>Hủy</Button>
        <Button variant={danger ? 'danger' : 'primary'} loading={loading} onClick={onConfirm}>{confirmLabel}</Button>
      </>}>
      <div className="text-[15px] text-gray-700">{message}</div>
    </Modal>
  )
}

// ------------------------------------------------------------------ Toast
type ToastItem = { id: number; tone: 'success' | 'error' | 'info'; text: string }
const ToastCtx = createContext<(tone: ToastItem['tone'], text: string) => void>(() => {})
export const useToast = () => useContext(ToastCtx)

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([])
  const push = useCallback((tone: ToastItem['tone'], text: string) => {
    setItems((prev) => {
      if (prev.some((item) => item.text === text && item.tone === tone)) {
        return prev
      }
      const id = Date.now() + Math.random()
      setTimeout(() => setItems((x) => x.filter((i) => i.id !== id)), tone === 'error' ? 5000 : 3500)
      return [...prev.slice(-2), { id, tone, text }]
    })
  }, [])
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="pointer-events-none fixed inset-x-0 bottom-20 z-[60] flex flex-col items-center gap-2 px-4 lg:bottom-6 lg:items-end lg:pr-6">
        {items.map((t) => (
          <div key={t.id} role="status" className={cx('pointer-events-auto flex max-w-md animate-slide-up items-start gap-2.5 rounded-2xl px-4 py-3 text-sm font-medium shadow-pop',
            t.tone === 'success' && 'bg-primary text-white', t.tone === 'error' && 'bg-red-600 text-white', t.tone === 'info' && 'bg-ink text-white')}>
            {t.tone === 'success' ? <CheckCircle2 className="mt-0.5 size-4 shrink-0" /> : t.tone === 'error' ? <XCircle className="mt-0.5 size-4 shrink-0" /> : <Info className="mt-0.5 size-4 shrink-0" />}
            <span>{t.text}</span>
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  )
}

// ------------------------------------------------------------------ Stat
export function Stat({ label, value, hint, icon, tone = 'green' }: { label: ReactNode; value: ReactNode; hint?: ReactNode; icon: ReactNode; tone?: Tone }) {
  const t: Record<Tone, string> = { green: 'bg-primary-light text-primary', blue: 'bg-info-light text-info', amber: 'bg-warn-light text-amber-600', red: 'bg-danger-light text-danger', gray: 'bg-gray-100 text-gray-500' }
  return (
    <Card className="p-4 sm:p-5">
      <div className="flex items-center justify-between gap-2">
        <p className="text-sm font-medium text-muted">{label}</p>
        <span className={cx('grid size-9 place-items-center rounded-xl', t[tone])}>{icon}</span>
      </div>
      <p className="mt-2 text-2xl font-bold tracking-tight text-ink sm:text-3xl">{value}</p>
      {hint && <p className="mt-1 text-xs text-muted">{hint}</p>}
    </Card>
  )
}
