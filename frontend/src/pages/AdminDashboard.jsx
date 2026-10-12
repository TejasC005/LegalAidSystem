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

import React, { useCallback, useEffect, useState } from 'react';
import {
  getAdminAnalyticsOverview,
  getAdminAgentAnalytics,
  getAdminUsers,
  getModerationQueue,
  suspendUser,
  reactivateUser,
} from '../services/api';
import './AdminDashboard.css';

const NAV_ITEMS = [
  { id: 'overview', label: 'Overview', icon: '◫' },
  { id: 'agents', label: 'Agent Analytics', icon: '◇' },
  { id: 'users', label: 'User Management', icon: '♙' },
  { id: 'moderation', label: 'Moderation Queue', icon: '⚑' },
];

const EMPTY_OVERVIEW = {
  total_sessions_logged: 0,
  total_agent_evaluations: 0,
  pass_rate_percentage: 0,
  fail_rate_percentage: 0,
  fallback_rate_percentage: 0,
  total_retries: 0,
  total_contradictions: 0,
  agents_evaluated: [],
};

function StatCard({ label, value, suffix = '', icon, note }) {
  return (
    <article className="admin-stat-card">
      <div className="admin-stat-top">
        <span>{label}</span>
        <span className="admin-stat-icon">{icon}</span>
      </div>
      <div className="admin-stat-value">
        {value ?? 0}{suffix}
      </div>
      <div className="admin-stat-note">{note}</div>
    </article>
  );
}

function StatusBadge({ active }) {
  return (
    <span className={`admin-status ${active ? 'is-active' : 'is-suspended'}`}>
      <span className="admin-status-dot" />
      {active ? 'Active' : 'Suspended'}
    </span>
  );
}

function EmptyState({ message }) {
  return <div className="admin-empty">{message}</div>;
}

