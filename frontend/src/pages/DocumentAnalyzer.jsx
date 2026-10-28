/*
 * frontend/src/pages/DocumentAnalyzer.jsx
 * ──────────────────────────────────────────────────────────────────────────
 * LEXIS — Intelligent Multi-Document Analyzer (Module 7)
 *
 * Supports auto-detection and adaptive views for:
 *   1. Identity Documents (Aadhaar & PAN Cards) with verified profile card,
 *      copyable masked ID, prior memory sync status, and 1-click draft pre-fill.
 *   2. Court Judgments & Orders with verdict banners, plain-language translations
 *      in English and Hindi, and operative directions checklists.
 *   3. Rental Agreements with key terms grids (Rent, Deposit, Tenure) and
 *      tab-switched clause risk reviews.
 *   4. Legal Contracts with color-coded clause-by-clause risk scoring.
 * ──────────────────────────────────────────────────────────────────────────
 */

import React, { useState, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  FileSearch,
  UploadCloud,
  UserCheck,
  Scale,
  Home,
  FileText,
  Image as ImageIcon,
  File,
  CheckCircle2,
  AlertTriangle,
  AlertOctagon,
  Search,
  X,
  Landmark,
  Copy,
  Check,
  MapPin,
  Info,
  FileEdit,
  Calendar,
  Lightbulb,
  BookOpen,
  ShieldCheck,
  ArrowRight,
  Loader2,
} from 'lucide-react';
import { uploadDocumentForAnalysis } from '../services/api';
import './DocumentAnalyzer.css';

// ── Constants ────────────────────────────────────────────────────────────────
const ACCEPTED_TYPES = ['application/pdf', 'image/jpeg', 'image/png'];
const MAX_SIZE_MB = 10;
const MAX_SIZE_BYTES = MAX_SIZE_MB * 1024 * 1024;

const RISK_CONFIG = {
  green:  { label: 'Low Risk',    className: 'green'  },
  yellow: { label: 'Caution',     className: 'yellow' },
  red:    { label: 'High Risk',   className: 'red'    },
};

