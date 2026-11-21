import { Menu } from 'lucide-react'
import { useLocation } from 'react-router-dom'
import { NAV_ITEMS } from './navigation'

export default function Header({ onMenu, menuOpen }) {
  const { pathname } = useLocation()
  const current = NAV_ITEMS.find((item) => pathname.startsWith(item.to)) ?? NAV_ITEMS[0]
  return (
    <header className="header">
      <button type="button" className="icon-btn menu-btn" onClick={onMenu} aria-label="Toggle navigation" aria-expanded={menuOpen} aria-controls="main-nav">
        <Menu size={20} aria-hidden="true" />
      </button>
      <div>
        <h1 className="header-title">{current.title}</h1>
        <p className="header-sub">{current.subtitle}</p>
      </div>
    </header>
  )
}
