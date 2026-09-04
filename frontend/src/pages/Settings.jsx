/*
 * frontend/src/pages/Settings.jsx
 * ──────────────────────────────────────────────────────────────────────────────
 * LEXIS — Account & Profile Settings Page (Module 13B)
 * ──────────────────────────────────────────────────────────────────────────────
 */

import React, { useState, useEffect } from 'react';
import {
  getUserProfile,
  updateUserProfile,
  sendEmailOtp,
  verifyEmailOtp,
  uploadProfilePicture,
  exportUserData,
  deleteAccount,
} from '../services/api';
import { useAuth } from '../context/AuthContext';
import './Settings.css';

function Settings() {
  const { user, setUser, logout } = useAuth();

  const [loading, setLoading] = useState(false);
  const [msg, setMsg] = useState('');
  const [error, setError] = useState('');

  // Profile Form state
  const [fullName, setFullName] = useState('');
  const [address, setAddress] = useState('');
  const [prefLang, setPrefLang] = useState('en');
  const [dob, setDob] = useState('');
  const [notifPref, setNotifPref] = useState('sms');
  const [picUrl, setPicUrl] = useState('');

  // Email verification state
  const [email, setEmail] = useState('');
  const [emailVerified, setEmailVerified] = useState(false);
  const [emailOtp, setEmailOtp] = useState('');
  const [emailStep, setEmailStep] = useState('input'); // 'input' | 'otp'

  useEffect(() => {
    fetchProfile();
  }, []);

  async function fetchProfile() {
    try {
      const res = await getUserProfile();
      const p = res.data.profile || {};
      setFullName(p.full_name || '');
      setAddress(p.address || '');
      setPrefLang(p.preferred_language || 'en');
      setDob(p.date_of_birth || '');
      setNotifPref(p.notification_preference || 'sms');
      setPicUrl(p.profile_picture_url || '');
      setEmail(res.data.email || '');
      setEmailVerified(res.data.email_verified || false);
    } catch (err) {
      setError('Could not load profile details.');
    }
  }

  async function handleSaveProfile(e) {
    e.preventDefault();
    setMsg('');
    setError('');
    setLoading(true);

    try {
      const res = await updateUserProfile({
        full_name: fullName.trim(),
        address: address.trim() || undefined,
        preferred_language: prefLang,
        date_of_birth: dob || undefined,
        notification_preference: notifPref,
      });
      setMsg('Profile updated successfully.');
      if (setUser && user) {
        setUser({ ...user, profile: res.data.profile });
      }
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to update profile.');
    } finally {
      setLoading(false);
    }
  }

  async function handleSendEmailOtp(e) {
    e.preventDefault();
    if (!email.trim()) return;
    setMsg('');
    setError('');
    setLoading(true);
    try {
      await sendEmailOtp(email.trim());
      setEmailStep('otp');
      setMsg('Verification OTP sent to email. Check console in dev mode.');
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to send email OTP.');
    } finally {
      setLoading(false);
    }
  }

  async function handleVerifyEmailOtp(e) {
    e.preventDefault();
    if (!emailOtp.trim()) return;
    setMsg('');
    setError('');
    setLoading(true);
    try {
      await verifyEmailOtp(email.trim(), emailOtp.trim());
      setEmailVerified(true);
      setEmailStep('input');
      setMsg('Email verified successfully!');
    } catch (err) {
      setError(err.response?.data?.detail || 'Invalid or expired OTP.');
    } finally {
      setLoading(false);
    }
  }

  async function handlePictureUpload(e) {
    const file = e.target.files[0];
    if (!file) return;
    setMsg('');
    setError('');
    setLoading(true);
    try {
      const res = await uploadProfilePicture(file);
      setPicUrl(res.data.profile_picture_url);
      setMsg('Profile picture updated.');
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to upload picture. Max 2MB images only.');
    } finally {
      setLoading(false);
    }
  }

  async function handleExport() {
    setMsg('');
    setError('');
    try {
      const res = await exportUserData();
      const blob = new Blob([JSON.stringify(res.data, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `lexis_data_export_${new Date().toISOString().split('T')[0]}.json`;
      a.click();
      URL.revokeObjectURL(url);
      setMsg('Account data exported successfully.');
    } catch (err) {
      setError('Failed to export account data.');
    }
  }

  async function handleDeleteAccount() {
    if (!window.confirm('Are you SURE you want to delete your account? All vault documents and deadlines will be permanently removed. This cannot be undone.')) {
      return;
    }
    setLoading(true);
    try {
      await deleteAccount();
      alert('Your account has been deleted.');
      logout();
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to delete account.');
      setLoading(false);
    }
  }

  return (
    <div className="settings-page">
      <div className="settings-header">
        <h2>⚙️ Settings & Profile</h2>
        <p>Manage your account, notification preferences, email, and privacy options.</p>
      </div>

      {msg && <div className="login-hint" style={{ color: '#4ade80', marginBottom: '1rem' }}>{msg}</div>}
      {error && <div className="login-error" style={{ marginBottom: '1rem' }}>{error}</div>}

      {/* ── Section 1: Profile Details ── */}
      <section className="settings-section">
        <h3>👤 Profile Details</h3>
        <form onSubmit={handleSaveProfile} className="settings-form">
          <div className="picture-upload-box">
            {picUrl ? (
              <img src={picUrl} alt="Avatar" className="avatar-preview" />
            ) : (
              <div className="avatar-preview">👤</div>
            )}
            <div>
              <label htmlFor="picFile" className="btn btn-secondary" style={{ cursor: 'pointer', display: 'inline-block' }}>
                Upload New Picture
              </label>
              <input
                id="picFile"
                type="file"
                accept="image/*"
                onChange={handlePictureUpload}
                style={{ display: 'none' }}
                disabled={loading}
              />
              <p style={{ fontSize: '0.8rem', color: '#94a3b8', marginTop: '0.25rem' }}>JPEG, PNG, WEBP max 2MB</p>
            </div>
          </div>

          <div className="form-group">
            <label htmlFor="fullName">Full Name</label>
            <input
              id="fullName"
              type="text"
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              disabled={loading}
            />
          </div>

          <div className="form-group">
            <label htmlFor="address">Address</label>
            <textarea
              id="address"
              rows="2"
              value={address}
              onChange={(e) => setAddress(e.target.value)}
              disabled={loading}
            />
          </div>

          <div className="form-group">
            <label htmlFor="prefLang">Preferred Language</label>
            <select
              id="prefLang"
              value={prefLang}
              onChange={(e) => setPrefLang(e.target.value)}
              disabled={loading}
            >
              <option value="en">English</option>
              <option value="hi">Hindi (हिंदी)</option>
              <option value="mr">Marathi (मराठी)</option>
            </select>
          </div>

          <div className="form-group">
            <label htmlFor="dob">Date of Birth</label>
            <input
              id="dob"
              type="date"
              value={dob}
              onChange={(e) => setDob(e.target.value)}
              disabled={loading}
            />
          </div>

          <div className="form-group">
            <label htmlFor="notifPref">Notification Preference</label>
            <select
              id="notifPref"
              value={notifPref}
              onChange={(e) => setNotifPref(e.target.value)}
              disabled={loading}
            >
              <option value="sms">SMS Only</option>
              <option value="email">Email Only</option>
              <option value="both">Both SMS & Email</option>
            </select>
          </div>

          <button type="submit" className="btn btn-primary" style={{ alignSelf: 'flex-start' }} disabled={loading}>
            Save Profile Changes
          </button>
        </form>
      </section>

      {/* ── Section 2: Secondary Email Verification ── */}
      <section className="settings-section">
        <h3>
          ✉️ Secondary Email Channel
          {emailVerified ? (
            <span className="status-badge verified">Verified</span>
          ) : (
            <span className="status-badge unverified">Unverified / Optional</span>
          )}
        </h3>

        <div className="email-verify-box">
          {emailStep === 'input' ? (
            <form onSubmit={handleSendEmailOtp} style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap' }}>
              <input
                type="email"
                placeholder="enter@email.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                disabled={loading || emailVerified}
                className="input-field"
                style={{ flex: 1, minWidth: '220px' }}
              />
              {!emailVerified && (
                <button type="submit" className="btn btn-primary" disabled={loading || !email}>
                  Send Verification OTP
                </button>
              )}
            </form>
          ) : (
            <form onSubmit={handleVerifyEmailOtp} style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap' }}>
              <input
                type="text"
                placeholder="Enter 6-digit OTP"
                value={emailOtp}
                onChange={(e) => setEmailOtp(e.target.value)}
                disabled={loading}
                className="input-field"
                style={{ width: '180px' }}
              />
              <button type="submit" className="btn btn-primary" disabled={loading}>
                Verify OTP
              </button>
              <button type="button" className="btn btn-ghost" onClick={() => setEmailStep('input')}>
                Cancel
              </button>
            </form>
          )}
        </div>
      </section>

      {/* ── Section 3: Data Export & Privacy ── */}
      <section className="settings-section">
        <h3>📦 Data & Privacy</h3>
        <p style={{ color: '#94a3b8', fontSize: '0.9rem', marginBottom: '1rem' }}>
          Download a full JSON dump of your profile and vault metadata.
        </p>
        <button type="button" className="btn btn-secondary" onClick={handleExport}>
          📥 Export Account Data (JSON)
        </button>
      </section>

      {/* ── Section 4: Danger Zone ── */}
      <section className="settings-section danger-zone">
        <h3>⚠️ Danger Zone</h3>
        <p style={{ color: '#94a3b8', fontSize: '0.9rem', marginBottom: '1rem' }}>
          Permanently delete your user record, vault documents, and deadlines. No soft delete.
        </p>
        <button type="button" className="btn-danger" onClick={handleDeleteAccount} disabled={loading}>
          🗑️ Delete Account & All Data
        </button>
      </section>
    </div>
  );
}

export default Settings;
