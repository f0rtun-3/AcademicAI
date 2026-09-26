import { screen, within } from '@testing-library/react';
import { Route, Routes } from 'react-router-dom';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import Dashboard from '../src/pages/Dashboard.jsx';
import ChatPage from '../src/pages/ChatPage.jsx';
import CalendarPage from '../src/pages/CalendarPage.jsx';
import RepDashboard from '../src/pages/RepDashboard.jsx';
import EventDetailPage from '../src/pages/EventDetailPage.jsx';
import { COMMUNITY, mockApi, renderAtRoute, renderWithAuth, REP_SESSION, STUDENT_SESSION }
  from './helpers.jsx';

const EVENT = {
  id: 7, course_id: 1, course_code: 'COS202', event_type: 'ASSIGNMENT',
  title: 'COS202 Assignment', event_date: '2026-09-18', event_time: null,
  venue: 'LT1', priority: 'NORMAL', status: 'SCHEDULED', version: 1,
  original_message: 'cos 202 assignment on friday', created_at: '2026-09-15',
  completed: false,
};

function dashboard(overrides = {}) {
  return {
    greeting: 'Welcome back, Bola',
    user: { id: 2, full_name: 'Bola Student' },
    community: COMMUNITY,
    membership: { community_id: 1, status: 'ACTIVE', role: 'STUDENT' },
    upcoming: [EVENT],
    recent_changes: [{
      id: 1, entity_type: 'academic_event', entity_id: 7, change_type: 'DEADLINE_CHANGED',
      old_value: { event_date: '2026-09-18' }, new_value: { event_date: '2026-09-21' },
      actor_id: 1, actor_name: 'Ada Rep', source_message: null, created_at: '2026-09-16',
    }],
    announcements: [], reminders: [], ...overrides,
  };
}

describe('Dashboard', () => {
  it('shows community identity, upcoming items and recent changes', async () => {
    mockApi({ '/auth/me': STUDENT_SESSION, '/dashboard': dashboard() });
    renderWithAuth(<Dashboard />);

    expect(await screen.findByText('Welcome back, Bola')).toBeInTheDocument();
    expect(screen.getByText(/Babcock University/)).toBeInTheDocument();
    expect(screen.getByText(/Software Engineering/)).toBeInTheDocument();
    expect(screen.getAllByText('COS202 Assignment').length).toBeGreaterThan(0);

    // Band 1: the change is read from history per render and rendered as a
    // state chip plus, in words, what moved from what to what.
    expect(screen.getByText('Deadline moved')).toBeInTheDocument();
    expect(screen.getByText(/Deadline moved from Friday 18 September to Monday 21 September\./))
      .toBeInTheDocument();
  });

  it('omits the needs-attention band entirely when nothing changed', async () => {
    mockApi({
      '/auth/me': STUDENT_SESSION,
      '/dashboard': dashboard({ recent_changes: [] }),
    });
    renderWithAuth(<Dashboard />);
    await screen.findByText('Welcome back, Bola');
    // Omitted, not shown as a reassuring zero.
    expect(screen.queryByText('Needs attention')).not.toBeInTheDocument();
  });

  it('shows an empty state rather than a blank panel', async () => {
    mockApi({
      '/auth/me': STUDENT_SESSION,
      '/dashboard': dashboard({ upcoming: [], recent_changes: [] }),
    });
    renderWithAuth(<Dashboard />);
    expect(await screen.findByText('Nothing due in the next week')).toBeInTheDocument();
  });

  it('shows an error state with a retry when the API fails', async () => {
    mockApi({
      '/auth/me': STUDENT_SESSION,
      '/dashboard': () => ({ __status: 500, error: 'internal_error',
                             message: 'Something went wrong.' }),
    });
    renderWithAuth(<Dashboard />);
    const alert = await screen.findByRole('alert');
    // The backend's own sentence is kept; the framing adds only what the
    // backend cannot know - whether anything was written.
    expect(alert).toHaveTextContent(/Something went wrong\./);
    expect(alert).toHaveTextContent(/Nothing was changed/);
    // A failed READ can never have half-applied a write, so it must not say so.
    expect(alert).not.toHaveTextContent(/may not have been saved/);
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument();
  });
});

