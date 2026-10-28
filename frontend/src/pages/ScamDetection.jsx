/*
 * frontend/src/pages/ScamDetection.jsx
 * ──────────────────────────────────────────────────────────────────────────
 * LEXIS — Scam Intelligence & Citizen Document Analysis (Module 8)
 *
 * Citizen-facing submission interface for text, messages, screenshots,
 * PDFs, DOCX, and structured messages. Extracts indicators, compares
 * against verified intelligence, and flags novel scam tactics.
 * ──────────────────────────────────────────────────────────────────────────
 */

import React, { useRef, useState } from 'react';
import {
  ShieldAlert,
  ShieldCheck,
  AlertTriangle,
  Search,
  RotateCcw,
  Lock,
  PhoneCall,
  Globe,
  Scale,
  Landmark,
  CheckCircle2,
  Package,
  Smartphone,
  HelpCircle,
  BookOpen,
  Info,
  UploadCloud,
  FileText,
  File,
  X,
  AlertOctagon,
  Eye,
  CheckCircle,
} from 'lucide-react';
import { checkScam, analyzeScamUpload } from '../services/api';
import './ScamDetection.css';

// Quick-example prompts for citizen convenience
const EXAMPLE_PROMPTS = [
  { icon: PhoneCall, text: 'A person called claiming I am under "digital arrest" by CBI' },
  { icon: Package, text: 'A courier company said my package was seized with drugs and demanded Rs 15,000' },
  { icon: Smartphone, text: 'Someone told me to scan a QR code to receive ₹5,000 on PhonePe' },
  { icon: Lock, text: 'I got a message saying my Aadhaar is suspended and KYC must be updated' },
  { icon: Scale, text: 'An "investment app" on Telegram promised 35% monthly returns on crypto trading' },
  { icon: Landmark, text: 'A caller said my bank account is frozen under PMLA and I must transfer money to a "safe account"' },
];

function getSeverityLabel(severity) {
  const map = { CRITICAL: 'Critical Threat', HIGH: 'High Risk', MEDIUM: 'Caution / Medium', LOW: 'Low Risk' };
  return map[severity] || severity;
}

function parseSteps(text) {
  if (!text) return [];
  const lines = text.split('\n').filter(l => l.trim());
  return lines.map(l => l.replace(/^\d+[\.\)]\s*/, '').trim()).filter(Boolean);
}

function renderChannelIcon(channel) {
  const c = channel.toLowerCase();
  if (c.includes('cybercrime') || c.includes('gov')) return <Globe size={16} />;
  if (c.includes('1930') || c.includes('helpline')) return <PhoneCall size={16} />;
  if (c.includes('police') || c.includes('fir')) return <Scale size={16} />;
  return <Landmark size={16} />;
}

