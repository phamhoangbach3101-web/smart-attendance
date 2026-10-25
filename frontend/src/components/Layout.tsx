import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { BarChart3, BookOpen, Camera, CircleAlert, Home, Loader2, Menu, ScanFace, Settings, Users, WifiOff, X } from 'lucide-react'
import { api, type Health } from '../api'
import { cx, useInterval } from '../lib'

const NAV = [
  { to: '/', label: 'Trang chủ', icon: Home, mobile: true },
  { to: '/attendance', label: 'Điểm danh', icon: Camera, mobile: true },
  { to: '/classes', label: 'Lớp & Môn học', icon: BookOpen },
  { to: '/students', label: 'Sinh viên', icon: Users, mobile: true },
  { to: '/reports', label: 'Lịch sử & Báo cáo', icon: BarChart3, mobile: true, short: 'Báo cáo' },
  { to: '/settings', label: 'Cài đặt', icon: Settings },
]

const TITLES: [RegExp, string][] = [
  [/^\/$/, 'Trang chủ'], [/^\/classes/, 'Lớp & Môn học'], [/^\/attendance\/\d+/, 'Điểm danh trực tiếp'],
  [/^\/attendance/, 'Điểm danh'], [/^\/students\/enroll/, 'Đăng ký khuôn mặt'], [/^\/students/, 'Sinh viên'],
  [/^\/reports/, 'Lịch sử & Báo cáo'], [/^\/settings/, 'Cài đặt'],
]

type HealthState = { health: Health | null; offline: boolean; refresh: () => void }
const HealthCtx = createContext<HealthState>({ health: null, offline: false, refresh: () => {} })
export const useHealth = () => useContext(HealthCtx)

export function ModelPill({ health, offline }: { health: Health | null; offline: boolean }) {
  if (offline) return <span className="inline-flex items-center gap-1.5 rounded-full bg-danger-light px-3 py-1.5 text-xs font-semibold text-red-700"><WifiOff className="size-3.5" /> Mất kết nối máy chủ</span>
  if (!health) return <span className="inline-flex items-center gap-1.5 rounded-full bg-gray-100 px-3 py-1.5 text-xs font-semibold text-gray-600"><Loader2 className="size-3.5 animate-spin" /> Đang kết nối…</span>
  const s = health.models.state
  if (s === 'ready') return <span className="inline-flex items-center gap-1.5 rounded-full bg-primary-light px-3 py-1.5 text-xs font-semibold text-primary-dark"><span className="size-2 rounded-full bg-primary" /> Model sẵn sàng</span>
  if (s === 'error') return <span className="inline-flex items-center gap-1.5 rounded-full bg-danger-light px-3 py-1.5 text-xs font-semibold text-red-700" title={health.models.error ?? ''}><CircleAlert className="size-3.5" /> Model lỗi</span>
  return <span className="inline-flex items-center gap-1.5 rounded-full bg-warn-light px-3 py-1.5 text-xs font-semibold text-amber-700"><Loader2 className="size-3.5 animate-spin" /> Model đang tải</span>
}

function Brand() {
  return (
    <div className="flex items-center gap-3 px-2">
      <div className="grid size-10 place-items-center rounded-2xl bg-primary text-white shadow-md shadow-primary/30"><ScanFace className="size-6" /></div>
      <div className="leading-tight">
        <p className="text-[15px] font-bold text-ink">Smart Attendance</p>
        <p className="text-xs text-muted">Điểm danh khuôn mặt</p>
      </div>
    </div>
  )
}

function SideLink({ to, label, icon: Icon, onClick }: { to: string; label: string; icon: any; onClick?: () => void }) {
  return (
    <NavLink to={to} end={to === '/'} onClick={onClick}
      className={({ isActive }) => cx('flex items-center gap-3 rounded-xl px-3 py-2.5 text-[15px] font-medium transition',
        isActive ? 'bg-primary-light text-primary-dark' : 'text-gray-600 hover:bg-gray-50 hover:text-ink')}>
      {({ isActive }) => <><Icon className={cx('size-5', isActive ? 'text-primary' : 'text-gray-400')} />{label}</>}
    </NavLink>
  )
}

