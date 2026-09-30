import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import CommunitySetup from '../src/pages/CommunitySetup.jsx';
import RepElections from '../src/components/RepElections.jsx';
import { COMMUNITY, mockApi, renderWithAuth, REP_SESSION, STUDENT_SESSION } from './helpers.jsx';

const PENDING_COMMUNITY = {
  ...COMMUNITY, status: 'PENDING', reps: [], member_count: 4,
  election: { eligible_members: 4, required_members: 4, preparation_threshold: 3,
              in_preparation: true, can_start_election: true, members_needed: 0 },
};

const SHORT_COMMUNITY = {
  ...PENDING_COMMUNITY, member_count: 3,
  election: { eligible_members: 3, required_members: 4, preparation_threshold: 3,
              in_preparation: true, can_start_election: false, members_needed: 1 },
};

function setupPage(routes) {
  const calls = mockApi({
    '/auth/me': { ...STUDENT_SESSION, membership: null, next_step: 'community_setup' },
    ...routes,
  });
  renderWithAuth(<CommunitySetup />);
  return calls;
}

// --- The first course-rep bootstrap ---------------------------------------

describe('first course rep bootstrap', () => {
  it('"I\'m a Student" joins without creating a candidacy', async () => {
    const calls = setupPage({
      'POST /community/setup': { community: PENDING_COMMUNITY, created: false, existed: true,
                                 message: 'Your academic community is ready.' },
      'POST /community/join': { membership: { status: 'ACTIVE', role: 'STUDENT' },
                                community: PENDING_COMMUNITY, awaiting_approval: false },
    });
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: "I'm a Student" }));

    await waitFor(() => {
      expect(calls.some((c) => c.path === '/community/join')).toBe(true);
    });
    // The student path must NOT open a ballot.
    expect(calls.some((c) => c.path === '/rep/nominate')).toBe(false);
  });

  it('"Yes, I\'m a Course Rep" joins AND submits a candidacy', async () => {
    const calls = setupPage({
      'POST /community/setup': { community: PENDING_COMMUNITY, created: false, existed: true,
                                 message: 'Your academic community is ready.' },
      'POST /community/join': { membership: { status: 'ACTIVE', role: 'STUDENT' },
                                community: PENDING_COMMUNITY, awaiting_approval: false },
      'POST /rep/nominate': { nomination: { id: 7, status: 'OPEN', candidate_id: 2 } },
    });
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: "Yes, I'm a Course Rep" }));

    await waitFor(() => {
      expect(calls.some((c) => c.path === '/community/join')).toBe(true);
      expect(calls.some((c) => c.path === '/rep/nominate')).toBe(true);
    });
    expect(await screen.findByText(/your candidacy is open/i)).toBeInTheDocument();
  });

  it('joins anyway and explains when the candidacy cannot start', async () => {
    // The backend refuses the ballot because the community is too small. The
    // student must still end up a member, and must be told why.
    globalThis.fetch = async (url, init) => {
      const path = String(url).replace(/^.*\/api/, '');
      const json = (body, status = 200) => new Response(JSON.stringify(body),
        { status, headers: { 'Content-Type': 'application/json' } });
      if (path === '/auth/me') {
        return json({ ...STUDENT_SESSION, membership: null, next_step: 'community_setup' });
      }
      if (path === '/community/setup') {
        return json({ community: SHORT_COMMUNITY, created: false, existed: true,
                      message: 'Your academic community is ready.' });
      }
      if (path === '/community/join') {
        return json({ membership: { status: 'ACTIVE', role: 'STUDENT' },
                      community: SHORT_COMMUNITY, awaiting_approval: false });
      }
      if (path === '/rep/nominate') {
        return json({ error: 'conflict',
                      message: 'A rep election needs at least 3 eligible voters besides '
                               + 'the candidate.' }, 409);
      }
      return json({}, 404);
    };

    renderWithAuth(<CommunitySetup />, { route: '/community-setup' });
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: "Yes, I'm a Course Rep" }));

    expect(await screen.findByText(/you have joined this community, but your candidacy could not start/i))
      .toBeInTheDocument();
    expect(screen.getByText(/3 eligible voters besides the candidate/)).toBeInTheDocument();
  });

  it('states the shortfall before anyone tries to stand', async () => {
    setupPage({
      'POST /community/setup': { community: SHORT_COMMUNITY, created: true, existed: false,
                                 message: "Your academic community hasn't been set up yet." },
    });
    expect(await screen.findByText(/1 more needed right now/)).toBeInTheDocument();
  });
});

