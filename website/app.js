// mail2pay landing page — Clerk sign-up / sign-in wiring.
//
// The Clerk publishable key is injected via `config.js`, which is written
// from a GitHub Actions secret at deploy time. Locally, copy
// `config.example.js` to `config.js` and fill in a development key.
//
// Reference: https://clerk.com/docs/quickstarts/javascript

import { Clerk } from 'https://cdn.jsdelivr.net/npm/@clerk/clerk-js@5/+esm';

const config = window.CLERK_CONFIG || {};
const publishableKey = config.publishableKey;

const signedOut = document.getElementById('signed-out');
const signedIn = document.getElementById('signed-in');
const loading = document.getElementById('loading');
const signUpBtn = document.getElementById('sign-up-btn');
const signInBtn = document.getElementById('sign-in-btn');
const signUpMount = document.getElementById('clerk-sign-up');
const signInMount = document.getElementById('clerk-sign-in');
const userButtonMount = document.getElementById('user-button');

function showError(message) {
  loading.hidden = false;
  signedOut.hidden = true;
  signedIn.hidden = true;
  loading.innerHTML = `<p style="color:#f87171">${message}</p>`;
}

if (!publishableKey || publishableKey.startsWith('pk_REPLACE')) {
  showError(
    'Clerk publishable key missing. Copy website/config.example.js to ' +
      'website/config.js and set your key, or configure the ' +
      'CLERK_PUBLISHABLE_KEY repository secret for deploys.'
  );
} else {
  init(publishableKey).catch((err) => {
    console.error(err);
    showError('Failed to load Clerk. Check your publishable key and network.');
  });
}

async function init(key) {
  const clerk = new Clerk(key);
  await clerk.load();

  render(clerk);
  clerk.addListener(() => render(clerk));

  signUpBtn.addEventListener('click', () => {
    signUpMount.innerHTML = '';
    clerk.mountSignUp(signUpMount);
  });
  signInBtn.addEventListener('click', () => {
    signInMount.innerHTML = '';
    clerk.mountSignIn(signInMount);
  });
}

function render(clerk) {
  loading.hidden = true;
  if (clerk.user) {
    signedOut.hidden = true;
    signedIn.hidden = false;
    userButtonMount.innerHTML = '';
    clerk.mountUserButton(userButtonMount);
  } else {
    signedOut.hidden = false;
    signedIn.hidden = true;
  }
}
