// The Agenda: events grouped by day, with a day heading that carries the
// weekday, the date and — for today — a marker.
//
// EVENT VISUAL LANGUAGE
// ---------------------
// Type is shown as a glyph plus its word, in neutral ink. Status keeps the
// semantic colour, through StatusBadge - which stays silent for an event that
// is simply scheduled, so the badge that does appear is noticed.
//
// That split is deliberate. The design system reserves accent/info/warn/crit
// for STATE, and an event's type is not a state — colouring eight types from
// the same four-colour palette would make "assignment" and "cancelled" compete
// for the same meaning. It also satisfies the accessibility rule directly:
// nothing here is distinguished by colour alone, because the word is always
// present beside the glyph.

import { Completion, StatusBadge, daysUntil, humanTime } from '../ui.jsx';
import { eventTypeLabel } from '../../lib/vocabulary.js';
import {
  IconAlert, IconBook, IconCalendar, IconClock, IconEdit, IconPin, IconSpark,
} from '../icons.jsx';
import { parseISO, isAssessment } from '../../lib/calendar.js';

const LONG_DAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday',
                   'Friday', 'Saturday'];
const LONG_MONTHS = ['January', 'February', 'March', 'April', 'May', 'June',
                     'July', 'August', 'September', 'October', 'November', 'December'];

// One glyph per type. Neutral by construction — they inherit ink, not a
// semantic colour.
const TYPE_ICON = {
  ASSIGNMENT: IconEdit,
  PROJECT: IconBook,
  QUIZ: IconSpark,
  TEST: IconAlert,
  EXAM: IconAlert,
  PRESENTATION: IconBook,
  CLASS: IconCalendar,
  OTHER: IconCalendar,
};

export function EventType({ type }) {
  const Icon = TYPE_ICON[type] ?? IconCalendar;
  return (
    <span className="etype">
      <Icon size={14} />
      <span>{eventTypeLabel(type)}</span>
    </span>
  );
}

// "Due tomorrow", "In 3 days" — computed from the event's own date, which the
// backend already supplies. It states proximity; it does not invent urgency,
// and it is only shown for assessment types where a deadline is the point.
function Proximity({ event, today }) {
  if (!event.event_date || event.status === 'CANCELLED') return null;
  if (!isAssessment(event)) return null;
  const days = daysUntil(event.event_date, today);
  if (days === null || days < 0 || days > 7) return null;
  const word = days === 0 ? 'Due today' : days === 1 ? 'Due tomorrow' : `Due in ${days} days`;
  // HIGH priority is a real stored field, not a frontend guess.
  const urgent = days <= 1 || event.priority === 'HIGH';
  return <span className={`due${urgent ? ' due--now' : ''}`}>{word}</span>;
}

function DayHeading({ date, isToday, count }) {
  if (!date) {
    return (
      <div className="agday__head">
        <div className="agday__date">
          <span className="agday__dow">No date</span>
        </div>
        <span className="agday__count mono">
          {count} {count === 1 ? 'item' : 'items'}
        </span>
      </div>
    );
  }
  const d = parseISO(date);
  return (
    <div className={`agday__head${isToday ? ' agday__head--today' : ''}`}>
      <div className="agday__date">
        <span className="agday__dow">{isToday ? 'Today' : LONG_DAYS[d.getDay()]}</span>
        <span className="agday__dm">{d.getDate()} {LONG_MONTHS[d.getMonth()]}</span>
      </div>
      <span className="agday__count mono">
        {count} {count === 1 ? 'item' : 'items'}
      </span>
    </div>
  );
}

function AgendaEvent({ event, onOpen, today }) {
  const cancelled = event.status === 'CANCELLED';
  return (
    <button type="button"
            className={`agev${cancelled ? ' agev--cancelled' : ''}`}
            onClick={() => onOpen(event.id)}>
      {/* Time column. "All day" rather than a blank when the backend has no
          time — an absent field is stated, never hidden. */}
      <span className="agev__time mono">
        {event.event_time ? humanTime(event.event_time) : <span className="agev__allday">All day</span>}
      </span>

      <span className="agev__body">
        <span className="agev__top">
          {event.course_code && <span className="agev__course mono">{event.course_code}</span>}
          <span className="agev__title">{event.title}</span>
        </span>
        <span className="agev__meta">
          <EventType type={event.event_type} />
          {event.venue
            ? <span className="agev__bit"><IconPin size={13} />{event.venue}</span>
            : <span className="agev__bit agev__bit--absent">Venue not specified</span>}
          <Proximity event={event} today={today} />
          {event.completed && <Completion done />}
        </span>
      </span>

      <span className="agev__side">
        {/* "Scheduled" is the normal case and carries no badge; a
            cancellation does, beside its struck-through title. */}
        <StatusBadge value={event.status} />
      </span>
    </button>
  );
}

export default function AgendaView({ groups, onOpen, todayKey, today }) {
  return (
    <div className="agenda">
      {groups.map(({ date, items }) => (
        // A month view legitimately includes days that have passed. They are
        // dimmed rather than hidden: the record still matters, but the eye
        // should land on what is still ahead.
        <section className={`agday${date && date < todayKey ? ' agday--past' : ''}`}
                 key={date ?? 'undated'}>
          <DayHeading date={date} isToday={date === todayKey} count={items.length} />
          <div className="agday__list">
            {items.map((event) => (
              <AgendaEvent key={event.id} event={event} onOpen={onOpen} today={today} />
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}
