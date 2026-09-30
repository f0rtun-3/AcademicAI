// Email verification on or off (ACADEMICAI_EMAIL_VERIFICATION_REQUIRED).
//
// The deployment decides; the backend's register response says which. With it
// off, sign-up tells the student nothing about codes or email and carries on
// to the normal next step. With it on, the existing code flow is unchanged.
// "Off" and "on, but the email could not be sent" are different answers and
// must read differently.

import { fireEvent, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import SignUp from '../src/pages/SignUp.jsx';
import SettingsPage from '../src/pages/SettingsPage.jsx';
import ProfilePage from '../src/pages/ProfilePage.jsx';
import VerifyEmail from '../src/pages/VerifyEmail.jsx';
import { COMMUNITY, STUDENT_SESSION, mockApi, renderWithAuth } from './helpers.jsx';

// Filling the whole sign-up form takes several seconds when the full suite
// shares the machine, as in institutional_email and refinement.
vi.setConfig({ testTimeout: 15000 });

const REGISTRY = { universities: [{ id: 1, name: 'Babcock University',
  domains: [{ domain: 'student.babcock.edu.ng', domain_type: 'STUDENT' }] }] };
const EMAIL = 'ada@student.babcock.edu.ng';
const USER = { id: 9, full_name: 'Ada Student', email: EMAIL };
const CODE_TALK = /check your email|verification code|code was generated|we sent|sent you/i;

// What POST /auth/register answers in each state (auth_routes.register).
const CREATED = {
  off: { __status: 201, user: { ...USER, email_verified: true }, next_step: 'community_setup',
         email_verification_required: false, email_delivered: false },
  on: { __status: 201, user: { ...USER, email_verified: false }, next_step: 'verify_email',
        email_verification_required: true, email_delivered: true, email_backend: 'resend' },
  onButUndelivered: { __status: 201, user: { ...USER, email_verified: false },
                      next_step: 'verify_email', email_verification_required: true,
                      email_delivered: false, email_error: 'provider refused' },
};

const session = (nextStep, verified) => ({
  user: { ...USER, email_verified: verified }, membership: null,
  pending_membership: null, next_step: nextStep, timezone: 'Africa/Lagos',
});

async function fillForm(user) {
  await screen.findByLabelText('University');
  await waitFor(() => expect(screen.getByLabelText('University').tagName).toBe('SELECT'));
  const set = (label, value) => fireEvent.change(screen.getByLabelText(label), { target: { value } });
  set('Full name', 'Ada Student');
  set('Student email', EMAIL);
  set('Password', 'Password123');
  set('Confirm password', 'Password123');
  await user.selectOptions(screen.getByLabelText('University'), 'Babcock University');
  set('Department', 'Software Engineering');
  set('Level', '200');
  set('Academic session', '2026/2027');
  set('Matric Number', '21/1234');
  await user.click(screen.getByRole('checkbox', { name: /^I agree to the Terms & Conditions/ }));
}

// Signs up against a deployment in the given state. Sign-in is held until the
// test releases it, so the notice sign-up shows can be read before the page
// moves on.
async function signUp(created, nextStep, verified) {
  let release;
  const signedIn = new Promise((resolve) => { release = resolve; });
  const calls = mockApi({
    '/universities': REGISTRY,
    'POST /auth/register': created,
    'POST /auth/login': async () => { await signedIn; return { token: 'fresh', user: USER }; },
    '/auth/me': session(nextStep, verified),
  });
  renderWithAuth(
    <Routes>
      <Route path="/signup" element={<SignUp />} />
      <Route path="/" element={<p>Home route</p>} />
      <Route path="/verify-email" element={<p>Verification code screen</p>} />
    </Routes>,
    { route: '/signup', token: null },
  );
  const user = userEvent.setup();
  await fillForm(user);
  await user.click(screen.getByRole('button', { name: 'Create account' }));
  return { calls, release };
}

describe('sign-up with email verification switched off', () => {
  it('says the account is ready - nothing about codes or email', async () => {
    const { release } = await signUp(CREATED.off, 'community_setup', true);
    expect(await screen.findByText('Account created. You can start using AcademicAI right away.'))
      .toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(CODE_TALK);
    release();
  });

  it('continues to the normal next step, never to the code screen', async () => {
    const { calls, release } = await signUp(CREATED.off, 'community_setup', true);
    release();
    expect(await screen.findByText('Home route')).toBeInTheDocument();
    expect(screen.queryByText('Verification code screen')).not.toBeInTheDocument();
    // Signed straight in, and no verification request of any kind was made.
    expect(calls.some((c) => c.path === '/auth/login')).toBe(true);
    expect(calls.filter((c) => /verify|resend/.test(c.path))).toEqual([]);
  });
});

describe('sign-up with email verification switched on (unchanged)', () => {
  it('asks for the code and goes to the code screen', async () => {
    const { release } = await signUp(CREATED.on, 'verify_email', false);
    expect(await screen.findByText('Account created. Check your email for a verification code.'))
      .toBeInTheDocument();
    release();
    expect(await screen.findByText('Verification code screen')).toBeInTheDocument();
    expect(screen.queryByText('Home route')).not.toBeInTheDocument();
  });

  it('a failed send is not "switched off": it says so and still goes to the code screen', async () => {
    const { release } = await signUp(CREATED.onButUndelivered, 'verify_email', false);
    expect(await screen.findByText('Account created. A verification code was generated.'))
      .toBeInTheDocument();
    expect(screen.queryByText(/right away/)).not.toBeInTheDocument();
    release();
    expect(await screen.findByText('Verification code screen')).toBeInTheDocument();
  });
});

// public_user's `email_verification`, as /auth/me reports it.
async function profileFor(emailFields) {
  mockApi({
    '/auth/me': { ...STUDENT_SESSION, user: { ...STUDENT_SESSION.user, ...emailFields } },
    '/community': { community: COMMUNITY },
  });
  renderWithAuth(<ProfilePage />);
  await screen.findByRole('heading', { level: 1, name: STUDENT_SESSION.user.full_name });
}
const WHAT_VERIFIED_MEANS = 'What “verified” means';

describe('the profile says how the email stands', () => {
  it('a code was entered: "Email verified", and what that means', async () => {
    await profileFor({ email_verified: true, email_verification: 'verified' });
    expect(screen.getByText('Email verified')).toBeInTheDocument();
    expect(screen.getByText(WHAT_VERIFIED_MEANS)).toBeInTheDocument();
  });

  it('let through with verification off: "not required", never "verified"', async () => {
    await profileFor({ email_verified: true, email_verification: 'not_required' });
    expect(screen.getByText('Email verification not required')).toBeInTheDocument();
    expect(screen.queryByText('Email verified')).not.toBeInTheDocument();
    expect(screen.queryByText(WHAT_VERIFIED_MEANS)).not.toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/has been verified/);
  });

  it('not verified yet: "Email not verified"', async () => {
    await profileFor({ email_verified: false, email_verification: 'pending' });
    expect(screen.getByText('Email not verified')).toBeInTheDocument();
    expect(screen.queryByText(WHAT_VERIFIED_MEANS)).not.toBeInTheDocument();
  });

  it('a session from before the field still reads from email_verified', async () => {
    await profileFor({ email_verified: true });
    expect(screen.getByText('Email verified')).toBeInTheDocument();
  });
});

