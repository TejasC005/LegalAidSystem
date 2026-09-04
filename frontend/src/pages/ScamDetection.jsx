/*
 * frontend/src/pages/ScamDetection.jsx
 * ──────────────────────────────────────────────────────────────────────────
 * LEXIS — Scam Detection Feature Page (Module 8)
 *
 * UI FLOW:
 *   1. Citizen types or clicks an example description.
 *   2. "Check for Scam" button → POST /api/v1/scam/check
 *   3a. MATCHED: Alert card with DB-grounded scam details.
 *   3b. NO MATCH: Honest fallback with emergency helpline.
 *
 * SAFETY NOTE:
 *   All text shown in the alert card (legal_reality, recommended_action,
 *   reporting_channels) comes directly from the backend DB response —
 *   this component does NOT generate or modify any legal claim.
 * ──────────────────────────────────────────────────────────────────────────
 */

import React, { useState } from 'react';
import { checkScam } from '../services/api';
import './ScamDetection.css';

// ── Quick-example prompts (not suggestions — real representative scenarios) ─
const EXAMPLE_PROMPTS = [
  { icon: '📵', text: 'A person called claiming I am under "digital arrest" by CBI' },
  { icon: '📦', text: 'A courier company said my package was seized with drugs and demanded Rs 15,000' },
  { icon: '📱', text: 'Someone told me to scan a QR code to receive ₹5,000 on PhonePe' },
  { icon: '🔒', text: 'I got a message saying my Aadhaar is suspended and KYC must be updated' },
  { icon: '💰', text: 'An "investment app" on Telegram promised 35% monthly returns on crypto trading' },
  { icon: '🏦', text: 'A caller said my bank account is frozen under PMLA and I must transfer money to a "safe account"' },
];

// ── Severity colour mapping ────────────────────────────────────────────────
function getSeverityLabel(severity) {
  const map = { CRITICAL: '🔴 Critical', HIGH: '🟠 High', MEDIUM: '🔵 Medium' };
  return map[severity] || severity;
}

// ── Match method label ─────────────────────────────────────────────────────
function getMatchLabel(method) {
  const map = { keyword: '⚡ Keyword match', semantic: '🔍 Semantic match', none: '—' };
  return map[method] || method;
}

// ── Parse recommended_action into numbered steps ──────────────────────────
function parseSteps(text) {
  if (!text) return [];
  // Handles "1. Step\n2. Step" or "1) Step\n2) Step" or plain line breaks
  const lines = text.split('\n').filter(l => l.trim());
  return lines.map(l => l.replace(/^\d+[\.\)]\s*/, '').trim()).filter(Boolean);
}

// ── Channel icon helper ───────────────────────────────────────────────────
function channelIcon(channel) {
  if (channel.toLowerCase().includes('cybercrime') || channel.toLowerCase().includes('gov')) return '🌐';
  if (channel.toLowerCase().includes('1930')) return '📞';
  if (channel.toLowerCase().includes('police') || channel.toLowerCase().includes('fir')) return '👮';
  if (channel.toLowerCase().includes('helpline')) return '📞';
  return '📋';
}

// =============================================================================
// Main Component
// =============================================================================

