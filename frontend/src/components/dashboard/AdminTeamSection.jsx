import React, { useState, useEffect, useCallback } from 'react';
import {
  getAdminTeam,
  createAdmin,
  updateAdminStatus,
  resetAdminPassword,
} from '../../services/api';
import { useAuth } from '../../context/AuthContext';

export default function AdminTeamSection() {
  const { user: currentUser } = useAuth();
  const [admins, setAdmins] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busyAdminId, setBusyAdminId] = useState('');

  // Add Admin Modal State
  const [showAddModal, setShowAddModal] = useState(false);
  const [newEmail, setNewEmail] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [newFullName, setNewFullName] = useState('');
  const [submitting, setSubmitting] = useState(false);

  // Reset Password Modal State
  const [showPwdModal, setShowPwdModal] = useState(false);
  const [targetAdmin, setTargetAdmin] = useState(null);
  const [resetPwd, setResetPwd] = useState('');
  const [resetting, setResetting] = useState(false);

  const loadAdmins = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const response = await getAdminTeam();
      setAdmins(Array.isArray(response.data) ? response.data : []);
    } catch (err) {
      setError(err.response?.data?.detail || err.message || 'Failed to load administrator accounts.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadAdmins();
  }, [loadAdmins]);

  const handleCreateAdmin = async (e) => {
    e.preventDefault();
    if (!newEmail.trim() || !newPassword) {
      setError('Please provide both email and a strong password.');
      return;
    }
    if (newPassword.length < 6) {
      setError('Password must be at least 6 characters long.');
      return;
    }

    setSubmitting(true);
    setError('');
    setNotice('');

    try {
      const res = await createAdmin({
        email: newEmail.trim().toLowerCase(),
        password: newPassword,
        full_name: newFullName.trim() || null,
      });
      setNotice(`Administrator '${res.data.email}' was successfully created!`);
      setShowAddModal(false);
      setNewEmail('');
      setNewPassword('');
      setNewFullName('');
      await loadAdmins();
    } catch (err) {
      setError(err.response?.data?.detail || err.message || 'Failed to create administrator.');
    } finally {
      setSubmitting(false);
    }
  };

  const handleToggleStatus = async (admin) => {
    const isSelf = currentUser && (currentUser.id === admin.id || currentUser.user_id === admin.id || currentUser.email === admin.email);
    if (isSelf && admin.is_active) {
      setError('Safety protection: You cannot deactivate your own administrator account.');
      return;
    }

    setBusyAdminId(admin.id);
    setError('');
    setNotice('');

    try {
      await updateAdminStatus(admin.id, !admin.is_active);
      setNotice(`Administrator '${admin.email}' is now ${!admin.is_active ? 'active' : 'suspended'}.`);
      await loadAdmins();
    } catch (err) {
      setError(err.response?.data?.detail || err.message || 'Failed to update administrator status.');
    } finally {
      setBusyAdminId('');
    }
  };

  const handleResetPassword = async (e) => {
    e.preventDefault();
    if (!resetPwd || resetPwd.length < 6) {
      setError('New password must be at least 6 characters.');
      return;
    }

    setResetting(true);
    setError('');
    setNotice('');

    try {
      await resetAdminPassword(targetAdmin.id, resetPwd);
      setNotice(`Password for administrator '${targetAdmin.email}' has been successfully reset!`);
      setShowPwdModal(false);
      setTargetAdmin(null);
      setResetPwd('');
    } catch (err) {
      setError(err.response?.data?.detail || err.message || 'Failed to reset password.');
    } finally {
      setResetting(false);
    }
  };

  return (
    <section className="admin-panel">
      <div className="admin-panel-heading">
        <div>
          <h3>Platform Administrators</h3>
          <p>
            Manage authorized administrator credentials with independent access to the LEXIS Admin Dashboard.
          </p>
        </div>
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
          <span className="admin-data-label">{admins.length} ADMINS</span>
          <button
            type="button"
            className="admin-action-button success"
            onClick={() => {
              setError('');
              setShowAddModal(true);
            }}
          >
            + Add Administrator
          </button>
        </div>
      </div>

      {notice && <div className="admin-notice">{notice}</div>}
      {error && <div className="admin-error-banner">{error}</div>}

      {/* Add Admin Modal */}
      {showAddModal && (
        <div className="admin-modal-backdrop">
          <div className="admin-modal-content">
            <div className="admin-modal-header">
              <h4>Create New Administrator</h4>
              <button
                type="button"
                className="admin-modal-close"
                onClick={() => setShowAddModal(false)}
              >
                &times;
              </button>
            </div>
            <form onSubmit={handleCreateAdmin}>
              <div className="admin-form-group">
                <label>Admin Email *</label>
                <input
                  type="email"
                  className="input-field"
                  placeholder="admin@example.com"
                  value={newEmail}
                  onChange={(e) => setNewEmail(e.target.value)}
                  required
                />
              </div>

              <div className="admin-form-group">
                <label>Full Name (Optional)</label>
                <input
                  type="text"
                  className="input-field"
                  placeholder="e.g. Adv. John Doe"
                  value={newFullName}
                  onChange={(e) => setNewFullName(e.target.value)}
                />
              </div>

              <div className="admin-form-group">
                <label>Password * (Minimum 6 characters)</label>
                <input
                  type="password"
                  className="input-field"
                  placeholder="Enter secure password"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  required
                />
              </div>

              <div className="admin-modal-actions">
                <button
                  type="button"
                  className="admin-action-button"
                  onClick={() => setShowAddModal(false)}
                  disabled={submitting}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="admin-action-button success"
                  disabled={submitting}
                >
                  {submitting ? 'Creating...' : 'Create Admin'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Reset Password Modal */}
      {showPwdModal && targetAdmin && (
        <div className="admin-modal-backdrop">
          <div className="admin-modal-content">
            <div className="admin-modal-header">
              <h4>Reset Password: {targetAdmin.email}</h4>
              <button
                type="button"
                className="admin-modal-close"
                onClick={() => {
                  setShowPwdModal(false);
                  setTargetAdmin(null);
                }}
              >
                &times;
              </button>
            </div>
            <form onSubmit={handleResetPassword}>
              <div className="admin-form-group">
                <label>New Password * (Min 6 characters)</label>
                <input
                  type="password"
                  className="input-field"
                  placeholder="Enter new password"
                  value={resetPwd}
                  onChange={(e) => setResetPwd(e.target.value)}
                  required
                />
              </div>

              <div className="admin-modal-actions">
                <button
                  type="button"
                  className="admin-action-button"
                  onClick={() => {
                    setShowPwdModal(false);
                    setTargetAdmin(null);
                  }}
                  disabled={resetting}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="admin-action-button success"
                  disabled={resetting}
                >
                  {resetting ? 'Updating...' : 'Update Password'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {loading ? (
        <div className="admin-loading">Loading administrators list...</div>
      ) : admins.length === 0 ? (
        <div className="admin-empty">No administrator records found.</div>
      ) : (
        <div className="admin-table-wrap">
          <table className="admin-table">
            <thead>
              <tr>
                <th>Administrator</th>
                <th>Role</th>
                <th>Status</th>
                <th>Created</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {admins.map((admin) => {
                const isCurrent =
                  currentUser &&
                  (currentUser.id === admin.id ||
                    currentUser.user_id === admin.id ||
                    currentUser.email === admin.email);

                return (
                  <tr key={admin.id}>
                    <td>
                      <div className="admin-account">
                        <div
                          className="admin-account-avatar"
                          style={{
                            backgroundColor: '#1a6b5a',
                            color: '#fff',
                            fontWeight: 'bold',
                          }}
                        >
                          {(admin.full_name || admin.email || 'A')[0].toUpperCase()}
                        </div>
                        <div>
                          <strong>
                            {admin.full_name ? `${admin.full_name} ` : ''}
                            {admin.email}
                            {isCurrent && (
                              <span
                                style={{
                                  marginLeft: '8px',
                                  fontSize: '0.75rem',
                                  color: '#06d6a0',
                                  background: 'rgba(6,214,160,0.15)',
                                  padding: '2px 6px',
                                  borderRadius: '4px',
                                }}
                              >
                                You
                              </span>
                            )}
                          </strong>
                          <span>ID: {admin.id}</span>
                        </div>
                      </div>
                    </td>
                    <td>
                      <span className="admin-role-badge">admin</span>
                    </td>
                    <td>
                      <span
                        className={`admin-status-badge ${
                          admin.is_active ? 'active' : 'suspended'
                        }`}
                      >
                        {admin.is_active ? 'Active' : 'Suspended'}
                      </span>
                    </td>
                    <td>
                      {admin.created_at
                        ? new Date(admin.created_at).toLocaleDateString()
                        : '—'}
                    </td>
                    <td>
                      <div style={{ display: 'flex', gap: '6px' }}>
                        <button
                          type="button"
                          className="admin-action-button"
                          onClick={() => {
                            setTargetAdmin(admin);
                            setResetPwd('');
                            setShowPwdModal(true);
                          }}
                        >
                          Reset Pwd
                        </button>
                        {isCurrent ? (
                          <span className="admin-protected-label">Active Self</span>
                        ) : (
                          <button
                            type="button"
                            className={`admin-action-button ${
                              admin.is_active ? 'danger' : 'success'
                            }`}
                            disabled={busyAdminId === admin.id}
                            onClick={() => handleToggleStatus(admin)}
                          >
                            {busyAdminId === admin.id
                              ? 'Saving...'
                              : admin.is_active
                              ? 'Suspend'
                              : 'Reactivate'}
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
