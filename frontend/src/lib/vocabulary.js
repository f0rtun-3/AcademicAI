// The student-facing vocabulary.
//
// The backend speaks in canonical values: SCHEDULED, DEADLINE_CHANGED,
// event_date, PENDING_APPROVAL. Those are right for storage and wrong for a
// student, who should never have to learn a state machine to read their own
// timetable. This module is the ONE place that turns a canonical value into
// the words the interface shows. Components ask it for a label or a sentence;
// they never lowercase, split or map a token themselves.
//
// Three rules hold it together:
//
//   1. Reword, never invent. Every sentence is built only from what the record
//      holds. A change row with no subject is described without one.
//   2. No raw value escapes. An unmapped token falls back to neutral words
//      ("An update was made…"), not to its own name.
//   3. Routine is quiet. "Scheduled", "Active" and "Published" are the normal
//      state of things, so lists do not badge them (see isRoutineStatus); a
//      badge is spent on what a student needs to notice.

/* ── Dates ─────────────────────────────────────────────────────────────── */

const WEEKDAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday',
                  'Saturday'];
const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July',
                'August', 'September', 'October', 'November', 'December'];

function parseDay(value) {
  if (!value) return null;
  const date = new Date(`${String(value).slice(0, 10)}T00:00:00`);
  return Number.isNaN(date.getTime()) ? null : date;
}

// "Friday 18 September" - how a person says a date inside a sentence. Day
// before month whatever the runtime locale, like every date in this product.
export function spokenDay(value) {
  const date = parseDay(value);
  if (!date) return null;
  return `${WEEKDAYS[date.getDay()]} ${date.getDate()} ${MONTHS[date.getMonth()]}`;
}

// "MONDAY" -> "Mon" / "Monday", for the timetable's day column.
export function dayShort(dayOfWeek) {
  const word = dayLong(dayOfWeek);
  return word ? word.slice(0, 3) : '';
}

export function dayLong(dayOfWeek) {
  if (!dayOfWeek) return '';
  const lower = String(dayOfWeek).toLowerCase();
  return lower.charAt(0).toUpperCase() + lower.slice(1);
}

/* ── Event types ───────────────────────────────────────────────────────── */

export const EVENT_TYPES = ['ASSIGNMENT', 'PROJECT', 'QUIZ', 'TEST', 'PRESENTATION',
                            'EXAM', 'CLASS', 'OTHER'];

const TYPE_LABEL = {
  ASSIGNMENT: 'Assignment', PROJECT: 'Project', QUIZ: 'Quiz', TEST: 'Test',
  EXAM: 'Exam', PRESENTATION: 'Presentation', CLASS: 'Class', OTHER: 'Other',
};

const TYPE_PLURAL = {
  ASSIGNMENT: 'Assignments', PROJECT: 'Projects', QUIZ: 'Quizzes', TEST: 'Tests',
  EXAM: 'Exams', PRESENTATION: 'Presentations', CLASS: 'Classes', OTHER: 'Other',
};

// Work that is handed in has a deadline; everything else happens on a date.
const DUE_TYPES = new Set(['ASSIGNMENT', 'PROJECT']);

export function eventTypeLabel(type) {
  return TYPE_LABEL[type] ?? 'Other';
}

export function eventTypePlural(type) {
  return TYPE_PLURAL[type] ?? 'Other';
}

// The noun inside a sentence: "A new assignment was added."
export function eventTypeNoun(type) {
  if (!type || type === 'OTHER' || !TYPE_LABEL[type]) return 'event';
  return TYPE_LABEL[type].toLowerCase();
}

export function isDueType(type) {
  return DUE_TYPES.has(type);
}

// The label for an event's date field: an assignment is due, an exam is on.
export function dateLabel(type) {
  return isDueType(type) ? 'Due' : 'Date';
}

/* ── Status labels ─────────────────────────────────────────────────────── */

// Sentence case, and the words a student would use. Keys are the canonical
// values the backend stores.
const STATUS = {
  SCHEDULED: 'Scheduled',
  CANCELLED: 'Cancelled',
  COMPLETED: 'Completed',
  RESCHEDULED: 'Rescheduled',
  ARCHIVED: 'Archived',
  DEADLINE_MOVED: 'Deadline moved',
  VENUE_CHANGED: 'Venue changed',
  TIME_CHANGED: 'Time changed',
  CHANGED: 'Changed',
  UPDATE: 'Updated',
  PUBLISHED: 'Published',
  WITHDRAWN: 'Withdrawn',
  ACTIVE: 'Active',
  PENDING: 'Pending',
  // NEEDS_REVIEW must never imply that anybody is going to look at it: there
  // is no review queue (C·6).
  NEEDS_REVIEW: 'Not confirmed',
  PENDING_APPROVAL: 'Awaiting a rep',
  CLARIFICATION: 'Needs clarification',
  VERIFIED: 'Verified',
  UNVERIFIED: 'Not verified',
  VERIFIED_REP: 'Course rep',
  STUDENT: 'Student',
  ENROLLED: 'Enrolled',
  DROPPED: 'Dropped',
  OPEN: 'Voting open',
  PASSED: 'Passed',
  FAILED: 'Did not pass',
  COOLDOWN: 'Cooling off',
  TRANSFER_PENDING: 'Transfer pending',
  SENT: 'Sent',
  ENDED: 'Ended',
  REMOVED: 'Removed',
  REJECTED: 'Rejected',
  DUPLICATE: 'Already recorded',
  CREATE: 'New record',
  CANCEL: 'Cancellation',
};

