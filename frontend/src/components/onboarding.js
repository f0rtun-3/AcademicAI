// The onboarding sequence, in one place.
//
// These ids are the backend's own `next_step` values, so the indicator can
// never drift from the routing: App.jsx gates on the same strings. There is
// deliberately no identity-verification step — student ID-card verification is
// out of MVP scope.
//
// "Dashboard" is included as the final step so the indicator shows where the
// flow ends rather than stopping on an ambiguous last item.

export const ONBOARDING_STEPS = [
  { id: 'verify_email', label: 'Verify email' },
  { id: 'community_setup', label: 'Your community' },
  { id: 'awaiting_approval', label: 'Join' },
  { id: 'dashboard', label: 'Done' },
];
