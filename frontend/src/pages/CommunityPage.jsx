// S8 · Community, with the sub-nav the approved IA specifies:
//
//   Overview | Elections | Membership | Manage (verified rep only)
//
// Each is a route (/community, /community/elections, /community/membership,
// /community/manage) so a section is linkable and survives a refresh. Manage
// is the fourth SUB-route, not a fifth top-level tab — a role changes what is
// inside the shell, never the shell itself. For a student it is absent, not
// disabled.

import { useState } from 'react';
import { Navigate, useParams } from 'react-router-dom';
import { api } from '../api/client.js';
import { useAuth } from '../auth/AuthContext.jsx';
import RepElections from '../components/RepElections.jsx';
import CommunityMembership from '../components/CommunityMembership.jsx';
import CommunityNav from '../components/CommunityNav.jsx';
import { useResource } from '../components/useResource.js';
import { EmptyState, ErrorBanner, ErrorState, Loading } from '../components/States.jsx';
import {
  Board, CommunityStatus, Facts, Notice, PageHeader, Row, StatusBadge,
  longDate, whenParts,
} from '../components/ui.jsx';
import {
  IconBook, IconCalendar, IconClock, IconMegaphone, IconShield,
} from '../components/icons.jsx';
import { dayShort, describeChange, isStudentFacingChange } from '../lib/vocabulary.js';

const SECTIONS = ['elections', 'membership'];

function Overview({ community, courses, timetable, announcements, changes,
                   onToggleEnrollment, busy, archived }) {
  return (
    <div className="stack stack--loose">
      <Board title="Verified reps" icon={IconShield}>
        {community.reps.length === 0 ? (
          /* The shared empty state, not a bare row with grey text in it. The
             readiness sentence is the same one the Notice above prints, and
             every number in it is the backend's. */
          <EmptyState title="No verified rep yet"
                      message={'Any member of this community can stand for election. '
                        + (community.election && community.election.can_start_election === false
                          ? `An election cannot start yet: ${community.election.members_needed} `
                            + `more verified student`
                            + `${community.election.members_needed === 1 ? '' : 's'} needed, `
                            + `because a candidate cannot vote for themselves and `
                            + `${community.election.required_members} members are required.`
                          : '')} />
        ) : community.reps.map((rep) => (
          /* No badge: the board is titled "Verified reps", so a "Course rep"
             chip on every row would repeat the heading. */
          <Row key={rep.id} title={rep.full_name}
               meta={rep.rep_since ? `Rep since ${longDate(rep.rep_since)}` : null} />
        ))}
      </Board>

      <Board title="Your courses" icon={IconBook}
             foot={<span className="prose">
               You only receive notifications for courses you are enrolled in.
             </span>}>
        {courses.length === 0 ? (
          <EmptyState title="No courses yet"
                      message="Your course rep publishes the course list." />
        ) : courses.map((course) => (
          <Row key={course.id} title={course.code}
               meta={course.title}
               side={archived ? <StatusBadge value="ARCHIVED" /> : (
                 <button type="button" className="btn btn--secondary" disabled={busy}
                         onClick={() => onToggleEnrollment(course)}>
                   {course.enrolled ? 'Leave course' : 'Enrol'}
                 </button>
               )} />
        ))}
      </Board>

      <div className="bands bands--2">
        <Board title="Announcements" icon={IconMegaphone}>
          {announcements.length === 0 ? (
            <EmptyState title="No announcements"
                        message="Announcements your reps publish appear here." />
          ) : announcements.map((item) => (
            /* An announcement's body is prose a person wrote, so it is set in
               the UI face. It was rendering in the metadata mono, which is
               this product's voice for VALUES and made a paragraph read like a
               log line. Attribution is shown because a human published it. */
            <Row key={item.id} when={whenParts(item.created_at)} title={item.title}
                 meta={<>
                   <span className="prose">{item.body}</span>
                   {item.author_name && (
                     <span className="brow__by">Posted by {item.author_name}</span>
                   )}
                 </>}
                 side={<StatusBadge value={item.status ?? 'PUBLISHED'} />} />
          ))}
        </Board>

        <Board title="Timetable" icon={IconCalendar}>
          {timetable.length === 0 ? (
            <EmptyState title="No timetable yet"
                        message="Your course rep can publish the weekly timetable." />
          ) : timetable.map((entry) => (
            <Row key={entry.id}
                 when={{ top: dayShort(entry.day_of_week), bottom: entry.start_time ?? '' }}
                 title={entry.title ?? entry.course_code ?? 'Class'}
                 meta={entry.venue ?? 'Venue not specified'}
                 side={<StatusBadge value={entry.status ?? 'ACTIVE'} />} />
          ))}
        </Board>
      </div>

      <Board title="Recent changes" icon={IconClock} className="board--timeline board--past">
        {changes.length === 0 ? (
          <EmptyState title="Nothing has changed recently"
                      message="Changes your course reps make to official information appear here." />
        ) : changes.map((change) => {
          /* A sentence naming what changed ("The deadline for COS202 Quiz was
             updated."), not the change type. Who made it is the metadata;
             a change the system made on its own (an election closing) has no
             person to name, so it names nobody. */
          const { sentence } = describeChange(change);
          return (
            <Row key={change.id} when={whenParts(change.created_at)}
                 title={sentence}
                 meta={change.actor_name ? `By ${change.actor_name}` : null} />
          );
        })}
      </Board>
    </div>
  );
}