export default function ScamDetection() {
  const [activeTab, setActiveTab] = useState('text'); // 'text' | 'file'
  const [description, setDescription] = useState('');
  const [selectedFile, setSelectedFile] = useState(null);
  const [fileNote, setFileNote] = useState('');
  const [isDragging, setIsDragging] = useState(false);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  const fileInputRef = useRef(null);
  const MAX_CHARS = 2000;
  const MIN_CHARS = 10;
  const MAX_FILE_SIZE_BYTES = 15 * 1024 * 1024; // 15MB

  // ── Drag & Drop handlers ──────────────────────────────────────────────────
  function handleDragOver(e) {
    e.preventDefault();
    setIsDragging(true);
  }

  function handleDragLeave(e) {
    e.preventDefault();
    setIsDragging(false);
  }

  function handleDrop(e) {
    e.preventDefault();
    setIsDragging(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      validateAndSetFile(e.dataTransfer.files[0]);
    }
  }

  function handleFileInputChange(e) {
    if (e.target.files && e.target.files.length > 0) {
      validateAndSetFile(e.target.files[0]);
    }
  }

  function validateAndSetFile(file) {
    setError(null);
    if (file.size > MAX_FILE_SIZE_BYTES) {
      setError(`File size (${(file.size / (1024 * 1024)).toFixed(1)} MB) exceeds 15 MB limit.`);
      return;
    }
    const ext = '.' + file.name.split('.').pop().toLowerCase();
    const allowed = ['.pdf', '.docx', '.txt', '.json', '.png', '.jpg', '.jpeg', '.webp'];
    if (!allowed.includes(ext)) {
      setError(`Unsupported file type '${ext}'. Please upload PDF, DOCX, TXT, JSON, or an image screenshot.`);
      return;
    }
    setSelectedFile(file);
    setResult(null);
  }

  function handleRemoveFile() {
    setSelectedFile(null);
    if (fileInputRef.current) fileInputRef.current.value = '';
  }

  // ── Submit handler ────────────────────────────────────────────────────────
  async function handleAnalyze() {
    setLoading(true);
    setResult(null);
    setError(null);

    try {
      if (activeTab === 'file' && selectedFile) {
        const formData = new FormData();
        formData.append('file', selectedFile);
        if (fileNote.trim()) {
          formData.append('text', fileNote.trim());
        }
        const data = await analyzeScamUpload(formData);
        setResult(data);
      } else {
        if (description.trim().length < MIN_CHARS) {
          setError(`Please provide at least ${MIN_CHARS} characters describing the incident.`);
          setLoading(false);
          return;
        }
        // Send via unified analyze-upload endpoint for full indicator extraction & candidate discovery
        const formData = new FormData();
        formData.append('text', description.trim());
        const data = await analyzeScamUpload(formData);
        setResult(data);
      }
    } catch (err) {
      const msg =
        err?.response?.data?.detail ||
        err?.message ||
        'Failed to connect to the scam detection service. Please try again.';
      setError(msg);
    } finally {
      setLoading(false);
    }
  }

  function handleExample(text) {
    setActiveTab('text');
    setDescription(text);
    setResult(null);
    setError(null);
  }

  function handleReset() {
    setDescription('');
    setSelectedFile(null);
    setFileNote('');
    setResult(null);
    setError(null);
    if (fileInputRef.current) fileInputRef.current.value = '';
  }

  const canSubmit = activeTab === 'file'
    ? Boolean(selectedFile) && !loading
    : description.trim().length >= MIN_CHARS && !loading;

  // ── Render Indicators Chips ───────────────────────────────────────────────
  function renderIndicatorTags(indicators) {
    if (!indicators) return null;
    const tags = [];

    (indicators.impersonation_claims || []).forEach((c, idx) => {
      tags.push({ type: 'danger', icon: Scale, label: `Impersonation: ${c.toUpperCase()}`, key: `imp_${idx}` });
    });
    (indicators.threat_keywords || []).forEach((t, idx) => {
      tags.push({ type: 'danger', icon: AlertOctagon, label: `Threat: ${t}`, key: `thr_${idx}` });
    });
    (indicators.otp_requests || []).forEach((o, idx) => {
      tags.push({ type: 'danger', icon: Lock, label: `Credential Trap: ${o}`, key: `otp_${idx}` });
    });
    (indicators.payment_demands || []).forEach((p, idx) => {
      tags.push({ type: 'warning', icon: Landmark, label: `Payment Demand: ${p}`, key: `pay_${idx}` });
    });
    (indicators.urgency_keywords || []).forEach((u, idx) => {
      tags.push({ type: 'warning', icon: AlertTriangle, label: `Urgency Tactic: ${u}`, key: `urg_${idx}` });
    });
    (indicators.upi_ids || []).forEach((upi, idx) => {
      tags.push({ type: 'info', icon: Smartphone, label: `UPI: ${upi}`, key: `upi_${idx}` });
    });
    (indicators.domains || []).forEach((d, idx) => {
      tags.push({ type: 'info', icon: Globe, label: `Domain: ${d}`, key: `dom_${idx}` });
    });

    if (tags.length === 0) return null;

    return (
      <div className="scam-indicators-panel">
        <h4 className="scam-indicators-title">
          <Eye size={16} /> Extracted Suspicious Signals ({tags.length})
        </h4>
        <div className="scam-indicator-tags">
          {tags.map(tag => {
            const Icon = tag.icon;
            return (
              <span key={tag.key} className={`scam-indicator-pill ${tag.type}`}>
                <Icon size={13} />
                <span>{tag.label}</span>
              </span>
            );
          })}
        </div>
      </div>
    );
  }

  // ── Render Analysis Outcome Card ──────────────────────────────────────────
  function renderOutcome(res) {
    const isMatched = res.outcome === 'Likely scam' && res.matched_pattern;
    const isSuspicious = res.outcome === 'Suspicious — needs verification';
    const isSafe = res.outcome === 'No strong scam indicators found';

    const steps = isMatched ? parseSteps(res.matched_pattern.recommended_action) : [];

    return (
      <div className="scam-result-wrapper">
        {/* Outcome Banner */}
        <div className={`scam-outcome-banner ${isMatched ? 'danger' : isSuspicious ? 'warning' : 'neutral'}`}>
          <div className="scam-outcome-icon-box">
            {isMatched ? <ShieldAlert size={32} /> : isSuspicious ? <AlertTriangle size={32} /> : <ShieldCheck size={32} />}
          </div>
          <div className="scam-outcome-text">
            <div className="scam-outcome-badge-row">
              <span className="scam-outcome-badge">{res.outcome}</span>
              <span className={`scam-risk-badge ${res.risk_level}`}>Risk: {res.risk_level}</span>
              <span className="scam-confidence-badge">Confidence: {Math.round(res.confidence_score * 100)}%</span>
            </div>
            <h3>{res.summary}</h3>
          </div>
        </div>

        {/* Extracted Indicators */}
        {renderIndicatorTags(res.matching_indicators)}

        {/* Candidate discovery notice */}
        {res.candidate_created && (
          <div className="scam-candidate-alert">
            <Info size={18} className="candidate-icon" />
            <div>
              <strong>Novel Scam Tactic Queued for Investigation</strong>
              <p>
                This incident does not match established historical cases, but exhibits coercive scam indicators.
                LEXIS has redacted your personal details and placed this report in the Admin Scam Intelligence Review Queue.
                {res.candidate_id && ` Reference ID: ${res.candidate_id}`}
              </p>
            </div>
          </div>
        )}

        {/* Matched Pattern Card */}
        {isMatched && (
          <div className="scam-alert-card" role="alert" aria-live="assertive">
            <div className="scam-alert-header">
              <div className="scam-alert-header-left">
                <div className="scam-alert-icon-box" aria-hidden="true">
                  <ShieldAlert size={26} />
                </div>
                <div>
                  <h2 className="scam-alert-name">{res.matched_pattern.name}</h2>
                  <div className="scam-alert-meta">
                    <span className={`severity-badge ${res.matched_pattern.severity}`}>
                      {getSeverityLabel(res.matched_pattern.severity)}
                    </span>
                    <span className="match-chip">{res.matched_pattern.match_method || 'Verified Match'}</span>
                  </div>
                </div>
              </div>
              <div className="scam-alert-header-right">
                <span className="scam-trace-id" title="Traceability ID — links to the source database record">
                  DB ID: {res.matched_pattern.id}
                </span>
              </div>
            </div>

            <div className="scam-alert-body">
              {/* How it works */}
              <div className="scam-section">
                <div className="scam-section-label">
                  <BookOpen size={16} />
                  <span>Modus Operandi (How It Works)</span>
                </div>
                <p className="scam-section-content">{res.matched_pattern.description}</p>
              </div>

              {/* Legal Reality */}
              <div className="scam-section legal">
                <div className="scam-section-label">
                  <Scale size={16} />
                  <span>Verified Legal Reality</span>
                </div>
                <p className="scam-section-content">{res.matched_pattern.legal_reality}</p>
              </div>

              {/* Steps */}
              <div className="scam-section">
                <div className="scam-section-label">
                  <CheckCircle2 size={16} />
                  <span>Immediate Protective Steps</span>
                </div>
                {steps.length > 0 ? (
                  <ol className="scam-steps">
                    {steps.map((step, i) => (
                      <li key={i} className="scam-step">
                        <span className="scam-step-num">{i + 1}</span>
                        <span className="scam-step-text">{step}</span>
                      </li>
                    ))}
                  </ol>
                ) : (
                  <p className="scam-section-content">{res.matched_pattern.recommended_action}</p>
                )}
              </div>

              {/* Channels */}
              {res.matched_pattern.reporting_channels && res.matched_pattern.reporting_channels.length > 0 && (
                <div className="scam-section">
                  <div className="scam-section-label">
                    <PhoneCall size={16} />
                    <span>Official Reporting Portals</span>
                  </div>
                  <div className="scam-channels">
                    {res.matched_pattern.reporting_channels.map((ch, i) => (
                      <div key={i} className="scam-channel">
                        <span className="scam-channel-icon">{renderChannelIcon(ch)}</span>
                        <span>{ch}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Source ref */}
              {res.matched_pattern.source_ref && (
                <div className="scam-source-ref">
                  <Info size={14} />
                  <span>
                    <strong>Official reference:</strong> {res.matched_pattern.source_ref}
                  </span>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Safety Guidance if not matched but suspicious/safe */}
        {!isMatched && (
          <div className="scam-guidance-card">
            <h4>Recommended Safety Actions</h4>
            <ul className="scam-guidance-list">
              {(res.recommended_actions || []).map((action, i) => (
                <li key={i}>
                  <CheckCircle size={16} className="guidance-check" />
                  <span>{action}</span>
                </li>
              ))}
            </ul>
            <div className="scam-emergency-footer">
              <PhoneCall size={20} className="emergency-icon" />
              <div>
                <strong>National Cybercrime Helpline: 1930</strong>
                <p>Call immediately if money was transferred, or report at <strong>cybercrime.gov.in</strong>.</p>
              </div>
            </div>
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="scam-page">
      {/* Hero */}
      <header className="scam-hero">
        <div className="scam-hero-inner">
          <div className="scam-hero-badge">
            <ShieldCheck size={14} />
            {/* NOTE: "Module 8 · " prefix hidden from UI. Original: "Module 8 · Admin-Managed Scam Intelligence" */}
            <span>Admin-Managed Scam Intelligence</span>
          </div>
          <h1>Scam Intelligence & <span>Document Analysis</span></h1>
          <p className="scam-hero-sub">
            Upload suspicious documents, notices, chat screenshots, or paste call transcripts.
            LEXIS extracts deceptive signals, checks against verified government intelligence,
            and discovers emerging scam patterns.
          </p>
          <div className="scam-hero-stats">
            <div className="scam-stat">
              <span className="scam-stat-num">Verified DB</span>
              <span className="scam-stat-label">Authoritative Patterns</span>
            </div>
            <div className="scam-stat">
              <span className="scam-stat-num">OCR + Multi-format</span>
              <span className="scam-stat-label">PDF, DOCX, Images, JSON</span>
            </div>
            <div className="scam-stat">
              <span className="scam-stat-num">0 Fabrication</span>
              <span className="scam-stat-label">DB-Grounded Legal Facts</span>
            </div>
          </div>
        </div>
      </header>

      {/* Main Container */}
      <main className="scam-body">
        {/* Tab switch */}
        <div className="scam-tab-switcher">
          <button
            type="button"
            className={`scam-tab-btn ${activeTab === 'text' ? 'active' : ''}`}
            onClick={() => setActiveTab('text')}
          >
            <FileText size={16} />
            <span>Paste Message / Transcript</span>
          </button>
          <button
            type="button"
            className={`scam-tab-btn ${activeTab === 'file' ? 'active' : ''}`}
            onClick={() => setActiveTab('file')}
          >
            <UploadCloud size={16} />
            <span>Upload Document / Screenshot</span>
          </button>
        </div>

        {/* Input Card */}
        <div className="scam-input-card">
          {activeTab === 'text' ? (
            <>
              <h2>Describe the suspicious incident or paste message</h2>
              <p>
                Include details: who called, what authority they claimed, payment requests,
                phone numbers, or links. The more detail, the more accurate the indicator extraction.
              </p>
              <textarea
                id="scam-description-input"
                className="scam-textarea"
                value={description}
                onChange={e => setDescription(e.target.value.slice(0, MAX_CHARS))}
                placeholder="e.g. A person called claiming to be a CBI Inspector from Delhi Police. They told me my Aadhaar is linked to illegal parcels with drugs and I am under 'digital arrest'. They asked me to transfer ₹50,000 to a verification account..."
                disabled={loading}
                rows={5}
                aria-label="Describe suspicious situation"
              />
              <div className="scam-char-counter">
                {description.length} / {MAX_CHARS}
              </div>
            </>
          ) : (
            <>
              <h2>Upload suspicious document, notice, or screenshot</h2>
              <p>
                Supports PDF notices, DOCX letters, images/screenshots (PNG, JPG, WEBP), TXT transcripts, or JSON logs. Max 15 MB.
              </p>

              {!selectedFile ? (
                <div
                  className={`scam-dropzone ${isDragging ? 'is-dragging' : ''}`}
                  onDragOver={handleDragOver}
                  onDragLeave={handleDragLeave}
                  onDrop={handleDrop}
                  onClick={() => fileInputRef.current?.click()}
                >
                  <input
                    type="file"
                    ref={fileInputRef}
                    className="scam-hidden-file-input"
                    accept=".pdf,.docx,.txt,.json,.png,.jpg,.jpeg,.webp"
                    onChange={handleFileInputChange}
                  />
                  <div className="scam-dropzone-icon">
                    <UploadCloud size={38} />
                  </div>
                  <h4>Drag and drop your file here, or click to browse</h4>
                  <p>Supported: PDF, Word (DOCX), Text, JSON, PNG, JPG (Max 15MB)</p>
                </div>
              ) : (
                <div className="scam-selected-file">
                  <div className="scam-file-info">
                    <File size={28} className="scam-file-icon" />
                    <div>
                      <span className="scam-file-name">{selectedFile.name}</span>
                      <span className="scam-file-meta">
                        {(selectedFile.size / (1024 * 1024)).toFixed(2)} MB · {selectedFile.type || 'Document'}
                      </span>
                    </div>
                  </div>
                  <button
                    type="button"
                    className="scam-remove-file-btn"
                    onClick={handleRemoveFile}
                    title="Remove file"
                  >
                    <X size={18} />
                  </button>
                </div>
              )}

              <div className="scam-file-note-box">
                <label htmlFor="file-note">Additional Context (Optional):</label>
                <input
                  id="file-note"
                  type="text"
                  placeholder="e.g. Received this PDF via WhatsApp from an unknown number demanding immediate UPI transfer..."
                  value={fileNote}
                  onChange={e => setFileNote(e.target.value)}
                  disabled={loading}
                />
              </div>
            </>
          )}

          {/* Action bar */}
          <div className="scam-actions">
            <div className="scam-hint">
              <Lock size={14} />
              <span>Passwords, card numbers, and OTPs are redacted prior to intelligence analysis.</span>
            </div>
            <div style={{ display: 'flex', gap: '0.75rem' }}>
              {(result || description || selectedFile) && (
                <button onClick={handleReset} className="btn-reset-scam">
                  <RotateCcw size={14} />
                  <span>Reset</span>
                </button>
              )}
              <button
                id="scam-check-button"
                className="scam-check-btn"
                onClick={handleAnalyze}
                disabled={!canSubmit}
              >
                {loading ? (
                  <>
                    <span className="scam-btn-spinner" />
                    <span>Analyzing Indicators…</span>
                  </>
                ) : (
                  <>
                    <Search size={16} />
                    <span>Analyze for Scams</span>
                  </>
                )}
              </button>
            </div>
          </div>
        </div>

        {/* Loading state */}
        {loading && (
          <div className="scam-analyzing">
            <div className="scam-analyzing-pulse">
              <Search size={24} className="animate-pulse" />
            </div>
            <p>
              <strong>Extracting indicators & scanning verified intelligence…</strong><br />
              Parsing text → Redacting sensitive credentials → Identifying extortion signals → Matching verified knowledge base
            </p>
          </div>
        )}

        {/* Error state */}
        {error && !loading && (
          <div className="scam-error">
            <AlertTriangle size={20} className="scam-error-icon" />
            <div className="scam-error-text">
              <h4>Analysis halted</h4>
              <p>{error}</p>
            </div>
          </div>
        )}

        {/* Results */}
        {result && !loading && renderOutcome(result)}

        {/* Quick examples */}
        {!result && !loading && activeTab === 'text' && (
          <div className="scam-examples">
            <h3>Example situations to test</h3>
            <div className="scam-examples-grid">
              {EXAMPLE_PROMPTS.map((ex, i) => {
                const PromptIcon = ex.icon;
                return (
                  <button
                    key={i}
                    id={`scam-example-${i}`}
                    className="scam-example-chip"
                    onClick={() => handleExample(ex.text)}
                    title="Click to use this example"
                  >
                    <span className="scam-example-chip-icon">
                      <PromptIcon size={16} />
                    </span>
                    <span>{ex.text}</span>
                  </button>
                );
              })}
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