// An account created while verification was on, before the code arrived.
const PENDING_SESSION = (required) => ({
  ...session('verify_email', false), email_verification_required: required,
  user: { ...USER, email_verified: false, email_verification: 'pending' },
});

describe('the verification screen', () => {
  it('with verification switched off: says no code was sent, asks for none', async () => {
    const calls = mockApi({ '/auth/me': PENDING_SESSION(false) });
    renderWithAuth(<VerifyEmail />);
    expect(await screen.findByRole('heading', { level: 1, name: 'Your account isn’t active yet' }))
      .toBeInTheDocument();
    expect(document.body.textContent).toMatch(/no code was sent/);
    expect(document.body.textContent).not.toMatch(/We sent/);
    expect(screen.queryByLabelText('6-digit verification code')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Send a new code' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Log out' })).toBeInTheDocument();
    expect(calls.filter((c) => /verify|resend/.test(c.path))).toEqual([]);
  });

  it('with verification on: the existing code screen, unchanged', async () => {
    mockApi({ '/auth/me': PENDING_SESSION(true) });
    renderWithAuth(<VerifyEmail />);
    expect(await screen.findByRole('heading', { level: 1, name: 'Verify your email' }))
      .toBeInTheDocument();
    expect(document.body.textContent).toMatch(/We sent a 6-digit code to/);
    expect(screen.getByLabelText('6-digit verification code')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Send a new code' })).toBeInTheDocument();
  });

  it('a session from before the field keeps the code screen', async () => {
    const { email_verification_required: _omitted, ...older } = PENDING_SESSION(true);
    mockApi({ '/auth/me': older });
    renderWithAuth(<VerifyEmail />);
    expect(await screen.findByRole('heading', { level: 1, name: 'Verify your email' }))
      .toBeInTheDocument();
  });
});

describe('Settings: changing email while verification is switched off', () => {
  it('shows the refusal, keeps the address, and says nothing about a code', async () => {
    // auth_service.change_email's refusal, word for word.
    const REFUSAL = "Changing your email isn't available while email verification is "
      + 'switched off. Your address has not been changed.';
    const calls = mockApi({
      '/auth/me': STUDENT_SESSION,
      'POST /auth/change-email': { __status: 409, error: 'conflict', message: REFUSAL,
                                   details: { email_verification_required: false } },
    });
    renderWithAuth(<SettingsPage />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Change email' }));
    fireEvent.change(screen.getByLabelText('New student email'),
      { target: { value: 'moved@student.babcock.edu.ng' } });
    await user.click(screen.getByRole('button', { name: 'Change email' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(REFUSAL);
    expect(screen.queryByText(/Verify your new address/)).not.toBeInTheDocument();
    expect(screen.queryByText(/verification code, then sign in again/)).not.toBeInTheDocument();
    expect(screen.getByText(STUDENT_SESSION.user.email)).toBeInTheDocument();
    // Nothing to re-read: the session was not touched.
    expect(calls.filter((c) => c.path === '/auth/me')).toHaveLength(1);
  });
});
