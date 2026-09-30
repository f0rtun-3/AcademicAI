// Event detail as a route, and the rep edit path it carries.
//
// The spec makes this a ROUTE rather than a panel so a record is linkable and
// survives a refresh. Editing is the rep's primary action here, and it is the
// one place a rep changes an official record outside the AI proposal flow.

import { screen, within, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import EventDetailPage from '../src/pages/EventDetailPage.jsx';
import { mockApi, renderAtRoute, REP_SESSION, STUDENT_SESSION } from './helpers.jsx';

const EVENT = {
  id: 7, course_id: 1, course_code: 'COS202', event_type: 'ASSIGNMENT',
  title: 'COS202 Assignment', event_date: '2026-09-18', event_time: null,
  venue: 'LT1', priority: 'NORMAL', status: 'SCHEDULED', version: 3,
  original_message: 'cos 202 assignment on friday', created_at: '2026-09-15',
  completed: false,
};

const HISTORY = [
  { id: 1, entity_type: 'academic_event', entity_id: 7, change_type: 'EVENT_CREATED',
    old_value: null, new_value: { title: 'COS202 Assignment' }, actor_id: 1,
    actor_name: 'Ada Rep', created_at: '2026-09-12' },
  { id: 2, entity_type: 'academic_event', entity_id: 7, change_type: 'DEADLINE_CHANGED',
    old_value: { event_date: '2026-09-15' }, new_value: { event_date: '2026-09-18' },
    actor_id: 1, actor_name: 'Ada Rep', created_at: '2026-09-16' },
];

function open(routes) {
  const calls = mockApi(routes);
  renderAtRoute('/events/:eventId', <EventDetailPage />, { route: '/events/7' });
  return calls;
}

const ORIGINAL_TZ = process.env.TZ;
afterEach(() => {
  vi.useRealTimers();
  process.env.TZ = ORIGINAL_TZ;
});

describe('event detail', () => {
  it('shows the current facts, the history and the original message', async () => {
    open({ '/auth/me': STUDENT_SESSION, '/events/7': { event: EVENT, history: HISTORY } });

    expect(await screen.findByRole('heading', { name: 'COS202 Assignment' }))
      .toBeInTheDocument();
    // The due date now appears in TWO places — the record, and the change
    // history line that moved it — so this is scoped to the record rather than
    // matching the whole document.
    const record = screen.getByText('Due').closest('.panel');
    expect(within(record).getByText('Friday 18 September 2026')).toBeInTheDocument();
    expect(screen.getByText('LT1')).toBeInTheDocument();
    // "Not specified" is shown as a VALUE, not as an omission.
    expect(screen.getAllByText('Not specified').length).toBeGreaterThan(0);

    // History is written for a student: each change is a sentence, and its
    // detail says from what to what, with spoken dates.
    const history = screen.getByRole('heading', { name: 'What changed' }).closest('.board');
    expect(within(history).getByText('The deadline was updated.')).toBeInTheDocument();
    expect(within(history).getByText(
      'Deadline moved from Tuesday 15 September to Friday 18 September.')).toBeInTheDocument();
    expect(within(history).getByText('A new assignment was added.')).toBeInTheDocument();
    expect(within(history).getAllByText(/By Ada Rep/).length).toBe(2);
    // ...and none of the audit log's own language reaches the page.
    const text = history.textContent;
    expect(text).not.toMatch(/deadline changed|event created|event_type|_|→|\d{4}-\d{2}-\d{2}/i);
    expect(screen.getByText('cos 202 assignment on friday')).toBeInTheDocument();
  });

  it('offers a student a reminder, created only on an explicit submit', async () => {
    // Only Date is faked: faking timers too would stall userEvent. The DEVICE
    // is in London on purpose: the university (Babcock) is on Lagos time, and
    // the device's zone must not move the reminder.
    vi.useFakeTimers({ toFake: ['Date'], now: new Date('2026-09-15T09:00:00Z') });
    process.env.TZ = 'Europe/London';
    const calls = open({
      '/auth/me': STUDENT_SESSION,
      // The backend's default: 08:00 on the academic day before, Lagos clock.
      '/events/7': { event: EVENT, history: [], reminder_default_local: '2026-09-17T08:00' },
      'POST /reminders': { reminder: { id: 1, title: 'Prepare for COS202 Assignment',
                                       remind_at: '2026-09-17T07:00:00+00:00',
                                       remind_at_local: '2026-09-17T08:00',
                                       timezone: 'Africa/Lagos',
                                       status: 'PENDING', event_id: 7 } },
    });
    const user = userEvent.setup();

    await user.click(await screen.findByRole('button', { name: 'Add a reminder' }));
    // Nothing is created by opening the offer.
    expect(calls.some((c) => c.path === '/reminders' && c.method === 'POST')).toBe(false);

    await user.click(screen.getByRole('button', { name: 'Create reminder' }));
    await waitFor(() => {
      const call = calls.find((c) => c.path === '/reminders' && c.method === 'POST');
      expect(call).toBeTruthy();
      // Linked to the event, defaulting to 08:00 the morning before on the
      // university's clock, and sent as that wall-clock time: the backend
      // attaches Lagos's zone. No instant is computed from the London device.
      expect(call.body.event_id).toBe(7);
      expect(call.body.remind_at_local).toBe('2026-09-17T08:00');
      expect(call.body.remind_at).toBeUndefined();
    });
    expect(await screen.findByText(/Only you can see it/)).toBeInTheDocument();
  });

  it('lets a rep edit, and sends the version so a stale form cannot overwrite', async () => {
    const calls = open({
      '/auth/me': REP_SESSION,
      '/events/7': { event: EVENT, history: [] },
      'PUT /events/7': { event: { ...EVENT, venue: 'B107', version: 4 },
                         applied_changes: { venue: 'B107' } },
    });
    const user = userEvent.setup();

    await user.click(await screen.findByRole('button', { name: 'Edit' }));
    // The consequences of publishing a change are stated before saving. The
    // wording says "notifies", not "emails": no email provider is connected,
    // and the warning must describe what actually happens.
    expect(screen.getByText(/notifies every student enrolled on this course/i))
      .toBeInTheDocument();

    const venue = screen.getByLabelText('Venue');
    await user.clear(venue);
    await user.type(venue, 'B107');
    await user.click(screen.getByRole('button', { name: 'Save and notify students' }));

    await waitFor(() => {
      const call = calls.find((c) => c.path === '/events/7' && c.method === 'PUT');
      expect(call).toBeTruthy();
      expect(call.body.venue).toBe('B107');
      // Optimistic concurrency: the read version travels with the write.
      expect(call.body.expected_version).toBe(3);
    });
    // The publisher is named. The AI must never appear to have published.
    expect(await screen.findByText(/Updated by you/)).toBeInTheDocument();
  });

  it('surfaces a stale edit as the backend refused it, with no force option', async () => {
    open({
      '/auth/me': REP_SESSION,
      '/events/7': { event: EVENT, history: [] },
      'PUT /events/7': () => ({
        __status: 409, error: 'stale_proposal',
        message: 'This event changed since the proposal was generated. Re-analyse the message.',
        details: { current_version: 5 },
      }),
    });
    const user = userEvent.setup();

    await user.click(await screen.findByRole('button', { name: 'Edit' }));
    await user.click(screen.getByRole('button', { name: 'Save and notify students' }));

    // The backend's own sentence, verbatim — and never an overwrite offer.
    expect(await screen.findByText(/This event changed since the proposal was generated/))
      .toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /force|overwrite|anyway/i }))
      .not.toBeInTheDocument();
  });

  it('relays a revoked-authority refusal rather than trusting local role state', async () => {
    open({
      '/auth/me': REP_SESSION,                    // the session still says rep
      '/events/7': { event: EVENT, history: [] },
      'PUT /events/7': () => ({
        __status: 403, error: 'forbidden',
        message: 'Only a verified course rep can change official events.',
      }),
    });
    const user = userEvent.setup();

    await user.click(await screen.findByRole('button', { name: 'Edit' }));
    await user.click(screen.getByRole('button', { name: 'Save and notify students' }));

    expect(await screen.findByText(/Only a verified course rep can change official events/))
      .toBeInTheDocument();
  });

  it('removes every write control once the session is archived', async () => {
    open({
      '/auth/me': REP_SESSION,
      '/events/7': { event: { ...EVENT, status: 'ARCHIVED' }, history: [] },
    });
    await screen.findByRole('heading', { name: 'COS202 Assignment' });
    expect(screen.getByText(/no longer accepts changes/i)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Edit' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Cancel event' })).not.toBeInTheDocument();
    // Personal completion is not a community write, so it survives.
    expect(screen.getByRole('button', { name: /Mark complete/ })).toBeInTheDocument();
  });

  it('does not confirm that a record outside the community exists', async () => {
    open({
      '/auth/me': STUDENT_SESSION,
      '/events/7': () => ({ __status: 404, error: 'not_found', message: 'Event not found.' }),
    });
    expect(await screen.findByText(/isn’t in your community/)).toBeInTheDocument();
  });
});

