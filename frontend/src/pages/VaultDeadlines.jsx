/*
 * frontend/src/pages/VaultDeadlines.jsx
 * ──────────────────────────────────────────────────────────────────────────────
 * LEXIS — Vault & Deadlines Dashboard (Module 10 — Agent 6)
 *
 * Features:
 *   - Anonymous mode block (friendly message + sign-in prompt)
 *   - Drag-and-drop file upload zone
 *   - Date extraction with confidence badges (amber = needs review)
 *   - Date confirmation modal before creating a deadline
 *   - Document list with download / delete
 *   - Deadline cards with T-minus countdown badges
 *   - Proactive draft preview panel per deadline
 * ──────────────────────────────────────────────────────────────────────────────
 */

import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  FolderLock,
  Lock,
  UploadCloud,
  Calendar,
  FileText,
  Image as ImageIcon,
  File,
  Download,
  Trash2,
  Clock,
  FileEdit,
  AlertTriangle,
  CheckCircle2,
  AlertCircle
} from 'lucide-react';
import './VaultDeadlines.css';

/* ── API helpers ──────────────────────────────────────────────────────────── */
const rawBase = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';
const BASE = rawBase.endsWith('/api/v1') ? rawBase : `${rawBase.replace(/\/+$/, '')}/api/v1`;

