/*
 * frontend/src/pages/Login.jsx
 * ──────────────────────────────────────────────────────────────────────────────
 * LEXIS — Login Page (Email OTP with Brevo Service)
 *
 * TWO-STEP LOGIN FLOW:
 *   Step 1 (EMAIL): User enters their email address → clicks "Send Verification Code"
 *                   → calls POST /api/v1/auth/send-otp with { email }
 *                   → Brevo delivers 6-digit OTP to inbox (or terminal in dev mode)
 *
 *   Step 2 (OTP):   User enters the 6-digit code → clicks "Verify & Sign in"
 *                   → calls POST /api/v1/auth/verify-otp with { email, otp }
 *                   → on success: JWT tokens saved, redirected to /
 *
 * RELIABILITY FEATURES:
 *   - 60s Resend countdown cooldown timer
 *   - "Change email" action to rectify typos without refreshing
 *   - Clean error feedback & loading states
 *   - No external third-party captcha dependencies
 * ──────────────────────────────────────────────────────────────────────────────
 */

import React, { useState, useEffect, useRef } from 'react';
import { Navigate } from 'react-router-dom';
import {
  Scale,
  Check,
  Info,
  AlertTriangle,
  Lock,
  Lightbulb,
  ArrowLeft,
  Mail,
  ArrowRight,
} from 'lucide-react';
import { sendOtp, verifyOtp, getMe } from '../services/api';
import { useAuth } from '../context/AuthContext';
import './Login.css';

const RESEND_COOLDOWN_SECONDS = 60;
const OTP_LENGTH = 6;