export default function Layout() {
  const [health, setHealth] = useState<Health | null>(null)
  const [offline, setOffline] = useState(false)
  const [moreOpen, setMoreOpen] = useState(false)
  const loc = useLocation()
  const refresh = () => api.get<Health>('/api/health').then((h) => { setHealth(h); setOffline(false) }).catch(() => setOffline(true))
  useEffect(() => { refresh() }, [])
  useInterval(refresh, health?.models.state === 'ready' && !offline ? 15000 : 2500)
  useEffect(() => setMoreOpen(false), [loc.pathname])

  const title = TITLES.find(([re]) => re.test(loc.pathname))?.[1] ?? 'Smart Attendance'
  const today = new Date().toLocaleDateString('vi-VN', { weekday: 'long', day: '2-digit', month: '2-digit', year: 'numeric' })

  return (
    <HealthCtx.Provider value={{ health, offline, refresh }}>
      <div className="min-h-full lg:pl-64">
        {/* Sidebar (desktop) */}
        <aside className="fixed inset-y-0 left-0 z-30 hidden w-64 flex-col border-r border-line bg-white px-4 py-6 lg:flex">
          <Brand />
          <nav className="mt-8 flex flex-col gap-1">{NAV.map((n) => <SideLink key={n.to} {...n} />)}</nav>
          <div className="mt-auto rounded-2xl bg-primary-light/70 p-4 text-xs text-primary-dark">
            <p className="font-semibold">Dữ liệu xử lý cục bộ</p>
            <p className="mt-1 opacity-80">Ảnh khuôn mặt chỉ được xử lý trên máy này, không gửi ra ngoài.</p>
          </div>
        </aside>

        {/* Top bar */}
        <header className="sticky top-0 z-20 border-b border-line bg-white/85 backdrop-blur-md">
          <div className="mx-auto flex h-16 max-w-[1400px] items-center gap-3 px-4 sm:px-6">
            <div className="grid size-9 place-items-center rounded-xl bg-primary text-white lg:hidden"><ScanFace className="size-5" /></div>
            <div className="min-w-0 flex-1">
              <h1 className="truncate text-lg font-bold text-ink sm:text-xl">{title}</h1>
              <p className="hidden text-xs capitalize text-muted sm:block">{today}</p>
            </div>
            {health && health.active_sessions > 0 && !loc.pathname.startsWith('/attendance/') && (
              <NavLink to="/attendance" className="hidden items-center gap-1.5 rounded-full bg-primary px-3 py-1.5 text-xs font-semibold text-white sm:inline-flex">
                <span className="size-2 animate-pulse rounded-full bg-white" /> {health.active_sessions} phiên đang mở
              </NavLink>
            )}
            <ModelPill health={health} offline={offline} />
          </div>
        </header>

        {offline && (
          <div className="mx-auto max-w-[1400px] px-4 pt-4 sm:px-6">
            <div className="flex items-center gap-2 rounded-2xl border border-red-200 bg-danger-light/70 p-3 text-sm text-red-800">
              <WifiOff className="size-4 shrink-0" /> Không kết nối được máy chủ. Hãy kiểm tra cửa sổ chạy <b>run.ps1</b> còn mở; trang sẽ tự kết nối lại.
            </div>
          </div>
        )}

        <main className="mx-auto max-w-[1400px] px-4 pb-28 pt-5 sm:px-6 lg:pb-10 lg:pt-6">
          <Outlet />
        </main>

        {/* Bottom nav (mobile) */}
        <nav className="fixed inset-x-0 bottom-0 z-30 border-t border-line bg-white/95 pb-[env(safe-area-inset-bottom)] backdrop-blur-md lg:hidden">
          <div className="grid grid-cols-5">
            {NAV.filter((n) => n.mobile).map(({ to, label, short, icon: Icon }) => (
              <NavLink key={to} to={to} end={to === '/'}
                className={({ isActive }) => cx('flex flex-col items-center gap-1 py-2.5 text-[11px] font-semibold', isActive ? 'text-primary' : 'text-gray-500')}>
                {({ isActive }) => <><span className={cx('grid h-7 w-12 place-items-center rounded-full transition', isActive && 'bg-primary-light')}><Icon className="size-5" /></span>{short ?? label}</>}
              </NavLink>
            ))}
            <button onClick={() => setMoreOpen(true)} className="flex flex-col items-center gap-1 py-2.5 text-[11px] font-semibold text-gray-500">
              <span className="grid h-7 w-12 place-items-center rounded-full"><Menu className="size-5" /></span>Thêm
            </button>
          </div>
        </nav>

        {moreOpen && (
          <div className="fixed inset-0 z-40 lg:hidden">
            <div className="absolute inset-0 animate-fade-in bg-gray-900/40" onClick={() => setMoreOpen(false)} />
            <div className="absolute inset-x-0 bottom-0 animate-slide-up rounded-t-3xl bg-white p-5 pb-[calc(env(safe-area-inset-bottom)+20px)]">
              <div className="mb-4 flex items-center justify-between"><Brand /><button className="grid size-10 place-items-center rounded-xl hover:bg-gray-100" onClick={() => setMoreOpen(false)} aria-label="Đóng"><X className="size-5" /></button></div>
              <div className="flex flex-col gap-1">{NAV.map((n) => <SideLink key={n.to} {...n} />)}</div>
            </div>
          </div>
        )}
      </div>
    </HealthCtx.Provider>
  )
}

export function PageHeader({ title, subtitle, actions }: { title?: ReactNode; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div className="min-w-0">
        {title && <h2 className="text-xl font-bold text-ink">{title}</h2>}
        {subtitle && <p className="mt-1 text-sm text-muted">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  )
}