export default function AdminDashboard() {
  const [section, setSection] = useState('overview');
  const [overview, setOverview] = useState(EMPTY_OVERVIEW);
  const [agents, setAgents] = useState([]);
  const [users, setUsers] = useState([]);
  const [moderation, setModeration] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busyUser, setBusyUser] = useState('');

  const loadDashboard = useCallback(async () => {
    setLoading(true);
    setError('');

    try {
      const results = await Promise.allSettled([
        getAdminAnalyticsOverview(),
        getAdminAgentAnalytics(),
        getAdminUsers(0, 50),
        getModerationQueue(50),
      ]);

      const labels = [
        'Overview analytics',
        'Agent analytics',
        'User list',
        'Moderation queue',
      ];

      const failures = [];

      results.forEach((result, index) => {
        if (result.status === 'rejected') {
          failures.push(
            `${labels[index]}: ${
              result.reason?.response?.data?.detail ||
              result.reason?.message ||
              'Request failed'
            }`
          );
          return;
        }

        const data = result.value.data;

        if (index === 0) setOverview(data);
        if (index === 1) setAgents(Array.isArray(data) ? data : []);
        if (index === 2) setUsers(Array.isArray(data) ? data : []);
        if (index === 3) setModeration(Array.isArray(data) ? data : []);
      });

      if (failures.length) {
        setError(failures.join(' • '));
      }
    } catch (err) {
      setError(
        err?.response?.data?.detail ||
        err?.message ||
        'Unable to load dashboard data.'
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadDashboard();
  }, [loadDashboard]);

  const handleUserStatus = async (user) => {
    const action = user.is_active ? 'suspend' : 'reactivate';

    const confirmed = window.confirm(
      `Are you sure you want to ${action} this account?`
    );

    if (!confirmed) return;

    setBusyUser(user.id);
    setNotice('');
    setError('');

    try {
      if (user.is_active) {
        await suspendUser(user.id);
      } else {
        await reactivateUser(user.id);
      }

      setNotice(
        `User account ${action === 'suspend' ? 'suspended' : 'reactivated'} successfully.`
      );

      await loadDashboard();
    } catch (err) {
      setError(
        err?.response?.data?.detail ||
        err?.message ||
        `Could not ${action} this user.`
      );
    } finally {
      setBusyUser('');
    }
  };

  const totalUsers = users.length;
  const activeUsers = users.filter((user) => user.is_active).length;
  const suspendedUsers = totalUsers - activeUsers;

  const title = NAV_ITEMS.find((item) => item.id === section)?.label || 'Overview';

  return (
    <div className="admin-page">
      <aside className="admin-sidebar">
        <div className="admin-brand">
          <div className="admin-brand-mark">L</div>
          <div>
            <strong>LEXIS</strong>
            <span>Administration</span>
          </div>
        </div>

        <div className="admin-nav-label">WORKSPACE</div>

        <nav className="admin-nav" aria-label="Admin navigation">
          {NAV_ITEMS.map((item) => (
            <button
              type="button"
              key={item.id}
              className={`admin-nav-item ${section === item.id ? 'selected' : ''}`}
              onClick={() => setSection(item.id)}
            >
              <span className="admin-nav-icon">{item.icon}</span>
              <span>{item.label}</span>
              {section === item.id && <span className="admin-nav-indicator" />}
            </button>
          ))}
        </nav>

        <div className="admin-sidebar-bottom">
          <div className="admin-secure-icon">✓</div>
          <div>
            <strong>Secure workspace</strong>
            <span>Administrator access</span>
          </div>
        </div>
      </aside>

      <main className="admin-main">
        <header className="admin-topbar">
          <div className="admin-breadcrumb">
            <span>LEXIS</span>
            <span>/</span>
            <strong>{title}</strong>
          </div>

          <div className="admin-topbar-right">
            <span className="admin-live-dot" />
            <span>Admin workspace</span>
            <div className="admin-avatar">A</div>
          </div>
        </header>

        <div className="admin-content">
          <div className="admin-page-heading">
            <div>
              <div className="admin-eyebrow">LEXIS CONTROL CENTER</div>
              <h1>{title}</h1>
              <p>
                Monitor platform activity, review agent performance and manage
                registered accounts.
              </p>
            </div>

            <button
              type="button"
              className="admin-refresh-button"
              onClick={loadDashboard}
              disabled={loading}
            >
              <span>{loading ? '↻' : '⟳'}</span>
              {loading ? 'Refreshing...' : 'Refresh data'}
            </button>
          </div>

          {error && (
            <div className="admin-alert admin-alert-error" role="alert">
              <strong>Some data could not be loaded</strong>
              <span>{error}</span>
            </div>
          )}

          {notice && (
            <div className="admin-alert admin-alert-success" role="status">
              {notice}
              <button type="button" onClick={() => setNotice('')}>×</button>
            </div>
          )}

          {loading && (
            <div className="admin-loading">
              <span className="admin-spinner" />
              Loading dashboard data...
            </div>
          )}

          {!loading && (
            <>
              {section === 'overview' && (
                <>
                  <div className="admin-section-heading">
                    <div>
                      <h2>Platform overview</h2>
                      <p>Metrics reported by the existing backend.</p>
                    </div>
                    <span className="admin-data-label">LIVE API DATA</span>
                  </div>

                  <div className="admin-stats-grid">
                    <StatCard
                      label="Sessions logged"
                      value={overview.total_sessions_logged}
                      icon="◷"
                      note="Recorded reflection sessions"
                    />
                    <StatCard
                      label="Agent evaluations"
                      value={overview.total_agent_evaluations}
                      icon="◇"
                      note="Recorded agent evaluations"
                    />
                    <StatCard
                      label="Pass rate"
                      value={overview.pass_rate_percentage}
                      suffix="%"
                      icon="✓"
                      note="Evaluations marked pass"
                    />
                    <StatCard
                      label="Fallback rate"
                      value={overview.fallback_rate_percentage}
                      suffix="%"
                      icon="↻"
                      note="Evaluations marked fallback"
                    />
                  </div>

                  <div className="admin-overview-grid">
                    <section className="admin-panel">
                      <div className="admin-panel-heading">
                        <div>
                          <h3>Agent quality summary</h3>
                          <p>Pass, fail and fallback distribution</p>
                        </div>
                      </div>

                      {[
                        {
                          label: 'Passed',
                          value: overview.pass_rate_percentage,
                          color: 'green',
                        },
                        {
                          label: 'Failed',
                          value: overview.fail_rate_percentage,
                          color: 'red',
                        },
                        {
                          label: 'Fallback',
                          value: overview.fallback_rate_percentage,
                          color: 'amber',
                        },
                      ].map((metric) => (
                        <div className="admin-progress-row" key={metric.label}>
                          <div className="admin-progress-label">
                            <span>{metric.label}</span>
                            <strong>{metric.value ?? 0}%</strong>
                          </div>
                          <div className="admin-progress-track">
                            <div
                              className={`admin-progress-fill ${metric.color}`}
                              style={{
                                width: `${Math.min(100, Math.max(0, Number(metric.value) || 0))}%`,
                              }}
                            />
                          </div>
                        </div>
                      ))}

                      <div className="admin-summary-footer">
                        <span>Total retries</span>
                        <strong>{overview.total_retries ?? 0}</strong>
                        <span>Contradictions</span>
                        <strong>{overview.total_contradictions ?? 0}</strong>
                      </div>
                    </section>

                    <section className="admin-panel">
                      <div className="admin-panel-heading">
                        <div>
                          <h3>User accounts</h3>
                          <p>From the first 50 registered accounts loaded</p>
                        </div>
                        <button
                          type="button"
                          className="admin-text-button"
                          onClick={() => setSection('users')}
                        >
                          Manage users →
                        </button>
                      </div>

                      <div className="admin-user-summary">
                        <div>
                          <span>Total loaded</span>
                          <strong>{totalUsers}</strong>
                        </div>
                        <div>
                          <span>Active</span>
                          <strong className="admin-green-text">{activeUsers}</strong>
                        </div>
                        <div>
                          <span>Suspended</span>
                          <strong className="admin-red-text">{suspendedUsers}</strong>
                        </div>
                      </div>

                      <div className="admin-panel-note">
                        User counts reflect the currently loaded page, not
                        necessarily every account in the database.
                      </div>
                    </section>
                  </div>

                  <section className="admin-panel admin-agent-preview">
                    <div className="admin-panel-heading">
                      <div>
                        <h3>Agent performance</h3>
                        <p>Quick view of registered agent metrics</p>
                      </div>
                      <button
                        type="button"
                        className="admin-text-button"
                        onClick={() => setSection('agents')}
                      >
                        View all →
                      </button>
                    </div>
                    <AgentTable agents={agents.slice(0, 3)} />
                  </section>
                </>
              )}

              {section === 'agents' && (
                <section className="admin-panel">
                  <div className="admin-panel-heading">
                    <div>
                      <h3>Agent analytics</h3>
                      <p>
                        Recorded evaluations from reflection_logs. Zero values
                        mean no matching activity was recorded.
                      </p>
                    </div>
                  </div>
                  <AgentTable agents={agents} />
                </section>
              )}

              {section === 'users' && (
                <section className="admin-panel">
                  <div className="admin-panel-heading">
                    <div>
                      <h3>Registered users</h3>
                      <p>Review roles and manage account status.</p>
                    </div>
                    <span className="admin-data-label">{users.length} LOADED</span>
                  </div>

                  {users.length === 0 ? (
                    <EmptyState message="No users were returned by the API." />
                  ) : (
                    <div className="admin-table-wrap">
                      <table className="admin-table">
                        <thead>
                          <tr>
                            <th>Account</th>
                            <th>Role</th>
                            <th>Status</th>
                            <th>Created</th>
                            <th>Action</th>
                          </tr>
                        </thead>
                        <tbody>
                          {users.map((user) => (
                            <tr key={user.id}>
                              <td>
                                <div className="admin-account">
                                  <div className="admin-account-avatar">
                                    {(user.email || user.phone || 'U')[0].toUpperCase()}
                                  </div>
                                  <div>
                                    <strong>{user.email || 'No email'}</strong>
                                    <span>{user.phone || 'No phone number'}</span>
                                  </div>
                                </div>
                              </td>
                              <td>
                                <span className="admin-role-badge">
                                  {user.role || 'user'}
                                </span>
                              </td>
                              <td><StatusBadge active={user.is_active} /></td>
                              <td>
                                {user.created_at
                                  ? new Date(user.created_at).toLocaleDateString()
                                  : '—'}
                              </td>
                              <td>
                                {user.role === 'admin' ? (
                                  <span className="admin-protected-label">Protected</span>
                                ) : (
                                  <button
                                    type="button"
                                    className={`admin-action-button ${user.is_active ? 'danger' : 'success'}`}
                                    disabled={busyUser === user.id}
                                    onClick={() => handleUserStatus(user)}
                                  >
                                    {busyUser === user.id
                                      ? 'Working...'
                                      : user.is_active
                                        ? 'Suspend'
                                        : 'Reactivate'}
                                  </button>
                                )}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </section>
              )}

              {section === 'moderation' && (
                <section className="admin-panel">
                  <div className="admin-panel-heading">
                    <div>
                      <h3>Moderation queue</h3>
                      <p>
                        Fallback records surfaced by the Confirmation Agent
                        reflection logs.
                      </p>
                    </div>
                    <span className="admin-data-label">
                      {moderation.length} ITEMS
                    </span>
                  </div>

                  {moderation.length === 0 ? (
                    <EmptyState message="No fallback records are currently returned by the API." />
                  ) : (
                    <div className="admin-table-wrap">
                      <table className="admin-table">
                        <thead>
                          <tr>
                            <th>Session</th>
                            <th>Agents checked</th>
                            <th>Retries</th>
                            <th>Reason</th>
                            <th>Timestamp</th>
                          </tr>
                        </thead>
                        <tbody>
                          {moderation.map((item, index) => (
                            <tr key={`${item.session_id}-${index}`}>
                              <td><code>{item.session_id || '—'}</code></td>
                              <td>{item.agents_checked?.join(', ') || '—'}</td>
                              <td>{item.retry_count}</td>
                              <td>{item.rejection_reason || 'Not recorded'}</td>
                              <td>
                                {item.timestamp
                                  ? new Date(item.timestamp).toLocaleString()
                                  : '—'}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </section>
              )}
            </>
          )}
        </div>
      </main>
    </div>
  );
}

function AgentTable({ agents }) {
  if (!agents.length) {
    return <EmptyState message="No agent metrics are available." />;
  }

  return (
    <div className="admin-table-wrap">
      <table className="admin-table">
        <thead>
          <tr>
            <th>Agent</th>
            <th>Total</th>
            <th>Passed</th>
            <th>Failed</th>
            <th>Fallbacks</th>
            <th>Retries</th>
            <th>Contradictions</th>
          </tr>
        </thead>
        <tbody>
          {agents.map((agent) => (
            <tr key={agent.agent_id}>
              <td>
                <strong className="admin-agent-name">{agent.agent_id}</strong>
              </td>
              <td>{agent.total_queries}</td>
              <td className="admin-green-text">{agent.passed_queries}</td>
              <td className="admin-red-text">{agent.failed_queries}</td>
              <td>{agent.fallback_queries}</td>
              <td>{agent.retry_count_total}</td>
              <td>{agent.contradiction_count}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
