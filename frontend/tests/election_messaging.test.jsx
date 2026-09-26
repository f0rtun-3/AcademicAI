import { screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import CommunitySetup from '../src/pages/CommunitySetup.jsx';
import CommunityPage from '../src/pages/CommunityPage.jsx';
import { COMMUNITY, mockApi, renderWithAuth, REP_SESSION } from './helpers.jsx';

describe('election requirement messaging', () => {
  it('states the four-member requirement before anyone tries to stand', async () => {
    mockApi({
      '/auth/me': { ...REP_SESSION, membership: null, next_step: 'community_setup' },
      'POST /community/setup': {
        community: {
          ...COMMUNITY, status: 'PENDING', member_count: 0, reps: [],
          election: { eligible_members: 0, required_members: 4, preparation_threshold: 3,
                      in_preparation: false, can_start_election: false, members_needed: 4 },
        },
        created: true, existed: false,
        message: "Your academic community hasn't been set up yet.",
      },
    });
    renderWithAuth(<CommunitySetup />);
    expect(await screen.findByText(/needs 4 verified students/)).toBeInTheDocument();
    expect(screen.getByText(/cannot vote for themselves/)).toBeInTheDocument();
  });

  it('tells a short-handed community how many more members it needs', async () => {
    mockApi({
      '/auth/me': REP_SESSION,
      '/community': {
        community: {
          ...COMMUNITY, status: 'PENDING', member_count: 3, reps: [],
          election: { eligible_members: 3, required_members: 4, preparation_threshold: 3,
                      in_preparation: true, can_start_election: false, members_needed: 1 },
        },
        membership: { community_id: 1, status: 'ACTIVE', role: 'STUDENT' },
      },
      '/community/courses': { courses: [] },
      '/community/timetable': { timetable: [] },
      '/community/announcements': { announcements: [] },
      '/community/changes?limit=20': { changes: [] },
    });
    renderWithAuth(<CommunityPage />);
    expect(await screen.findByText(/1 more verified student/)).toBeInTheDocument();
  });
});