function ScamDetection() {
  const [description, setDescription] = useState('');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);  // ScamCheckResponse or null
  const [error, setError] = useState(null);

  const MAX_CHARS = 2000;
  const MIN_CHARS = 10;

  // ── Submit handler ────────────────────────────────────────────────────────
  async function handleCheck() {
    if (description.trim().length < MIN_CHARS) return;
    setLoading(true);
    setResult(null);
    setError(null);

    try {
      const response = await checkScam(description.trim());
      setResult(response);
    } catch (err) {
      const msg =
        err?.response?.data?.detail ||
        'Failed to connect to the scam detection service. Please try again.';
      setError(msg);
    } finally {
      setLoading(false);
    }
  }

  function handleExample(text) {
    setDescription(text);
    setResult(null);
    setError(null);
  }

  function handleReset() {
    setDescription('');
    setResult(null);
    setError(null);
  }

  const canSubmit = description.trim().length >= MIN_CHARS && !loading;
  const charWarn = description.length > MAX_CHARS * 0.85;

  // ==========================================================================
  // Render helpers
  // ==========================================================================

  function renderAlert(alert) {
    if (!alert.matched) {
      return (
        <div className="scam-no-match">
          <div className="scam-no-match-header">
            <div className="scam-no-match-icon">❓</div>
            <div>
              <h3>Pattern Not Recognised</h3>
              <p>No known scam pattern matched your description.</p>
            </div>
          </div>
          <div className="scam-no-match-body">
            {alert.safe_fallback_message}
          </div>
          <div className="scam-no-match-emergency">
            <span>🚨</span>
            <p>
              If you are in immediate danger or have already lost money,
              call <strong>1930</strong> (National Cyber Helpline) right now.
            </p>
          </div>
        </div>
      );
    }

    const steps = parseSteps(alert.recommended_action);

    return (
      <div className="scam-alert-card" role="alert" aria-live="assertive">
        {/* Header */}
        <div className="scam-alert-header">
          <div className="scam-alert-header-left">
            <div className="scam-alert-icon-box" aria-hidden="true">🚨</div>
            <div>
              <h2 className="scam-alert-name">{alert.pattern_name}</h2>
              <div className="scam-alert-meta">
                <span className={`severity-badge ${alert.severity}`}>
                  {getSeverityLabel(alert.severity)}
                </span>
                <span className="match-chip">{getMatchLabel(alert.match_method)}</span>
              </div>
            </div>
          </div>
          <div className="scam-alert-header-right">
            <span className="scam-trace-id" title="Traceability ID — links to the source database record">
              ID: {alert.db_id}
            </span>
            {alert.match_method === 'semantic' && (
              <span className="scam-confidence">
                Confidence: {Math.round((alert.confidence_score || 0) * 100)}%
              </span>
            )}
          </div>
        </div>

        {/* Body */}
        <div className="scam-alert-body">

          {/* What this scam is */}
          <div className="scam-section">
            <div className="scam-section-label">
              <span>📖</span> What this scam is
            </div>
            <p className="scam-section-content">{alert.description}</p>
          </div>

          {/* Legal Reality — highlighted box */}
          <div className="scam-section legal">
            <div className="scam-section-label">
              <span>⚖️</span> Legal Reality
            </div>
            <p className="scam-section-content">{alert.legal_reality}</p>
          </div>

          {/* Recommended Action */}
          <div className="scam-section">
            <div className="scam-section-label">
              <span>✅</span> What you should do right now
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
              <p className="scam-section-content">{alert.recommended_action}</p>
            )}
          </div>

          {/* Reporting Channels */}
          {alert.reporting_channels && alert.reporting_channels.length > 0 && (
            <div className="scam-section">
              <div className="scam-section-label">
                <span>📢</span> Report to
              </div>
              <div className="scam-channels">
                {alert.reporting_channels.map((ch, i) => (
                  <div key={i} className="scam-channel">
                    <span className="scam-channel-icon">{channelIcon(ch)}</span>
                    {ch}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Source reference — transparency */}
          {alert.source_ref && (
            <div className="scam-source-ref">
              <span>📚</span>
              <span>
                <strong>Legal reference:</strong> {alert.source_ref}
              </span>
            </div>
          )}
        </div>
      </div>
    );
  }

  // ==========================================================================
  // JSX
  // ==========================================================================

  return (
    <div className="scam-page">

      {/* ── Hero ───────────────────────────────────────────────────────────── */}
      <header className="scam-hero">
        <div className="scam-hero-inner">
          <div className="scam-hero-badge">
            <span>🛡️</span> Module 8 — Active
          </div>
          <h1>Scam Detection <span>Engine</span></h1>
          <p className="scam-hero-sub">
            Describe a suspicious call, message, or demand. LEXIS matches it against a
            verified database of known scams and returns grounded legal facts and action steps.
            Every alert traces to an official government or legal source.
          </p>
          <div className="scam-hero-stats">
            <div className="scam-stat">
              <span className="scam-stat-num">17</span>
              <span className="scam-stat-label">Known scam patterns</span>
            </div>
            <div className="scam-stat">
              <span className="scam-stat-num">100%</span>
              <span className="scam-stat-label">DB-grounded alerts</span>
            </div>
            <div className="scam-stat">
              <span className="scam-stat-num">0</span>
              <span className="scam-stat-label">LLM-fabricated facts</span>
            </div>
          </div>
        </div>
      </header>

      {/* ── Body ────────────────────────────────────────────────────────────── */}
      <main className="scam-body">

        {/* Input card */}
        <div className="scam-input-card">
          <h2>Describe the situation</h2>
          <p>
            Include details: who called, what they claimed, what they asked for,
            any app or link they mentioned. The more detail, the better the match.
          </p>
          <textarea
            id="scam-description-input"
            className="scam-textarea"
            value={description}
            onChange={e => setDescription(e.target.value.slice(0, MAX_CHARS))}
            placeholder="e.g. A person called from an unknown number saying they are from CBI. They said I am under 'digital arrest' and must pay ₹50,000 to avoid being physically arrested..."
            disabled={loading}
            rows={5}
            aria-label="Describe the suspicious situation"
          />
          <div className={`scam-char-counter ${charWarn ? 'warn' : ''}`}>
            {description.length} / {MAX_CHARS}
          </div>
          <div className="scam-actions">
            <div className="scam-hint">
              <span>🔒</span>
              Your description is not stored or shared.
            </div>
            <div style={{ display: 'flex', gap: '0.75rem' }}>
              {result && (
                <button
                  onClick={handleReset}
                  style={{
                    background: 'transparent',
                    border: '1px solid #2a2d35',
                    color: '#9aa0a6',
                    borderRadius: '10px',
                    padding: '0.7rem 1.2rem',
                    cursor: 'pointer',
                    fontSize: '0.85rem',
                  }}
                >
                  ↺ Reset
                </button>
              )}
              <button
                id="scam-check-button"
                className="scam-check-btn"
                onClick={handleCheck}
                disabled={!canSubmit}
              >
                {loading ? (
                  <>
                    <span className="scam-btn-spinner" />
                    Analysing…
                  </>
                ) : (
                  <>🔍 Check for Scam</>
                )}
              </button>
            </div>
          </div>
        </div>

        {/* Analysing state */}
        {loading && (
          <div className="scam-analyzing">
            <div className="scam-analyzing-pulse">🔍</div>
            <p>
              <strong>Running detection pipeline…</strong><br />
              Checking keyword signals → semantic search → database lookup
            </p>
          </div>
        )}

        {/* Error state */}
        {error && !loading && (
          <div className="scam-error">
            <span className="scam-error-icon">⚠️</span>
            <div className="scam-error-text">
              <h4>Detection failed</h4>
              <p>{error}</p>
            </div>
          </div>
        )}

        {/* Result */}
        {result && !loading && renderAlert(result.alert)}

        {/* Quick examples */}
        {!result && !loading && (
          <div className="scam-examples">
            <h3>Example situations to try</h3>
            <div className="scam-examples-grid">
              {EXAMPLE_PROMPTS.map((ex, i) => (
                <button
                  key={i}
                  id={`scam-example-${i}`}
                  className="scam-example-chip"
                  onClick={() => handleExample(ex.text)}
                  title="Click to use this example"
                >
                  <span className="scam-example-chip-icon">{ex.icon}</span>
                  {ex.text}
                </button>
              ))}
            </div>
          </div>
        )}

      </main>
    </div>
  );
}

export default ScamDetection;
