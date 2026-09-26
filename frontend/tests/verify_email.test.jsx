// The email verification screen.
//
// The rule these protect is mostly an ABSENCE: this screen contains no
// verification logic. It does not know the code, does not check its shape
// against anything the server would accept, does not decide that a code has
// expired, and does not count attempts. It posts six digits and renders the
// answer. The tests below assert that shape - in particular that a wrong code
// is wrong because the SERVER said so, not because the component judged it.

import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import VerifyEmail from '../src/pages/VerifyEmail.jsx';
import { mockApi, renderWithAuth, STUDENT_SESSION } from './helpers.jsx';

const EMAIL = 'bola@student.babcock.edu.ng';

// An account past login but before the gate.
const UNVERIFIED = {
  ...STUDENT_SESSION,
  user: { ...STUDENT_SESSION.user, email: EMAIL, email_verified: false },
  membership: null,
  next_step: 'verify_email',
};

function open(extra = {}) {
  const calls = mockApi({ '/auth/me': UNVERIFIED, ...extra });
  renderWithAuth(<VerifyEmail />);
  return calls;
}

const rejection = (message, details, status = 400) => () => ({
  __status: status, error: 'validation_error', message, details,
});

describe('verify email', () => {
  it('names the address the code was sent to', async () => {
    open();
    expect(await screen.findByText(EMAIL)).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Verify your email' })).toBeInTheDocument();
  });

  it('sends the typed code with the account address', async () => {
    const calls = open({ 'POST /auth/verify-email': { user: {}, next_step: 'community_setup' } });
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText(/6-digit verification code/i), '482917');

    await waitFor(() => {
      const post = calls.find((c) => c.path === '/auth/verify-email');
      expect(post?.body).toEqual({ email: EMAIL, code: '482917' });
    });
  });

  it('accepts a pasted code in one go', async () => {
    const calls = open({ 'POST /auth/verify-email': { user: {}, next_step: 'community_setup' } });
    const user = userEvent.setup();
    const field = await screen.findByLabelText(/6-digit verification code/i);
    field.focus();
    await user.paste('482917');

    await waitFor(() => {
      expect(calls.find((c) => c.path === '/auth/verify-email')?.body.code).toBe('482917');
    });
  });

  it('strips spaces and stray characters out of a pasted code', async () => {
    // Mail clients break a code across a line, or paste it with a space.
    const calls = open({ 'POST /auth/verify-email': { user: {}, next_step: 'community_setup' } });
    const user = userEvent.setup();
    const field = await screen.findByLabelText(/6-digit verification code/i);
    field.focus();
    await user.paste('482 917');

    await waitFor(() => {
      expect(calls.find((c) => c.path === '/auth/verify-email')?.body.code).toBe('482917');
    });
  });

  it('will not submit fewer than six digits', async () => {
    const calls = open({ 'POST /auth/verify-email': { user: {} } });
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText(/6-digit verification code/i), '4829');

    expect(screen.getByRole('button', { name: 'Verify email' })).toBeDisabled();
    expect(calls.find((c) => c.path === '/auth/verify-email')).toBeUndefined();
  });

  it('shows the success state before moving on', async () => {
    open({ 'POST /auth/verify-email': { user: {}, next_step: 'community_setup' } });
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText(/6-digit verification code/i), '482917');

    expect(await screen.findByRole('heading', { name: 'Email verified' })).toBeInTheDocument();
  });

  // ── Failures are the server's verdict, never the component's ────────────

  it('reports an incorrect code and the tries left, from the response', async () => {
    open({
      'POST /auth/verify-email': rejection('That code is not correct.',
        { reason: 'incorrect', attempts_remaining: 3 }),
    });
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText(/6-digit verification code/i), '111111');

    expect(await screen.findByText(/That code is not correct/)).toBeInTheDocument();
    // The count is the server's number, echoed — not computed here.
    expect(screen.getByText(/3 tries left/)).toBeInTheDocument();
  });

  it('distinguishes an expired code from an incorrect one', async () => {
    open({
      'POST /auth/verify-email': rejection('That code has expired. Request a new one.',
        { reason: 'expired' }),
    });
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText(/6-digit verification code/i), '482917');

    // The banner carries the verdict; the hint keeps describing the rule
    // rather than repeating the sentence above it.
    expect(await screen.findByText(/That code has expired. Request a new one./))
      .toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Send a new code' })).toBeEnabled();
  });

  it('clears the field after a rejection so the next try starts clean', async () => {
    open({
      'POST /auth/verify-email': rejection('That code is not correct.',
        { reason: 'incorrect', attempts_remaining: 4 }),
    });
    const user = userEvent.setup();
    const field = await screen.findByLabelText(/6-digit verification code/i);
    await user.type(field, '111111');

    await waitFor(() => expect(field).toHaveValue(''));
    expect(field).toHaveAttribute('aria-invalid', 'true');
  });

  it('never judges a code by itself', async () => {
    // The server accepts a code the component has no reason to like. If any
    // client-side validation existed, this would not reach the endpoint.
    const calls = open({ 'POST /auth/verify-email': { user: {}, next_step: 'community_setup' } });
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText(/6-digit verification code/i), '000000');

    await waitFor(() => {
      expect(calls.find((c) => c.path === '/auth/verify-email')?.body.code).toBe('000000');
    });
    expect(await screen.findByRole('heading', { name: 'Email verified' })).toBeInTheDocument();
  });

  // ── Resend ──────────────────────────────────────────────────────────────

  it('requests a new code and starts the countdown the server specified', async () => {
    const calls = open({
      'POST /auth/resend-verification': { status: 'sent', resend_after_seconds: 60,
                                          email_delivered: true },
    });
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Send a new code' }));

    expect(calls.find((c) => c.path === '/auth/resend-verification')).toBeTruthy();
    const button = await screen.findByRole('button', { name: /Resend in 60s/ });
    expect(button).toBeDisabled();
    expect(screen.getByText(new RegExp(`We sent a new code to ${EMAIL}`))).toBeInTheDocument();
  });

  it('adopts the backend cooldown when it refuses an early resend', async () => {
    // The countdown on screen is a courtesy; the server owns the rule, and
    // when the two disagree the server wins.
    open({
      'POST /auth/resend-verification': rejection('Please wait 42 seconds.',
        { retry_after_seconds: 42 }, 429),
    });
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Send a new code' }));

    expect(await screen.findByRole('button', { name: /Resend in 42s/ })).toBeDisabled();
  });

  it('does not claim an email was sent when the backend says it was not', async () => {
    open({
      'POST /auth/resend-verification': { status: 'sent', resend_after_seconds: 60,
                                          email_delivered: false },
    });
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Send a new code' }));

    expect(await screen.findByText(/not connected to an email provider/)).toBeInTheDocument();
    expect(screen.queryByText(/We sent a new code/)).not.toBeInTheDocument();
  });

  // ── Accessibility ───────────────────────────────────────────────────────

  it('labels the field and describes the rule', async () => {
    open();
    const field = await screen.findByLabelText(/6-digit verification code/i);
    expect(field).toHaveAttribute('inputMode', 'numeric');
    expect(field).toHaveAttribute('autoComplete', 'one-time-code');
    expect(field).toHaveAccessibleDescription(/expires 10 minutes/i);
  });
});
