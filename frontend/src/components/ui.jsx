// The design-system primitives every screen is built from.
//
// Two rules hold this file together:
//
//   1. A chip is a READING of state, never the state itself. Nothing here may
//      decide what a user is allowed to do - these components render what the
//      backend said, and the backend re-checks every write regardless.
//   2. Personal completion is not a status. It has its own marker (Completion)
//      and may never be rendered through StateChip.

import { useEffect, useId, useRef, useState } from 'react';
import { IconCheck, IconChevronRight, IconEye, IconEyeOff } from './icons.jsx';
import { TONE, isRoutineStatus, statusLabel } from '../lib/vocabulary.js';
import { academicClockTime, academicDateOf, academicToday } from '../lib/academicTime.js';

/* ── Formatting ─────────────────────────────────────────────────────────── */

const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

// A calendar day as a local Date at midnight, for day arithmetic only. The DAY
// is the academic one: an instant ("…T23:30:00+00:00") is read on the
// university's clock first, because its own first ten characters are the UTC
// date - a different day for part of every night.
function parseDate(value) {
  const day = academicDateOf(value);
  if (!day) return null;
  const date = new Date(`${day}T00:00:00`);
  return Number.isNaN(date.getTime()) ? null : date;
}

// Today on the university's clock (lib/academicTime.js), not the device's.
export function todayISO(now = new Date()) {
  return academicToday(now);
}

// "Mon / 21 Sep", with today and tomorrow named rather than dated — the
// departure-board column. Returns the two lines separately so the row can set
// them on their own baselines.
export function whenParts(value, today = parseDate(todayISO())) {
  const date = parseDate(value);
  if (!date) return { top: '—', bottom: 'no date' };
  const days = Math.round((date - today) / 86400000);
  if (days === 0) return { top: 'Today', bottom: `${date.getDate()} ${MONTHS[date.getMonth()]}` };
  if (days === 1) return { top: 'Tomorrow', bottom: `${date.getDate()} ${MONTHS[date.getMonth()]}` };
  return { top: DAYS[date.getDay()], bottom: `${date.getDate()} ${MONTHS[date.getMonth()]}` };
}

export function daysUntil(value, today = parseDate(todayISO())) {
  const date = parseDate(value);
  if (!date) return null;
  return Math.round((date - today) / 86400000);
}

const LONG_DAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday',
                   'Friday', 'Saturday'];
const LONG_MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July',
                     'August', 'September', 'October', 'November', 'December'];

// Day-month order, written out rather than delegated to the runtime locale: a
// student in Lagos reading "Friday 18 September" must not become "September 18"
// because the browser happens to be set to en-US.
export function longDate(value) {
  const date = parseDate(value);
  if (!date) return 'Not specified';
  return `${LONG_DAYS[date.getDay()]} ${date.getDate()} ${LONG_MONTHS[date.getMonth()]} `
       + `${date.getFullYear()}`;
}

export function humanTime(value) {
  return value || 'Not specified';
}

// Countdown as remaining time, announced as such rather than as a ticking
// string (accessibility requirement 17).
export function remaining(closesAt) {
  if (!closesAt) return null;
  const ms = new Date(closesAt).getTime() - Date.now();
  if (Number.isNaN(ms)) return null;
  if (ms <= 0) return 'closed';
  const hours = Math.floor(ms / 3600000);
  const minutes = Math.floor((ms % 3600000) / 60000);
  if (hours >= 24) return `${Math.floor(hours / 24)}d ${hours % 24}h left`;
  return hours > 0 ? `${hours}h ${minutes}m left` : `${minutes}m left`;
}

/* ── Reminder times ─────────────────────────────────────────────────────
 *
 * `<input type="datetime-local">` holds a wall-clock time with no zone. It is
 * sent AS SUCH, as remind_at_local, and the backend reads it on the
 * university's clock (with that zone's DST rules) - so the browser never turns
 * it into an instant, and a device set to another zone cannot move it. The API
 * returns remind_at_local for display and editing.
 *
 * It was once converted here with the DEVICE's zone, which put a Babcock
 * reminder on London time whenever the laptop was set to London.
 */

// "08:00" on the university's clock, for an instant or a wall-clock value.
export function localTime(value) {
  return academicClockTime(value);
}

export function initials(name) {
  return String(name || '?').trim().split(/\s+/).slice(0, 2)
    .map((part) => part[0] ?? '').join('').toUpperCase() || '?';
}

/* ── 11 · State chips ───────────────────────────────────────────────────── */

// Labels and tones come from the vocabulary layer (lib/vocabulary.js), the one
// place a canonical value becomes words. The chip's DOM text is the label
// itself - "Deadline moved", not DEADLINE_MOVED - so what the eye reads, what
// a screen reader announces and what a test queries are the same string.
export function stateLabel(value, context) {
  return statusLabel(value, context);
}

