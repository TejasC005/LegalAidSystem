/*
 * frontend/src/pages/FilingGuide.jsx
 * ──────────────────────────────────────────────────────────────────────────
 * LEXIS — Complaint Filing Guide Specialist Agent (Module 9 Enhanced)
 *
 * An autonomous specialist agent helping Indian citizens understand WHERE
 * and HOW to file complaints, legal notices, and statutory petitions.
 *
 * ARCHITECTURAL PATTERN:
 *   - Conversational Natural Language Understanding
 *   - Grounded in verified Indian statutory databases (RTI Act 2005, CPA 2019, etc.)
 *   - Interactive multi-turn dialogue with follow-up Q&A
 *   - Pecuniary jurisdiction calculation (District vs State vs National)
 *   - Interactive document readiness checklists and step-by-step procedures
 *   - Seamless handoff from Document Drafter (Module 6)
 *   - Zero fabrication: only verified .gov.in / .nic.in portals
 * ──────────────────────────────────────────────────────────────────────────
 */

import React, { useState, useEffect, useRef } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import {
  getFilingGuide,
  lookupFilingAuthority,
  lookupFilingByDraftId,
} from '../services/api';
import './FilingGuide.css';

// Markdown and inline token formatting helper for citizen readability
function formatInlineTokens(line) {
  const parts = [];
  const regex = /(\*\*.*?\*\*|\[.*?\]\(.*?\))/g;
  let lastIdx = 0;
  let match;

  while ((match = regex.exec(line)) !== null) {
    if (match.index > lastIdx) {
      parts.push(line.substring(lastIdx, match.index));
    }
    const token = match[0];
    if (token.startsWith('**') && token.endsWith('**')) {
      parts.push(<strong key={match.index}>{token.slice(2, -2)}</strong>);
    } else if (token.startsWith('[') && token.includes('](') && token.endsWith(')')) {
      const closingBracket = token.indexOf('](');
      const label = token.slice(1, closingBracket);
      const url = token.slice(closingBracket + 2, -1);
      parts.push(
        <a key={match.index} href={url} target="_blank" rel="noopener noreferrer" className="inline-portal-link">
          {label}
        </a>
      );
    }
    lastIdx = regex.lastIndex;
  }

  if (lastIdx < line.length) {
    parts.push(line.substring(lastIdx));
  }

  return parts.length > 0 ? parts : line;
}

function renderFormattedText(text, hasGuide) {
  if (!text) return null;
  if (hasGuide && text.startsWith('### 📋 Filing Guide:')) {
    return (
      <div className="guide-intro-banner">
        <span>📋</span> Procedural guidance, official submission portal, and document checklist:
      </div>
    );
  }

  const lines = text.split('\n');
  return (
    <div className="formatted-message-lines">
      {lines.map((line, lIdx) => {
        if (!line.trim()) {
          return <div key={lIdx} className="line-spacer" />;
        }
        if (line.startsWith('### ')) {
          return <h3 key={lIdx} className="formatted-h3">{line.replace('### ', '')}</h3>;
        }
        if (line.startsWith('## ')) {
          return <h2 key={lIdx} className="formatted-h2">{line.replace('## ', '')}</h2>;
        }
        return (
          <p key={lIdx} className="formatted-line">
            {formatInlineTokens(line)}
          </p>
        );
      })}
    </div>
  );
}

// Quick scenario prompts for common citizen filing needs
const SCENARIO_PROMPTS = [
  {
    icon: '🏛️',
    label: 'RTI for Road Work',
    query: 'How do I file an RTI application for delayed road repair in my municipal ward?',
  },
  {
    icon: '🛒',
    label: 'Defective Product Refund',
    query: 'I bought a defective laptop for ₹45,000 online and the seller refuses to refund. How do I file a consumer complaint?',
  },
  {
    icon: '⚖️',
    label: 'Unpaid Rental Deposit',
    query: 'My landlord refuses to return my ₹60,000 security deposit after vacating. How do I send a legal demand notice?',
  },
  {
    icon: '🚗',
    label: 'High-Value Consumer Dispute',
    query: 'I bought a car with manufacturing defects worth ₹65 Lakh in Pune, Maharashtra. Which consumer court has jurisdiction?',
  },
];

