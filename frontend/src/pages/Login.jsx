/*
 * frontend/src/pages/Login.jsx
 * ──────────────────────────────────────────────────────────────────────────────
 * LEXIS — Login Page (Module 3)
 *
 * HOW THE TWO-STEP LOGIN FLOW WORKS:
 *   Step 1 (PHONE):  User enters their phone number → clicks "Send OTP"
 *                    → calls POST /api/v1/auth/send-otp
 *                    → OTP appears in the BACKEND TERMINAL (dev mode)
 *
 *   Step 2 (OTP):    User types the OTP from the terminal → clicks "Verify"
 *                    → calls POST /api/v1/auth/verify-otp
 *                    → on success: tokens saved, redirected to /dashboard
 *
 * We track which step we're on with a `step` state variable:
 *   'phone' → show phone input
 *   'otp'   → show OTP input
 *
 * STATE VARIABLES (useState):
 *   phone    — what the user typed in the phone field
 *   otp      — what the user typed in the OTP field
 *   step     — 'phone' or 'otp'
 *   loading  — true while a network request is in flight (disables the button)
 *   error    — an error message string (shown in red below the form)
 * ──────────────────────────────────────────────────────────────────────────────
 */

import React, { useState } from 'react';
import { Navigate } from 'react-router-dom';
import { sendOtp, verifyOtp, getMe } from '../services/api';
import { useAuth } from '../context/AuthContext';
import './Login.css';


function Login() {
  // ── Read auth context ──────────────────────────────────────────────────
  const { isAuthenticated, login } = useAuth();

  // ── Local state ────────────────────────────────────────────────────────
  const [phone,   setPhone]   = useState('');    // e.g. +919876543210
  const [otp,     setOtp]     = useState('');    // 6-digit code
  const [step,    setStep]    = useState('phone'); // 'phone' | 'otp'
  const [loading, setLoading] = useState(false);
  const [error,   setError]   = useState('');


  // ── If already logged in, skip the login page entirely ────────────────
  if (isAuthenticated) {
    return <Navigate to="/" replace />;
  }


  // ── Step 1 handler: send OTP ──────────────────────────────────────────
  async function handleSendOtp(e) {
    // e.preventDefault() stops the browser from refreshing the page
    // (the default behaviour of a form submit).
    e.preventDefault();
    setError('');

    // Basic validation — backend also validates, but this avoids a round-trip
    if (!phone.trim()) {
      setError('Please enter your phone number.');
      return;
    }

    setLoading(true);
    try {
      await sendOtp(phone.trim());
      // OTP was sent — move to the next step
      setStep('otp');
    } catch (err) {
      // err.response?.data?.detail is the FastAPI error message from the backend
      setError(err.response?.data?.detail || 'Failed to send OTP. Try again.');
    } finally {
      // finally always runs — we always want to stop the loading spinner
      setLoading(false);
    }
  }


  // ── Step 2 handler: verify OTP ────────────────────────────────────────
  async function handleVerifyOtp(e) {
    e.preventDefault();
    setError('');

    if (!otp.trim()) {
      setError('Please enter the OTP.');
      return;
    }

    setLoading(true);
    try {
      // Call verify-otp — returns { access_token, refresh_token, role }
      const tokenResponse = await verifyOtp(phone.trim(), otp.trim());
      const tokens = tokenResponse.data;

      // Store the access token in localStorage temporarily so getMe() can use
      // the Axios interceptor (which reads from localStorage).
      localStorage.setItem('lexis_access_token', tokens.access_token);

      // Fetch the full user profile from /auth/me
      let userObj;
      try {
        const meResponse = await getMe();
        userObj = meResponse.data;
      } catch {
        // If /me fails, build a minimal user object from the token response.
        // This still lets the user in; we'll retry /me later.
        userObj = { role: tokens.role, phone: phone.trim() };
      }

      // login() saves tokens + user to context and localStorage, then navigates to /
      login(tokens, userObj);

    } catch (err) {
      setError(err.response?.data?.detail || 'Invalid OTP. Please try again.');
      // Clean up the temp token we set above
      localStorage.removeItem('lexis_access_token');
    } finally {
      setLoading(false);
    }
  }


  // ── Render ─────────────────────────────────────────────────────────────
  return (
    <div className="login-page">
      <div className="login-card">

        {/* Logo / brand */}
        <div className="login-card__brand">
          <span className="login-card__logo">⚖</span>
          <h1 className="login-card__title">LEXIS</h1>
          <p className="login-card__subtitle">Legal Aid, Autonomously</p>
        </div>

        {/* Step indicator */}
        <div className="login-steps">
          <span className={`login-step ${step === 'phone' ? 'login-step--active' : 'login-step--done'}`}>
            1 · Phone
          </span>
          <span className="login-steps__connector" />
          <span className={`login-step ${step === 'otp' ? 'login-step--active' : ''}`}>
            2 · Verify OTP
          </span>
        </div>

        {/* Error message */}
        {error && (
          <div className="login-error" role="alert">
            {error}
          </div>
        )}

        {/* ── STEP 1: Phone entry ────────────────────────────────── */}
        {step === 'phone' && (
          <form onSubmit={handleSendOtp} className="login-form" noValidate>
            <label htmlFor="phone" className="login-label">
              Mobile number (with country code)
            </label>
            <input
              id="phone"
              type="tel"
              className="input-field"
              placeholder="+91 9876543210"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              autoFocus
              autoComplete="tel"
              disabled={loading}
            />
            <p className="login-hint">
              An OTP will be sent to this number. In development mode,
              check the <strong>backend server terminal</strong> for the code.
            </p>
            <button
              type="submit"
              className="btn btn-primary login-submit-btn"
              disabled={loading}
            >
              {loading ? 'Sending…' : 'Send OTP →'}
            </button>
          </form>
        )}

        {/* ── STEP 2: OTP entry ──────────────────────────────────── */}
        {step === 'otp' && (
          <form onSubmit={handleVerifyOtp} className="login-form" noValidate>
            <p className="login-otp-sent">
              OTP sent to <strong>{phone}</strong>.
              Check the backend server terminal for the code.
            </p>
            <label htmlFor="otp" className="login-label">
              Enter 6-digit OTP
            </label>
            <input
              id="otp"
              type="text"
              inputMode="numeric"
              maxLength={6}
              className="input-field login-otp-input"
              placeholder="123456"
              value={otp}
              onChange={(e) => setOtp(e.target.value.replace(/\D/g, ''))} // digits only
              autoFocus
              autoComplete="one-time-code"
              disabled={loading}
            />
            <button
              type="submit"
              className="btn btn-primary login-submit-btn"
              disabled={loading}
            >
              {loading ? 'Verifying…' : 'Verify & Sign in →'}
            </button>
            {/* Allow going back to edit phone number */}
            <button
              type="button"
              className="btn btn-ghost login-back-btn"
              onClick={() => { setStep('phone'); setOtp(''); setError(''); }}
              disabled={loading}
            >
              ← Change number
            </button>
          </form>
        )}

      </div>
    </div>
  );
}

export default Login;
