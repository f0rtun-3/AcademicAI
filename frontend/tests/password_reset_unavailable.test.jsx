// Password reset is switched off until students can actually receive the
// email (lib/features.js). Every place that offers it says so, the same way,
// and nothing in the frontend can send the reset request.

import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import Login from '../src/pages/Login.jsx';
import ForgotPassword from '../src/pages/ForgotPassword.jsx';
import SettingsPage from '../src/pages/SettingsPage.jsx';
import ProfilePage from '../src/pages/ProfilePage.jsx';
import { api } from '../src/api/client.js';
import { PASSWORD_RESET_AVAILABLE } from '../src/lib/features.js';
import { STUDENT_SESSION, mockApi, renderWithAuth } from './helpers.jsx';

const TITLE = 'Password reset isn’t available yet';
const BODY = /We’re still setting up secure email delivery for AcademicAI\. Password reset will be available once this is ready\./;
const resetCalls = (calls) => calls.filter((c) => /\/auth\/(forgot|reset)-password/.test(c.path));

function authRoutes(route) {
  return renderWithAuth(
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/forgot-password" element={<ForgotPassword />} />
    </Routes>,
    { route, token: null },
  );
}

describe('password reset, while it is unavailable', () => {
  it('is switched off', () => {
    expect(PASSWORD_RESET_AVAILABLE).toBe(false);
  });

  it('the Forgot password page explains, and asks for nothing', async () => {
    const calls = mockApi({ '/auth/me': { __status: 401 } });
    authRoutes('/forgot-password');
    expect(await screen.findByRole('heading', { level: 1, name: TITLE })).toBeInTheDocument();
    expect(document.body.textContent).toMatch(BODY);
    expect(screen.getByText('Your password hasn’t changed')).toBeInTheDocument();
    // No email to enter, no stages, no pretend "sent".
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/email/i)).not.toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/check your email|on its way|reset code|if an account exists/i);
    expect(resetCalls(calls)).toEqual([]);
  });

  it('the frontend cannot send a reset request at all', async () => {
    const calls = mockApi({ 'POST /auth/forgot-password': { status: 'sent' } });
    await expect(api.post('/auth/forgot-password', { email: 'a@b.edu' }))
      .rejects.toMatchObject({ status: 503, code: 'unavailable' });
    await expect(api.post('/auth/reset-password', { token: 'x', password: 'y' }))
      .rejects.toMatchObject({ status: 503 });
    expect(resetCalls(calls)).toEqual([]);          // nothing left the browser
  });

  it('Sign in → Forgot password → Back to sign in', async () => {
    const calls = mockApi({ '/auth/me': { __status: 401 } });
    authRoutes('/login');
    const user = userEvent.setup();
    // The link stays on the sign-in page: the feature is planned, not gone.
    await user.click(await screen.findByRole('link', { name: 'Forgot your password?' }));
    expect(await screen.findByRole('heading', { level: 1, name: TITLE })).toBeInTheDocument();
    await user.click(screen.getByRole('link', { name: 'Back to sign in' }));
    expect(await screen.findByRole('heading', { level: 1, name: 'Sign in' })).toBeInTheDocument();
    expect(resetCalls(calls)).toEqual([]);
  });

  it('Settings says it is unavailable, and its control opens the same explanation', async () => {
    const calls = mockApi({ '/auth/me': STUDENT_SESSION });
    renderWithAuth(<SettingsPage />);
    const user = userEvent.setup();
    const button = await screen.findByRole('button', { name: 'Reset password' });
    expect(screen.getByText('Currently unavailable')).toBeInTheDocument();
    expect(button).toHaveAttribute('aria-expanded', 'false');
    await user.click(button);
    expect(button).toHaveAttribute('aria-expanded', 'true');
    const note = screen.getByRole('region', { name: TITLE });
    expect(note).toHaveTextContent(BODY);
    expect(within(note).queryByRole('textbox')).not.toBeInTheDocument();
    expect(resetCalls(calls)).toEqual([]);
  });

  it('Profile behaves the same way', async () => {
    const calls = mockApi({ '/auth/me': STUDENT_SESSION });
    renderWithAuth(<ProfilePage />);
    const user = userEvent.setup();
    const button = await screen.findByRole('button', { name: 'Reset password' });
    expect(screen.getByText('Currently unavailable')).toBeInTheDocument();
    await user.click(button);
    await waitFor(() => expect(screen.getByRole('region', { name: TITLE })).toHaveTextContent(BODY));
    expect(resetCalls(calls)).toEqual([]);
  });
});

// The switch is what hides the flow; the flow itself is kept. With it on, the
// original first step - asking for the email - is what renders.
describe('the reset flow is still in the code', () => {
  it('returns when the switch is turned on', async () => {
    vi.resetModules();
    vi.doMock('../src/lib/features.js', () => ({
      PASSWORD_RESET_AVAILABLE: true, PASSWORD_RESET_PATHS: new Set(),
    }));
    const { default: Flow } = await import('../src/pages/ForgotPassword.jsx');
    mockApi({ '/auth/me': { __status: 401 } });
    renderWithAuth(<Flow />, { token: null });
    expect(await screen.findByLabelText('Student email')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Email me a reset code' })).toBeInTheDocument();
    vi.doUnmock('../src/lib/features.js');
    vi.resetModules();
  });
});
