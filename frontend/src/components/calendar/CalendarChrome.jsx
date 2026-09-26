// The Calendar's frame: header, summary and toolbar.
//
// The HEADER IS STRUCTURAL. It renders identically whether or not there are
// events — title, month, description, always, in that order. It is deliberately
// not part of the empty state: a page whose heading changes shape when its data
// runs out reads as two different screens.

import {
  IconBack, IconCalendar, IconChevronRight, IconFilter,
} from '../icons.jsx';
import { monthLabel } from '../../lib/calendar.js';
import { eventTypePlural } from '../../lib/vocabulary.js';

/* ── Header ──────────────────────────────────────────────────────────────── */

export function CalendarHeader({ anchor }) {
  return (
    <header className="page__head calhead">
      <h1 className="t-display">Calendar</h1>
      {/* The month is DATA, so it takes the mono face, and it tracks the
          anchor rather than being fixed. */}
      <p className="calhead__month" aria-live="polite">{monthLabel(anchor)}</p>
      <p className="calhead__lede">
        Keep track of classes, deadlines, presentations and exams.
      </p>
    </header>
  );
}

/* ── Summary ─────────────────────────────────────────────────────────────── */

// Every number is counted from the events the backend returned. A zero is
// shown as a zero — there is no version of this component that invents
// activity to look busy.
export function CalendarSummary({ summary }) {
  const cards = [
    { n: summary.upcoming, label: 'Upcoming', sub: 'scheduled from today' },
    { n: summary.thisWeek, label: 'Next 7 days', sub: 'in the coming week' },
    { n: summary.deadlines, label: 'Assessments', sub: 'due within 7 days' },
  ];
  return (
    <div className="calsum">
      {cards.map((card) => (
        <div className="calsum__card" key={card.label}>
          <span className="calsum__n mono">{card.n}</span>
          <span className="calsum__label">{card.label}</span>
          <span className="calsum__sub">{card.sub}</span>
        </div>
      ))}
      {/* Only appears when there is something to report. */}
      {summary.cancelled > 0 && (
        <div className="calsum__card calsum__card--note">
          <span className="calsum__n mono">{summary.cancelled}</span>
          <span className="calsum__label">Cancelled</span>
          <span className="calsum__sub">still ahead of today</span>
        </div>
      )}
    </div>
  );
}

/* ── Toolbar ─────────────────────────────────────────────────────────────── */

// View switcher, type filter and date navigation in one bar.
//
// The step buttons are context-aware: a month in Agenda, a week in Week, which
// is what each view is actually paging through. Their accessible names say so
// explicitly, so the control is never just an ambiguous arrow.
export function CalendarToolbar({
  view, onView, filter, onFilter, types, anchor, onStep, onToday, isToday, weekOnly,
}) {
  const unit = view === 'week' ? 'week' : 'month';
  return (
    <div className="caltoolbar">
      <div className="caltoolbar__views" role="tablist" aria-label="Calendar view">
        <button type="button" role="tab" id="tab-agenda"
                aria-selected={view === 'agenda'} aria-controls="calendar-panel"
                className={view === 'agenda' ? 'is-on' : undefined}
                onClick={() => onView('agenda')}>
          <IconCalendar size={16} />
          Agenda
        </button>
        {/* Week is withdrawn below 640px by the stylesheet, not compressed: a
            seven-column grid at 375px is unreadable. */}
        {!weekOnly && (
          <button type="button" role="tab" id="tab-week"
                  aria-selected={view === 'week'} aria-controls="calendar-panel"
                  className={view === 'week' ? 'is-on' : undefined}
                  onClick={() => onView('week')}>
            <IconCalendar size={16} />
            Week
          </button>
        )}
      </div>

      <div className="caltoolbar__nav">
        <button type="button" className="btn btn--secondary btn--icon calstep" onClick={() => onStep(-1)}
                aria-label={`Previous ${unit}`} title={`Previous ${unit}`}>
          <IconBack size={16} />
        </button>
        <span className="calstep__label" aria-hidden="true">{monthLabel(anchor)}</span>
        <button type="button" className="btn btn--secondary btn--icon calstep" onClick={() => onStep(1)}
                aria-label={`Next ${unit}`} title={`Next ${unit}`}>
          <IconChevronRight size={16} />
        </button>
        <button type="button" className="btn btn--secondary calstep__today"
                onClick={onToday} disabled={isToday}
                title={isToday ? 'Already showing today' : 'Jump to today'}>
          Today
        </button>
      </div>

      <div className="caltoolbar__filter field">
        <label htmlFor="cal-filter" className="sr-only">Filter by event type</label>
        <span className="caltoolbar__filtericon" aria-hidden="true"><IconFilter size={15} /></span>
        <select id="cal-filter" value={filter} onChange={(e) => onFilter(e.target.value)}>
          {types.map((type) => (
            <option key={type} value={type}>
              {type === 'ALL' ? 'All types' : eventTypePlural(type)}
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}