async function apiFetch(path, options = {}) {
  const token = localStorage.getItem('lexis_access_token') || localStorage.getItem('access_token');
  const res = await fetch(`${BASE}${path}`, {
    ...options,
    headers: {
      Authorization: token ? `Bearer ${token}` : '',
      ...options.headers,
    },
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw Object.assign(new Error(err.detail || 'Request failed'), { status: res.status });
  }
  return res.json();
}

/* ── Helpers ─────────────────────────────────────────────────────────────── */
function formatDate(iso) {
  if (!iso) return '—';
  try { return new Date(iso).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' }); }
  catch { return iso; }
}

function fileSizeLabel(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function renderDocIcon(ct) {
  if (ct === 'application/pdf') return <FileText size={20} className="doc-icon-svg pdf" />;
  if (ct?.startsWith('image/')) return <ImageIcon size={20} className="doc-icon-svg img" />;
  return <File size={20} className="doc-icon-svg generic" />;
}

function urgencyClass(u) {
  return { critical: 'urgency-critical', high: 'urgency-high', medium: 'urgency-medium', low: 'urgency-low' }[u] || '';
}

function confidenceTier(c) {
  if (c >= 0.85) return { label: `${Math.round(c * 100)}% confident`, cls: 'high' };
  if (c >= 0.70) return { label: `${Math.round(c * 100)}% confident`, cls: 'medium' };
  return { label: `${Math.round(c * 100)}% — Verify`, cls: 'low' };
}

/* ── Date Confirmation Modal ──────────────────────────────────────────────── */
function DateConfirmModal({ doc, onConfirm, onClose }) {
  const [edits, setEdits] = useState(() =>
    (doc.extracted_dates || []).map(d => ({ ...d, date_str: d.date_str || '' }))
  );

  function setDateStr(idx, val) {
    setEdits(prev => prev.map((e, i) => i === idx ? { ...e, date_str: val } : e));
  }

  function handleConfirm() {
    const confirmed = edits
      .filter(d => d.date_str)
      .map(d => ({ label: d.label, date_str: d.date_str, doc_type: 'legal_notice' }));
    if (!confirmed.length) return;
    onConfirm(doc.file_id, confirmed);
  }

  return (
    <div className="dates-modal-overlay" role="dialog" aria-modal="true">
      <div className="dates-modal">
        <h3>
          <Calendar size={22} className="modal-title-icon" />
          <span>Review Extracted Dates</span>
        </h3>
        <p className="modal-desc">
          LEXIS extracted the following dates from your document.
          Dates in <span style={{ color: '#d97706', fontWeight: 600 }}>amber</span> have lower confidence
          — please verify them against your original document before creating a deadline.
          You can edit any date directly.
        </p>

        {edits.length === 0 && (
          <p style={{ color: '#64748b', textAlign: 'center', padding: '1rem 0' }}>
            No dates were extracted from this document.
            You can add deadlines manually from the Deadlines panel later.
          </p>
        )}

        {edits.map((d, i) => {
          const tier = confidenceTier(d.confidence);
          return (
            <div key={i} className={`date-card ${d.needs_confirmation ? 'needs-confirm' : ''}`}>
              <div className="date-card-header">
                <span className="date-label">{d.label}</span>
                <span className={`confidence-badge ${tier.cls}`}>{tier.label}</span>
              </div>
              <div className="date-value-row">
                <input
                  type="date"
                  value={d.date_str}
                  onChange={e => setDateStr(i, e.target.value)}
                  aria-label={`Date for ${d.label}`}
                />
              </div>
              {d.raw_snippet && (
                <p className="date-snippet">From document: "{d.raw_snippet}"</p>
              )}
              {d.needs_confirmation && (
                <p className="warn-label">
                  <AlertTriangle size={13} style={{ display: 'inline', verticalAlign: 'middle', marginRight: '4px' }} />
                  Please verify this date against your document before confirming.
                </p>
              )}
            </div>
          );
        })}

        <div className="modal-actions">
          <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
          <button
            className="btn btn-primary"
            onClick={handleConfirm}
            disabled={edits.filter(d => d.date_str).length === 0}
            id="confirm-dates-btn"
          >
            Confirm &amp; Create Deadlines
          </button>
        </div>
      </div>
    </div>
  );
}

/* ── Main Component ───────────────────────────────────────────────────────── */
function VaultDeadlines() {
  const navigate = useNavigate();
  const [isAnonymous, setIsAnonymous] = useState(false);
  const [docs, setDocs] = useState([]);
  const [deadlines, setDeadlines] = useState([]);
  const [uploading, setUploading] = useState(false);
  const [uploadStatus, setUploadStatus] = useState(null);
  const [dragOver, setDragOver] = useState(false);
  const [pendingDoc, setPendingDoc] = useState(null);
  const [selectedDeadline, setSelectedDeadline] = useState(null);
  const [draftText, setDraftText] = useState('');
  const [loadingDraft, setLoadingDraft] = useState(false);

  const fileInputRef = useRef(null);

  /* ── Check role & load data on mount ── */
  useEffect(() => {
    try {
      const stored = localStorage.getItem('lexis_user');
      if (stored) {
        const u = JSON.parse(stored);
        if (u.role === 'anonymous') {
          setIsAnonymous(true);
          return;
        }
      }
    } catch { /* ignore */ }

    loadData();
  }, []);

  async function loadData() {
    try {
      const [dRes, dlRes] = await Promise.all([
        apiFetch('/vault/documents'),
        apiFetch('/vault/deadlines'),
      ]);
      setDocs(dRes.documents || []);
      setDeadlines(dlRes.deadlines || []);
    } catch (e) {
      if (e.status === 401) {
        setIsAnonymous(true);
      }
    }
  }

  /* ── Upload ── */
  async function handleUpload(file) {
    if (!file) return;
    const allowed = ['application/pdf', 'image/jpeg', 'image/png'];
    if (!allowed.includes(file.type)) {
      setUploadStatus({ type: 'error', msg: 'Only PDF, JPEG, and PNG files are allowed.' });
      return;
    }
    if (file.size > 10 * 1024 * 1024) {
      setUploadStatus({ type: 'error', msg: 'File exceeds the 10 MB limit.' });
      return;
    }

    setUploading(true);
    setUploadStatus({ type: 'uploading', msg: `Encrypting & analysing "${file.name}"…` });
    try {
      const fd = new FormData();
      fd.append('file', file);
      const res = await apiFetch('/vault/upload', { method: 'POST', body: fd });
      setUploadStatus({ type: 'success', msg: `✓ Uploaded. ${res.extraction_summary?.total_dates_found || 0} date(s) extracted.` });
      setPendingDoc(res);
      await loadData();
    } catch (e) {
      setUploadStatus({ type: 'error', msg: e.message || 'Upload failed. Please try again.' });
    } finally {
      setUploading(false);
    }
  }

  function onFileSelect(e) {
    const f = e.target.files?.[0];
    if (f) handleUpload(f);
    e.target.value = '';
  }

  const onDrop = useCallback(e => {
    e.preventDefault();
    setDragOver(false);
    const f = e.dataTransfer.files?.[0];
    if (f) handleUpload(f);
  }, []);

  /* ── Confirm dates ── */
  async function handleConfirmDates(docId, confirmed) {
    try {
      await apiFetch(`/vault/${docId}/confirm-dates`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ confirmed_dates: confirmed }),
      });
      setPendingDoc(null);
      await loadData();
    } catch (e) {
      alert(`Failed to confirm dates: ${e.message}`);
    }
  }

  /* ── Delete ── */
  async function handleDelete(fileId, name) {
    if (!window.confirm(`Permanently delete "${name}"? This cannot be undone.`)) return;
    try {
      await apiFetch(`/vault/documents/${fileId}`, { method: 'DELETE' });
      setDocs(prev => prev.filter(d => d.file_id !== fileId));
      setDeadlines(prev => prev.filter(dl => dl.vault_doc_id !== fileId));
    } catch (e) {
      alert(`Delete failed: ${e.message}`);
    }
  }

  /* ── Download ── */
  function handleDownload(fileId) {
    const url = `${BASE}/vault/documents/${fileId}/download`;
    const a = document.createElement('a');
    a.href = url;
    a.setAttribute('download', fileId);
    a.setAttribute('target', '_blank');
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  }

  /* ── View draft ── */
  async function handleViewDraft(dl) {
    setSelectedDeadline(dl);
    setDraftText('');
    if (!dl.reminders_sent?.length) {
      setDraftText('No draft yet — a draft will be auto-generated when the first reminder fires (T-30, T-15, or T-3 days).');
      return;
    }
    setLoadingDraft(true);
    try {
      const res = await apiFetch(`/vault/deadlines/${dl.deadline_id}/draft`);
      setDraftText(res.draft_text || 'No draft available yet.');
    } catch {
      setDraftText('Could not load draft.');
    } finally {
      setLoadingDraft(false);
    }
  }

  /* ── Anonymous block ── */
  if (isAnonymous) {
    return (
      <div className="vault-page">
        <div className="vault-header">
          <div className="vault-header-icon-wrap">
            <FolderLock size={26} />
          </div>
          <div>
            <h1>Vault &amp; Deadlines</h1>
            <p className="vault-subtitle">Encrypted personal document storage with proactive deadline reminders</p>
          </div>
        </div>
        <div className="vault-anon-block">
          <div className="anon-icon">
            <Lock size={36} />
          </div>
          <h2>Account Required</h2>
          <p>
            The Vault encrypts your documents (Aadhaar, passports, lease agreements) with
            AES-256 and sends you proactive reminders before important deadlines — including
            a ready-to-use legal draft. This requires a verified LEXIS account so your data
            is tied to your identity, not an anonymous session.
          </p>
          <button className="btn-signin" id="vault-signin-btn" onClick={() => navigate('/login')}>
            Sign in with Email OTP →
          </button>
        </div>
      </div>
    );
  }

  /* ── Authenticated UI ── */
  return (
    <div className="vault-page">
      <div className="vault-header">
        <div className="vault-header-icon-wrap">
          <FolderLock size={26} />
        </div>
        <div>
          <h1>Vault &amp; Deadlines</h1>
          <p className="vault-subtitle">
            AES-256 encrypted · Proactive reminders at T-30, T-15, T-3 · Auto-draft generation
          </p>
        </div>
      </div>

      <div className="vault-grid">
        {/* ── Upload + Documents ── */}
        <div>
          {/* Upload zone */}
          <div className="glass-panel" style={{ marginBottom: '1.5rem' }}>
            <h2>
              <UploadCloud size={20} className="panel-title-icon" />
              <span>Upload Document</span>
            </h2>
            <div
              className={`upload-zone ${dragOver ? 'drag-over' : ''}`}
              onClick={() => fileInputRef.current?.click()}
              onDragOver={e => { e.preventDefault(); setDragOver(true); }}
              onDragLeave={() => setDragOver(false)}
              onDrop={onDrop}
              role="button"
              tabIndex={0}
              aria-label="Upload vault document"
              onKeyDown={e => e.key === 'Enter' && fileInputRef.current?.click()}
              id="vault-upload-zone"
            >
              <div className="upload-icon">
                <UploadCloud size={32} />
              </div>
              <p><strong>Click or drag &amp; drop</strong> to upload</p>
              <p>LEXIS will extract deadlines automatically</p>
              <p className="upload-filetypes">PDF · JPEG · PNG — max 10 MB</p>
              <input
                ref={fileInputRef}
                type="file"
                accept=".pdf,.jpg,.jpeg,.png"
                onChange={onFileSelect}
                id="vault-file-input"
              />
            </div>

            {uploadStatus && (
              <div className={`upload-status ${uploadStatus.type}`}>
                {uploadStatus.type === 'uploading' && <span className="spinner" />}
                {uploadStatus.type === 'success' && '✓ '}
                {uploadStatus.type === 'error' && '✗ '}
                {uploadStatus.msg}
              </div>
            )}
          </div>

          {/* Document list */}
          <div className="glass-panel">
            <h2>
              <FileText size={20} className="panel-title-icon" />
              <span>Your Documents <span style={{ color: '#64748b', fontWeight: 500, fontSize: '0.9rem' }}>({docs.length})</span></span>
            </h2>
            {docs.length === 0 ? (
              <div className="empty-state"><p>No documents stored yet. Upload one above.</p></div>
            ) : (
              <div className="doc-list">
                {docs.map(doc => (
                  <div key={doc.file_id} className="doc-card">
                    <span className="doc-icon">{renderDocIcon(doc.content_type)}</span>
                    <div className="doc-info">
                      <div className="doc-name" title={doc.original_name}>{doc.original_name}</div>
                      <div className="doc-meta">
                        {fileSizeLabel(doc.size_bytes)} · {formatDate(doc.created_at)}
                        &nbsp;<span className="doc-enc-badge"><Lock size={11} style={{ display: 'inline', verticalAlign: 'middle', marginRight: '3px' }} />Encrypted</span>
                      </div>
                    </div>
                    <div className="doc-actions">
                      <button
                        className="btn btn-ghost btn-sm"
                        onClick={() => handleDownload(doc.file_id)}
                        title="Download (decrypted)"
                        id={`download-doc-${doc.file_id}`}
                      >
                        <Download size={15} />
                      </button>
                      <button
                        className="btn btn-danger btn-sm"
                        onClick={() => handleDelete(doc.file_id, doc.original_name)}
                        title="Permanently delete"
                        id={`delete-doc-${doc.file_id}`}
                      >
                        <Trash2 size={15} />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* ── Deadlines + Draft ── */}
        <div>
          <div className="glass-panel" style={{ marginBottom: '1.5rem' }}>
            <h2>
              <Clock size={20} className="panel-title-icon" />
              <span>Upcoming Deadlines <span style={{ color: '#64748b', fontWeight: 500, fontSize: '0.9rem' }}>({deadlines.length})</span></span>
            </h2>
            <p style={{ fontSize: '0.84rem', color: '#64748b', marginTop: '-0.5rem', marginBottom: '1.25rem' }}>
              Reminders fire at T-30, T-15, T-3 days · Includes proactive draft letter
            </p>
            {deadlines.length === 0 ? (
              <div className="empty-state"><p>No deadlines tracked. Upload a document to get started.</p></div>
            ) : (
              <div className="deadline-list">
                {deadlines.map(dl => (
                  <div key={dl.deadline_id} className={`deadline-card ${urgencyClass(dl.urgency)}`}>
                    <span className={`urgency-badge ${dl.urgency}`}>
                      <Clock size={12} style={{ display: 'inline', verticalAlign: 'middle', marginRight: '4px' }} />
                      {dl.days_remaining != null ? `${dl.days_remaining}d left` : '—'}
                    </span>
                    <div className="deadline-info">
                      <div className="deadline-label">{dl.label}</div>
                      <div className="deadline-date">Due: {formatDate(dl.deadline_date)}</div>
                      <div className="deadline-reminders">
                        Reminders sent: {dl.reminders_sent?.length ? dl.reminders_sent.map(r => `T-${r}`).join(', ') : 'None yet'}
                      </div>
                    </div>
                    <button
                      className="btn btn-ghost btn-sm"
                      onClick={() => handleViewDraft(dl)}
                      id={`view-draft-${dl.deadline_id}`}
                      title="View proactive draft"
                    >
                      <FileEdit size={16} />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Draft preview */}
          {selectedDeadline && (
            <div className="glass-panel">
              <h2>
                <FileEdit size={20} className="panel-title-icon" />
                <span>Proactive Draft — {selectedDeadline.label}</span>
              </h2>
              <p style={{ fontSize: '0.84rem', color: '#64748b', marginTop: '-0.5rem', marginBottom: '1.25rem' }}>
                Auto-generated by LEXIS at reminder time. Review, fill in placeholders, and submit.
              </p>
              {loadingDraft ? (
                <div style={{ textAlign: 'center', padding: '2rem' }}><span className="spinner" /></div>
              ) : (
                <div className="draft-preview">
                  <h4>✦ Auto-Drafted Legal Notice</h4>
                  <pre className="draft-text">{draftText}</pre>
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Date Confirmation Modal */}
      {pendingDoc && (
        <DateConfirmModal
          doc={pendingDoc}
          onConfirm={handleConfirmDates}
          onClose={() => setPendingDoc(null)}
        />
      )}
    </div>
  );
}

export default VaultDeadlines;
