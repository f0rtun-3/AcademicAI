// UI behaviours pinned by regression tests.
//
// Each block names the failure it guards against: a question lost when Chat
// could not send, a toast stack stuck paused, keyboard focus dropped to the
// top of the page, a form error nowhere near its field, actions offered on a
// cancelled event, Manage links that led somewhere else, and audit-log wording
// on the Community page.

import { useRef, useState } from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Navigate, Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
// These fill the whole nine-field sign-up form key by key; under a full
// parallel run that brushes the 5s default, so this file allows longer.
vi.setConfig({ testTimeout: 15000 });
import ChatPage from '../src/pages/ChatPage.jsx';
import CommunityPage from '../src/pages/CommunityPage.jsx';
import EventDetailPage from '../src/pages/EventDetailPage.jsx';
import RepDashboard from '../src/pages/RepDashboard.jsx';
import SignUp from '../src/pages/SignUp.jsx';
import Layout from '../src/components/Layout.jsx';
import NotificationToasts from '../src/components/NotificationToasts.jsx';
import {
  COMMUNITY, mockApi, renderAtRoute, renderWithAuth, REP_SESSION, STUDENT_SESSION,
} from './helpers.jsx';

const ORIGINAL_TZ = process.env.TZ;
afterEach(() => {
  vi.useRealTimers();
  process.env.TZ = ORIGINAL_TZ;
});

// ── Chat ──────────────────────────────────────────────────────────────────

