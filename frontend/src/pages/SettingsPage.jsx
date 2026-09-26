// S16 · Settings — deliberately thin: two account actions and log out.
//
// Per J·1 there is no notifications section: the MVP is email-only and there
// is nothing to configure. Per J·2 there is no authenticated password change,
// only a reset emailed to the address on the account.
//
// Changing an email (J·3) re-runs institutional-domain validation, clears
// email_verified and revokes EVERY session including this one. The caller logs
// itself out by its own request. That is the rule working, so the UI says so
// before the button is pressed and handles the sign-out as an expected
// outcome rather than an error.

import { useState } from 'react';
import { api } from '../api/client.js';
import { useAuth } from '../auth/AuthContext.jsx';
import { ErrorBanner } from '../components/States.jsx';
import { Field, Notice, PageHeader, Panel } from '../components/ui.jsx';
import ThemeToggle from '../components/ThemeToggle.jsx';

export default function SettingsPage() {
  const { user, logout, refresh } = useAuth();
  const [email, setEmail] = useState('');
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [done, setDone] = useState(false);
  const [resetSent, setResetSent] = useState(false);

  async function changeEmail(event) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.post('/auth/change-email', { email });
      setDone(true);
      // Every session was revoked, this one included. Re-reading the session
      // is what surfaces that, rather than predicting it locally.
      await refresh();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  async function resetPassword() {
    setBusy(true);
    setError(null);
    try {
      await api.post('/auth/forgot-password', { email: user?.email });
      setResetSent(true);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="stack stack--loose">
      <PageHeader
        title="Settings"
        lede="Your account and how AcademicAI looks. Academic details live on your
              profile and change through a community transfer, not here." />

      <ErrorBanner message={error} onDismiss={() => setError(null)} />

      <Panel title="Account">
        <dl className="kv">
          <dt>Email</dt><dd className="mono">{user?.email}</dd>
        </dl>

        {done ? (
          <Notice tone="warn" label="Verify your new address" role="status"
                  style={{ marginTop: 'var(--s4)' }}>
            Your email was changed. It is not verified yet, and every session —
            including this one — was signed out. Check the new address for a
            verification code, then sign in again.
          </Notice>
        ) : !editing ? (
          <button type="button" className="btn btn--secondary"
                  style={{ marginTop: 'var(--s4)' }}
                  onClick={() => setEditing(true)}>
            Change email
          </button>
        ) : (
          <form onSubmit={changeEmail} className="stack" style={{ marginTop: 'var(--s4)' }}>
            <Notice tone="warn" label="Before you change it">
              <ul>
                <li>The new address must be on an approved domain for your university.</li>
                <li>Your email verification is cleared and must be done again.</li>
                <li>Every session is signed out, including this one.</li>
              </ul>
            </Notice>
            <Field id="new-email" label="New student email" type="email" required
                   value={email} onChange={(e) => setEmail(e.target.value)}
                   disabled={busy} />
            <div className="row-x stackable">
              <button type="submit" className="btn btn--primary" disabled={busy}>
                {busy ? 'Changing…' : 'Change email'}
              </button>
              <button type="button" className="btn btn--secondary" disabled={busy}
                      onClick={() => { setEditing(false); setEmail(''); }}>
                Cancel
              </button>
            </div>
          </form>
        )}
      </Panel>

      <Panel title="Password">
        {resetSent ? (
          <Notice tone="info" label="Check your email" role="status">
            If an account exists for {user?.email}, a reset code is on its way.
          </Notice>
        ) : (
          <>
            <p className="t-body">
              We email you a reset link rather than changing a password in place.
            </p>
            <button type="button" className="btn btn--secondary" disabled={busy}
                    style={{ marginTop: 'var(--s4)' }} onClick={resetPassword}>
              Reset password
            </button>
          </>
        )}
      </Panel>

      <Panel title="Appearance">
        {/* The theme control already existed in the rail and the account menu,
            but not on the page actually called Settings. Same component, so
            there is one source of truth for the preference. */}
        <div className="setrow">
          <div>
            <p className="setrow__name">Colour theme</p>
            <p className="prose">
              Light, dark, or whatever your device is set to. Saved in this browser.
            </p>
          </div>
          <ThemeToggle />
        </div>
      </Panel>

      <Panel title="Session">
        <div className="setrow">
          <div>
            <p className="setrow__name">Log out</p>
            <p className="prose">Ends this session on this device only.</p>
          </div>
          <button type="button" className="btn btn--danger" onClick={logout}>Log out</button>
        </div>
      </Panel>
    </div>
  );
}
