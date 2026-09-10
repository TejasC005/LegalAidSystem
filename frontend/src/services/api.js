/*
 * frontend/src/services/api.js
 * ──────────────────────────────────────────────────────────────────────────────
 * LEXIS — Axios API Client (Module 3)
 *
 * WHAT IS THIS FILE?
 *   Axios is a JavaScript library that makes HTTP requests (GET, POST, etc.)
 *   to the backend.  Instead of writing the base URL in every request, we
 *   create ONE "instance" here with default settings.  Every other file just
 *   imports this instance and calls it directly.
 *
 * HOW DOES THE TOKEN GET ATTACHED AUTOMATICALLY?
 *   An "interceptor" is a function that runs automatically on every request
 *   BEFORE it is sent (or on every response AFTER it is received).
 *
 *   Request interceptor (lines below):
 *     1. Reads the access token from localStorage.
 *     2. If a token exists, it adds the header:
 *        Authorization: Bearer <token>
 *     The backend's get_current_user dependency reads that header to identify
 *     who is making the request.
 *
 *   Response interceptor:
 *     1. If the backend replies with HTTP 401 (Unauthorized — usually "token
 *        expired or missing"), we clear the stored tokens and redirect the
 *        browser to /login so the user can sign in again.
 *
 * VITE ENV VARIABLE:
 *   import.meta.env.VITE_API_BASE_URL comes from frontend/.env.
 *   Vite automatically injects variables that start with VITE_ into the app.
 *   The fallback 'http://localhost:8000' is a safe default for local dev.
 * ──────────────────────────────────────────────────────────────────────────────
 */

import axios from 'axios';

// ── Create the Axios instance ──────────────────────────────────────────────
// baseURL: every request we make will be prefixed with this.
// e.g.  api.post('/api/v1/auth/send-otp', ...)
//       → actually calls http://localhost:8000/api/v1/auth/send-otp
const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000',
  headers: {
    'Content-Type': 'application/json',  // We always send/expect JSON
  },
  timeout: 15000,  // 15 seconds — give up if server takes too long
});


// ── Request interceptor — attach JWT automatically ─────────────────────────
// This function runs on EVERY outgoing request.
api.interceptors.request.use(
  (config) => {
    // Read the token from localStorage (where we stored it after login).
    const token = localStorage.getItem('lexis_access_token');

    if (token) {
      // Add the Authorization header.
      // The backend's get_current_user dependency reads "Bearer <token>".
      config.headers['Authorization'] = `Bearer ${token}`;
    }

    return config;  // Always return the config — this tells Axios to proceed
  },
  (error) => {
    // If something went wrong while building the request, just reject it.
    return Promise.reject(error);
  }
);


// ── Response interceptor — handle 401 (expired / invalid token) ───────────
// This function runs on EVERY response that comes back from the server.
api.interceptors.response.use(
  (response) => {
    // If the response was successful (2xx), just pass it through unchanged.
    return response;
  },
  (error) => {
    // Check if the server returned 401 Unauthorized.
    if (error.response && error.response.status === 401) {
      // Clear stored credentials — they are no longer valid.
      localStorage.removeItem('lexis_access_token');
      localStorage.removeItem('lexis_refresh_token');
      localStorage.removeItem('lexis_user');

      // Send the user to the login page.
      // We use window.location.href (a hard browser redirect) instead of
      // React Router here because this interceptor lives outside React.
      if (window.location.pathname !== '/login') {
        window.location.href = '/login';
      }
    }

    // Re-throw the error so the calling code can handle it too if needed.
    return Promise.reject(error);
  }
);


// ── Typed API helpers ──────────────────────────────────────────────────────
// These thin wrappers call the exact backend endpoints from Module 2.
// Keeping them here means if the URL ever changes, you only fix it in one place.

/**
 * Step 1 of login: request an OTP for an email address (or phone number).
 * @param {string|object} target  Email address (e.g. "citizen@example.com") or { email } / { phone }
 * @returns {Promise}             Resolves with the axios response object
 */
export function sendOtp(target) {
  const payload = typeof target === 'string'
    ? (target.includes('@') ? { email: target.trim().toLowerCase() } : { phone: target.trim() })
    : target;
  return api.post('/api/v1/auth/send-otp', payload);
}

/**
 * Step 2 of login: submit the OTP received.
 * @param {string|object} target  Email address or phone number, or object { email, otp }
 * @param {string} [otp]          6-digit code
 * @returns {Promise}             Resolves with { access_token, refresh_token, role }
 */
export function verifyOtp(target, otp) {
  let payload;
  if (typeof target === 'object') {
    payload = target;
  } else if (typeof target === 'string' && target.includes('@')) {
    payload = { email: target.trim().toLowerCase(), otp: otp?.trim() };
  } else {
    payload = { phone: target?.trim(), otp: otp?.trim() };
  }
  return api.post('/api/v1/auth/verify-otp', payload);
}

