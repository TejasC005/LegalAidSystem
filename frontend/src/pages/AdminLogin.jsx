
import React, { useState } from 'react';
import { Navigate, useNavigate } from 'react-router-dom';
import { Scale, Lock, Mail, ArrowRight, AlertTriangle } from 'lucide-react';
import { getMe } from '../services/api';
import api from '../services/api';
import { useAuth } from '../context/AuthContext';
import './Login.css';

function AdminLogin() {
  const { isAuthenticated, isLoading, user, login } = useAuth();
  const navigate = useNavigate();

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  if (isLoading) return null;

  if (isAuthenticated && user?.role === 'admin') {
    return <Navigate to="/admin" replace />;
  }

  if (isAuthenticated && user?.role !== 'admin') {
    return <Navigate to="/" replace />;
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setError('');

    if (!email.trim() || !password) {
      setError('Enter your admin email and password.');
      return;
    }

    setLoading(true);

    try {
      // Authenticate using the existing backend admin endpoint.
      const response = await api.post('/api/v1/auth/admin/login', {
        email: email.trim().toLowerCase(),
        password,
      });

      const tokens = response.data;

      if (!tokens.access_token) {
        throw new Error('The server did not return an access token.');
      }

      // Temporarily save the access token so getMe() can authenticate.
      localStorage.setItem('lexis_access_token', tokens.access_token);

      let userObj;

      try {
        const meResponse = await getMe();
        userObj = meResponse.data;
      } catch {
        // Admin login itself succeeded; use a minimal admin profile
        // if the profile endpoint is temporarily unavailable.
        userObj = {
          email: email.trim().toLowerCase(),
          role: tokens.role || 'admin',
        };
      }

      // Never accept a non-admin profile into the admin dashboard.
      if (userObj.role !== 'admin') {
        localStorage.removeItem('lexis_access_token');
        throw new Error('This account does not have administrator access.');
      }

      // AuthContext stores tokens/profile and navigates to "/".
      // Navigate to the admin dashboard immediately afterwards.
      login(tokens, userObj, '/admin');
    } catch (err) {
      localStorage.removeItem('lexis_access_token');

      const message =
        err.response?.data?.detail ||
        err.message ||
        'Admin login failed. Check your credentials and try again.';

      setError(
        typeof message === 'string' ? message : 'Admin login failed.'
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="login-page">
      <div className="login-card">
        <div className="login-card__brand">
          <div className="login-card__logo-wrapper">
            <Scale size={32} color="#1a6b5a" />
          </div>
          <h1 className="login-card__title">LEXIS</h1>
          <p className="login-card__subtitle">
            Administrator Portal
          </p>
        </div>

        {error && (
          <div className="login-error" role="alert">
            <AlertTriangle size={16} />
            <span>{error}</span>
          </div>
        )}

        <form
          onSubmit={handleSubmit}
          className="login-form"
          noValidate
        >
          <label htmlFor="admin-email" className="login-label">
            Admin Email
          </label>

          <div className="login-input-group">
            <span className="login-input-icon" aria-hidden="true">
              <Mail size={18} />
            </span>
            <input
              id="admin-email"
              type="email"
              className="input-field login-email-input"
              placeholder="admin@example.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="username"
              disabled={loading}
              required
            />
          </div>

          <label
            htmlFor="admin-password"
            className="login-label"
          >
            Password
          </label>

          <div className="login-input-group">
            <span className="login-input-icon" aria-hidden="true">
              <Lock size={18} />
            </span>
            <input
              id="admin-password"
              type="password"
              className="input-field login-email-input"
              placeholder="Enter admin password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              disabled={loading}
              required
            />
          </div>

          <button
            type="submit"
            className="btn btn-primary login-submit-btn"
            disabled={loading || !email.trim() || !password}
          >
            {loading ? (
              'Signing in…'
            ) : (
              <span
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 6,
                }}
              >
                Admin Sign In <ArrowRight size={15} />
              </span>
            )}
          </button>
        </form>

        <p className="login-hint">
          This portal is restricted to authorized administrators.
        </p>

        <button
          type="button"
          className="btn btn-link"
          onClick={() => navigate('/login')}
        >
          Sign in as a citizen instead
        </button>
      </div>
    </div>
  );
}

export default AdminLogin;