export default function CommunityPage() {
  const { refresh, isRep } = useAuth();
  const { section } = useParams();
  const tab = SECTIONS.includes(section) ? section : 'overview';
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState(null);

  const { status, data, error, reload } = useResource(() => Promise.all([
    api.get('/community'),
    api.get('/community/courses'),
    api.get('/community/timetable'),
    api.get('/community/announcements'),
    api.get('/community/changes?limit=20'),
  ]).then(([community, courses, timetable, announcements, changes]) => ({
    community: community.community,
    membership: community.membership,
    courses: courses.courses,
    timetable: timetable.timetable,
    announcements: announcements.announcements,
    changes: changes.changes,
  })));

  // An address that is not a section goes to the overview rather than
  // pretending to be one.
  if (section && !SECTIONS.includes(section)) return <Navigate to="/community" replace />;
  if (status === 'loading') return <Loading label="Loading your community…" />;
  if (status === 'error') return <ErrorState message={error} onRetry={reload} />;

  const { community, membership, courses, timetable, announcements } = data;
  // Membership rows are classmates' administrative business, not academic
  // information; the feed shows what changed in the records themselves.
  const changes = data.changes.filter(isStudentFacingChange);
  const archived = community.status === 'ARCHIVED';

  async function afterBallotChange() {
    // A ballot can change the caller's own role, so the session view must be
    // re-read from the backend rather than assumed.
    await refresh();
    reload();
  }

  async function toggleEnrollment(course) {
    setBusy(true);
    setActionError(null);
    try {
      if (course.enrolled) await api.del(`/community/courses/${course.id}/enroll`);
      else await api.post(`/community/courses/${course.id}/enroll`);
      await reload();
    } catch (err) {
      setActionError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="stack stack--loose">
      {/* The same surfaced header the dashboard uses. A community IS a
        * place with a state, so the title, the state and the four attributes
        * that define it belong to one component rather than to a display
        * heading with a grey run-on line under it. */}
      <PageHeader
        surface
        eyebrow="Your community"
        title={`${community.department} · Level ${community.level}`}
        lede="Official academic information for this department, level and session.
              Only an elected course rep can publish it."
        action={<CommunityStatus status={community.status} />}
        meta={<Facts items={[
          { label: 'University', value: community.university },
          { label: 'Session', value: community.academic_session, mono: true },
          { label: 'Members', value: community.member_count, mono: true },
        ]} />} />

      {/* PENDING is the state a student is most likely to misread, so it is
          explained here rather than left as a chip. Every number comes from
          the backend's election readiness - none is a client constant. */}
      {community.status === 'PENDING' && (
        <Notice tone="info" label="No course rep yet">
          This community becomes active once its first course representative is
          elected. Until then there is nobody who can publish official information
          or approve new members — which is why you were able to join directly.
          {community.election && (
            community.election.can_start_election ? (
              <> It has {community.election.eligible_members} eligible members, so an
                election can be held now.</>
            ) : (
              <> It has {community.election.eligible_members} of the{' '}
                {community.election.required_members} eligible members an election
                needs, so {community.election.members_needed} more{' '}
                {community.election.members_needed === 1 ? 'student' : 'students'} in
                this exact department, level and session must join first.</>
            )
          )}
        </Notice>
      )}

      <CommunityNav isRep={isRep} />

      {archived && (
        <Notice tone="none" label="Session archived">
          This academic session has been archived. It no longer accepts changes.
        </Notice>
      )}

      <ErrorBanner message={actionError} onDismiss={() => setActionError(null)} />

      {tab === 'overview' && (
        <Overview community={community} courses={courses} timetable={timetable}
                  announcements={announcements} changes={changes} busy={busy}
                  archived={archived} onToggleEnrollment={toggleEnrollment} />
      )}
      {tab === 'elections' && (
        <RepElections community={community} membership={membership}
                      onChanged={afterBallotChange} />
      )}
      {tab === 'membership' && (
        <CommunityMembership community={community} membership={membership} />
      )}

    </div>
  );
}
