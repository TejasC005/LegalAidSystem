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
  uploadKnowledgeBaseDocument,
  getKnowledgeBaseDocuments,
  getKnowledgeBaseDocument,
  activateKnowledgeBaseDocument,
  deactivateKnowledgeBaseDocument,
  deleteKnowledgeBaseDocument,
  reprocessKnowledgeBaseDocument,
} from '../services/api';
import ScamIntelligenceSection from '../components/dashboard/ScamIntelligenceSection';
import AdminTeamSection from '../components/dashboard/AdminTeamSection';
import CollectionsExplorerSection from '../components/dashboard/CollectionsExplorerSection';
import './AdminDashboard.css';

const NAV_ITEMS = [
  { id: 'overview', label: 'Overview', icon: '◫' },
  { id: 'scam_intel', label: 'Scam Intelligence', icon: '🛡' },
  { id: 'knowledge', label: 'Legal Knowledge Base', icon: '⚖' },
  { id: 'agents', label: 'Agent Analytics', icon: '◇' },
  { id: 'users', label: 'Citizens & Users', icon: '♙' },
  { id: 'admins', label: 'Admin Team', icon: '👑' },
  { id: 'collections', label: 'Collections Explorer', icon: '🗄' },
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
  const [kbDocs, setKbDocs] = useState([]);
  const [selectedKbDoc, setSelectedKbDoc] = useState(null);
  const [inspectLoading, setInspectLoading] = useState(false);
  const [uploadingKb, setUploadingKb] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [busyDocId, setBusyDocId] = useState('');

  // Upload form state
  const [kbFile, setKbFile] = useState(null);
  const [kbTitle, setKbTitle] = useState('');
  const [kbActName, setKbActName] = useState('');
  const [kbTopic, setKbTopic] = useState('');
  const [kbJurisdiction, setKbJurisdiction] = useState('India');
  const [kbAuthority, setKbAuthority] = useState('');
  const [kbVersion, setKbVersion] = useState('1.0');
  const [kbEffectiveDate, setKbEffectiveDate] = useState('');
  const [kbAutoActivate, setKbAutoActivate] = useState(true);

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
        getKnowledgeBaseDocuments(),
      ]);

      const labels = [
        'Overview analytics',
        'Agent analytics',
        'User list',
        'Moderation queue',
        'Legal Knowledge Base',
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
        if (index === 4) setKbDocs(Array.isArray(data) ? data : []);
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

  const handleKbFileChange = (e) => {
    const file = e.target.files?.[0];
    if (file) {
      setKbFile(file);
      const cleanStem = file.name.replace(/\.[^/.]+$/, '').replace(/[-_]+/g, ' ').trim();
      const titleFormatted = cleanStem.charAt(0).toUpperCase() + cleanStem.slice(1);
      if (!kbTitle) setKbTitle(titleFormatted);
      if (!kbActName) setKbActName(titleFormatted);
      if (!kbTopic) setKbTopic('Citizen Rights');
    }
  };

  const handleUploadKb = async (e) => {
    e.preventDefault();
    if (!kbFile) {
      setError('Please select a file to upload (.pdf, .docx, or .json).');
      return;
    }
    setUploadingKb(true);
    setUploadProgress(0);
    setError('');
    setNotice('');

    const formData = new FormData();
    formData.append('file', kbFile);
    if (kbTitle) formData.append('title', kbTitle);
    if (kbActName) formData.append('act_name', kbActName);
    if (kbTopic) formData.append('topic', kbTopic);
    if (kbJurisdiction) formData.append('jurisdiction', kbJurisdiction);
    if (kbAuthority) formData.append('authority', kbAuthority);
    if (kbVersion) formData.append('version', kbVersion);
    if (kbEffectiveDate) formData.append('effective_date', kbEffectiveDate);
    formData.append('auto_activate', kbAutoActivate ? 'true' : 'false');

    try {
      const res = await uploadKnowledgeBaseDocument(formData, (progressEvent) => {
        if (progressEvent.total) {
          const percent = Math.round((progressEvent.loaded * 100) / progressEvent.total);
          setUploadProgress(percent);
        }
      });
      setNotice(`Document "${res.data.title}" successfully uploaded and indexed with ${res.data.chunk_count} chunks.`);
      setKbFile(null);
      setKbTitle('');
      setKbActName('');
      setKbTopic('');
      setKbAuthority('');
      setKbEffectiveDate('');
      setKbVersion('1.0');
      const fileInput = document.getElementById('kb-file-input');
      if (fileInput) fileInput.value = '';
      await loadDashboard();
    } catch (err) {
      setError(
        err?.response?.data?.detail ||
        err?.message ||
        'Failed to upload legal document.'
      );
    } finally {
      setUploadingKb(false);
      setUploadProgress(0);
    }
  };

  const handleToggleDocStatus = async (doc) => {
    const isActivating = !doc.is_active;
    const actionLabel = isActivating ? 'activate' : 'deactivate';
    setBusyDocId(doc.document_id);
    setError('');
    setNotice('');

    try {
      if (isActivating) {
        await activateKnowledgeBaseDocument(doc.document_id);
        setNotice(`Document "${doc.title}" activated and vectors indexed in Qdrant.`);
      } else {
        await deactivateKnowledgeBaseDocument(doc.document_id);
        setNotice(`Document "${doc.title}" deactivated. Vectors removed from Qdrant retrieval.`);
      }
      await loadDashboard();
    } catch (err) {
      setError(err?.response?.data?.detail || err?.message || `Failed to ${actionLabel} document.`);
    } finally {
      setBusyDocId('');
    }
  };

  const handleDeleteDoc = async (doc) => {
    const confirmed = window.confirm(`Permanently delete document "${doc.title}" and remove all vectors from Qdrant?`);
    if (!confirmed) return;
    setBusyDocId(doc.document_id);
    setError('');
    setNotice('');

    try {
      await deleteKnowledgeBaseDocument(doc.document_id);
      setNotice(`Document "${doc.title}" and its vectors permanently deleted.`);
      if (selectedKbDoc?.document_id === doc.document_id) {
        setSelectedKbDoc(null);
      }
      await loadDashboard();
    } catch (err) {
      setError(err?.response?.data?.detail || err?.message || 'Failed to delete document.');
    } finally {
      setBusyDocId('');
    }
  };

  const handleReprocessDoc = async (doc) => {
    setBusyDocId(doc.document_id);
    setError('');
    setNotice('');

    try {
      const res = await reprocessKnowledgeBaseDocument(doc.document_id);
      setNotice(`Document "${doc.title}" reprocessed successfully (${res.data.chunk_count} chunks indexed).`);
      await loadDashboard();
    } catch (err) {
      setError(err?.response?.data?.detail || err?.message || 'Failed to reprocess document.');
    } finally {
      setBusyDocId('');
    }
  };

  const handleInspectDoc = async (docId) => {
    setInspectLoading(true);
    setError('');
    try {
      const res = await getKnowledgeBaseDocument(docId);
      setSelectedKbDoc(res.data);
    } catch (err) {
      setError(err?.response?.data?.detail || err?.message || 'Could not load document details.');
    } finally {
      setInspectLoading(false);
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

              {section === 'scam_intel' && <ScamIntelligenceSection />}

              {section === 'admins' && <AdminTeamSection />}

              {section === 'collections' && <CollectionsExplorerSection />}

              {section === 'knowledge' && (
                <>
                  <div className="admin-section-heading">
                    <div>
                      <h2>Official Legal Knowledge Base</h2>
                      <p>
                        Upload and manage authoritative legal documents (PDF, Word DOCX, JSON)
                        indexed into Qdrant for RAG-grounded retrieval by the Rights Agent.
                      </p>
                    </div>
                    <span className="admin-data-label">{kbDocs.length} LEGAL SOURCES</span>
                  </div>

                  {/* Upload Card */}
                  <section className="admin-panel kb-upload-panel">
                    <div className="admin-panel-heading">
                      <div>
                        <h3>Upload New Legal Document</h3>
                        <p>Text is extracted, chunked with section citations, embedded via BGE-M3, and indexed into Qdrant.</p>
                      </div>
                    </div>

                    <form onSubmit={handleUploadKb} className="kb-upload-form">
                      {/* File Selection Zone */}
                      <div className="kb-file-dropzone">
                        <input
                          id="kb-file-input"
                          type="file"
                          accept=".pdf,.docx,.json"
                          onChange={handleKbFileChange}
                          disabled={uploadingKb}
                          style={{ display: 'none' }}
                        />
                        <label htmlFor="kb-file-input" className="kb-file-label">
                          <span className="kb-drop-icon">📄</span>
                          {kbFile ? (
                            <div className="kb-file-selected">
                              <strong>{kbFile.name}</strong>
                              <span>{(kbFile.size / (1024 * 1024)).toFixed(2)} MB • Ready to upload</span>
                            </div>
                          ) : (
                            <div>
                              <strong>Click or drag to select a legal document</strong>
                              <span>Supported formats: PDF (.pdf), Word (.docx), JSON (.json) — Max 15 MB</span>
                            </div>
                          )}
                        </label>
                      </div>

                      {/* Metadata Form Grid */}
                      <div className="kb-form-grid">
                        <div className="kb-field">
                          <label htmlFor="kb-title">Document Title</label>
                          <input
                            id="kb-title"
                            type="text"
                            placeholder="e.g. Digital Personal Data Protection Act, 2023"
                            value={kbTitle}
                            onChange={(e) => setKbTitle(e.target.value)}
                            disabled={uploadingKb}
                          />
                        </div>

                        <div className="kb-field">
                          <label htmlFor="kb-act-name">Act / Statute Name</label>
                          <input
                            id="kb-act-name"
                            type="text"
                            placeholder="e.g. DPDP Act 2023"
                            value={kbActName}
                            onChange={(e) => setKbActName(e.target.value)}
                            disabled={uploadingKb}
                          />
                        </div>

                        <div className="kb-field">
                          <label htmlFor="kb-topic">Primary Legal Topic</label>
                          <input
                            id="kb-topic"
                            type="text"
                            placeholder="e.g. Data Privacy and Protection"
                            value={kbTopic}
                            onChange={(e) => setKbTopic(e.target.value)}
                            disabled={uploadingKb}
                          />
                        </div>

                        <div className="kb-field">
                          <label htmlFor="kb-jurisdiction">Jurisdiction</label>
                          <input
                            id="kb-jurisdiction"
                            type="text"
                            placeholder="e.g. India"
                            value={kbJurisdiction}
                            onChange={(e) => setKbJurisdiction(e.target.value)}
                            disabled={uploadingKb}
                          />
                        </div>

                        <div className="kb-field">
                          <label htmlFor="kb-authority">Enacting / Governing Authority</label>
                          <input
                            id="kb-authority"
                            type="text"
                            placeholder="e.g. Ministry of Electronics and Information Technology"
                            value={kbAuthority}
                            onChange={(e) => setKbAuthority(e.target.value)}
                            disabled={uploadingKb}
                          />
                        </div>

                        <div className="kb-field">
                          <label htmlFor="kb-version">Document Version</label>
                          <input
                            id="kb-version"
                            type="text"
                            placeholder="1.0"
                            value={kbVersion}
                            onChange={(e) => setKbVersion(e.target.value)}
                            disabled={uploadingKb}
                          />
                        </div>

                        <div className="kb-field">
                          <label htmlFor="kb-effective-date">Effective Date (optional)</label>
                          <input
                            id="kb-effective-date"
                            type="date"
                            value={kbEffectiveDate}
                            onChange={(e) => setKbEffectiveDate(e.target.value)}
                            disabled={uploadingKb}
                          />
                        </div>

                        <div className="kb-field kb-checkbox-field">
                          <label className="kb-checkbox-label">
                            <input
                              type="checkbox"
                              checked={kbAutoActivate}
                              onChange={(e) => setKbAutoActivate(e.target.checked)}
                              disabled={uploadingKb}
                            />
                            <span>Auto-activate immediately (indexes vectors in Qdrant)</span>
                          </label>
                        </div>
                      </div>

                      {uploadingKb && (
                        <div className="kb-progress-wrap">
                          <div className="kb-progress-bar">
                            <div className="kb-progress-fill" style={{ width: `${uploadProgress}%` }} />
                          </div>
                          <span>{uploadProgress > 0 ? `Uploading & indexing... ${uploadProgress}%` : 'Processing & generating embeddings...'}</span>
                        </div>
                      )}

                      <div className="kb-form-actions">
                        <button
                          type="submit"
                          className="admin-action-button success"
                          disabled={uploadingKb || !kbFile}
                        >
                          {uploadingKb ? 'Processing & Indexing…' : 'Upload & Process Document'}
                        </button>
                      </div>
                    </form>
                  </section>

                  {/* Document Inventory Table */}
                  <section className="admin-panel">
                    <div className="admin-panel-heading">
                      <div>
                        <h3>Authoritative Documents Inventory</h3>
                        <p>Active documents are queried in real time by the Rights Explainer Agent.</p>
                      </div>
                      <span className="admin-data-label">{kbDocs.length} LOADED</span>
                    </div>

                    {kbDocs.length === 0 ? (
                      <EmptyState message="No legal documents uploaded yet. Upload a PDF, Word, or JSON file above." />
                    ) : (
                      <div className="admin-table-wrap">
                        <table className="admin-table">
                          <thead>
                            <tr>
                              <th>Document & Statute</th>
                              <th>Type</th>
                              <th>Source / Authority</th>
                              <th>Version</th>
                              <th>Chunks</th>
                              <th>Status</th>
                              <th>Uploaded</th>
                              <th>Actions</th>
                            </tr>
                          </thead>
                          <tbody>
                            {kbDocs.map((doc) => (
                              <tr key={doc.document_id}>
                                <td>
                                  <div className="admin-account">
                                    <div className="admin-account-avatar kb-doc-icon">
                                      {doc.file_type === 'pdf' ? 'PDF' : doc.file_type === 'docx' ? 'DOC' : 'JSON'}
                                    </div>
                                    <div>
                                      <strong>{doc.title}</strong>
                                      <span>{doc.act_name} • {doc.file_name}</span>
                                    </div>
                                  </div>
                                </td>
                                <td>
                                  <span className={`kb-type-badge kb-type-${doc.file_type}`}>
                                    .{doc.file_type}
                                  </span>
                                </td>
                                <td>
                                  <div>
                                    <strong>{doc.authority || 'Official'}</strong>
                                    <span style={{ fontSize: '11px', color: '#778397', display: 'block' }}>{doc.jurisdiction}</span>
                                  </div>
                                </td>
                                <td>v{doc.version || '1.0'}</td>
                                <td>
                                  <strong className="admin-blue-text">{doc.chunk_count}</strong>
                                </td>
                                <td>
                                  <span className={`admin-status ${doc.is_active ? 'is-active' : 'is-suspended'}`}>
                                    <span className="admin-status-dot" />
                                    {doc.status === 'active' ? 'Active' : doc.status === 'failed' ? 'Failed' : 'Inactive'}
                                  </span>
                                </td>
                                <td>
                                  {doc.created_at ? new Date(doc.created_at).toLocaleDateString() : '—'}
                                </td>
                                <td>
                                  <div className="kb-action-group">
                                    <button
                                      type="button"
                                      className="admin-text-button"
                                      onClick={() => handleInspectDoc(doc.document_id)}
                                      disabled={inspectLoading}
                                    >
                                      Inspect
                                    </button>

                                    <button
                                      type="button"
                                      className={`admin-action-button ${doc.is_active ? 'danger' : 'success'}`}
                                      disabled={busyDocId === doc.document_id}
                                      onClick={() => handleToggleDocStatus(doc)}
                                    >
                                      {busyDocId === doc.document_id
                                        ? '...'
                                        : doc.is_active
                                          ? 'Deactivate'
                                          : 'Activate'}
                                    </button>

                                    <button
                                      type="button"
                                      className="admin-action-button"
                                      style={{ background: '#f1f5f9', color: '#334155', border: '1px solid #cbd5e1' }}
                                      disabled={busyDocId === doc.document_id}
                                      onClick={() => handleReprocessDoc(doc)}
                                      title="Reprocess and re-chunk from disk"
                                    >
                                      ↺
                                    </button>

                                    <button
                                      type="button"
                                      className="admin-action-button danger"
                                      disabled={busyDocId === doc.document_id}
                                      onClick={() => handleDeleteDoc(doc)}
                                      title="Permanently remove"
                                    >
                                      ✕
                                    </button>
                                  </div>
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </section>
                </>
              )}

              {/* Document Inspection Modal */}
              {selectedKbDoc && (
                <div className="kb-modal-backdrop" onClick={() => setSelectedKbDoc(null)}>
                  <div className="kb-modal" onClick={(e) => e.stopPropagation()}>
                    <div className="kb-modal-header">
                      <div>
                        <span className="admin-eyebrow">LEGAL DOCUMENT INSPECTION</span>
                        <h2>{selectedKbDoc.title}</h2>
                        <span className="kb-modal-sub">
                          {selectedKbDoc.act_name} • Version {selectedKbDoc.version} • {selectedKbDoc.chunk_count} chunks indexed
                        </span>
                      </div>
                      <button
                        type="button"
                        className="kb-modal-close"
                        onClick={() => setSelectedKbDoc(null)}
                      >
                        ×
                      </button>
                    </div>

                    <div className="kb-modal-body">
                      {/* Metadata Summary Pill Row */}
                      <div className="kb-modal-meta-row">
                        <div className="kb-meta-pill">
                          <span>Jurisdiction</span>
                          <strong>{selectedKbDoc.jurisdiction}</strong>
                        </div>
                        <div className="kb-meta-pill">
                          <span>Authority</span>
                          <strong>{selectedKbDoc.authority || 'Not specified'}</strong>
                        </div>
                        <div className="kb-meta-pill">
                          <span>File Format</span>
                          <strong>.{selectedKbDoc.file_type?.toUpperCase()} ({(selectedKbDoc.file_size_bytes / 1024).toFixed(1)} KB)</strong>
                        </div>
                        <div className="kb-meta-pill">
                          <span>Status</span>
                          <strong className={selectedKbDoc.is_active ? 'admin-green-text' : 'admin-red-text'}>
                            {selectedKbDoc.status?.toUpperCase()}
                          </strong>
                        </div>
                      </div>

                      {/* Text Preview */}
                      <div className="kb-modal-section">
                        <h4>Extracted Content Preview</h4>
                        <pre className="kb-preview-box">
                          {selectedKbDoc.preview_text || 'No preview available.'}
                        </pre>
                      </div>

                      {/* Chunks Breakdown */}
                      <div className="kb-modal-section">
                        <h4>Indexed Chunks & Citations ({selectedKbDoc.chunks?.length || 0})</h4>
                        <div className="kb-chunks-list">
                          {selectedKbDoc.chunks?.map((chunk, idx) => (
                            <div key={chunk.chunk_id || idx} className="kb-chunk-card">
                              <div className="kb-chunk-head">
                                <span className="kb-chunk-num">#{idx + 1}</span>
                                <strong>{chunk.section || 'General Provision'}</strong>
                                <span className="kb-chunk-cite">[Source: {chunk.citation}]</span>
                              </div>
                              <p className="kb-chunk-text">{chunk.content}</p>
                            </div>
                          ))}
                        </div>
                      </div>
                    </div>

                    <div className="kb-modal-footer">
                      <button
                        type="button"
                        className="admin-action-button"
                        onClick={() => setSelectedKbDoc(null)}
                      >
                        Close Preview
                      </button>
                    </div>
                  </div>
                </div>
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