describe('Calendar', () => {
  // The calendar anchors on the real current week, and EVENT is dated
  // 2026-09-18. That made these assertions depend on when the suite ran: the
  // Week test passed while the machine clock was inside the week of 14–20
  // September 2026 and started failing on the 21st, having tested nothing
  // about the code in between. The clock is now fixed to the Friday of the
  // event's own week, so the scenario under test is the scenario every run
  // gets.
  //
  // Only Date is faked. Faking setTimeout as well would deadlock
  // userEvent, which waits on real timers between synthetic events.
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['Date'], now: new Date(2026, 8, 18, 9, 0, 0) });
  });
  afterEach(() => { vi.useRealTimers(); });

  it('opens an event as a linkable route rather than an in-page panel', async () => {
    mockApi({
      '/auth/me': STUDENT_SESSION,
      '/calendar': {
        events: [EVENT],
        timetable: [{ id: 3, course_id: 1, course_code: 'COS202', title: 'Data Structures',
                      day_of_week: 'WEDNESDAY', start_time: '08:00', end_time: null,
                      venue: 'LT1', version: 1 }],
      },
      '/events/7': { event: EVENT, history: [] },
    });
    const user = userEvent.setup();
    renderWithAuth(
      <Routes>
        <Route path="/calendar" element={<CalendarPage />} />
        <Route path="/events/:eventId" element={<EventDetailPage />} />
      </Routes>,
      { route: '/calendar' },
    );

    // Agenda opens first and runs forward from today.
    await user.click(await screen.findByRole('button', { name: /COS202 Assignment/ }));

    // S7 is a route: the record is now addressable and survives a refresh.
    expect(await screen.findByRole('heading', { name: 'COS202 Assignment' }))
      .toBeInTheDocument();
    expect(screen.getByText('cos 202 assignment on friday')).toBeInTheDocument();
    expect(screen.getByText('LT1')).toBeInTheDocument();
  });

  it('renders an event addressed directly by its URL', async () => {
    mockApi({
      '/auth/me': STUDENT_SESSION,
      '/events/7': { event: EVENT, history: [] },
    });
    renderAtRoute('/events/:eventId', <EventDetailPage />, { route: '/events/7' });

    expect(await screen.findByRole('heading', { name: 'COS202 Assignment' }))
      .toBeInTheDocument();
    // C·2 — the official status is stated in the details ("Scheduled" is the
    // normal case, so it carries no header badge). Completion is never a chip.
    expect(screen.getByText('Scheduled')).toBeInTheDocument();
    expect(screen.queryByText(/COMPLETED BY YOU|Completed by you/)).not.toBeInTheDocument();
    expect(screen.getByText(/does not change the official record/)).toBeInTheDocument();
  });

  it('withdraws the week view to agenda-only, and shows classes when chosen', async () => {
    mockApi({
      '/auth/me': STUDENT_SESSION,
      '/calendar': {
        events: [EVENT],
        timetable: [{ id: 3, course_id: 1, course_code: 'COS202', title: 'Data Structures',
                      day_of_week: 'WEDNESDAY', start_time: '08:00', end_time: null,
                      venue: 'LT1', version: 1 }],
      },
    });
    const user = userEvent.setup();
    renderWithAuth(<CalendarPage />);

    await user.click(await screen.findByRole('tab', { name: 'Week' }));

    // The Week view is now a time GRID, not a list, so its day columns are
    // headed "Wed" rather than spelling out "Wednesday" in a row's metadata.
    // The rule being protected is unchanged and is asserted more directly than
    // before: choosing Week must surface the recurring timetable entry, on the
    // right weekday, with its course and venue intact.
    expect(await screen.findByText('Wed')).toBeInTheDocument();
    // The recurring class, identified by its own time+venue line, which is
    // unique to the timetable block.
    expect(screen.getByText(/08:00 · LT1/)).toBeInTheDocument();
    // The dated event is present too, in the all-day band: it has no
    // event_time, so it has no position on the time axis.
    expect(screen.getByText('COS202 Assignment')).toBeInTheDocument();
    // The two block kinds stay distinguishable by more than colour.
    expect(screen.getByText(/Timetable entries repeat weekly/)).toBeInTheDocument();
  });
});

