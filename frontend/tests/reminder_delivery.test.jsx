// A reminder reaching its time, as the page sees it.
//
// The bell still decides nothing: every toast here appears because the mocked
// server RETURNED a row. What is under test is WHEN the bell asks - just after
// the next reminder is due, rather than on its next fixed poll - and that the
// rest of the page moves with it.

import { act, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import NotificationBell from '../src/components/NotificationBell.jsx';
import PersonalReminders from '../src/components/PersonalReminders.jsx';
import { api } from '../src/api/client.js';
import {
  announce, listen, NOTIFICATIONS_ARRIVED, REMINDERS_CHANGED,
} from '../src/lib/liveEvents.js';
import { mockApi, renderWithAuth, STUDENT_SESSION } from './helpers.jsx';

const FIRED = {
  id: 9, subject: 'COS202 Assignment', body: 'Due Monday 28 September at 23:59.',
  kind: 'PERSONAL_REMINDER', link: '/reminders',
  created_at: '2026-09-27T17:00:00+00:00', read_at: null,
};

const toastRegion = () => screen.getByRole('region', { name: 'New notifications' });
const bellCalls = (calls) => calls.filter((c) => c.path === '/notifications').length;

function hideTab(hidden) {
  Object.defineProperty(document, 'visibilityState', {
    configurable: true, get: () => (hidden ? 'hidden' : 'visible'),
  });
}

// A server whose reminder "fires" when the test says so.
function server({ dueInMs }) {
  const state = { fired: false, nextAt: new Date(Date.now() + dueInMs).toISOString() };
  const calls = mockApi({
    '/auth/me': STUDENT_SESSION,
    '/notifications': () => (state.fired
      ? { notifications: [FIRED], unread: 1, next_reminder_at: null }
      : { notifications: [], unread: 0, next_reminder_at: state.nextAt }),
  });
  return { state, calls };
}

describe('the bell asks at the reminder time', () => {
  beforeEach(() => { vi.useFakeTimers({ shouldAdvanceTime: true }); hideTab(false); });
  afterEach(() => { vi.useRealTimers(); hideTab(false); });

  it('asks again just after the next reminder is due, and toasts it', async () => {
    const { state, calls } = server({ dueInMs: 10_000 });
    renderWithAuth(<NotificationBell />);
    await screen.findByRole('button', { name: 'Notifications' });
    const atLoad = bellCalls(calls);

    // Before its time: no extra request, nothing shown.
    await act(() => vi.advanceTimersByTimeAsync(9_000));
    expect(bellCalls(calls)).toBe(atLoad);

    // The worker fires it at its time; the bell asks just after - well
    // inside the 30s regular poll - and the toast appears.
    state.fired = true;
    await act(() => vi.advanceTimersByTimeAsync(4_000));
    expect(bellCalls(calls)).toBe(atLoad + 1);
    expect(await within(toastRegion()).findByText('COS202 Assignment')).toBeInTheDocument();
    expect(within(toastRegion()).getByText('Due Monday 28 September at 23:59.'))
      .toBeInTheDocument();
    // ...and the badge moved without a reload.
    expect(screen.getByRole('button', { name: 'Notifications, 1 unread' })).toBeInTheDocument();
  });

  it('asks again shortly while a due reminder has not arrived yet', async () => {
    // Due already (the worker is mid-cycle): recheck in seconds, not at the
    // next poll.
    const { state, calls } = server({ dueInMs: -1_000 });
    renderWithAuth(<NotificationBell />);
    await screen.findByRole('button', { name: 'Notifications' });
    const atLoad = bellCalls(calls);

    await act(() => vi.advanceTimersByTimeAsync(3_500));
    expect(bellCalls(calls)).toBe(atLoad + 1);
    state.fired = true;
    await act(() => vi.advanceTimersByTimeAsync(3_500));
    expect(await within(toastRegion()).findByText('COS202 Assignment')).toBeInTheDocument();
  });

  it('stops asking early once a reminder is long overdue (the worker is not running)', async () => {
    const { calls } = server({ dueInMs: -5 * 60_000 });
    renderWithAuth(<NotificationBell />);
    await screen.findByRole('button', { name: 'Notifications' });
    const atLoad = bellCalls(calls);
    // Only the regular 30s poll, not a 3s recheck loop.
    await act(() => vi.advanceTimersByTimeAsync(29_000));
    expect(bellCalls(calls)).toBe(atLoad);
  });

  it('does not ask at the reminder time while the tab is hidden', async () => {
    const { state, calls } = server({ dueInMs: 5_000 });
    renderWithAuth(<NotificationBell />);
    await screen.findByRole('button', { name: 'Notifications' });
    const atLoad = bellCalls(calls);

    hideTab(true);
    state.fired = true;
    await act(() => vi.advanceTimersByTimeAsync(10_000));
    expect(bellCalls(calls)).toBe(atLoad);

    // Back on the tab: it asks, finds it, and toasts it then.
    hideTab(false);
    document.dispatchEvent(new Event('visibilitychange'));
    expect(await within(toastRegion()).findByText('COS202 Assignment')).toBeInTheDocument();
  });

  it('shows one toast for one reminder, however many times it asks', async () => {
    const { state } = server({ dueInMs: 2_000 });
    renderWithAuth(<NotificationBell />);
    await screen.findByRole('button', { name: 'Notifications' });
    state.fired = true;
    await act(() => vi.advanceTimersByTimeAsync(5_000));
    await within(toastRegion()).findByText('COS202 Assignment');
    // The due check, a focus, a reminder change and a regular poll all ask
    // again; the same id never toasts twice.
    window.dispatchEvent(new Event('focus'));
    announce(REMINDERS_CHANGED);
    await act(() => vi.advanceTimersByTimeAsync(31_000));
    await waitFor(() => {
      expect(within(toastRegion()).queryAllByText('COS202 Assignment').length).toBeLessThanOrEqual(1);
    });
    expect(toastRegion().querySelectorAll('.toast').length).toBeLessThanOrEqual(1);
  });
});

describe('the rest of the page moves with the bell', () => {
  afterEach(() => { vi.useRealTimers(); });

  it('re-reads when a reminder is set anywhere, to learn the new due time', async () => {
    const calls = mockApi({
      '/auth/me': STUDENT_SESSION,
      '/notifications': { notifications: [], unread: 0, next_reminder_at: null },
    });
    renderWithAuth(<NotificationBell />);
    await screen.findByRole('button', { name: 'Notifications' });
    const atLoad = bellCalls(calls);
    announce(REMINDERS_CHANGED);
    await waitFor(() => expect(bellCalls(calls)).toBe(atLoad + 1));
  });

  it('the API client announces every reminder write, and nothing else', async () => {
    mockApi({
      'POST /reminders': { reminder: { id: 1 } },
      'PUT /reminders/1': { reminder: { id: 1 } },
      'DELETE /reminders/1': { ok: true },
      '/reminders': { reminders: [] },
      'POST /events': { event: {} },
    });
    const heard = vi.fn();
    const stop = listen(REMINDERS_CHANGED, heard);
    await api.get('/reminders');
    await api.post('/events', {});
    expect(heard).not.toHaveBeenCalled();
    await api.post('/reminders', { title: 'x' });
    await api.put('/reminders/1', { title: 'y' });
    await api.del('/reminders/1');
    expect(heard).toHaveBeenCalledTimes(3);
    stop();
  });

  it('announces what arrived, so other views can re-read', async () => {
    let batch = [];
    mockApi({
      '/auth/me': STUDENT_SESSION,
      '/notifications': () => ({ notifications: batch, unread: batch.length }),
    });
    const heard = vi.fn();
    const stop = listen(NOTIFICATIONS_ARRIVED, (e) => heard(e.detail));
    renderWithAuth(<NotificationBell />);
    await screen.findByRole('button', { name: 'Notifications' });
    expect(heard).not.toHaveBeenCalled();       // the first load announces nothing
    batch = [FIRED];
    window.dispatchEvent(new Event('focus'));
    await waitFor(() => expect(heard).toHaveBeenCalledWith({ kinds: ['PERSONAL_REMINDER'] }));
    stop();
  });

  it('the reminders list re-reads when one of its reminders fires', async () => {
    let status = 'PENDING';
    const calls = mockApi({
      '/auth/me': STUDENT_SESSION,
      '/reminders': () => ({ reminders: [{
        id: 1, title: 'COS202 Assignment', status,
        remind_at: '2026-09-27T17:00:00+00:00', remind_at_local: '2026-09-27T18:00',
        timezone: 'Africa/Lagos', event_id: null,
      }] }),
    });
    renderWithAuth(<PersonalReminders caption={null} />);
    await screen.findByText('COS202 Assignment');
    const reads = () => calls.filter((c) => c.path === '/reminders').length;
    const before = reads();

    // Something else arriving does not concern this list.
    announce(NOTIFICATIONS_ARRIVED, { kinds: ['ANNOUNCEMENT'] });
    status = 'SENT';
    announce(NOTIFICATIONS_ARRIVED, { kinds: ['PERSONAL_REMINDER'] });
    await waitFor(() => expect(reads()).toBe(before + 1));
    expect(await screen.findByText('Sent')).toBeInTheDocument();
  });
});


// ── The date you picked is the date you see ────────────────────────────────
//
// A reminder set for 29 September 2027 instead of 2026 - one arrow-key press
// in a date picker's year - read "Wed 29 Sep" in the list, looked like this
// week's, and never fired. The year is now shown wherever it could mislead.

describe('the date you picked is the date you see', () => {
  it('a date more than six months away carries its year; a near one does not', async () => {
    const { whenParts } = await import('../src/components/ui.jsx');
    const today = new Date('2026-09-29T00:00:00');
    expect(whenParts('2027-09-29', today)).toEqual({ top: 'Wed', bottom: '29 Sep', year: '2027' });
    expect(whenParts('2026-10-02', today)).toEqual({ top: 'Fri', bottom: '2 Oct' });
    // Across a new year but near: still short, and unambiguous.
    expect(whenParts('2027-01-12', today)).toEqual({ top: 'Tue', bottom: '12 Jan' });
    // Long past (an old change in the history) also says which year.
    expect(whenParts('2025-12-01', today).year).toBe('2025');
    expect(whenParts('2026-09-29', today).top).toBe('Today');
  });

  it('the form reads the picked time back in full, year included', async () => {
    const { fireEvent } = await import('@testing-library/react');
    mockApi({ '/auth/me': STUDENT_SESSION, '/reminders': { reminders: [] } });
    renderWithAuth(<PersonalReminders caption={null} />);
    const when = await screen.findByLabelText('Remind me at');
    fireEvent.change(when, { target: { value: '2027-09-29T11:54' } });
    expect(screen.getByText("You'll be reminded on Wednesday 29 September 2027 at 11:54."))
      .toBeInTheDocument();
    // It describes the field, so a screen reader hears it with the input.
    expect(when).toHaveAttribute('aria-describedby', 'new-reminder-when-hint');
  });

  it('after adding, says what the server stored - with its year', async () => {
    const { fireEvent } = await import('@testing-library/react');
    const stored = {
      id: 5, title: 'hey', status: 'PENDING', event_id: null,
      remind_at: '2026-09-29T10:54:00+00:00', remind_at_local: '2026-09-29T11:54',
      timezone: 'Africa/Lagos',
    };
    mockApi({
      '/auth/me': STUDENT_SESSION,
      '/reminders': { reminders: [] },
      'POST /reminders': { reminder: stored },
    });
    renderWithAuth(<PersonalReminders caption={null} />);
    fireEvent.change(await screen.findByLabelText('Reminder title'), { target: { value: 'hey' } });
    fireEvent.change(screen.getByLabelText('Remind me at'), { target: { value: '2026-09-29T11:54' } });
    fireEvent.click(screen.getByRole('button', { name: 'Add reminder' }));
    expect(await screen.findByText('Reminder added for Tuesday 29 September 2026 at 11:54.'))
      .toBeInTheDocument();
  });
});