// The same token can mean different things on different records. A PENDING
// reminder is queued; a PENDING community has no rep yet. The distinction
// lives here, keyed by what the status is about.
const IN_CONTEXT = {
  reminder: { PENDING: 'Scheduled', SENT: 'Sent', CANCELLED: 'Cancelled' },
  // PENDING for a community is "no rep has been elected yet", not "waiting
  // for approval" - an unlabelled PENDING read as a statement about the reader.
  community: { PENDING: 'No rep yet', ACTIVE: 'Active', ARCHIVED: 'Archived' },
  proposal: {
    CREATE: 'New record',
    UPDATE: 'Change to an existing record',
    DUPLICATE: 'Already recorded',
    CLARIFICATION: 'Needs clarification',
    CANCEL: 'Cancellation',
  },
  ballot: { OPEN: 'Voting open', PASSED: 'Passed', FAILED: 'Did not pass' },
  membership: { ACTIVE: 'Active member', PENDING_APPROVAL: 'Awaiting a rep' },
};

function sentenceCase(token) {
  const words = String(token).replace(/_/g, ' ').toLowerCase().trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export function statusLabel(value, context) {
  if (!value) return '';
  return IN_CONTEXT[context]?.[value] ?? STATUS[value] ?? sentenceCase(value);
}

// The normal state of a record. A list does not badge these: twenty
// "Scheduled" chips say nothing and bury the one "Cancelled".
const ROUTINE = {
  default: new Set(['SCHEDULED', 'ACTIVE', 'PUBLISHED', 'ENROLLED']),
  reminder: new Set(['PENDING']),
  rep: new Set(['VERIFIED_REP']),
};

export function isRoutineStatus(value, context) {
  return (ROUTINE[context] ?? ROUTINE.default).has(value);
}

// Tone per canonical value. Values that recur on different records share a
// tone because they share a meaning class, not because they are one state.
export const TONE = {
  VERIFIED: 'pos', ACTIVE: 'pos', PASSED: 'pos', PUBLISHED: 'pos',
  VERIFIED_REP: 'pos', ENROLLED: 'pos',
  SCHEDULED: '', STUDENT: '', OPEN: '', UNVERIFIED: '',
  CHANGED: 'info', RESCHEDULED: 'info', DEADLINE_MOVED: 'info',
  VENUE_CHANGED: 'info', TIME_CHANGED: 'info', UPDATE: 'info',
  PENDING: 'warn', PENDING_APPROVAL: 'warn', NEEDS_REVIEW: 'warn',
  CLARIFICATION: 'warn', COOLDOWN: 'warn', TRANSFER_PENDING: 'warn',
  CANCELLED: 'crit', FAILED: 'crit', REJECTED: 'crit', CANCEL: 'crit',
  // Terminal and neutral: no dot.
  ARCHIVED: 'none', DUPLICATE: 'none', SENT: 'none', ENDED: 'none',
  REMOVED: 'none', DROPPED: 'none', WITHDRAWN: 'none', COMPLETED: 'none',
};

/* ── Priority ──────────────────────────────────────────────────────────── */

export const PRIORITIES = ['LOW', 'NORMAL', 'HIGH'];

export function priorityLabel(value) {
  return { LOW: 'Low', NORMAL: 'Normal', HIGH: 'High' }[value] ?? 'Normal';
}

/* ── Change history ────────────────────────────────────────────────────── */

// Membership rows are administrative: a classmate being approved, joining or
// leaving is not academic information and is not someone else's to read.
export function isStudentFacingChange(change) {
  return Boolean(change) && change.entity_type !== 'community_member';
}

function objectOf(value) {
  return value && typeof value === 'object' ? value : {};
}

// "Programming II Quiz (COS202)". The subject is what the change query joined
// in; a creation's own snapshot is the fallback. Returns null when nothing
// names the record, and the sentence is then written without a name.
function subjectOf(change, override) {
  const subject = { ...objectOf(change?.subject), ...objectOf(override) };
  const snapshot = objectOf(change?.new_value);
  const title = subject.title ?? snapshot.title ?? null;
  const course = subject.course_code ?? null;
  const type = subject.event_type ?? snapshot.event_type ?? null;
  const name = title ? (course ? `${title} (${course})` : title) : null;
  return { title, course, type, name };
}

function when(date, time) {
  const day = spokenDay(date);
  if (!day) return null;
  return time ? `${day} at ${time}` : day;
}

// "Venue moved from B007 to B107." with the field named, for an update that
// touched several fields at once.
function fieldMoved(label, from, to, speak = (v) => v) {
  const a = from ? speak(from) : null;
  const b = to ? speak(to) : null;
  if (a && b) return `${label} moved from ${a} to ${b}.`;
  if (b) return `${label} is now ${b}.`;
  return `${label} was removed.`;
}

// The per-field detail of an update, in words. Fields a student has no use
// for (ids, versions, internal flags) produce nothing rather than a raw key.
function fieldDetails(change, type) {
  const before = objectOf(change.old_value);
  const after = objectOf(change.new_value);
  const lines = [];
  for (const key of Object.keys(after)) {
    const from = before[key] ?? null;
    const to = after[key] ?? null;
    if (from === to) continue;
    if (key === 'event_date') {
      lines.push(fieldMoved(isDueType(type) ? 'Deadline' : 'Date', from, to, spokenDay));
    } else if (key === 'event_time') lines.push(fieldMoved('Time', from, to));
    else if (key === 'venue') lines.push(fieldMoved('Venue', from, to));
    else if (key === 'title' && to) {
      lines.push(from ? `Renamed from “${from}” to “${to}”.` : `Titled “${to}”.`);
    } else if (key === 'priority' && to) {
      lines.push(to === 'HIGH' ? 'Marked as high priority.'
        : `Priority set to ${priorityLabel(to).toLowerCase()}.`);
    } else if (key === 'description') {
      lines.push(!to ? 'The instructions were removed.'
        : from ? 'The instructions were updated.' : 'Instructions were added.');
    } else if (key === 'course_id') lines.push('Moved to a different course.');
    else if (key === 'event_type' && to) lines.push(`Now a ${eventTypeNoun(to)}.`);
  }
  return lines;
}

// The fields a proposed change would alter, one line each, for the review
// shown before a rep publishes. Same words as the history uses afterwards.
export function describeFieldChanges(before, after, type) {
  return fieldDetails({ old_value: before, new_value: after }, type);
}

/**
 * One change, in words a student reads.
 *
 * @param change      a change-history row as the API returns it
 * @param options.perspective
 *   'community' (default) - a feed of changes across the community, so the
 *                           sentence names its subject;
 *   'event'               - the history of ONE event, whose name is already the
 *                           page heading, so the sentence does not repeat it.
 * @param options.subject optional { title, course_code, event_type } override
 * @returns { sentence, details } where details are short follow-up lines.
 */
export function describeChange(change, { perspective = 'community', subject: override } = {}) {
  const kind = change?.change_type ?? '';
  const subj = subjectOf(change, override);
  const noun = eventTypeNoun(subj.type);
  const onEvent = perspective === 'event';
  const named = subj.name;
  const snapshot = objectOf(change?.new_value);
  const before = objectOf(change?.old_value);
  let details = [];

  const sentence = (() => {
    switch (kind) {
      case 'EVENT_CREATED': {
        const at = when(snapshot.event_date, snapshot.event_time);
        if (at) details.push(`${isDueType(subj.type) ? 'Due' : 'On'} ${at}.`);
        if (onEvent && snapshot.venue) details.push(`In ${snapshot.venue}.`);
        if (onEvent || !named) return `A new ${noun} was added.`;
        return `A new ${noun} was added: ${named}.`;
      }
      case 'DEADLINE_CHANGED': {
        const label = isDueType(subj.type) ? 'deadline' : 'date';
        details = [fieldMoved(isDueType(subj.type) ? 'Deadline' : 'Date',
                              before.event_date, snapshot.event_date, spokenDay)];
        if (onEvent || !named) return `The ${label} was updated.`;
        return `The ${label} for ${named} was updated.`;
      }
      case 'VENUE_CHANGED':
        details = [fieldMoved('Venue', before.venue, snapshot.venue)];
        if (onEvent || !named) return 'The venue was changed.';
        return `The venue for ${named} was changed.`;
      case 'TIME_CHANGED':
        details = [fieldMoved('Time', before.event_time, snapshot.event_time)];
        if (onEvent || !named) return 'The time was changed.';
        return `The time for ${named} was changed.`;
      case 'EVENT_UPDATED':
        details = fieldDetails(change, subj.type);
        if (onEvent || !named) return 'The details were updated.';
        return `${named} was updated.`;
      case 'EVENT_CANCELLED':
        if (onEvent || !named) return `The ${noun} was cancelled.`;
        return `${named} was cancelled.`;
      case 'MATERIAL_ATTACHED': {
        const file = typeof change.new_value === 'string' ? change.new_value : null;
        if (file) details.push(file);
        if (onEvent || !named) return 'Supporting material was added.';
        return `Supporting material was added to ${named}.`;
      }
      case 'MATERIAL_REMOVED':
        if (onEvent || !named) return 'Supporting material was removed.';
        return `Supporting material was removed from ${named}.`;
      case 'ANNOUNCEMENT_PUBLISHED':
        return subj.title ? `A new announcement was posted: ${subj.title}.`
          : 'A new announcement was posted.';
      case 'ANNOUNCEMENT_UPDATED':
        return subj.title ? `An announcement was edited: ${subj.title}.` : 'An announcement was edited.';
      case 'ANNOUNCEMENT_WITHDRAWN':
        return 'An announcement was withdrawn.';
      case 'COURSE_CREATED':
      case 'COURSE_UPDATED':
      case 'COURSE_REMOVED': {
        const code = subj.course ?? snapshot.code ?? before.code ?? null;
        const what = code ?? 'A course';
        if (kind === 'COURSE_CREATED') return `${what} was added to the course list.`;
        if (kind === 'COURSE_UPDATED') return `${what} was updated.`;
        return `${what} was removed from the course list.`;
      }
      case 'TIMETABLE_CREATED':
        return subj.title ? `A class was added to the timetable: ${subj.title}.`
          : 'A class was added to the timetable.';
      case 'TIMETABLE_UPDATED':
      case 'TIMETABLE_DAY_CHANGED':
        return subj.title ? `A class in the timetable was changed: ${subj.title}.`
          : 'A class in the timetable was changed.';
      case 'TIMETABLE_CANCELLED':
        return subj.title ? `A class was removed from the timetable: ${subj.title}.`
          : 'A class was removed from the timetable.';
      case 'CALENDAR_UPLOADED':
        return 'The academic calendar was updated.';
      case 'SESSION_ARCHIVED':
        return 'This academic session has ended.';
      case 'NOMINATION_OPENED':
        return 'A course rep election was opened.';
      case 'NOMINATION_PASSED':
        return 'A new course rep was confirmed.';
      case 'NOMINATION_FAILED':
        return 'A course rep election closed without a result.';
      case 'REMOVAL_OPENED':
        return 'A vote to remove a course rep was opened.';
      case 'REMOVAL_PASSED':
        return 'A course rep was removed after a vote.';
      case 'REMOVAL_FAILED':
        return 'A vote to remove a course rep did not pass.';
      default:
        // An unmapped type never prints its own name.
        return "An update was made to your community's records.";
    }
  })();

  return { sentence, details: details.filter(Boolean) };
}

/* ── Notifications ─────────────────────────────────────────────────────── */

const KIND_LABEL = {
  EVENT_REMINDER: 'Reminder',
  PERSONAL_REMINDER: 'Reminder',
  EVENT_CREATED: 'New',
  EVENT_CHANGED: 'Changed',
  EVENT_CANCELLED: 'Cancelled',
  ANNOUNCEMENT: 'Announcement',
  TIMETABLE: 'Timetable',
  COURSE_REPS: 'Course reps',
};

// A kind we do not know shows no label rather than printing its own token.
export function notificationKindLabel(kind) {
  return KIND_LABEL[kind] ?? null;
}

export function notificationViewLabel(kind) {
  if (kind === 'EVENT_REMINDER' || kind === 'PERSONAL_REMINDER') return 'View reminder';
  if (kind === 'EVENT_CREATED' || kind === 'EVENT_CHANGED' || kind === 'EVENT_CANCELLED') {
    return 'View event';
  }
  if (kind === 'ANNOUNCEMENT') return 'View announcement';
  return 'View';
}

/* ── AI proposals (Add message) ────────────────────────────────────────── */

// How sure the reading is, in words. The number stays in the data; the
// student reads what it means for them.
export function confidenceWords(confidence) {
  if (typeof confidence !== 'number') return null;
  if (confidence >= 0.8) return 'AcademicAI is confident about this reading.';
  if (confidence >= 0.5) return 'AcademicAI is fairly sure about this reading. Check the details.';
  return 'AcademicAI is unsure about this reading. Check every detail before relying on it.';
}

/* ── Ballots ───────────────────────────────────────────────────────────── */

export function voteWord(vote) {
  return { YES: 'yes', NO: 'no' }[vote] ?? String(vote ?? '').toLowerCase();
}
