/*
 * frontend/src/pages/FilingGuide.jsx
 * ──────────────────────────────────────────────────────────────────────────
 * LEXIS — Complaint Filing Guide (Module 9)
 *
 * WHERE TO FILE — shows the citizen the correct government authority,
 * portal, fee, and required documents for their complaint type.
 *
 * TWO ENTRY MODES:
 * ────────────────
 * 1. HANDOFF from Document Drafter (Module 6):
 *    URL: /filing-guide?doc_type=rti_application&draft_id=abc-123
 *    → doc_type and draft_id are read from URL query params.
 *    → Backend reads doc_type from the draft record (no re-entry).
 *    → A "Carried from your RTI Application draft" banner is shown.
 *
 * 2. MANUAL LOOKUP (citizen arrives independently):
 *    URL: /filing-guide
 *    → Dropdown selector lets citizen choose document type.
 *    → Backend does a direct doc_type lookup.
 *
 * WHY THE HANDOFF MATTERS (beginner explanation):
 * ────────────────────────────────────────────────
 * Without handoff: the citizen has to describe their situation again in a
 * new tool. The system re-interprets natural language — it might classify
 * "rental deposit issue" as a consumer complaint instead of a legal notice.
 *
 * With handoff: the doc_type ("legal_notice") is authoritative structured
 * data from the drafting session. No re-interpretation, no risk of error.
 * ──────────────────────────────────────────────────────────────────────────
 */

import React, { useState, useEffect } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import {
  ClipboardList,
  Landmark,
  ShoppingCart,
  Scale,
  ExternalLink,
  CheckCircle2,
  Info,
  Link2,
  AlertTriangle,
  Clock,
  FileText
} from 'lucide-react';
import {
  lookupFilingAuthority,
  lookupFilingByDraftId,
  getFilingAuthorities,
} from '../services/api';
import './FilingGuide.css';

// Human-readable labels for each doc_type
const DOC_TYPE_LABELS = {
  rti_application: 'RTI Application',
  consumer_complaint: 'Consumer Complaint',
  legal_notice: 'Legal Demand Notice',
};

