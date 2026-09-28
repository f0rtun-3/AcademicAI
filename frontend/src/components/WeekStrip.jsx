// The week at a glance: today and the six days after it, each with a mark
// per thing that is due.
//
// It answers "how heavy is my week?" before any list is read - the one
// question a stack of rows cannot answer at a glance. It holds nothing and
// decides nothing: it counts the events the dashboard already fetched, by the
// academic date each one carries. Titles are deliberately NOT repeated here;
// the lists below say what each thing is, and a strip that repeated them would
// be the same information twice.

import { addDays, parseISO, toISO } from '../lib/calendar.js';
import { spokenDay } from '../lib/vocabulary.js';

const SHORT = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const MAX_MARKS = 3;

export default function WeekStrip({ events = [], today }) {
  const start = parseISO(today);
  if (!start) return null;

  const days = Array.from({ length: 7 }, (_, i) => {
    const date = addDays(start, i);
    const iso = toISO(date);
    const onDay = events.filter((e) => e.event_date === iso);
    const due = onDay.filter((e) => e.status !== 'CANCELLED').length;
    const cancelled = onDay.length - due;
    const when = i === 0 ? `Today, ${spokenDay(iso)}` : spokenDay(iso);
    const said = due === 0 ? 'nothing due' : `${due} due`;
    return {
      iso, today: i === 0, dow: SHORT[date.getDay()], num: date.getDate(), due, cancelled,
      label: `${when}: ${said}${cancelled ? `, ${cancelled} cancelled` : ''}`,
    };
  });

  return (
    <ol className="wkstrip" aria-label="Your next seven days">
      {days.map((day) => (
        <li key={day.iso}
            className={`wkstrip__day${day.today ? ' wkstrip__day--today' : ''}`
                       + `${day.due ? ' wkstrip__day--busy' : ''}`}>
          {/* The weekday, even for today: the lit cell already says which
              day is today, and "Today" does not fit a 360px column. */}
          <span className="wkstrip__dow" aria-hidden="true">{day.dow}</span>
          <span className="wkstrip__num" aria-hidden="true">{day.num}</span>
          {/* One mark per thing due, up to three; a cancellation is a hollow
              mark so the day still shows it happened. */}
          <span className="wkstrip__marks" aria-hidden="true">
            {Array.from({ length: Math.min(day.due, MAX_MARKS) }, (_, i) => (
              <i key={`d${i}`} />
            ))}
            {day.due > MAX_MARKS && <b>+{day.due - MAX_MARKS}</b>}
            {day.cancelled > 0 && day.due < MAX_MARKS && <i className="is-cancelled" />}
          </span>
          <span className="sr-only">{day.label}</span>
        </li>
      ))}
    </ol>
  );
}
