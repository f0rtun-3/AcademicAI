// S5 · Dashboard.
//
// The page answers one question first: what do I need to know or do right
// now? So the order is
//
//   header        a compact greeting, the community it greets you into, and
//                 the way into Ask AcademicAI
//   ① Needs attention   what changed on work that is close - omitted
//                        entirely when empty rather than showing a zero
//   ② (rep only)  the membership queue, because it blocks other people
//   ③ Coming up   today and the next seven days, in date order
//   ④ secondary   your reminders, announcements, your community
//
// Each event appears ONCE. Something in Needs attention is not repeated in
// Coming up: the attention row already carries the date, and says what
// changed, which is the more useful of the two readings.

import { Link, useNavigate } from 'react-router-dom';
import { api } from '../api/client.js';
import { useAuth } from '../auth/AuthContext.jsx';
import { useResource } from '../components/useResource.js';
import { EmptyState, ErrorState, Loading } from '../components/States.jsx';
import {
  Board, CommunityStatus, Completion, Facts, Notice, PageHeader, Row, StateChip,
  StatusBadge, daysUntil, localTime, longDate, todayISO, whenParts,
} from '../components/ui.jsx';
import { IconChat } from '../components/icons.jsx';
import { needsAttention } from '../lib/attention.js';
import { describeChange, eventTypeLabel, eventTypeNoun } from '../lib/vocabulary.js';
import { reminderLocal } from '../lib/academicTime.js';

const NEXT_DAYS = 7;

function eventMeta(event) {
  const parts = [eventTypeLabel(event.event_type)];
  if (event.course_code) parts.push(event.course_code);
  if (event.event_time) parts.push(event.event_time);
  parts.push(event.venue ? event.venue : 'Venue not specified');
  return parts.join(' · ');
}

// What changed, in one line: "Deadline moved from Friday 18 September to
// Monday 21 September." Built by the vocabulary layer from the change row
// itself, so a status transition or a field name can never be printed.
function attentionLine(item) {
  const { event, change, state } = item;
  const type = event?.event_type;
  if (state === 'CANCELLED') return `This ${eventTypeNoun(type)} was cancelled.`;
  const { sentence, details } = describeChange(change, {
    perspective: 'event', subject: type ? { event_type: type } : undefined,
  });
  return details[0] ?? sentence;
}

function AttentionRow({ item, onOpen }) {
  const { event, state } = item;
  const title = event?.title ?? 'An official record changed';
  return (
    <Row when={whenParts(item.date)} title={title}
         onClick={event ? () => onOpen(item.eventId) : undefined}
         meta={<>
           {event?.course_code && <span>{event.course_code} · </span>}
           {attentionLine(item)}
           {event?.completed ? <> · <Completion done /></> : null}
         </>}
         side={<StateChip value={state} />} />
  );
}

