/*
 * frontend/src/pages/RightsExplainer.jsx
 * ──────────────────────────────────────────────────────────────────────────
 * LEXIS — Rights Explainer Agent Page (Module 5)
 *
 * Interactive chat interface for asking legal rights queries.
 * Communicates with backend POST /api/v1/query, rendering responses
 * alongside verified Qdrant knowledge base source citations.
 * ──────────────────────────────────────────────────────────────────────────
 */

import React, { useState, useRef, useEffect } from 'react';
import {
  Scale,
  Lightbulb,
  BookOpen,
  ShieldCheck,
  Search,
  Send,
  ExternalLink
} from 'lucide-react';
import { sendQuery } from '../services/api';
import './RightsExplainer.css';

const SAMPLE_QUESTIONS = [
  "Can my landlord deduct money from my security deposit without bills?",
  "What are the rules and timelines for POSH workplace harassment reporting?",
  "How long can a PIO take to answer an RTI application?",
  "What rights do I have if I receive a defective product from e-commerce?",
];

/**
 * Inline text parser:
 * - Converts markdown links [label](url) to <a> tags
 * - Converts bold **text** to <strong> tags (removing asterisks)
 * - Converts italics _text_ to <em> tags
 * - Strips any stray asterisks (*)
 */
function renderInlineText(rawText) {
  if (!rawText) return null;

  // Match markdown links [label](url)
  const linkRegex = /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g;
  const parts = [];
  let lastIndex = 0;
  let match;

  while ((match = linkRegex.exec(rawText)) !== null) {
    if (match.index > lastIndex) {
      parts.push({ type: 'text', val: rawText.substring(lastIndex, match.index) });
    }
    parts.push({ type: 'link', label: match[1], url: match[2] });
    lastIndex = linkRegex.lastIndex;
  }
  if (lastIndex < rawText.length) {
    parts.push({ type: 'text', val: rawText.substring(lastIndex) });
  }

  return parts.map((part, pIdx) => {
    if (part.type === 'link') {
      return (
        <a
          key={pIdx}
          href={part.url}
          target="_blank"
          rel="noopener noreferrer"
          className="formatted-link"
        >
          <span>{part.label}</span>
          <ExternalLink size={12} className="inline-link-icon" />
        </a>
      );
    }

    // Split on bold boundaries **text**
    const boldTokens = part.val.split(/\*\*/);
    return (
      <span key={pIdx}>
        {boldTokens.map((token, bIdx) => {
          // Odd indices are bold
          if (bIdx % 2 === 1) {
            const cleanBold = token.replace(/\*/g, '');
            return (
              <strong key={bIdx} className="formatted-strong">
                {cleanBold}
              </strong>
            );
          }
          // Even indices are normal text: strip stray asterisks
          const cleanText = token.replace(/\*/g, '');
          return cleanText;
        })}
      </span>
    );
  });
}

/**
 * Rich message formatter:
 * - Parses headers (###, ##, #) into styled section headings without hashes
 * - Parses lists (- item, * item) into clean styled bullet items without dashes/asterisks
 * - Formats legal source citations ([Source: ...]) into clean callout pills
 * - Formats paragraphs cleanly with proper spacing and typography
 */