export function StateChip({ value, label, tone, title, context }) {
  if (!value && !label) return null;
  const resolved = tone ?? TONE[value] ?? '';
  return (
    <span className={`chip${resolved ? ` chip--${resolved}` : ''}`} title={title}>
      {label ?? statusLabel(value, context)}
    </span>
  );
}

// A status that earns a badge. Routine states - an event that is simply
// scheduled, an announcement that is simply published - render nothing, so
// the badge that does appear ("Cancelled", "Deadline moved") is noticed.
// Pages that must always state the status (a record's own detail list) use
// the plain label instead.
export function StatusBadge({ value, context, ...rest }) {
  if (!value || isRoutineStatus(value, context)) return null;
  return <StateChip value={value} context={context} {...rest} />;
}

// The community's own lifecycle state, labelled with its subject.
//
// WHY THIS EXISTS RATHER THAN A BARE StateChip
// -------------------------------------------
// The community header puts this chip directly after the student's name and
// academic profile, so an unlabelled "PENDING" reads as a statement about the
// READER - "your membership is pending" - when it is nothing of the kind. A
// real student hit exactly that: active member, unlabelled PENDING chip, and
// the reasonable conclusion that something of theirs was waiting.
//
// Two fixes, both scoped to the community:
//
//   1. The chip carries its subject visibly ("Community"), not just a tooltip.
//   2. PENDING is relabelled "No rep yet". For a community it does not mean
//      "waiting for approval" - it means no rep has been elected yet.
//
// The relabelling is the vocabulary's "community" context, not a global
// label: a PENDING reminder is a different idea (queued, not yet sent) and
// keeps its own word. Same token, two meanings.
const COMMUNITY_TITLE = {
  PENDING: 'This community has no elected course rep yet. '
         + 'It becomes active once its first rep election succeeds.',
  ACTIVE: 'This community has at least one verified course rep.',
  ARCHIVED: 'This academic session has ended. Its records are read-only.',
};

export function CommunityStatus({ status }) {
  if (!status) return null;
  return (
    <span className="substate">
      <span className="substate__of">Community</span>
      <StateChip value={status} context="community" title={COMMUNITY_TITLE[status]} />
    </span>
  );
}

// C·2 — personal completion. Slate, metadata line, never a chip and never the
// status column. The scope is in the words, not only in the styling.
export function Completion({ done }) {
  if (!done) return null;
  return (
    <span className="pmark">
      <IconCheck size={13} />
      {' '}Done — only you can see this
    </span>
  );
}

/* ── Page header ────────────────────────────────────────────────────────── */

// The top of every page, in one place.
//
// The audit found each screen inventing its own: Calendar had title + month +
// lede, Profile had a bare name floating on the page ground, Settings had a
// title and nothing else. A page whose heading changes shape from route to
// route reads as several products.
//
// Structure, top to bottom:
//   eyebrow  optional, mono, the page's DATA line (a month, a community, a
//            course code) — never prose
//   title    the page's one <h1>
//   lede     one sentence saying what the page is for
//   meta     optional row beneath (chips, status, counts)
//   action   optional right-aligned control
//
// `lede` is deliberately not optional-by-convention: a page with nothing worth
// saying about it usually has a hierarchy problem rather than a copy problem.
//
// `surface` puts the whole composition on a card. It is for a header that
// carries STATE as well as a title — the dashboard's welcome, which has to
// group the greeting with the community it greets you into. A header that is
// only a title and a sentence stays on the page ground, because a card around
// two lines of text is a box for its own sake.
export function PageHeader({ title, eyebrow, lede, meta, action, surface = false,
                             className = '', children }) {
  return (
    <header className={`page__head phead${surface ? ' phead--surface' : ''}`
                       + `${className ? ` ${className}` : ''}`}>
      <div className="phead__row">
        <div className="phead__text">
          {eyebrow && <p className="phead__eyebrow">{eyebrow}</p>}
          <h1 className="t-display">{title}</h1>
          {lede && <p className="phead__lede">{lede}</p>}
        </div>
        {action && <div className="phead__action">{action}</div>}
      </div>
      {meta && <div className="phead__meta">{meta}</div>}
      {children}
    </header>
  );
}

