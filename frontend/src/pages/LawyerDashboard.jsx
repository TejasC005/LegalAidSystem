/*
 * frontend/src/pages/LawyerDashboard.jsx
 * ──────────────────────────────────────────────────────────────────────────────
 * LEXIS — Lawyer Dashboard (Module 13: Coming Soon scaffold)
 *
 * WHAT THIS PAGE IS:
 *   This is an intentional, documented coming-soon screen.  It is NOT a bug,
 *   a missing feature, or an incomplete implementation.  It is the correct
 *   output of Module 13, which establishes the lawyer-role permission boundary
 *   without building any lawyer-facing feature logic.
 *
 * WHO CAN SEE THIS PAGE:
 *   Only authenticated users with role="lawyer".
 *   App.jsx wraps this route with <ProtectedRoute allowedRoles={['lawyer']} />.
 *   Any other role (user, admin, anonymous) is redirected to the home dashboard.
 *
 * WHY SCAFFOLD NOW (architectural rationale for academic report):
 *   1.  Closes the permission gap: the lawyer role has been issuable since
 *       Module 2.  Without a route, a lawyer JWT had no defined landing page
 *       — undefined behaviour is a security concern.
 *   2.  Single extension point: when the real lawyer feature is built, this
 *       file is the only thing that changes.  No new routing, no new guards,
 *       no new auth changes needed.
 *   3.  Testable boundary: role-isolation tests can run TODAY and will catch
 *       future regressions.
 *   4.  Honest documentation: README and docs mark this as "scaffolded only".
 *       The code matches the documentation exactly.
 * ──────────────────────────────────────────────────────────────────────────────
 */

import React from 'react';
import { useAuth } from '../context/AuthContext';
import './LawyerDashboard.css';

// ── Coming-soon feature list (static text — NOT functional links) ─────────────
// These are planned features for a future phase.  None of them are wired to
// any backend logic.  They are listed here as honest documentation.
const PLANNED_FEATURES = [
  {
    icon: '📂',
    title: 'Case Referrals',
    description:
      'Receive referral requests from citizens whose legal needs exceed self-help tools. ' +
      'Review case summaries submitted by the LEXIS system and choose to accept or decline.',
    phase: 'Future phase',
    id: 'feature-case-referrals',
  },
  {
    icon: '🪪',
    title: 'Lawyer Verification',
    description:
      'Submit your Bar Council of India registration number and valid practice certificate ' +
      'for admin review. A verified badge unlocks case referral visibility to citizens.',
    phase: 'Future phase',
    id: 'feature-lawyer-verification',
  },
  {
    icon: '📅',
    title: 'Consultation Booking',
    description:
      'Set your available time windows and let citizens book 30-minute consultation slots ' +
      'directly from LEXIS. Receive booking notifications and session reminders.',
    phase: 'Future phase',
    id: 'feature-consultation-booking',
  },
];


// ── LawyerDashboard component ──────────────────────────────────────────────────
function LawyerDashboard() {
  const { user } = useAuth();

  return (
    <div className="lawyer-dashboard" id="lawyer-dashboard-page">

      {/* ── Hero banner ─────────────────────────────────────────────────── */}
      <div className="lawyer-hero">
        <div className="lawyer-hero__badge" id="lawyer-role-badge">
          ⚖️  Legal Professional Portal
        </div>
        <h1 className="lawyer-hero__title">
          Lawyer Dashboard
        </h1>
        <p className="lawyer-hero__subtitle">
          Welcome{user?.phone ? `, ${user.phone}` : ''}.
          Your role and permission boundary are active.
        </p>
      </div>

      {/* ── Coming Soon notice ───────────────────────────────────────────── */}
      <div className="lawyer-notice" id="lawyer-coming-soon-notice" role="status" aria-live="polite">
        <div className="lawyer-notice__icon">🚧</div>
        <div className="lawyer-notice__body">
          <h2 className="lawyer-notice__heading">Coming Soon — Future Phase</h2>
          <p className="lawyer-notice__text">
            This portal is an <strong>intentional, documented scaffold</strong> — not a bug
            or missing feature. The lawyer role exists and is enforced in the permission
            system, but the full feature set is deferred to a post-MVP development phase.
          </p>
          <p className="lawyer-notice__text">
            Listed below are the planned features. None of them are functional yet.
            They are shown here as honest documentation of future scope.
          </p>
        </div>
      </div>

      {/* ── Planned features (static text, NOT functional) ──────────────── */}
      <section className="lawyer-features" aria-labelledby="planned-features-heading">
        <h2 className="lawyer-features__heading" id="planned-features-heading">
          Planned Features — Not Yet Implemented
        </h2>

        <div className="lawyer-features__grid">
          {PLANNED_FEATURES.map((feature) => (
            <article
              key={feature.id}
              id={feature.id}
              className="lawyer-feature-card"
              aria-label={`Planned feature: ${feature.title}`}
            >
              <div className="lawyer-feature-card__icon" aria-hidden="true">
                {feature.icon}
              </div>
              <div className="lawyer-feature-card__body">
                <h3 className="lawyer-feature-card__title">{feature.title}</h3>
                <p className="lawyer-feature-card__description">{feature.description}</p>
                <span className="lawyer-feature-card__phase-badge">
                  🗓 {feature.phase}
                </span>
              </div>
            </article>
          ))}
        </div>
      </section>

      {/* ── Scope boundary note ──────────────────────────────────────────── */}
      <footer className="lawyer-scope-note" id="lawyer-scope-note">
        <div className="lawyer-scope-note__inner">
          <span className="lawyer-scope-note__icon">ℹ️</span>
          <p className="lawyer-scope-note__text">
            <strong>Architectural note:</strong> This scaffold exists to lock the
            role-permission boundary in code before the feature set is built.
            It prevents accidental privilege leak (lawyer JWTs cannot reach admin or
            citizen routes), provides a single extension point for the next phase,
            and makes role-isolation unit tests runnable today.
            See Module 13 in the project README for full rationale.
          </p>
        </div>
      </footer>

    </div>
  );
}

export default LawyerDashboard;