function FormattedMessage({ text }) {
  if (!text) return null;

  const lines = text.split('\n');
  const elements = [];
  let currentList = [];

  const flushList = () => {
    if (currentList.length > 0) {
      elements.push(
        <ul key={`ul-${elements.length}`} className="formatted-list">
          {currentList.map((item, idx) => (
            <li key={idx} className="formatted-list-item">
              <span className="formatted-bullet-dot">•</span>
              <span className="formatted-item-content">{renderInlineText(item)}</span>
            </li>
          ))}
        </ul>
      );
      currentList = [];
    }
  };

  for (let i = 0; i < lines.length; i++) {
    const rawLine = lines[i];
    const trimmed = rawLine.trim();

    if (!trimmed) {
      flushList();
      continue;
    }

    // Check for source citation line: [Source: ...]
    const sourceMatch = trimmed.match(/^\[Source:\s*(.+?)\]$/i);
    if (sourceMatch) {
      flushList();
      elements.push(
        <div key={`source-${i}`} className="formatted-source-callout">
          <ShieldCheck size={14} className="source-callout-icon" />
          <span><strong className="formatted-strong">Legal Source:</strong> {sourceMatch[1]}</span>
        </div>
      );
      continue;
    }

    // Check for markdown headers (###, ##, #)
    const headerMatch = trimmed.match(/^(#{1,4})\s+(.+)$/);
    if (headerMatch) {
      flushList();
      const headerText = headerMatch[2].replace(/\*/g, '').trim();
      elements.push(
        <div key={`h-${i}`} className="formatted-heading">
          {renderInlineText(headerText)}
        </div>
      );
      continue;
    }

    // Check for bullet lists (starts with - or * or •)
    const listMatch = trimmed.match(/^[-*•]\s+(.+)$/);
    if (listMatch) {
      // Strip leading dash or asterisk and add to current list
      currentList.push(listMatch[1].trim());
      continue;
    }

    // Normal paragraph
    flushList();
    elements.push(
      <p key={`p-${i}`} className="formatted-paragraph">
        {renderInlineText(trimmed)}
      </p>
    );
  }

  flushList();

  return <div className="formatted-content">{elements}</div>;
}

function RightsExplainer() {
  const [messages, setMessages] = useState([]);
  const [inputText, setInputText] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState('');

  const chatEndRef = useRef(null);

  const scrollToBottom = () => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, isLoading]);

  const handleSend = async (queryText) => {
    const q = queryText || inputText;
    if (!q || !q.trim() || isLoading) return;

    const userMsg = { sender: 'user', text: q.trim(), timestamp: new Date() };
    setMessages((prev) => [...prev, userMsg]);
    setInputText('');
    setIsLoading(true);
    setErrorMsg('');

    try {
      const response = await sendQuery(q.trim());
      const data = response.data;
      console.log('LEXIS API RESPONSE:', data);

      // Extract metadata citations & verification status from response root or agents
      let citations = Array.isArray(data.citations) ? [...data.citations] : [];
      let verificationStatus = data.verification_status || 'unverified';

      const agentRecords = data.agents || data.scratchpad || [];

      agentRecords.forEach((record) => {
        if (record.metadata) {
          if (record.metadata.citations && Array.isArray(record.metadata.citations)) {
            citations = [...citations, ...record.metadata.citations];
          }

          // Use verification status from RightsExplainerAgent or rights intent
          if (
            (record.metadata.agent === 'RightsExplainerAgent' || record.intent === 'rights') &&
            record.metadata.verification_status
          ) {
            verificationStatus = record.metadata.verification_status;
          }
        }
      });

      const agentMsg = {
        sender: 'agent',
        text: data.final_response,
        citations: Array.from(new Set(citations)),
        verificationStatus,
        status: data.status,
        timestamp: new Date(),
      };

      setMessages((prev) => [...prev, agentMsg]);
    } catch (err) {
      const detail = err.response?.data?.detail
        || (err.code === 'ECONNABORTED' ? 'Request timed out while contacting the Rights Explainer. Please try again.' : null)
        || err.message
        || 'An error occurred while reaching the Rights Explainer Agent.';
      setErrorMsg(detail);
      const errorAgentMsg = {
        sender: 'agent',
        text: `Error: ${detail}`,
        status: 'error',
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, errorAgentMsg]);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="rights-container">
      {/* Header Banner */}
      <div className="rights-header">
        <div className="rights-title-area">
          <div className="rights-header-icon-wrap">
            <Scale size={24} strokeWidth={2.2} />
          </div>
          <div>
            <h1 className="rights-title">Rights Explainer Agent</h1>
            <p className="rights-subtitle">Understand your legal rights in plain language, backed by verified Indian Acts</p>
          </div>
        </div>
        <span className="badge-rag">Qdrant + BGE-M3 RAG</span>
      </div>

      {/* Suggestion Chips */}
      <div className="suggestions-panel">
        {SAMPLE_QUESTIONS.map((q, idx) => (
          <button
            key={idx}
            className="suggestion-chip"
            onClick={() => handleSend(q)}
            disabled={isLoading}
          >
            <Lightbulb size={15} className="suggestion-icon" />
            <span>{q}</span>
          </button>
        ))}
      </div>

      {/* Chat Messages History */}
      <div className="chat-history">
        {messages.length === 0 ? (
          <div className="chat-empty">
            <div className="chat-empty-icon-wrap">
              <BookOpen size={36} />
            </div>
            <h3>Ask any question about your legal rights in India</h3>
            <p>Example: Tenant deposits, POSH harassment rules, RTI response limits, or consumer redressal.</p>
          </div>
        ) : (
          messages.map((msg, index) => (
            <div key={index} className={`message-row ${msg.sender}`}>
              <span className="message-sender">
                {msg.sender === 'user' ? 'You (Citizen)' : 'LEXIS Rights Explainer'}
              </span>
              <div className="message-bubble">
                {msg.sender === 'user' ? (
                  <div className="user-message-text">{msg.text}</div>
                ) : (
                  <FormattedMessage text={msg.text} />
                )}
                {msg.sender === 'agent' && (
                  <div className={`verification-badge ${msg.verificationStatus || 'unverified'}`}>
                    <span className="verification-dot"></span>

                    <span>
                      {msg.verificationStatus === 'verified'
                        ? 'Verified'
                        : msg.verificationStatus === 'verified_with_scope'
                          ? 'Verified with Scope'
                          : 'Unverified / Not Verified'}
                    </span>
                  </div>
                )}

                {/* Verified Citation Card */}
                {msg.citations && msg.citations.length > 0 && (
                  <div className="citation-card">
                    <div className="citation-card-header">
                      <ShieldCheck size={16} />
                      <span>Verified Source Citation:</span>
                    </div>
                    <div>
                      {msg.citations.map((c, i) => (
                        <div key={i}>• {c}</div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>
          ))
        )}

        {isLoading && (
          <div className="message-row agent">
            <span className="message-sender">LEXIS Rights Explainer</span>
            <div className="message-bubble typing-indicator">
              <Search size={16} className="animate-spin" style={{ display: 'inline', verticalAlign: 'middle', marginRight: '6px' }} />
              <span>Searching Qdrant legal knowledge base &amp; drafting verified answer...</span>
            </div>
          </div>
        )}

        <div ref={chatEndRef} />
      </div>

      {/* Input Bar */}
      <div className="input-bar">
        <input
          type="text"
          className="rights-input"
          placeholder="Ask a question about your rights (e.g. Can my landlord deduct my deposit?)..."
          value={inputText}
          onChange={(e) => setInputText(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSend()}
          disabled={isLoading}
        />
        <button
          className="btn-send"
          onClick={() => handleSend()}
          disabled={isLoading || !inputText.trim()}
        >
          {isLoading ? 'Searching...' : 'Ask Rights Agent →'}
        </button>
      </div>
    </div>
  );
}

export default RightsExplainer;
