import { NavLink } from 'react-router-dom'
import { NAV_ITEMS } from './navigation'

export default function Sidebar({ open, onNavigate }) {
  return (
    <aside id="main-nav" className={`sidebar ${open ? 'is-open' : ''}`} aria-label="Main navigation">
      <div className="brand">
        <span className="brand-mark" aria-hidden="true">W</span>
        <span className="brand-name">WorkPilot <span>AI</span></span>
      </div>
      <nav className="nav">
        {NAV_ITEMS.map(({ to, label, icon: Icon }) => (
          <NavLink key={to} to={to} onClick={onNavigate} className={({ isActive }) => `nav-link ${isActive ? 'is-active' : ''}`}>
            <Icon size={18} aria-hidden="true" />
            {label}
          </NavLink>
        ))}
      </nav>
      <p className="sidebar-foot">Hackathon preview</p>
    </aside>
  )
}
