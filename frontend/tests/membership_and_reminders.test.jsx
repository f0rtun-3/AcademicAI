import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import CommunityMembership from '../src/components/CommunityMembership.jsx';
import PersonalReminders from '../src/components/PersonalReminders.jsx';
import ChatPage from '../src/pages/ChatPage.jsx';
import { COMMUNITY, mockApi, renderWithAuth, REP_SESSION, STUDENT_SESSION } from './helpers.jsx';

function jsonResponder(handlers) {
  globalThis.fetch = async (url, init) => {
    const path = String(url).replace(/^.*\/api/, '');
    const method = init?.method || 'GET';
    const key = `${method} ${path}`;
    const handler = handlers[key] ?? handlers[path];
    const json = (body, status = 200) => new Response(JSON.stringify(body),
      { status, headers: { 'Content-Type': 'application/json' } });
    if (!handler) return json({ error: 'not_found', message: 'Not found.' }, 404);
    const result = typeof handler === 'function' ? handler(init) : handler;
    return json(result.__body ?? result, result.__status ?? 200);
  };
}

// --- Transfer -------------------------------------------------------------

describe('community transfer', () => {
  it('sends the destination and reports that the old membership stays active', async () => {
    const calls = mockApi({
      '/auth/me': STUDENT_SESSION,
      'POST /community/transfer': {
        membership: { status: 'PENDING_APPROVAL' },
        destination: { ...COMMUNITY, level: '300' },
        awaiting_approval: true,
      },
    });
    renderWithAuth(<CommunityMembership community={COMMUNITY}
                                        membership={{ user_id: 2, role: 'STUDENT' }} />);
    const user = userEvent.setup();
    await user.clear(screen.getByLabelText('Level'));
    await user.type(screen.getByLabelText('Level'), '300');
    await user.click(screen.getByRole('button', { name: 'Request transfer' }));

    await waitFor(() => {
      const call = calls.find((c) => c.path === '/community/transfer');
      expect(call).toBeTruthy();
      expect(call.body.level).toBe('300');
      expect(call.body.university).toBe('Babcock University');
    });
    expect(await screen.findByText(/you stay in your current community until a rep/i))
      .toBeInTheDocument();
  });

  it('reports an immediate transfer when the destination needs no approval', async () => {
    mockApi({
      '/auth/me': STUDENT_SESSION,
      'POST /community/transfer': {
        membership: { status: 'ACTIVE' }, destination: COMMUNITY, awaiting_approval: false,
      },
    });
    renderWithAuth(<CommunityMembership community={COMMUNITY}
                                        membership={{ user_id: 2, role: 'STUDENT' }} />);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText('Level'), '400');
    await user.click(screen.getByRole('button', { name: 'Request transfer' }));
    expect(await screen.findByText(/transfer complete/i)).toBeInTheDocument();
  });

  it('surfaces a backend refusal, such as a domain mismatch', async () => {
    jsonResponder({
      '/auth/me': STUDENT_SESSION,
      'POST /community/transfer': {
        __status: 400,
        __body: { error: 'validation_error',
                  message: 'The email address must use an approved student email domain '
                           + 'for the selected university.' },
      },
    });
    renderWithAuth(<CommunityMembership community={COMMUNITY}
                                        membership={{ user_id: 2, role: 'STUDENT' }} />);
    const user = userEvent.setup();
    await user.clear(screen.getByLabelText('University'));
    await user.type(screen.getByLabelText('University'), 'Covenant University');
    await user.type(screen.getByLabelText('Level'), '300');
    await user.click(screen.getByRole('button', { name: 'Request transfer' }));
    expect(await screen.findByText(/approved student email domain/)).toBeInTheDocument();
  });
});

// --- Leave ----------------------------------------------------------------