function formatBytes(bytes) {
  if (bytes < 1024)    return `${bytes} B`;
  if (bytes < 1048576) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1048576).toFixed(1)} MB`;
}

function truncateClause(text, maxChars = 300) {
  if (!text || text.length <= maxChars) return text;
  return text.slice(0, maxChars) + '…';
}

function DocumentAnalyzer() {
  const navigate = useNavigate();

  // File selection state
  const [selectedFile, setSelectedFile] = useState(null);
  const [dragActive, setDragActive]     = useState(false);
  const [clientError, setClientError]   = useState('');
  const fileInputRef = useRef(null);

  // Analysis state
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [analysisResult, setAnalysisResult] = useState(null);
  const [serverError, setServerError]       = useState('');

  // UI view tabs
  const [activeFilter, setActiveFilter] = useState('all');
  const [rentalTab, setRentalTab]       = useState('terms'); // 'terms' | 'clauses'
  const [copiedId, setCopiedId]         = useState(false);
  const [showConflicts, setShowConflicts] = useState(false);

  // ── File validation (client-side pre-check) ─────────────────────────────
  const validateFile = useCallback((file) => {
    if (!file) return 'No file selected.';
    if (!ACCEPTED_TYPES.includes(file.type)) {
      return `File type "${file.type || 'unknown'}" is not accepted. Please upload a PDF, JPEG, or PNG.`;
    }
    if (file.size > MAX_SIZE_BYTES) {
      return `File is too large (${formatBytes(file.size)}). Maximum allowed size is ${MAX_SIZE_MB} MB.`;
    }
    return null;
  }, []);

  // ── Handle file selection ──────────────────────────────────────────────
  const handleFileSelect = useCallback((file) => {
    setClientError('');
    setServerError('');
    setAnalysisResult(null);

    const error = validateFile(file);
    if (error) {
      setClientError(error);
      return;
    }
    setSelectedFile(file);
  }, [validateFile]);

  const onInputChange = (e) => {
    const file = e.target.files?.[0];
    if (file) handleFileSelect(file);
    e.target.value = '';
  };

  const onDragOver  = (e) => { e.preventDefault(); setDragActive(true); };
  const onDragLeave = (e) => { e.preventDefault(); setDragActive(false); };
  const onDrop      = (e) => {
    e.preventDefault();
    setDragActive(false);
    const file = e.dataTransfer.files?.[0];
    if (file) handleFileSelect(file);
  };

  const removeFile = () => {
    setSelectedFile(null);
    setClientError('');
    setServerError('');
    setAnalysisResult(null);
  };

  // ── Upload and analyze ────────────────────────────────────────────────
  const handleAnalyze = async () => {
    if (!selectedFile || isAnalyzing) return;
    setIsAnalyzing(true);
    setServerError('');
    setAnalysisResult(null);

    try {
      const storedSession = localStorage.getItem('lexis_active_session_id');
      const sessionId = (storedSession && storedSession !== 'undefined' && storedSession !== 'null') ? storedSession : null;
      const response = await uploadDocumentForAnalysis(selectedFile, sessionId);
      setAnalysisResult(response.data);
      setActiveFilter('all');
      setRentalTab('terms');
    } catch (err) {
      const detail = err.response?.data?.detail;
      const errMsg = typeof detail === 'string'
        ? detail
        : Array.isArray(detail)
          ? detail.map((d) => d.msg || JSON.stringify(d)).join(', ')
          : (err.message || 'Analysis failed. Please check your file and try again.');
      setServerError(errMsg);
    } finally {
      setIsAnalyzing(false);
    }
  };

  const copyToClipboard = (text) => {
    if (!text) return;
    navigator.clipboard.writeText(text);
    setCopiedId(true);
    setTimeout(() => setCopiedId(false), 2000);
  };

  // Filter clauses
  const filteredClauses = analysisResult?.clauses?.filter((c) => {
    if (activeFilter === 'all') return true;
    return c.risk_level === activeFilter;
  }) ?? [];

  const category = analysisResult?.document_category || 'agreement_contract';
  const extracted = analysisResult?.extracted_info || {};

  const renderCategoryIcon = (cat) => {
    switch (cat) {
      case 'identity_document':
        return <UserCheck size={18} />;
      case 'court_document':
        return <Scale size={18} />;
      case 'agreement_contract':
        return <Home size={18} />;
      default:
        return <FileText size={18} />;
    }
  };

  const getCategoryLabel = (cat) => {
    switch (cat) {
      case 'identity_document':
        return 'Identity Document';
      case 'court_document':
        return 'Court Order / Judgment';
      case 'agreement_contract':
        return 'Agreement / Lease';
      default:
        return 'Legal Document';
    }
  };

  const renderFileIcon = (mimeType) => {
    if (mimeType === 'application/pdf') return <FileText size={24} color="#1a6b5a" />;
    if (mimeType?.startsWith('image/')) return <ImageIcon size={24} color="#1a6b5a" />;
    return <File size={24} color="#1a6b5a" />;
  };

  return (
    <div className="analyzer-page">
      {/* ── Page Header Banner ────────────────────────────────────────── */}
      <div className="analyzer-header">
        <div className="analyzer-header-content">
          <div className="analyzer-icon-box">
            <FileSearch size={28} color="#ffffff" />
          </div>
          <div>
            <h1>Intelligent Document Analyzer</h1>
            <p>
              Upload any legal document, Indian identity card (Aadhaar / PAN), rental agreement,
              or court order for instant intelligence extraction, memory pre-filling, and risk scoring.
            </p>
          </div>
        </div>
      </div>

      {/* ── Upload Zone ──────────────────────────────────────────────── */}
      <div
        id="upload-zone"
        className={`upload-zone ${dragActive ? 'drag-active' : ''}`}
        onDragOver={onDragOver}
        onDragLeave={onDragLeave}
        onDrop={onDrop}
        onClick={() => !selectedFile && fileInputRef.current?.click()}
        role="button"
        tabIndex={0}
        aria-label="Upload document for analysis"
        onKeyDown={(e) => e.key === 'Enter' && fileInputRef.current?.click()}
      >
        <input
          ref={fileInputRef}
          type="file"
          accept=".pdf,.jpg,.jpeg,.png"
          onChange={onInputChange}
          style={{ display: 'none' }}
          id="file-input"
          aria-hidden="true"
        />

        <div className="upload-icon-container">
          <UploadCloud size={44} className="upload-icon-svg" />
        </div>
        <h3>
          {dragActive
            ? 'Drop your document here'
            : 'Drag & drop your document here, or browse files'}
        </h3>
        <p>Supported: Aadhaar, PAN Card, Rental Agreement, Court Judgment, or Commercial Contract</p>

        <div className="file-types">
          <span className="file-type-badge">PDF</span>
          <span className="file-type-badge">JPEG</span>
          <span className="file-type-badge">PNG</span>
          <span className="file-type-badge">Max {MAX_SIZE_MB} MB</span>
        </div>
      </div>

      {/* ── Client-side validation error ─────────────────────────────── */}
      {clientError && (
        <div className="error-card" role="alert">
          <AlertTriangle size={18} />
          <span>{clientError}</span>
        </div>
      )}

      {/* ── Selected file info card ───────────────────────────────────── */}
      {selectedFile && (
        <div className="selected-file-card">
          <span className="selected-file-icon">
            {renderFileIcon(selectedFile.type)}
          </span>
          <div className="selected-file-info">
            <div className="selected-file-name">{selectedFile.name}</div>
            <div className="selected-file-meta">
              {selectedFile.type} · {formatBytes(selectedFile.size)}
            </div>
          </div>
          <button
            id="btn-remove-file"
            className="btn-remove-file"
            onClick={removeFile}
            disabled={isAnalyzing}
            aria-label="Remove selected file"
          >
            <X size={14} />
            <span>Remove</span>
          </button>
        </div>
      )}

      {/* ── Analyze button ────────────────────────────────────────────── */}
      {selectedFile && !isAnalyzing && (
        <button
          id="btn-analyze"
          className="btn-analyze"
          onClick={handleAnalyze}
          disabled={isAnalyzing || !selectedFile}
        >
          <Search size={18} />
          <span>Analyze & Extract Document</span>
        </button>
      )}

      {/* ── Progress bar (while analyzing) ───────────────────────────── */}
      {isAnalyzing && (
        <div className="progress-bar-wrapper" role="status" aria-live="polite">
          <div className="progress-label">
            <Loader2 size={16} className="spinning-icon" />
            <span>Reading document, classifying structure, and extracting intelligence…</span>
          </div>
          <div className="progress-track">
            <div className="progress-fill" />
          </div>
        </div>
      )}

      {/* ── Server error ─────────────────────────────────────────────── */}
      {serverError && (
        <div className="error-card" role="alert">
          <AlertOctagon size={18} />
          <span>{serverError}</span>
        </div>
      )}

      {/* ── Results Container ────────────────────────────────────────── */}
      {analysisResult && (
        <section className="results-section" aria-label="Analysis results">

          {/* Document Type Header Badge */}
          <div className="doc-category-banner">
            <span className={`doc-category-chip cat-${category}`}>
              {renderCategoryIcon(category)}
              <span>{analysisResult.document_title || getCategoryLabel(category)}</span>
            </span>
            {analysisResult.memory_saved && (
              <span className="memory-saved-chip">
                <CheckCircle2 size={15} />
                <span>Synchronized to Memory & Profile</span>
              </span>
            )}
          </div>

          {/* ========================================================== */}
          {/* VIEW 1: IDENTITY PROFILE CARD (AADHAAR / PAN)              */}
          {/* ========================================================== */}
          {category === 'identity_document' && (
            <div className="identity-profile-view">
              <div className="id-card-wrapper">
                {/* ID Card Top Header */}
                <div className="id-card-header">
                  <div className="id-authority-badge">
                    <Landmark size={15} />
                    <span>{extracted.issuing_authority || 'Government of India'}</span>
                  </div>
                  <div className="id-type-pill">
                    {extracted.id_type || 'Identity Card'}
                  </div>
                </div>

                {/* ID Card Body */}
                <div className="id-card-body">
                  <div className="id-main-details">
                    <div className="id-name-label">NAME / नाम</div>
                    <div className="id-name-value">{extracted.name || 'Not Detected'}</div>

                    <div className="id-number-row">
                      <span className="id-number-label">ID NUMBER:</span>
                      <span className="id-number-value">{extracted.id_number || '•••• •••• ••••'}</span>
                      {extracted.id_number && (
                        <button
                          className="btn-copy-id"
                          onClick={() => copyToClipboard(extracted.id_number)}
                          title="Copy ID Number"
                        >
                          {copiedId ? (
                            <>
                              <Check size={13} />
                              <span>Copied</span>
                            </>
                          ) : (
                            <>
                              <Copy size={13} />
                              <span>Copy</span>
                            </>
                          )}
                        </button>
                      )}
                    </div>
                  </div>

                  <div className="id-meta-grid">
                    <div className="id-meta-item">
                      <span className="id-meta-label">DATE OF BIRTH / जन्म तिथि</span>
                      <span className="id-meta-val">
                        {extracted.dob || '—'} {extracted.dob_iso && <small>({extracted.dob_iso})</small>}
                      </span>
                    </div>

                    <div className="id-meta-item">
                      <span className="id-meta-label">GENDER / लिंग</span>
                      <span className="id-meta-val">{extracted.gender || '—'}</span>
                    </div>

                    {extracted.care_of && (
                      <div className="id-meta-item">
                        <span className="id-meta-label">CARE OF / FATHER</span>
                        <span className="id-meta-val">{extracted.care_of}</span>
                      </div>
                    )}

                    {extracted.city && (
                      <div className="id-meta-item">
                        <span className="id-meta-label">CITY / DISTRICT</span>
                        <span className="id-meta-val">{extracted.city}</span>
                      </div>
                    )}
                  </div>

                  {extracted.address ? (
                    <div className="id-address-box">
                      <span className="id-address-label">
                        <MapPin size={13} /> ADDRESS / पता:
                      </span>
                      <p className="id-address-text">{extracted.address}</p>
                    </div>
                  ) : (extracted.card_side === 'front' || extracted.id_type === 'Aadhaar Card') ? (
                    <div className="id-address-box id-front-side-tip">
                      <span className="id-address-label">
                        <Info size={14} /> AADHAAR FRONT VERIFIED:
                      </span>
                      <p className="id-address-text">
                        Name, DOB, Gender, and Masked ID verified successfully. Your permanent address is located on the back side of this card.
                      </p>
                    </div>
                  ) : null}
                </div>

                {/* Prior Memory Synchronization Status Banner */}
                <div className={`memory-status-banner ${analysisResult.memory_action}`}>
                  {analysisResult.prior_info_found ? (
                    analysisResult.memory_action === 'conflict_detected' ? (
                      <div className="memory-banner-content">
                        <span>
                          <AlertTriangle size={15} style={{ verticalAlign: 'text-bottom', marginRight: 4 }} />
                          <strong>Discrepancy Detected:</strong> Details on this document differ from your existing profile.
                        </span>
                        <button className="btn-toggle-diff" onClick={() => setShowConflicts(!showConflicts)}>
                          {showConflicts ? 'Hide Discrepancy' : 'View Discrepancy'}
                        </button>
                      </div>
                    ) : (
                      <div className="memory-banner-content">
                        <span>
                          <Info size={15} style={{ verticalAlign: 'text-bottom', marginRight: 4 }} />
                          <strong>Intelligently Merged:</strong> Prior profile found. Verified identity details merged and existing fields preserved.
                        </span>
                      </div>
                    )
                  ) : (
                    <div className="memory-banner-content">
                      <span>
                        <CheckCircle2 size={15} style={{ verticalAlign: 'text-bottom', marginRight: 4 }} />
                        <strong>Saved to Memory:</strong> Verified identity details stored in your profile. The Document Drafter will automatically use these details.
                      </span>
                    </div>
                  )}
                </div>

                {/* Collapsible Conflicts Drawer */}
                {showConflicts && analysisResult.conflicts && analysisResult.conflicts.length > 0 && (
                  <div className="conflicts-drawer">
                    <h4>Profile Discrepancies</h4>
                    {analysisResult.conflicts.map((conf, idx) => (
                      <div key={idx} className="conflict-row">
                        <span className="conflict-field">{conf.field}:</span>
                        <span className="conflict-prior">Profile was: "{conf.prior}"</span>
                        <span className="conflict-extracted">Document has: "{conf.extracted}"</span>
                      </div>
                    ))}
                  </div>
                )}

                {/* Action footer */}
                <div className="id-card-actions">
                  <button
                    className="btn-use-drafter"
                    onClick={() => navigate('/document-drafter')}
                  >
                    <FileEdit size={16} />
                    <span>Start Legal Draft with these details →</span>
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* ========================================================== */}
          {/* VIEW 2: COURT JUDGMENT / ORDER CARD                       */}
          {/* ========================================================== */}
          {category === 'court_document' && (
            <div className="court-verdict-view">
              {/* Operative Verdict Banner */}
              <div className={`verdict-banner ${
                String(extracted.verdict || '').includes('GRANTED') || String(extracted.verdict || '').includes('ALLOWED')
                  ? 'verdict-granted'
                  : String(extracted.verdict || '').includes('DISMISSED') || String(extracted.verdict || '').includes('REJECTED')
                  ? 'verdict-dismissed'
                  : 'verdict-neutral'
              }`}>
                <div className="verdict-label">OPERATIVE OUTCOME</div>
                <div className="verdict-title">{extracted.verdict || 'ORDER PASSED'}</div>
              </div>

              {/* Case Metadata Pills */}
              <div className="court-meta-bar">
                {extracted.court_name && (
                  <div className="court-meta-pill">
                    <Landmark size={14} />
                    <span>{extracted.court_name}</span>
                  </div>
                )}
                {extracted.case_number && (
                  <div className="court-meta-pill">
                    <FileText size={14} />
                    <span>{extracted.case_number}</span>
                  </div>
                )}
                {extracted.decision_date && (
                  <div className="court-meta-pill">
                    <Calendar size={14} />
                    <span>{extracted.decision_date}</span>
                  </div>
                )}
                {extracted.bench && (
                  <div className="court-meta-pill">
                    <Scale size={14} />
                    <span>Bench: {extracted.bench}</span>
                  </div>
                )}
              </div>

              {/* Parties */}
              {(extracted.petitioner || extracted.respondent) && (
                <div className="parties-card">
                  <div className="party-box">
                    <span className="party-role">PETITIONER / APPLICANT:</span>
                    <span className="party-name">{extracted.petitioner || '—'}</span>
                  </div>
                  <div className="party-vs">VS</div>
                  <div className="party-box">
                    <span className="party-role">RESPONDENT / STATE:</span>
                    <span className="party-name">{extracted.respondent || '—'}</span>
                  </div>
                </div>
              )}

              {/* Plain Language Bilingual Explanation */}
              <div className="plain-explanation-card">
                <div className="explanation-header">
                  <Lightbulb size={17} color="#047857" />
                  <span>In Simple Words / सरल शब्दों में अदालत का फैसला</span>
                </div>
                <div className="explanation-body">
                  <p className="explanation-en">{analysisResult.plain_language_summary}</p>
                  {analysisResult.plain_language_summary_hi && (
                    <p className="explanation-hi">{analysisResult.plain_language_summary_hi}</p>
                  )}
                </div>
              </div>

              {/* Operative directions & Key Actions */}
              {extracted.key_actions && extracted.key_actions.length > 0 && (
                <div className="directions-card">
                  <div className="directions-header">
                    <CheckCircle2 size={17} color="#059669" />
                    <h3>Required Actions & Compliance Checklist</h3>
                  </div>
                  <ul className="directions-list">
                    {extracted.key_actions.map((act, i) => (
                      <li key={i}>{act}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}

          {/* ========================================================== */}
          {/* VIEW 3: RENTAL AGREEMENT TERMS VIEW                        */}
          {/* ========================================================== */}
          {analysisResult.document_type === 'rental_agreement' && (
            <div className="rental-view-wrapper">
              {/* Tab Navigation */}
              <div className="rental-tabs">
                <button
                  className={`rental-tab-btn ${rentalTab === 'terms' ? 'active' : ''}`}
                  onClick={() => setRentalTab('terms')}
                >
                  <Home size={15} />
                  <span>Key Lease Terms & Rights Summary</span>
                </button>
                <button
                  className={`rental-tab-btn ${rentalTab === 'clauses' ? 'active' : ''}`}
                  onClick={() => setRentalTab('clauses')}
                >
                  <FileSearch size={15} />
                  <span>Clause Risk Analysis ({analysisResult.total_clauses})</span>
                </button>
              </div>

              {rentalTab === 'terms' ? (
                <div className="rental-terms-view">
                  {/* Key Terms Grid */}
                  <div className="terms-grid">
                    <div className="term-card">
                      <span className="term-label">MONTHLY RENT</span>
                      <span className="term-val highlight">{extracted.monthly_rent || 'Not Stated'}</span>
                      <small>{extracted.rent_due_day || 'Due monthly'}</small>
                    </div>
                    <div className="term-card">
                      <span className="term-label">SECURITY DEPOSIT</span>
                      <span className="term-val">{extracted.security_deposit || 'Not Stated'}</span>
                      <small>{extracted.deposit_refund_terms || 'Refundable'}</small>
                    </div>
                    <div className="term-card">
                      <span className="term-label">TENURE / DURATION</span>
                      <span className="term-val">{extracted.lease_duration || '11 Months'}</span>
                    </div>
                    <div className="term-card">
                      <span className="term-label">NOTICE PERIOD</span>
                      <span className="term-val">{extracted.notice_period || '1 Month'}</span>
                    </div>
                  </div>

                  {/* Parties & Property Address */}
                  <div className="rental-parties-box">
                    <div className="rental-party">
                      <strong>Landlord / Lessor:</strong> {extracted.landlord_name || '—'}
                    </div>
                    <div className="rental-party">
                      <strong>Tenant / Lessee:</strong> {extracted.tenant_name || '—'}
                    </div>
                    {extracted.property_address && (
                      <div className="rental-address">
                        <strong>Rented Premises:</strong> {extracted.property_address}
                      </div>
                    )}
                  </div>

                  {/* Plain Language Summary */}
                  <div className="plain-explanation-card">
                    <div className="explanation-header">
                      <BookOpen size={17} color="#047857" />
                      <span>Tenancy Explanation & Legal Protection</span>
                    </div>
                    <div className="explanation-body">
                      <p className="explanation-en">{analysisResult.plain_language_summary}</p>
                      {analysisResult.plain_language_summary_hi && (
                        <p className="explanation-hi">{analysisResult.plain_language_summary_hi}</p>
                      )}
                    </div>
                  </div>
                </div>
              ) : null}
            </div>
          )}

          {/* ========================================================== */}
          {/* VIEW 4: CLAUSE RISK ANALYSIS (AGREEMENTS & CONTRACTS)      */}
          {/* ========================================================== */}
          {(category === 'agreement_contract' || category === 'general_legal') &&
           (analysisResult.document_type !== 'rental_agreement' || rentalTab === 'clauses') && (
            <div className="contract-clauses-view">
              {/* Summary stat cards */}
              <div className="results-summary-bar">
                <div className="summary-stat-card total">
                  <div className="stat-number">{analysisResult.total_clauses}</div>
                  <div className="stat-label">Total Clauses</div>
                </div>
                <div className="summary-stat-card green">
                  <div className="stat-number">{analysisResult.green_count}</div>
                  <div className="stat-label-icon">
                    <ShieldCheck size={14} color="#10b981" />
                    <span>Safe</span>
                  </div>
                </div>
                <div className="summary-stat-card yellow">
                  <div className="stat-number">{analysisResult.yellow_count}</div>
                  <div className="stat-label-icon">
                    <AlertTriangle size={14} color="#f59e0b" />
                    <span>Caution</span>
                  </div>
                </div>
                <div className="summary-stat-card red">
                  <div className="stat-number">{analysisResult.red_count}</div>
                  <div className="stat-label-icon">
                    <AlertOctagon size={14} color="#ef4444" />
                    <span>High Risk</span>
                  </div>
                </div>
              </div>

              {/* Filter + header */}
              <div className="results-header">
                <h2>Clause-by-Clause Risk Review</h2>
                <div className="filter-pills" role="group" aria-label="Filter clauses by risk level">
                  {['all', 'green', 'yellow', 'red'].map((f) => (
                    <button
                      key={f}
                      id={`filter-${f}`}
                      className={`filter-pill ${activeFilter === f ? `active-${f}` : ''}`}
                      onClick={() => setActiveFilter(f)}
                      aria-pressed={activeFilter === f}
                    >
                      {f === 'all' ? 'All' : (
                        <>
                          {f === 'green' && <ShieldCheck size={13} style={{ marginRight: 4 }} />}
                          {f === 'yellow' && <AlertTriangle size={13} style={{ marginRight: 4 }} />}
                          {f === 'red' && <AlertOctagon size={13} style={{ marginRight: 4 }} />}
                          {RISK_CONFIG[f].label}
                        </>
                      )}
                      {f !== 'all' && ` (${analysisResult[`${f}_count`]})`}
                    </button>
                  ))}
                </div>
              </div>

              {/* Clause cards */}
              <div className="clauses-list">
                {filteredClauses.length === 0 ? (
                  <p className="empty-filter-msg">
                    No {activeFilter} clauses found in this document.
                  </p>
                ) : (
                  filteredClauses.map((clause, idx) => {
                    const risk = RISK_CONFIG[clause.risk_level] ?? RISK_CONFIG.green;
                    return (
                      <article
                        key={idx}
                        className={`clause-card risk-${risk.className}`}
                        aria-label={`Clause ${idx + 1}: ${risk.label} risk`}
                      >
                        {/* Left panel: original clause */}
                        <div className="clause-original">
                          <div className="clause-panel-label">
                            <FileText size={13} />
                            <span>Original Clause</span>
                          </div>
                          <p className="clause-text-original">
                            {truncateClause(clause.text)}
                          </p>
                        </div>

                        {/* Right panel: analysis */}
                        <div className="clause-analysis">
                          <div className="clause-panel-label">
                            <FileSearch size={13} />
                            <span>Risk Analysis</span>
                          </div>

                          {/* Risk badge */}
                          <span className={`risk-badge ${risk.className}`}>
                            {risk.className === 'green' && <ShieldCheck size={13} />}
                            {risk.className === 'yellow' && <AlertTriangle size={13} />}
                            {risk.className === 'red' && <AlertOctagon size={13} />}
                            <span>{risk.label}</span>
                          </span>

                          {/* Confidence */}
                          {clause.confidence && (
                            <div className="confidence-tag">
                              Confidence: {clause.confidence}
                              {clause.rule_hit && ` · Rule: ${clause.rule_hit}`}
                            </div>
                          )}

                          {/* Explanation */}
                          {clause.explanation && (
                            <p className="clause-explanation">{clause.explanation}</p>
                          )}

                          {/* Plain-language rewrite (YELLOW/RED only) */}
                          {clause.rewrite && (
                            <div className="clause-rewrite">
                              {clause.rewrite}
                            </div>
                          )}
                        </div>
                      </article>
                    );
                  })
                )}
              </div>
            </div>
          )}

        </section>
      )}
    </div>
  );
}

export default DocumentAnalyzer;
