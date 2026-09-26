// The Week grid: the recurring timetable, with the anchored week's dated
// events overlaid on it.
//
// WHAT THE DATA ALLOWS
// --------------------
// Timetable entries have `day_of_week` and `start_time` and NO date — they
// recur. Events have a real date. So the grid is a weekly shape that the
// anchored week's events are placed into, and the two are visually distinct:
// a timetable block is the standing class, an event block is a one-off.
//
// `end_time` is nullable. When it is missing a block is drawn one hour tall,
// and it says "time not specified" rather than implying a duration nobody
// recorded.
//
// Withdrawn entirely below 640px by CalendarPage, not compressed.

import { eventTypeNoun } from '../../lib/vocabulary.js';
import { EventType } from './AgendaView.jsx';
import { timeToMinutes, toISO } from '../../lib/calendar.js';

const SHORT = { MONDAY: 'Mon', TUESDAY: 'Tue', WEDNESDAY: 'Wed', THURSDAY: 'Thu',
                FRIDAY: 'Fri', SATURDAY: 'Sat', SUNDAY: 'Sun' };

const SLOT = 60;          // px per hour; also the CSS row height
const DEFAULT_MIN = 60;   // an entry with no end_time is drawn one hour tall

function offsetRows(startMinutes, fromHour) {
  return (startMinutes - fromHour * 60) / 60;
}

function Block({ kind, top, height, children, onClick, label }) {
  const style = { top: `${top * SLOT}px`, height: `${Math.max(height * SLOT, 34)}px` };
  const className = `wblock wblock--${kind}`;
  if (onClick) {
    return (
      <button type="button" className={className} style={style} onClick={onClick}
              aria-label={label}>
        {children}
      </button>
    );
  }
  return <div className={className} style={style}>{children}</div>;
}

export default function WeekView({
  columns, entries, eventsByDay, range, onOpen, todayKey,
}) {
  const hours = [];
  for (let h = range.from; h < range.to; h += 1) hours.push(h);

  const hasAllDay = [...eventsByDay.values()].some((list) => list.some((e) => !e.event_time));
  const axisRow = hasAllDay ? 3 : 2;

  return (
    <div className="weekwrap">
      <div className="week" style={{ '--week-cols': columns.length, '--slot': `${SLOT}px` }}>
        {/* Corner + day headings — row 1 */}
        <div className="week__corner" style={{ gridRow: 1, gridColumn: 1 }} />
        {columns.map((col) => {
          const isToday = col.date && toISO(col.date) === todayKey;
          return (
            <div key={col.day}
                 style={{ gridRow: 1, gridColumn: col.index + 2 }}
                 className={`week__dayhead${isToday ? ' week__dayhead--today' : ''}`}>
              <span className="week__dow">{SHORT[col.day]}</span>
              {col.date && <span className="week__dnum mono">{col.date.getDate()}</span>}
            </div>
          );
        })}

        {/* Time axis — row 3 when an all-day band exists, otherwise row 2 */}
        <div className="week__axis" style={{ gridRow: axisRow, gridColumn: 1 }}>
          {hours.map((h) => (
            <div className="week__hour mono" key={h} style={{ height: SLOT }}>
              {String(h).padStart(2, '0')}:00
            </div>
          ))}
        </div>

        {/* All-day band. An event with no time has no position on a time
            axis, so it gets its own row above the grid instead of being
            pinned to the first hour, where it collided with real entries
            scheduled at that hour. The band only exists when something needs
            it. */}
        {hasAllDay && (
          <div className="week__allkey" style={{ gridRow: 2, gridColumn: 1 }}>All day</div>
        )}
        {hasAllDay && columns.map((col) => {
          const allDay = (eventsByDay.get(col.day) ?? []).filter((e) => !e.event_time);
          return (
            <div className="week__allcell" key={`ad-${col.day}`}
                 style={{ gridRow: 2, gridColumn: col.index + 2 }}>
              {allDay.map((event) => (
                <button type="button" key={event.id}
                        className={`wchip${event.status === 'CANCELLED' ? ' wchip--cancelled' : ''}`}
                        onClick={() => onOpen(event.id)}
                        aria-label={`${event.title}, ${eventTypeNoun(event.event_type)}, all day`
                                    + `${event.status === 'CANCELLED' ? ', cancelled' : ''}`}>
                  <span className="wchip__code mono">{event.course_code ?? ''}</span>
                  <span className="wchip__title">{event.title}</span>
                </button>
              ))}
            </div>
          );
        })}

        {/* One positioned column per day */}
        {columns.map((col) => {
          const isToday = col.date && toISO(col.date) === todayKey;
          const dayEntries = entries.filter((e) => e.day_of_week === col.day);
          const dayEvents = (eventsByDay.get(col.day) ?? []).filter((e) => e.event_time);
          return (
            <div key={col.day}
                 className={`week__col${isToday ? ' week__col--today' : ''}`}
                 style={{ height: hours.length * SLOT,
                          gridRow: axisRow, gridColumn: col.index + 2 }}>
              {hours.map((h) => (
                <div className="week__cell" key={h} style={{ height: SLOT }} aria-hidden="true" />
              ))}

              {dayEntries.map((entry) => {
                const start = timeToMinutes(entry.start_time);
                if (start === null) return null;
                const end = timeToMinutes(entry.end_time);
                const span = end !== null && end > start
                  ? (end - start) / 60 : DEFAULT_MIN / 60;
                return (
                  <Block key={`t${entry.id}`} kind="class"
                         top={offsetRows(start, range.from)} height={span}>
                    <span className="wblock__code mono">
                      {entry.start_time}{entry.end_time ? `–${entry.end_time}` : ''}
                      {entry.venue ? ` · ${entry.venue}` : ''}
                    </span>
                    <span className="wblock__title">
                      {entry.course_code ?? entry.title ?? 'Class'}
                    </span>
                  </Block>
                );
              })}

              {dayEvents.map((event) => {
                const start = timeToMinutes(event.event_time);
                if (start === null) return null;          // handled by the band
                return (
                  <Block key={`e${event.id}`}
                         kind={event.status === 'CANCELLED' ? 'cancelled' : 'event'}
                         top={Math.max(0, offsetRows(start, range.from))}
                         height={DEFAULT_MIN / 60}
                         onClick={() => onOpen(event.id)}
                         label={`${event.title}, ${eventTypeNoun(event.event_type)}, `
                                + `${event.event_time}`
                                + `${event.status === 'CANCELLED' ? ', cancelled' : ''}`}>
                    <span className="wblock__code mono">
                      {event.course_code ?? event.event_time}
                    </span>
                    <span className="wblock__title">{event.title}</span>
                  </Block>
                );
              })}
            </div>
          );
        })}
      </div>

      {/* A legend, because the two block kinds mean different things and the
          difference is not decorative. */}
      <p className="week__legend t-meta">
        <span className="week__key week__key--class" aria-hidden="true" /> Recurring class
        <span className="week__key week__key--event" aria-hidden="true" /> Dated event
        <span className="week__note">
          Timetable entries repeat weekly; dated events belong to this week only.
        </span>
      </p>
    </div>
  );
}
