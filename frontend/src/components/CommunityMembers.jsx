// Community · Members - the people in this community, as a directory.
//
// ONE SOURCE OF TRUTH. Members come from GET /api/community/members - active
// members only - which returns exactly four fields per person (user_id,
// full_name, role, status), a contract the backend's privacy tests pin. The
// directory shows those and nothing more: no email, no matric number.
//
// Department, level and session are NOT per-person here, deliberately. A
// community IS a department, level and session, and every active member joined
// through it, so the same three values on every row would be one fact printed
// forty times. They are said once, above the list. A rep's "since" date comes
// from the community payload's reps, which already carries it.
//
// Reps are distinguished the way the rest of the product marks authority: a
// forest shield and the words "Course rep", never a filled badge. The one
// signal-coloured thing in the list is you.

import { useMemo, useState } from 'react';
import { api } from '../api/client.js';
import { useAuth } from '../auth/AuthContext.jsx';
import { useResource } from './useResource.js';
import { EmptyState, ErrorState } from './States.jsx';
import { initials, longDate } from './ui.jsx';
import { IconClose, IconSearch, IconShield } from './icons.jsx';

// Below this many people a search box is furniture: the list is the search.
const SEARCH_FROM = 9;

// "September 2026" from an instant - a rep's tenure is read in months.
function monthYear(value) {
  const words = longDate(value).split(' ');
  return words.length >= 3 ? words.slice(-2).join(' ') : null;
}

function Member({ member, isYou, repSince }) {
  const rep = member.role === 'VERIFIED_REP';
  return (
    <li className={`member${isYou ? ' member--you' : ''}`}>
      <span className={`member__avatar${rep ? ' member__avatar--rep' : ''}`} aria-hidden="true">
        {initials(member.full_name)}
      </span>
      <div className="member__body">
        <p className="member__name">
          {member.full_name}
          {isYou && <span className="member__you">You</span>}
        </p>
        <p className="member__role">
          {rep ? (
            <>
              <IconShield size={14} />
              <span>Course rep{repSince ? ` since ${repSince}` : ''}</span>
            </>
          ) : 'Student'}
        </p>
      </div>
    </li>
  );
}

function Group({ label, members, youId, sinceById }) {
  if (members.length === 0) return null;
  return (
    <section className="mgroup-dir" aria-label={label}>
      <h3 className="mgroup-dir__label">
        {label} <span className="mgroup-dir__n">{members.length}</span>
      </h3>
      <ul className="members">
        {members.map((m) => (
          <Member key={m.user_id} member={m} isYou={m.user_id === youId}
                  repSince={sinceById.get(m.user_id)} />
        ))}
      </ul>
    </section>
  );
}

export default function CommunityMembers({ community }) {
  const { user } = useAuth();
  const [query, setQuery] = useState('');
  const [only, setOnly] = useState('everyone');   // 'everyone' | 'reps'
  const { status, data, error, reload } = useResource(
    () => api.get('/community/members').then((d) => d.members ?? []));

  const sinceById = useMemo(() => new Map((community.reps ?? [])
    .map((r) => [r.id, r.rep_since ? monthYear(r.rep_since) : null])), [community.reps]);

  const members = data ?? [];
  const needle = query.trim().toLowerCase();
  const shown = members.filter((m) => (!needle || m.full_name.toLowerCase().includes(needle))
                                       && (only === 'everyone' || m.role === 'VERIFIED_REP'));
  const byName = (a, b) => a.full_name.localeCompare(b.full_name);
  const reps = shown.filter((m) => m.role === 'VERIFIED_REP').sort(byName);
  const students = shown.filter((m) => m.role !== 'VERIFIED_REP').sort(byName);
  const repCount = members.filter((m) => m.role === 'VERIFIED_REP').length;
  const searchable = members.length >= SEARCH_FROM;

  return (
    <section className="board mdir" aria-labelledby="mdir-title">
      <header className="mdir__head">
        <div>
          <h2 className="mdir__title" id="mdir-title">Members</h2>
          {/* Said once for everyone, because it is true of everyone. */}
          <p className="mdir__where">
            {community.department} · Level {community.level} · {community.academic_session}
          </p>
        </div>
        {status === 'ready' && (
          <p className="mdir__count">
            <strong>{members.length}</strong> {members.length === 1 ? 'person' : 'people'}
          </p>
        )}
      </header>

      {status === 'ready' && members.length > 1 && (searchable || repCount > 0) && (
        <div className="mdir__tools">
          {searchable && (
            <div className="msearch">
              <label className="sr-only" htmlFor="member-search">Find a member</label>
              <IconSearch size={17} />
              <input id="member-search" type="search" placeholder="Find a member by name"
                     autoComplete="off" value={query}
                     onChange={(e) => setQuery(e.target.value)} />
              {query && (
                <button type="button" className="msearch__clear" aria-label="Clear the search"
                        onClick={() => setQuery('')}>
                  <IconClose size={15} />
                </button>
              )}
            </div>
          )}
          {repCount > 0 && (
            <div className="mfilter" role="group" aria-label="Show">
              {[['everyone', 'Everyone'], ['reps', `Course reps (${repCount})`]].map(([id, label]) => (
                <button key={id} type="button" aria-pressed={only === id}
                        onClick={() => setOnly(id)}>{label}</button>
              ))}
            </div>
          )}
        </div>
      )}

      {status === 'loading' && (
        <ul className="members members--loading" aria-label="Loading members">
          {[0, 1, 2, 3].map((i) => (
            <li className="member" key={i} aria-hidden="true">
              <span className="member__avatar skel" />
              <div className="member__body">
                <span className="skel" style={{ width: `${46 - i * 6}%`, height: 14, display: 'block' }} />
                <span className="skel" style={{ width: '22%', height: 11, display: 'block', marginTop: 8 }} />
              </div>
            </li>
          ))}
        </ul>
      )}

      {status === 'error' && <ErrorState message={error} onRetry={reload} />}

      {status === 'ready' && members.length <= 1 && (
        <EmptyState title="It’s just you so far"
                    message={`Classmates appear here as they join ${community.department}, Level ${community.level}.`} />
      )}

      {status === 'ready' && members.length > 1 && (
        shown.length === 0 ? (
          <EmptyState title={needle ? `No one called “${query.trim()}”` : 'No one to show'}
                      message="Try part of a first name or surname."
                      action={needle ? (
                        <button type="button" className="btn btn--secondary"
                                onClick={() => setQuery('')}>Clear the search</button>
                      ) : null} />
        ) : (
          <div className="mdir__list" key={`${only}:${needle}`}>
            <Group label="Course reps" members={reps} youId={user?.id} sinceById={sinceById} />
            <Group label="Students" members={students} youId={user?.id} sinceById={sinceById} />
          </div>
        )
      )}
    </section>
  );
}