export default function Dashboard() {
  const { isRep } = useAuth();
  const navigate = useNavigate();
  const openEvent = (id) => navigate(`/events/${id}`);
  const { status, data, error, reload } = useResource(async () => {
    const dashboard = await api.get('/dashboard');
    // The cancelled-event rows the band needs are not in `upcoming`, which is
    // scheduled-only. Reading the calendar as well composes two authoritative
    // endpoints; it never creates a third source of truth. Best effort: if it
    // fails, the band simply renders from `upcoming` alone.
    let all = null;
    try {
      all = (await api.get('/calendar')).events;
    } catch {
      all = null;
    }
    return { ...dashboard, allEvents: all };
  });

  if (status === 'loading') return <Loading label="Loading your dashboard…" />;
  if (status === 'error') return <ErrorState message={error} onRetry={reload} />;

  const {
    greeting, community, upcoming, recent_changes: changes,
    announcements, reminders, rep, allEvents,
  } = data;

  const today = todayISO();
  const attention = needsAttention({
    events: allEvents ?? upcoming,
    changes,
    today,
  });
  const inAttention = new Set(attention.items.map((item) => item.eventId));

  // Today and the next seven days, minus anything already in Needs attention.
  const comingUp = upcoming.filter((event) => {
    const days = daysUntil(event.event_date);
    return days !== null && days >= 0 && days <= NEXT_DAYS && !inAttention.has(event.id);
  });
  const pendingReminders = (reminders ?? []).filter((r) => r.status === 'PENDING');
  const archived = community.status === 'ARCHIVED';

  return (
    <div className="stack stack--loose">
      {/* A header, not a card. The greeting, the date, and the four facts that
        * say which community this is - labelled, so no value has to be
        * guessed. The community's status is shown only when it is not the
        * normal one: an "Active" badge on every visit says nothing. */}
      <PageHeader
        className="dashhead"
        eyebrow={longDate(today)}
        title={greeting}
        action={(
          <Link className="btn btn--secondary" to="/chat">
            <IconChat size={18} />
            Ask AcademicAI
          </Link>
        )}
        meta={<>
          <Facts items={[
            { label: 'University', value: community.university },
            { label: 'Department', value: community.department },
            { label: 'Level', value: community.level, mono: true },
            { label: 'Session', value: community.academic_session, mono: true },
          ]} />
          {community.status !== 'ACTIVE' && <CommunityStatus status={community.status} />}
        </>} />

      {archived && (
        <Notice tone="none" label="Session archived">
          This academic session has been archived. Everything below is read-only.
        </Notice>
      )}

      {/* ① Needs attention — omitted entirely when empty. */}
      {attention.items.length > 0 && (
        <Board title="Needs attention"
               action={<span className="t-meta">
                 {attention.items.length} change{attention.items.length === 1 ? '' : 's'}
               </span>}
               foot={attention.more > 0 ? (
                 <Link className="linkish" to="/calendar">
                   {attention.more} more change{attention.more === 1 ? '' : 's'} in the calendar
                 </Link>
               ) : null}>
          {attention.items.map((item) => (
            <AttentionRow key={item.key} item={item} onOpen={openEvent} />
          ))}
        </Board>
      )}

      {/* ② Rep only: the queue that blocks other people. */}
      {isRep && rep && rep.pending_requests?.length > 0 && (
        <Board title="Awaiting your decision"
               action={<Link className="linkish" to="/community/manage">Open Manage</Link>}>
          {rep.pending_requests.map((request) => (
            <Row key={request.user_id} when={whenParts(request.requested_at)}
                 title={request.full_name}
                 meta="Asked to join your community" />
          ))}
        </Board>
      )}

      {/* ③ Coming up: today and the next seven days, once each. */}
      <Board title="Coming up"
             action={<span className="t-meta">Today and the next {NEXT_DAYS} days</span>}>
        {comingUp.length === 0 ? (
          attention.items.length > 0 ? (
            <EmptyState title="Nothing else coming up"
                        message="Everything due in the next week is listed under Needs attention." />
          ) : (
            <EmptyState title="Nothing due in the next week"
                        message="Deadlines, quizzes and exams appear here as your reps publish them." />
          )
        ) : comingUp.map((event) => {
          const days = daysUntil(event.event_date);
          return (
            <Row key={event.id} when={whenParts(event.event_date)} title={event.title}
                 onClick={() => openEvent(event.id)}
                 meta={<>{eventMeta(event)}{event.completed ? <> · <Completion done /></> : null}</>}
                 side={<>
                   <StatusBadge value={event.status} />
                   {/* Today and Tomorrow are already named in the date column. */}
                   {days > 1 && <span className="t-meta">in {days} days</span>}
                 </>} />
          );
        })}
      </Board>

      <div className="bands bands--2">
        {/* ④ Your reminders */}
        <Board title="Your reminders"
               action={<Link className="linkish" to="/reminders">See all reminders</Link>}>
          {pendingReminders.length === 0 ? (
            <EmptyState title="No reminders yet"
                        message="Reminders are personal — nobody else sees them."
                        action={<Link className="btn btn--secondary" to="/reminders">
                          Add a reminder
                        </Link>} />
          ) : pendingReminders.slice(0, 4).map((reminder) => (
            /* The day goes in the column; only the clock time, which no other
               row has, goes in the meta. A scheduled reminder is the normal
               case, so it carries no badge. */
            <Row key={reminder.id} when={whenParts(reminderLocal(reminder))}
                 title={reminder.title}
                 meta={localTime(reminderLocal(reminder))}
                 side={<StatusBadge value={reminder.status} context="reminder" />} />
          ))}
        </Board>

        {/* ⑤ Announcements */}
        <Board title="Announcements">
          {(!announcements || announcements.length === 0) ? (
            <EmptyState title="No announcements"
                        message="Announcements your reps publish appear here." />
          ) : announcements.slice(0, 4).map((item) => (
            /* Attribution, where the backend has it. An announcement is
               something a person published — naming them is the visible half
               of the trust model, and the date already has its own column. */
            <Row key={item.id} when={whenParts(item.created_at)}
                 title={item.title}
                 meta={item.author_name ? `Posted by ${item.author_name}` : null}
                 side={<StatusBadge value={item.status ?? 'PUBLISHED'} />} />
          ))}
        </Board>
      </div>

      {/* ⑥ Your community - secondary, so it takes the same board and heading
          as everything else rather than a larger heading of its own. */}
      <Board title="Your community"
             action={<Link className="linkish" to="/community">Open Community</Link>}>
        <Row title={community.reps.length === 0
                      ? 'No verified course rep yet'
                      : `Course rep${community.reps.length === 1 ? '' : 's'}: `
                        + community.reps.map((r) => r.full_name).join(', ')}
             meta={`${community.member_count} member${community.member_count === 1 ? '' : 's'}`} />
      </Board>
    </div>
  );
}
