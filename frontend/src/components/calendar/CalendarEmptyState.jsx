// The Calendar's empty states.
//
// "Empty" is three different situations and conflating them is what made the
// old screen unhelpful. A student whose exam is next month was told "Nothing
// scheduled", which was true of the view and false of their term.
//
//   NOTHING     the community has published no events at all
//   OFF-MONTH   events exist, just not in the month being viewed
//   FILTERED    events exist in this month, hidden by the type filter
//
// The last two carry the way out as a control, because the user's next action
// is obvious and the screen may as well offer it.
//
// The CTA is real: /reminders is an existing route whose "Add a reminder"
// panel posts to the existing /reminders endpoint with an optional event_id,
// so a personal reminder can be created with no academic event to attach it
// to. Nothing here is a decorative button.

import { Link } from 'react-router-dom';
import { IconCalendar } from '../icons.jsx';
import { eventTypePlural } from '../../lib/vocabulary.js';
import { monthLabel } from '../../lib/calendar.js';

// What a calendar holds, so the page explains itself when it has nothing to
// show. These are the event_type values the backend actually stores.
const KINDS = ['ASSIGNMENT', 'PROJECT', 'QUIZ', 'TEST', 'EXAM', 'PRESENTATION', 'CLASS'];

function Frame({ children }) {
  return (
    <div className="calempty">
      {/* A small ruled mark, the same figure as the brand. Not an illustration
          and not a giant grey box. */}
      <span className="calempty__mark" aria-hidden="true">
        <IconCalendar size={24} />
      </span>
      {children}
    </div>
  );
}

export default function CalendarEmptyState({
  reason, anchor, filter, nextDate, onClearFilter, onJump,
}) {
  if (reason === 'filtered') {
    return (
      <Frame>
        <h3>No {eventTypePlural(filter).toLowerCase()} in {monthLabel(anchor)}</h3>
        <p>
          Other event types are scheduled this month. Clear the filter to see them.
        </p>
        <button type="button" className="btn btn--secondary" onClick={onClearFilter}>
          Show all types
        </button>
      </Frame>
    );
  }

  if (reason === 'off-month') {
    return (
      <Frame>
        <h3>Nothing scheduled in {monthLabel(anchor)}</h3>
        <p>
          Your calendar is not empty — the next item is
          {' '}<strong>{nextDate.label}</strong>.
        </p>
        <button type="button" className="btn btn--secondary" onClick={onJump}>
          Go to {nextDate.month}
        </button>
      </Frame>
    );
  }

  return (
    <Frame>
      <h3>Nothing scheduled yet</h3>
      <p>
        Academic events published by your course representative appear here —
        with the date, time, venue and course attached.
      </p>

      <div className="calempty__kinds">
        <span className="t-label">Your calendar will hold</span>
        <ul>
          {KINDS.map((kind) => <li key={kind}>{eventTypePlural(kind)}</li>)}
        </ul>
      </div>

      <p className="calempty__cta">
        In the meantime you can keep your own private notes:{' '}
        <Link className="linkish" to="/reminders">add a personal reminder</Link>.
        Only you can see those.
      </p>
    </Frame>
  );
}
