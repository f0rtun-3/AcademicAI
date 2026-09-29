// S16 · Profile - who you are in AcademicAI, and what you can change.
//
// THREE KINDS OF FACT, KEPT APART:
//
//   identity    your name, your role, your address - on night, at the top,
//               the same material as the account menu's header.
//   the record  your name, department, level, session and matric number.
//               READ-ONLY. The name is fixed: it is how your course reps and
//               classmates know who belongs to the community, so no screen
//               offers to change it. Level and session define your community,
//               so changing them is a transfer, not an edit (J·6). Said on the
//               block, not discovered by looking for a pencil that is not there.
//   your account  the things you CAN change - email, password, appearance, your
//               session. They live in Settings, where the rules around them
//               are explained (a new email signs you out everywhere), so this
//               page states them and leads there rather than growing a second
//               copy of the same form.
//
// DATA. The session supplies the person; /api/community - read only when you
// are a member - supplies the university's name, the member count and, for a
// rep, since when. Nothing here is fetched that the app did not already expose.

import { useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api/client.js';
import { useAuth } from '../auth/AuthContext.jsx';
import { useResource } from '../components/useResource.js';
import { Loading } from '../components/States.jsx';
import ThemeToggle from '../components/ThemeToggle.jsx';
import { Notice, initials, longDate } from '../components/ui.jsx';
import { IconCheck, IconChevronRight, IconLogout } from '../components/icons.jsx';
import { ResetUnavailableNote } from '../components/PasswordResetUnavailable.jsx';
import { PASSWORD_RESET_AVAILABLE } from '../lib/features.js';

function Fact({ label, value, mono = false }) {
  return (
    <div className="pfact">
      <dt>{label}</dt>
      <dd className={mono ? 'mono' : undefined}>{value ?? <span className="pfact__none">Not set</span>}</dd>
    </div>
  );
}

export default function ProfilePage() {
  const { user, membership, isRep, logout } = useAuth();
  // Reset is switched off (lib/features.js): its control opens the reason.
  const [resetWhy, setResetWhy] = useState(false);
  // Only a member can read their community; anyone else gets no request.
  const community = useResource(
    () => (membership ? api.get('/community').then((d) => d.community) : Promise.resolve(null)),
    [membership?.community_id]);

  if (!user) return <Loading label="Loading your profile…" />;

  const c = community.status === 'ready' ? community.data : null;
  const repSince = c?.reps?.find((r) => r.id === user.id)?.rep_since;
  const role = !membership ? 'Not in a community yet' : isRep ? 'Course rep' : 'Student';
  const where = [user.department, user.level ? `Level ${user.level}` : null].filter(Boolean).join(' · ');

  return (
    <div className="profile stack stack--loose">
      {/* Identity: the page's one night surface. */}
      <section className="pid" aria-labelledby="pid-name">
        <span className="pid__avatar" aria-hidden="true">{initials(user.full_name)}</span>
        <div className="pid__body">
          <h1 className="pid__name" id="pid-name">{user.full_name}</h1>
          <p className="pid__role">
            <span className="pid__rolename">{role}</span>
            {membership && where && <span className="pid__where">{where}</span>}
          </p>
          <p className="pid__mail">
            <span className="pid__addr">{user.email}</span>
            {user.email_verified ? (
              <span className="pid__verified"><IconCheck size={14} /> Email verified</span>
            ) : (
              <span className="pid__unverified">Email not verified</span>
            )}
          </p>
        </div>
      </section>

      <div className="profile__grid">
        {/* The record: set at registration, read-only by design. */}
        <section className="pblock" aria-labelledby="pb-record">
          <header className="pblock__head">
            <h2 id="pb-record">Academic record</h2>
            <span className="pblock__tag">Read-only</span>
          </header>
          <dl className="pfacts">
            <Fact label="Name" value={user.full_name} />
            <Fact label="Department" value={user.department} />
            <Fact label="Level" value={user.level} mono />
            <Fact label="Academic session" value={user.academic_session} mono />
            {/* C·12: Matric Number in the UI; the column keeps its own name. */}
            <Fact label="Matric number" value={user.student_id_number} mono />
          </dl>
          <p className="pblock__foot">
            Set when you registered. Your name stays as registered: it is how your
            course reps and classmates know you. Your level and session define your
            community, so changing them means{' '}
            <Link to="/community/membership">requesting a transfer</Link>.
          </p>
        </section>

        {/* Where you belong. */}
        <section className="pblock pblock--community" aria-labelledby="pb-community">
          <header className="pblock__head">
            <h2 id="pb-community">Your community</h2>
          </header>
          {!membership ? (
            <div className="pcomm">
              <p className="pcomm__lede">You are not a member of a community yet.</p>
              <Link className="btn btn--primary" to="/community">Find your community</Link>
            </div>
          ) : (
            <div className="pcomm">
              <p className="pcomm__name">
                {c ? `${c.department} · Level ${c.level}` : where || 'Your community'}
              </p>
              <p className="pcomm__sub">
                {[c?.university, c?.academic_session ?? user.academic_session].filter(Boolean).join(' · ')}
              </p>
              <dl className="pfacts pfacts--inline">
                <Fact label="Your role"
                      value={isRep ? `Course rep${repSince ? ` since ${longDate(repSince)}` : ''}` : 'Student'} />
                {c && <Fact label="Members" value={c.member_count} mono />}
              </dl>
              <div className="pcomm__links">
                <Link className="plink" to="/community/members">
                  <span>See who is in it</span><IconChevronRight size={15} />
                </Link>
                <Link className="plink" to="/community">
                  <span>Open Community</span><IconChevronRight size={15} />
                </Link>
              </div>
            </div>
          )}
        </section>
      </div>

      {/* What you can change. Each lives in Settings, where its rules are. */}
      <section className="pblock" aria-labelledby="pb-account">
        <header className="pblock__head">
          <h2 id="pb-account">Your account</h2>
          <span className="pblock__note">Changes are made in Settings</span>
        </header>
        <ul className="pacts">
          <li className="pact">
            <div className="pact__text">
              <p className="pact__k">Email address</p>
              <p className="pact__v">{user.email}</p>
            </div>
            <Link className="btn btn--secondary btn--sm" to="/settings">Change email</Link>
          </li>
          {PASSWORD_RESET_AVAILABLE ? (
            <li className="pact">
              <div className="pact__text">
                <p className="pact__k">Password</p>
                <p className="pact__v">Reset it with a code sent to your email.</p>
              </div>
              <Link className="btn btn--secondary btn--sm" to="/settings">Reset password</Link>
            </li>
          ) : (
            <li className="pact pact--stack">
              <div className="pact__row">
                <div className="pact__text">
                  <p className="pact__k">Password</p>
                  <p className="pact__v resetrow__status">Currently unavailable</p>
                </div>
                <button type="button" className="btn btn--secondary btn--sm"
                        aria-expanded={resetWhy} aria-controls="reset-unavailable"
                        onClick={() => setResetWhy((open) => !open)}>
                  Reset password
                </button>
              </div>
              {resetWhy && <ResetUnavailableNote id="reset-unavailable" />}
            </li>
          )}
          <li className="pact">
            <div className="pact__text">
              <p className="pact__k">Appearance</p>
              <p className="pact__v">Light, dark, or match your device.</p>
            </div>
            <ThemeToggle />
          </li>
          <li className="pact pact--out">
            <div className="pact__text">
              <p className="pact__k">Session</p>
              <p className="pact__v">Signed in on this device.</p>
            </div>
            <button type="button" className="btn btn--sm pact__logout" onClick={logout}>
              <IconLogout size={16} /> Log out
            </button>
          </li>
        </ul>
      </section>

      {/* Says exactly what was established and nothing more: there is no
          ID-card check in this MVP, so this must never read as "identity
          verified". */}
      {user.email_verified && (
        <Notice tone="info" label="What “verified” means">
          Your email address has been verified, and it is on an approved domain for your
          university. AcademicAI has not otherwise confirmed your identity or checked your
          university&apos;s student records.
        </Notice>
      )}
    </div>
  );
}
