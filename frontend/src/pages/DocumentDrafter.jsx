/*
 * frontend/src/pages/DocumentDrafter.jsx
 * ──────────────────────────────────────────────────────────────────────────
 * LEXIS — Document Drafter Feature Page (Module 6)
 *
 * Interactive multi-step conversational form for drafting legal documents:
 *   - RTI Application (Right to Information 2005)
 *   - Legal Demand Notice (Landlord deposit refund, contract breach)
 *   - Consumer Complaint (Consumer Protection Act 2019)
 *
 * Features:
 *   - Interactive step-by-step questionnaire
 *   - Real-time progress indicator
 *   - Formatted Document Preview
 *   - Server-side PDF & DOCX export downloads
 * ──────────────────────────────────────────────────────────────────────────
 */

import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  getDraftTemplates,
  startDraftSession,
  submitDraftAnswer,
  getUserDrafts,
  downloadDraftFile,
} from '../services/api';
import './DocumentDrafter.css';

function DocumentDrafter() {
  const navigate = useNavigate();
  const [templates, setTemplates] = useState([]);
  const [selectedTemplate, setSelectedTemplate] = useState(null);
  const [sessionId, setSessionId] = useState(null);
  const [sessionData, setSessionData] = useState(null);
  const [currentAnswer, setCurrentAnswer] = useState('');
  const [history, setHistory] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState('');
  const [savedDrafts, setSavedDrafts] = useState([]);

  useEffect(() => {
    loadTemplatesAndDrafts();
  }, []);

  const loadTemplatesAndDrafts = async () => {
    try {
      const [tplRes, draftsRes] = await Promise.all([
        getDraftTemplates(),
        getUserDrafts().catch(() => ({ data: [] })),
      ]);
      setTemplates(tplRes.data);
      setSavedDrafts(draftsRes.data || []);
    } catch (err) {
      console.error('Failed to load templates:', err);
    }
  };

  const handleStartSession = async (docType) => {
    setIsLoading(true);
    setErrorMsg('');
    try {
      const res = await startDraftSession(docType);
      const data = res.data;
      setSelectedTemplate(docType);
      setSessionId(data.session_id);
      setSessionData(data);

      setHistory([
        {
          sender: 'system',
          text: `Starting draft for **${data.doc_type_name}**. Please answer the following questions to build your document.`,
        },
        {
          sender: 'agent',
          question: data.current_question,
          step: 1,
          total: data.total_questions,
        },
      ]);
    } catch (err) {
      setErrorMsg(err.response?.data?.detail || 'Failed to start draft session.');
    } finally {
      setIsLoading(false);
    }
  };

  const handleSubmitAnswer = async (e) => {
    e?.preventDefault();
    if (!currentAnswer.trim() || !sessionId || isLoading) return;

    const answerText = currentAnswer.trim();
    setCurrentAnswer('');
    setIsLoading(true);
    setErrorMsg('');

    // Append user answer to history
    setHistory((prev) => [
      ...prev,
      { sender: 'user', text: answerText },
    ]);

    try {
      const res = await submitDraftAnswer(sessionId, answerText);
      const data = res.data;
      setSessionData(data);

      if (data.status === 'completed') {
        setHistory((prev) => [
          ...prev,
          {
            sender: 'system',
            text: '🎉 Document assembly complete! See the preview below.',
          },
        ]);
        loadTemplatesAndDrafts();
      } else {
        setHistory((prev) => [
          ...prev,
          {
            sender: 'agent',
            question: data.current_question,
            step: data.questions_answered + 1,
            total: data.total_questions,
          },
        ]);
      }
    } catch (err) {
      setErrorMsg(err.response?.data?.detail || 'Failed to submit answer.');
    } finally {
      setIsLoading(false);
    }
  };

  const handleDownload = async (draftId, format) => {
    try {
      const res = await downloadDraftFile(draftId, format);
      const blob = new Blob([res.data], {
        type: format === 'pdf' ? 'application/pdf' : 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
      });
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `legal_document_${draftId.substring(0, 8)}.${format}`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
    } catch (err) {
      alert('Failed to download file. Please try again.');
    }
  };

  const resetSession = () => {
    setSelectedTemplate(null);
    setSessionId(null);
    setSessionData(null);
    setHistory([]);
    setCurrentAnswer('');
  };

  return (
    <div className="drafter-container">
      {/* Banner */}
      <div className="drafter-header">
        <div className="drafter-title-area">
          <span className="drafter-icon">📄</span>
          <div>
            <h1 className="drafter-title">Document Drafter Agent</h1>
            <p className="drafter-subtitle">
              Draft RTI applications, legal demand notices, and consumer complaints in minutes
            </p>
          </div>
        </div>
        <span className="badge-drafter">Clause Engine + PDF/DOCX</span>
      </div>

      {errorMsg && <div className="error-banner">⚠️ {errorMsg}</div>}

      {/* Step 1: Template Selection (if no session active) */}
      {!selectedTemplate && (
        <div className="template-selection-section">
          <h2>Select Document Type to Draft</h2>
          <div className="templates-grid">
            {templates.map((tpl) => (
              <div key={tpl.id} className="template-card" onClick={() => handleStartSession(tpl.id)}>
                <div className="template-card-icon">
                  {tpl.id === 'rti_application' ? '🏛️' : tpl.id === 'legal_notice' ? '⚖️' : '🛒'}
                </div>
                <h3>{tpl.name}</h3>
                <p>{tpl.description}</p>
                <div className="template-card-footer">
                  <span>{tpl.total_questions} Questions</span>
                  <button className="btn-start-draft">Start Draft →</button>
                </div>
              </div>
            ))}
          </div>

          {/* Saved Drafts Section */}
          {savedDrafts.length > 0 && (
            <div className="saved-drafts-section">
              <h3>📁 Your Saved Drafted Documents</h3>
              <div className="saved-drafts-list">
                {savedDrafts.map((d) => (
                  <div key={d.draft_id} className="saved-draft-item">
                    <div>
                      <strong>{d.title}</strong>
                      <div className="draft-meta">{d.doc_type_name} • {new Date(d.created_at).toLocaleDateString()}</div>
                    </div>
                    <div className="download-actions">
                      <button className="btn-download pdf" onClick={() => handleDownload(d.draft_id, 'pdf')}>
                        📥 PDF
                      </button>
                      <button className="btn-download docx" onClick={() => handleDownload(d.draft_id, 'docx')}>
                        📥 DOCX
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Step 2: Active Drafting Session */}
      {selectedTemplate && sessionData && (
        <div className="active-drafting-session">
          <div className="session-top-bar">
            <button className="btn-back" onClick={resetSession}>← Back to Templates</button>
            <div className="session-progress">
              <span>Progress: {sessionData.questions_answered} / {sessionData.total_questions}</span>
              <div className="progress-bar-bg">
                <div
                  className="progress-bar-fill"
                  style={{ width: `${(sessionData.questions_answered / sessionData.total_questions) * 100}%` }}
                />
              </div>
            </div>
          </div>

          {/* Conversation Area */}
          <div className="draft-chat-window">
            {history.map((item, idx) => (
              <div key={idx} className={`chat-row ${item.sender}`}>
                {item.sender === 'system' && (
                  <div className="system-msg">{item.text}</div>
                )}
                {item.sender === 'user' && (
                  <div className="user-bubble">{item.text}</div>
                )}
                {item.sender === 'agent' && (
                  <div className="agent-question-box">
                    <span className="question-step-badge">Question {item.step} of {item.total}</span>
                    <p className="question-text">{item.question}</p>
                  </div>
                )}
              </div>
            ))}

            {isLoading && (
              <div className="chat-row agent">
                <div className="typing-indicator">⚙️ Processing your answer...</div>
              </div>
            )}
          </div>

          {/* Input Bar (if in progress) */}
          {sessionData.status !== 'completed' && (
            <form onSubmit={handleSubmitAnswer} className="draft-input-form">
              <input
                type="text"
                className="draft-input"
                placeholder="Type your answer here..."
                value={currentAnswer}
                onChange={(e) => setCurrentAnswer(e.target.value)}
                disabled={isLoading}
                autoFocus
              />
              <button type="submit" className="btn-submit-answer" disabled={isLoading || !currentAnswer.trim()}>
                Next Step →
              </button>
            </form>
          )}

          {/* Document Completed Preview */}
          {sessionData.status === 'completed' && sessionData.assembled_document && (
            <div className="document-preview-card">
              <div className="preview-header">
                <h3>📜 Assembled Document Preview</h3>
                <div className="preview-download-buttons">
                  <button
                    className="btn-download pdf"
                    onClick={() => handleDownload(sessionData.draft_id, 'pdf')}
                  >
                    📥 Download PDF
                  </button>
                  <button
                    className="btn-download docx"
                    onClick={() => handleDownload(sessionData.draft_id, 'docx')}
                  >
                    📥 Download DOCX
                  </button>
                  {/*
                   * MODULE 9 HANDOFF BUTTON
                   * ─────────────────────────────────────────────────────────
                   * Clicking this takes the citizen to the Filing Guide with
                   * their doc_type and draft_id pre-filled via URL params.
                   *
                   * The Filing Guide reads doc_type from the draft record
                   * in MongoDB — NO re-entry required. The citizen immediately
                   * sees the correct filing authority for their document type.
                   *
                   * doc_type is authoritative structured data (not re-classified
                   * natural language), so there is zero risk of misclassification.
                   */}
                  <button
                    id="btn-where-to-file"
                    className="btn-where-to-file"
                    onClick={() =>
                      navigate(
                        `/filing-guide?doc_type=${sessionData.doc_type}&draft_id=${sessionData.draft_id}`
                      )
                    }
                    title="Find the correct government authority, portal and documents required to file this complaint"
                  >
                    📋 Where to File →
                  </button>
                </div>
              </div>
              <pre className="preview-document-text">{sessionData.assembled_document}</pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default DocumentDrafter;
