import { screen, waitFor } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import App from '../src/App.jsx';
import { COMMUNITY, mockApi, renderWithAuth, REP_SESSION } from './helpers.jsx';

describe('onboarding gate', () => {
  it('shows the awaiting-approval state instead of a dashboard that would 403', async () => {
    // spec 9: a student awaiting approval must not be routed to the dashboard.
    mockApi({
      '/auth/me': {
        user: { ...REP_SESSION.user, id: 9, full_name: 'Chidi Student' },
        membership: null,
        pending_membership: { community_id: 1, status: 'PENDING_APPROVAL', role: 'STUDENT' },
        next_step: 'awaiting_approval',
      },
    });
    renderWithAuth(<App />, { route: '/dashboard' });

    expect(await screen.findByText('Waiting for approval')).toBeInTheDocument();
    expect(screen.queryByText(/Welcome back/)).not.toBeInTheDocument();
  });

  it('routes an unverified email to the email verification step', async () => {
    mockApi({
      '/auth/me': {
        user: { ...REP_SESSION.user, email_verified: false },
        membership: null, pending_membership: null, next_step: 'verify_email',
      },
    });
    renderWithAuth(<App />, { route: '/dashboard' });
    expect(await screen.findByRole('heading', { name: 'Verify your email' })).toBeInTheDocument();
  });

  it('never shows the verification step when the deployment does not verify email',
     async () => {
    // With ACADEMICAI_EMAIL_VERIFICATION_REQUIRED=false the backend creates
    // accounts already verified, so next_step is never verify_email and this
    // screen is unreachable. The decision is entirely the backend's: nothing
    // in the client knows the switch exists, which is the point.
    mockApi({
      '/auth/me': {
        user: { ...REP_SESSION.user, email_verified: true },
        membership: null, pending_membership: null, next_step: 'community_setup',
      },
    });
    renderWithAuth(<App />, { route: '/verify-email' });

    await waitFor(() => {
      expect(screen.queryByRole('heading', { name: 'Verify your email' }))
        .not.toBeInTheDocument();
    });
  });

  it('sends an anonymous visitor to login', async () => {
    mockApi({});
    renderWithAuth(<App />, { route: '/dashboard', token: null });
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument();
  });

  it('shows the community-ready message when the community already exists', async () => {
    mockApi({
      '/auth/me': {
        user: REP_SESSION.user, membership: null, pending_membership: null,
        next_step: 'community_setup',
      },
      'POST /community/setup': { community: COMMUNITY, created: false, existed: true,
                                 message: 'Your academic community is ready.' },
    });
    renderWithAuth(<App />, { route: '/community-setup' });
    expect(await screen.findByText('Your academic community is ready.')).toBeInTheDocument();
  });

  it("offers the rep and student choice when the community is new", async () => {
    mockApi({
      '/auth/me': {
        user: REP_SESSION.user, membership: null, pending_membership: null,
        next_step: 'community_setup',
      },
      'POST /community/setup': { community: { ...COMMUNITY, status: 'PENDING' },
                                 created: true, existed: false,
                                 message: "Your academic community hasn't been set up yet." },
    });
    renderWithAuth(<App />, { route: '/community-setup' });
    expect(await screen.findByText(/hasn't been set up yet/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Course Rep/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /I'm a Student/ })).toBeInTheDocument();
  });

  it('sends an email-verified student with no membership to community setup', async () => {
    // Replaces a test that routed to the removed ID-card screen. The backend
    // owns the step; the client only follows it, and there is no longer any
    // step between verifying an email and determining the community.
    mockApi({
      '/auth/me': {
        user: { ...REP_SESSION.user, email_verified: true },
        membership: null, pending_membership: null, next_step: 'community_setup',
      },
      'POST /community/setup': { community: { id: 1, department: 'Software Engineering' },
                                 created: true, existed: false,
                                 message: "Your academic community hasn't been set up yet." },
    });
    renderWithAuth(<App />, { route: '/dashboard' });
    expect(await screen.findByText(/hasn't been set up yet/)).toBeInTheDocument();
  });

  it('never routes anyone to an ID-card screen', async () => {
    mockApi({
      '/auth/me': {
        user: { ...REP_SESSION.user, email_verified: true },
        membership: null, pending_membership: null, next_step: 'community_setup',
      },
      'POST /community/setup': { community: { id: 1, department: 'Software Engineering' },
                                 created: true, existed: false, message: 'x' },
    });
    renderWithAuth(<App />, { route: '/verify-identity' });
    await screen.findByText(/./);
    const body = document.body.textContent;
    expect(body).not.toMatch(/student ID card/i);
    expect(body).not.toMatch(/upload|photograph|scan/i);
  });
});
