/*
 * frontend/src/services/firebase.js
 * ──────────────────────────────────────────────────────────────────────────────
 * LEXIS — Firebase Authentication Client Setup
 *
 * Configures Firebase Web SDK with project environment variables and exports
 * auth helpers for phone verification with reCAPTCHA.
 * ──────────────────────────────────────────────────────────────────────────────
 */

import { initializeApp } from 'firebase/app';
import { getAuth, RecaptchaVerifier, signInWithPhoneNumber } from 'firebase/auth';

const firebaseConfig = {
  apiKey: import.meta.env.VITE_FIREBASE_API_KEY,
  authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN,
  projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID,
  storageBucket: import.meta.env.VITE_FIREBASE_STORAGE_BUCKET,
  messagingSenderId: import.meta.env.VITE_FIREBASE_MESSAGING_SENDER_ID,
  appId: import.meta.env.VITE_FIREBASE_APP_ID,
};

const app = initializeApp(firebaseConfig);
export const auth = getAuth(app);

/**
 * Initializes or resets the Firebase RecaptchaVerifier on a container element.
 * @param {string} containerId Element ID (e.g., 'recaptcha-container')
 * @returns {RecaptchaVerifier}
 */
export function setupRecaptcha(containerId = 'recaptcha-container') {
  if (window.recaptchaVerifier) {
    try {
      window.recaptchaVerifier.clear();
    } catch {
      // Ignore if already cleared
    }
    window.recaptchaVerifier = null;
  }

  window.recaptchaVerifier = new RecaptchaVerifier(auth, containerId, {
    size: 'invisible',
    callback: () => {
      // reCAPTCHA solved — will proceed with phone auth
    },
    'expired-callback': () => {
      // Response expired
    },
  });

  return window.recaptchaVerifier;
}

/**
 * Trigger Firebase Phone OTP request to the target mobile number.
 * @param {string} phoneNumber  E.164 formatted phone number (e.g. +919876543210)
 * @param {string} containerId  reCAPTCHA container DOM ID
 * @returns {Promise<ConfirmationResult>} Confirmation object with .confirm(otp) method
 */
export async function sendFirebaseOtp(phoneNumber, containerId = 'recaptcha-container') {
  const recaptchaVerifier = setupRecaptcha(containerId);
  const confirmationResult = await signInWithPhoneNumber(auth, phoneNumber, recaptchaVerifier);
  return confirmationResult;
}