// --- Election ballots -----------------------------------------------------

function renderElections({ community, membership, candidates = [], removals = [] }) {
  const calls = mockApi({
    '/auth/me': REP_SESSION,
    '/rep/candidates': { candidates },
    '/rep/removals': { removals },
    'POST /rep/nominate': { nomination: { id: 9 } },
    'POST /rep/candidates/5/vote': { tally: { yes: 1, no: 0 } },
    'POST /rep/removals/8/vote': { tally: { yes: 1, no: 0 } },
    'POST /rep/removals': { removal: { id: 8 } },
  });
  renderWithAuth(<RepElections community={community} membership={membership} />);
  return calls;
}

const OPEN_BALLOT = {
  id: 5, candidate_id: 3, full_name: 'Chidi Student', status: 'OPEN',
  opened_at: '2026-09-15T09:00:00+00:00', closes_at: '2026-09-16T09:00:00+00:00',
  resolved_at: null, yes_votes: 1, no_votes: 0, min_votes_required: 3,
  is_me: false, my_vote: null, can_vote: true,
};

describe('rep election ballots', () => {
  it('shows an open ballot with its tally and lets an eligible member vote', async () => {
    const calls = renderElections({
      community: COMMUNITY,
      membership: { user_id: 1, role: 'STUDENT' },
      candidates: [OPEN_BALLOT],
    });
    const user = userEvent.setup();
    expect(await screen.findByText('Chidi Student')).toBeInTheDocument();
    expect(screen.getByText(/1 yes · 0 no · 3 votes needed/)).toBeInTheDocument();

    await user.click(screen.getByTestId('candidate-5-yes'));
    await waitFor(() => {
      const vote = calls.find((c) => c.path === '/rep/candidates/5/vote');
      expect(vote).toBeTruthy();
      expect(vote.body.vote).toBe('YES');
    });
  });

  it('offers no vote control when the backend says the member cannot vote', async () => {
    renderElections({
      community: COMMUNITY,
      membership: { user_id: 3, role: 'STUDENT' },
      candidates: [{ ...OPEN_BALLOT, is_me: true, can_vote: false }],
    });
    await screen.findByText('Chidi Student');
    // A candidate may not vote on their own nomination.
    expect(screen.queryByTestId('candidate-5-yes')).not.toBeInTheDocument();
  });

  it('shows how the member already voted instead of a vote control', async () => {
    renderElections({
      community: COMMUNITY,
      membership: { user_id: 1, role: 'STUDENT' },
      candidates: [{ ...OPEN_BALLOT, my_vote: 'NO', can_vote: false }],
    });
    expect(await screen.findByText(/you voted no/)).toBeInTheDocument();
    expect(screen.queryByTestId('candidate-5-yes')).not.toBeInTheDocument();
  });

  it('shows a resolved outcome with final counts', async () => {
    renderElections({
      community: COMMUNITY,
      membership: { user_id: 1, role: 'STUDENT' },
      candidates: [{ ...OPEN_BALLOT, status: 'PASSED', can_vote: false,
                     yes_votes: 3, no_votes: 0, resolved_at: '2026-09-16T09:00:00+00:00' }],
    });
    expect(await screen.findByText('Passed')).toBeInTheDocument();
    expect(screen.getByText(/3 yes · 0 no/)).toBeInTheDocument();
  });

  it('surfaces the backend refusal verbatim when a vote is rejected', async () => {
    globalThis.fetch = async (url) => {
      const path = String(url).replace(/^.*\/api/, '');
      const json = (b, s = 200) => new Response(JSON.stringify(b),
        { status: s, headers: { 'Content-Type': 'application/json' } });
      if (path === '/auth/me') return json(REP_SESSION);
      if (path === '/rep/candidates') return json({ candidates: [OPEN_BALLOT] });
      if (path === '/rep/removals') return json({ removals: [] });
      if (path === '/rep/candidates/5/vote') {
        return json({ error: 'conflict',
                      message: 'You have already voted on this nomination.' }, 409);
      }
      return json({}, 404);
    };
    renderWithAuth(<RepElections community={COMMUNITY}
                                 membership={{ user_id: 1, role: 'STUDENT' }} />);
    const user = userEvent.setup();
    await user.click(await screen.findByTestId('candidate-5-yes'));
    expect(await screen.findByText(/already voted on this nomination/)).toBeInTheDocument();
  });

  it('lets a member with no candidacy stand for election', async () => {
    const calls = renderElections({
      community: COMMUNITY, membership: { user_id: 1, role: 'STUDENT' }, candidates: [],
    });
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Stand for election' }));
    await waitFor(() => expect(calls.some((c) => c.path === '/rep/nominate')).toBe(true));
  });

  it('handles a community with no verified rep', async () => {
    renderElections({
      community: { ...COMMUNITY, reps: [] },
      membership: { user_id: 1, role: 'STUDENT' },
    });
    // The empty board is now the shared EmptyState rather than a bare row, so
    // the sentence became a title and lost its full stop. Still an exact-text
    // assertion on the same message; nothing was relaxed.
    expect(await screen.findByText('No nominations yet')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Stand for election' })).toBeInTheDocument();
  });
});

// --- Removal ballots ------------------------------------------------------

const OPEN_REMOVAL = {
  id: 8, target_user_id: 1, target_name: 'Ada Rep', status: 'OPEN',
  opened_at: '2026-09-15T09:00:00+00:00', closes_at: '2026-09-16T09:00:00+00:00',
  resolved_at: null, yes_votes: 2, no_votes: 0, min_votes_required: 3,
  is_me: false, my_vote: null, can_vote: true,
};

describe('rep removal ballots', () => {
  it('lets a verified rep start a removal for another rep', async () => {
    const calls = renderElections({
      community: { ...COMMUNITY,
                   reps: [{ id: 1, full_name: 'Ada Rep' }, { id: 4, full_name: 'Bola Rep' }] },
      membership: { user_id: 1, role: 'VERIFIED_REP' },
    });
    const user = userEvent.setup();
    await user.click(await screen.findByTestId('remove-4'));

    // A removal is hard to undo, so its consequences are read first.
    const dialog = await screen.findByRole('dialog');
    expect(dialog).toHaveTextContent(/24 hours/);
    expect(dialog).toHaveTextContent(/loses rep authority immediately/);
    expect(dialog).toHaveTextContent(/stays in the community as a student/);

    // Nothing is sent until the rep confirms.
    expect(calls.some((c) => c.path === '/rep/removals' && c.method === 'POST')).toBe(false);

    await user.click(within(dialog).getByRole('button', { name: 'Start removal vote' }));
    await waitFor(() => {
      // The component also GETs this path on mount, so match the POST.
      const call = calls.find((c) => c.path === '/rep/removals' && c.method === 'POST');
      expect(call).toBeTruthy();
      expect(call.body.target_user_id).toBe(4);
    });
  });

  it('cancelling the removal dialog sends nothing', async () => {
    const calls = renderElections({
      community: { ...COMMUNITY,
                   reps: [{ id: 1, full_name: 'Ada Rep' }, { id: 4, full_name: 'Bola Rep' }] },
      membership: { user_id: 1, role: 'VERIFIED_REP' },
    });
    const user = userEvent.setup();
    await user.click(await screen.findByTestId('remove-4'));
    const dialog = await screen.findByRole('dialog');
    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }));

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(calls.some((c) => c.path === '/rep/removals' && c.method === 'POST')).toBe(false);
  });

  it('does not offer removal to a plain student', async () => {
    renderElections({
      community: { ...COMMUNITY, reps: [{ id: 4, full_name: 'Bola Rep' }] },
      membership: { user_id: 2, role: 'STUDENT' },
    });
    expect(await screen.findByText(/only a verified course rep can start a removal vote/i))
      .toBeInTheDocument();
    expect(screen.queryByTestId('remove-4')).not.toBeInTheDocument();
  });

  it('lets an eligible member vote on a removal', async () => {
    const calls = renderElections({
      community: COMMUNITY,
      membership: { user_id: 2, role: 'STUDENT' },
      removals: [OPEN_REMOVAL],
    });
    const user = userEvent.setup();
    await user.click(await screen.findByTestId('removal-8-no'));
    await waitFor(() => {
      const vote = calls.find((c) => c.path === '/rep/removals/8/vote');
      expect(vote.body.vote).toBe('NO');
    });
  });

  it('gives the target no vote on their own removal', async () => {
    renderElections({
      community: COMMUNITY,
      membership: { user_id: 1, role: 'VERIFIED_REP' },
      removals: [{ ...OPEN_REMOVAL, is_me: true, can_vote: false }],
    });
    expect(await screen.findByText(/this is about you/)).toBeInTheDocument();
    expect(screen.queryByTestId('removal-8-yes')).not.toBeInTheDocument();
  });

  it('shows a passed removal and a failed removal distinctly', async () => {
    renderElections({
      community: COMMUNITY,
      membership: { user_id: 2, role: 'STUDENT' },
      removals: [
        { ...OPEN_REMOVAL, id: 8, status: 'PASSED', can_vote: false, yes_votes: 3, no_votes: 0 },
        { ...OPEN_REMOVAL, id: 9, target_name: 'Bola Rep', status: 'FAILED',
          can_vote: false, yes_votes: 1, no_votes: 2 },
      ],
    });
    expect(await screen.findByText('Passed')).toBeInTheDocument();
    expect(screen.getByText('Did not pass')).toBeInTheDocument();
  });
});