// A labelled fact strip. Several short attributes, each keeping its own name.
//
// The alternative — joining them with " · " into one line — is how the
// dashboard used to read, and it loses the labels: "Babcock University ·
// Computer Science · Level 300 · 2025/2026" asks the reader to work out which
// value is which. A record states its fields.
//
// Values with no data are dropped rather than rendered as "Not set": this is a
// header, and a header that lists absences is noise. Pages that must account
// for a missing value say so in their own body (see Profile's Academic panel).
export function Facts({ items }) {
  const shown = items.filter((f) => f.value !== null && f.value !== undefined && f.value !== '');
  if (shown.length === 0) return null;
  return (
    <dl className="facts">
      {shown.map((f) => (
        <div className="fact" key={f.label}>
          <dt>{f.label}</dt>
          <dd className={f.mono ? 'mono' : undefined}>{f.value}</dd>
        </div>
      ))}
    </dl>
  );
}

/* ── 10 · Containers ────────────────────────────────────────────────────── */

export function Panel({ title, action, children, as: Tag = 'section',
                        className = '', ...rest }) {
  return (
    <Tag className={`panel ${className}`.trim()} {...rest}>
      {(title || action) && (
        <div className="panel__head">
          {title && <h2 className="t-section">{title}</h2>}
          {action}
        </div>
      )}
      {children}
    </Tag>
  );
}

// A board's title is a section heading a student scans for ("Needs
// attention", "Coming up"), so it is set as one - not as an 11px caption.
export function Board({ title, action, children, foot, className = '', ...rest }) {
  return (
    <section className={`board ${className}`.trim()} {...rest}>
      {(title || action) && (
        <div className="board__head">
          {title && <h2 className="board__title">{title}</h2>}
          {action}
        </div>
      )}
      {children}
      {foot && <div className="board__foot">{foot}</div>}
    </section>
  );
}

// The row pattern everything else is built from: urgency leftmost in tabular
// mono, state chip always in the same column.
export function Row({ when, title, meta, side, onClick, ...rest }) {
  const body = (
    <>
      {when && (
        <div className="brow__when">
          <strong>{when.top}</strong>
          {when.bottom}
        </div>
      )}
      <div className="brow__main">
        <div className="brow__title">{title}</div>
        {meta && <div className="brow__meta">{meta}</div>}
      </div>
      <div className="brow__side">{side}</div>
    </>
  );
  if (onClick) {
    // A row that opens something says so. Hover cannot carry that on touch, so
    // the affordance is a chevron rather than a state the finger never sees.
    return (
      <button type="button"
              className={`brow brow--link${when ? '' : ' brow--flat'}`}
              onClick={onClick} {...rest}>
        {body}
        <span className="brow__go" aria-hidden="true"><IconChevronRight size={16} /></span>
      </button>
    );
  }
  return <div className={`brow${when ? '' : ' brow--flat'}`} {...rest}>{body}</div>;
}

export function Tile({ n, label }) {
  return (
    <div className="tile">
      <div className="tile__n">{n}</div>
      <div className="t-label">{label}</div>
    </div>
  );
}

/* ── 12 · Notices ───────────────────────────────────────────────────────── */

export function Notice({ tone = 'info', label, children, role, ...rest }) {
  return (
    <div className={`notice notice--${tone}`} role={role} {...rest}>
      {label && <span className="notice__label">{label}</span>}
      {children}
    </div>
  );
}

/* ── 11 · Tally ─────────────────────────────────────────────────────────── */

// The empty remainder is the votes STILL REQUIRED, so "fewer than the minimum
// fails" is visible rather than something a voter has to already know.
export function Tally({ yes = 0, no = 0, needed = 0, closesAt, note }) {
  const cast = yes + no;
  const width = Math.max(cast, needed) || 1;
  const left = remaining(closesAt);
  const shortfall = Math.max(0, needed - cast);
  return (
    <div className="stack stack--tight">
      <div className="t-meta" aria-hidden="true">
        {yes} yes · {no} no · {needed} votes needed
      </div>
      <div className="tally__bar">
        <div className="tally__yes" style={{ width: `${(yes / width) * 100}%` }} />
        <div className="tally__no" style={{ width: `${(no / width) * 100}%` }} />
      </div>
      <div className="t-meta">
        <span className="sr-only">{yes} yes, {no} no, {needed} votes needed. </span>
        {shortfall > 0
          ? `${shortfall} more vote${shortfall === 1 ? '' : 's'} needed to count`
          : 'Minimum met'}
        {note ? ` · ${note}` : ''}
        {left ? ` · ${left}` : ''}
      </div>
    </div>
  );
}

/* ── 9 · Fields ─────────────────────────────────────────────────────────── */

