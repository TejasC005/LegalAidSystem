/*
 * frontend/src/components/layout/AppLayout.jsx
 * ──────────────────────────────────────────────────────────────────────────────
 * LEXIS — Shared App Layout (Module 3)
 *
 * WHAT IS THIS?
 *   Every protected page (dashboard, feature pages) uses the same visual
 *   shell: a header at the top, a sidebar on the left with navigation links,
 *   the page content in the middle, and a footer at the bottom.
 *
 *   Instead of repeating that structure in every page component, we define
 *   it ONCE here.  React Router's <Outlet /> fills in whichever page
 *   component matched the URL.  So:
 *
 *     URL /               → AppLayout renders, Outlet is replaced by <Home>
 *     URL /rights-explainer → AppLayout renders, Outlet is replaced by <RightsExplainer>
 *     ...and so on.
 *
 * LAYOUT STRUCTURE (CSS Grid):
 *
 *   ┌─────────────────────────────────────────────┐
 *   │                   HEADER                    │
 *   ├──────────┬──────────────────────────────────┤
 *   │          │                                  │
 *   │ SIDEBAR  │          MAIN CONTENT            │
 *   │          │         (Outlet here)            │
 *   │          │                                  │
 *   ├──────────┴──────────────────────────────────┤
 *   │                   FOOTER                    │
 *   └─────────────────────────────────────────────┘
 *
 * SIDEBAR NAVIGATION:
 *   Lists all 6 LEXIS features.  We use NavLink from React Router, which
 *   automatically adds an "active" CSS class when the current URL matches
 *   the link's path — that's how the active link is highlighted without
 *   any manual tracking.
 * ──────────────────────────────────────────────────────────────────────────────
 */

import React from 'react';
import { NavLink, Outlet } from 'react-router-dom';
import {
  Scale,
  LayoutDashboard,
  FileEdit,
  FileSearch,
  ShieldAlert,
  ClipboardList,
  FolderLock,
  Settings,
  Sliders,
  Briefcase
} from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import './AppLayout.css';

// ── Navigation links for all 6 LEXIS features ─────────────────────────────
const NAV_LINKS = [
  { path: '/',                 label: 'Dashboard',           icon: LayoutDashboard, module: null    },
  { path: '/rights-explainer', label: 'Rights Explainer',    icon: Scale,           module: 5       },
  { path: '/document-drafter', label: 'Document Drafter',    icon: FileEdit,        module: 6       },
  { path: '/document-analyzer',label: 'Document Analyzer',   icon: FileSearch,      module: 7       },
  { path: '/scam-detection',   label: 'Scam Detection',      icon: ShieldAlert,     module: 8       },
  { path: '/filing-guide',     label: 'Filing Guide',        icon: ClipboardList,   module: 9       },
  { path: '/vault-deadlines',  label: 'Vault & Deadlines',   icon: FolderLock,      module: 10      },
  { path: '/settings',         label: 'Settings',            icon: Settings,        module: 13      },
];


// ── AppLayout component ────────────────────────────────────────────────────
function AppLayout() {
  const { user, logout } = useAuth();

  return (
    <div className="app-layout">

      {/* ── Header ───────────────────────────────────────────────────── */}
      <header className="app-header">
        <div className="app-header__brand">
          <div className="app-header__logo-wrap">
            <Scale className="app-header__logo-icon" size={22} strokeWidth={2.2} />
          </div>
          <span className="app-header__name">LEXIS</span>
          <span className="app-header__tagline">Legal Aid, Autonomously</span>
        </div>

        <div className="app-header__user">
          {/* Show the user's email/phone (or "User") */}
          <span className="app-header__phone">
            {user?.email || user?.phone || user?.id || 'User'}
          </span>
          <span className="app-header__role-badge">{user?.role || 'user'}</span>

          {/* Sign out button */}
          <button className="btn btn-ghost app-header__logout-btn" onClick={logout}>
            Sign out
          </button>
        </div>
      </header>

      {/* ── Body: sidebar + main ─────────────────────────────────────── */}
      <div className="app-body">

        {/* ── Sidebar navigation ───────────────────────────────────── */}
        <nav className="app-sidebar" aria-label="Main navigation">
          <ul className="app-sidebar__list">
            {NAV_LINKS.map(({ path, label, icon: IconComponent }) => (
              <li key={path} className="app-sidebar__item">
                <NavLink
                  to={path}
                  end={path === '/'}   // exact match for home only
                  className={({ isActive }) =>
                    isActive ? 'app-sidebar__link app-sidebar__link--active'
                             : 'app-sidebar__link'
                  }
                >
                  <IconComponent className="app-sidebar__icon" size={18} strokeWidth={2} />
                  <span>{label}</span>
                </NavLink>
              </li>
            ))}
            {/* Show Admin Panel link only when user has role='admin' */}
            {user?.role === 'admin' && (
              <li className="app-sidebar__item" style={{ marginTop: '1rem', borderTop: '1px solid rgba(255,255,255,0.08)', paddingTop: '0.5rem' }}>
                <NavLink
                  to="/admin"
                  className={({ isActive }) =>
                    isActive ? 'app-sidebar__link app-sidebar__link--active'
                             : 'app-sidebar__link'
                  }
                  style={{ color: '#38bdf8' }}
                >
                  <Sliders className="app-sidebar__icon" size={18} strokeWidth={2} />
                  <span>Admin Panel</span>
                </NavLink>
              </li>
            )}
            {/* Show Lawyer Portal link only when user has role='lawyer' — Module 13 scaffold */}
            {user?.role === 'lawyer' && (
              <li className="app-sidebar__item" style={{ marginTop: '1rem', borderTop: '1px solid rgba(255,255,255,0.08)', paddingTop: '0.5rem' }}>
                <NavLink
                  to="/lawyer"
                  className={({ isActive }) =>
                    isActive ? 'app-sidebar__link app-sidebar__link--active'
                             : 'app-sidebar__link'
                  }
                  style={{ color: '#fbbf24' }}
                >
                  <Briefcase className="app-sidebar__icon" size={18} strokeWidth={2} />
                  <span>Lawyer Portal</span>
                </NavLink>
              </li>
            )}
          </ul>
        </nav>

        {/* ── Main content — React Router fills this in ────────────── */}
        <main className="app-main" id="main-content">
          {/*
            <Outlet /> is replaced at runtime by whichever child route matched.
            e.g. if URL is /rights-explainer, React Router puts <RightsExplainer> here.
          */}
          <Outlet />
        </main>

      </div>

      {/* ── Footer ───────────────────────────────────────────────────── */}
      <footer className="app-footer">
        <span>© 2026 LEXIS — Sanjivani College of Engineering, Kopargaon</span>
        <span className="app-footer__divider">|</span>
        <span>Final-year Capstone Project</span>
      </footer>

    </div>
  );
}

export default AppLayout;
