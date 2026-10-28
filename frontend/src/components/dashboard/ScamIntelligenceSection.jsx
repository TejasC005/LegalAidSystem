/*
 * frontend/src/components/dashboard/ScamIntelligenceSection.jsx
 * ──────────────────────────────────────────────────────────────────────────
 * LEXIS — Admin Scam Intelligence Knowledge Base Management
 *
 * Full management interface:
 *   1. Overview: Platform metrics, verified patterns, candidates, submissions
 *   2. Pattern Library: Search, filter, inspect, edit, activate/deactivate, curate
 *   3. Review Queue: Moderate citizen-discovered candidates (approve, reject, merge)
 *   4. Submission History: Audit trail of citizen document/text analyses
 * ──────────────────────────────────────────────────────────────────────────
 */

import React, { useCallback, useEffect, useState } from 'react';
import {
  ShieldAlert,
  ShieldCheck,
  AlertTriangle,
  Search,
  Plus,
  RotateCcw,
  CheckCircle2,
  XCircle,
  GitMerge,
  Eye,
  Edit,
  Trash2,
  Power,
  FileText,
  Clock,
  Layers,
  HelpCircle,
  BookOpen,
  Scale,
  Landmark,
  PhoneCall,
  Lock,
  Tag,
  AlertOctagon,
  Globe,
} from 'lucide-react';
import {
  getAdminScamAnalytics,
  getAdminScamPatterns,
  getAdminScamPattern,
  createAdminScamPattern,
  updateAdminScamPattern,
  activateAdminScamPattern,
  deactivateAdminScamPattern,
  deleteAdminScamPattern,
  getAdminScamReviewQueue,
  approveAdminScamCandidate,
  rejectAdminScamCandidate,
  mergeAdminScamCandidate,
  getAdminScamSubmissions,
} from '../../services/api';

const SCAM_CATEGORIES = [
  'All',
  'Digital Arrest',
  'Impersonation',
  'Payment/UPI',
  'KYC/Identity',
  'Investment',
  'Job/Employment',
  'Customs/Courier',
  'Lottery/Phishing',
  'Other',
];

