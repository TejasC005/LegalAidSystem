/*
 * frontend/src/context/AuthContext.jsx
 * ──────────────────────────────────────────────────────────────────────────────
 * LEXIS — Authentication Context (Module 3)
 *
 * WHAT IS "CONTEXT" IN REACT?
 *   Normally, to share data between components you have to pass it as "props"
 *   down through every level of the component tree.  Context is a shortcut:
 *   you wrap your whole app in a "Provider", and any component — no matter
 *   how deep — can read the shared data without prop-drilling.
 *
 * WHAT DOES THIS CONTEXT STORE?
 *   - user        : the user object returned by the backend (phone, role, id)
 *   - accessToken : the short-lived JWT (15 min) used on every request
 *   - refreshToken: the long-lived JWT (7 days) used to get a new access token
 *   - isLoading   : true while we're checking localStorage at startup
 *
 * HOW LOGIN / LOGOUT WORK:
 *   login(tokens, userObj) → saves tokens to localStorage AND to React state
 *   logout()               → clears localStorage AND React state, goes to /login
 *
 * WHY BOTH LOCALSTORAGE AND STATE?
 *   React state resets when the page refreshes.  localStorage persists across
 *   refreshes.  On startup, we read from localStorage to restore the session,
 *   then keep state in sync for the rest of the browser session.
 * ──────────────────────────────────────────────────────────────────────────────
 */

import React, { createContext, useContext, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';

// ── Create the context object ──────────────────────────────────────────────
// createContext(defaultValue) — the default is only used if a component is
// rendered outside of the Provider (which shouldn't happen in our app).
const AuthContext = createContext(null);


// ── AuthProvider component ─────────────────────────────────────────────────
// This wraps the entire app (see main.jsx).  It stores auth state and
// exposes login/logout functions to every component inside it.
export function AuthProvider({ children }) {
  // State: what we know about the currently logged-in user.
  const [user, setUser]               = useState(null);
  const [accessToken, setAccessToken] = useState(null);
  const [refreshToken, setRefreshToken] = useState(null);

  // isLoading is true only for the first render while we read localStorage.
  // We show nothing (or a spinner) until this is false, to avoid a flash
  // where the app briefly thinks the user is logged out.
  const [isLoading, setIsLoading]     = useState(true);

  const navigate = useNavigate();  // React Router hook — lets us change pages programmatically

  // ── Restore session from localStorage on first load ──────────────────────
  // useEffect with an empty dependency array [] runs exactly ONCE,
  // right after the component mounts (appears on screen for the first time).
  useEffect(() => {
    const storedAccess  = localStorage.getItem('lexis_access_token');
    const storedRefresh = localStorage.getItem('lexis_refresh_token');
    const storedUser    = localStorage.getItem('lexis_user');

    if (storedAccess && storedUser) {
      // We have a saved session — restore it into React state.
      try {
        setUser(JSON.parse(storedUser));      // localStorage stores strings; parse back to object
        setAccessToken(storedAccess);
        setRefreshToken(storedRefresh);
      } catch {
        // If parsing fails (corrupted data), clear everything and start fresh.
        clearStorage();
      }
    }

    // Done loading — the app can now decide which route to show.
    setIsLoading(false);
  }, []); // [] means "only run once on mount"


  // ── login() — called after successful OTP verification ──────────────────
  // Parameters:
  //   tokens  : { access_token, refresh_token } from the backend response
  //   userObj : the user profile we got from /auth/me (or we build a minimal one)
  function login(tokens, userObj) {
    const { access_token, refresh_token } = tokens;

    // 1. Save to localStorage so the session survives a page refresh.
    localStorage.setItem('lexis_access_token',  access_token);
    localStorage.setItem('lexis_refresh_token', refresh_token);
    localStorage.setItem('lexis_user',          JSON.stringify(userObj));

    // 2. Update React state so the rest of the app re-renders with the new user.
    setAccessToken(access_token);
    setRefreshToken(refresh_token);
    setUser(userObj);

    // 3. Navigate to the dashboard.
    navigate('/');
  }


  // ── logout() — called when the user clicks "Sign out" or on 401 ─────────
  function logout() {
    clearStorage();

    // Reset state — every component that reads from context will re-render.
    setUser(null);
    setAccessToken(null);
    setRefreshToken(null);

    // Go back to the login page.
    navigate('/login');
  }


  // ── clearStorage() — helper to remove all auth keys ──────────────────────
  function clearStorage() {
    localStorage.removeItem('lexis_access_token');
    localStorage.removeItem('lexis_refresh_token');
    localStorage.removeItem('lexis_user');
  }


  // ── Convenience getter ─────────────────────────────────────────────────
  // True when we have an access token (i.e. user is logged in).
  const isAuthenticated = Boolean(accessToken);


  // ── What we expose to every component that uses useAuth() ────────────────
  const value = {
    user,           // The user object { id, phone, role, ... }
    accessToken,    // The JWT access token string (15-min lifetime)
    refreshToken,   // The JWT refresh token string (7-day lifetime)
    isLoading,      // True while we're reading localStorage on first load
    isAuthenticated,// Boolean shortcut — true if logged in
    login,          // Call after verifyOtp succeeds
    logout,         // Call on sign-out or 401
  };

  return (
    // The Provider makes `value` available to every child component.
    <AuthContext.Provider value={value}>
      {children}
    </AuthContext.Provider>
  );
}


// ── useAuth() hook ─────────────────────────────────────────────────────────
// Any component can call:  const { user, login, logout } = useAuth();
// This is cleaner than importing AuthContext directly everywhere.
export function useAuth() {
  const context = useContext(AuthContext);

  // If context is null, the component is used outside of AuthProvider.
  // This is a programming mistake — throw a clear error instead of a cryptic one.
  if (context === null) {
    throw new Error('useAuth() must be used inside <AuthProvider>. Check main.jsx.');
  }

  return context;
}

export default AuthContext;
