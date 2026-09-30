import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
// These fill the whole nine-field sign-up form key by key; under a full
// parallel run that brushes the 5s default, so this file allows longer.
vi.setConfig({ testTimeout: 15000 });
import SignUp from '../src/pages/SignUp.jsx';
import { mockApi, renderWithAuth } from './helpers.jsx';

const REGISTRY = {
  universities: [
    { id: 1, name: 'Babcock University',
      domains: [{ domain: 'student.babcock.edu.ng', domain_type: 'STUDENT' }] },
    { id: 2, name: 'Covenant University',
      domains: [{ domain: 'stu.cu.edu.ng', domain_type: 'STUDENT' }] },
    { id: 3, name: 'University of Ibadan',
      domains: [{ domain: 'stu.ui.edu.ng', domain_type: 'STUDENT' }] },
    { id: 4, name: 'University of Lagos',
      domains: [{ domain: 'unilag.edu.ng', domain_type: 'INSTITUTIONAL' }] },
  ],
};

function setup(routes = {}) {
  const calls = mockApi({ '/universities': REGISTRY, ...routes });
  renderWithAuth(<SignUp />, { token: null });
  return calls;
}

async function fillRequired(user, { email, university }) {
  await user.type(screen.getByLabelText('Full name'), 'Fortune Okala');
  await user.type(screen.getByLabelText('Student email'), email);
  await user.type(screen.getByLabelText('Password'), 'Password123');
  await user.type(screen.getByLabelText('Confirm password'), 'Password123');
  await user.selectOptions(screen.getByLabelText('University'), university);
  await user.type(screen.getByLabelText('Department'), 'Software Engineering');
  await user.type(screen.getByLabelText('Level'), '200');
  await user.type(screen.getByLabelText('Academic session'), '2026/2027');
  await user.type(screen.getByLabelText('Matric Number'), 'BU/SEN/0001');
  // The agreement is part of a complete form.
  await user.click(screen.getByRole('checkbox', { name: /I agree to the Terms/ }));
}

describe('institutional email guidance on sign-up', () => {
  it('explains the requirement without claiming it proves enrolment', async () => {
    setup();
    await screen.findByLabelText('Student email');
    const body = document.body.textContent;
    expect(body).toMatch(/domain must\s+match the university you select/i);
    expect(body).toMatch(/control an email account associated with your university/i);
    // Must not overclaim.
    expect(body).not.toMatch(/currently enrolled/i);
    expect(body).not.toMatch(/proves you are/i);
  });

  it('offers only the universities the backend supports', async () => {
    setup();
    // The field starts as a plain input and becomes a select once the
    // backend registry arrives.
    await waitFor(() =>
      expect(screen.getByLabelText('University').tagName).toBe('SELECT'));
    const select = screen.getByLabelText('University');
    const options = Array.from(select.options).map((o) => o.value).filter(Boolean);
    expect(options).toEqual([
      'Babcock University', 'Covenant University',
      'University of Ibadan', 'University of Lagos',
    ]);
    // The list is fetched, never hardcoded in the component.
    expect(options).not.toContain('Obafemi Awolowo University');
  });

  it('shows the expected domain once a university is chosen', async () => {
    setup();
    const user = userEvent.setup();
    await screen.findByLabelText('University');
    await user.selectOptions(screen.getByLabelText('University'), 'University of Lagos');
    expect(await screen.findByText(/addresses end in @unilag\.edu\.ng/)).toBeInTheDocument();
  });

  it('warns about a mismatched domain before submitting', async () => {
    setup();
    const user = userEvent.setup();
    await screen.findByLabelText('University');
    await user.selectOptions(screen.getByLabelText('University'), 'Babcock University');
    await user.type(screen.getByLabelText('Student email'), 'fortune@gmail.com');

    const warning = await screen.findByRole('status');
    expect(warning).toHaveTextContent(/not approved for Babcock University/);
    expect(warning).toHaveTextContent(/@student\.babcock\.edu\.ng/);
  });

  it('warns when the domain belongs to another supported university', async () => {
    setup();
    const user = userEvent.setup();
    await screen.findByLabelText('University');
    await user.selectOptions(screen.getByLabelText('University'), 'Babcock University');
    await user.type(screen.getByLabelText('Student email'), 'fortune@stu.cu.edu.ng');
    expect(await screen.findByRole('status')).toHaveTextContent(/not approved/);
  });

  it('does not warn when the domain matches', async () => {
    setup();
    const user = userEvent.setup();
    await screen.findByLabelText('University');
    await user.selectOptions(screen.getByLabelText('University'), 'Babcock University');
    await user.type(screen.getByLabelText('Student email'),
                    'fortune@student.babcock.edu.ng');
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });

  it('treats the domain check as case-insensitive, like the backend', async () => {
    setup();
    const user = userEvent.setup();
    await screen.findByLabelText('University');
    await user.selectOptions(screen.getByLabelText('University'), 'Babcock University');
    await user.type(screen.getByLabelText('Student email'),
                    'FORTUNE@STUDENT.BABCOCK.EDU.NG');
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });

  it('still submits a mismatched domain so the backend decides, not the UI', async () => {
    // The warning is guidance. The security control is server-side, so the
    // client must not be the thing that blocks the request.
    const calls = setup({
      'POST /auth/register': { user: { id: 1 }, next_step: 'verify_email' },
    });
    const user = userEvent.setup();
    await screen.findByLabelText('University');
    await fillRequired(user, { email: 'fortune@gmail.com', university: 'Babcock University' });
    await user.click(screen.getByRole('button', { name: /Create account|Creating/ }));

    await waitFor(() => {
      const register = calls.find((c) => c.path === '/auth/register');
      expect(register).toBeTruthy();
      expect(register.body.email).toBe('fortune@gmail.com');
      expect(register.body.university).toBe('Babcock University');
    });
  });

  it('surfaces the backend rejection message', async () => {
    mockApi({ '/universities': REGISTRY });
    globalThis.fetch = (() => {
      const original = globalThis.fetch;
      return async (url, init) => {
        if (String(url).includes('/auth/register')) {
          return new Response(JSON.stringify({
            error: 'validation_error',
            message: 'The email address must use an approved student email domain '
                     + 'for the selected university.',
          }), { status: 400, headers: { 'Content-Type': 'application/json' } });
        }
        return original(url, init);
      };
    })();

    renderWithAuth(<SignUp />, { token: null });
    const user = userEvent.setup();
    await screen.findByLabelText('University');
    await fillRequired(user, { email: 'fortune@gmail.com', university: 'Babcock University' });
    await user.click(screen.getByRole('button', { name: /Create account|Creating/ }));

    expect(await screen.findByText(/approved student email domain/))
      .toBeInTheDocument();
  });

  it('still works if the registry cannot be fetched', async () => {
    // Guidance degrades; registration remains possible and server-validated.
    mockApi({});
    renderWithAuth(<SignUp />, { token: null });
    expect(await screen.findByLabelText('University')).toBeInTheDocument();
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });
});