export default function ScamIntelligenceSection() {
  const [subTab, setSubTab] = useState('overview'); // overview | library | queue | submissions
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');

  // Analytics State
  const [analytics, setAnalytics] = useState(null);

  // Pattern Library State
  const [patterns, setPatterns] = useState([]);
  const [patternTotal, setPatternTotal] = useState(0);
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedCategory, setSelectedCategory] = useState('All');
  const [selectedSeverity, setSelectedSeverity] = useState('All');
  const [selectedStatus, setSelectedStatus] = useState('All');
  const [selectedPattern, setSelectedPattern] = useState(null);
  const [showPatternModal, setShowPatternModal] = useState(false);
  const [showAddModal, setShowAddModal] = useState(false);
  const [showEditModal, setShowEditModal] = useState(false);
  const [busyPatternId, setBusyPatternId] = useState('');

  // Add/Edit Form State
  const [patternForm, setPatternForm] = useState({
    name: '',
    category: 'Other',
    description: '',
    keywords: '',
    legal_reality: '',
    recommended_action: '',
    reporting_channels: 'cybercrime.gov.in, Helpline: 1930',
    source_ref: '',
    severity: 'HIGH',
    review_notes: '',
  });

  // Review Queue State
  const [candidates, setCandidates] = useState([]);
  const [queueTotal, setQueueTotal] = useState(0);
  const [queueStatus, setQueueStatus] = useState('candidate');
  const [selectedCandidate, setSelectedCandidate] = useState(null);
  const [showApproveModal, setShowApproveModal] = useState(false);
  const [showRejectModal, setShowRejectModal] = useState(false);
  const [showMergeModal, setShowMergeModal] = useState(false);
  const [approveForm, setApproveForm] = useState({
    name: '',
    category: 'Other',
    description: '',
    keywords: '',
    legal_reality: '',
    recommended_action: '',
    reporting_channels: 'cybercrime.gov.in, Helpline: 1930',
    source_ref: '',
    severity: 'HIGH',
    review_notes: '',
  });
  const [rejectReason, setRejectReason] = useState('');
  const [mergeTargetId, setMergeTargetId] = useState('');
  const [mergeNotes, setMergeNotes] = useState('');

  // Submissions State
  const [submissions, setSubmissions] = useState([]);
  const [submissionsTotal, setSubmissionsTotal] = useState(0);

  // ── Data Fetching ──────────────────────────────────────────────────────────
  const loadData = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      if (subTab === 'overview') {
        const res = await getAdminScamAnalytics();
        setAnalytics(res.data);
      } else if (subTab === 'library') {
        const params = {};
        if (searchQuery.trim()) params.q = searchQuery.trim();
        if (selectedCategory !== 'All') params.category = selectedCategory;
        if (selectedSeverity !== 'All') params.severity = selectedSeverity;
        if (selectedStatus === 'Active') params.is_active = true;
        if (selectedStatus === 'Deactivated') params.is_active = false;
        const res = await getAdminScamPatterns(params);
        setPatterns(res.data.patterns || []);
        setPatternTotal(res.data.total || 0);
      } else if (subTab === 'queue') {
        const res = await getAdminScamReviewQueue(queueStatus, 0, 50);
        setCandidates(res.data.candidates || []);
        setQueueTotal(res.data.total || 0);
      } else if (subTab === 'submissions') {
        const res = await getAdminScamSubmissions(0, 50);
        setSubmissions(res.data.submissions || []);
        setSubmissionsTotal(res.data.total || 0);
      }
    } catch (err) {
      setError(err?.response?.data?.detail || err?.message || 'Failed to fetch data.');
    } finally {
      setLoading(false);
    }
  }, [subTab, searchQuery, selectedCategory, selectedSeverity, selectedStatus, queueStatus]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  function showTemporaryNotice(msg) {
    setNotice(msg);
    setTimeout(() => setNotice(''), 4000);
  }

  // ── Pattern Actions ────────────────────────────────────────────────────────
  async function handleToggleActivate(pattern) {
    setBusyPatternId(pattern.id);
    try {
      if (pattern.is_active) {
        await deactivateAdminScamPattern(pattern.id);
        showTemporaryNotice(`Pattern '${pattern.id}' deactivated.`);
      } else {
        await activateAdminScamPattern(pattern.id);
        showTemporaryNotice(`Pattern '${pattern.id}' activated and indexed.`);
      }
      loadData();
    } catch (err) {
      setError(err?.response?.data?.detail || 'Failed to update pattern status.');
    } finally {
      setBusyPatternId('');
    }
  }

  async function handleDeletePattern(patternId) {
    if (!window.confirm(`Are you sure you want to delete pattern '${patternId}'?`)) return;
    setBusyPatternId(patternId);
    try {
      await deleteAdminScamPattern(patternId);
      showTemporaryNotice(`Pattern '${patternId}' deleted.`);
      loadData();
    } catch (err) {
      setError(err?.response?.data?.detail || 'Failed to delete pattern.');
    } finally {
      setBusyPatternId('');
    }
  }

  async function handleCreatePattern(e) {
    e.preventDefault();
    try {
      const payload = {
        name: patternForm.name,
        category: patternForm.category,
        description: patternForm.description,
        keywords: patternForm.keywords.split(',').map(k => k.trim()).filter(Boolean),
        legal_reality: patternForm.legal_reality,
        recommended_action: patternForm.recommended_action,
        reporting_channels: patternForm.reporting_channels.split(',').map(r => r.trim()).filter(Boolean),
        source_ref: patternForm.source_ref,
        severity: patternForm.severity,
        auto_activate: true,
        review_notes: patternForm.review_notes,
      };
      await createAdminScamPattern(payload);
      setShowAddModal(false);
      showTemporaryNotice('New scam pattern created and synchronized.');
      loadData();
    } catch (err) {
      setError(err?.response?.data?.detail || 'Failed to create pattern.');
    }
  }

  async function handleEditPattern(e) {
    e.preventDefault();
    if (!selectedPattern) return;
    try {
      const payload = {
        name: patternForm.name,
        category: patternForm.category,
        description: patternForm.description,
        keywords: patternForm.keywords.split(',').map(k => k.trim()).filter(Boolean),
        legal_reality: patternForm.legal_reality,
        recommended_action: patternForm.recommended_action,
        reporting_channels: patternForm.reporting_channels.split(',').map(r => r.trim()).filter(Boolean),
        source_ref: patternForm.source_ref,
        severity: patternForm.severity,
        review_notes: patternForm.review_notes,
      };
      await updateAdminScamPattern(selectedPattern.id, payload);
      setShowEditModal(false);
      showTemporaryNotice(`Pattern '${selectedPattern.id}' updated.`);
      loadData();
    } catch (err) {
      setError(err?.response?.data?.detail || 'Failed to update pattern.');
    }
  }

  function openEditModal(pattern) {
    setSelectedPattern(pattern);
    setPatternForm({
      name: pattern.name || '',
      category: pattern.category || 'Other',
      description: pattern.description || '',
      keywords: (pattern.keywords || []).join(', '),
      legal_reality: pattern.legal_reality || '',
      recommended_action: pattern.recommended_action || '',
      reporting_channels: (pattern.reporting_channels || []).join(', '),
      source_ref: pattern.source_ref || '',
      severity: pattern.severity || 'HIGH',
      review_notes: pattern.review_notes || '',
    });
    setShowEditModal(true);
  }

  // ── Candidate Review Actions ───────────────────────────────────────────────
  function openApproveModal(cand) {
    setSelectedCandidate(cand);
    setApproveForm({
      name: cand.suggested_title || 'Suspected Scam Incident',
      category: cand.category || 'Other',
      description: cand.summary || cand.redacted_text || '',
      keywords: (cand.indicators?.threat_keywords || []).concat(cand.indicators?.impersonation_claims || []).join(', '),
      legal_reality: 'Under Indian criminal law (IPC/BNSS), no legitimate law enforcement agency conducts video-call arrests or demands advance settlement funds via UPI.',
      recommended_action: '1. Disconnect call immediately and do not transfer funds.\n2. Call National Cyber Helpline: 1930.\n3. File formal complaint on cybercrime.gov.in.',
      reporting_channels: 'cybercrime.gov.in, Helpline: 1930',
      source_ref: 'Citizen Report verified by LEXIS Administrator; MHA Cyber Crime Advisory',
      severity: cand.confidence_score >= 0.7 ? 'CRITICAL' : 'HIGH',
      review_notes: 'Approved from citizen candidate discovery queue.',
    });
    setShowApproveModal(true);
  }

  async function handleApproveCandidate(e) {
    e.preventDefault();
    if (!selectedCandidate) return;
    try {
      const payload = {
        name: approveForm.name,
        category: approveForm.category,
        description: approveForm.description,
        keywords: approveForm.keywords.split(',').map(k => k.trim()).filter(Boolean),
        legal_reality: approveForm.legal_reality,
        recommended_action: approveForm.recommended_action,
        reporting_channels: approveForm.reporting_channels.split(',').map(r => r.trim()).filter(Boolean),
        source_ref: approveForm.source_ref,
        severity: approveForm.severity,
        review_notes: approveForm.review_notes,
      };
      await approveAdminScamCandidate(selectedCandidate.candidate_id, payload);
      setShowApproveModal(false);
      showTemporaryNotice(`Candidate '${selectedCandidate.candidate_id}' approved as verified pattern.`);
      loadData();
    } catch (err) {
      setError(err?.response?.data?.detail || 'Failed to approve candidate.');
    }
  }

  async function handleRejectCandidate(e) {
    e.preventDefault();
    if (!selectedCandidate || !rejectReason.trim()) return;
    try {
      await rejectAdminScamCandidate(selectedCandidate.candidate_id, { reason: rejectReason.trim() });
      setShowRejectModal(false);
      setRejectReason('');
      showTemporaryNotice(`Candidate '${selectedCandidate.candidate_id}' rejected.`);
      loadData();
    } catch (err) {
      setError(err?.response?.data?.detail || 'Failed to reject candidate.');
    }
  }

  async function handleMergeCandidate(e) {
    e.preventDefault();
    if (!selectedCandidate || !mergeTargetId.trim()) return;
    try {
      await mergeAdminScamCandidate(selectedCandidate.candidate_id, {
        target_pattern_id: mergeTargetId.trim(),
        merge_notes: mergeNotes.trim() || 'Merged duplicate candidate.',
      });
      setShowMergeModal(false);
      setMergeTargetId('');
      setMergeNotes('');
      showTemporaryNotice(`Candidate merged into '${mergeTargetId}'.`);
      loadData();
    } catch (err) {
      setError(err?.response?.data?.detail || 'Failed to merge candidate.');
    }
  }

  return (
    <div className="scam-admin-section">
      {/* Sub Tabs */}
      <div className="scam-admin-subtabs">
        <button
          className={`scam-admin-subtab ${subTab === 'overview' ? 'active' : ''}`}
          onClick={() => setSubTab('overview')}
        >
          <Layers size={16} /> Overview Analytics
        </button>
        <button
          className={`scam-admin-subtab ${subTab === 'library' ? 'active' : ''}`}
          onClick={() => setSubTab('library')}
        >
          <BookOpen size={16} /> Pattern Library ({patternTotal || 0})
        </button>
        <button
          className={`scam-admin-subtab ${subTab === 'queue' ? 'active' : ''}`}
          onClick={() => setSubTab('queue')}
        >
          <Clock size={16} /> Review Queue
        </button>
        <button
          className={`scam-admin-subtab ${subTab === 'submissions' ? 'active' : ''}`}
          onClick={() => setSubTab('submissions')}
        >
          <FileText size={16} /> Citizen Submissions
        </button>
      </div>

      {notice && <div className="admin-banner-notice">{notice}</div>}
      {error && <div className="admin-banner-error">{error}</div>}

      {/* ── SUBTAB: OVERVIEW ──────────────────────────────────────────────── */}
      {subTab === 'overview' && (
        <div className="scam-admin-overview">
          {analytics ? (
            <>
              <div className="admin-grid-four">
                <article className="admin-stat-card">
                  <div className="admin-stat-top">
                    <span>Verified Patterns</span>
                    <ShieldCheck size={20} className="admin-green-text" />
                  </div>
                  <div className="admin-stat-value">{analytics.total_verified_patterns}</div>
                  <div className="admin-stat-note">{analytics.active_patterns_count} active in detection</div>
                </article>

                <article className="admin-stat-card">
                  <div className="admin-stat-top">
                    <span>Pending Candidates</span>
                    <Clock size={20} className="admin-yellow-text" />
                  </div>
                  <div className="admin-stat-value">{analytics.pending_candidates_count}</div>
                  <div className="admin-stat-note">Awaiting admin review</div>
                </article>

                <article className="admin-stat-card">
                  <div className="admin-stat-top">
                    <span>Citizen Uploads</span>
                    <FileText size={20} className="admin-blue-text" />
                  </div>
                  <div className="admin-stat-value">{analytics.total_citizen_submissions}</div>
                  <div className="admin-stat-note">{analytics.likely_scam_count} matched likely scams</div>
                </article>

                <article className="admin-stat-card">
                  <div className="admin-stat-top">
                    <span>Resolved Reports</span>
                    <CheckCircle2 size={20} className="admin-green-text" />
                  </div>
                  <div className="admin-stat-value">
                    {analytics.rejected_candidates_count + analytics.merged_candidates_count}
                  </div>
                  <div className="admin-stat-note">
                    {analytics.merged_candidates_count} merged, {analytics.rejected_candidates_count} rejected
                  </div>
                </article>
              </div>

              {/* Category Breakdown */}
              <div className="admin-card-section" style={{ marginTop: '1.5rem' }}>
                <h3>Scam Patterns by Threat Category</h3>
                <div className="scam-cat-grid">
                  {Object.entries(analytics.category_breakdown || {}).map(([cat, count]) => (
                    <div key={cat} className="scam-cat-pill">
                      <span className="scam-cat-name">{cat}</span>
                      <span className="scam-cat-count">{count}</span>
                    </div>
                  ))}
                </div>
              </div>

              {/* Recent Activity */}
              <div className="admin-card-section" style={{ marginTop: '1.5rem' }}>
                <h3>Recent Citizen Detection Activity</h3>
                {analytics.recent_activity?.length > 0 ? (
                  <div className="admin-table-wrap">
                    <table className="admin-table">
                      <thead>
                        <tr>
                          <th>Submission ID</th>
                          <th>Outcome</th>
                          <th>Source</th>
                          <th>Matched Pattern</th>
                          <th>Timestamp</th>
                        </tr>
                      </thead>
                      <tbody>
                        {analytics.recent_activity.map((act, i) => (
                          <tr key={i}>
                            <td><code>{act.submission_id}</code></td>
                            <td>
                              <span className={`admin-outcome-pill ${act.outcome}`}>
                                {act.outcome}
                              </span>
                            </td>
                            <td>{act.content_source}</td>
                            <td>{act.matched_pattern_id || '—'}</td>
                            <td>{new Date(act.created_at).toLocaleString()}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <div className="admin-empty">No recent detection activity recorded yet.</div>
                )}
              </div>
            </>
          ) : (
            <div className="admin-empty">{loading ? 'Loading intelligence metrics…' : 'No data available.'}</div>
          )}
        </div>
      )}

      {/* ── SUBTAB: PATTERN LIBRARY ───────────────────────────────────────── */}
      {subTab === 'library' && (
        <div className="scam-admin-library">
          {/* Controls Bar */}
          <div className="scam-library-controls">
            <div className="scam-search-box">
              <Search size={16} />
              <input
                type="text"
                placeholder="Search patterns by name, description, keyword..."
                value={searchQuery}
                onChange={e => setSearchQuery(e.target.value)}
              />
            </div>

            <div className="scam-filter-group">
              <select value={selectedCategory} onChange={e => setSelectedCategory(e.target.value)}>
                {SCAM_CATEGORIES.map(c => (
                  <option key={c} value={c}>{c === 'All' ? 'All Categories' : c}</option>
                ))}
              </select>

              <select value={selectedSeverity} onChange={e => setSelectedSeverity(e.target.value)}>
                <option value="All">All Severities</option>
                <option value="CRITICAL">Critical</option>
                <option value="HIGH">High</option>
                <option value="MEDIUM">Medium</option>
                <option value="LOW">Low</option>
              </select>

              <select value={selectedStatus} onChange={e => setSelectedStatus(e.target.value)}>
                <option value="All">All Statuses</option>
                <option value="Active">Active in Detection</option>
                <option value="Deactivated">Deactivated</option>
              </select>

              <button className="btn-add-pattern" onClick={() => setShowAddModal(true)}>
                <Plus size={16} /> Add Pattern
              </button>
            </div>
          </div>

          {/* Table */}
          <div className="admin-table-wrap">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Name & Category</th>
                  <th>Severity</th>
                  <th>Status</th>
                  <th>Keywords</th>
                  <th>Reports</th>
                  <th>Version</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {patterns.map((p) => (
                  <tr key={p.id}>
                    <td><code>{p.id}</code></td>
                    <td>
                      <strong>{p.name}</strong>
                      <div className="scam-table-cat">{p.category || 'Other'}</div>
                    </td>
                    <td>
                      <span className={`severity-badge ${p.severity}`}>
                        {p.severity}
                      </span>
                    </td>
                    <td>
                      <span className={`admin-status ${p.is_active ? 'is-active' : 'is-suspended'}`}>
                        <span className="admin-status-dot" />
                        {p.is_active ? 'Active' : 'Inactive'}
                      </span>
                    </td>
                    <td>
                      <div className="scam-kw-preview">
                        {(p.keywords || []).slice(0, 3).join(', ')}
                        {(p.keywords || []).length > 3 && ` +${p.keywords.length - 3}`}
                      </div>
                    </td>
                    <td>{p.report_count || 1}</td>
                    <td>v{p.version || '1.0'}</td>
                    <td>
                      <div className="admin-action-row">
                        <button
                          className="btn-action-icon"
                          title="View Details"
                          onClick={() => { setSelectedPattern(p); setShowPatternModal(true); }}
                        >
                          <Eye size={15} />
                        </button>
                        <button
                          className="btn-action-icon"
                          title="Edit Pattern"
                          onClick={() => openEditModal(p)}
                        >
                          <Edit size={15} />
                        </button>
                        <button
                          className={`btn-action-icon ${p.is_active ? 'btn-warn' : 'btn-success'}`}
                          title={p.is_active ? 'Deactivate' : 'Activate'}
                          disabled={busyPatternId === p.id}
                          onClick={() => handleToggleActivate(p)}
                        >
                          <Power size={15} />
                        </button>
                        <button
                          className="btn-action-icon btn-danger"
                          title="Delete Pattern"
                          disabled={busyPatternId === p.id}
                          onClick={() => handleDeletePattern(p.id)}
                        >
                          <Trash2 size={15} />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
                {patterns.length === 0 && !loading && (
                  <tr>
                    <td colSpan={8} style={{ textAlign: 'center', padding: '2rem' }}>
                      No scam patterns found matching filters.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ── SUBTAB: REVIEW QUEUE ─────────────────────────────────────────── */}
      {subTab === 'queue' && (
        <div className="scam-admin-queue">
          <div className="scam-queue-filter-row">
            <span style={{ fontSize: '0.85rem', fontWeight: 600, color: '#475569' }}>Filter Status:</span>
            {['candidate', 'approved', 'rejected', 'merged', 'all'].map(st => (
              <button
                key={st}
                className={`scam-queue-tab ${queueStatus === st ? 'active' : ''}`}
                onClick={() => setQueueStatus(st)}
              >
                {st.toUpperCase()}
              </button>
            ))}
          </div>

          <div className="scam-queue-cards">
            {candidates.map((cand) => (
              <div key={cand.candidate_id} className="scam-candidate-card">
                <div className="scam-candidate-header">
                  <div>
                    <span className="scam-candidate-id">{cand.candidate_id}</span>
                    <h3 className="scam-candidate-title">{cand.suggested_title}</h3>
                    <div className="scam-candidate-meta">
                      <span>Category: <strong>{cand.category}</strong></span> ·{' '}
                      <span>Confidence: <strong>{Math.round((cand.confidence_score || 0) * 100)}%</strong></span> ·{' '}
                      <span>Reports: <strong>{cand.report_count || 1}</strong></span> ·{' '}
                      <span>Source: {cand.source}</span>
                    </div>
                  </div>
                  <div>
                    <span className={`scam-cand-status ${cand.status}`}>{cand.status.toUpperCase()}</span>
                  </div>
                </div>

                {/* Redacted Content Preview */}
                <div className="scam-cand-text-box">
                  <div className="scam-cand-text-label">Redacted Citizen Content:</div>
                  <p>{cand.redacted_text}</p>
                </div>

                {/* Extracted Indicators */}
                {cand.indicators && (
                  <div className="scam-cand-indicators">
                    {cand.indicators.impersonation_claims?.map((imp, idx) => (
                      <span key={`imp_${idx}`} className="scam-indicator-pill danger">
                        <Scale size={12} /> Impersonation: {imp}
                      </span>
                    ))}
                    {cand.indicators.threat_keywords?.map((thr, idx) => (
                      <span key={`thr_${idx}`} className="scam-indicator-pill danger">
                        <AlertOctagon size={12} /> Threat: {thr}
                      </span>
                    ))}
                    {cand.indicators.otp_requests?.map((otp, idx) => (
                      <span key={`otp_${idx}`} className="scam-indicator-pill danger">
                        <Lock size={12} /> Trap: {otp}
                      </span>
                    ))}
                    {cand.indicators.payment_demands?.map((pay, idx) => (
                      <span key={`pay_${idx}`} className="scam-indicator-pill warning">
                        <Landmark size={12} /> Payment: {pay}
                      </span>
                    ))}
                    {cand.indicators.upi_ids?.map((upi, idx) => (
                      <span key={`upi_${idx}`} className="scam-indicator-pill info">
                        UPI: {upi}
                      </span>
                    ))}
                  </div>
                )}

                {/* Queue Actions */}
                {cand.status === 'candidate' && (
                  <div className="scam-candidate-actions">
                    <button
                      className="btn-approve-cand"
                      onClick={() => openApproveModal(cand)}
                    >
                      <CheckCircle2 size={16} /> Approve as Pattern
                    </button>
                    <button
                      className="btn-merge-cand"
                      onClick={() => { setSelectedCandidate(cand); setShowMergeModal(true); }}
                    >
                      <GitMerge size={16} /> Merge Duplicate
                    </button>
                    <button
                      className="btn-reject-cand"
                      onClick={() => { setSelectedCandidate(cand); setShowRejectModal(true); }}
                    >
                      <XCircle size={16} /> Reject
                    </button>
                  </div>
                )}
              </div>
            ))}

            {candidates.length === 0 && !loading && (
              <div className="admin-empty">No candidate records found in review queue.</div>
            )}
          </div>
        </div>
      )}

      {/* ── SUBTAB: CITIZEN SUBMISSIONS ──────────────────────────────────── */}
      {subTab === 'submissions' && (
        <div className="scam-admin-submissions">
          <div className="admin-table-wrap">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>Submission ID</th>
                  <th>Outcome</th>
                  <th>Source</th>
                  <th>File Details</th>
                  <th>Confidence</th>
                  <th>Indicators Count</th>
                  <th>Matched Pattern</th>
                  <th>Date</th>
                </tr>
              </thead>
              <tbody>
                {submissions.map((s) => (
                  <tr key={s.submission_id}>
                    <td><code>{s.submission_id}</code></td>
                    <td>
                      <span className={`admin-outcome-pill ${s.outcome}`}>
                        {s.outcome}
                      </span>
                    </td>
                    <td>{s.content_source}</td>
                    <td>
                      {s.file_name ? (
                        <span>{s.file_name} ({s.file_type})</span>
                      ) : (
                        <span>Pasted text</span>
                      )}
                    </td>
                    <td>{Math.round((s.confidence_score || 0) * 100)}%</td>
                    <td>{s.indicators_count || 0}</td>
                    <td>{s.matched_pattern_id || '—'}</td>
                    <td>{new Date(s.created_at).toLocaleString()}</td>
                  </tr>
                ))}
                {submissions.length === 0 && !loading && (
                  <tr>
                    <td colSpan={8} style={{ textAlign: 'center', padding: '2rem' }}>
                      No citizen submissions recorded yet.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ── MODAL: INSPECT PATTERN ────────────────────────────────────────── */}
      {showPatternModal && selectedPattern && (
        <div className="admin-modal-overlay" onClick={() => setShowPatternModal(false)}>
          <div className="admin-modal-box large" onClick={e => e.stopPropagation()}>
            <div className="admin-modal-header">
              <div>
                <span className="scam-trace-id">ID: {selectedPattern.id}</span>
                <h2>{selectedPattern.name}</h2>
              </div>
              <button className="btn-close-modal" onClick={() => setShowPatternModal(false)}>✕</button>
            </div>
            <div className="admin-modal-body">
              <div className="scam-detail-row">
                <strong>Category:</strong> <span>{selectedPattern.category}</span> ·{' '}
                <strong>Severity:</strong> <span className={`severity-badge ${selectedPattern.severity}`}>{selectedPattern.severity}</span> ·{' '}
                <strong>Status:</strong> <span>{selectedPattern.is_active ? 'Active' : 'Inactive'}</span> ·{' '}
                <strong>Version:</strong> <span>v{selectedPattern.version || '1.0'}</span>
              </div>

              <div className="scam-detail-section">
                <h4>Modus Operandi:</h4>
                <p>{selectedPattern.description}</p>
              </div>

              <div className="scam-detail-section legal">
                <h4>Legal Reality:</h4>
                <p>{selectedPattern.legal_reality}</p>
              </div>

              <div className="scam-detail-section">
                <h4>Recommended Actions:</h4>
                <pre>{selectedPattern.recommended_action}</pre>
              </div>

              <div className="scam-detail-section">
                <h4>Keywords:</h4>
                <div className="scam-indicator-tags">
                  {(selectedPattern.keywords || []).map((k, i) => (
                    <span key={i} className="scam-kw-pill">{k}</span>
                  ))}
                </div>
              </div>

              <div className="scam-detail-section">
                <h4>Official Reference:</h4>
                <p>{selectedPattern.source_ref}</p>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ── MODAL: ADD / CURATE PATTERN ───────────────────────────────────── */}
      {showAddModal && (
        <div className="admin-modal-overlay" onClick={() => setShowAddModal(false)}>
          <div className="admin-modal-box large" onClick={e => e.stopPropagation()}>
            <div className="admin-modal-header">
              <h2>Curate New Scam Intelligence Pattern</h2>
              <button className="btn-close-modal" onClick={() => setShowAddModal(false)}>✕</button>
            </div>
            <form onSubmit={handleCreatePattern}>
              <div className="admin-modal-body">
                <div className="form-group">
                  <label>Pattern Name *</label>
                  <input
                    type="text"
                    required
                    value={patternForm.name}
                    onChange={e => setPatternForm({ ...patternForm, name: e.target.value })}
                    placeholder="e.g. TRAI SIM Deactivation Extortion Scam"
                  />
                </div>

                <div className="form-row">
                  <div className="form-group">
                    <label>Threat Category *</label>
                    <select
                      value={patternForm.category}
                      onChange={e => setPatternForm({ ...patternForm, category: e.target.value })}
                    >
                      {SCAM_CATEGORIES.filter(c => c !== 'All').map(c => (
                        <option key={c} value={c}>{c}</option>
                      ))}
                    </select>
                  </div>

                  <div className="form-group">
                    <label>Severity *</label>
                    <select
                      value={patternForm.severity}
                      onChange={e => setPatternForm({ ...patternForm, severity: e.target.value })}
                    >
                      <option value="CRITICAL">Critical</option>
                      <option value="HIGH">High</option>
                      <option value="MEDIUM">Medium</option>
                      <option value="LOW">Low</option>
                    </select>
                  </div>
                </div>

                <div className="form-group">
                  <label>Modus Operandi (Description) *</label>
                  <textarea
                    rows={4}
                    required
                    value={patternForm.description}
                    onChange={e => setPatternForm({ ...patternForm, description: e.target.value })}
                    placeholder="Explain how the fraudsters manipulate victims..."
                  />
                </div>

                <div className="form-group">
                  <label>Keywords (comma separated) *</label>
                  <input
                    type="text"
                    value={patternForm.keywords}
                    onChange={e => setPatternForm({ ...patternForm, keywords: e.target.value })}
                    placeholder="sim deactivation, trai call, mobile blocked within 2 hours"
                  />
                </div>

                <div className="form-group">
                  <label>Verified Legal Reality *</label>
                  <textarea
                    rows={3}
                    required
                    value={patternForm.legal_reality}
                    onChange={e => setPatternForm({ ...patternForm, legal_reality: e.target.value })}
                    placeholder="TRAI does not block individual mobile numbers via phone calls..."
                  />
                </div>

                <div className="form-group">
                  <label>Recommended Action Steps *</label>
                  <textarea
                    rows={3}
                    required
                    value={patternForm.recommended_action}
                    onChange={e => setPatternForm({ ...patternForm, recommended_action: e.target.value })}
                    placeholder="1. Hang up immediately.\n2. Verify with your service provider..."
                  />
                </div>

                <div className="form-group">
                  <label>Official Reference Source *</label>
                  <input
                    type="text"
                    required
                    value={patternForm.source_ref}
                    onChange={e => setPatternForm({ ...patternForm, source_ref: e.target.value })}
                    placeholder="TRAI Public Advisory 2024; DoT Advisory on SIM Disconnection Frauds"
                  />
                </div>
              </div>

              <div className="admin-modal-footer">
                <button type="button" className="btn-cancel" onClick={() => setShowAddModal(false)}>Cancel</button>
                <button type="submit" className="btn-primary">Save & Synchronize Pattern</button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ── MODAL: EDIT PATTERN ───────────────────────────────────────────── */}
      {showEditModal && selectedPattern && (
        <div className="admin-modal-overlay" onClick={() => setShowEditModal(false)}>
          <div className="admin-modal-box large" onClick={e => e.stopPropagation()}>
            <div className="admin-modal-header">
              <h2>Edit Pattern: {selectedPattern.name} ({selectedPattern.id})</h2>
              <button className="btn-close-modal" onClick={() => setShowEditModal(false)}>✕</button>
            </div>
            <form onSubmit={handleEditPattern}>
              <div className="admin-modal-body">
                <div className="form-group">
                  <label>Pattern Name *</label>
                  <input
                    type="text"
                    required
                    value={patternForm.name}
                    onChange={e => setPatternForm({ ...patternForm, name: e.target.value })}
                  />
                </div>

                <div className="form-row">
                  <div className="form-group">
                    <label>Threat Category</label>
                    <select
                      value={patternForm.category}
                      onChange={e => setPatternForm({ ...patternForm, category: e.target.value })}
                    >
                      {SCAM_CATEGORIES.filter(c => c !== 'All').map(c => (
                        <option key={c} value={c}>{c}</option>
                      ))}
                    </select>
                  </div>

                  <div className="form-group">
                    <label>Severity</label>
                    <select
                      value={patternForm.severity}
                      onChange={e => setPatternForm({ ...patternForm, severity: e.target.value })}
                    >
                      <option value="CRITICAL">Critical</option>
                      <option value="HIGH">High</option>
                      <option value="MEDIUM">Medium</option>
                      <option value="LOW">Low</option>
                    </select>
                  </div>
                </div>

                <div className="form-group">
                  <label>Modus Operandi</label>
                  <textarea
                    rows={4}
                    value={patternForm.description}
                    onChange={e => setPatternForm({ ...patternForm, description: e.target.value })}
                  />
                </div>

                <div className="form-group">
                  <label>Keywords (comma separated)</label>
                  <input
                    type="text"
                    value={patternForm.keywords}
                    onChange={e => setPatternForm({ ...patternForm, keywords: e.target.value })}
                  />
                </div>

                <div className="form-group">
                  <label>Verified Legal Reality</label>
                  <textarea
                    rows={3}
                    value={patternForm.legal_reality}
                    onChange={e => setPatternForm({ ...patternForm, legal_reality: e.target.value })}
                  />
                </div>

                <div className="form-group">
                  <label>Recommended Action Steps</label>
                  <textarea
                    rows={3}
                    value={patternForm.recommended_action}
                    onChange={e => setPatternForm({ ...patternForm, recommended_action: e.target.value })}
                  />
                </div>

                <div className="form-group">
                  <label>Review Notes (Reason for version increment)</label>
                  <input
                    type="text"
                    value={patternForm.review_notes}
                    onChange={e => setPatternForm({ ...patternForm, review_notes: e.target.value })}
                    placeholder="e.g. Updated legal citations and added new UPI fraud vectors"
                  />
                </div>
              </div>

              <div className="admin-modal-footer">
                <button type="button" className="btn-cancel" onClick={() => setShowEditModal(false)}>Cancel</button>
                <button type="submit" className="btn-primary">Save Changes (Increment Version)</button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ── MODAL: APPROVE CANDIDATE ──────────────────────────────────────── */}
      {showApproveModal && selectedCandidate && (
        <div className="admin-modal-overlay" onClick={() => setShowApproveModal(false)}>
          <div className="admin-modal-box large" onClick={e => e.stopPropagation()}>
            <div className="admin-modal-header">
              <h2>Promote Candidate to Verified Pattern</h2>
              <button className="btn-close-modal" onClick={() => setShowApproveModal(false)}>✕</button>
            </div>
            <form onSubmit={handleApproveCandidate}>
              <div className="admin-modal-body">
                <div className="form-group">
                  <label>Pattern Name *</label>
                  <input
                    type="text"
                    required
                    value={approveForm.name}
                    onChange={e => setApproveForm({ ...approveForm, name: e.target.value })}
                  />
                </div>

                <div className="form-row">
                  <div className="form-group">
                    <label>Threat Category</label>
                    <select
                      value={approveForm.category}
                      onChange={e => setApproveForm({ ...approveForm, category: e.target.value })}
                    >
                      {SCAM_CATEGORIES.filter(c => c !== 'All').map(c => (
                        <option key={c} value={c}>{c}</option>
                      ))}
                    </select>
                  </div>

                  <div className="form-group">
                    <label>Severity</label>
                    <select
                      value={approveForm.severity}
                      onChange={e => setApproveForm({ ...approveForm, severity: e.target.value })}
                    >
                      <option value="CRITICAL">Critical</option>
                      <option value="HIGH">High</option>
                      <option value="MEDIUM">Medium</option>
                      <option value="LOW">Low</option>
                    </select>
                  </div>
                </div>

                <div className="form-group">
                  <label>Description (Modus Operandi) *</label>
                  <textarea
                    rows={3}
                    required
                    value={approveForm.description}
                    onChange={e => setApproveForm({ ...approveForm, description: e.target.value })}
                  />
                </div>

                <div className="form-group">
                  <label>Keywords (comma separated) *</label>
                  <input
                    type="text"
                    required
                    value={approveForm.keywords}
                    onChange={e => setApproveForm({ ...approveForm, keywords: e.target.value })}
                  />
                </div>

                <div className="form-group">
                  <label>Legal Reality *</label>
                  <textarea
                    rows={3}
                    required
                    value={approveForm.legal_reality}
                    onChange={e => setApproveForm({ ...approveForm, legal_reality: e.target.value })}
                  />
                </div>

                <div className="form-group">
                  <label>Recommended Protective Actions *</label>
                  <textarea
                    rows={3}
                    required
                    value={approveForm.recommended_action}
                    onChange={e => setApproveForm({ ...approveForm, recommended_action: e.target.value })}
                  />
                </div>

                <div className="form-group">
                  <label>Official Reference Source *</label>
                  <input
                    type="text"
                    required
                    value={approveForm.source_ref}
                    onChange={e => setApproveForm({ ...approveForm, source_ref: e.target.value })}
                  />
                </div>

                <div className="form-group">
                  <label>Reviewer Approval Notes</label>
                  <input
                    type="text"
                    value={approveForm.review_notes}
                    onChange={e => setApproveForm({ ...approveForm, review_notes: e.target.value })}
                  />
                </div>
              </div>

              <div className="admin-modal-footer">
                <button type="button" className="btn-cancel" onClick={() => setShowApproveModal(false)}>Cancel</button>
                <button type="submit" className="btn-primary">Approve & Activate in Detection</button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ── MODAL: REJECT CANDIDATE ───────────────────────────────────────── */}
      {showRejectModal && selectedCandidate && (
        <div className="admin-modal-overlay" onClick={() => setShowRejectModal(false)}>
          <div className="admin-modal-box" onClick={e => e.stopPropagation()}>
            <div className="admin-modal-header">
              <h2>Reject Candidate Report</h2>
              <button className="btn-close-modal" onClick={() => setShowRejectModal(false)}>✕</button>
            </div>
            <form onSubmit={handleRejectCandidate}>
              <div className="admin-modal-body">
                <p>
                  Please specify why candidate <strong>{selectedCandidate.candidate_id}</strong> is being rejected (e.g. insufficient evidence, benign message, unverified claim):
                </p>
                <div className="form-group">
                  <textarea
                    rows={3}
                    required
                    placeholder="Enter rejection rationale..."
                    value={rejectReason}
                    onChange={e => setRejectReason(e.target.value)}
                  />
                </div>
              </div>
              <div className="admin-modal-footer">
                <button type="button" className="btn-cancel" onClick={() => setShowRejectModal(false)}>Cancel</button>
                <button type="submit" className="btn-danger">Confirm Rejection</button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ── MODAL: MERGE CANDIDATE ────────────────────────────────────────── */}
      {showMergeModal && selectedCandidate && (
        <div className="admin-modal-overlay" onClick={() => setShowMergeModal(false)}>
          <div className="admin-modal-box" onClick={e => e.stopPropagation()}>
            <div className="admin-modal-header">
              <h2>Merge Duplicate Candidate</h2>
              <button className="btn-close-modal" onClick={() => setShowMergeModal(false)}>✕</button>
            </div>
            <form onSubmit={handleMergeCandidate}>
              <div className="admin-modal-body">
                <p>
                  Merge candidate <strong>{selectedCandidate.candidate_id}</strong> into an existing pattern.
                  This increments the pattern&apos;s report count and links discovered indicators.
                </p>
                <div className="form-group">
                  <label>Target Pattern ID *</label>
                  <input
                    type="text"
                    required
                    placeholder="e.g. SCAM_001 or SCAM_INT_..."
                    value={mergeTargetId}
                    onChange={e => setMergeTargetId(e.target.value)}
                  />
                </div>
                <div className="form-group">
                  <label>Merge Notes</label>
                  <input
                    type="text"
                    placeholder="e.g. Duplicate report from WhatsApp scam campaign"
                    value={mergeNotes}
                    onChange={e => setMergeNotes(e.target.value)}
                  />
                </div>
              </div>
              <div className="admin-modal-footer">
                <button type="button" className="btn-cancel" onClick={() => setShowMergeModal(false)}>Cancel</button>
                <button type="submit" className="btn-primary">Confirm Merge</button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
