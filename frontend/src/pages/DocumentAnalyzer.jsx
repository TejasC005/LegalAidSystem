/*
 * frontend/src/pages/DocumentAnalyzer.jsx
 * ──────────────────────────────────────────────────────────────────────────
 * LEXIS — Document Analyzer Feature Page (Module 7)
 *
 * Replaces the Module 3 placeholder with a full document analysis UI:
 *   1. Drag-and-drop file upload zone (PDF, JPEG, PNG accepted).
 *   2. File validation feedback before sending.
 *   3. Animated loading state during analysis.
 *   4. Side-by-side view: original clause text ↔ risk badge + plain explanation.
 *   5. Color-coded by risk: 🟢 Green (safe) / 🟡 Yellow (caution) / 🔴 Red (high risk).
 *   6. Summary statistics bar: total clauses, risk breakdown counts.
 *   7. Filter pills to show only specific risk levels.
 * ──────────────────────────────────────────────────────────────────────────
 */

import React, { useState, useRef, useCallback } from 'react';
import { uploadDocumentForAnalysis } from '../services/api';
import './DocumentAnalyzer.css';

// ── Constants ────────────────────────────────────────────────────────────────
const ACCEPTED_TYPES = ['application/pdf', 'image/jpeg', 'image/png'];
const MAX_SIZE_MB = 10;
const MAX_SIZE_BYTES = MAX_SIZE_MB * 1024 * 1024;

const RISK_CONFIG = {
  green:  { emoji: '🟢', label: 'Low Risk',    className: 'green'  },
  yellow: { emoji: '🟡', label: 'Caution',     className: 'yellow' },
  red:    { emoji: '🔴', label: 'High Risk',   className: 'red'    },
};

const FILE_ICONS = {
  'application/pdf': '📄',
  'image/jpeg':      '🖼️',
  'image/png':       '🖼️',
};

