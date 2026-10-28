/*
 * frontend/src/pages/ProfileSetup.jsx
 * ──────────────────────────────────────────────────────────────────────────────
 * LEXIS — Profile Setup Page (Module 13B)
 *
 * Shown once after first login if profile is incomplete.
 * Allows citizen to complete their full name, address, language, and DOB.
 * ──────────────────────────────────────────────────────────────────────────────
 */

import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { updateUserProfile } from '../services/api';
import { useAuth } from '../context/AuthContext';
import './ProfileSetup.css';

function ProfileSetup() {
  const { user, setUser } = useAuth();
  const navigate = useNavigate();

  const [fullName, setFullName] = useState(user?.profile?.full_name || '');
  const [address, setAddress] = useState(user?.profile?.address || '');
  const [prefLang, setPrefLang] = useState(user?.profile?.preferred_language || 'en');
  const [dob, setDob] = useState(user?.profile?.date_of_birth || '');
  const [notifPref, setNotifPref] = useState(user?.profile?.notification_preference || 'sms');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  async function handleSubmit(e) {
    e.preventDefault();
    setError('');

    if (!fullName.trim()) {
      setError('Full name is required.');
      return;
    }

    setLoading(true);
    try {
      const res = await updateUserProfile({
        full_name: fullName.trim(),
        address: address.trim() || undefined,
        preferred_language: prefLang,
        date_of_birth: dob || undefined,
        notification_preference: notifPref,
      });

      // Update auth context user state
      const updatedUser = {
        ...user,
        profile: res.data.profile,
        profile_complete: true,
      };
      localStorage.setItem('lexis_user', JSON.stringify(updatedUser));
      if (setUser) setUser(updatedUser);

      navigate('/');
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to update profile. Please try again.');
    } finally {
      setLoading(false);
    }
  }

  function handleSkip() {
    navigate('/');
  }

  return (
    <div className="profile-setup-container">
      <div className="profile-setup-header">
        <h2>Complete Your Profile</h2>
        <p>Help LEXIS personalize your legal guidance and deadline alerts.</p>
      </div>

      {error && <div className="login-error" role="alert">{error}</div>}

      <form onSubmit={handleSubmit} className="profile-form-grid">
        <div className="form-group">
          <label htmlFor="fullName">Full Name *</label>
          <input
            id="fullName"
            type="text"
            placeholder="e.g. Ramesh Kumar"
            value={fullName}
            onChange={(e) => setFullName(e.target.value)}
            required
            disabled={loading}
          />
        </div>

        <div className="form-group">
          <label htmlFor="address">Address (Optional)</label>
          <textarea
            id="address"
            rows="3"
            placeholder="Your city / state address for legal document drafting"
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
          <label htmlFor="dob">Date of Birth (Optional)</label>
          <input
            id="dob"
            type="date"
            value={dob}
            onChange={(e) => setDob(e.target.value)}
            disabled={loading}
          />
        </div>

        <div className="form-group">
          <label htmlFor="notifPref">Deadline Reminder Preference</label>
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

        <div className="form-actions">
          <button type="button" className="btn-skip" onClick={handleSkip} disabled={loading}>
            Skip for now
          </button>
          <button type="submit" className="btn btn-primary" disabled={loading}>
            {loading ? 'Saving...' : 'Save & Continue →'}
          </button>
        </div>
      </form>
    </div>
  );
}

export default ProfileSetup;
