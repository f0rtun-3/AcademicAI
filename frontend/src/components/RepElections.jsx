// S9 · Elections, and S10 · Rep removal (spec 11, 12).
//
// TRUST BOUNDARY. This component renders what the backend reported and
// forwards actions to it. It re-implements NO election rule: eligibility, the
// 24-hour window, the minimum vote count, the YES > NO decision, vacancy and
// the cooldowns all live in the services, and every POST here is re-authorised
// there inside the writing transaction.
//
// `can_vote`, `cooldown_until`, `can_start_election` and `members_needed` are
// UI HINTS WITH NO AUTHORITY. They decide what is SHOWN, never what is
// ALLOWED. Where a hint is stale or missing the request still goes, and the
// backend's refusal is what the student reads (C·3, C·9).

import { useCallback, useEffect, useState } from 'react';
import { api } from '../api/client.js';
import { EmptyState, ErrorBanner, Loading, SuccessBanner } from './States.jsx';
import {
  Board, Modal, Notice, Panel, Row, StateChip, Tally, longDate, remaining,
} from './ui.jsx';
import { voteWord } from '../lib/vocabulary.js';

function VoteButtons({ onVote, busy, idPrefix }) {
  return (
    <span className="row-x stackable">
      <button type="button" className="btn btn--secondary" disabled={busy}
              onClick={() => onVote('YES')} data-testid={`${idPrefix}-yes`}>
        Vote yes
      </button>
      <button type="button" className="btn btn--secondary" disabled={busy}
              onClick={() => onVote('NO')} data-testid={`${idPrefix}-no`}>
        Vote no
      </button>
    </span>
  );
}

function BallotRow({ ballot, name, busy, idPrefix, onVote, aboutYou }) {
  return (
    <Row title={name}
         meta={<>
           {ballot.yes_votes} yes · {ballot.no_votes} no
           {ballot.status === 'OPEN' && ` · ${ballot.min_votes_required} votes needed`}
           {ballot.status === 'OPEN' && ballot.closes_at
             ? ` · ${remaining(ballot.closes_at) ?? ''}` : ''}
           {/* " · you" on its own read as a label with no predicate. */}
           {ballot.is_me && (aboutYou ? ' · this is about you' : ' · your candidacy')}
           {ballot.my_vote ? ` · you voted ${voteWord(ballot.my_vote)}` : ''}
           {ballot.status === 'FAILED' && ballot.outcome_reason ? ` · ${ballot.outcome_reason}` : ''}
         </>}
         side={<>
           <StateChip value={ballot.status} context="ballot" />
           {ballot.can_vote && (
             <VoteButtons busy={busy} idPrefix={idPrefix} onVote={onVote} />
           )}
         </>} />
  );
}

