// The vocabulary layer: canonical values in, student words out.
//
// These pin the one rule the layer exists for - no stored token, field name,
// id, version, state transition or ISO date ever reaches the interface - and
// the wording decisions the pages rely on.

import { afterEach, describe, expect, it } from 'vitest';
import {
  EVENT_TYPES, confidenceWords, dayShort, describeChange, describeFieldChanges,
  eventTypeLabel, eventTypeNoun, isRoutineStatus, isStudentFacingChange,
  notificationKindLabel, notificationViewLabel, spokenDay, statusLabel, voteWord,
} from '../src/lib/vocabulary.js';
import {
  academicClockTime, academicDateOf, academicToday, instantToLocal, isInstant, reminderLocal,
  setAcademicTimeZone,
} from '../src/lib/academicTime.js';
import { todayISO, whenParts } from '../src/components/ui.jsx';

// Anything matching this in a student-facing string is a leak.
const LEAK = /[A-Z]{2,}_[A-Z]|_[a-z]+_|\b(SCHEDULED|CANCELLED|PENDING|ACTIVE|NORMAL|CREATE)\b|→|->|event_type|course_id|\bversion\b|\d{4}-\d{2}-\d{2}/;

const CHANGE_TYPES = [
  'EVENT_CREATED', 'DEADLINE_CHANGED', 'VENUE_CHANGED', 'TIME_CHANGED', 'EVENT_UPDATED',
  'EVENT_CANCELLED', 'MATERIAL_ATTACHED', 'MATERIAL_REMOVED', 'ANNOUNCEMENT_PUBLISHED',
  'ANNOUNCEMENT_UPDATED', 'ANNOUNCEMENT_WITHDRAWN', 'COURSE_CREATED', 'COURSE_UPDATED',
  'COURSE_REMOVED', 'TIMETABLE_CREATED', 'TIMETABLE_UPDATED', 'TIMETABLE_DAY_CHANGED',
  'TIMETABLE_CANCELLED', 'CALENDAR_UPLOADED', 'SESSION_ARCHIVED', 'NOMINATION_OPENED',
  'NOMINATION_PASSED', 'NOMINATION_FAILED', 'REMOVAL_OPENED', 'REMOVAL_PASSED',
  'REMOVAL_FAILED', 'SOME_FUTURE_THING',
];

function change(type, extra = {}) {
  return {
    id: 1, entity_type: 'academic_event', entity_id: 4, change_type: type,
    old_value: { status: 'SCHEDULED', event_date: '2026-09-15', venue: 'B007',
                 event_time: '10:00', course_id: 3, priority: 'NORMAL' },
    new_value: { status: 'CANCELLED', event_date: '2026-09-18', venue: 'B107',
                 event_time: '12:00', course_id: 15, priority: 'NORMAL', version: 3 },
    created_at: '2026-09-25T10:00:00+00:00', ...extra,
  };
}

describe('event types', () => {
  it('reads every type as a word, and anything unknown as Other', () => {
    expect(EVENT_TYPES.map(eventTypeLabel)).toEqual([
      'Assignment', 'Project', 'Quiz', 'Test', 'Presentation', 'Exam', 'Class', 'Other']);
    expect(eventTypeLabel('SOMETHING_NEW')).toBe('Other');
    expect(eventTypeNoun('ASSIGNMENT')).toBe('assignment');
    expect(eventTypeNoun('OTHER')).toBe('event');
  });
});

describe('status labels', () => {
  it('are sentence case, and never the stored token', () => {
    expect(statusLabel('SCHEDULED')).toBe('Scheduled');
    expect(statusLabel('CANCELLED')).toBe('Cancelled');
    expect(statusLabel('COMPLETED')).toBe('Completed');
    expect(statusLabel('DEADLINE_MOVED')).toBe('Deadline moved');
    expect(statusLabel('SOME_FUTURE_STATE')).toBe('Some future state');
  });

  it('read the same token by what it is about', () => {
    expect(statusLabel('PENDING', 'reminder')).toBe('Scheduled');
    expect(statusLabel('PENDING', 'community')).toBe('No rep yet');
    expect(statusLabel('CREATE', 'proposal')).toBe('New record');
    expect(statusLabel('FAILED', 'ballot')).toBe('Did not pass');
  });

  it('treat the normal state of a record as routine, and exceptions as not', () => {
    for (const routine of ['SCHEDULED', 'ACTIVE', 'PUBLISHED']) {
      expect(isRoutineStatus(routine)).toBe(true);
    }
    expect(isRoutineStatus('PENDING', 'reminder')).toBe(true);
    expect(isRoutineStatus('CANCELLED')).toBe(false);
    expect(isRoutineStatus('DEADLINE_MOVED')).toBe(false);
    expect(isRoutineStatus('SENT', 'reminder')).toBe(false);
  });
});