/**
 * Exchange Firebase ID token for LEXIS JWT access + refresh tokens (legacy).
 * @param {string} idToken  Firebase user ID token
 * @param {string} phone    Phone number verified by Firebase
 * @returns {Promise}       Resolves with { access_token, refresh_token, role }
 */
export function verifyFirebaseToken(idToken, phone) {
  return api.post('/api/v1/auth/verify-firebase-token', { id_token: idToken, phone });
}


/**
 * Get the currently-logged-in user's profile.
 * The request interceptor above attaches the Bearer token automatically.
 * @returns {Promise}  Resolves with the user object from MongoDB
 */
export function getMe() {
  return api.get('/api/v1/auth/me');
}

/**
 * Sends a citizen query to the LEXIS Orchestrator Agent core.
 * @param {string} query  The legal question
 * @returns {Promise}     Resolves with QueryResponse { query, final_response, status, intents, scratchpad }
 */
export function sendQuery(query) {
  return api.post('/api/v1/query', { query });
}

/**
 * Fetch available document templates.
 */
export function getDraftTemplates() {
  return api.get('/api/v1/drafts/templates');
}

/**
 * Start a new drafting session.
 * @param {string} docType  'rti_application' | 'legal_notice' | 'consumer_complaint'
 */
export function startDraftSession(docType) {
  return api.post('/api/v1/drafts/session', { doc_type: docType });
}

/**
 * Submit answer to current question in draft session.
 * @param {string} sessionId
 * @param {string} answer
 */
export function submitDraftAnswer(sessionId, answer) {
  return api.post(`/api/v1/drafts/session/${sessionId}/answer`, { answer });
}

/**
 * List user's saved drafts.
 */
export function getUserDrafts() {
  return api.get('/api/v1/drafts');
}

/**
 * Download draft file (PDF or DOCX).
 */
export function downloadDraftFile(draftId, format) {
  return api.get(`/api/v1/drafts/${draftId}/download/${format}`, {
    responseType: 'blob'
  });
}

/**
 * Module 7: Upload a document for analysis.
 *
 * WHY FORMDATA (not JSON)?
 *   File uploads use multipart/form-data — a special HTTP content type that
 *   allows sending binary files alongside other fields.  JSON can only carry
 *   text; it cannot carry raw file bytes.
 *
 *   We pass the file in a FormData object (the browser's built-in API).
 *   Axios automatically sets the correct Content-Type: multipart/form-data
 *   header with the boundary marker when it detects FormData.
 *   We must NOT set Content-Type manually here — that would break the boundary.
 *
 * @param {File} file  The File object from the file input element
 * @returns {Promise}  Resolves with AnalysisResponse (clauses array + summary stats)
 */
export function uploadDocumentForAnalysis(file) {
  const formData = new FormData();
  formData.append('file', file);

  return api.post('/api/v1/analysis/upload', formData, {
    headers: {
      // Let Axios set Content-Type automatically — do NOT set it manually
      // Setting it manually breaks multipart boundary and causes 422 errors
      'Content-Type': undefined,
    },
    timeout: 60000,  // 60s — OCR on large documents can take time
  });
}

/**
 * Module 7: List the current user's past document analyses.
 * @returns {Promise}  Resolves with { analyses: [...] }
 */
export function getUserAnalyses() {
  return api.get('/api/v1/analysis/');
}

/**
 * Module 7: Get a specific analysis result by ID.
 * @param {string} analysisId
 * @returns {Promise}
 */
export function getAnalysis(analysisId) {
  return api.get(`/api/v1/analysis/${analysisId}`);
}

// ─────────────────────────────────────────────────────────────────────────────
// Module 8 — Scam Detection Helpers
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Module 8: Submit a description for scam pattern matching.
 *
 * Returns a ScamCheckResponse containing:
 *   - status: "matched" | "no_match" | "error"
 *   - alert: ScamAlertCard (all fields sourced from the DB, never LLM-generated)
 *   - message: human-readable summary string
 *
 * Safety note: the backend guarantees that every alert.* field returned here
 * traces to a real seeded database document (identified by alert.db_id).
 * This function does not need to add or modify any returned content.
 *
 * @param {string} description - The citizen's situation description (10–2000 chars)
 * @returns {Promise<{status, alert, message}>}
 */
export async function checkScam(description) {
  const response = await api.post('/api/v1/scam/check', { description });
  return response.data;
}

/**
 * Module 8: Fetch the list of all seeded scam patterns.
 *
 * Returns { total, patterns: [{id, name, severity, keywords}, ...] }
 * Useful for admin verification and for debugging the seed dataset.
 *
 * @returns {Promise<{total, patterns}>}
 */
export async function getScamPatterns() {
  const response = await api.get('/api/v1/scam/patterns');
  return response.data;
}

