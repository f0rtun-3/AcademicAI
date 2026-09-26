// S6 · Calendar.
//
// Two views over the SAME single fetch of /api/calendar. There is no second
// event store, no local cache and no extra request: /api/calendar returns
// every event and the recurring timetable, and everything below is a
// projection of that one payload.
//
//   Agenda  the anchored month, grouped by day. Primary at every width.
//   Week    the anchored week: recurring timetable with that week's dated
//           events laid over it. WITHDRAWN below 640px, not compressed —
//           a seven-column time grid at 375px is unreadable.
//
// NAVIGATION. The anchor is one date. The header always shows its month. The
// step buttons page by month in Agenda and by week in Week, because that is
// what each view is actually moving through; their accessible names say which.
// None of this touches the API — the backend takes no date range, so paging is
// a filter over data already in hand.
//
// Opening an event navigates to /events/:id (S7), the existing route. No event
// business logic is duplicated here.

import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api/client.js';
import { useResource } from '../components/useResource.js';
import { ErrorState, Loading } from '../components/States.jsx';
import { todayISO } from '../components/ui.jsx';
import { spokenDay } from '../lib/vocabulary.js';
import {
  CalendarHeader, CalendarSummary, CalendarToolbar,
} from '../components/calendar/CalendarChrome.jsx';
import AgendaView from '../components/calendar/AgendaView.jsx';
import WeekView from '../components/calendar/WeekView.jsx';
import CalendarEmptyState from '../components/calendar/CalendarEmptyState.jsx';
import {
  addDays, addMonths, applyFilter, eventsForWeek, eventsInMonth, groupByDay,
  hourRange, monthLabel, parseISO, sameMonth, startOfToday, startOfWeek,
  summarise, toISO, weekColumns,
} from '../lib/calendar.js';

export default function CalendarPage() {
  const navigate = useNavigate();
  const { status, data, error, reload } = useResource(() => api.get('/calendar'));
  const [view, setView] = useState('agenda');
  const [filter, setFilter] = useState('ALL');
  const [anchor, setAnchor] = useState(() => startOfToday());

  const today = startOfToday();
  const todayKey = todayISO();

  const events = data?.events ?? [];
  const timetable = data?.timetable ?? [];

  // Derivations are memoised on the payload rather than recomputed per render;
  // the grouping walks every event and the page re-renders on each keystroke
  // in the filter.
  const filtered = useMemo(() => applyFilter(events, filter), [events, filter]);
  const summary = useMemo(() => summarise(events, today), [events, todayKey]);
  const monthEvents = useMemo(() => eventsInMonth(filtered, anchor), [filtered, anchor]);
  const groups = useMemo(() => groupByDay(monthEvents), [monthEvents]);

  const weekStart = useMemo(() => startOfWeek(anchor), [anchor]);
  const weekEvents = useMemo(() => eventsForWeek(filtered, weekStart), [filtered, weekStart]);
  const columns = useMemo(
    () => weekColumns(timetable, filtered, weekStart), [timetable, filtered, weekStart],
  );
  const range = useMemo(() => hourRange(timetable, filtered), [timetable, filtered]);

  if (status === 'loading') return <Loading label="Loading your calendar…" />;
  if (status === 'error') return <ErrorState message={error} onRetry={reload} />;

  // The filter offers only types the backend actually returned, so it can
  // never present a category this community has no events for.
  const types = ['ALL', ...[...new Set(events.map((e) => e.event_type))].sort()];

  const step = (direction) => setAnchor((current) => (
    view === 'week' ? addDays(current, 7 * direction) : addMonths(current, direction)
  ));
  const isToday = view === 'week'
    ? toISO(startOfWeek(today)) === toISO(weekStart)
    : sameMonth(anchor, today);

  // Why the agenda is empty, so the empty state can say something useful and
  // offer the way out rather than just reporting absence.
  let emptyReason = null;
  let nextDate = null;
  if (view === 'agenda' && groups.length === 0) {
    if (events.length === 0) {
      emptyReason = 'nothing';
    } else if (eventsInMonth(events, anchor).length > 0) {
      emptyReason = 'filtered';
    } else {
      // Nearest dated event in either direction, preferring the future.
      const dated = events.filter((e) => e.event_date)
        .sort((a, b) => a.event_date.localeCompare(b.event_date));
      const ahead = dated.find((e) => e.event_date >= toISO(anchor));
      const target = ahead ?? dated[dated.length - 1];
      if (target) {
        const date = parseISO(target.event_date);
        emptyReason = 'off-month';
        nextDate = { label: `${target.title} on ${spokenDay(target.event_date)}`,
                     month: monthLabel(date), date };
      } else {
        emptyReason = 'nothing';
      }
    }
  }

  return (
    <div className="stack stack--loose calpage">
      {/* STRUCTURAL. Title, month and description render identically whether
          or not there are events — this header is never part of an empty
          state, and its shape does not change when the data runs out. */}
      <CalendarHeader anchor={anchor} />

      <CalendarSummary summary={summary} />

      <CalendarToolbar
        view={view} onView={setView}
        filter={filter} onFilter={setFilter} types={types}
        anchor={anchor} onStep={step}
        onToday={() => setAnchor(startOfToday())} isToday={isToday}
      />

      <div id="calendar-panel" role="tabpanel"
           aria-labelledby={view === 'week' ? 'tab-week' : 'tab-agenda'}>
        {view === 'agenda' ? (
          emptyReason ? (
            <CalendarEmptyState
              reason={emptyReason} anchor={anchor} filter={filter} nextDate={nextDate}
              onClearFilter={() => setFilter('ALL')}
              onJump={() => nextDate && setAnchor(nextDate.date)} />
          ) : (
            <AgendaView groups={groups} todayKey={todayKey} today={today}
                        onOpen={(id) => navigate(`/events/${id}`)} />
          )
        ) : (
          timetable.length === 0 && weekEvents.size === 0 ? (
            <CalendarEmptyState
              reason={events.length === 0 ? 'nothing' : 'off-month'}
              anchor={anchor} filter={filter}
              nextDate={nextDate ?? { label: 'elsewhere in the term',
                                      month: monthLabel(anchor), date: anchor }}
              onClearFilter={() => setFilter('ALL')}
              onJump={() => setAnchor(startOfToday())} />
          ) : (
            <WeekView columns={columns} entries={timetable} eventsByDay={weekEvents}
                      range={range} todayKey={todayKey}
                      onOpen={(id) => navigate(`/events/${id}`)} />
          )
        )}
      </div>
    </div>
  );
}
