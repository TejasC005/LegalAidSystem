
import React from 'react';
import { Outlet } from 'react-router-dom';
import { Scale } from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import './AdminLayout.css';

function AdminLayout() {
  const { user, logout } = useAuth();

  return (
    <div className="admin-layout">
      <header className="admin-layout__header">
        <div className="admin-layout__brand">
          <div className="admin-layout__logo">
            <Scale size={22} />
          </div>
          <span className="admin-layout__name">LEXIS</span>
          <span className="admin-layout__tagline">
            Legal Aid, Autonomously
          </span>
        </div>

        <div className="admin-layout__account">
          <span>{user?.email || user?.id || 'Administrator'}</span>
          <span className="admin-layout__badge">ADMIN</span>
          <button
            type="button"
            className="admin-layout__logout"
            onClick={logout}
          >
            Sign out
          </button>
        </div>
      </header>

      <main className="admin-layout__main">
        <Outlet />
      </main>
    </div>
  );
}

export default AdminLayout;
