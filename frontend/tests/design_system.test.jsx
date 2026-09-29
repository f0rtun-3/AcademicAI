// The design system's load-bearing rules, as tests.
//
// These are not styling assertions. Each one pins a rule that the corrected
// specification calls non-negotiable, because each is a place where a
// plausible-looking interface would mislead a student.

import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { Completion, StateChip, Tally, stateLabel } from '../src/components/ui.jsx';
import { errorText } from '../src/components/States.jsx';
import SettingsPage from '../src/pages/SettingsPage.jsx';
import ProfilePage from '../src/pages/ProfilePage.jsx';
import EventDetailPage from '../src/pages/EventDetailPage.jsx';
import { mockApi, renderAtRoute, renderWithAuth, REP_SESSION, STUDENT_SESSION }
  from './helpers.jsx';

function openEvent(event, session, history = []) {
  mockApi({ '/auth/me': session, '/events/7': { event, history } });
  return renderAtRoute('/events/:eventId', <EventDetailPage />, { route: '/events/7' });
}

class Refused extends Error {
  constructor(status, message, serverMessage = message) {
    super(message);
    this.status = status;
    this.serverMessage = serverMessage;
  }
}

// ── C·1 · the chip is a reading of state ──────────────────────────────────
describe('state chips', () => {
  it('renders the student-facing label, so what is read and announced are the same', () => {
    render(<StateChip value="DEADLINE_MOVED" />);
    // The DOM text IS the label: a screen reader, a test and the eye all get
    // "Deadline moved", never the stored token.
    expect(screen.getByText('Deadline moved')).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/DEADLINE|_/);
  });

  it('never implies a reviewer for NEEDS_REVIEW', () => {
    render(<StateChip value="NEEDS_REVIEW" />);
    const chip = screen.getByText('Not confirmed');
    expect(chip).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/review/i);
  });

  it('drops the dot on terminal states and keeps it on live ones', () => {
    const { container } = render(<><StateChip value="ARCHIVED" /><StateChip value="OPEN" /></>);
    const [archived, open] = container.querySelectorAll('.chip');
    expect(archived.className).toContain('chip--none');
    expect(open.className).not.toContain('chip--none');
  });

  it('has no COMPLETED BY YOU state — completion is not a status (C·2)', () => {
    expect(stateLabel('COMPLETED_BY_YOU')).toBe('Completed by you');
    // ...but it is never rendered as one: the marker names its own scope.
    const { container } = render(<Completion done />);
    expect(container.querySelector('.chip')).toBeNull();
    expect(screen.getByText(/only you can see this/i)).toBeInTheDocument();
  });
});

// ── C·5 · business-rule copy verbatim, transport copy framed ──────────────
describe('error copy', () => {
  it('renders a business-rule refusal verbatim', () => {
    const refusal = 'Only a verified course rep can publish official information.';
    expect(errorText(new Refused(403, refusal))).toBe(refusal);
    expect(errorText(new Refused(409, 'This course still has 1 scheduled event.')))
      .toBe('This course still has 1 scheduled event.');
  });

  it('keeps a backend sentence on a framed status and adds the guarantee', () => {
    const text = errorText(new Refused(503, 'The AI service is temporarily unavailable.'));
    expect(text).toMatch(/temporarily unavailable/);
    expect(text).toMatch(/Nothing was changed/);
  });

  it('frames a transport failure that carries no sentence', () => {
    const bare = new Refused(500, 'x', null);
    expect(errorText(bare, 'write')).toMatch(/may not have been saved/);
    // A failed READ cannot have half-applied a write, so it must not say so.
    expect(errorText(bare, 'read')).toMatch(/Nothing was changed/);
    expect(errorText(bare, 'read')).not.toMatch(/may not have been saved/);
  });
});

// ── 11 · the tally shows the shortfall, not just the count ────────────────
describe('tally', () => {
  it('states how many more votes are needed to count', () => {
    render(<Tally yes={1} no={1} needed={3} />);
    expect(screen.getByText(/1 more vote needed to count/)).toBeInTheDocument();
  });

  it('says the minimum is met once enough have voted', () => {
    render(<Tally yes={3} no={0} needed={3} />);
    expect(screen.getByText(/Minimum met/)).toBeInTheDocument();
  });

  it('announces the tally to screen readers as a sentence', () => {
    render(<Tally yes={2} no={1} needed={3} />);
    expect(screen.getByText('2 yes, 1 no, 3 votes needed.')).toBeInTheDocument();
  });
});

