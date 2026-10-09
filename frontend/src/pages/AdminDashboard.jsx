/*
 * frontend/src/pages/AdminDashboard.jsx
 * ──────────────────────────────────────────────────────────────────────────────
 * LEXIS — Admin Panel Dashboard (Module 12)
 *
 * FEATURES:
 *   1. Usage Analytics: Overview stats & per-agent metrics (all 6 agents)
 *      pulled from real MongoDB reflection logs (Module 11).
 *   2. User Management: List users, check role, suspend & reactivate accounts.
 *      Suspended users cannot log in.
 *   3. Moderation Queue: Surfaces Confirmation Agent failures where max retries
 *      were reached and an honest fallback was presented to the citizen.
 * ──────────────────────────────────────────────────────────────────────────────
 */

import React, { useState, useEffect } from 'react';
import {
  BarChart3,
  Users,
  ShieldCheck,
  ShieldAlert,
  RefreshCw,
  AlertTriangle,
  Loader2,
  CheckCircle2,
  Cpu,
  TrendingUp,
  UserX,
  Ban,
  Sliders,
} from 'lucide-react';
import {
  getAdminAnalyticsOverview,
  getAdminAgentAnalytics,
  getAdminUsers,
  suspendUser,
  reactivateUser,
  getModerationQueue,
} from '../services/api';
import './AdminDashboard.css';