// --- Course removal is refused while records depend on the course ---------

describe('course removal blocking', () => {
  it('names the records that block removal', async () => {
    const { default: RepDashboard } = await import('../src/pages/RepDashboard.jsx');
    globalThis.fetch = async (url, init) => {
      const path = String(url).replace(/^.*\/api/, '');
      const method = init?.method || 'GET';
      const json = (b, s = 200) => new Response(JSON.stringify(b),
        { status: s, headers: { 'Content-Type': 'application/json' } });
      if (path === '/auth/me') return json(REP_SESSION);
      if (path === '/dashboard') {
        return json({ greeting: 'Hi', community: COMMUNITY,
                      membership: REP_SESSION.membership, upcoming: [],
                      recent_changes: [], announcements: [], reminders: [],
                      rep: { student_count: 4, rep_count: 1, pending_requests: [],
                             course_count: 1, timetable_count: 0 } });
      }
      if (path === '/community/courses') {
        return json({ courses: [{ id: 12, code: 'COS500', title: 'Attached' }] });
      }
      if (path === '/community/timetable') return json({ timetable: [] });
      if (path === '/rep/candidates') return json({ candidates: [] });
      if (path === '/rep/removals') return json({ removals: [] });
      if (path === '/community/calendar') return json({ calendar: null });
      if (path === '/community/announcements') return json({ announcements: [] });
      if (path === '/community/courses/12' && method === 'DELETE') {
        return json({
          error: 'conflict',
          message: 'This course still has 1 scheduled event. Cancel or reschedule '
                   + 'them before removing the course.',
          details: {
            blocking_events: [{ id: 41, title: 'COS202 assignment',
                                event_type: 'ASSIGNMENT', event_date: '2026-10-20' }],
            blocking_timetable_entries: [],
          },
        }, 409);
      }
      return json({}, 404);
    };

    renderWithAuth(<RepDashboard />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Remove' }));

    expect(await screen.findByText(/Cancel or reschedule them/)).toBeInTheDocument();
    expect(screen.getByText(/Still attached: COS202 assignment/)).toBeInTheDocument();
  });
});