describe('AI Chat', () => {
  it('answers from the record and offers a reminder the student must accept', async () => {
    mockApi({
      '/auth/me': STUDENT_SESSION,
      '/chat/prompts': { prompts: ['What is my next deadline?'] },
      'POST /chat': {
        answer: 'Your next deadline is COS202 Assignment (COS202) - 2026-09-18 in LT1.',
        grounded: true, referenced_event_ids: [7],
        suggested_reminder: { title: 'Prepare for COS202 Assignment',
                              remind_at: '2026-09-18T08:00:00+00:00' },
        conversation_id: 11,
      },
      'POST /reminders': { reminder: { id: 1, title: 'Prepare for COS202 Assignment',
                                       remind_at: '2026-09-18T08:00:00+00:00',
                                       status: 'PENDING', event_id: null } },
    });
    const user = userEvent.setup();
    renderWithAuth(<ChatPage />);

    await user.click(await screen.findByRole('button', { name: 'What is my next deadline?' }));
    expect(await screen.findByText(/Your next deadline is COS202 Assignment/)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Add reminder' }));
    expect(await screen.findByText('Personal reminder created.')).toBeInTheDocument();
  });

  it('relays that only a rep can change official information', async () => {
    mockApi({
      '/auth/me': STUDENT_SESSION,
      '/chat/prompts': { prompts: [] },
      'POST /chat': {
        answer: "I can't change official academic information. Only a verified course rep can.",
        grounded: true, referenced_event_ids: [], suggested_reminder: null, conversation_id: 12,
      },
    });
    const user = userEvent.setup();
    renderWithAuth(<ChatPage />);

    await user.type(await screen.findByLabelText('Your question'), 'change the COS202 deadline');
    await user.click(screen.getByRole('button', { name: 'Ask' }));
    expect(await screen.findByText(/Only a verified course rep can/)).toBeInTheDocument();
  });
});

describe('Rep dashboard', () => {
  const REP_ROUTES = {
    '/auth/me': REP_SESSION,
    '/dashboard': {
      ...dashboard({ membership: REP_SESSION.membership }),
      rep: {
        student_count: 4, rep_count: 1, course_count: 1, timetable_count: 1,
        pending_requests: [{ user_id: 9, full_name: 'Chidi Student',
                             requested_at: '2026-09-16' }],
      },
    },
    '/community/courses': { courses: [{ id: 1, code: 'COS202', title: 'Data Structures',
                                        version: 1 }] },
    '/community/timetable': { timetable: [] },
    '/rep/candidates': { candidates: [] },
    '/rep/removals': { removals: [] },
    '/community/calendar': { calendar: null },
    '/community/announcements': { announcements: [] },
    'POST /community/requests/9/approve': { membership: { id: 4, community_id: 1, user_id: 9,
                                                          role: 'STUDENT', status: 'ACTIVE' } },
  };

  it('lists membership requests and approves one', async () => {
    mockApi(REP_ROUTES);
    const user = userEvent.setup();
    renderWithAuth(<RepDashboard />);

    expect(await screen.findByText('Chidi Student')).toBeInTheDocument();

    // Counts are tiles here, where the figures are the point.
    expect(screen.getByText('students')).toBeInTheDocument();
    expect(screen.getByText('verified rep')).toBeInTheDocument();
    // No denominator is invented: the vacancy cap is a backend rule that no
    // response carries, so the UI must not state one (C·3 / P·4).
    expect(document.body.textContent).not.toMatch(/of 3 reps/);

    await user.click(screen.getByRole('button', { name: 'Approve' }));
    expect(await screen.findByText('Student approved.')).toBeInTheDocument();
  });

  it('refuses to render for a student', async () => {
    mockApi({ '/auth/me': STUDENT_SESSION });
    renderWithAuth(<RepDashboard />);
    expect(await screen.findByText('Not available to you')).toBeInTheDocument();
    // An explanation inside the shell with a route onward, never a bare 403.
    expect(screen.getByRole('link', { name: 'Back to Community' })).toBeInTheDocument();
  });
});