// Labels are always visible and always above the field. No placeholder-as-
// label: it vanishes exactly when the user needs it.
// A label, its control, and the one line that qualifies it — in that order,
// always, with nothing allowed between the label and the control it names.
//
// `required` is marked with a CSS pseudo-element rather than text in the
// label. Two reasons: the label's own text stays exactly what it says (so a
// test or a user searching the page finds "Level", not "Level *"), and the
// requirement itself is already carried to assistive technology by the
// control's native `required` attribute — the marker only has a job for the
// eye. Render-prop fields pass `required` to Field as well as to their child,
// because in that branch `rest` never reaches an element.
export function Field({ id, label, hint, error, children, className = '', ...rest }) {
  const hintId = hint ? `${id}-hint` : undefined;
  const errId = error ? `${id}-err` : undefined;
  const describedBy = [hintId, errId].filter(Boolean).join(' ') || undefined;
  const cls = ['field', rest.required ? 'field--req' : '', className]
    .filter(Boolean).join(' ');
  return (
    <div className={cls}>
      <label htmlFor={id}>{label}</label>
      {children
        ? children({ id, 'aria-describedby': describedBy, 'aria-invalid': error ? 'true' : undefined })
        : (
          <input id={id} aria-describedby={describedBy}
                 aria-invalid={error ? 'true' : undefined} {...rest} />
        )}
      {hint && <span className="hint" id={hintId}>{hint}</span>}
      {error && <span className="err" id={errId}>{error}</span>}
    </div>
  );
}

/* ── 14 · Modal ─────────────────────────────────────────────────────────── */

// Used only where an action is hard to undo and needs its consequences read
// first. Focus is trapped and returned to the trigger; Escape closes; a
// backdrop click does NOT close a destructive dialog.
const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), '
  + 'select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

// A password field with a visibility control.
//
// Built on Field so the label, hint, error and aria wiring are identical to
// every other input - the only addition is the toggle. The button is
// type="button" (never submits), is labelled for screen readers, and reports
// the CURRENT state rather than the action, because "Hide password" on a
// masked field reads as a lie.
//
// Autocomplete is passed through rather than guessed: a sign-in field wants
// "current-password" and a sign-up field wants "new-password", and getting
// that wrong makes password managers offer the wrong thing.
export function PasswordInput({ id, label, hint, error, value, onChange,
                                autoComplete = 'current-password', ...rest }) {
  const [shown, setShown] = useState(false);
  return (
    // `required` is forwarded so the label carries the same marker every other
    // required field has. It also stays in `rest`, so the input keeps the real
    // attribute — the marker and the requirement are never set separately.
    <Field id={id} label={label} hint={hint} error={error} required={rest.required}>
      {(fieldProps) => (
        <span className={`pw${error ? ' pw--err' : ''}`}>
          <input {...fieldProps} {...rest}
                 type={shown ? 'text' : 'password'}
                 value={value} onChange={onChange}
                 autoComplete={autoComplete} />
          <button type="button" className="pw__toggle"
                  onClick={() => setShown((on) => !on)}
                  aria-label={shown ? 'Password shown. Hide it.' : 'Password hidden. Show it.'}
                  title={shown ? 'Hide password' : 'Show password'}>
            {shown ? <IconEyeOff size={18} /> : <IconEye size={18} />}
          </button>
        </span>
      )}
    </Field>
  );
}

// `className` exists for one case: a viewer needs to be wide and tall, and a
// confirmation needs to be neither.
export function Modal({ title, children, onClose, actions, className = '' }) {
  const ref = useRef(null);
  const titleId = useId();
  // Callers pass an inline `onClose`, which is a new function on every render.
  // Held in a ref so the effect below runs once per OPENING: with `onClose` in
  // its dependencies, any parent re-render (a busy flag flipping) tore it down
  // - sending focus to the trigger behind the scrim - and then pulled focus
  // back to the dialog, losing the reader's place mid-action.
  const closeRef = useRef(onClose);
  useEffect(() => { closeRef.current = onClose; });

  useEffect(() => {
    const previous = document.activeElement;
    ref.current?.focus();

    const onKey = (event) => {
      if (event.key === 'Escape') { closeRef.current(); return; }
      if (event.key !== 'Tab' || !ref.current) return;
      // Tab cycles within the dialog rather than escaping to the page behind
      // it, which a screen-reader user would otherwise have no way to leave.
      const items = [...ref.current.querySelectorAll(FOCUSABLE)];
      if (items.length === 0) { event.preventDefault(); return; }
      const first = items[0];
      const last = items[items.length - 1];
      const active = document.activeElement;
      if (event.shiftKey && (active === first || active === ref.current)) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && active === last) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('keydown', onKey);
      // Focus returns to whatever opened the dialog.
      if (previous instanceof HTMLElement) previous.focus();
    };
  }, []);

  return (
    <div className="scrim">
      <div className={`modal ${className}`.trim()} role="dialog" aria-modal="true"
           aria-labelledby={titleId}
           tabIndex={-1} ref={ref}>
        <h2 className="modal__title" id={titleId}>{title}</h2>
        {children}
        <div className="modal__actions">{actions}</div>
      </div>
    </div>
  );
}