// ── Optional supporting material (S7 extension) ─────────────────────────────
//
// The product rule under test is an ABSENCE: an assignment or project with no
// attachment is a complete record, and the interface must never imply it is
// missing something. Everything else here is the authority model, unchanged.

const MATERIAL = {
  id: 4, event_id: 7, filename: 'COS202_Assignment1.pdf',
  content_type: 'application/pdf', byte_size: 24576,
  uploaded_at: '2026-09-16', uploaded_by: 1,
};

const WITH_INSTRUCTIONS = {
  ...EVENT,
  description: 'Write a Python program that demonstrates the use of functions.',
  attachments: [],
};

describe('supporting material', () => {
  it('shows typed instructions exactly as the rep wrote them', async () => {
    open({ '/auth/me': STUDENT_SESSION,
           '/events/7': { event: WITH_INSTRUCTIONS, history: [] } });

    expect(await screen.findByText(/Write a Python program/)).toBeInTheDocument();
  });

  it('shows a student NO supporting-material panel when nothing is attached',
     async () => {
    // The core guarantee. An empty "no attachments" box would tell a student
    // that a complete record is incomplete.
    open({ '/auth/me': STUDENT_SESSION,
           '/events/7': { event: WITH_INSTRUCTIONS, history: [] } });

    await screen.findByText(/Write a Python program/);
    expect(screen.queryByText('Supporting material')).not.toBeInTheDocument();
    expect(screen.queryByText(/Add attachment/)).not.toBeInTheDocument();
  });

  it('lets a student open the original without offering any way to change it',
     async () => {
    open({ '/auth/me': STUDENT_SESSION,
           '/events/7': { event: { ...EVENT, attachments: [MATERIAL] }, history: [] } });

    expect(await screen.findByText('COS202_Assignment1.pdf')).toBeInTheDocument();
    expect(screen.getByText('24 KB')).toBeInTheDocument();
    // Reading it in the page and saving it are separate acts, and a PDF can
    // do both.
    expect(screen.getByRole('button', { name: 'View' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Download' })).toBeInTheDocument();
    // A student may read official material and never modify it.
    expect(screen.queryByRole('button', { name: 'Remove' })).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/Add supporting material/)).not.toBeInTheDocument();
  });

  it('tells a rep the attachment is optional, with nothing attached', async () => {
    open({ '/auth/me': REP_SESSION,
           '/events/7': { event: WITH_INSTRUCTIONS, history: [] } });

    expect(await screen.findByLabelText(/Add supporting material \(optional\)/))
      .toBeInTheDocument();
    expect(screen.getByText(/Nothing attached, and nothing needs to be/))
      .toBeInTheDocument();
    // Nothing is selected, so there is nothing to submit yet.
    expect(screen.getByRole('button', { name: 'Add attachment' })).toBeDisabled();
  });

  it('uploads as multipart to the event that owns it', async () => {
    const calls = open({
      '/auth/me': REP_SESSION,
      '/events/7': { event: WITH_INSTRUCTIONS, history: [] },
      'POST /events/7/attachments': { attachment: MATERIAL },
    });
    const user = userEvent.setup();
    const field = await screen.findByLabelText(/Add supporting material/);
    await user.upload(field, new File(['%PDF-1.4'], 'brief.pdf',
                                      { type: 'application/pdf' }));
    await user.click(screen.getByRole('button', { name: 'Add attachment' }));

    await waitFor(() => {
      const post = calls.find((c) => c.path === '/events/7/attachments'
                                     && c.method === 'POST');
      expect(post).toBeTruthy();
    });
  });

  it('lets a rep withdraw material, addressed through its own event', async () => {
    const calls = open({
      '/auth/me': REP_SESSION,
      '/events/7': { event: { ...EVENT, attachments: [MATERIAL] }, history: [] },
      'DELETE /events/7/attachments/4': { removed: true },
    });
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Remove' }));

    await waitFor(() => {
      const del = calls.find((c) => c.path === '/events/7/attachments/4'
                                    && c.method === 'DELETE');
      expect(del).toBeTruthy();
    });
  });

  it('survives a response with no attachments key at all', async () => {
    // An older cached payload must not take the route down over an optional
    // field. EVENT here deliberately has no `attachments`.
    open({ '/auth/me': STUDENT_SESSION, '/events/7': { event: EVENT, history: [] } });
    expect(await screen.findByRole('heading', { name: 'COS202 Assignment' }))
      .toBeInTheDocument();
  });
});

// ── Viewing in the page ────────────────────────────────────────────────────

describe('supporting material · viewing', () => {
  it('opens a readable preview in a dialog rather than the downloads folder',
     async () => {
    open({ '/auth/me': STUDENT_SESSION,
           '/events/7': { event: { ...EVENT, attachments: [MATERIAL] }, history: [] } });
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'View' }));

    const dialog = await screen.findByRole('dialog');
    expect(dialog).toHaveAccessibleName('COS202_Assignment1.pdf');
    // Saving is still one click away, from inside the viewer.
    expect(within(dialog).getByRole('button', { name: 'Download' })).toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: 'Close' })).toBeInTheDocument();
  });

  it('offers no View for a format the browser cannot render', async () => {
    // Word documents need a converter. Pretending to preview one would open
    // an empty frame and leave the reader guessing.
    const doc = {
      ...MATERIAL, id: 9, filename: 'brief.docx',
      content_type:
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    };
    open({ '/auth/me': STUDENT_SESSION,
           '/events/7': { event: { ...EVENT, attachments: [doc] }, history: [] } });

    expect(await screen.findByText('brief.docx')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Download' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'View' })).not.toBeInTheDocument();
  });
});
