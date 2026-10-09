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
  Info
} from 'lucide-react';
import { checkScam } from '../services/api';
import './ScamDetection.css';

// ── Quick-example prompts (real representative scenarios) ───────────────────
const EXAMPLE_PROMPTS = [
  { icon: PhoneCall, text: 'A person called claiming I am under "digital arrest" by CBI' },
  { icon: Package, text: 'A courier company said my package was seized with drugs and demanded Rs 15,000' },
  { icon: Smartphone, text: 'Someone told me to scan a QR code to receive ₹5,000 on PhonePe' },
  { icon: Lock, text: 'I got a message saying my Aadhaar is suspended and KYC must be updated' },
  { icon: Scale, text: 'An "investment app" on Telegram promised 35% monthly returns on crypto trading' },
  { icon: Landmark, text: 'A caller said my bank account is frozen under PMLA and I must transfer money to a "safe account"' },
];

// ── Severity colour mapping ────────────────────────────────────────────────
function getSeverityLabel(severity) {
  const map = { CRITICAL: 'Critical Threat', HIGH: 'High Risk', MEDIUM: 'Caution / Medium' };
  return map[severity] || severity;
}

// ── Match method label ─────────────────────────────────────────────────────
function getMatchLabel(method) {
  const map = { keyword: 'Keyword Match', semantic: 'Semantic RAG Match', none: '—' };
  return map[method] || method;
}

// ── Parse recommended_action into numbered steps ──────────────────────────
function parseSteps(text) {
  if (!text) return [];
  const lines = text.split('\n').filter(l => l.trim());
  return lines.map(l => l.replace(/^\d+[\.\)]\s*/, '').trim()).filter(Boolean);
}

// ── Channel icon helper ───────────────────────────────────────────────────
function renderChannelIcon(channel) {
  const c = channel.toLowerCase();
  if (c.includes('cybercrime') || c.includes('gov')) return <Globe size={16} />;
  if (c.includes('1930') || c.includes('helpline')) return <PhoneCall size={16} />;
  if (c.includes('police') || c.includes('fir')) return <Scale size={16} />;
  return <Landmark size={16} />;
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
            <div className="scam-no-match-icon">
              <HelpCircle size={24} />
            </div>
            <div>
              <h3>Pattern Not Recognised in Database</h3>
              <p>No verified scam pattern strictly matched your description.</p>
            </div>
          </div>
          <div className="scam-no-match-body">
            {alert.safe_fallback_message}
          </div>
          <div className="scam-no-match-emergency">
            <PhoneCall size={20} className="emergency-icon" />
            <p>
              If you are in immediate danger or have already lost money,
              call <strong>1930</strong> (National Cybercrime Helpline) immediately.
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
            <div className="scam-alert-icon-box" aria-hidden="true">
              <ShieldAlert size={26} />
            </div>
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
              DB ID: {alert.db_id}
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
              <BookOpen size={16} />
              <span>Modus Operandi (How It Works)</span>
            </div>
            <p className="scam-section-content">{alert.description}</p>
          </div>

          {/* Legal Reality — highlighted box */}
          <div className="scam-section legal">
            <div className="scam-section-label">
              <Scale size={16} />
              <span>Verified Legal Reality</span>
            </div>
            <p className="scam-section-content">{alert.legal_reality}</p>
          </div>

          {/* Recommended Action */}
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
              <p className="scam-section-content">{alert.recommended_action}</p>
            )}
          </div>

          {/* Reporting Channels */}
          {alert.reporting_channels && alert.reporting_channels.length > 0 && (
            <div className="scam-section">
              <div className="scam-section-label">
                <PhoneCall size={16} />
                <span>Official Reporting Portals</span>
              </div>
              <div className="scam-channels">
                {alert.reporting_channels.map((ch, i) => (
                  <div key={i} className="scam-channel">
                    <span className="scam-channel-icon">{renderChannelIcon(ch)}</span>
                    <span>{ch}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Source reference */}
          {alert.source_ref && (
            <div className="scam-source-ref">
              <Info size={14} />
              <span>
                <strong>Official reference:</strong> {alert.source_ref}
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
            <ShieldCheck size={14} />
            <span>Module 8 · Active Detection</span>
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
          <h2>Describe the suspicious incident</h2>
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
              <Lock size={14} />
              <span>Your description is processed securely and not stored permanently.</span>
            </div>
            <div style={{ display: 'flex', gap: '0.75rem' }}>
              {result && (
                <button
                  onClick={handleReset}
                  className="btn-reset-scam"
                >
                  <RotateCcw size={14} />
                  <span>Reset</span>
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
                    <span>Analysing…</span>
                  </>
                ) : (
                  <>
                    <Search size={16} />
                    <span>Check for Scam</span>
                  </>
                )}
              </button>
            </div>
          </div>
        </div>

        {/* Analysing state */}
        {loading && (
          <div className="scam-analyzing">
            <div className="scam-analyzing-pulse">
              <Search size={24} className="animate-pulse" />
            </div>
            <p>
              <strong>Running verified detection pipeline…</strong><br />
              Checking keyword signals → semantic Qdrant matching → database verification
            </p>
          </div>
        )}

        {/* Error state */}
        {error && !loading && (
          <div className="scam-error">
            <AlertTriangle size={20} className="scam-error-icon" />
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

export default ScamDetection;