export default function RepElections({ community, membership, onChanged }) {
  const [candidates, setCandidates] = useState(null);
  const [removals, setRemovals] = useState(null);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [busy, setBusy] = useState(false);
  const [confirmRemoval, setConfirmRemoval] = useState(null);

  const load = useCallback(async () => {
    try {
      const [c, r] = await Promise.all([
        api.get('/rep/candidates'),
        api.get('/rep/removals'),
      ]);
      setCandidates(c.candidates ?? []);
      setRemovals(r.removals ?? []);
    } catch (err) {
      setError(err);
      setCandidates([]);
      setRemovals([]);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  async function act(fn, successMessage) {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await fn();
      setNotice(successMessage);
      await load();
      if (onChanged) await onChanged();
    } catch (err) {
      // The backend refused. Show its reason verbatim (C·5).
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  // The same skeleton every other screen shows while it waits, rather than a
  // line of grey monospace that looks like a value.
  if (candidates === null || removals === null) {
    return <Loading label="Loading ballots…" rows={2} />;
  }

  const openCandidacy = candidates.find((c) => c.status === 'OPEN' && c.is_me);
  const isRep = membership?.role === 'VERIFIED_REP';
  const reps = community?.reps ?? [];
  const otherReps = reps.filter((r) => r.id !== membership?.user_id);
  const election = community?.election ?? {};
  // C·3 — every number below is the backend's. No frontend constant expresses
  // the rule; if the object is missing, the sentence is omitted, not guessed,
  // and the action stays available because the backend refuses authoritatively.
  const shortfall = election.can_start_election === false ? election.members_needed : null;
  const cooldownUntil = election.cooldown_until ?? null;   // J·4, read-only

  return (
    <div className="stack stack--loose" data-testid="rep-elections">
      <section className="stack">
        {/* A section heading is a name, not a sentence. The rep count used to
            BE the heading, which left the tab with no title at all and set a
            statement in heading type. The count is now what it is: a fact in
            the sentence that explains the section. */}
        <div className="secthead">
          <div className="secthead__text">
            <h2 className="t-section">Elections</h2>
            <p className="prose">
              Course reps are elected by this community, and only an elected rep
              can publish official academic information.{' '}
              {/* No denominator: the vacancy cap is a backend rule and is not in
                  any response, so it is not invented here (C·3 / P·4). */}
              This community has {reps.length} verified rep{reps.length === 1 ? '' : 's'}.
            </p>
          </div>
          {!isRep && !openCandidacy && (
            <button type="button" className="btn btn--primary" disabled={busy}
                    onClick={() => act(() => api.post('/rep/nominate', {}),
                                       'Your candidacy is open. Your classmates now vote on it.')}>
              Stand for election
            </button>
          )}
        </div>

        <ErrorBanner message={error} onDismiss={() => setError(null)} />
        <SuccessBanner message={notice} onDismiss={() => setNotice(null)} />

        {shortfall ? (
          <Notice tone="warn" label="Not enough verified students yet">
            This community needs {shortfall} more verified
            student{shortfall === 1 ? '' : 's'} before an election can start —{' '}
            {election.required_members} are required, because a candidate cannot vote
            for themselves.
          </Notice>
        ) : null}

        {cooldownUntil && (
          <Notice tone="warn" label="You can stand again later">
            You can stand again from {longDate(cooldownUntil)}.
          </Notice>
        )}
      </section>

      {openCandidacy && (
        <Panel title="Your candidacy" data-testid="my-candidacy">
          <p className="t-body" style={{ marginBottom: 'var(--s3)' }}>
            Your candidacy is open and closes on {longDate(openCandidacy.closes_at)}
            {(openCandidacy.closes_at || '').slice(11, 16)
              ? ` at ${openCandidacy.closes_at.slice(11, 16)}` : ''}.
          </p>
          <Tally yes={openCandidacy.yes_votes} no={openCandidacy.no_votes}
                 needed={openCandidacy.min_votes_required}
                 closesAt={openCandidacy.closes_at} />
          <p className="t-meta" style={{ marginTop: 'var(--s3) ' }}>
            You cannot vote on your own candidacy.
          </p>
        </Panel>
      )}

      <Board title="Candidacies">
        {candidates.length === 0 ? (
          <EmptyState title="No nominations yet"
                      message="Any member of this community can stand for election." />
        ) : (
          <div data-testid="candidate-list">
            {candidates.map((c) => (
              <BallotRow key={c.id} ballot={c} name={c.full_name} busy={busy}
                         idPrefix={`candidate-${c.id}`}
                         onVote={(vote) => act(
                           () => api.post(`/rep/candidates/${c.id}/vote`, { vote }),
                           `Your ${voteWord(vote)} vote has been recorded.`)} />
            ))}
          </div>
        )}
      </Board>

      {/* S10 · Removal. Only a verified rep may open one (spec 12).
        *
        * The board used to stack up to three flat rows of grey monospace above
        * the ballots — who may start one, whether there is anyone to remove,
        * whether any vote exists — so a board of RECORDS opened with three
        * pieces of explanation dressed as records. Explanation is now the
        * board's footnote and the action is a footer control; the rows are
        * ballots and nothing else. */}
      <Board title="Rep removal"
             foot={<div className="stack stack--tight">
               <span className="prose">
                 {isRep && otherReps.length > 0
                   ? 'Removal strips rep authority. The consequences are listed before '
                     + 'you start.'
                   : isRep
                     ? 'There is no other verified rep to remove.'
                     : 'Only a verified course rep can start a removal vote.'}
               </span>
               {isRep && otherReps.length > 0 && (
                 <div className="row-x stackable" data-testid="removal-actions">
                   {otherReps.map((rep) => (
                     <button key={rep.id} type="button" className="btn btn--danger" disabled={busy}
                             data-testid={`remove-${rep.id}`}
                             onClick={() => setConfirmRemoval(rep)}>
                       Start removal vote for {rep.full_name}
                     </button>
                   ))}
                 </div>
               )}
             </div>}>
        {removals.length === 0 ? (
          <EmptyState title="No removal votes"
                      message="A removal vote appears here while it is open, and stays as a
                               record once it closes." />
        ) : (
          <div data-testid="removal-list">
            {removals.map((r) => (
              <BallotRow key={r.id} ballot={r} name={r.target_name} busy={busy} aboutYou
                         idPrefix={`removal-${r.id}`}
                         onVote={(vote) => act(
                           () => api.post(`/rep/removals/${r.id}/vote`, { vote }),
                           `Your ${voteWord(vote)} vote has been recorded.`)} />
            ))}
          </div>
        )}
      </Board>

      {confirmRemoval && (
        <Modal title={`Start a removal vote for ${confirmRemoval.full_name}?`}
               onClose={() => setConfirmRemoval(null)}
               actions={<>
                 <button type="button" className="btn btn--secondary"
                         onClick={() => setConfirmRemoval(null)}>Cancel</button>
                 <button type="button" className="btn btn--danger" disabled={busy}
                         onClick={() => {
                           const target = confirmRemoval;
                           setConfirmRemoval(null);
                           act(() => api.post('/rep/removals', { target_user_id: target.id }),
                               `A removal vote for ${target.full_name} is now open.`);
                         }}>
                   Start removal vote
                 </button>
               </>}>
          {/* A consequence list, not an "are you sure". Never truncated. */}
          <Notice tone="crit" label="What happens">
            <ul>
              <li>Every verified member of this community except {confirmRemoval.full_name} may vote.</li>
              <li>Voting is open for 24 hours.</li>
              <li>Enough people must vote, and yes must exceed no.</li>
              <li>If it passes, {confirmRemoval.full_name} loses rep authority immediately and
                stays in the community as a student.</li>
              <li>If it fails, no further vote against them for the cooldown period.</li>
            </ul>
          </Notice>
        </Modal>
      )}
    </div>
  );
}
