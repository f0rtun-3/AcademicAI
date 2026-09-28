// The hero's product preview.
//
// Assembled from the application's OWN primitives — Board, Row, StatusBadge,
// Tile — rather than a screenshot or an abstract illustration. Three reasons:
//
//   1. It cannot go stale. Restyle a row and the marketing page restyles with
//      it, so the landing page can never promise a UI the product no longer
//      has.
//   2. It costs no image bytes and no extra request.
//   3. It is honest. This is genuinely what a dashboard row looks like.
//
// It is INERT by construction: every Row is rendered without onClick, so
// nothing inside is focusable and a keyboard user tabs straight past it to the
// real calls to action. The whole figure is aria-hidden with a text
// alternative supplied by the caller's surrounding copy.
//
// The data is illustrative sample content, clearly generic (COS202, GEDS201 —
// real Babcock course codes are not used to imply an affiliation), and the
// dates are relative strings rather than fabricated calendar dates.

import { Board, Row, StatusBadge } from './ui.jsx';
import { IconAlert, IconMegaphone } from './icons.jsx';

export default function ProductPreview() {
  return (
    <div className="preview rise" aria-hidden="true">
      <div className="preview__bar">
        <span className="preview__dot" />
        <span className="preview__dot" />
        <span className="preview__dot" />
        <span className="preview__label">Dashboard</span>
      </div>

      <div className="preview__body">
        <Board title="Needs attention" icon={IconAlert}>
          <Row when={{ top: 'Today', bottom: '18 Sep' }}
               title="COS202 Assignment"
               meta="Data Structures · due 23:59"
               side={<StatusBadge value="SCHEDULED" />} />
          <Row when={{ top: 'Tomorrow', bottom: '19 Sep' }}
               title="GEDS201 Presentation"
               meta="Venue changed · B007"
               side={<StatusBadge value="VENUE_CHANGED" />} />
          <Row when={{ top: 'Fri', bottom: '21 Sep' }}
               title="SEN212 Quiz"
               meta="Software Requirements"
               side={<StatusBadge value="RESCHEDULED" />} />
        </Board>

        <Board title="Official updates" icon={IconMegaphone}>
          <Row title="Mid-semester timetable published"
               meta="Published by your course rep"
               side={<StatusBadge value="PUBLISHED" />} />
        </Board>
      </div>
    </div>
  );
}