describe('leaving a community', () => {
  it('requires an explicit confirmation before leaving', async () => {
    const calls = mockApi({
      '/auth/me': STUDENT_SESSION,
      'POST /community/leave': { status: 'left' },
    });
    renderWithAuth(<CommunityMembership community={COMMUNITY}
                                        membership={{ user_id: 2, role: 'STUDENT' }} />);
    const user = userEvent.setup();

    await user.click(screen.getByRole('button', { name: 'Leave community' }));
    // Nothing is sent until the second, explicit confirmation.
    expect(calls.some((c) => c.path === '/community/leave')).toBe(false);
    expect(screen.getByTestId('leave-confirm')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Yes, leave' }));
    await waitFor(() => expect(calls.some((c) => c.path === '/community/leave')).toBe(true));
  });

  it('explains what leaving costs before it happens', async () => {
    mockApi({ '/auth/me': STUDENT_SESSION });
    renderWithAuth(<CommunityMembership community={COMMUNITY}
                                        membership={{ user_id: 2, role: 'STUDENT' }} />);
    const body = document.body.textContent;
    expect(body).toMatch(/drops your course enrolments/i);
    expect(body).toMatch(/stops its notifications/i);
  });

  it('can be cancelled without sending anything', async () => {
    const calls = mockApi({ '/auth/me': STUDENT_SESSION });
    renderWithAuth(<CommunityMembership community={COMMUNITY}
                                        membership={{ user_id: 2, role: 'STUDENT' }} />);
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: 'Leave community' }));
    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(screen.queryByTestId('leave-confirm')).not.toBeInTheDocument();
    expect(calls.some((c) => c.path === '/community/leave')).toBe(false);
  });
});

// --- Personal reminders ---------------------------------------------------

const REMINDERS = [
  { id: 11, title: 'Finish COS202 draft', remind_at: '2026-09-19T08:00:00+00:00',
    status: 'PENDING', event_id: null },
  { id: 12, title: 'Linked to an event', remind_at: '2026-09-20T08:00:00+00:00',
    status: 'PENDING', event_id: 4 },
  { id: 13, title: 'Already sent', remind_at: '2026-09-10T08:00:00+00:00',
    status: 'SENT', event_id: null },
];

describe('personal reminders', () => {
  it('lists the student\'s reminders with their timing and status', async () => {
    mockApi({ '/auth/me': STUDENT_SESSION, '/reminders': { reminders: REMINDERS } });
    renderWithAuth(<PersonalReminders />);
    expect(await screen.findByText('Finish COS202 draft')).toBeInTheDocument();
    // A sent reminder says so in words; a scheduled one is the normal case
    // and carries no badge at all.
    expect(screen.getByText('Sent')).toBeInTheDocument();
    expect(screen.queryByText(/^(PENDING|Pending|Scheduled)$/)).not.toBeInTheDocument();
    expect(screen.getByText(/linked to an academic event/)).toBeInTheDocument();
  });

  it('creates a reminder', async () => {
    const calls = mockApi({
      '/auth/me': STUDENT_SESSION, '/reminders': { reminders: [] },
      'POST /reminders': { reminder: REMINDERS[0] },
    });
    renderWithAuth(<PersonalReminders />);
    const user = userEvent.setup();
    await screen.findByText('You have no personal reminders.');
    await user.type(screen.getByLabelText('Reminder title'), 'Revise for the quiz');
    await user.type(screen.getByLabelText('Remind me at'), '2026-09-21T08:00');
    await user.click(screen.getByRole('button', { name: 'Add reminder' }));

    await waitFor(() => {
      const call = calls.find((c) => c.path === '/reminders' && c.method === 'POST');
      expect(call.body.title).toBe('Revise for the quiz');

      // The input is LOCAL wall-clock and the API stores an instant, so what
      // goes on the wire is the UTC equivalent — not the typed digits with a
      // "+00:00" glued on, which is what it used to send and which set every
      // reminder an hour late in Lagos.
      //
      // Asserted by round-tripping rather than against a fixed string, so the
      // test means the same thing in every timezone it is run in.
      expect(call.body.remind_at).toMatch(/Z$/);
      const sent = new Date(call.body.remind_at);
      expect(sent.getFullYear()).toBe(2026);
      expect(sent.getMonth()).toBe(8);      // September
      expect(sent.getDate()).toBe(21);
      expect(sent.getHours()).toBe(8);      // 08:00 as the reader set it
      expect(sent.getMinutes()).toBe(0);
    });
  });

  it('edits a reminder', async () => {
    const calls = mockApi({
      '/auth/me': STUDENT_SESSION, '/reminders': { reminders: REMINDERS },
      'PUT /reminders/11': { reminder: { ...REMINDERS[0], title: 'Renamed' } },
    });
    renderWithAuth(<PersonalReminders />);
    const user = userEvent.setup();
    await user.click(await screen.findByTestId('edit-11'));
    // Both the edit form and the create form label a field "Reminder title";
    // target the one belonging to this reminder.
    const titleField = document.getElementById('r-title-11');
    await user.clear(titleField);
    await user.type(titleField, 'Renamed');
    await user.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => {
      const call = calls.find((c) => c.path === '/reminders/11' && c.method === 'PUT');
      expect(call.body.title).toBe('Renamed');
    });
  });

  it('cancels a reminder', async () => {
    const calls = mockApi({
      '/auth/me': STUDENT_SESSION, '/reminders': { reminders: REMINDERS },
      'DELETE /reminders/11': { status: 'cancelled' },
    });
    renderWithAuth(<PersonalReminders />);
    const user = userEvent.setup();
    await user.click(await screen.findByTestId('cancel-11'));
    await waitFor(() => {
      expect(calls.some((c) => c.path === '/reminders/11' && c.method === 'DELETE')).toBe(true);
    });
  });

  it('offers no edit or cancel control for a reminder already sent', async () => {
    mockApi({ '/auth/me': STUDENT_SESSION, '/reminders': { reminders: REMINDERS } });
    renderWithAuth(<PersonalReminders />);
    await screen.findByText('Already sent');
    expect(screen.queryByTestId('edit-13')).not.toBeInTheDocument();
    expect(screen.queryByTestId('cancel-13')).not.toBeInTheDocument();
  });

  it('says these are private and not official records', async () => {
    mockApi({ '/auth/me': STUDENT_SESSION, '/reminders': { reminders: [] } });
    renderWithAuth(<PersonalReminders />);
    await screen.findByText('You have no personal reminders.');
    expect(document.body.textContent).toMatch(/not official academic records/i);
  });
});

