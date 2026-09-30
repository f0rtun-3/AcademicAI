// The "Needs attention" projection.
//
// These tests exist to hold the band to being a PROJECTION: a pure function of
// the authoritative records, with the approved window, cap and ordering.

import { describe, expect, it } from 'vitest';
import { needsAttention, ATTENTION_MAX_ITEMS, ATTENTION_WINDOW_DAYS }
  from '../src/lib/attention.js';

const TODAY = '2026-09-15';

function event(id, overrides = {}) {
  return {
    id, title: `Event ${id}`, course_code: 'COS202', event_type: 'ASSIGNMENT',
    event_date: '2026-09-18', event_time: null, venue: null, priority: 'NORMAL',
    status: 'SCHEDULED', completed: false, ...overrides,
  };
}

function change(id, entityId, type, overrides = {}) {
  return {
    id, entity_type: 'academic_event', entity_id: entityId, change_type: type,
    old_value: null, new_value: null, created_at: '2026-09-14', ...overrides,
  };
}

describe('needs attention', () => {
  it('uses the approved window and cap', () => {
    expect(ATTENTION_WINDOW_DAYS).toBe(7);
    expect(ATTENTION_MAX_ITEMS).toBe(5);
  });

  it('is empty when nothing changed, so the band can be omitted', () => {
    const result = needsAttention({ events: [event(1)], changes: [], today: TODAY });
    expect(result.items).toEqual([]);
    expect(result.more).toBe(0);
  });

  it('ignores creations — a new record is not a change to re-read', () => {
    const result = needsAttention({
      events: [event(1)],
      changes: [change(10, 1, 'EVENT_CREATED')],
      today: TODAY,
    });
    expect(result.items).toEqual([]);
  });

  it('reads the chip from change history, never from the event', () => {
    const result = needsAttention({
      events: [event(1)],
      changes: [change(10, 1, 'DEADLINE_CHANGED',
                       { old_value: { event_date: '2026-09-11' },
                         new_value: { event_date: '2026-09-18' } })],
      today: TODAY,
    });
    expect(result.items).toHaveLength(1);
    expect(result.items[0].state).toBe('DEADLINE_MOVED');
    expect(result.items[0].detail).toEqual({
      field: 'event_date', from: '2026-09-11', to: '2026-09-18',
    });
  });

  it('drops anything beyond the 7-day window', () => {
    const result = needsAttention({
      events: [event(1, { event_date: '2026-09-30' })],
      changes: [change(10, 1, 'VENUE_CHANGED')],
      today: TODAY,
    });
    expect(result.items).toEqual([]);
  });

  it('keeps only the most recent change per event', () => {
    const result = needsAttention({
      events: [event(1)],
      // Newest first, as the backend returns them.
      changes: [change(12, 1, 'VENUE_CHANGED'), change(10, 1, 'DEADLINE_CHANGED')],
      today: TODAY,
    });
    expect(result.items).toHaveLength(1);
    expect(result.items[0].state).toBe('VENUE_CHANGED');
  });

  it('sorts overdue, then today, then cancellations, then reschedules', () => {
    const result = needsAttention({
      events: [
        event(1, { event_date: '2026-09-20' }),                       // reschedule
        event(2, { event_date: '2026-09-15' }),                       // today
        event(3, { event_date: '2026-09-12' }),                       // overdue
        event(4, { event_date: '2026-09-19', status: 'CANCELLED' }),  // cancelled
      ],
      changes: [
        change(10, 1, 'DEADLINE_CHANGED'),
        change(11, 2, 'VENUE_CHANGED'),
        change(12, 3, 'VENUE_CHANGED'),
        change(13, 4, 'EVENT_CANCELLED'),
      ],
      today: TODAY,
    });
    expect(result.items.map((i) => i.eventId)).toEqual([3, 2, 4, 1]);
  });

  it('does not call a completed past event overdue', () => {
    const result = needsAttention({
      events: [event(1, { event_date: '2026-09-12', completed: true })],
      changes: [change(10, 1, 'VENUE_CHANGED')],
      today: TODAY,
    });
    // Still present — completion never silences a change the student has not
    // seen — but not ranked as urgent.
    expect(result.items).toHaveLength(1);
    expect(result.items[0].tier).not.toBe(0);
  });

  it('caps at five and reports how many were held back', () => {
    const events = [];
    const changes = [];
    for (let i = 1; i <= 8; i += 1) {
      events.push(event(i, { event_date: '2026-09-18' }));
      changes.push(change(100 + i, i, 'VENUE_CHANGED'));
    }
    const result = needsAttention({ events, changes, today: TODAY });
    expect(result.items).toHaveLength(5);
    expect(result.more).toBe(3);
  });

  it('never displaces something urgent with something routine', () => {
    const events = [event(99, { event_date: '2026-09-12' })];
    const changes = [change(999, 99, 'VENUE_CHANGED')];
    for (let i = 1; i <= 8; i += 1) {
      events.push(event(i, { event_date: '2026-09-18' }));
      changes.push(change(100 + i, i, 'VENUE_CHANGED'));
    }
    const result = needsAttention({ events, changes, today: TODAY });
    expect(result.items[0].eventId).toBe(99);       // overdue survives the cap
  });

  it('ignores changes to entities that are not academic events', () => {
    const result = needsAttention({
      events: [event(1)],
      changes: [{ id: 10, entity_type: 'course', entity_id: 1,
                  change_type: 'COURSE_REMOVED' }],
      today: TODAY,
    });
    expect(result.items).toEqual([]);
  });

  it('is pure: calling it twice with the same input gives the same answer', () => {
    const input = {
      events: [event(1)], changes: [change(10, 1, 'VENUE_CHANGED')], today: TODAY,
    };
    expect(needsAttention(input)).toEqual(needsAttention(input));
  });
});
