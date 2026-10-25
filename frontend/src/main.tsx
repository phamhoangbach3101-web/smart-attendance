import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Link, Route, Routes } from 'react-router-dom'
import './index.css'
import Layout from './components/Layout'
import { Button, EmptyState, ToastProvider } from './components/ui'
import Dashboard from './pages/Dashboard'
import Classes from './pages/Classes'
import AttendanceSetup from './pages/AttendanceSetup'
import LiveSession from './pages/LiveSession'
import Students from './pages/Students'
import Enroll from './pages/Enroll'
import Reports from './pages/Reports'
import Settings from './pages/Settings'
import { Compass } from 'lucide-react'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ToastProvider>
      <BrowserRouter>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<Dashboard />} />
            <Route path="classes" element={<Classes />} />
            <Route path="attendance" element={<AttendanceSetup />} />
            <Route path="attendance/:id" element={<LiveSession />} />
            <Route path="students" element={<Students />} />
            <Route path="students/enroll" element={<Enroll />} />
            <Route path="reports" element={<Reports />} />
            <Route path="settings" element={<Settings />} />
            <Route path="*" element={<EmptyState icon={<Compass className="size-7" />} title="Không tìm thấy trang" action={<Link to="/"><Button>Về Tổng quan</Button></Link>} />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </ToastProvider>
  </StrictMode>,
)
