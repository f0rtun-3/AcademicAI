// S1 · Forgot password, and the reset it leads to.
//
// Per J·2 there is no authenticated password change: resetting always goes
// through a code emailed to the address on the account. The request response
// is deliberately identical whether or not the account exists, so this screen
// must not report "no such account" — the backend does not tell it, and
// inventing that answer would leak who is registered.
//
// Unchanged from the previous version: both endpoints, the three stages, and
// the wording of the "if an account exists" notice. New: the shared auth
// composition, a stage indicator so the two-step reset does not feel like a
// dead end, and password fields with a visibility control.

import { useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api/client.js';
import AuthLayout from '../components/AuthLayout.jsx';
import { ErrorBanner } from '../components/States.jsx';
import { Field, Notice, PasswordInput } from '../components/ui.jsx';
import StepList from '../components/StepList.jsx';

const STAGES = [
  { id: 'request', label: 'Your email' },
  { id: 'sent', label: 'New password' },
  { id: 'done', label: 'Done' },
];

export default function ForgotPassword() {
  const [stage, setStage] = useState('request');
  const [email, setEmail] = useState('');
  const [form, setForm] = useState({ token: '', password: '', confirm_password: '' });
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  async function request(event) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.post('/auth/forgot-password', { email });
      setStage('sent');
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  async function reset(event) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.post('/auth/reset-password', form);
      setStage('done');
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  const subtitle = {
    request: 'We will email a reset code to the address on your account.',
    sent: 'Enter the code we emailed you, then choose a new password.',
    done: null,
  }[stage];

  return (
    <AuthLayout
      title="Reset your password"
      subtitle={subtitle}
      preview={false}
      pitch="Locked out?"
      blurb="Resetting always goes through the email address on the account — there
             is no way to change a password without it."
      footer={<><Link to="/login">Back to sign in</Link></>}
    >
      <StepList steps={STAGES} current={stage} />

      <ErrorBanner message={error} onDismiss={() => setError(null)} />

      {stage === 'request' && (
        <form onSubmit={request} className="stack">
          <Field id="reset-email" label="Student email" type="email" required
                 autoComplete="username" value={email}
                 onChange={(e) => setEmail(e.target.value)}
                 hint="We email a reset code to the address on the account." />
          <button type="submit" className="btn btn--primary btn--block" disabled={busy}>
            {busy ? 'Sending…' : 'Email me a reset code'}
          </button>
        </form>
      )}

      {stage === 'sent' && (
        <div className="stack">
          <Notice tone="info" label="Check your email" role="status">
            If an account exists for that address, a reset code is on its way.
            Enter it below with your new password.
          </Notice>
          <form onSubmit={reset} className="stack">
            <Field id="reset-token" label="Reset code" required value={form.token}
                   autoComplete="one-time-code" inputMode="text"
                   onChange={(e) => setForm({ ...form, token: e.target.value })} />
            <PasswordInput id="reset-password" label="New password" required
                           autoComplete="new-password" value={form.password}
                           onChange={(e) => setForm({ ...form, password: e.target.value })} />
            <PasswordInput id="reset-confirm" label="Confirm new password" required
                           autoComplete="new-password" value={form.confirm_password}
                           onChange={(e) => setForm({ ...form, confirm_password: e.target.value })} />
            <button type="submit" className="btn btn--primary btn--block" disabled={busy}>
              {busy ? 'Saving…' : 'Set new password'}
            </button>
          </form>
          <p className="t-meta">
            No code yet?{' '}
            <button type="button" className="linkish" onClick={() => setStage('request')}>
              Send it again
            </button>
          </p>
        </div>
      )}

      {stage === 'done' && (
        <div className="stack">
          <Notice tone="pos" label="Password changed" role="status">
            Your password has been changed and every other session was signed out.
          </Notice>
          <Link className="btn btn--primary btn--block" to="/login">Sign in</Link>
        </div>
      )}
    </AuthLayout>
  );
}