describe('change history in words', () => {
  it('never lets a raw value through, for any change type or perspective', () => {
    for (const type of CHANGE_TYPES) {
      for (const perspective of ['community', 'event']) {
        const { sentence, details } = describeChange(change(type), { perspective });
        for (const text of [sentence, ...details]) {
          expect(text, `${type} (${perspective})`).not.toMatch(LEAK);
          expect(text.length).toBeGreaterThan(0);
        }
      }
    }
  });

  it('says a cancellation happened, not which states it moved between', () => {
    expect(describeChange(change('EVENT_CANCELLED'), {
      perspective: 'event', subject: { event_type: 'QUIZ' },
    }).sentence).toBe('The quiz was cancelled.');
  });

  it('names its subject in a community feed', () => {
    const subject = { title: 'Programming II Quiz', course_code: 'COS204', event_type: 'QUIZ' };
    expect(describeChange(change('DEADLINE_CHANGED', { subject })).sentence)
      .toBe('The date for Programming II Quiz (COS204) was updated.');
    expect(describeChange(change('VENUE_CHANGED', { subject })).sentence)
      .toBe('The venue for Programming II Quiz (COS204) was changed.');
    expect(describeChange(change('EVENT_CANCELLED', { subject })).sentence)
      .toBe('Programming II Quiz (COS204) was cancelled.');
    expect(describeChange({ change_type: 'EVENT_CREATED', new_value:
      { title: 'Data Structures Assignment 2', event_type: 'ASSIGNMENT' } }).sentence)
      .toBe('A new assignment was added: Data Structures Assignment 2.');
  });

  it('uses "deadline" for work that is handed in, "date" otherwise', () => {
    const due = describeChange(change('DEADLINE_CHANGED'),
      { perspective: 'event', subject: { event_type: 'ASSIGNMENT' } });
    expect(due.sentence).toBe('The deadline was updated.');
    expect(due.details).toEqual(['Deadline moved from Tuesday 15 September to Friday 18 September.']);
    const onDate = describeChange(change('DEADLINE_CHANGED'),
      { perspective: 'event', subject: { event_type: 'EXAM' } });
    expect(onDate.sentence).toBe('The date was updated.');
  });

  it('keeps venue names as they were typed', () => {
    const { details } = describeChange(change('VENUE_CHANGED'), { perspective: 'event' });
    expect(details).toEqual(['Venue moved from B007 to B107.']);
  });

  it('turns an update into readable lines and drops what a student has no use for', () => {
    const lines = describeFieldChanges(
      { course_id: 3, priority: 'NORMAL', description: null },
      { course_id: 15, priority: 'HIGH', description: 'Read chapter 4', version: 9 },
      'ASSIGNMENT');
    expect(lines).toEqual([
      'Moved to a different course.', 'Marked as high priority.', 'Instructions were added.']);
  });

  it('leaves classmates\' membership activity out of the feed', () => {
    expect(isStudentFacingChange({ entity_type: 'community_member',
                                   change_type: 'MEMBERSHIP_APPROVED' })).toBe(false);
    expect(isStudentFacingChange(change('EVENT_CREATED'))).toBe(true);
  });

  it('never prints an unmapped change type', () => {
    expect(describeChange(change('SOME_FUTURE_THING')).sentence)
      .toBe("An update was made to your community's records.");
  });
});

