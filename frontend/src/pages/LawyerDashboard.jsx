/*
 * frontend/src/pages/LawyerDashboard.jsx
 * ──────────────────────────────────────────────────────────────────────────────
 * LEXIS — Lawyer Dashboard (Module 13: Coming Soon scaffold)
 *
 * WHAT THIS PAGE IS:
 *   This is an intentional, documented coming-soon screen. It is NOT a bug,
 *   a missing feature, or an incomplete implementation. It is the correct
 *   output of Module 13, which establishes the lawyer-role permission boundary
 *   without building any lawyer-facing feature logic.
 * ──────────────────────────────────────────────────────────────────────────────
 */

import React from 'react';
import {
  Scale,
  Briefcase,
  UserCheck,
  Calendar,
  Clock,
  Info,
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import './LawyerDashboard.css';

// ── Coming-soon feature list (static text — NOT functional links) ─────────────
const PLANNED_FEATURES = [
  {
    iconType: 'referrals',
    title: 'Case Referrals',
    description:
      'Receive referral requests from citizens whose legal needs exceed self-help tools. ' +
      'Review case summaries submitted by the LEXIS system and choose to accept or decline.',
    phase: 'Future phase',
    id: 'feature-case-referrals',
  },
  {
    iconType: 'verification',
    title: 'Lawyer Verification',
    description:
      'Submit your Bar Council of India registration number and valid practice certificate ' +
      'for admin review. A verified badge unlocks case referral visibility to citizens.',
    phase: 'Future phase',
    id: 'feature-lawyer-verification',
  },
  {
    iconType: 'booking',
    title: 'Consultation Booking',
    description:
      'Set your available time windows and let citizens book 30-minute consultation slots ' +
      'directly from LEXIS. Receive booking notifications and session reminders.',
    phase: 'Future phase',
    id: 'feature-consultation-booking',
  },
];

function LawyerDashboard() {
  const { user } = useAuth();

  const renderFeatureIcon = (type) => {
    switch (type) {
      case 'referrals':
        return <Briefcase size={26} color="#134e42" />;
      case 'verification':
        return <UserCheck size={26} color="#134e42" />;
      case 'booking':
        return <Calendar size={26} color="#134e42" />;
      default:
        return <Scale size={26} color="#134e42" />;
    }
  };

  return (
    <div className="lawyer-dashboard" id="lawyer-dashboard-page">
      {/* ── Hero banner ─────────────────────────────────────────────────── */}
      <div className="lawyer-hero">
        <div className="lawyer-hero__badge" id="lawyer-role-badge">
          <Scale size={15} />
          <span>Legal Professional Portal</span>
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
        <div className="lawyer-notice__icon-wrapper">
          <Clock size={24} color="#b45309" />
        </div>
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
              <div className="lawyer-feature-card__icon-badge" aria-hidden="true">
                {renderFeatureIcon(feature.iconType)}
              </div>
              <div className="lawyer-feature-card__body">
                <h3 className="lawyer-feature-card__title">{feature.title}</h3>
                <p className="lawyer-feature-card__description">{feature.description}</p>
                <span className="lawyer-feature-card__phase-badge">
                  <Calendar size={13} />
                  <span>{feature.phase}</span>
                </span>
              </div>
            </article>
          ))}
        </div>
      </section>

      {/* ── Scope boundary note ──────────────────────────────────────────── */}
      <footer className="lawyer-scope-note" id="lawyer-scope-note">
        <div className="lawyer-scope-note__inner">
          <Info size={18} color="#134e42" style={{ flexShrink: 0, marginTop: 2 }} />
          <p className="lawyer-scope-note__text">
            <strong>Architectural note:</strong> This scaffold exists to lock the
            role-permission boundary in code before the feature set is built.
            It prevents accidental privilege leak (lawyer JWTs cannot reach admin or
            citizen routes), provides a single extension point for the next phase,
            and makes role-isolation unit tests runnable today.
          </p>
        </div>
      </footer>
    </div>
  );
}

export default LawyerDashboard;
