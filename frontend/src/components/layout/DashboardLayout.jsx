import { useState } from 'react'
import { Outlet } from 'react-router-dom'
import Header from './Header'
import Sidebar from './Sidebar'

export default function DashboardLayout() {
  const [menuOpen, setMenuOpen] = useState(false)
  return (
    <div className="shell">
      <Sidebar open={menuOpen} onNavigate={() => setMenuOpen(false)} />
      {menuOpen && <button type="button" className="scrim" aria-label="Close navigation" onClick={() => setMenuOpen(false)} />}
      <div className="main">
        <Header menuOpen={menuOpen} onMenu={() => setMenuOpen((open) => !open)} />
        <main className="content">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
