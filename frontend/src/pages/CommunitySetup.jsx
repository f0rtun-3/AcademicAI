import { useEffect, useState } from 'react';
import { api } from '../api/client.js';
import { useAuth } from '../auth/AuthContext.jsx';
import { ErrorBanner, Loading, SuccessBanner } from '../components/States.jsx';
import { Notice } from '../components/ui.jsx';

// Community determination (spec 7). The two headline messages below are the
// exact wording the product specifies.
//
// The two choices lead to genuinely different workflows:
//
//   "I'm a Student"     -> join, and that is all
//   "I'm a Course Rep"  -> join, then stand for election straight away
//
// Standing is a self-nomination through the existing backend ballot, so none
// of the election rules are re-implemented here. Joining must happen first
// because the backend requires an ACTIVE membership to nominate. If the
// community is too small to hold a winnable election the nomination is
// refused, and we say so plainly rather than failing silently - the student
// is still a member and can stand later from the community page.
export default function CommunitySetup() {
  const { refresh, logout } = useAuth();
  const [setup, setSetup] = useState(null);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [busy, setBusy] = useState(null);

  useEffect(() => {
    let cancelled = false;
    api.post('/community/setup')
      .then((data) => { if (!cancelled) setSetup(data); })
      .catch((err) => { if (!cancelled) setError(err.message); });
    return () => { cancelled = true; };
  }, []);

  async function joinOnly() {
    setBusy('student');
    setError(null);
    try {
      await api.post('/community/join');
      await refresh();
    } catch (err) {
      setError(err.message);
      setBusy(null);
    }
  }

  async function joinAndStand() {
    setBusy('rep');
    setError(null);
    setNotice(null);
    try {
      await api.post('/community/join');
    } catch (err) {
      setError(err.message);
      setBusy(null);
      return;
    }
    // Membership succeeded. The candidacy is a separate, optional step: if it
    // is refused the student is still in, so we report it and continue.
    try {
      await api.post('/rep/nominate', {});
      setNotice('You have joined and your candidacy is open. '
        + 'Your classmates now vote on it.');
    } catch (err) {
      setNotice(`You have joined this community, but your candidacy could not start: ${
        err.message} You can stand for election later from the Community page.`);
    }
    await refresh();
  }

  if (error && !setup) return <ErrorBanner message={error} />;
  if (!setup) return <Loading label="Finding your academic community…" />;

  const { community, existed } = setup;
  // C·3 — every number below is the backend's, read from
  // community_service.election_readiness(). No frontend constant expresses the
  // rule: there is no 4, no 3 and no arithmetic reconstructing the threshold
  // from another field. If the object is missing the sentence is OMITTED, not
  // guessed, and both buttons stay available because the backend refuses
  // authoritatively and says why.
  const election = community.election ?? {};
  const required = election.required_members ?? null;
  const shortfall = election.can_start_election === false
    ? (election.members_needed ?? null)
    : null;

  return (
    <div className="gate">
      <h1 className="t-display" style={{ marginBottom: 'var(--s5)' }}>
        {existed ? 'Your academic community is ready.' : "Your academic community hasn't been set up yet."}
      </h1>
      <div className="gate__card stack">
        <p className="t-meta">
          {community.university} · {community.department} · Level {community.level} · {community.academic_session}
        </p>
        <ErrorBanner message={error} onDismiss={() => setError(null)} />
        <SuccessBanner message={notice} />

        {existed && community.reps?.length > 0 ? (
          <button type="button" className="btn btn--primary" onClick={joinOnly}
                  disabled={busy !== null}>
            {busy === 'student' ? 'Joining…' : 'Join this community'}
          </button>
        ) : (
          <>
            <p className="t-body">
              This community has no verified course rep yet. Joining is the same either
              way; being a course rep requires a vote by your classmates.
            </p>

            {/* Stated up front so nobody discovers the requirement only by
                being refused when they try to stand (spec 8). */}
            {required !== null && (
              <Notice tone="info" label="Before an election can start">
                An election needs {required} verified students in the community before it
                can start: a candidate cannot vote for themselves, and a ballot only
                counts once enough classmates have voted.
                {shortfall ? ` ${shortfall} more needed right now.` : ''}
              </Notice>
            )}

            {/* C·11 — two declarations, not an action and its alternative.
                Ranking one visually would nudge a choice the student should
                make freely, so both carry the same weight. */}
            <div className="row-x stackable">
              <button type="button" className="btn btn--primary" onClick={joinAndStand}
                      disabled={busy !== null}>
                {busy === 'rep' ? 'Submitting…' : "Yes, I'm a Course Rep"}
              </button>
              <button type="button" className="btn btn--secondary" onClick={joinOnly}
                      disabled={busy !== null}>
                {busy === 'student' ? 'Joining…' : "I'm a Student"}
              </button>
            </div>
          </>
        )}
        <button type="button" className="btn btn--quiet" onClick={logout}
                style={{ alignSelf: 'flex-start' }}>Log out</button>
      </div>
    </div>
  );
}