function Login() {
  // ── Read auth context ──────────────────────────────────────────────────
  const { isAuthenticated, login } = useAuth();

  // ── Local state ────────────────────────────────────────────────────────
  const [email, setEmail] = useState('');
  const [otpDigits, setOtpDigits] = useState(Array(OTP_LENGTH).fill(''));
  const [step, setStep] = useState('email'); // 'email' | 'otp'
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [info, setInfo] = useState('');
  const [resendCooldown, setResendCooldown] = useState(0);

  // References to the 6 individual OTP digit inputs
  const inputRefs = useRef([]);

  // ── Resend cooldown countdown timer ────────────────────────────────────
  useEffect(() => {
    let timer;
    if (resendCooldown > 0) {
      timer = setInterval(() => {
        setResendCooldown((prev) => (prev > 0 ? prev - 1 : 0));
      }, 1000);
    }
    return () => {
      if (timer) clearInterval(timer);
    };
  }, [resendCooldown]);

  // ── Auto-focus first digit when entering OTP step ─────────────────────
  useEffect(() => {
    if (step === 'otp') {
      const firstEmptyIndex = otpDigits.findIndex((d) => !d);
      const targetIndex = firstEmptyIndex === -1 ? 0 : firstEmptyIndex;
      inputRefs.current[targetIndex]?.focus();
    }
  }, [step]);

  // ── If already logged in, skip the login page entirely ────────────────
  if (isAuthenticated) {
    return <Navigate to="/" replace />;
  }

  // Helper to validate email format
  function isValidEmail(val) {
    return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(val.trim());
  }

  // ── Step 1 handler: Send OTP via Brevo Email Service ──────────────────
  async function handleSendOtp(e) {
    if (e) e.preventDefault();
    setError('');
    setInfo('');

    const trimmedEmail = email.trim().toLowerCase();
    if (!trimmedEmail) {
      setError('Please enter your email address.');
      return;
    }

    if (!isValidEmail(trimmedEmail)) {
      setError('Please enter a valid email address (e.g. name@example.com).');
      return;
    }

    setLoading(true);
    try {
      await sendOtp(trimmedEmail);
      setEmail(trimmedEmail);
      setOtpDigits(Array(OTP_LENGTH).fill(''));
      setStep('otp');
      setResendCooldown(RESEND_COOLDOWN_SECONDS);
      setInfo(`A 6-digit verification code has been dispatched to ${trimmedEmail}. Please check your inbox.`);
    } catch (err) {
      console.error('Send OTP error:', err);
      const msg = err.response?.data?.detail || err.message || 'Failed to send verification code. Please try again.';
      setError(msg);
    } finally {
      setLoading(false);
    }
  }

  // ── Resend OTP handler ────────────────────────────────────────────────
  async function handleResendOtp() {
    if (resendCooldown > 0 || loading) return;
    setError('');
    setInfo('');
    setLoading(true);

    try {
      await sendOtp(email);
      setOtpDigits(Array(OTP_LENGTH).fill(''));
      setResendCooldown(RESEND_COOLDOWN_SECONDS);
      setInfo('A fresh verification code has been dispatched to your email.');
      inputRefs.current[0]?.focus();
    } catch (err) {
      console.error('Resend OTP error:', err);
      const msg = err.response?.data?.detail || err.message || 'Failed to resend code. Please wait a moment.';
      setError(msg);
    } finally {
      setLoading(false);
    }
  }

  // ── Step 2 handler: Core OTP Verification ─────────────────────────────
  async function handleVerifyCode(codeToVerify) {
    const code = (codeToVerify || otpDigits.join('')).trim();
    const trimmedEmail = email.trim().toLowerCase();

    if (!code || code.length !== OTP_LENGTH) {
      setError(`Please enter the complete ${OTP_LENGTH}-digit verification code.`);
      return;
    }

    setError('');
    setInfo('');
    setLoading(true);

    try {
      // 1. Verify OTP with LEXIS Backend
      const tokenResponse = await verifyOtp(trimmedEmail, code);
      const tokens = tokenResponse.data;

      // Store access token in localStorage for getMe()
      localStorage.setItem('lexis_access_token', tokens.access_token);

      // 2. Fetch full citizen profile
      let userObj;
      try {
        const meResponse = await getMe();
        userObj = meResponse.data;
      } catch {
        userObj = { role: tokens.role, email: trimmedEmail };
      }

      // 3. Complete authentication
      login(tokens, userObj);
    } catch (err) {
      console.error('OTP verification error:', err);
      localStorage.removeItem('lexis_access_token');
      const msg = err.response?.data?.detail || err.message || 'Verification failed. Please check the code and try again.';
      setError(msg);
      inputRefs.current[0]?.focus();
      inputRefs.current[0]?.select();
    } finally {
      setLoading(false);
    }
  }

  function handleFormSubmit(e) {
    e.preventDefault();
    handleVerifyCode(otpDigits.join(''));
  }

  // ── Segmented OTP Input Box Handlers ──────────────────────────────────
  function handleDigitChange(index, e) {
    const rawVal = e.target.value;
    const cleanDigits = rawVal.replace(/\D/g, '');

    if (!cleanDigits) {
      const next = [...otpDigits];
      next[index] = '';
      setOtpDigits(next);
      return;
    }

    const char = cleanDigits.slice(-1);
    const next = [...otpDigits];
    next[index] = char;
    setOtpDigits(next);

    // Auto-advance focus to next tile
    if (index < OTP_LENGTH - 1 && char) {
      inputRefs.current[index + 1]?.focus();
    }

    // Auto-submit when all 6 boxes are filled
    const fullCode = next.join('');
    if (fullCode.length === OTP_LENGTH && next.every((d) => d !== '')) {
      handleVerifyCode(fullCode);
    }
  }

  function handleDigitKeyDown(index, e) {
    if (e.key === 'Backspace') {
      if (!otpDigits[index] && index > 0) {
        inputRefs.current[index - 1]?.focus();
        const next = [...otpDigits];
        next[index - 1] = '';
        setOtpDigits(next);
      }
    } else if (e.key === 'ArrowLeft' && index > 0) {
      e.preventDefault();
      inputRefs.current[index - 1]?.focus();
    } else if (e.key === 'ArrowRight' && index < OTP_LENGTH - 1) {
      e.preventDefault();
      inputRefs.current[index + 1]?.focus();
    }
  }

  function handleDigitPaste(e) {
    e.preventDefault();
    const pasted = e.clipboardData.getData('text').replace(/\D/g, '').slice(0, OTP_LENGTH);
    if (!pasted) return;

    const next = [...otpDigits];
    for (let i = 0; i < OTP_LENGTH; i++) {
      next[i] = pasted[i] || '';
    }
    setOtpDigits(next);

    const targetIdx = Math.min(pasted.length, OTP_LENGTH - 1);
    inputRefs.current[targetIdx]?.focus();

    if (pasted.length === OTP_LENGTH) {
      handleVerifyCode(pasted);
    }
  }

  const currentOtpValue = otpDigits.join('');

  // ── Render ─────────────────────────────────────────────────────────────
  return (
    <div className="login-page">
      <div className="login-card">

        {/* Logo / Brand Header */}
        <div className="login-card__brand">
          <div className="login-card__logo-wrapper">
            <Scale size={32} color="#1a6b5a" />
          </div>
          <h1 className="login-card__title">LEXIS</h1>
          <p className="login-card__subtitle">Autonomous Legal Aid System</p>
        </div>

        {/* Step Indicator */}
        <div className="login-steps" aria-label="Sign-in progress">
          <span className={`login-step ${step === 'email' ? 'login-step--active' : 'login-step--done'}`}>
            {step === 'otp' ? (
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 3 }}>
                <Check size={12} /> Email
              </span>
            ) : (
              '1 · Email'
            )}
          </span>
          <span className="login-steps__connector" />
          <span className={`login-step ${step === 'otp' ? 'login-step--active' : ''}`}>
            2 · Verification
          </span>
        </div>

        {/* Info Feedback Banner */}
        {info && (
          <div className="login-info" role="status">
            <Info size={16} className="login-info__icon" />
            <span>{info}</span>
          </div>
        )}

        {/* Error Feedback Banner */}
        {error && (
          <div className="login-error" role="alert">
            <AlertTriangle size={16} className="login-error__icon" />
            <span>{error}</span>
          </div>
        )}

        {/* ── STEP 1: Email Entry ──────────────────────────────────── */}
        {step === 'email' && (
          <form onSubmit={handleSendOtp} className="login-form" noValidate>
            <label htmlFor="email" className="login-label">
              Citizen Email Address
            </label>
            <div className="login-input-group">
              <span className="login-input-icon" aria-hidden="true">
                <Mail size={18} />
              </span>
              <input
                id="email"
                type="email"
                className="input-field login-email-input"
                placeholder="citizen@example.com"
                value={email}
                onChange={(e) => {
                  setEmail(e.target.value);
                  if (error) setError('');
                }}
                autoFocus
                autoComplete="email"
                disabled={loading}
                required
              />
            </div>

            <p className="login-hint">
              <Lock size={13} style={{ verticalAlign: 'text-bottom', marginRight: 4, color: '#1a6b5a' }} />
              <strong>Passwordless & Secure:</strong> We will email you a 6-digit one-time code to authenticate your session.
            </p>

            <button
              type="submit"
              className="btn btn-primary login-submit-btn"
              disabled={loading || !email.trim()}
            >
              {loading ? (
                <span className="login-btn-content">
                  <span className="login-spinner" /> Sending Code…
                </span>
              ) : (
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                  Send Verification Code <ArrowRight size={15} />
                </span>
              )}
            </button>
          </form>
        )}

        {/* ── STEP 2: 6-Digit Segmented OTP Entry ──────────────────── */}
        {step === 'otp' && (
          <form onSubmit={handleFormSubmit} className="login-form" noValidate>
            <div className="login-otp-sent-banner">
              <div className="login-otp-sent-text">
                Code sent to <span className="login-email-badge">{email}</span>
              </div>
              <button
                type="button"
                className="login-edit-email-btn"
                onClick={() => {
                  setStep('email');
                  setOtpDigits(Array(OTP_LENGTH).fill(''));
                  setError('');
                  setInfo('');
                }}
                disabled={loading}
                title="Change email address"
              >
                Change
              </button>
            </div>

            <label className="login-label">
              Enter 6-digit Verification Code
            </label>

            {/* 6-box Segmented PIN Input */}
            <div
              className={`login-otp-boxes ${error ? 'login-otp-boxes--error' : ''}`}
              onPaste={handleDigitPaste}
            >
              {otpDigits.map((digit, idx) => (
                <input
                  key={idx}
                  ref={(el) => (inputRefs.current[idx] = el)}
                  type="text"
                  inputMode="numeric"
                  pattern="[0-9]*"
                  maxLength={1}
                  className={`login-otp-box ${digit ? 'login-otp-box--filled' : ''}`}
                  value={digit}
                  onChange={(e) => handleDigitChange(idx, e)}
                  onKeyDown={(e) => handleDigitKeyDown(idx, e)}
                  disabled={loading}
                  aria-label={`Digit ${idx + 1} of ${OTP_LENGTH}`}
                  autoComplete="one-time-code"
                />
              ))}
            </div>

            <button
              type="submit"
              className="btn btn-primary login-submit-btn"
              disabled={loading || currentOtpValue.length !== OTP_LENGTH}
            >
              {loading ? (
                <span className="login-btn-content">
                  <span className="login-spinner" /> Verifying…
                </span>
              ) : (
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                  Verify & Sign in <ArrowRight size={15} />
                </span>
              )}
            </button>

            {/* Resend OTP Row with Cooldown */}
            <div className="login-resend-row">
              {resendCooldown > 0 ? (
                <span className="login-cooldown-text">
                  Resend code in <strong>{resendCooldown}s</strong>
                </span>
              ) : (
                <button
                  type="button"
                  className="btn btn-link login-resend-btn"
                  onClick={handleResendOtp}
                  disabled={loading}
                >
                  Didn’t receive the email? <strong>Resend Code</strong>
                </button>
              )}
            </div>

            {/* Micro-guide helper */}
            <div className="login-troubleshoot-hints">
              <p className="login-hint-item">
                <Lightbulb size={13} style={{ verticalAlign: 'text-bottom', marginRight: 4, color: '#1a6b5a' }} />
                <strong>Tip:</strong> If you don't see the email within 30 seconds, please check your <em>Spam</em> or <em>Promotions</em> folder.
              </p>
            </div>

            {/* Back Button */}
            <button
              type="button"
              className="btn btn-ghost login-back-btn"
              onClick={() => {
                setStep('email');
                setOtpDigits(Array(OTP_LENGTH).fill(''));
                setError('');
                setInfo('');
              }}
              disabled={loading}
            >
              <ArrowLeft size={14} style={{ marginRight: 4, verticalAlign: 'middle' }} />
              Use a different email
            </button>
          </form>
        )}

      </div>
    </div>
  );
}

export default Login;