// --- Chat history ---------------------------------------------------------

describe('AI chat history', () => {
  it('restores the previous conversation when the page opens', async () => {
    const calls = mockApi({
      '/auth/me': REP_SESSION,
      '/chat/prompts': { prompts: ['What is my next deadline?'] },
      '/chat/history': { conversations: [{ id: 42, title: 'Earlier', updated_at: 'x' }] },
      '/chat/history?conversation_id=42': {
        conversation_id: 42,
        messages: [
          { role: 'user', content: 'What is due this week?', created_at: 'a' },
          { role: 'assistant', content: 'COS202 assignment on Friday.', created_at: 'b' },
        ],
      },
    });
    renderWithAuth(<ChatPage />);

    expect(await screen.findByText('What is due this week?')).toBeInTheDocument();
    expect(screen.getByText('COS202 assignment on Friday.')).toBeInTheDocument();
    expect(calls.some((c) => c.path === '/chat/history')).toBe(true);
  });

  it('continues the restored conversation rather than starting a new one', async () => {
    const calls = mockApi({
      '/auth/me': REP_SESSION,
      '/chat/prompts': { prompts: [] },
      '/chat/history': { conversations: [{ id: 42, title: 'Earlier', updated_at: 'x' }] },
      '/chat/history?conversation_id=42': {
        conversation_id: 42,
        messages: [{ role: 'user', content: 'Earlier question', created_at: 'a' }],
      },
      'POST /chat': { answer: 'Answered.', conversation_id: 42, grounded: true },
    });
    renderWithAuth(<ChatPage />);
    const user = userEvent.setup();
    await screen.findByText('Earlier question');

    await user.type(screen.getByLabelText('Your question'), 'And after that?');
    await user.click(screen.getByRole('button', { name: /Ask|Asking/ }));

    await waitFor(() => {
      const ask = calls.find((c) => c.path === '/chat' && c.method === 'POST');
      expect(ask).toBeTruthy();
      // The existing thread is continued.
      expect(ask.body.conversation_id).toBe(42);
    });
    expect(await screen.findByText('Answered.')).toBeInTheDocument();
  });

  it('starts cleanly when there is no history', async () => {
    mockApi({
      '/auth/me': REP_SESSION,
      '/chat/prompts': { prompts: [] },
      '/chat/history': { conversations: [] },
    });
    renderWithAuth(<ChatPage />);
    await waitFor(() =>
      expect(screen.queryByText('Loading your conversation…')).not.toBeInTheDocument());
    expect(screen.getByLabelText('Your question')).toBeInTheDocument();
  });

  it('still allows a new question if history cannot be loaded', async () => {
    jsonResponder({
      '/auth/me': REP_SESSION,
      '/chat/prompts': { prompts: [] },
      '/chat/history': { __status: 500, __body: { error: 'internal_error', message: 'boom' } },
      'POST /chat': { answer: 'Fine.', conversation_id: 1, grounded: true },
    });
    renderWithAuth(<ChatPage />);
    const user = userEvent.setup();
    await waitFor(() =>
      expect(screen.queryByText('Loading your conversation…')).not.toBeInTheDocument());
    await user.type(screen.getByLabelText('Your question'), 'Hello');
    await user.click(screen.getByRole('button', { name: /Ask|Asking/ }));
    expect(await screen.findByText('Fine.')).toBeInTheDocument();
  });
});