// ── Helper: format bytes ──────────────────────────────────────────────────────
function formatBytes(bytes) {
  if (bytes < 1024)       return `${bytes} B`;
  if (bytes < 1048576)    return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1048576).toFixed(1)} MB`;
}

// ── Helper: truncate long clause text for display ─────────────────────────────
function truncateClause(text, maxChars = 300) {
  if (!text || text.length <= maxChars) return text;
  return text.slice(0, maxChars) + '…';
}


// =============================================================================
// MAIN COMPONENT
// =============================================================================

function DocumentAnalyzer() {
  // File selection state
  const [selectedFile, setSelectedFile] = useState(null);
  const [dragActive, setDragActive]     = useState(false);
  const [clientError, setClientError]   = useState('');
  const fileInputRef = useRef(null);

  // Analysis state
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [analysisResult, setAnalysisResult] = useState(null);
  const [serverError, setServerError]       = useState('');

  // Filter state
  const [activeFilter, setActiveFilter] = useState('all');


  // ── File validation (client-side pre-check) ─────────────────────────────
  const validateFile = useCallback((file) => {
    if (!file) return 'No file selected.';
    if (!ACCEPTED_TYPES.includes(file.type)) {
      return `File type "${file.type || 'unknown'}" is not accepted. Please upload a PDF, JPEG, or PNG.`;
    }
    if (file.size > MAX_SIZE_BYTES) {
      return `File is too large (${formatBytes(file.size)}). Maximum allowed size is ${MAX_SIZE_MB} MB.`;
    }
    return null; // null = no error
  }, []);

  // ── Handle file selection (from input click or drop) ──────────────────
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

  // ── Input change handler ───────────────────────────────────────────────
  const onInputChange = (e) => {
    const file = e.target.files?.[0];
    if (file) handleFileSelect(file);
    // Reset input value so the same file can be re-selected after removal
    e.target.value = '';
  };

  // ── Drag-and-drop handlers ─────────────────────────────────────────────
  const onDragOver  = (e) => { e.preventDefault(); setDragActive(true); };
  const onDragLeave = (e) => { e.preventDefault(); setDragActive(false); };
  const onDrop      = (e) => {
    e.preventDefault();
    setDragActive(false);
    const file = e.dataTransfer.files?.[0];
    if (file) handleFileSelect(file);
  };

  // ── Remove selected file ──────────────────────────────────────────────
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
      const response = await uploadDocumentForAnalysis(selectedFile);
      setAnalysisResult(response.data);
      setActiveFilter('all'); // Reset filter on new result
    } catch (err) {
      const detail = err.response?.data?.detail;
      setServerError(
        detail ||
        'Analysis failed. Please check your file and try again.'
      );
    } finally {
      setIsAnalyzing(false);
    }
  };

  // ── Filter clauses ────────────────────────────────────────────────────
  const filteredClauses = analysisResult?.clauses?.filter((c) => {
    if (activeFilter === 'all') return true;
    return c.risk_level === activeFilter;
  }) ?? [];


  // ==========================================================================
  // RENDER
  // ==========================================================================

  return (
    <div className="analyzer-page">
      {/* ── Page Header ──────────────────────────────────────────────── */}
      <div className="analyzer-header">
        <h1>📄 Document Analyzer</h1>
        <p>
          Upload a contract, rent agreement, or legal notice to receive a clause-by-clause
          risk analysis with plain-language explanations.
        </p>
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

        <span className="upload-icon">☁️</span>
        <h3>
          {dragActive
            ? 'Drop your document here'
            : 'Drag & drop your document here'}
        </h3>
        <p>or click to browse</p>

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
          <span>⚠️</span>
          <span>{clientError}</span>
        </div>
      )}

      {/* ── Selected file info card ───────────────────────────────────── */}
      {selectedFile && (
        <div className="selected-file-card">
          <span className="selected-file-icon">
            {FILE_ICONS[selectedFile.type] ?? '📁'}
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
            ✕ Remove
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
          🔍 Analyze Document
        </button>
      )}

      {/* ── Progress bar (while analyzing) ───────────────────────────── */}
      {isAnalyzing && (
        <div className="progress-bar-wrapper" role="status" aria-live="polite">
          <div className="progress-label">
            <span className="spinner" aria-hidden="true" />
            Extracting text and analyzing clauses…
          </div>
          <div className="progress-track">
            <div className="progress-fill" />
          </div>
        </div>
      )}

      {/* ── Server error ─────────────────────────────────────────────── */}
      {serverError && (
        <div className="error-card" role="alert">
          <span>❌</span>
          <span>{serverError}</span>
        </div>
      )}

      {/* ── Results ──────────────────────────────────────────────────── */}
      {analysisResult && (
        <section className="results-section" aria-label="Analysis results">

          {/* Summary stat cards */}
          <div className="results-summary-bar">
            <div className="summary-stat-card total">
              <div className="stat-number">{analysisResult.total_clauses}</div>
              <div className="stat-label">Total Clauses</div>
            </div>
            <div className="summary-stat-card green">
              <div className="stat-number">{analysisResult.green_count}</div>
              <div className="stat-label">🟢 Safe</div>
            </div>
            <div className="summary-stat-card yellow">
              <div className="stat-number">{analysisResult.yellow_count}</div>
              <div className="stat-label">🟡 Caution</div>
            </div>
            <div className="summary-stat-card red">
              <div className="stat-number">{analysisResult.red_count}</div>
              <div className="stat-label">🔴 High Risk</div>
            </div>
          </div>

          {/* Filter + header */}
          <div className="results-header">
            <h2>Clause-by-Clause Analysis</h2>
            <div className="filter-pills" role="group" aria-label="Filter clauses by risk level">
              {['all', 'green', 'yellow', 'red'].map((f) => (
                <button
                  key={f}
                  id={`filter-${f}`}
                  className={`filter-pill ${activeFilter === f ? `active-${f}` : ''}`}
                  onClick={() => setActiveFilter(f)}
                  aria-pressed={activeFilter === f}
                >
                  {f === 'all' ? 'All' : RISK_CONFIG[f].emoji + ' ' + RISK_CONFIG[f].label}
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
                        📋 Original Clause
                      </div>
                      <p className="clause-text-original">
                        {truncateClause(clause.text)}
                      </p>
                    </div>

                    {/* Right panel: analysis */}
                    <div className="clause-analysis">
                      <div className="clause-panel-label">
                        🔍 Risk Analysis
                      </div>

                      {/* Risk badge */}
                      <span className={`risk-badge ${risk.className}`}>
                        {risk.emoji} {risk.label}
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
        </section>
      )}
    </div>
  );
}

export default DocumentAnalyzer;