describe('frontend never treats local state as authority', () => {
  it('surfaces a backend 403 even when the session says the user is a rep', async () => {
    // The UI may show rep controls from server-supplied session state, but the
    // backend remains authoritative: if authority was revoked since the session
    // was fetched, the refusal must reach the user rather than be swallowed.
    const { default: AddMessage } = await import('../src/pages/AddMessage.jsx');
    const { REP_SESSION, COMMUNITY } = await import('./helpers.jsx');

    globalThis.fetch = async (url) => {
      const path = String(url).replace(/^.*\/api/, '');
      if (path === '/auth/me') {
        return new Response(JSON.stringify(REP_SESSION),
          { status: 200, headers: { 'Content-Type': 'application/json' } });
      }
      if (path === '/community') {
        return new Response(JSON.stringify({ community: COMMUNITY, membership: REP_SESSION.membership }),
          { status: 200, headers: { 'Content-Type': 'application/json' } });
      }
      if (path.startsWith('/ai/')) {
        return new Response(JSON.stringify({
          error: 'forbidden',
          message: 'Only a verified course rep can publish official information.',
        }), { status: 403, headers: { 'Content-Type': 'application/json' } });
      }
      return new Response(JSON.stringify({ courses: [], events: [] }),
        { status: 200, headers: { 'Content-Type': 'application/json' } });
    };

    const user = userEvent.setup();
    renderWithAuth(<AddMessage />);
    const box = await screen.findByLabelText(/message/i);
    await user.type(box, 'COS202 assignment due friday');
    await user.click(screen.getByRole('button', { name: /Analyse|Analyze/i }));

    expect(await screen.findByText(/Only a verified course rep/)).toBeInTheDocument();
  });

  it('stores only the auth token locally, never role or verification state', async () => {
    const client = await import('../src/api/client.js');
    client.setToken('abc123');
    const keys = Object.keys(localStorage);
    expect(keys).toEqual(['academicai.token']);
    for (const key of keys) {
      const value = localStorage.getItem(key);
      expect(value).not.toMatch(/VERIFIED_REP|identity_status|email_verified/);
    }
  });
});

describe('what sign-up claims about the Matric Number', () => {
  // MVP SCOPE: there is no ID-card check and no university-records lookup, so
  // the field must not let a student assume it is being verified. The copy is
  // a plain hint, not a warning - see the design system's Field hint slot.

  it('says plainly that the matric number is not verified', async () => {
    setup();
    const field = await screen.findByLabelText('Matric Number');
    const hintId = field.getAttribute('aria-describedby');
    expect(hintId).toBeTruthy();
    const hint = document.getElementById(hintId.split(' ')[0]);
    expect(hint).toHaveTextContent(
      'Your university matric number. AcademicAI does not currently verify this information.');
  });

  it('never claims the matric number is verified or checked anywhere', async () => {
    setup();
    await screen.findByLabelText('Matric Number');
    const body = document.body.textContent;
    expect(body).not.toMatch(/matric number (is )?verified/i);
    expect(body).not.toMatch(/we('| wi)ll (verify|check|confirm)/i);

    // The removed ID-card feature has no vocabulary left anywhere.
    expect(body).not.toMatch(/ID card|upload|scan|photograph/i);

    // "University records" may only appear as a DENIAL, such as the sign-up
    // disclaimer "AcademicAI does not verify identity or university records":
    // every mention must be negated, and at least one denial must be present.
    const mentions = body.match(/.{0,24}(university|student) records/gi) ?? [];
    expect(mentions.length).toBeGreaterThan(0);
    for (const mention of mentions) {
      expect(mention).toMatch(/\b(not|never|no)\b/i);
    }
  });

  it('does not use a real person\'s matric number as the example', async () => {
    // The placeholder is illustrative only; it must not be anyone's actual
    // number, and it is the one a screenshot of sign-up would show.
    setup();
    const field = await screen.findByLabelText('Matric Number');
    expect(field).toHaveAttribute('placeholder', '21/1234');
  });
});
