// The notification bell.
//
// The rule under test is an absence as much as a presence: the bell renders
// what the server returned and never concludes on its own that a reminder has
// fired. There is no clock comparison in this component to test, and these
// make sure none appears.

import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import NotificationBell from '../src/components/NotificationBell.jsx';
import { mockApi, renderWithAuth, STUDENT_SESSION } from './helpers.jsx';

const REMINDER = {
  id: 3, subject: 'Reminder: Revise for the quiz',
  body: 'Your personal reminder: Revise for the quiz',
  kind: 'PERSONAL_REMINDER', link: '/reminders',
  created_at: '2026-09-22T08:00:00+00:00', read_at: null,
};

const EVENT = {
  id: 4, subject: 'Reminder: COS202 Assignment',
  body: 'Reminder: COS202 Assignment (Assignment) is due 23 September.',
  kind: 'EVENT_REMINDER', link: '/events/7',
  created_at: '2026-09-22T07:00:00+00:00', read_at: null,
};

const READ = {
  id: 5, subject: 'Reminder: Older thing', body: 'Already seen',
  kind: 'PERSONAL_REMINDER', link: '/reminders',
  created_at: '2026-09-20T08:00:00+00:00', read_at: '2026-09-20T09:00:00+00:00',
};

// jsdom reports a visible tab and offers no way to change it; the component
// reads `document.visibilityState` directly, so override the getter.
function hideTab(hidden) {
  Object.defineProperty(document, 'visibilityState', {
    configurable: true,
    get: () => (hidden ? 'hidden' : 'visible'),
  });
}

function open(notifications, unread, extra = {}) {
  const calls = mockApi({
    '/auth/me': STUDENT_SESSION,
    '/notifications': { notifications, unread },
    ...extra,
  });
  renderWithAuth(<NotificationBell />);
  return calls;
}

describe('notification bell', () => {
  it('shows nothing on the bell when there is nothing unread', async () => {
    open([READ], 0);
    const bell = await screen.findByRole('button', { name: 'Notifications' });
    // No badge, and the label does not claim a count.
    expect(bell).toBeInTheDocument();
    expect(screen.queryByText('1')).not.toBeInTheDocument();
  });

  it('badges the unread count and says it in the accessible name', async () => {
    open([REMINDER, EVENT], 2);
    expect(await screen.findByRole('button', { name: 'Notifications, 2 unread' }))
      .toBeInTheDocument();
    expect(screen.getByText('2')).toBeInTheDocument();
  });

  it('caps the badge but not the announced count', async () => {
    open([REMINDER], 14);
    expect(await screen.findByRole('button', { name: 'Notifications, 14 unread' }))
      .toBeInTheDocument();
    expect(screen.getByText('9+')).toBeInTheDocument();
  });

  it('lists reminders with their kind, subject and message', async () => {
    open([REMINDER], 1);
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: /Notifications/ }));

    const panel = screen.getByRole('dialog', { name: 'Notifications' });
    expect(within(panel).getByText('Reminder')).toBeInTheDocument();
    expect(within(panel).getByText('Reminder: Revise for the quiz')).toBeInTheDocument();
    expect(within(panel).getByText(/Your personal reminder/)).toBeInTheDocument();
  });

  it('says so plainly when there is nothing', async () => {
    open([], 0);
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: /Notifications/ }));
    expect(screen.getByText(/Updates from your course reps, and reminders you set/))
      .toBeInTheDocument();
  });

  it('marks one as read without leaving the panel', async () => {
    const calls = open([REMINDER], 1, {
      'POST /notifications/3/read': { id: 3, unread: 0 },
    });
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: /Notifications/ }));
    await user.click(screen.getByRole('button',
      { name: 'Mark "Reminder: Revise for the quiz" as read' }));

    await waitFor(() => {
      expect(calls.find((c) => c.path === '/notifications/3/read'
                               && c.method === 'POST')).toBeTruthy();
    });
    // The badge follows the server's count.
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Notifications' })).toBeInTheDocument();
    });
  });

  it('marks all as read', async () => {
    const calls = open([REMINDER, EVENT], 2, {
      'POST /notifications/read-all': { marked: 2, unread: 0 },
    });
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: /Notifications/ }));
    await user.click(screen.getByRole('button', { name: 'Mark all as read' }));

    await waitFor(() => {
      expect(calls.find((c) => c.path === '/notifications/read-all'
                               && c.method === 'POST')).toBeTruthy();
    });
  });

  it('offers no mark-all when there is nothing unread', async () => {
    open([READ], 0);
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: /Notifications/ }));
    expect(screen.queryByRole('button', { name: 'Mark all as read' }))
      .not.toBeInTheDocument();
  });

  it('opens the record a notification is about', async () => {
    const calls = open([EVENT], 1, {
      'POST /notifications/4/read': { id: 4, unread: 0 },
    });
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: /Notifications/ }));
    await user.click(screen.getByText('Reminder: COS202 Assignment'));

    // Following it also marks it read — you have seen it.
    await waitFor(() => {
      expect(calls.find((c) => c.path === '/notifications/4/read')).toBeTruthy();
    });
  });

  it('closes on Escape', async () => {
    open([REMINDER], 1);
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: /Notifications/ }));
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    await user.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  });

  it('survives the endpoint failing, without a banner', async () => {
    // A failed poll must not take the shell down or shout at the reader.
    mockApi({
      '/auth/me': STUDENT_SESSION,
      '/notifications': () => ({ __status: 500, error: 'server_error', message: 'boom' }),
    });
    renderWithAuth(<NotificationBell />);
    expect(await screen.findByRole('button', { name: 'Notifications' })).toBeInTheDocument();
  });

  it('never invents a notification from the clock', async () => {
    // The server says nothing is due. Whatever the local time is, the bell
    // shows nothing: the worker is the authority, not the browser.
    open([], 0);
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: /Notifications/ }));
    expect(screen.queryByText(/Reminder:/)).not.toBeInTheDocument();
  });
});