describe('dates and small words', () => {
  it('speaks a date day-first, without the year', () => {
    expect(spokenDay('2026-09-27')).toBe('Sunday 27 September');
    expect(spokenDay(null)).toBeNull();
    expect(dayShort('MONDAY')).toBe('Mon');
  });

  it('labels notification kinds without echoing their token', () => {
    expect(notificationKindLabel('EVENT_CANCELLED')).toBe('Cancelled');
    expect(notificationKindLabel('PERSONAL_REMINDER')).toBe('Reminder');
    expect(notificationKindLabel('SOMETHING_ELSE')).toBeNull();
    expect(notificationViewLabel('EVENT_REMINDER')).toBe('View reminder');
    expect(notificationViewLabel('EVENT_CHANGED')).toBe('View event');
  });

  it('turns confidence and votes into words', () => {
    expect(confidenceWords(0.87)).toBe('AcademicAI is confident about this reading.');
    expect(confidenceWords(0.3)).toMatch(/unsure/);
    expect(voteWord('YES')).toBe('yes');
  });
});

// ── The academic clock ────────────────────────────────────────────────────
//
// AcademicAI times are read on the UNIVERSITY'S clock (the session's IANA
// zone), never on the device's. The device is set to a different zone in each
// test below to prove it cannot move anything.

describe('the academic clock', () => {
  const original = process.env.TZ;
  afterEach(() => {
    process.env.TZ = original;
    setAcademicTimeZone(null);
  });

  it('reads an instant on the university clock, not the device clock', () => {
    process.env.TZ = 'UTC';
    setAcademicTimeZone('Africa/Lagos');
    expect(instantToLocal('2026-09-27T07:00:00+00:00')).toBe('2026-09-27T08:00');
    expect(academicClockTime('2026-09-27T07:00:00+00:00')).toBe('08:00');
  });

  it('puts 00:30 Lagos on the Lagos day, though it is still yesterday in UTC', () => {
    process.env.TZ = 'UTC';
    setAcademicTimeZone('Africa/Lagos');
    expect(academicDateOf('2026-09-26T23:30:00+00:00')).toBe('2026-09-27');
    const when = whenParts('2026-09-26T23:30:00+00:00', new Date('2026-09-20T00:00:00'));
    expect(when).toEqual({ top: 'Sun', bottom: '27 Sep' });
  });

  it('follows the university zone\'s DST, not a fixed offset', () => {
    process.env.TZ = 'Africa/Lagos';
    setAcademicTimeZone('Europe/London');
    expect(instantToLocal('2026-10-24T07:00:00+00:00')).toBe('2026-10-24T08:00');   // BST
    expect(instantToLocal('2026-10-26T08:00:00+00:00')).toBe('2026-10-26T08:00');   // GMT
  });

  it('takes today from the university clock', () => {
    process.env.TZ = 'UTC';
    setAcademicTimeZone('Africa/Lagos');
    const utcStillYesterday = new Date('2026-09-26T23:30:00Z');
    expect(academicToday(utcStillYesterday)).toBe('2026-09-27');
    expect(todayISO(utcStillYesterday)).toBe('2026-09-27');
  });

  it('leaves academic wall-clock values exactly as written', () => {
    process.env.TZ = 'America/New_York';
    setAcademicTimeZone('Africa/Lagos');
    expect(isInstant('2026-09-27T08:00')).toBe(false);
    expect(academicDateOf('2026-09-27T00:30')).toBe('2026-09-27');
    expect(academicClockTime('2026-09-27T00:30')).toBe('00:30');
    expect(academicDateOf('2026-09-27')).toBe('2026-09-27');
  });

  it('prefers the API\'s remind_at_local and falls back to reading the instant', () => {
    process.env.TZ = 'UTC';
    setAcademicTimeZone('Africa/Lagos');
    expect(reminderLocal({ remind_at: 'ignored+00:00', remind_at_local: '2026-09-27T00:30' }))
      .toBe('2026-09-27T00:30');
    expect(reminderLocal({ remind_at: '2026-09-26T23:30:00+00:00' })).toBe('2026-09-27T00:30');
  });

  it('refuses a zone the browser does not know, falling back to the device', () => {
    process.env.TZ = 'UTC';
    setAcademicTimeZone('Mars/Olympus_Mons');
    expect(instantToLocal('2026-09-27T07:00:00+00:00')).toBe('2026-09-27T07:00');
  });
});
