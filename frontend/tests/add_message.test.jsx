import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import AddMessage from '../src/pages/AddMessage.jsx';
import { mockApi, renderWithAuth, REP_SESSION, STUDENT_SESSION } from './helpers.jsx';

const COURSES = { courses: [{ id: 1, code: 'COS202', title: 'Data Structures', version: 1 }] };

function proposal(overrides = {}) {
  return {
    action: 'CREATE', scope: 'EVENT', course_code: 'COS202', event_type: 'ASSIGNMENT',
    title: 'COS202 Assignment', event_date: '2026-09-18', event_time: null, venue: null,
    day_of_week: null, priority: 'NORMAL', old_value: null, new_value: null,
    confidence: 0.8, needs_clarification: false, possible_match_id: null,
    matching_confidence: null, explanation: 'New assignment for COS202 on 2026-09-18.',
    clarification_question: null, discrepancies: [], community_id: 1,
    original_message: 'cos 202 assignment on friday', matched_record: null,
    expected_version: null, publishable: true, ...overrides,
  };
}

async function analyse(user, text = 'cos 202 assignmentto be submittted on friday') {
  await user.type(screen.getByLabelText('Original message'), text);
  await user.click(screen.getByRole('button', { name: 'Analyse message' }));
}

describe('Add Message', () => {
  it('shows a CREATE proposal with the parsed fields and a publish action', async () => {
    mockApi({
      '/auth/me': REP_SESSION,
      '/community/courses': COURSES,
      'POST /ai/analyze-message': { proposal: proposal() },
    });
    const user = userEvent.setup();
    renderWithAuth(<AddMessage />);
    await screen.findByLabelText('Original message');
    await analyse(user);

    // The proposal kind and the date are in words, not tokens.
    expect(await screen.findByText('New record')).toBeInTheDocument();
    expect(screen.getByText('Friday 18 September 2026')).toBeInTheDocument();
    expect(screen.getByText('AcademicAI is confident about this reading.')).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/CREATE|confidence \d|\d+%/);
    expect(screen.getByRole('button', { name: 'Confirm & Publish' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Edit' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Discard' })).toBeInTheDocument();
  });

  // ── The Course field ───────────────────────────────────────────────────
  //
  // It is free text, not a picklist: a rep pasting "cos 202 quiz on friday"
  // already knows the code, and in a community whose rep has not published a
  // course list the old <select> had nothing in it at all.
  //
  // The rule it must not break: a course is a rep-curated record, and an event
  // may only point at one that already exists. The client never creates one
  // and never decides the answer — it resolves what was typed against the
  // published list only to choose which field to send, and to warn early.

  it('accepts a typed course code, normalising it the way the backend does',
     async () => {
    const calls = mockApi({
      '/auth/me': REP_SESSION,
      '/community/courses': COURSES,
      'POST /ai/analyze-message': { proposal: proposal() },
      'POST /ai/publish': { published: true },
    });
    const user = userEvent.setup();
    renderWithAuth(<AddMessage />);
    await screen.findByLabelText('Original message');

    // Lower case and an inner space, as a person would actually type it.
    await user.type(screen.getByLabelText('Course'), 'cos 202');
    // It matches COS202, so nothing warns.
    expect(screen.queryByText(/is not a course in this community/)).not.toBeInTheDocument();

    await analyse(user);
    // /ai/analyze-message takes an id, so a matched code resolves to one.
    const sent = calls.find((c) => c.path === '/ai/analyze-message');
    expect(sent.body.course_id).toBe(1);

    await user.click(await screen.findByRole('button', { name: 'Confirm & Publish' }));
    await waitFor(() => {
      const pub = calls.find((c) => c.path === '/ai/publish');
      // Publishing sends the CODE, normalised. The backend re-resolves it.
      expect(pub.body.course_code).toBe('COS202');
    });
  });

  it('warns a rep about a code that is not in the list, and still lets the '
     + 'backend decide', async () => {
    const calls = mockApi({
      '/auth/me': REP_SESSION,
      '/community/courses': COURSES,
      'POST /ai/analyze-message': { proposal: proposal() },
      'POST /ai/publish': { published: true },
    });
    const user = userEvent.setup();
    renderWithAuth(<AddMessage />);
    await screen.findByLabelText('Original message');

    await user.type(screen.getByLabelText('Course'), 'COS301');
    expect(await screen.findByText(/COS301 is not a course in this community yet/))
      .toBeInTheDocument();

    await analyse(user);
    // Nothing to bias the AI's context with, so no id is claimed.
    const sent = calls.find((c) => c.path === '/ai/analyze-message');
    expect(sent.body.course_id).toBeUndefined();

    // The warning does not block. The request goes, and the backend's
    // refusal is what the rep reads.
    await user.click(await screen.findByRole('button', { name: 'Confirm & Publish' }));
    await waitFor(() => {
      const pub = calls.find((c) => c.path === '/ai/publish');
      expect(pub.body.course_code).toBe('COS301');
    });
  });

  it('says so when the community has no published course list', async () => {
    // A select whose only option is "No specific course" must explain why.
    mockApi({
      '/auth/me': REP_SESSION,
      '/community/courses': { courses: [] },
      'POST /ai/analyze-message': { proposal: proposal() },
    });
    const user = userEvent.setup();
    renderWithAuth(<AddMessage />);
    await screen.findByLabelText('Original message');

    expect(await screen.findByText(/no published course list yet/)).toBeInTheDocument();
    // Still typeable — that is the point.
    const field = screen.getByLabelText('Course');
    await user.type(field, 'SEN201');
    expect(field).toHaveValue('SEN201');
  });

  it('shows the clarification question and refuses to publish it', async () => {
    // spec 14: an ambiguous message must not be publishable.
    mockApi({
      '/auth/me': REP_SESSION,
      '/community/courses': COURSES,
      'POST /ai/analyze-message': {
        proposal: proposal({
          action: 'CLARIFICATION', needs_clarification: true, publishable: false,
          event_date: null,
          clarification_question: 'What exact date should this be scheduled for?',
          explanation: 'The message does not state a date that can be resolved.',
        }),
      },
    });
    const user = userEvent.setup();
    renderWithAuth(<AddMessage />);
    await screen.findByLabelText('Original message');
    await analyse(user, 'presentation next two weeks');

    await screen.findByText('What exact date should this be scheduled for?');
    expect(document.querySelector('.chip')).toHaveTextContent('Needs clarification');
    expect(screen.getByText(/What exact date/)).toBeInTheDocument();
    // ABSENT, not disabled: a disabled control invites guessing at how to
    // enable it, and there is no way to enable this one.
    expect(screen.queryByRole('button', { name: 'Confirm & Publish' }))
      .not.toBeInTheDocument();
  });

  it('surfaces a stale proposal as a re-analysis prompt, not a raw error', async () => {
    // spec 17: publishing against an outdated version is a 409.
    mockApi({
      '/auth/me': REP_SESSION,
      '/community/courses': COURSES,
      'POST /ai/analyze-message': {
        proposal: proposal({ action: 'UPDATE', possible_match_id: 5, expected_version: 1 }),
      },
      'POST /ai/publish': () => ({
        __status: 409, error: 'stale_proposal',
        message: 'This event changed since the proposal was generated.',
        details: { current_version: 2 },
      }),
    });
    const user = userEvent.setup();
    renderWithAuth(<AddMessage />);
    await screen.findByLabelText('Original message');
    await analyse(user, 'deadline extended to next week monday');

    await user.click(await screen.findByRole('button', { name: 'Confirm & Publish' }));
    expect(await screen.findByText(/Analyse the message again/)).toBeInTheDocument();
  });

  it('shows a discrepancy warning when rep fields conflict with the message', async () => {
    mockApi({
      '/auth/me': REP_SESSION,
      '/community/courses': COURSES,
      'POST /ai/analyze-message': {
        proposal: proposal({
          needs_clarification: true,
          discrepancies: ['You selected COS202 but the message mentions SEN212.'],
        }),
      },
    });
    const user = userEvent.setup();
    renderWithAuth(<AddMessage />);
    await screen.findByLabelText('Original message');
    await analyse(user, 'sen212 quiz on friday');

    expect(await screen.findByText(/the message mentions SEN212/)).toBeInTheDocument();
  });

  it('gives a student a personal interpretation with no publish action', async () => {
    // spec 13: a student's paste never becomes official information.
    mockApi({
      '/auth/me': STUDENT_SESSION,
      '/community/courses': COURSES,
      'POST /ai/analyze-message': {
        proposal: proposal({
          publishable: false, personal_only: true,
          note: 'This is a personal interpretation. Only a verified course rep can publish official academic information.',
        }),
      },
    });
    const user = userEvent.setup();
    renderWithAuth(<AddMessage />);
    await screen.findByLabelText('Original message');
    await analyse(user);

    expect(await screen.findByText(/Only a verified course rep can publish/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Confirm & Publish' })).not.toBeInTheDocument();
  });

  it('disables the date field when the rep marks it as not specified', async () => {
    // spec 14: "no specified date" is an explicit answer, not a blank.
    mockApi({ '/auth/me': REP_SESSION, '/community/courses': COURSES });
    const user = userEvent.setup();
    renderWithAuth(<AddMessage />);
    await screen.findByLabelText('Original message');

    expect(screen.getByLabelText('Date')).toBeEnabled();
    await user.click(screen.getByLabelText('No specified date'));
    expect(screen.getByLabelText('Date')).toBeDisabled();
  });

  it('reports an analysis failure without losing the typed message', async () => {
    mockApi({
      '/auth/me': REP_SESSION,
      '/community/courses': COURSES,
      'POST /ai/analyze-message': () => ({
        __status: 503, error: 'service_unavailable',
        message: 'The AI service is temporarily unavailable. Please try again.',
      }),
    });
    const user = userEvent.setup();
    renderWithAuth(<AddMessage />);
    await screen.findByLabelText('Original message');
    await analyse(user, 'quiz on friday');

    expect(await screen.findByText(/temporarily unavailable/)).toBeInTheDocument();
    expect(screen.getByLabelText('Original message')).toHaveValue('quiz on friday');
  });
});

// ── Typed instructions at review time ──────────────────────────────────────
//
// The rule: instructions are OPTIONAL and publishing is unchanged without
// them. The attachment itself is never part of publishing at all — it is
// added on the event's own page afterwards — so there is nothing here that
// can block a rep from publishing.

describe('Add Message · instructions', () => {
  it('publishes with no instructions exactly as before', async () => {
    const calls = mockApi({
      '/auth/me': REP_SESSION,
      '/community/courses': COURSES,
      'POST /ai/analyze-message': { proposal: proposal() },
      'POST /ai/publish': { published: true },
    });
    const user = userEvent.setup();
    renderWithAuth(<AddMessage />);
    await screen.findByLabelText('Original message');
    await analyse(user);
    await user.click(await screen.findByRole('button', { name: 'Confirm & Publish' }));

    await waitFor(() => {
      const pub = calls.find((c) => c.path === '/ai/publish');
      expect(pub).toBeTruthy();
      expect(pub.body.description).toBeNull();
    });
  });

  it('lets a rep type instructions before publishing', async () => {
    const calls = mockApi({
      '/auth/me': REP_SESSION,
      '/community/courses': COURSES,
      'POST /ai/analyze-message': { proposal: proposal() },
      'POST /ai/publish': { published: true },
    });
    const user = userEvent.setup();
    renderWithAuth(<AddMessage />);
    await screen.findByLabelText('Original message');
    await analyse(user);

    await user.click(await screen.findByRole('button', { name: 'Edit' }));
    await user.type(screen.getByLabelText(/Instructions \(optional\)/),
                    'Write a Python program.');
    await user.click(screen.getByRole('button', { name: 'Confirm & Publish' }));

    await waitFor(() => {
      const pub = calls.find((c) => c.path === '/ai/publish');
      expect(pub.body.description).toBe('Write a Python program.');
    });
  });

  it('offers the attachment as optional and publishes fine without one',
     async () => {
    // The control is present in the creation form, but it is never a step
    // between a rep and publishing.
    const calls = mockApi({
      '/auth/me': REP_SESSION,
      '/community/courses': COURSES,
      'POST /ai/analyze-message': { proposal: proposal() },
      'POST /ai/publish': { published: { action: 'CREATE', event: { id: 12 } } },
    });
    const user = userEvent.setup();
    renderWithAuth(<AddMessage />);
    await screen.findByLabelText('Original message');
    await analyse(user);

    expect(await screen.findByLabelText(/Supporting material \(optional\)/))
      .toBeInTheDocument();
    // Nothing attached, and the publish action is ready anyway.
    expect(screen.getByRole('button', { name: 'Confirm & Publish' })).toBeEnabled();
    await user.click(screen.getByRole('button', { name: 'Confirm & Publish' }));

    await waitFor(() => {
      expect(calls.find((c) => c.path === '/ai/publish')).toBeTruthy();
    });
    // No upload was attempted, because nothing was staged.
    expect(calls.some((c) => c.path.includes('/attachments'))).toBe(false);
  });

  it('stages a file and attaches it AFTER the record is published', async () => {
    // Order matters: an attachment needs an event, and the event does not
    // exist until the proposal is published.
    const calls = mockApi({
      '/auth/me': REP_SESSION,
      '/community/courses': COURSES,
      'POST /ai/analyze-message': { proposal: proposal() },
      'POST /ai/publish': { published: { action: 'CREATE', event: { id: 12 } } },
      'POST /events/12/attachments': { attachment: { id: 3 } },
    });
    const user = userEvent.setup();
    renderWithAuth(<AddMessage />);
    await screen.findByLabelText('Original message');
    await analyse(user);

    await user.upload(await screen.findByLabelText(/Supporting material \(optional\)/),
                      new File(['%PDF-1.4'], 'brief.pdf', { type: 'application/pdf' }));
    expect(screen.getByText(/will be attached once this is published/))
      .toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Confirm & Publish' }));

    await waitFor(() => {
      const paths = calls.filter((c) => c.method === 'POST').map((c) => c.path);
      expect(paths).toContain('/ai/publish');
      expect(paths).toContain('/events/12/attachments');
      // Published first, attached second.
      expect(paths.indexOf('/ai/publish'))
        .toBeLessThan(paths.indexOf('/events/12/attachments'));
    });
  });

  it('a failed upload never says the record failed to publish', async () => {
    const calls = mockApi({
      '/auth/me': REP_SESSION,
      '/community/courses': COURSES,
      'POST /ai/analyze-message': { proposal: proposal() },
      'POST /ai/publish': { published: { action: 'CREATE', event: { id: 12 } } },
      'POST /events/12/attachments': () => ({
        __status: 400, error: 'validation_error',
        message: 'That file type is not supported.',
      }),
    });
    const user = userEvent.setup();
    renderWithAuth(<AddMessage />);
    await screen.findByLabelText('Original message');
    await analyse(user);
    await user.upload(await screen.findByLabelText(/Supporting material \(optional\)/),
                      new File(['x'], 'thing.exe', { type: 'application/x-msdownload' }));
    await user.click(screen.getByRole('button', { name: 'Confirm & Publish' }));

    // The record IS official. Saying otherwise would be a lie about the
    // database, and would invite the rep to publish it twice.
    expect(await screen.findByText(/The record was published, but/))
      .toBeInTheDocument();
    expect(screen.getByText(/could not be attached/)).toBeInTheDocument();
    expect(calls.filter((c) => c.path === '/ai/publish').length).toBe(1);
  });
});
