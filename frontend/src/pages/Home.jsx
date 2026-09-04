/*
 * frontend/src/pages/Home.jsx
 * ──────────────────────────────────────────────────────────────────────────────
 * LEXIS — Dashboard / Home Page (Module 3)
 *
 * This is the first page the user sees after logging in.
 * It shows a greeting, a summary of the user's account, and
 * six cards — one for each LEXIS feature — that link to the feature pages.
 *
 * Right now the feature pages are placeholders.  Future modules will fill them in.
 * ──────────────────────────────────────────────────────────────────────────────
 */

import React from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import './Home.css';

// ── Feature cards data ─────────────────────────────────────────────────────
// Same 6 features as the sidebar nav links.
// `module` is the module number that will build the real UI.
const FEATURES = [
  {
    path:    '/rights-explainer',
    icon:    '⚖️',
    title:   'Rights Explainer',
    desc:    'Understand your legal rights as an Indian citizen in plain language.',
    module:  5,
    color:   '#1a6b5a',
  },
  {
    path:    '/document-drafter',
    icon:    '📄',
    title:   'Document Drafter',
    desc:    'Generate legal document drafts — RTI applications, affidavits, notices.',
    module:  6,
    color:   '#1a4a6b',
  },
  {
    path:    '/document-analyzer',
    icon:    '🔍',
    title:   'Document Analyzer',
    desc:    'Upload a contract or document to get a risk and clause analysis.',
    module:  7,
    color:   '#6b1a5a',
  },
  {
    path:    '/scam-detection',
    icon:    '🚨',
    title:   'Scam Detection',
    desc:    'Identify common legal scams and fraudulent schemes targeting citizens.',
    module:  8,
    color:   '#8b3a0a',
  },
  {
    path:    '/filing-guide',
    icon:    '📋',
    title:   'Filing Guide',
    desc:    'Find the right authority to file a complaint with — step by step.',
    module:  9,
    color:   '#1a6b35',
  },
  {
    path:    '/vault-deadlines',
    icon:    '🔐',
    title:   'Vault & Deadlines',
    desc:    'Securely store important documents and receive deadline reminders.',
    module:  10,
    color:   '#4a1a6b',
  },
];


// ── Home component ─────────────────────────────────────────────────────────
function Home() {
  const { user } = useAuth();

  // Friendly display name: phone number or fallback
  const displayName = user?.phone || user?.id || 'Citizen';

  return (
    <div className="home-page">

      {/* ── Welcome banner ───────────────────────────────────────── */}
      <div className="home-welcome">
        <div className="home-welcome__text">
          <h1 className="home-welcome__heading">
            Welcome to LEXIS
          </h1>
          <p className="home-welcome__sub">
            Signed in as <strong>{displayName}</strong>
            <span className="home-welcome__role"> · {user?.role || 'user'}</span>
          </p>
          <p className="home-welcome__desc">
            LEXIS is your autonomous legal aid assistant. Choose a feature below
            to get started. Each feature is powered by a specialist AI agent.
          </p>
        </div>
      </div>

      {/* ── Feature grid ─────────────────────────────────────────── */}
      <section aria-labelledby="features-heading">
        <h2 id="features-heading" className="home-section-title">
          Available Features
        </h2>

        <div className="home-feature-grid">
          {FEATURES.map((feature) => (
            <Link
              key={feature.path}
              to={feature.path}
              className="home-feature-card card"
              style={{ '--card-accent': feature.color }}   /* Custom CSS variable per card */
            >
              <span className="home-feature-card__icon">{feature.icon}</span>
              <div className="home-feature-card__body">
                <h3 className="home-feature-card__title">{feature.title}</h3>
                <p className="home-feature-card__desc">{feature.desc}</p>
              </div>
              <span className="home-feature-card__module">Module {feature.module}</span>
            </Link>
          ))}
        </div>
      </section>

    </div>
  );
}

export default Home;