function FilingGuide() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();

  // ── URL params from Document Drafter handoff ───────────────────────────────
  const draftId = searchParams.get('draft_id');
  const docTypeParam = searchParams.get('doc_type');

  // ── Component state ────────────────────────────────────────────────────────
  const [selectedDocType, setSelectedDocType] = useState(docTypeParam || '');
  const [authorityRecord, setAuthorityRecord] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState('');
  const [authorities, setAuthorities] = useState([]);   // For dropdown
  const [isHandoff, setIsHandoff] = useState(false);    // True if arrived from drafter

  // ── On mount: load available authority types + auto-lookup if handoff ──────
  useEffect(() => {
    loadAuthorities();

    if (draftId || docTypeParam) {
      setIsHandoff(!!draftId);
      handleLookup(draftId, docTypeParam);
    }
  }, []);

  const loadAuthorities = async () => {
    try {
      const result = await getFilingAuthorities();
      setAuthorities(result.data || []);
    } catch {
      // Non-critical — fallback hardcoded list shown instead
      setAuthorities([
        { doc_type: 'rti_application', doc_type_name: 'RTI Application' },
        { doc_type: 'consumer_complaint', doc_type_name: 'Consumer Complaint' },
        { doc_type: 'legal_notice', doc_type_name: 'Legal Demand Notice' },
      ]);
    }
  };

  const handleLookup = async (dId, dType) => {
    setIsLoading(true);
    setErrorMsg('');
    setAuthorityRecord(null);

    try {
      let result;
      if (dId) {
        // Handoff path: backend reads doc_type from the draft record
        result = await lookupFilingByDraftId(dId);
      } else if (dType) {
        // Direct lookup path
        result = await lookupFilingAuthority(dType);
      } else {
        setErrorMsg('Please select a document type to look up.');
        return;
      }

      if (result.data && result.data.found) {
        setAuthorityRecord(result.data);
        setSelectedDocType(result.data.doc_type);
      } else {
        setErrorMsg(
          result.data?.message ||
            'No filing authority found for this document type.'
        );
      }
    } catch (err) {
      setErrorMsg(
        err.response?.data?.detail ||
          'Failed to load filing authority. Please try again.'
      );
    } finally {
      setIsLoading(false);
    }
  };

  const handleManualLookup = (e) => {
    e.preventDefault();
    if (!selectedDocType) {
      setErrorMsg('Please select a document type.');
      return;
    }
    setIsHandoff(false);
    handleLookup(null, selectedDocType);
  };

  const handleReset = () => {
    setAuthorityRecord(null);
    setSelectedDocType('');
    setErrorMsg('');
    setIsHandoff(false);
    navigate('/filing-guide');
  };

  return (
    <div className="filing-container">
      {/* ── Header ────────────────────────────────────────────────────────── */}
      <div className="filing-header">
        <div className="filing-title-area">
          <div className="filing-icon-wrap">
            <ClipboardList className="filing-icon-svg" size={26} strokeWidth={2.2} />
          </div>
          <div>
            <h1 className="filing-title">Complaint Filing Guide</h1>
            <p className="filing-subtitle">
              Find the correct government authority, portal, and documents to file your complaint
            </p>
          </div>
        </div>
        <span className="badge-filing">DB-Verified · Official Acts</span>
      </div>

      {/* ── Handoff Banner (from Document Drafter) ────────────────────────── */}
      {isHandoff && authorityRecord && (
        <div className="handoff-banner">
          <div className="handoff-icon-wrap">
            <Link2 className="handoff-icon-svg" size={20} />
          </div>
          <div>
            <strong>Carried from your {authorityRecord.doc_type_name} draft</strong>
            <p>
              Your document type was automatically recognised from the draft you just
              completed — you don't need to re-enter anything.
            </p>
          </div>
          <button className="btn-back-drafter" onClick={() => navigate('/document-drafter')}>
            ← Back to Draft
          </button>
        </div>
      )}

      {/* ── Error message ──────────────────────────────────────────────────── */}
      {errorMsg && (
        <div className="filing-error-banner">
          <AlertTriangle size={18} />
          <span>{errorMsg}</span>
        </div>
      )}

      {/* ── Manual Lookup Form (shown when no result yet) ─────────────────── */}
      {!authorityRecord && !isLoading && (
        <div className="lookup-form-section">
          <h2>Select your document type</h2>
          <p className="lookup-hint">
            Choose the type of document you drafted. Filing authorities, portal links,
            fees, and required documents are sourced from official Indian law — no invented
            information is shown.
          </p>
          <form className="lookup-form" onSubmit={handleManualLookup}>
            <div className="doc-type-cards">
              {[
                {
                  id: 'rti_application',
                  icon: Landmark,
                  label: 'RTI Application',
                  desc: 'File with the PIO of the public authority under RTI Act 2005',
                  portal: 'rtionline.gov.in',
                },
                {
                  id: 'consumer_complaint',
                  icon: ShoppingCart,
                  label: 'Consumer Complaint',
                  desc: 'File with the Consumer Commission (District / State / National)',
                  portal: 'edaakhil.nic.in',
                },
                {
                  id: 'legal_notice',
                  icon: Scale,
                  label: 'Legal Demand Notice',
                  desc: 'Serve directly to the opposite party (registered post / RPAD)',
                  portal: 'No portal — direct service',
                },
              ].map((item) => {
                const IconComponent = item.icon;
                return (
                  <div
                    key={item.id}
                    id={`doc-type-card-${item.id}`}
                    className={`doc-type-card ${selectedDocType === item.id ? 'selected' : ''}`}
                    onClick={() => setSelectedDocType(item.id)}
                    role="button"
                    tabIndex={0}
                    onKeyDown={(e) => e.key === 'Enter' && setSelectedDocType(item.id)}
                    aria-pressed={selectedDocType === item.id}
                  >
                    <div className="doc-type-card-icon">
                      <IconComponent size={26} strokeWidth={2} />
                    </div>
                    <h3>{item.label}</h3>
                    <p>{item.desc}</p>
                    <div className="doc-type-portal-hint">
                      <ExternalLink size={13} />
                      <span>{item.portal}</span>
                    </div>
                  </div>
                );
              })}
            </div>
            <button
              type="submit"
              id="btn-lookup-filing"
              className="btn-lookup"
              disabled={!selectedDocType}
            >
              Find Filing Authority →
            </button>
          </form>
        </div>
      )}

      {/* ── Loading State ─────────────────────────────────────────────────── */}
      {isLoading && (
        <div className="filing-loading">
          <div className="loading-spinner" />
          <p>Looking up verified filing authority…</p>
        </div>
      )}

      {/* ── Authority Result Card ─────────────────────────────────────────── */}
      {authorityRecord && !isLoading && (
        <div className="authority-result-section">
          <div className="result-top-bar">
            <button className="btn-reset" onClick={handleReset}>
              ← Look up another
            </button>
            <div className="result-doc-type-badge">
              {DOC_TYPE_LABELS[authorityRecord.doc_type] || authorityRecord.doc_type_name}
            </div>
          </div>

          {/* Main authority card */}
          <div className="authority-card">
            <div className="authority-card-header">
              <div>
                <h2 className="authority-card-title">{authorityRecord.authority_name}</h2>
                <p className="authority-card-short">{authorityRecord.authority_short}</p>
              </div>
              {authorityRecord.verified && (
                <span className="verified-badge">
                  <CheckCircle2 size={13} />
                  <span>Verified Authority</span>
                </span>
              )}
            </div>

            <p className="authority-description">{authorityRecord.description}</p>

            {/* Portal link */}
            {authorityRecord.portal_url && (
              <div className="portal-section">
                <div className="section-label">Official Portal</div>
                <a
                  href={authorityRecord.portal_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="portal-link-btn"
                  id="btn-visit-portal"
                >
                  <span>{authorityRecord.portal_name}</span>
                  <ExternalLink size={15} />
                </a>
                {authorityRecord.portal_scope && (
                  <p className="portal-scope-note">{authorityRecord.portal_scope}</p>
                )}
              </div>
            )}

            {/* Filing tiers */}
            {authorityRecord.filing_tiers && authorityRecord.filing_tiers.length > 0 && (
              <div className="filing-tiers-section">
                <div className="section-label">Filing Hierarchy &amp; Tiers</div>
                <div className="tiers-list">
                  {authorityRecord.filing_tiers.map((tier, idx) => (
                    <div key={idx} className="tier-card">
                      <div className="tier-step">{idx + 1}</div>
                      <div className="tier-content">
                        <strong>{tier.name || tier.tier}</strong>
                        <p>{tier.description}</p>
                        {tier.deadline_to_respond && (
                          <span className="tier-deadline">
                            <Clock size={13} style={{ display: 'inline', verticalAlign: 'middle', marginRight: '4px' }} />
                            Response: {tier.deadline_to_respond}
                          </span>
                        )}
                        {tier.jurisdiction && (
                          <span className="tier-jurisdiction">
                            <Scale size={13} style={{ display: 'inline', verticalAlign: 'middle', marginRight: '4px' }} />
                            Jurisdiction: {tier.jurisdiction}
                          </span>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Fee information */}
            {authorityRecord.fee && (
              <div className="fee-section">
                <div className="section-label">Statutory Filing Fee</div>
                <div className="fee-grid">
                  {authorityRecord.fee.amount_central && (
                    <div className="fee-item">
                      <span className="fee-label">Central Govt fee:</span>
                      <span className="fee-value">{authorityRecord.fee.amount_central}</span>
                    </div>
                  )}
                  {authorityRecord.fee.structure && (
                    <div className="fee-item">
                      <span className="fee-label">Fee structure:</span>
                      <span className="fee-value">{authorityRecord.fee.structure}</span>
                    </div>
                  )}
                  {authorityRecord.fee.fee_exemption && (
                    <div className="fee-item fee-exemption">
                      <span className="fee-label">Exemption:</span>
                      <span className="fee-value">{authorityRecord.fee.fee_exemption}</span>
                    </div>
                  )}
                  {authorityRecord.fee.state_fees && (
                    <div className="fee-item fee-note">
                      <span className="fee-label">State fees:</span>
                      <span className="fee-value">
                        {authorityRecord.fee.state_fees === 'needs_verification'
                          ? 'Varies by state — verify with your state authority'
                          : authorityRecord.fee.state_fees}
                      </span>
                    </div>
                  )}
                  {authorityRecord.fee.court_filing_fee && (
                    <div className="fee-item fee-note">
                      <span className="fee-label">Court filing fee:</span>
                      <span className="fee-value">
                        {authorityRecord.fee.court_filing_fee === 'needs_verification'
                          ? 'State-specific — verify with your local court or lawyer'
                          : authorityRecord.fee.court_filing_fee}
                      </span>
                    </div>
                  )}
                  {authorityRecord.fee.source && (
                    <div className="fee-source">Source: {authorityRecord.fee.source}</div>
                  )}
                </div>

                {/* Fee schedule table for consumer complaints */}
                {authorityRecord.fee.fee_schedule && authorityRecord.fee.fee_schedule.length > 0 && (
                  <div className="fee-schedule">
                    <div className="fee-schedule-title">Fee schedule (Consumer Protection Rules 2020):</div>
                    <table className="fee-table">
                      <thead>
                        <tr>
                          <th>Claim Amount</th>
                          <th>Fee</th>
                        </tr>
                      </thead>
                      <tbody>
                        {authorityRecord.fee.fee_schedule.map((row, i) => (
                          <tr key={i}>
                            <td>Up to {row.claim_up_to}</td>
                            <td>{row.fee}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            )}

            {/* Required documents checklist */}
            {authorityRecord.required_documents && authorityRecord.required_documents.length > 0 && (
              <div className="documents-section">
                <div className="section-label">Required Documents Checklist</div>
                <ul className="documents-checklist">
                  {authorityRecord.required_documents.map((doc, idx) => (
                    <li key={idx} className="document-item">
                      <CheckCircle2 size={16} className="check-icon-svg" />
                      <span>{doc}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* Important notes */}
            {authorityRecord.important_notes && authorityRecord.important_notes.length > 0 && (
              <div className="notes-section">
                <div className="section-label">Important Legal Notes</div>
                <ul className="notes-list">
                  {authorityRecord.important_notes.map((note, idx) => (
                    <li key={idx}>
                      <Info size={15} className="note-bullet-icon" />
                      <span>{note}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* Response timeline */}
            {authorityRecord.response_timeline && (
              <div className="timeline-section">
                <div className="section-label">⏱ Response Timeline</div>
                <p>{authorityRecord.response_timeline}</p>
              </div>
            )}

            {/* Legal basis + source */}
            <div className="legal-footer">
              {authorityRecord.legal_basis && (
                <div className="legal-basis">
                  <span className="legal-label">Legal basis:</span> {authorityRecord.legal_basis}
                </div>
              )}
              {authorityRecord.source_ref && (
                <div className="source-ref">
                  <span className="legal-label">Source:</span> {authorityRecord.source_ref}
                </div>
              )}
              {authorityRecord.last_verified && (
                <div className="last-verified">
                  Data last verified: {authorityRecord.last_verified}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default FilingGuide;