// ── Toasts ─────────────────────────────────────────────────────────────────
//
// The rule that matters most is an ABSENCE: a page you open with unread
// reminders already waiting must not fire a popup for each of them. A toast is
// for something that arrived while you were looking.
//
// There is also no time logic to test, because there is none in the frontend.
// A toast appears because the API returned a row the worker created.

// The toast region is always mounted - a live region inserted together with
// its first message is often never announced - so "no toast" means the region
// holds none, not that the region is absent.
const toastRegion = () => screen.getByRole('region', { name: 'New notifications' });
const toastCount = () => toastRegion().querySelectorAll('.toast').length;

describe('notification toasts', () => {
  it('does not replay existing unread notifications on first load', async () => {
    open([REMINDER, EVENT], 2);
    // The bell shows them...
    expect(await screen.findByRole('button', { name: 'Notifications, 2 unread' }))
      .toBeInTheDocument();
    // ...and nothing pops up.
    expect(toastCount()).toBe(0);
  });

  it('registers its live region before the first toast arrives', async () => {
    open([], 0);
    await screen.findByRole('button', { name: 'Notifications' });
    const region = toastRegion();
    expect(region).toHaveAttribute('aria-live', 'polite');
    expect(toastCount()).toBe(0);
  });

  it('pops up for a notification that arrives after the first load', async () => {
    let batch = [REMINDER];
    const calls = mockApi({
      '/auth/me': STUDENT_SESSION,
      '/notifications': () => ({ notifications: batch, unread: batch.length }),
    });
    renderWithAuth(<NotificationBell />);
    await screen.findByRole('button', { name: 'Notifications, 1 unread' });
    expect(toastCount()).toBe(0);

    // The worker creates one; the next poll picks it up. Triggered here by the
    // focus refresh the component already listens for — no second timer.
    batch = [EVENT, REMINDER];
    window.dispatchEvent(new Event('focus'));

    expect(await within(toastRegion()).findByText('Reminder: COS202 Assignment'))
      .toBeInTheDocument();
    // Only the NEW one, not the one that was already there.
    expect(within(toastRegion()).queryByText('Reminder: Revise for the quiz'))
      .not.toBeInTheDocument();
    expect(calls.filter((c) => c.path === '/notifications').length).toBeGreaterThan(1);
  });

  it('does not re-toast the same notification on a later poll', async () => {
    let batch = [REMINDER];
    mockApi({
      '/auth/me': STUDENT_SESSION,
      '/notifications': () => ({ notifications: batch, unread: batch.length }),
    });
    renderWithAuth(<NotificationBell />);
    await screen.findByRole('button', { name: /Notifications/ });

    batch = [EVENT, REMINDER];
    window.dispatchEvent(new Event('focus'));
    // Matched as a whole string, so this counts toast subjects and not the
    // body text underneath them, which repeats the title.
    expect(await within(toastRegion()).findAllByText('Reminder: COS202 Assignment'))
      .toHaveLength(1);

    // Same rows again: the id is already seen, so nothing new appears.
    window.dispatchEvent(new Event('focus'));
    await waitFor(() => {
      expect(within(screen.getByRole('region', { name: 'New notifications' }))
        .getAllByText('Reminder: COS202 Assignment')).toHaveLength(1);
    });
  });

  it('dismissing closes the popup and leaves the notification UNREAD', async () => {
    let batch = [];
    const calls = mockApi({
      '/auth/me': STUDENT_SESSION,
      '/notifications': () => ({ notifications: batch, unread: batch.length }),
    });
    renderWithAuth(<NotificationBell />);
    await screen.findByRole('button', { name: 'Notifications' });

    batch = [REMINDER];
    window.dispatchEvent(new Event('focus'));
    await within(toastRegion()).findByText('Reminder: Revise for the quiz');

    const user = userEvent.setup();
    await user.click(screen.getByRole('button',
      { name: 'Dismiss Reminder: Revise for the quiz' }));

    await waitFor(() => { expect(toastCount()).toBe(0); });
    // Nothing was marked read — the bell is still holding it.
    expect(calls.some((c) => c.path.includes('/read'))).toBe(false);
    expect(screen.getByRole('button', { name: 'Notifications, 1 unread' }))
      .toBeInTheDocument();
  });

  it('View marks it read and navigates to its link', async () => {
    let batch = [];
    const calls = mockApi({
      '/auth/me': STUDENT_SESSION,
      '/notifications': () => ({ notifications: batch, unread: batch.length }),
      'POST /notifications/3/read': { id: 3, unread: 0 },
    });
    renderWithAuth(<NotificationBell />);
    await screen.findByRole('button', { name: 'Notifications' });

    batch = [REMINDER];
    window.dispatchEvent(new Event('focus'));
    await within(toastRegion()).findByText('Reminder: Revise for the quiz');

    const user = userEvent.setup();
    // The label names the thing.
    await user.click(screen.getByRole('button', { name: 'View reminder' }));

    await waitFor(() => {
      expect(calls.find((c) => c.path === '/notifications/3/read'
                               && c.method === 'POST')).toBeTruthy();
    });
    // And the popup closes.
    await waitFor(() => { expect(toastCount()).toBe(0); });
  });

  it('caps a burst rather than covering the screen', async () => {
    let batch = [];
    mockApi({
      '/auth/me': STUDENT_SESSION,
      '/notifications': () => ({ notifications: batch, unread: batch.length }),
    });
    renderWithAuth(<NotificationBell />);
    await screen.findByRole('button', { name: 'Notifications' });

    // Five reminders come due at once, as they would after a worker outage.
    batch = [1, 2, 3, 4, 5].map((n) => ({
      ...REMINDER, id: 100 + n, subject: `Reminder: Item ${n}`,
    }));
    window.dispatchEvent(new Event('focus'));

    const region = await screen.findByRole('region', { name: 'New notifications' });
    await waitFor(() => {
      expect(within(region).getAllByText(/Reminder: Item/)).toHaveLength(3);
    });
    // The rest are not lost — they are in the bell.
    expect(screen.getByRole('button', { name: 'Notifications, 5 unread' }))
      .toBeInTheDocument();
  });

  it('announces politely and is reachable by keyboard', async () => {
    let batch = [];
    mockApi({
      '/auth/me': STUDENT_SESSION,
      '/notifications': () => ({ notifications: batch, unread: batch.length }),
    });
    renderWithAuth(<NotificationBell />);
    await screen.findByRole('button', { name: 'Notifications' });
    batch = [REMINDER];
    window.dispatchEvent(new Event('focus'));

    const region = await screen.findByRole('region', { name: 'New notifications' });
    expect(region).toHaveAttribute('aria-live', 'polite');
    // Both controls are real buttons, so they are in the tab order.
    expect(within(region).getByRole('button', { name: 'View reminder' })).toBeInTheDocument();
    expect(within(region).getByRole('button', { name: /^Dismiss/ })).toBeInTheDocument();
  });

  it('stays quiet while the tab is hidden, exactly as the bell already does', async () => {
    // The toast reuses the bell's poll and inherits its rule: a hidden tab is
    // not polled, so nothing can pop up behind your back and expire unseen.
    // Whatever arrived is still waiting in the bell when you come back.
    let batch = [];
    const calls = mockApi({
      '/auth/me': STUDENT_SESSION,
      '/notifications': () => ({ notifications: batch, unread: batch.length }),
    });
    renderWithAuth(<NotificationBell />);
    await screen.findByRole('button', { name: 'Notifications' });
    const atLoad = calls.filter((c) => c.path === '/notifications').length;

    hideTab(true);
    batch = [REMINDER];
    // Both signals the component listens for, while hidden.
    document.dispatchEvent(new Event('visibilitychange'));
    window.dispatchEvent(new Event('focus'));

    await waitFor(() => {
      expect(calls.filter((c) => c.path === '/notifications').length).toBe(atLoad);
    });
    expect(toastCount()).toBe(0);

    // Coming back to the tab is what fetches it — and THEN it toasts.
    hideTab(false);
    document.dispatchEvent(new Event('visibilitychange'));
    expect(await within(toastRegion()).findByText('Reminder: Revise for the quiz'))
      .toBeInTheDocument();
  });

  it('offers no View for a notification with nowhere to go', async () => {
    // Event notifications currently carry no link; a button that led nowhere
    // would be worse than none.
    let batch = [];
    mockApi({
      '/auth/me': STUDENT_SESSION,
      '/notifications': () => ({ notifications: batch, unread: batch.length }),
    });
    renderWithAuth(<NotificationBell />);
    await screen.findByRole('button', { name: 'Notifications' });

    batch = [{ ...REMINDER, id: 77, link: null, kind: null,
               subject: 'A community update' }];
    window.dispatchEvent(new Event('focus'));

    const region = toastRegion();
    expect(await within(region).findByText('A community update')).toBeInTheDocument();
    expect(within(region).queryByRole('button', { name: /^View/ })).not.toBeInTheDocument();
    expect(within(region).getByRole('button', { name: /^Dismiss/ })).toBeInTheDocument();
  });
});
