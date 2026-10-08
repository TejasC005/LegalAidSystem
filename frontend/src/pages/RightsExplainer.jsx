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
import { sendQuery } from '../services/api';
import './RightsExplainer.css';

const SAMPLE_QUESTIONS = [
  "Can my landlord deduct money from my security deposit without bills?",
  "What are the rules and timelines for POSH workplace harassment reporting?",
  "How long can a PIO take to answer an RTI application?",
  "What rights do I have if I receive a defective product from e-commerce?",
];

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
      console.log('LEXIS AGENTS:', data.agents);
      console.log('LEXIS SCRATCHPAD:', data.scratchpad);

      // Extract metadata citations from scratchpad if available
      // Extract citations and verification status from specialist metadata
      // Extract citations and verification status from specialist agents
      let citations = [];
      let verificationStatus = 'unverified';

      // The API exposes specialist results under `agents`
      const agentRecords = data.agents || data.scratchpad || [];

      agentRecords.forEach((record) => {
        if (record.metadata) {
          if (record.metadata.citations) {
            citations = [...citations, ...record.metadata.citations];
          }

          // Only use verification status from the Rights Explainer
          if (
            record.metadata.agent === 'RightsExplainerAgent' &&
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
      console.error('Failed to execute query:', err);
      const detail = err.response?.data?.detail || 'An error occurred while reaching the Rights Explainer Agent.';
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
          <span className="rights-header-icon">⚖️</span>
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
            💡 {q}
          </button>
        ))}
      </div>

      {/* Chat Messages History */}
      <div className="chat-history">
        {messages.length === 0 ? (
          <div className="chat-empty">
            <span className="chat-empty-icon">📜</span>
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
                {msg.text}
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
                      🛡️ Verified Source Citation:
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
              <span>🔍 Searching Qdrant legal knowledge base & drafting verified answer...</span>
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
