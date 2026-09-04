/*
 * frontend/src/App.jsx
 * ──────────────────────────────────────────────────────────────────────────────
 * LEXIS — Route Definitions (Module 3)
 *
 * HOW ROUTING WORKS IN THIS APP:
 *
 *   React Router v6 uses a component-based routing system.
 *   You declare <Route> elements here — each one maps a URL path to a React
 *   component.  When the user navigates to a URL, React Router looks for a
 *   matching <Route> and renders its component.
 *
 *   <Routes> — a container; only ONE child route matches at a time.
 *   <Route path="..." element={<Component />}> — when the URL matches "path",
 *     React renders <Component> in place of the <Routes> block.
 *
 * NESTED ROUTES (how layout + page share the screen):
 *
 *   We have a layout component (AppLayout) that provides the header/sidebar/footer.
 *   By nesting page routes INSIDE the layout route, each page automatically
 *   gets the shared layout.  AppLayout uses <Outlet /> as a placeholder —
 *   React Router replaces it with whichever nested route matched.
 *
 *   Example:
 *     URL "/"  →  AppLayout renders, <Outlet> becomes <Home>
 *     URL "/rights-explainer"  →  AppLayout renders, <Outlet> becomes <RightsExplainer>
 *
 * PROTECTED ROUTES:
 *
 *   <ProtectedRoute> is a wrapper component.  It checks if the user is
 *   authenticated.  If NOT → redirect to /login.  If YES → render <Outlet>
 *   (which is the nested AppLayout + page).
 *
 *   So the guard chain is:
 *     ProtectedRoute  → checks auth → AppLayout → checks URL → Page component
 * ──────────────────────────────────────────────────────────────────────────────
 */

import React from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';

// ── Layout & guard ─────────────────────────────────────────────────────────
import ProtectedRoute from './components/ProtectedRoute';
import AppLayout from './components/layout/AppLayout';

// ── Pages ──────────────────────────────────────────────────────────────────
import Login            from './pages/Login';
import Home             from './pages/Home';
import RightsExplainer  from './pages/RightsExplainer';
import DocumentDrafter  from './pages/DocumentDrafter';
import DocumentAnalyzer from './pages/DocumentAnalyzer';
import ScamDetection    from './pages/ScamDetection';
import FilingGuide      from './pages/FilingGuide';
import VaultDeadlines   from './pages/VaultDeadlines';
import AdminDashboard   from './pages/AdminDashboard';
import LawyerDashboard from './pages/LawyerDashboard';  // Module 13 scaffold
import ProfileSetup    from './pages/ProfileSetup';     // Module 13B
import Settings        from './pages/Settings';         // Module 13B


function App() {
  return (
    <Routes>

      {/* ── Public routes (no auth required) ──────────────────────────── */}
      <Route path="/login" element={<Login />} />

      {/* ── Protected routes (auth required) ──────────────────────────── */}
      {/*
        <ProtectedRoute> wraps all authenticated pages.
        It has no path of its own — it just acts as a guard.
        If the user is NOT logged in, they are redirected to /login.
        If they ARE logged in, <Outlet> renders, which is <AppLayout>.
        <AppLayout> then renders another <Outlet> for the specific page.
      */}
      <Route element={<ProtectedRoute />}>
        <Route element={<AppLayout />}>
          <Route index element={<Home />} />                                    {/* / */}
          <Route path="rights-explainer"  element={<RightsExplainer />} />    {/* /rights-explainer */}
          <Route path="document-drafter"  element={<DocumentDrafter />} />    {/* /document-drafter */}
          <Route path="document-analyzer" element={<DocumentAnalyzer />} />   {/* /document-analyzer */}
          <Route path="scam-detection"    element={<ScamDetection />} />      {/* /scam-detection */}
          <Route path="filing-guide"      element={<FilingGuide />} />        {/* /filing-guide */}
          <Route path="vault-deadlines"   element={<VaultDeadlines />} />     {/* /vault-deadlines */}
          <Route path="profile-setup"     element={<ProfileSetup />} />        {/* /profile-setup */}
          <Route path="settings"          element={<Settings />} />            {/* /settings */}
        </Route>
      </Route>

      {/* ── Admin-only protected route (allowedRoles=['admin']) ──────── */}
      <Route element={<ProtectedRoute allowedRoles={['admin']} />}>
        <Route element={<AppLayout />}>
          <Route path="admin" element={<AdminDashboard />} />                 {/* /admin */}
        </Route>
      </Route>

      {/* ── Lawyer-only protected route (allowedRoles=['lawyer']) ──────── */}
      {/*
        Module 13 scaffold: lawyer role has its own isolated route.
        admin, user, and anonymous JWTs are redirected to home (/).
        No functional features — Coming Soon screen only.
      */}
      <Route element={<ProtectedRoute allowedRoles={['lawyer']} />}>
        <Route element={<AppLayout />}>
          <Route path="lawyer" element={<LawyerDashboard />} />           {/* /lawyer */}
        </Route>
      </Route>

      {/* ── Catch-all: unknown URLs go to dashboard (or login if not authed) */}
      <Route path="*" element={<Navigate to="/" replace />} />

    </Routes>
  );
}

export default App;