describe('Chat when a question cannot be sent', () => {
  function chat(postChat) {
    return mockApi({
      '/auth/me': STUDENT_SESSION,
      '/chat/prompts': { prompts: [] },
      '/chat/history': { conversations: [] },
      'POST /chat': postChat,
    });
  }

  it('keeps the question, keeps focus in the box, and offers to try again', async () => {
    let fail = true;
    chat(() => (fail
      ? { __status: 503, error: 'unavailable',
          message: 'The AI service is temporarily unavailable.' }
      : { answer: 'Your next deadline is COS202 Assignment - Friday 18 September.',
          grounded: true, referenced_event_ids: [], suggested_reminder: null,
          conversation_id: 3 }));
    const user = userEvent.setup();
    renderWithAuth(<ChatPage />);

    const input = await screen.findByLabelText('Your question');
    await user.type(input, 'What is my next deadline?');
    await user.click(screen.getByRole('button', { name: 'Ask' }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Your question was not sent');
    expect(alert).toHaveTextContent(/temporarily unavailable/);
    // The words are not destroyed, and the keyboard is still in the box.
    expect(input).toHaveValue('What is my next deadline?');
    expect(input).toHaveFocus();
    expect(input).toBeEnabled();

    fail = false;
    await user.click(within(alert).getByRole('button', { name: 'Try again' }));
    expect(await screen.findByText(/Your next deadline is COS202 Assignment/))
      .toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('says when a suggested reminder would fire, on the university\'s clock', async () => {
    process.env.TZ = 'Europe/London';                  // the device, not Babcock
    chat({
      answer: 'Your next deadline is the COS202 exam - Monday 12 October at 08:00.',
      grounded: true, referenced_event_ids: [7], conversation_id: 4,
      suggested_reminder: { title: 'Prepare for the COS202 exam',
                            remind_at_local: '2026-10-12T08:00',
                            timezone: 'Africa/Lagos', event_id: 7 },
    });
    const user = userEvent.setup();
    renderWithAuth(<ChatPage />);
    await user.type(await screen.findByLabelText('Your question'), 'next deadline');
    await user.click(screen.getByRole('button', { name: 'Ask' }));
    expect(await screen.findByText('Monday 12 October at 08:00')).toBeInTheDocument();
  });

  it('accepts a suggestion as the same university-clock time it offered', async () => {
    process.env.TZ = 'UTC';
    const calls = chat({
      answer: 'Your next deadline is the COS202 exam.', grounded: true,
      referenced_event_ids: [7], conversation_id: 4,
      suggested_reminder: { title: 'Prepare for the COS202 exam',
                            remind_at_local: '2026-10-12T08:00',
                            timezone: 'Africa/Lagos', event_id: 7 },
    });
    const user = userEvent.setup();
    renderWithAuth(<ChatPage />);
    await user.type(await screen.findByLabelText('Your question'), 'next deadline');
    await user.click(screen.getByRole('button', { name: 'Ask' }));
    await user.click(await screen.findByRole('button', { name: 'Add reminder' }));
    await waitFor(() => {
      const call = calls.find((c) => c.path === '/reminders' && c.method === 'POST');
      expect(call.body).toEqual({ title: 'Prepare for the COS202 exam',
                                  remind_at_local: '2026-10-12T08:00', event_id: 7 });
    });
  });
});

// ── Toasts ────────────────────────────────────────────────────────────────

const toast = (id) => ({ id, subject: `Toast ${id}`, body: null, link: null,
                         kindLabel: 'Changed', viewLabel: 'View event' });

// A stack whose dismissals really remove toasts, with a stand-in bell.
function Stack({ initial, expose }) {
  const [toasts, setToasts] = useState(initial);
  const bell = useRef(null);
  expose?.(setToasts);
  return (
    <>
      <button type="button" ref={bell}>Notifications</button>
      <NotificationToasts toasts={toasts} onView={() => {}}
                          returnFocusTo={bell}
                          onDismiss={(id) => setToasts((t) => t.filter((x) => x.id !== id))} />
    </>
  );
}

describe('the toast stack', () => {
  it('stops being paused once the last toast is gone', () => {
    vi.useFakeTimers();
    let setToasts;
    render(<Stack initial={[toast(1)]} expose={(fn) => { setToasts = fn; }} />);
    const region = screen.getByRole('region', { name: 'New notifications' });

    // Pointer over the stack pauses it; dismissing the last toast removes the
    // element the pointer would have left, so no mouseleave ever arrives.
    fireEvent.mouseEnter(region);
    fireEvent.click(screen.getByRole('button', { name: 'Dismiss Toast 1' }));
    expect(region.querySelectorAll('.toast')).toHaveLength(0);

    // The next toast must still auto-dismiss.
    act(() => { setToasts([toast(2)]); });
    expect(screen.getByText('Toast 2')).toBeInTheDocument();
    act(() => { vi.advanceTimersByTime(7000); });
    expect(screen.queryByText('Toast 2')).not.toBeInTheDocument();
  });

  it('moves focus to the next toast, then back to the bell, as toasts are dismissed', () => {
    render(<Stack initial={[toast(1), toast(2)]} />);
    const first = screen.getByRole('button', { name: 'Dismiss Toast 1' });
    first.focus();
    fireEvent.click(first);
    expect(screen.getByRole('button', { name: 'Dismiss Toast 2' })).toHaveFocus();

    fireEvent.click(screen.getByRole('button', { name: 'Dismiss Toast 2' }));
    expect(screen.getByRole('button', { name: 'Notifications' })).toHaveFocus();
  });
});

// ── Sign-up errors belong to their field ──────────────────────────────────

const REGISTRY = { universities: [{ id: 1, name: 'Babcock University',
  domains: [{ domain: 'student.babcock.edu.ng', domain_type: 'STUDENT' }] }] };

async function fillSignUp(user, { confirm = 'Password123', agree = true } = {}) {
  await screen.findByLabelText('University');
  await waitFor(() => expect(screen.getByLabelText('University').tagName).toBe('SELECT'));
  await user.type(screen.getByLabelText('Full name'), 'Ada Student');
  await user.type(screen.getByLabelText('Student email'), 'ada@student.babcock.edu.ng');
  await user.type(screen.getByLabelText('Password'), 'Password123');
  await user.type(screen.getByLabelText('Confirm password'), confirm);
  await user.selectOptions(screen.getByLabelText('University'), 'Babcock University');
  await user.type(screen.getByLabelText('Department'), 'Software Engineering');
  await user.type(screen.getByLabelText('Level'), '200');
  await user.type(screen.getByLabelText('Academic session'), '2026/2027');
  await user.type(screen.getByLabelText('Matric Number'), '21/1234');
  if (agree) await user.click(screen.getByRole('checkbox', { name: /I agree to the Terms/ }));
}

function describedBy(field) {
  return (field.getAttribute('aria-describedby') || '').split(' ')
    .map((id) => document.getElementById(id)?.textContent ?? '').join(' ');
}

describe('sign-up field errors', () => {
  it('catches mismatched passwords at the field, without sending anything', async () => {
    const calls = mockApi({ '/universities': REGISTRY });
    renderWithAuth(<SignUp />, { token: null });
    const user = userEvent.setup();
    await fillSignUp(user, { confirm: 'Password124' });
    await user.click(screen.getByRole('button', { name: 'Create account' }));

    const confirm = screen.getByLabelText('Confirm password');
    await waitFor(() => expect(confirm).toHaveFocus());
    expect(confirm).toHaveAttribute('aria-invalid', 'true');
    expect(describedBy(confirm)).toMatch('Passwords do not match.');
    expect(calls.some((c) => c.path === '/auth/register')).toBe(false);
  });

  it('puts a refusal the backend tied to a field beside that field', async () => {
    mockApi({
      '/universities': REGISTRY,
      'POST /auth/register': { __status: 409, error: 'conflict',
                               message: 'An account with that email already exists.',
                               details: { field: 'email' } },
    });
    renderWithAuth(<SignUp />, { token: null });
    const user = userEvent.setup();
    await fillSignUp(user);
    await user.click(screen.getByRole('button', { name: 'Create account' }));

    const email = screen.getByLabelText('Student email');
    await waitFor(() => expect(email).toHaveFocus());
    expect(email).toHaveAttribute('aria-invalid', 'true');
    expect(describedBy(email)).toMatch('An account with that email already exists.');

    // Editing the field answers its error.
    await user.type(email, 'x');
    expect(email).not.toHaveAttribute('aria-invalid');
  });
});

// ── Event actions follow the event's state ────────────────────────────────

describe('event detail actions', () => {
  const EVENT = {
    id: 7, course_id: 1, course_code: 'COS202', event_type: 'ASSIGNMENT',
    title: 'COS202 Assignment', event_date: '2026-09-18', event_time: null,
    venue: 'LT1', priority: 'NORMAL', status: 'SCHEDULED', version: 1,
    original_message: null, created_at: '2026-09-12', completed: false,
  };

  function openAt(event) {
    vi.useFakeTimers({ toFake: ['Date'], now: new Date(2026, 8, 15, 9, 0, 0) });
    mockApi({ '/auth/me': STUDENT_SESSION, '/events/7': { event, history: [] } });
    renderAtRoute('/events/:eventId', <EventDetailPage />, { route: '/events/7' });
    return screen.findByRole('heading', { name: 'COS202 Assignment' });
  }

  it('offers a reminder and completion on work still ahead', async () => {
    await openAt(EVENT);
    expect(screen.getByRole('button', { name: 'Add a reminder' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Mark complete' })).toBeInTheDocument();
  });

  it('offers neither on a cancelled event, and says why', async () => {
    await openAt({ ...EVENT, status: 'CANCELLED' });
    expect(screen.getByText('This assignment was cancelled')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Add a reminder' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Mark/ })).not.toBeInTheDocument();
  });

  it('offers no reminder for work already marked done, but lets it be undone', async () => {
    await openAt({ ...EVENT, completed: true });
    expect(screen.queryByRole('button', { name: 'Add a reminder' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Mark not complete' })).toBeInTheDocument();
  });

  it('offers no reminder once the date has passed', async () => {
    await openAt({ ...EVENT, event_date: '2026-09-10' });
    expect(screen.queryByRole('button', { name: 'Add a reminder' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Mark complete' })).toBeInTheDocument();
  });
});

// ── Community routes, Manage included ─────────────────────────────────────

const COMMUNITY_ROUTES = {
  '/community': { community: COMMUNITY, membership: REP_SESSION.membership },
  '/community/courses': { courses: [] },
  '/community/timetable': { timetable: [] },
  '/community/announcements': { announcements: [] },
  '/community/changes?limit=20': { changes: [] },
  '/rep/candidates': { candidates: [] },
  '/rep/removals': { removals: [] },
  '/community/calendar': { calendar: null },
  '/dashboard': { community: COMMUNITY, rep: { pending_requests: [] } },
};

function communityApp(route, session = REP_SESSION, extra = {}) {
  mockApi({ '/auth/me': session, ...COMMUNITY_ROUTES, ...extra });
  return renderWithAuth(
    <Routes>
      <Route path="/community" element={<CommunityPage />} />
      <Route path="/community/manage" element={<RepDashboard />} />
      <Route path="/community/:section" element={<CommunityPage />} />
      <Route path="/rep" element={<Navigate to="/community/manage" replace />} />
    </Routes>,
    { route },
  );
}

describe('Community navigation', () => {
  it('treats Manage as a Community sub-route, reached from the old address too', async () => {
    communityApp('/rep');
    expect(await screen.findByRole('heading', { name: 'Manage', level: 1 })).toBeInTheDocument();
    const nav = screen.getByRole('navigation', { name: 'Community sections' });
    expect(within(nav).getByRole('link', { name: 'Manage' }))
      .toHaveAttribute('aria-current', 'page');
    // Every sub-tab leads to its own section, not to the overview.
    expect(within(nav).getByRole('link', { name: 'Elections' }))
      .toHaveAttribute('href', '/community/elections');
    expect(within(nav).getByRole('link', { name: 'Membership' }))
      .toHaveAttribute('href', '/community/membership');
  });

  it('opens the section a link names', async () => {
    communityApp('/community/manage');
    await screen.findByRole('heading', { name: 'Manage', level: 1 });
    const user = userEvent.setup();
    await user.click(within(screen.getByRole('navigation', { name: 'Community sections' }))
      .getByRole('link', { name: 'Elections' }));
    expect(await screen.findByRole('heading', { name: 'Elections' })).toBeInTheDocument();
    expect(within(screen.getByRole('navigation', { name: 'Community sections' }))
      .getByRole('link', { name: 'Elections' })).toHaveAttribute('aria-current', 'page');
  });

  it('deep-links straight to a section', async () => {
    communityApp('/community/membership', STUDENT_SESSION);
    expect(await screen.findByRole('heading', { name: 'Transfer to another community' }))
      .toBeInTheDocument();
    // A student has no Manage tab at all.
    expect(screen.queryByRole('link', { name: 'Manage' })).not.toBeInTheDocument();
  });

  it('writes recent changes as sentences and leaves classmates out', async () => {
    communityApp('/community', STUDENT_SESSION, {
      '/community/changes?limit=20': { changes: [
        { id: 2, entity_type: 'academic_event', entity_id: 4, change_type: 'DEADLINE_CHANGED',
          old_value: { event_date: '2026-09-17' }, new_value: { event_date: '2026-09-18' },
          subject: { title: 'COS202 Quiz', course_code: 'COS202', event_type: 'QUIZ' },
          actor_name: 'Ada Rep', created_at: '2026-09-16T09:00:00+00:00' },
        { id: 1, entity_type: 'community_member', entity_id: 9, change_type: 'MEMBERSHIP_APPROVED',
          old_value: { status: 'PENDING_APPROVAL' }, new_value: { status: 'ACTIVE' },
          actor_name: 'Ada Rep', created_at: '2026-09-15T09:00:00+00:00' },
      ] },
    });
    const board = (await screen.findByRole('heading', { name: 'Recent changes' })).closest('.board');
    expect(within(board).getByText('The date for COS202 Quiz (COS202) was updated.'))
      .toBeInTheDocument();
    expect(board.textContent).not.toMatch(/membership|approved|DEADLINE|_/i);
  });
});

// ── The shell ─────────────────────────────────────────────────────────────

function shellAt(route) {
  mockApi({ '/auth/me': STUDENT_SESSION, '/notifications': { notifications: [], unread: 0 } });
  return renderWithAuth(
    <Routes>
      <Route element={<Layout />}>
        <Route path="/chat" element={<p>Chat page</p>} />
        <Route path="/dashboard" element={<p>Dashboard page</p>} />
        <Route path="/community/manage" element={<p>Manage page</p>} />
      </Route>
    </Routes>,
    { route },
  );
}

describe('the application shell', () => {
  it('gives Chat its own Add message entry, since the floating one is withheld there', async () => {
    const { container } = shellAt('/chat');
    await screen.findByText('Chat page');
    const entry = container.querySelector('.topbar__chatadd');
    expect(entry).toHaveAttribute('aria-label', 'Add message');
    expect(entry).toHaveAttribute('href', '/add-message');
    expect(container.querySelector('.fab')).toBeNull();
  });

  it('keeps the floating Add message everywhere else, and no second one', async () => {
    const { container } = shellAt('/dashboard');
    await screen.findByText('Dashboard page');
    expect(container.querySelector('.fab')).not.toBeNull();
    expect(container.querySelector('.topbar__chatadd')).toBeNull();
  });

  it('keeps Community highlighted inside Manage', async () => {
    const { container } = shellAt('/community/manage');
    await screen.findByText('Manage page');
    expect(container.querySelector('.sidenav a.active')).toHaveTextContent('Community');
    expect(container.querySelector('.topbar__title')).toHaveTextContent('Manage');
  });
});
