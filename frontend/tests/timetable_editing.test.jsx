import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import RepDashboard from '../src/pages/RepDashboard.jsx';
import { COMMUNITY, renderWithAuth, REP_SESSION } from './helpers.jsx';

const ENTRY = {
  id: 21, course_id: 12, course_code: 'COS202', title: 'Software design',
  day_of_week: 'THURSDAY', start_time: '10:00', end_time: null,
  venue: 'B007', version: 3,
};

function mockRepDashboard({ onPut } = {}) {
  const calls = [];
  globalThis.fetch = async (url, init) => {
    const path = String(url).replace(/^.*\/api/, '');
    const method = init?.method || 'GET';
    let body = null;
    if (init?.body) { try { body = JSON.parse(init.body); } catch { body = init.body; } }
    calls.push({ path, method, body });
    const json = (b, s = 200) => new Response(JSON.stringify(b),
      { status: s, headers: { 'Content-Type': 'application/json' } });

    if (path === '/auth/me') return json(REP_SESSION);
    if (path === '/dashboard') {
      return json({ greeting: 'Hi', community: COMMUNITY,
                    membership: REP_SESSION.membership, upcoming: [],
                    recent_changes: [], announcements: [], reminders: [],
                    rep: { student_count: 4, rep_count: 1, pending_requests: [],
                           course_count: 1, timetable_count: 1 } });
    }
    if (path === '/community/courses') {
      return json({ courses: [{ id: 12, code: 'COS202', title: 'Software design' }] });
    }
    if (path === '/community/timetable') return json({ timetable: [ENTRY] });
    if (path === '/rep/candidates') return json({ candidates: [] });
    if (path === '/rep/removals') return json({ removals: [] });
    if (path === '/community/calendar') return json({ calendar: null });
    if (path === '/community/announcements') return json({ announcements: [] });
    if (path === '/community/timetable/21' && method === 'PUT') {
      return onPut ? onPut(json) : json({ timetable_entry: { ...ENTRY, version: 4 } });
    }
    return json({}, 404);
  };
  return calls;
}

describe('timetable editing', () => {
  it('shows an edit control for each entry', async () => {
    mockRepDashboard();
    renderWithAuth(<RepDashboard />);
    expect(await screen.findByTestId('edit-timetable-21')).toBeInTheDocument();
  });

  it('opens the entry prefilled with its current values', async () => {
    mockRepDashboard();
    renderWithAuth(<RepDashboard />);
    const user = userEvent.setup();
    await user.click(await screen.findByTestId('edit-timetable-21'));

    expect(document.getElementById('tt-e-title-21')).toHaveValue('Software design');
    expect(document.getElementById('tt-e-day-21')).toHaveValue('THURSDAY');
    expect(document.getElementById('tt-e-time-21')).toHaveValue('10:00');
    expect(document.getElementById('tt-e-venue-21')).toHaveValue('B007');
    expect(document.getElementById('tt-e-course-21')).toHaveValue('12');
  });

  it('sends the changed fields with the entry version for concurrency control', async () => {
    const calls = mockRepDashboard();
    renderWithAuth(<RepDashboard />);
    const user = userEvent.setup();
    await user.click(await screen.findByTestId('edit-timetable-21'));

    const venue = document.getElementById('tt-e-venue-21');
    await user.clear(venue);
    await user.type(venue, 'B107');
    await user.selectOptions(document.getElementById('tt-e-day-21'), 'WEDNESDAY');
    await user.click(screen.getByRole('button', { name: 'Save class' }));

    await waitFor(() => {
      const put = calls.find((c) => c.path === '/community/timetable/21' && c.method === 'PUT');
      expect(put).toBeTruthy();
      expect(put.body.venue).toBe('B107');
      expect(put.body.day_of_week).toBe('WEDNESDAY');
      // Optimistic concurrency: the version read must travel with the write.
      expect(put.body.expected_version).toBe(3);
    });
  });

  it('sends null rather than an empty string when a field is cleared', async () => {
    const calls = mockRepDashboard();
    renderWithAuth(<RepDashboard />);
    const user = userEvent.setup();
    await user.click(await screen.findByTestId('edit-timetable-21'));
    await user.clear(document.getElementById('tt-e-venue-21'));
    await user.click(screen.getByRole('button', { name: 'Save class' }));

    await waitFor(() => {
      const put = calls.find((c) => c.method === 'PUT');
      // "no specified venue" is an explicit null, not an empty string (spec 14).
      expect(put.body.venue).toBeNull();
    });
  });

  it('can detach an entry from its course', async () => {
    const calls = mockRepDashboard();
    renderWithAuth(<RepDashboard />);
    const user = userEvent.setup();
    await user.click(await screen.findByTestId('edit-timetable-21'));
    await user.selectOptions(document.getElementById('tt-e-course-21'), '');
    await user.click(screen.getByRole('button', { name: 'Save class' }));

    await waitFor(() => {
      const put = calls.find((c) => c.method === 'PUT');
      expect(put.body.course_id).toBeNull();
    });
  });

  it('closes the form without sending anything when editing is cancelled', async () => {
    const calls = mockRepDashboard();
    renderWithAuth(<RepDashboard />);
    const user = userEvent.setup();
    await user.click(await screen.findByTestId('edit-timetable-21'));
    await user.click(screen.getByRole('button', { name: 'Cancel editing' }));

    expect(document.getElementById('tt-e-venue-21')).toBeNull();
    expect(calls.some((c) => c.method === 'PUT')).toBe(false);
  });

  it('surfaces a stale-version conflict from the backend', async () => {
    mockRepDashboard({
      onPut: (json) => json({
        error: 'conflict',
        message: 'This timetable entry changed since the proposal was generated. '
                 + 'Re-analyse the message.',
      }, 409),
    });
    renderWithAuth(<RepDashboard />);
    const user = userEvent.setup();
    await user.click(await screen.findByTestId('edit-timetable-21'));
    await user.click(screen.getByRole('button', { name: 'Save class' }));

    expect(await screen.findByText(/changed since the proposal was generated/))
      .toBeInTheDocument();
  });

  it('surfaces a refusal when the entry is already cancelled', async () => {
    mockRepDashboard({
      onPut: (json) => json({
        error: 'conflict',
        message: 'This timetable entry has been cancelled and cannot be edited.',
      }, 409),
    });
    renderWithAuth(<RepDashboard />);
    const user = userEvent.setup();
    await user.click(await screen.findByTestId('edit-timetable-21'));
    await user.click(screen.getByRole('button', { name: 'Save class' }));

    expect(await screen.findByText(/cancelled and cannot be edited/)).toBeInTheDocument();
  });

  it('still allows removing an entry', async () => {
    const calls = mockRepDashboard();
    renderWithAuth(<RepDashboard />);
    const user = userEvent.setup();
    // Courses and timetable entries both have a "Remove" button, so target
    // the timetable one.
    await user.click(await screen.findByTestId('remove-timetable-21'));
    await waitFor(() => {
      expect(calls.some((c) => c.path === '/community/timetable/21'
                               && c.method === 'DELETE')).toBe(true);
    });
  });
});
