// S2 · Verify email. One gate, one task, one escape.
//
// WHAT THIS SCREEN DOES NOT DO
// ----------------------------
// It does not decide anything. It does not know the code, check the code,
// count attempts, or judge whether one has expired. It posts six digits and
// renders what the backend answers. Every rule lives in auth_service, because
// a check the client performs is a check an attacker skips.
//
// The one thing it tracks locally is the resend countdown, and that is a
// DISPLAY of a rule the server also enforces: pressing the button early is
// refused by the backend with the seconds remaining, which is what seeds the
// clock. The countdown is a courtesy, never the control.

import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../api/client.js';
import { useAuth } from '../auth/AuthContext.jsx';
import { ErrorBanner, SuccessBanner } from '../components/States.jsx';
import { Notice } from '../components/ui.jsx';
import StepList from '../components/StepList.jsx';
import { ONBOARDING_STEPS } from '../components/onboarding.js';

const LENGTH = 6;
const RESEND_SECONDS = 60;

// Only digits, only six of them. Applied to typing AND pasting, so a code
// copied with a stray space or a zero-width character still lands.
function clean(value) {
  return (value ?? '').replace(/\D/g, '').slice(0, LENGTH);
}

export default function VerifyEmail() {
  const { user, refresh, logout } = useAuth();
  const [digits, setDigits] = useState('');
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [busy, setBusy] = useState(false);
  const [resending, setResending] = useState(false);
  const [cooldown, setCooldown] = useState(0);
  const [done, setDone] = useState(false);
  const boxRef = useRef(null);

  // One interval for the countdown, cleared when it reaches zero.
  useEffect(() => {
    if (cooldown <= 0) return undefined;
    const tick = setInterval(() => setCooldown((n) => Math.max(0, n - 1)), 1000);
    return () => clearInterval(tick);
  }, [cooldown]);

  const submit = useCallback(async (code) => {
    if (busy || code.length !== LENGTH) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await api.post('/auth/verify-email', { email: user?.email, code });
      // Say so before leaving: a screen that simply vanishes leaves people
      // unsure whether it worked.
      setDone(true);
      await refresh();
    } catch (err) {
      setError(err);
      setDigits('');
      boxRef.current?.focus();
    } finally {
      setBusy(false);
    }
  }, [busy, refresh, user?.email]);

  function onChange(event) {
    const next = clean(event.target.value);
    setDigits(next);
    // Six digits is the whole input; waiting for a button press after the last
    // one is a keystroke nobody needs.
    if (next.length === LENGTH) submit(next);
  }

  async function resend() {
    if (resending || cooldown > 0) return;
    setError(null);
    setNotice(null);
    setResending(true);
    try {
      const data = await api.post('/auth/resend-verification');
      setDigits('');
      setCooldown(data?.resend_after_seconds ?? RESEND_SECONDS);
      setNotice(data?.email_delivered === false
        // Truthful: on a build with no provider configured, "check your inbox"
        // would send someone to look for a message that does not exist.
        ? 'A new code was generated. This build is not connected to an email provider, so it was not sent.'
        : `We sent a new code to ${user?.email}.`);
      boxRef.current?.focus();
    } catch (err) {
      // The backend owns the cooldown; if it refuses, adopt its number.
      const wait = err?.details?.retry_after_seconds;
      if (wait) setCooldown(wait);
      else setError(err);
    } finally {
      setResending(false);
    }
  }

  const expired = error?.details?.reason === 'expired';
  const remaining = error?.details?.attempts_remaining;

  if (done) {
    return (
      <div className="gate">
        <div className="gate__card stack" role="status">
          <h1 className="t-display">Email verified</h1>
          <p className="t-body">
            <strong className="addr">{user?.email}</strong> is confirmed.
            Taking you to the next step…
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="gate">
      <h1 className="t-display" style={{ marginBottom: 'var(--s5)' }}>Verify your email</h1>
      <div className="gate__card stack">
        <StepList steps={ONBOARDING_STEPS} current="verify_email" />

        <p className="t-body">
          We sent a 6-digit code to{' '}
          <strong className="addr">{user?.email}</strong>. Enter it below to continue.
        </p>

        <SuccessBanner message={notice} onDismiss={() => setNotice(null)} />
        <ErrorBanner message={error} onDismiss={() => setError(null)} />

        <form onSubmit={(e) => { e.preventDefault(); submit(digits); }} className="stack">
          {/* ONE input, not six boxes.
              Six separate inputs look tidier and are worse: they fight paste,
              they confuse screen readers into announcing six unlabelled
              fields, and backspacing across them is a known trap. This is a
              single labelled field, spaced by CSS, that accepts a pasted code
              in one go and autofills from an SMS/mail suggestion. */}
          <div className="otp">
            <label className="otp__label" htmlFor="code">
              6-digit verification code
            </label>
            <input id="code" ref={boxRef} className="otp__input mono"
                   value={digits} onChange={onChange}
                   inputMode="numeric" autoComplete="one-time-code"
                   pattern="[0-9]*" autoFocus
                   aria-describedby="code-hint"
                   aria-invalid={error ? 'true' : undefined}
                   disabled={busy} />
            <p className="otp__hint t-meta" id="code-hint">
              {typeof remaining === 'number' && !expired
                ? `Incorrect code. ${remaining} ${remaining === 1 ? 'try' : 'tries'} left before you need a new one.`
                : 'It expires 10 minutes after it was sent. Paste is fine.'}
            </p>
          </div>

          <button type="submit" className="btn btn--primary btn--block"
                  aria-busy={busy || undefined}
                  disabled={busy || digits.length !== LENGTH}>
            {busy ? 'Verifying…' : 'Verify email'}
          </button>
        </form>

        {/* The two ways out. Resending is the common one, so it reads as an
            action; logging out is quiet. */}
        <div className="row-x stackable">
          <button type="button" className="btn btn--secondary"
                  aria-busy={resending || undefined} onClick={resend}
                  disabled={resending || cooldown > 0}>
            {resending ? 'Sending…'
              : cooldown > 0 ? `Resend in ${cooldown}s`
              : 'Send a new code'}
          </button>
          <button type="button" className="btn btn--quiet" onClick={logout}>Log out</button>
        </div>
        {/* The countdown is announced, not just drawn, so it is not a
            visual-only explanation for a disabled button. */}
        <p className="sr-only" role="status">
          {cooldown > 0 ? `You can request another code in ${cooldown} seconds.` : ''}
        </p>

        <Notice tone="info" label="Not arrived?">
          Check spam, and confirm the address above is the one you meant to use. If it
          is wrong, log out and register again with the right address.
        </Notice>
      </div>
    </div>
  );
}
