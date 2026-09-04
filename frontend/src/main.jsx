/*
 * frontend/src/main.jsx
 * ──────────────────────────────────────────────────────────────────────────────
 * LEXIS — Application Entry Point (Module 3)
 *
 * This is the first file Vite runs when the app starts.
 * It does three things:
 *
 *   1. Imports the global CSS (index.css) — styles apply to the whole app.
 *
 *   2. Renders the React application into the <div id="root"> element
 *      in index.html.  Every React component you see in the browser lives
 *      inside that root div.
 *
 *   3. Wraps the app in two "provider" components:
 *
 *      <StrictMode> — a React development tool that detects potential
 *        problems in your code and warns you in the browser console.
 *        It only runs extra checks in development mode — has zero effect
 *        in production builds.
 *
 *      <BrowserRouter> — enables React Router.  It watches the browser URL
 *        and makes routing work.  Must wrap the entire app so that any
 *        component anywhere can use useNavigate(), useParams(), etc.
 *
 *      <AuthProvider> — provides the authentication state (user, tokens,
 *        login/logout) to every component in the app via the useAuth() hook.
 *        It also uses useNavigate() internally, so it must be INSIDE
 *        <BrowserRouter>.
 *
 *      Order matters:
 *        StrictMode (outermost)
 *          BrowserRouter  (provides routing)
 *            AuthProvider  (provides auth — uses Router internally)
 *              App         (defines routes and renders pages)
 * ──────────────────────────────────────────────────────────────────────────────
 */

import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';

import { AuthProvider } from './context/AuthContext';
import App from './App';
import './index.css';   // Global reset + design tokens — imported ONCE here


// ReactDOM.createRoot() — React 18's new rendering API.
// It mounts the React app into the <div id="root"> from index.html.
const rootElement = document.getElementById('root');

ReactDOM.createRoot(rootElement).render(
  <React.StrictMode>
    <BrowserRouter>
      {/* AuthProvider wraps App so every page can call useAuth() */}
      <AuthProvider>
        <App />
      </AuthProvider>
    </BrowserRouter>
  </React.StrictMode>
);
