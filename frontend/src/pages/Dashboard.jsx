// S5 · Dashboard.
//
// The page answers one question first: what do I need to know or do right
// now? So the order is
//
//   header        the day on one surface: date, greeting, a one-line pulse
//                 (due today / changes / reminders), the week at a glance, and
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

import { useEffect } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { api } from '../api/client.js';
import { useAuth } from '../auth/AuthContext.jsx';
import { useResource } from '../components/useResource.js';
import { EmptyState, ErrorState, Loading } from '../components/States.jsx';
import {
  Board, CommunityStatus, Completion, DueLabel, Facts, Notice, Row, StateChip,
  StatusBadge, daysUntil, localTime, longDate, todayISO, whenParts,
} from '../components/ui.jsx';
import {
  IconAlert, IconBell, IconCalendar, IconChat, IconCommunity, IconMegaphone, IconUser,
} from '../components/icons.jsx';
import WeekStrip from '../components/WeekStrip.jsx';
import { isAssessment } from '../lib/calendar.js';
import { needsAttention } from '../lib/attention.js';
import { describeChange, eventTypeLabel, eventTypeNoun } from '../lib/vocabulary.js';
import { reminderLocal } from '../lib/academicTime.js';
import { listen, NOTIFICATIONS_ARRIVED } from '../lib/liveEvents.js';

const NEXT_DAYS = 7;

// Written out, never delegated to the runtime locale: "Saturday" must not
// become something else because the browser is set to another language.
const WEEKDAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August',
                'September', 'October', 'November', 'December'];

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

function AttentionRow({ item, onOpen, today }) {
  const { event, state } = item;
  const title = event?.title ?? 'An official record changed';
  return (
    <Row when={whenParts(item.date)} title={title}
         today={state !== 'CANCELLED' && item.date === today}
         onClick={event ? () => onOpen(item.eventId) : undefined}
         meta={<>
           {event?.course_code && <span>{event.course_code} · </span>}
           {attentionLine(item)}
           {/* Its own line: the change is a sentence ending in a full stop,
               and a " · " after it printed "B107. · Done". */}
           {event?.completed ? <span className="brow__by"><Completion done /></span> : null}
         </>}
         side={<StateChip value={state} />} />
  );
}

