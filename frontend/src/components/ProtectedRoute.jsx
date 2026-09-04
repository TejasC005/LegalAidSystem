/*
 * frontend/src/components/ProtectedRoute.jsx
 * ──────────────────────────────────────────────────────────────────────────────
 * LEXIS — Protected Route Wrapper (Module 3)
 *
 * WHAT IS A PROTECTED ROUTE?
 *   Some pages (dashboard, feature pages) should only be accessible to
 *   logged-in users.  If someone types "/dashboard" directly into the
 *   address bar without being logged in, we want to send them to /login
 *   instead of showing them a broken page.
 *
 *   ProtectedRoute is a component that wraps those pages.  Before rendering
 *   the actual page, it asks: "Is the user authenticated?"
 *
 *     YES → render the page as normal  (children)
 *     NO  → redirect to /login         (<Navigate to="/login" />)
 *
 * HOW IT DECIDES:
 *   It calls useAuth() to read `isAuthenticated` and `isLoading` from
 *   AuthContext.  isLoading is true only on the very first render while we
 *   check localStorage — we wait for that check to finish before deciding,
 *   so we don't get a false "not authenticated" flash.
 *
 * HOW TO USE IT (in App.jsx):
 *   <Route element={<ProtectedRoute />}>
 *     <Route path="/" element={<Home />} />
 *   </Route>
 *
 *   Any <Route> nested inside <ProtectedRoute> is automatically guarded.
 *   <Outlet /> renders whichever nested route matched.
 *
 * FUTURE: role-based access
 *   This component accepts an optional `allowedRoles` prop (array of strings).
 *   If provided, it also checks that the current user's role is in that list.
 *   Currently not enforced in any route, but the check is already wired in.
 * ──────────────────────────────────────────────────────────────────────────────
 */

import React from 'react';
import { Navigate, Outlet } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';


// ── ProtectedRoute component ───────────────────────────────────────────────
// Props:
//   allowedRoles (optional, array) — if provided, user's role must be in this list
//   e.g. <ProtectedRoute allowedRoles={['admin', 'lawyer']} />
function ProtectedRoute({ allowedRoles }) {
  const { isAuthenticated, isLoading, user } = useAuth();

  // ── Step 1: Wait for localStorage check to finish ────────────────────────
  // isLoading is true for a split second on first render.
  // Returning null shows a blank screen rather than a flash of /login.
  if (isLoading) {
    return null;  // or swap for a <LoadingSpinner /> component later
  }

  // ── Step 2: Check authentication ─────────────────────────────────────────
  if (!isAuthenticated) {
    // Not logged in → send to /login.
    // `replace` means the /login page replaces the current history entry,
    // so pressing "Back" in the browser won't loop the user back to the
    // protected page they couldn't access.
    return <Navigate to="/login" replace />;
  }

  // ── Step 3: Check role (if allowedRoles was provided) ────────────────────
  // allowedRoles is optional — if not provided, skip this check.
  if (allowedRoles && allowedRoles.length > 0) {
    const userRole = user?.role;
    const hasPermission = allowedRoles.includes(userRole);

    if (!hasPermission) {
      // Logged in, but wrong role → redirect to home (dashboard).
      // We don't show a 403 page yet; that's a Module 12 concern.
      return <Navigate to="/" replace />;
    }
  }

  // ── Step 4: All checks passed — render the protected page ───────────────
  // <Outlet /> is a React Router placeholder: it renders whichever nested
  // route matched inside this ProtectedRoute wrapper.
  return <Outlet />;
}

export default ProtectedRoute;