// ─────────────────────────────────────────────────────────────────────────────
// Module 9 — Complaint Filing Guide Helpers
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Module 9: Look up the filing authority for a given document type.
 *
 * DIRECT LOOKUP PATH:
 *   Called when the citizen selects a doc_type from the dropdown on the
 *   Filing Guide page (no prior draft session needed).
 *
 * @param {string} docType  'rti_application' | 'consumer_complaint' | 'legal_notice'
 * @returns {Promise<{found, doc_type, authority_name, portal_url, fee, required_documents, ...}>}
 */
export function lookupFilingAuthority(docType) {
  return api.get('/api/v1/filing/lookup', { params: { doc_type: docType } });
}

/**
 * Module 9: Look up filing authority via a completed draft session (Module 6 → Module 9 handoff).
 *
 * HANDOFF PATH:
 *   Called when the citizen clicks "📋 Where to File →" on the Document Drafter
 *   completed preview card. The draft_id is passed so the backend can read the
 *   doc_type directly from the draft record — the citizen does NOT re-enter
 *   their document type.
 *
 *   Backend logic (api/routes/filing.py):
 *     1. Reads doc_type from db.user_drafts.find_one({"draft_id": draft_id, "user_id": user_id})
 *     2. Calls FilingGuideAgent.lookup_authority(doc_type)
 *     3. Returns the verified authority record
 *
 *   Security: the backend enforces user_id access control — only the draft owner
 *   can use their draft_id. Others get 404, not 403.
 *
 * @param {string} draftId  UUID from the completed draft session
 * @returns {Promise<{found, doc_type, authority_name, portal_url, fee, required_documents, ...}>}
 */
export function lookupFilingByDraftId(draftId) {
  return api.get('/api/v1/filing/lookup', { params: { draft_id: draftId } });
}

/**
 * Module 9: List all available filing authorities.
 * Used to populate the Filing Guide dropdown and for admin verification.
 *
 * @returns {Promise<Array<{id, doc_type, doc_type_name, authority_short, portal_url, verified}>>}
 */
export function getFilingAuthorities() {
  return api.get('/api/v1/filing/authorities');
}

// ─────────────────────────────────────────────────────────────────────────────
// Module 12 — Admin Panel Helpers
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Module 12: Fetch overview analytics from real reflection_logs collection.
 * @returns {Promise<{total_sessions_logged, total_agent_evaluations, pass_rate_percentage, ...}>}
 */
export function getAdminAnalyticsOverview() {
  return api.get('/api/v1/admin/analytics/overview');
}

/**
 * Module 12: Fetch per-agent breakdown for all 6 agents.
 * @returns {Promise<Array<{agent_id, total_queries, passed_queries, failed_queries, fallback_queries, retry_count_total, contradiction_count}>>}
 */
export function getAdminAgentAnalytics() {
  return api.get('/api/v1/admin/analytics/agents');
}

/**
 * Module 12: List registered users with role and status.
 * @returns {Promise<Array<{id, phone, role, is_active, created_at}>>}
 */
export function getAdminUsers(skip = 0, limit = 50) {
  return api.get('/api/v1/admin/users', { params: { skip, limit } });
}

/**
 * Module 12: Suspend a user account (set is_active = false).
 * @param {string} userId
 */
export function suspendUser(userId) {
  return api.patch(`/api/v1/admin/users/${userId}/suspend`);
}

/**
 * Module 12: Reactivate a user account (set is_active = true).
 * @param {string} userId
 */
export function reactivateUser(userId) {
  return api.patch(`/api/v1/admin/users/${userId}/reactivate`);
}

/**
 * Module 12: Surface Confirmation Agent fallback logs for human moderation.
 * @returns {Promise<Array<{session_id, timestamp, agents_checked, pass_fail, retry_count, rejection_reason, ...}>>}
 */
export function getModerationQueue(limit = 50) {
  return api.get('/api/v1/admin/moderation/queue', { params: { limit } });
}

// ─────────────────────────────────────────────────────────────────────────────
// Module 13B — Enhanced Auth & Profile Helpers
// ─────────────────────────────────────────────────────────────────────────────

export function sendEmailOtp(email) {
  return api.post('/api/v1/users/me/email/send-otp', { email });
}

export function verifyEmailOtp(email, otp) {
  return api.post('/api/v1/users/me/email/verify-otp', { email, otp });
}

export function getUserProfile() {
  return api.get('/api/v1/users/me/profile');
}

export function updateUserProfile(data) {
  return api.patch('/api/v1/users/me/profile', data);
}

export function uploadProfilePicture(file) {
  const formData = new FormData();
  formData.append('file', file);
  return api.post('/api/v1/users/me/profile/picture', formData, {
    headers: { 'Content-Type': undefined },
  });
}

export function deleteAccount() {
  return api.delete('/api/v1/users/me');
}

export function exportUserData() {
  return api.get('/api/v1/users/me/export');
}

// Default export — the raw Axios instance.
// Other files can import this if they need to make custom requests.
export default api;