// ── C·2 · personal completion never enters the official state column ──────
describe('personal completion', () => {
  const EVENT = {
    id: 7, course_id: 1, course_code: 'COS202', event_type: 'ASSIGNMENT',
    title: 'COS202 Assignment', event_date: '2099-09-18', event_time: null,
    venue: 'LT1', priority: 'NORMAL', status: 'CANCELLED', version: 1,
    original_message: null, created_at: '2026-09-15', completed: true,
  };

  it('keeps the official chip and scopes the marker, even when completed', async () => {
    const { container } = openEvent(EVENT, STUDENT_SESSION);
    await screen.findByRole('heading', { name: 'COS202 Assignment' });
    // Completion never suppresses official state: the header chip still says
    // the event was cancelled...
    expect(container.querySelector('.chip')).toHaveTextContent('Cancelled');
    // ...and a completion recorded earlier is still shown, scoped to the reader.
    expect(screen.getByText(/only you can see this/i)).toBeInTheDocument();
    // A cancelled event asks nothing of the student, so it offers no way to
    // complete it or set a reminder for it.
    expect(screen.queryByRole('button', { name: /Mark/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Add a reminder' })).not.toBeInTheDocument();
  });

  it('gives a student no cancel or edit control, absent rather than disabled', async () => {
    openEvent({ ...EVENT, status: 'SCHEDULED', completed: false }, STUDENT_SESSION);
    await screen.findByRole('heading', { name: 'COS202 Assignment' });
    expect(screen.queryByRole('button', { name: 'Cancel event' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Edit' })).not.toBeInTheDocument();
    // The student's primary action is their own reminder.
    expect(screen.getByRole('button', { name: 'Add a reminder' })).toBeInTheDocument();
  });

  it('offers a rep the cancel control behind a consequence dialog', async () => {
    openEvent({ ...EVENT, status: 'SCHEDULED' }, REP_SESSION);
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Cancel event' }));

    const dialog = await screen.findByRole('dialog');
    expect(dialog).toHaveTextContent(/students? enrolled on this course is notified/i);
    expect(dialog).toHaveTextContent(/history is never deleted/i);
  });
});

// ── S16 · Profile and Settings ────────────────────────────────────────────
describe('profile', () => {
  it('says Matric Number, never Student ID, and never overstates the check', async () => {
    mockApi({ '/auth/me': { ...STUDENT_SESSION,
                            user: { ...STUDENT_SESSION.user, student_id_number: 'BU/SEN/0001' } } });
    renderWithAuth(<ProfilePage />);
    expect(await screen.findByText('Matric number')).toBeInTheDocument();
    expect(screen.getByText('BU/SEN/0001')).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/student id/i);
    expect(document.body.textContent).toMatch(/has not otherwise confirmed your identity/i);
  });

  it('claims only that the email was verified, never an identity', async () => {
    // Student ID-card verification is out of MVP scope. The profile must say
    // what was actually established and nothing more, and must not show a
    // status the product no longer produces.
    mockApi({ '/auth/me': STUDENT_SESSION });
    renderWithAuth(<ProfilePage />);
    // The one claim, stated beside what it does NOT mean.
    await screen.findByText(/What “verified” means/);
    const body = document.body.textContent;
    expect(body).toMatch(/email address has been verified/i);
    expect(body).not.toMatch(/identity verified|identity has been verified/i);
    expect(body).not.toMatch(/ID card|student ID card|upload|scan/i);
    // No Identity row at all, so nothing can be read as a second status.
    expect(screen.queryByText('Identity')).not.toBeInTheDocument();
  });

  it('shows the Matric Number as profile data, never as verified', async () => {
    // MVP SCOPE: nothing verifies it. It may be displayed (the student owns
    // it) but must carry no Verified/Confirmed/University-verified label.
    mockApi({ '/auth/me': { ...STUDENT_SESSION,
                            user: { ...STUDENT_SESSION.user, student_id_number: '21/1234' } } });
    renderWithAuth(<ProfilePage />);
    const value = await screen.findByText('21/1234');
    expect(value).toBeInTheDocument();
    // It sits in the academic record with the other self-declared profile
    // fields, away from anything that says what was verified.
    const academic = value.closest('.pblock');
    expect(academic.textContent).toMatch(/Academic record/);
    expect(academic.textContent).not.toMatch(/verified|confirmed|validated/i);
  });

  it('keeps the academic block read-only and points at transfer (J·6)', async () => {
    mockApi({ '/auth/me': STUDENT_SESSION });
    renderWithAuth(<ProfilePage />);
    // Said on the block itself, and the way to change it is a transfer.
    expect(await screen.findByText('Read-only')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'requesting a transfer' })).toBeInTheDocument();
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
  });
});

describe('settings', () => {
  it('states the consequences before the email can be changed (J·3)', async () => {
    mockApi({ '/auth/me': STUDENT_SESSION });
    const user = userEvent.setup();
    renderWithAuth(<SettingsPage />);

    await user.click(await screen.findByRole('button', { name: 'Change email' }));
    expect(screen.getByText(/verification is cleared/i)).toBeInTheDocument();
    expect(screen.getByText(/Every session is signed out, including this one/i))
      .toBeInTheDocument();
  });

  it('sends the change and explains the sign-out as the rule working', async () => {
    const calls = mockApi({
      '/auth/me': STUDENT_SESSION,
      'POST /auth/change-email': {
        user: { ...STUDENT_SESSION.user, email: 'moved@student.babcock.edu.ng',
                email_verified: false },
        email_verified: false, sessions_revoked: true, next_step: 'verify_email',
      },
    });
    const user = userEvent.setup();
    renderWithAuth(<SettingsPage />);

    await user.click(await screen.findByRole('button', { name: 'Change email' }));
    await user.type(screen.getByLabelText('New student email'),
                    'moved@student.babcock.edu.ng');
    await user.click(screen.getByRole('button', { name: 'Change email' }));

    expect(await screen.findByText(/Verify your new address/i)).toBeInTheDocument();
    const call = calls.find((c) => c.path === '/auth/change-email' && c.method === 'POST');
    expect(call.body.email).toBe('moved@student.babcock.edu.ng');
  });

  it('relays a domain refusal verbatim rather than deciding locally', async () => {
    mockApi({
      '/auth/me': STUDENT_SESSION,
      'POST /auth/change-email': () => ({
        __status: 400, error: 'validation_error',
        message: 'That email domain is not approved for Babcock University.',
      }),
    });
    const user = userEvent.setup();
    renderWithAuth(<SettingsPage />);

    await user.click(await screen.findByRole('button', { name: 'Change email' }));
    await user.type(screen.getByLabelText('New student email'), 'fortune@gmail.com');
    await user.click(screen.getByRole('button', { name: 'Change email' }));

    expect(await screen.findByText(/not approved for Babcock University/)).toBeInTheDocument();
  });

  it('has no notification preferences (J·1) and no password field (J·2)', async () => {
    mockApi({ '/auth/me': STUDENT_SESSION });
    renderWithAuth(<SettingsPage />);
    await screen.findByText('Settings');
    expect(document.body.textContent).not.toMatch(/notification/i);
    expect(screen.queryByLabelText(/new password/i)).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Reset password' })).toBeInTheDocument();
  });
});

// ── 17 · Accessibility rules that are easy to lose in a refactor ──────────
describe('modal accessibility', () => {
  it('traps Tab, closes on Escape and returns focus to the trigger', async () => {
    openEvent({
      id: 7, course_id: 1, course_code: 'COS202', event_type: 'ASSIGNMENT',
      title: 'COS202 Assignment', event_date: '2099-09-18', event_time: null,
      venue: 'LT1', priority: 'NORMAL', status: 'SCHEDULED', version: 1,
      original_message: null, created_at: '2026-09-15', completed: false,
    }, REP_SESSION);
    const user = userEvent.setup();

    const trigger = await screen.findByRole('button', { name: 'Cancel event' });
    await user.click(trigger);

    const dialog = await screen.findByRole('dialog');
    expect(dialog).toHaveAttribute('aria-modal', 'true');
    // Tab cycles inside the dialog rather than escaping to the page behind it.
    await user.tab();
    expect(dialog.contains(document.activeElement)).toBe(true);
    await user.tab();
    expect(dialog.contains(document.activeElement)).toBe(true);

    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(document.activeElement).toBe(trigger);
  });
});

// ── Dates must not depend on the reader's timezone or browser locale ──────
describe('dates', () => {
  it('writes day before month, whatever the runtime locale', async () => {
    const { longDate } = await import('../src/components/ui.jsx');
    expect(longDate('2026-09-18')).toBe('Friday 18 September 2026');
  });

  it('derives today from the local date, not from UTC', async () => {
    const { todayISO } = await import('../src/components/ui.jsx');
    // 00:30 local on the 15th is still the 14th in UTC; "today" must be the
    // 15th, or a student checking after midnight sees tomorrow's agenda.
    const justAfterMidnight = new Date(2026, 8, 15, 0, 30, 0);
    expect(todayISO(justAfterMidnight)).toBe('2026-09-15');
  });
});