export default function Dashboard() {
  const { isRep } = useAuth();
  const navigate = useNavigate();
  const openEvent = (id) => navigate(`/events/${id}`);
  const { status, data, error, reload, refresh } = useResource(async () => {
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
  // Something arrived in the bell - a reminder fired, a rep published - so
  // what this page shows may have changed. Re-read quietly, in place.
  useEffect(() => listen(NOTIFICATIONS_ARRIVED, () => refresh()), [refresh]);

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

  // Today on the university's clock, split for the header's numeral.
  const todayDate = new Date(`${today}T00:00:00`);
  const todayParts = {
    day: todayDate.getDate(),
    weekday: WEEKDAYS[todayDate.getDay()],
    month: `${MONTHS[todayDate.getMonth()]} ${todayDate.getFullYear()}`,
  };

  // The day in one line: what is due today, what changed, what you set.
  const dueToday = upcoming.filter((e) => e.event_date === today && !e.completed).length;
  const eventsForWeek = allEvents ?? upcoming;

  return (
    // `dash`: a "today" header across the top, then the record in a main
    // column and the personal and community side in a narrower one. Content
    // arrives in three short beats (styles.css §31).
    <div className="stack stack--loose dash">
      {/* THE DAY. An open editorial composition on the page ground rather
        * than another card: today's date set as a very large numeral - the
        * product's time signature at full scale - beside the greeting and the
        * day's pulse. The week ahead follows as its own surface. */}
      <header className="today">
        <p className="today__date" aria-hidden="true">
          <span className="today__num">{todayParts.day}</span>
          <span className="today__cal">
            <span className="today__dow">{todayParts.weekday}</span>
            <span className="today__month">{todayParts.month}</span>
          </span>
        </p>
        <div className="today__main">
          {/* The numeral beside this is decorative, so the full date is
              said here for a screen reader. */}
          <p className="eyebrow-label">
            Today<span className="sr-only">, {longDate(today)}</span>
          </p>
          <h1 className="today__title">{greeting}</h1>
          <ul className="pulse" aria-label="Today at a glance">
            <li className={dueToday ? 'pulse--warn' : undefined}>
              {dueToday ? `${dueToday} due today` : 'Nothing due today'}
            </li>
            {attention.items.length > 0 && (
              <li className="pulse--info">
                {attention.items.length} change{attention.items.length === 1 ? '' : 's'} to check
              </li>
            )}
            {pendingReminders.length > 0 && (
              <li className="pulse--pos">
                {pendingReminders.length} reminder{pendingReminders.length === 1 ? '' : 's'} set
              </li>
            )}
            {community.status !== 'ACTIVE' && (
              <li className="pulse--plain"><CommunityStatus status={community.status} /></li>
            )}
          </ul>
        </div>
        <div className="today__action">
          <Link className="btn btn--ai" to="/chat">
            <IconChat size={18} />
            Ask AcademicAI
          </Link>
        </div>
      </header>

      <section className="weekpanel" aria-labelledby="week-heading">
        <div className="weekpanel__head">
          <h2 className="eyebrow-label" id="week-heading">The next seven days</h2>
          <Link className="linkish" to="/calendar">Open the calendar</Link>
        </div>
        <WeekStrip events={eventsForWeek} today={today} />
      </section>

      {archived && (
        <Notice tone="none" label="Session archived">
          This academic session has been archived. Everything below is read-only.
        </Notice>
      )}

      {/* The record: what needs you, what blocks others, what is coming. */}
      <div className="dash__main">
        {/* ① Needs attention — omitted entirely when empty. The one raised
            board on the screen: elevation is how priority is shown here, so
            nothing else on the dashboard carries it. */}
        {attention.items.length > 0 && (
          <Board title="Needs attention" raised icon={IconAlert}
                 action={<span className="count">
                   {attention.items.length}
                   <span className="sr-only">
                     {' '}change{attention.items.length === 1 ? '' : 's'}
                   </span>
                 </span>}
                 foot={attention.more > 0 ? (
                   <Link className="linkish" to="/calendar">
                     {attention.more} more change{attention.more === 1 ? '' : 's'} in the calendar
                   </Link>
                 ) : null}>
            {attention.items.map((item) => (
              <AttentionRow key={item.key} item={item} onOpen={openEvent} today={today} />
            ))}
          </Board>
        )}

        {/* ② Rep only: the queue that blocks other people. */}
        {isRep && rep && rep.pending_requests?.length > 0 && (
          <Board title="Awaiting your decision" icon={IconUser}
                 action={<Link className="linkish" to="/community/manage">Open Manage</Link>}>
            {rep.pending_requests.map((request) => (
              <Row key={request.user_id} when={whenParts(request.requested_at)}
                   title={request.full_name}
                   meta="Asked to join your community" />
            ))}
          </Board>
        )}

        {/* ③ Coming up: today and the next seven days, once each, on the
            time spine - it IS a sequence in time. */}
        <Board title="Coming up" icon={IconCalendar} className="board--timeline"
               action={<span className="t-meta">Today and the next {NEXT_DAYS} days</span>}>
          {comingUp.length === 0 ? (
            attention.items.length > 0 ? (
              <EmptyState title="Nothing else coming up" icon={IconCalendar}
                          message="Everything due in the next week is listed under Needs attention." />
            ) : (
              <EmptyState title="Nothing due in the next week" icon={IconCalendar}
                          message="Deadlines, quizzes and exams appear here as your reps publish them." />
            )
          ) : comingUp.map((event) => {
            const days = daysUntil(event.event_date);
            return (
              <Row key={event.id} when={whenParts(event.event_date)} title={event.title}
                   today={days === 0}
                   onClick={() => openEvent(event.id)}
                   meta={<>{eventMeta(event)}{event.completed ? <> · <Completion done /></> : null}</>}
                   side={<>
                     <StatusBadge value={event.status} />
                     {/* Work with a deadline says so the way the calendar
                         does; anything else states only its distance. Today
                         and Tomorrow are already named in the date column. */}
                     {isAssessment(event)
                       ? <DueLabel event={event} />
                       : days > 1 && <span className="t-meta">in {days} days</span>}
                   </>} />
            );
          })}
        </Board>
      </div>

      {/* Yours and your community's: reminders, announcements, who runs it. */}
      <aside className="dash__aside" aria-label="Your reminders and your community">
        {/* ④ Your reminders - also a sequence in time. */}
        <Board title="Your reminders" icon={IconBell} className="board--timeline"
               action={<Link className="linkish" to="/reminders">
                 See all<span className="sr-only"> reminders</span>
               </Link>}>
          {pendingReminders.length === 0 ? (
            <EmptyState title="No reminders yet" icon={IconBell}
                        message="Reminders are personal — nobody else sees them."
                        action={<Link className="btn btn--secondary" to="/reminders">
                          Add a reminder
                        </Link>} />
          ) : pendingReminders.slice(0, 4).map((reminder) => (
            /* The day goes in the column; only the clock time, which no other
               row has, goes in the meta. A scheduled reminder is the normal
               case, so it carries no badge. */
            <Row key={reminder.id} when={whenParts(reminderLocal(reminder))}
                 today={whenParts(reminderLocal(reminder)).top === 'Today'}
                 title={reminder.title}
                 meta={localTime(reminderLocal(reminder))}
                 side={<StatusBadge value={reminder.status} context="reminder" />} />
          ))}
        </Board>

        {/* ⑤ Announcements */}
        <Board title="Announcements" icon={IconMegaphone}>
          {(!announcements || announcements.length === 0) ? (
            <EmptyState title="No announcements" icon={IconMegaphone}
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

        {/* ⑥ Your community: which community this is - labelled, so no value
            has to be guessed - and who runs it. */}
        <Board title="Your community" icon={IconCommunity}
               action={<Link className="linkish" to="/community">
                 Open<span className="sr-only"> Community</span>
               </Link>}>
          <div className="dash__facts">
            <Facts items={[
              { label: 'University', value: community.university },
              { label: 'Department', value: community.department },
              { label: 'Level', value: community.level, mono: true },
              { label: 'Session', value: community.academic_session, mono: true },
            ]} />
          </div>
          <Row title={community.reps.length === 0
                        ? 'No verified course rep yet'
                        : `Course rep${community.reps.length === 1 ? '' : 's'}: `
                          + community.reps.map((r) => r.full_name).join(', ')}
               meta={`${community.member_count} member${community.member_count === 1 ? '' : 's'}`} />
        </Board>
      </aside>
    </div>
  );
}
