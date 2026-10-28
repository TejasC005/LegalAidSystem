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
import {
  Scale,
  FileEdit,
  FileSearch,
  ShieldAlert,
  ClipboardList,
  FolderLock
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import './Home.css';

// ── Feature cards data ─────────────────────────────────────────────────────
const FEATURES = [
  {
    path:    '/rights-explainer',
    icon:    Scale,
    title:   'Rights Explainer',
    desc:    'Understand your legal rights as an Indian citizen in plain language.',
    module:  5,
    color:   '#1a6b5a',
  },
  {
    path:    '/document-drafter',
    icon:    FileEdit,
    title:   'Document Drafter',
    desc:    'Generate legal document drafts — RTI applications, affidavits, notices.',
    module:  6,
    color:   '#1a6b5a',
  },
  {
    path:    '/document-analyzer',
    icon:    FileSearch,
    title:   'Document Analyzer',
    desc:    'Upload a contract or document to get a risk and clause analysis.',
    module:  7,
    color:   '#1a6b5a',
  },
  {
    path:    '/scam-detection',
    icon:    ShieldAlert,
    title:   'Scam Detection',
    desc:    'Identify common legal scams and fraudulent schemes targeting citizens.',
    module:  8,
    color:   '#1a6b5a',
  },
  /* ── Temporarily hidden from Dashboard UI cards. DO NOT DELETE. ───────────
   * Uncomment the blocks below to restore the Filing Guide & Vault cards.
  {
    path:    '/filing-guide',
    icon:    ClipboardList,
    title:   'Filing Guide',
    desc:    'Find the right authority to file a complaint with — step by step.',
    module:  9,
    color:   '#1a6b5a',
  },
  {
    path:    '/vault-deadlines',
    icon:    FolderLock,
    title:   'Vault & Deadlines',
    desc:    'Securely store important documents and receive deadline reminders.',
    module:  10,
    color:   '#1a6b5a',
  },
  * ────────────────────────────────────────────────────────────────────────── */
];


// ── Home component ─────────────────────────────────────────────────────────
function Home() {
  const { user } = useAuth();

  // Friendly display name: email, phone number, or fallback
  const displayName = user?.email || user?.phone || user?.id || 'Citizen';

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
          {FEATURES.map((feature) => {
            const IconComponent = feature.icon;
            return (
              <Link
                key={feature.path}
                to={feature.path}
                className="home-feature-card card"
                style={{ '--card-accent': feature.color }}
              >
                <div className="home-feature-card__icon-wrap">
                  <IconComponent className="home-feature-card__icon" size={24} strokeWidth={2} />
                </div>
                <div className="home-feature-card__body">
                  <h3 className="home-feature-card__title">{feature.title}</h3>
                  <p className="home-feature-card__desc">{feature.desc}</p>
                </div>
                {/* ──────────────────────────────────────────────────────────────────────────
                 * NOTE: "Module X" badge temporarily hidden from UI. DO NOT DELETE.
                 * Uncomment the line below to restore the module badge on feature cards.
                <span className="home-feature-card__module">Module {feature.module}</span>
                 * ────────────────────────────────────────────────────────────────────────── */}
              </Link>
            );
          })}
        </div>
      </section>

    </div>
  );
}

export default Home;