function FilingGuide() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();

  // URL query params for handoff from Document Drafter
  const draftId = searchParams.get('draft_id');
  const docTypeParam = searchParams.get('doc_type');

  // Chat and interaction state
  const [messages, setMessages] = useState([]);
  const [inputText, setInputText] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState('');
  const [activeGuide, setActiveGuide] = useState(null);
  const [isHandoff, setIsHandoff] = useState(false);
  const [checkedDocs, setCheckedDocs] = useState({});
  const [selectedDocType, setSelectedDocType] = useState(docTypeParam || '');

  const chatEndRef = useRef(null);

  const scrollToBottom = () => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, isLoading, activeGuide]);

  // On mount: handle handoff if arriving from Document Drafter
  useEffect(() => {
    if (draftId || docTypeParam) {
      setIsHandoff(!!draftId);
      handleInitialHandoff(draftId, docTypeParam);
    }
  }, [draftId, docTypeParam]);

  const handleInitialHandoff = async (dId, dType) => {
    setIsLoading(true);
    setErrorMsg('');
    try {
      const q = dType
        ? `I have completed drafting my ${dType.replace('_', ' ')}. Please provide the complete filing guide and procedure.`
        : 'Please provide the filing guide for my completed draft.';

      const res = await getFilingGuide(q, [], dId, dType);
      const data = res.data;

      const userGreeting = {
        sender: 'user',
        text: dId
          ? `Carried from Document Drafter (Draft: ${dType || 'Legal Document'})`
          : `Looking up filing guide for ${dType ? dType.replace('_', ' ') : 'Legal Document'}`,
        timestamp: new Date(),
      };

      const agentReply = {
        sender: 'agent',
        text: data.reply_text,
        guide: data.guide,
        intent: data.intent,
        verified: data.verified,
        sources: data.sources || [],
        disclaimer: data.disclaimer,
        timestamp: new Date(),
      };

      setMessages([userGreeting, agentReply]);
      if (data.guide) {
        setActiveGuide(data.guide);
      }
    } catch (err) {
      console.error('Failed to load filing guide handoff:', err);
      setErrorMsg(err.response?.data?.detail || 'Failed to load filing guide for this draft.');
    } finally {
      setIsLoading(false);
    }
  };

  // Main message send handler
  const handleSend = async (queryText) => {
    const q = queryText || inputText;
    if (!q || !q.trim() || isLoading) return;

    const trimmed = q.trim();
    const userMsg = { sender: 'user', text: trimmed, timestamp: new Date() };
    setMessages((prev) => [...prev, userMsg]);
    setInputText('');
    setIsLoading(true);
    setErrorMsg('');

    // Prepare conversation history context
    const historyPayload = messages.map((m) => ({
      sender: m.sender,
      text: m.text,
      role: m.sender === 'user' ? 'user' : 'assistant',
      content: m.text,
    }));

    try {
      const res = await getFilingGuide(
        trimmed,
        historyPayload,
        draftId,
        activeGuide ? activeGuide.doc_type : docTypeParam
      );
      const data = res.data;

      const agentMsg = {
        sender: 'agent',
        text: data.reply_text,
        guide: data.guide,
        intent: data.intent,
        verified: data.verified,
        sources: data.sources || [],
        disclaimer: data.disclaimer,
        timestamp: new Date(),
      };

      setMessages((prev) => [...prev, agentMsg]);
      if (data.guide) {
        setActiveGuide(data.guide);
      }
    } catch (err) {
      console.error('Failed to execute filing query:', err);
      const detail = err.response?.data?.detail || 'Failed to connect to Filing Guide Agent.';
      setErrorMsg(detail);
      setMessages((prev) => [
        ...prev,
        {
          sender: 'agent',
          text: `⚠️ Error: ${detail}`,
          status: 'error',
          timestamp: new Date(),
        },
      ]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleDocumentCheck = (msgIndex, dIdx) => {
    const key = `${msgIndex}-${dIdx}`;
    setCheckedDocs((prev) => ({
      ...prev,
      [key]: !prev[key],
    }));
  };

  const handleQuickCategorySelect = (docType) => {
    setSelectedDocType(docType);
    let q = '';
    if (docType === 'rti_application') {
      q = 'How do I file an RTI application under the Right to Information Act 2005?';
    } else if (docType === 'consumer_complaint') {
      q = 'How do I file a consumer complaint for deficiency in service or defective goods?';
    } else if (docType === 'legal_notice') {
      q = 'How do I serve a legal demand notice for tenant deposit or contractual default?';
    }
    handleSend(q);
  };

  const handleReset = () => {
    setMessages([]);
    setActiveGuide(null);
    setInputText('');
    setErrorMsg('');
    setIsHandoff(false);
    setCheckedDocs({});
    setSelectedDocType('');
    navigate('/filing-guide');
  };

  return (
    <div className="filing-page-container">
      {/* ── Header Banner ─────────────────────────────────────────────────── */}
      <div className="filing-header-banner">
        <div className="filing-header-left">
          <span className="filing-header-badge-icon">📋</span>
          <div>
            <h1 className="filing-header-title">Filing Guide Agent</h1>
            <p className="filing-header-subtitle">
              Autonomous procedural navigation for Indian courts, consumer commissions, and RTI authorities
            </p>
          </div>
        </div>
        <div className="filing-header-tags">
          <span className="badge-verified-authority">🏛️ Verified Portals Only</span>
          <span className="badge-no-hallucination">0 Fabrication</span>
        </div>
      </div>

      {/* ── Handoff Banner (if carried from Document Drafter) ─────────────── */}
      {isHandoff && (
        <div className="drafter-handoff-banner">
          <div className="handoff-content">
            <span className="handoff-emoji">🔗</span>
            <div>
              <strong>Carried from your Document Drafter session</strong>
              <p>Your document context has been linked automatically. You do not need to re-enter your dispute details.</p>
            </div>
          </div>
          <button
            className="btn-back-to-draft"
            onClick={() => navigate('/document-drafter')}
          >
            ← Return to Drafter
          </button>
        </div>
      )}

      {/* ── Error Banner ──────────────────────────────────────────────────── */}
      {errorMsg && <div className="filing-alert-banner">⚠️ {errorMsg}</div>}

      {/* ── Empty State / Scenario Prompt Chips ───────────────────────────── */}
      {messages.length === 0 && !isLoading && (
        <div className="filing-empty-state">
          <div className="empty-state-card">
            <span className="empty-state-icon">⚖️</span>
            <h2>Where and how do you need to file?</h2>
            <p>
              Ask any procedural question in natural language. The Filing Guide Agent will identify the
              correct statutory authority, check pecuniary jurisdiction, and give you step-by-step submission steps.
            </p>

            <div className="scenario-chips-grid">
              {SCENARIO_PROMPTS.map((item, idx) => (
                <button
                  key={idx}
                  className="scenario-chip-btn"
                  onClick={() => handleSend(item.query)}
                  disabled={isLoading}
                >
                  <span className="chip-icon">{item.icon}</span>
                  <div className="chip-text">
                    <strong>{item.label}</strong>
                    <span>{item.query}</span>
                  </div>
                </button>
              ))}
            </div>

            <div className="direct-categories-wrapper">
              <span className="categories-label">Or select a standard filing category:</span>
              <div className="categories-buttons">
                <button
                  className="category-pill-btn"
                  onClick={() => handleQuickCategorySelect('rti_application')}
                >
                  🏛️ RTI Application
                </button>
                <button
                  className="category-pill-btn"
                  onClick={() => handleQuickCategorySelect('consumer_complaint')}
                >
                  🛒 Consumer Complaint
                </button>
                <button
                  className="category-pill-btn"
                  onClick={() => handleQuickCategorySelect('legal_notice')}
                >
                  ⚖️ Legal Demand Notice
                </button>
              </div>

              <div className="categories-dropdown-container">
                <select
                  id="select-doc-type"
                  className="select-doc-type"
                  value={selectedDocType}
                  onChange={(e) => {
                    const val = e.target.value;
                    if (val) handleQuickCategorySelect(val);
                  }}
                >
                  <option value="">-- Or choose from document dropdown --</option>
                  <option value="rti_application">🏛️ RTI Application (Right to Information Act 2005)</option>
                  <option value="consumer_complaint">🛒 Consumer Complaint (Consumer Protection Act 2019)</option>
                  <option value="legal_notice">⚖️ Legal Demand Notice (Contract / Tenant / Cheque Bounce)</option>
                </select>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ── Chat Messages Thread ─────────────────────────────────────────── */}
      {messages.length > 0 && (
        <div className="filing-chat-thread">
          <div className="thread-actions-bar">
            <button className="btn-new-filing-query" onClick={handleReset}>
              ↺ Start New Filing Query
            </button>
          </div>

          {messages.map((msg, index) => (
            <div key={index} className={`chat-message-row ${msg.sender}`}>
              <div className="message-sender-tag">
                {msg.sender === 'user' ? 'You (Citizen)' : 'LEXIS Filing Guide Agent'}
              </div>

              <div className="chat-bubble">
                <div className="bubble-text">{renderFormattedText(msg.text, !!msg.guide)}</div>

                {/* If this message contains a structured guide, render cards only on initial guide or modification */}
                {msg.guide && (msg.intent === 'new_guide' || msg.intent === 'modify_guide' || !msg.intent) && (
                  <div className="structured-guide-container">
                    {/* 1. Authority & Overview Card */}
                    <div className="guide-card authority-overview-card">
                      <div className="guide-card-header">
                        <div>
                          <span className="card-badge">📌 Competent Authority</span>
                          <h3 className="authority-heading">{msg.guide.authority_name}</h3>
                          <span className="authority-short-tag">{msg.guide.authority_short}</span>
                        </div>
                        {msg.guide.verified && (
                          <span className="verified-pill">✅ Verified Authority</span>
                        )}
                      </div>

                      <p className="guide-description">{msg.guide.description}</p>

                      {/* Pecuniary Tier Badge (if calculated) */}
                      {msg.guide.calculated_tier && (
                        <div className="pecuniary-tier-callout">
                          <span className="tier-tag">⚖️ {msg.guide.calculated_tier.short_name}</span>
                          <p>
                            <strong>Jurisdiction:</strong> {msg.guide.calculated_tier.jurisdiction_limit}
                          </p>
                          <small>{msg.guide.calculated_tier.where_to_file}</small>
                        </div>
                      )}

                      {/* Filing Hierarchy & Appeal Tiers */}
                      {msg.guide.filing_tiers && msg.guide.filing_tiers.length > 0 && !msg.guide.calculated_tier && (
                        <div className="filing-tiers-overview-box">
                          <span className="tier-overview-title">⚖️ Statutory Appeal & Jurisdictional Tiers:</span>
                          <div className="tiers-grid">
                            {msg.guide.filing_tiers.map((t, tIdx) => (
                              <div key={tIdx} className="tier-mini-item">
                                <span className="tier-mini-name">{t.name || `Tier ${t.tier}`}</span>
                                {t.jurisdiction && <span className="tier-mini-limit">{t.jurisdiction}</span>}
                                {t.deadline_to_respond && <span className="tier-mini-deadline">⏱ {t.deadline_to_respond}</span>}
                                <p className="tier-mini-desc">{t.description}</p>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* Official Portal Action */}
                      {msg.guide.portal_url && (
                        <div className="portal-action-box">
                          <div>
                            <span className="portal-title">Official Government Portal</span>
                            <span className="portal-scope">{msg.guide.portal_scope || 'Central & State filing system'}</span>
                          </div>
                          <a
                            href={msg.guide.portal_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="btn-portal-launch"
                          >
                            Open {msg.guide.portal_name} ↗
                          </a>
                        </div>
                      )}
                    </div>

                    {/* 2. Eligibility & Prerequisites */}
                    {msg.guide.eligibility_prerequisites && msg.guide.eligibility_prerequisites.length > 0 && (
                      <div className="guide-card eligibility-card">
                        <h4 className="card-subheading">📋 Eligibility & Prerequisites</h4>
                        <ul className="bullet-list">
                          {msg.guide.eligibility_prerequisites.map((p, pIdx) => (
                            <li key={pIdx}>{p}</li>
                          ))}
                        </ul>
                      </div>
                    )}

                    {/* 3. Step-by-Step Filing Procedure */}
                    {msg.guide.step_by_step_procedure && msg.guide.step_by_step_procedure.length > 0 && (
                      <div className="guide-card procedure-card">
                        <h4 className="card-subheading">🔢 Step-by-Step Filing Procedure</h4>
                        <div className="procedure-timeline">
                          {msg.guide.step_by_step_procedure.map((step, sIdx) => (
                            <div key={sIdx} className="timeline-step-item">
                              <div className="step-number-circle">{step.step_number || sIdx + 1}</div>
                              <div className="step-body">
                                <div className="step-top-line">
                                  <strong>{step.title}</strong>
                                  {step.timeline && <span className="step-timeline-tag">⏱ {step.timeline}</span>}
                                </div>
                                <p>{step.description}</p>
                                {step.action_url && (
                                  <a
                                    href={step.action_url}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="step-action-link"
                                  >
                                    Visit Portal ↗
                                  </a>
                                )}
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* 4. Required Documents Checklist (Interactive) */}
                    {msg.guide.required_documents && msg.guide.required_documents.length > 0 && (
                      <div className="guide-card checklist-card">
                        <div className="checklist-header">
                          <h4 className="card-subheading">📁 Required Documents Checklist</h4>
                          <span className="checklist-hint">Check off items as you gather them</span>
                        </div>
                        <div className="interactive-checklist">
                          {msg.guide.required_documents.map((doc, dIdx) => (
                            <label
                              key={dIdx}
                              className={`checklist-item-label ${checkedDocs[`${index}-${dIdx}`] ? 'checked' : ''}`}
                            >
                              <input
                                type="checkbox"
                                checked={!!checkedDocs[`${index}-${dIdx}`]}
                                onChange={() => handleDocumentCheck(index, dIdx)}
                              />
                              <span className="custom-checkbox-box">{checkedDocs[`${index}-${dIdx}`] ? '✓' : ''}</span>
                              <span className="checklist-text">{doc}</span>
                            </label>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* 5. Statutory Fees & Timelines Grid */}
                    <div className="guide-grid-two-col">
                      {/* Fees */}
                      {msg.guide.fee && (
                        <div className="guide-card fee-card">
                          <h4 className="card-subheading">💰 Statutory Fees</h4>
                          <div className="fee-details-list">
                            {msg.guide.fee.amount_central && (
                              <div className="fee-row">
                                <span>Central Fee:</span>
                                <strong>{msg.guide.fee.amount_central}</strong>
                              </div>
                            )}
                            {msg.guide.fee.structure && (
                              <div className="fee-row">
                                <span>Structure:</span>
                                <span>{msg.guide.fee.structure}</span>
                              </div>
                            )}
                            {msg.guide.fee.fee_exemption && (
                              <div className="fee-row fee-exemption">
                                <span>Exemption:</span>
                                <span>{msg.guide.fee.fee_exemption}</span>
                              </div>
                            )}
                            {msg.guide.fee.state_fees && (
                              <div className="fee-row fee-warning">
                                <span>State Fees:</span>
                                <span>
                                  {msg.guide.fee.state_fees === 'needs_verification'
                                    ? '⚠️ Varies by state — verify with state authority'
                                    : msg.guide.fee.state_fees}
                                </span>
                              </div>
                            )}
                          </div>

                          {/* Fee schedule table for consumer commissions */}
                          {msg.guide.fee.fee_schedule && msg.guide.fee.fee_schedule.length > 0 && (
                            <div className="fee-schedule-table-box">
                              <table className="mini-fee-table">
                                <thead>
                                  <tr>
                                    <th>Claim Value</th>
                                    <th>Fee</th>
                                  </tr>
                                </thead>
                                <tbody>
                                  {msg.guide.fee.fee_schedule.map((row, rIdx) => (
                                    <tr key={rIdx}>
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

                      {/* Deadlines & Timelines */}
                      <div className="guide-card timeline-card">
                        <h4 className="card-subheading">⏱ Statutory Timelines</h4>
                        {msg.guide.response_timeline && (
                          <div className="timeline-highlight-box">
                            <strong>Official Response Period:</strong>
                            <p>{msg.guide.response_timeline}</p>
                          </div>
                        )}
                        {msg.guide.legal_basis && (
                          <div className="legal-basis-box">
                            <strong>Governing Statute:</strong>
                            <p>{msg.guide.legal_basis}</p>
                          </div>
                        )}
                      </div>
                    </div>

                    {/* 6. Common Mistakes to Avoid */}
                    {msg.guide.common_mistakes && msg.guide.common_mistakes.length > 0 && (
                      <div className="guide-card mistakes-card">
                        <h4 className="card-subheading">⚠️ Common Mistakes to Avoid</h4>
                        <ul className="mistakes-list">
                          {msg.guide.common_mistakes.map((m, mIdx) => (
                            <li key={mIdx}>{m}</li>
                          ))}
                        </ul>
                      </div>
                    )}

                    {/* 7. Legal Disclaimer Footer */}
                    <div className="guide-disclaimer-footer">
                      <p>{msg.disclaimer || 'Disclaimer: LEXIS provides verified procedural guidance and not legal advice.'}</p>
                      {msg.guide.source_ref && (
                        <span className="source-citation-line">
                          Source: {msg.guide.source_ref} {msg.guide.last_verified ? `(Verified ${msg.guide.last_verified})` : ''}
                        </span>
                      )}
                    </div>
                  </div>
                )}
              </div>
            </div>
          ))}

          {/* Loading indicator */}
          {isLoading && (
            <div className="chat-message-row agent">
              <div className="message-sender-tag">LEXIS Filing Guide Agent</div>
              <div className="chat-bubble loading-bubble">
                <div className="typing-dots">
                  <span></span>
                  <span></span>
                  <span></span>
                </div>
                <span className="loading-text">Analyzing filing requirements and jurisdiction rules…</span>
              </div>
            </div>
          )}

          <div ref={chatEndRef} />
        </div>
      )}

      {/* ── Conversational Input Box (Always accessible) ──────────────────── */}
      <div className="filing-input-container">
        <form
          className="filing-input-form"
          onSubmit={(e) => {
            e.preventDefault();
            handleSend();
          }}
        >
          <input
            type="text"
            className="filing-text-input"
            placeholder={
              messages.length === 0
                ? 'Describe your dispute or where you need to file (e.g. consumer complaint for ₹40,000 in Mumbai)…'
                : 'Ask a follow-up question (e.g. Do I need a lawyer? What is the deadline? Can I pay online?)…'
            }
            value={inputText}
            onChange={(e) => setInputText(e.target.value)}
            disabled={isLoading}
          />
          <button
            type="submit"
            className="btn-send-filing-query"
            disabled={!inputText.trim() || isLoading}
          >
            {isLoading ? 'Processing…' : 'Send →'}
          </button>
        </form>
      </div>
    </div>
  );
}

export default FilingGuide;