export default function AdminDashboard() {
  const [activeTab, setActiveTab] = useState('analytics');

  // Loading & Error States
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);
  const [actionLoading, setActionLoading] = useState(null);

  // Data States
  const [overview, setOverview] = useState(null);
  const [agentMetrics, setAgentMetrics] = useState([]);
  const [users, setUsers] = useState([]);
  const [moderationQueue, setModerationQueue] = useState([]);

  // Fetch all admin data
  const loadDashboardData = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const [overviewRes, agentRes, usersRes, modRes] = await Promise.all([
        getAdminAnalyticsOverview(),
        getAdminAgentAnalytics(),
        getAdminUsers(0, 100),
        getModerationQueue(50),
      ]);

      setOverview(overviewRes.data);
      setAgentMetrics(agentRes.data);
      setUsers(usersRes.data);
      setModerationQueue(modRes.data);
    } catch (err) {
      console.error('Failed to load admin panel data:', err);
      const msg = err.response?.data?.detail || 'Failed to load admin dashboard data. Ensure your user account has role="admin".';
      setError(msg);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadDashboardData();
  }, []);

  // Suspend Handler
  const handleSuspend = async (userId) => {
    setActionLoading(userId);
    try {
      await suspendUser(userId);
      setUsers((prev) =>
        prev.map((u) => (u.id === userId ? { ...u, is_active: false } : u))
      );
    } catch (err) {
      alert(err.response?.data?.detail || 'Failed to suspend user.');
    } finally {
      setActionLoading(null);
    }
  };

  // Reactivate Handler
  const handleReactivate = async (userId) => {
    setActionLoading(userId);
    try {
      await reactivateUser(userId);
      setUsers((prev) =>
        prev.map((u) => (u.id === userId ? { ...u, is_active: true } : u))
      );
    } catch (err) {
      alert(err.response?.data?.detail || 'Failed to reactivate user.');
    } finally {
      setActionLoading(null);
    }
  };

  if (isLoading) {
    return (
      <div className="admin-container">
        <div className="admin-empty-state">
          <Loader2 size={38} className="spinning-icon" />
          <div className="admin-empty-title">Loading Admin Dashboard</div>
          <div className="admin-empty-desc">Aggregating real reflection logs and user data...</div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="admin-container">
        <div className="admin-empty-state" style={{ borderColor: '#fca5a5' }}>
          <AlertTriangle size={38} color="#ef4444" />
          <div className="admin-empty-title" style={{ color: '#dc2626' }}>Access Denied or Error</div>
          <div className="admin-empty-desc">{error}</div>
          <button className="admin-refresh-btn" onClick={loadDashboardData} style={{ marginTop: '1rem' }}>
            <RefreshCw size={14} />
            <span>Retry</span>
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="admin-container">
      {/* Header Banner */}
      <div className="admin-header">
        <div className="admin-header-left">
          <div className="admin-header-title">
            <div className="admin-icon-wrapper">
              <Sliders size={26} color="#ffffff" />
            </div>
            <div>
              <h1>Platform Admin Dashboard</h1>
              <div className="admin-header-sub">
                Real-time reflection analytics, user access control, and self-correction moderation queue.
              </div>
            </div>
          </div>
        </div>
        <div className="admin-header-right">
          <span className="admin-badge">Module 12</span>
          <button className="admin-refresh-btn" onClick={loadDashboardData} disabled={isLoading}>
            <RefreshCw size={14} className={isLoading ? 'spinning-icon' : ''} />
            <span>Refresh Data</span>
          </button>
        </div>
      </div>

      {/* Tabs Bar */}
      <div className="admin-tabs">
        <button
          className={`admin-tab-btn ${activeTab === 'analytics' ? 'active' : ''}`}
          onClick={() => setActiveTab('analytics')}
        >
          <BarChart3 size={15} />
          <span>Usage Analytics ({overview?.total_sessions_logged || 0})</span>
        </button>
        <button
          className={`admin-tab-btn ${activeTab === 'users' ? 'active' : ''}`}
          onClick={() => setActiveTab('users')}
        >
          <Users size={15} />
          <span>User Management ({users.length})</span>
        </button>
        <button
          className={`admin-tab-btn ${activeTab === 'moderation' ? 'active' : ''}`}
          onClick={() => setActiveTab('moderation')}
        >
          <ShieldAlert size={15} />
          <span>Moderation Queue ({moderationQueue.length})</span>
        </button>
      </div>

      {/* TAB 1: USAGE ANALYTICS */}
      {activeTab === 'analytics' && (
        <>
          {/* Top KPI Cards */}
          <div className="admin-kpi-grid">
            <div className="admin-kpi-card total">
              <span className="admin-kpi-label">Total Sessions</span>
              <span className="admin-kpi-value">{overview?.total_sessions_logged || 0}</span>
              <span className="admin-kpi-sub">Logged in reflection store</span>
            </div>
            <div className="admin-kpi-card pass">
              <span className="admin-kpi-label">Confirmation Pass Rate</span>
              <span className="admin-kpi-value green">
                {overview?.pass_rate_percentage || 0}%
              </span>
              <span className="admin-kpi-sub">Passed validation on 1st try</span>
            </div>
            <div className="admin-kpi-card fail">
              <span className="admin-kpi-label">Fallback Rate</span>
              <span className="admin-kpi-value red">
                {overview?.fallback_rate_percentage || 0}%
              </span>
              <span className="admin-kpi-sub">Exhausted max retries (3)</span>
            </div>
            <div className="admin-kpi-card retry">
              <span className="admin-kpi-label">Total Retries Executed</span>
              <span className="admin-kpi-value amber">
                {overview?.total_retries || 0}
              </span>
              <span className="admin-kpi-sub">Self-correction loops</span>
            </div>
            <div className="admin-kpi-card contradiction">
              <span className="admin-kpi-label">Contradictions Caught</span>
              <span className="admin-kpi-value purple">
                {overview?.total_contradictions || 0}
              </span>
              <span className="admin-kpi-sub">Rule C1: Legal Act mismatches</span>
            </div>
          </div>

          {/* Per-Agent Breakdown Section */}
          <div className="admin-section">
            <div className="admin-section-title">
              <Cpu size={18} color="#134e42" />
              <span>Per-Agent Self-Correction Metrics (All 6 Agents)</span>
            </div>

            {overview?.total_sessions_logged === 0 ? (
              <div className="admin-empty-state">
                <TrendingUp size={36} color="#10b981" />
                <div className="admin-empty-title">No Evaluation Logs Recorded Yet</div>
                <div className="admin-empty-desc">
                  Metrics are pulled live from real MongoDB reflection logs. As citizens send queries to
                  Rights, Drafter, Analyzer, Scam, Filing, or Vault agents, real evaluation metrics will appear here automatically.
                </div>
              </div>
            ) : (
              <div className="admin-agent-grid">
                {agentMetrics.map((agent) => (
                  <div key={agent.agent_id} className="agent-card">
                    <div className="agent-card-header">
                      <span className="agent-name">Agent: {agent.agent_id}</span>
                      <span className="agent-total-pill">{agent.total_queries} queries</span>
                    </div>

                    <div className="agent-stats-row">
                      <div className="stat-item">
                        <span className="stat-val green">{agent.passed_queries}</span>
                        <span className="stat-lbl">Passed</span>
                      </div>
                      <div className="stat-item">
                        <span className="stat-val red">{agent.fallback_queries}</span>
                        <span className="stat-lbl">Fallback</span>
                      </div>
                      <div className="stat-item">
                        <span className="stat-val amber">{agent.retry_count_total}</span>
                        <span className="stat-lbl">Retries</span>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </>
      )}

      {/* TAB 2: USER MANAGEMENT */}
      {activeTab === 'users' && (
        <div className="admin-section">
          <div className="admin-section-title">
            <Users size={18} color="#134e42" />
            <span>Registered User Accounts & Access Control</span>
          </div>

          {users.length === 0 ? (
            <div className="admin-empty-state">
              <UserX size={36} color="#94a3b8" />
              <div className="admin-empty-title">No Registered Users Found</div>
              <div className="admin-empty-desc">No accounts have logged in via OTP yet.</div>
            </div>
          ) : (
            <div className="admin-table-container">
              <table className="admin-table">
                <thead>
                  <tr>
                    <th>User ID</th>
                    <th>Phone Number</th>
                    <th>Role</th>
                    <th>Status</th>
                    <th>Registered At</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {users.map((u) => (
                    <tr key={u.id}>
                      <td style={{ fontFamily: 'monospace', fontSize: '0.8rem', color: '#64748b' }}>
                        {u.id}
                      </td>
                      <td style={{ fontWeight: 600, color: '#0f172a' }}>{u.phone}</td>
                      <td>
                        <span
                          className="admin-badge"
                          style={{
                            background: u.role === 'admin' ? '#ecfdf5' : '#f8fafc',
                            color: u.role === 'admin' ? '#065f46' : '#475569',
                            borderColor: u.role === 'admin' ? '#a7f3d0' : '#cbd5e1',
                          }}
                        >
                          {u.role}
                        </span>
                      </td>
                      <td>
                        {u.is_active ? (
                          <span className="status-badge active">
                            <CheckCircle2 size={12} /> Active
                          </span>
                        ) : (
                          <span className="status-badge suspended">
                            <Ban size={12} /> Suspended
                          </span>
                        )}
                      </td>
                      <td style={{ fontSize: '0.8rem', color: '#64748b' }}>
                        {new Date(u.created_at).toLocaleString()}
                      </td>
                      <td>
                        {u.is_active ? (
                          <button
                            className="action-btn suspend"
                            onClick={() => handleSuspend(u.id)}
                            disabled={actionLoading === u.id}
                          >
                            {actionLoading === u.id ? 'Processing...' : 'Suspend Account'}
                          </button>
                        ) : (
                          <button
                            className="action-btn reactivate"
                            onClick={() => handleReactivate(u.id)}
                            disabled={actionLoading === u.id}
                          >
                            {actionLoading === u.id ? 'Processing...' : 'Reactivate'}
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* TAB 3: MODERATION QUEUE */}
      {activeTab === 'moderation' && (
        <div className="admin-section">
          <div className="admin-section-title">
            <ShieldAlert size={18} color="#134e42" />
            <span>Moderation Queue — Surfacing Confirmation Failures</span>
          </div>

          <div style={{ fontSize: '0.875rem', color: '#64748b', marginBottom: '0.75rem' }}>
            Surfaces session logs where the Confirmation Agent exhausted max retries (3 attempts) and presented an honest fallback notice to the citizen.
          </div>

          {moderationQueue.length === 0 ? (
            <div className="admin-empty-state">
              <CheckCircle2 size={38} color="#10b981" />
              <div className="admin-empty-title">Moderation Queue Clean</div>
              <div className="admin-empty-desc">
                No repeated Confirmation Agent rejections recorded. All agent outputs have either passed validation or met standard response criteria.
              </div>
            </div>
          ) : (
            <div className="moderation-list">
              {moderationQueue.map((item, idx) => (
                <div key={idx} className="moderation-item-card">
                  <div className="mod-header">
                    <span className="mod-session">Session: {item.session_id}</span>
                    <span className="mod-time">{new Date(item.timestamp).toLocaleString()}</span>
                  </div>

                  <div className="mod-reason">
                    <strong>Rejection Reason:</strong> {item.rejection_reason || 'Max retries exhausted'}
                  </div>

                  <div className="mod-footer">
                    <span><strong>Agents Checked:</strong> {item.agents_checked.join(', ')}</span>
                    <span><strong>Retries Used:</strong> {item.retry_count} / 3</span>
                    {item.contradiction_caught && (
                      <span style={{ color: '#9333ea' }}>
                        <strong>Contradiction:</strong> {item.contradiction_caught}
                      </span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
