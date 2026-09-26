// The "Needs attention" projection (S5 band 1, correction C·7).
//
// THIS HOLDS NOTHING. It is a pure function over the authoritative records the
// backend already returned - academic_events for current state, change_history
// for what changed - recomputed on every render.
//
//   * No table, no cache, no flag written back to an event, no localStorage,
//     no client-side list that outlives a fetch.
//   * No dismissal and no read state. An item leaves this band when the record
//     or the window says so, never because it was clicked.
//   * Event detail wins any disagreement; a refetch is the fix, never a local
//     patch.
//   * DEADLINE MOVED / VENUE CHANGED / RESCHEDULED are read from change
//     history per render. They are not persisted and not inferred from
//     anything the client remembers about a previous fetch.

export const ATTENTION_WINDOW_DAYS = 7;
export const ATTENTION_MAX_ITEMS = 5;

// Selection order, applied BEFORE the cap so nothing urgent is displaced by
// something routine.
const TIER = { OVERDUE: 0, TODAY: 1, CANCELLED: 2, RESCHEDULED: 3, OTHER: 4 };

// Within a tier, after date: exams outrank assignments.
const TYPE_RANK = {
  EXAM: 0, TEST: 1, QUIZ: 2, PRESENTATION: 3, PROJECT: 4, ASSIGNMENT: 5,
};
const PRIORITY_RANK = { HIGH: 0, NORMAL: 1, LOW: 2 };

const EVENT_CHANGE_TYPES = new Set([
  'DEADLINE_CHANGED', 'VENUE_CHANGED', 'TIME_CHANGED', 'EVENT_UPDATED', 'EVENT_CANCELLED',
]);

function addDays(iso, days) {
  const date = new Date(`${iso}T00:00:00`);
  date.setDate(date.getDate() + days);
  return date.toISOString().slice(0, 10);
}

function firstChangedField(change) {
  const { old_value: before, new_value: after } = change;
  if (!after || typeof after !== 'object') return null;
  const key = Object.keys(after)[0];
  if (!key) return null;
  return {
    field: key,
    from: (before && typeof before === 'object' ? before[key] : null) ?? null,
    to: after[key] ?? null,
  };
}

// The chip a change earns. Derived per render, never stored.
function describe(change, event) {
  switch (change.change_type) {
    case 'EVENT_CANCELLED':
      return { state: 'CANCELLED', tier: TIER.CANCELLED };
    case 'DEADLINE_CHANGED':
      return { state: 'DEADLINE_MOVED', tier: TIER.RESCHEDULED };
    case 'VENUE_CHANGED':
      return { state: 'VENUE_CHANGED', tier: TIER.OTHER };
    case 'TIME_CHANGED':
      return { state: 'CHANGED', tier: TIER.OTHER };
    default:
      return {
        state: event?.status === 'RESCHEDULED' ? 'RESCHEDULED' : 'CHANGED',
        tier: event?.status === 'RESCHEDULED' ? TIER.RESCHEDULED : TIER.OTHER,
      };
  }
}

/**
 * @param events  academic events as the backend returned them (any status)
 * @param changes change-history rows, newest first
 * @returns { items, more } - at most `cap` items, plus how many were capped
 */
export function needsAttention({
  events = [],
  changes = [],
  today = new Date().toISOString().slice(0, 10),
  windowDays = ATTENTION_WINDOW_DAYS,
  cap = ATTENTION_MAX_ITEMS,
} = {}) {
  const horizon = addDays(today, windowDays);
  const byId = new Map(events.map((event) => [event.id, event]));

  // One entry per event: the most recent change wins. `changes` arrives newest
  // first, so the first sighting is the latest.
  const seen = new Map();
  for (const change of changes) {
    if (change.entity_type !== 'academic_event') continue;
    if (!EVENT_CHANGE_TYPES.has(change.change_type)) continue;
    if (seen.has(change.entity_id)) continue;
    seen.set(change.entity_id, change);
  }

  const items = [];
  for (const [eventId, change] of seen) {
    const event = byId.get(eventId);
    const { state, tier: baseTier } = describe(change, event);
    const date = event?.event_date ?? null;

    // The window is on the EVENT, not on when the change happened: a student
    // needs to know about next week's moved deadline, not last term's.
    if (state !== 'CANCELLED') {
      if (!date) continue;
      if (date > horizon) continue;
    } else if (date && date > horizon) {
      continue;
    }

    // A cancelled or personally completed event is never "overdue".
    let tier = baseTier;
    if (state !== 'CANCELLED' && date) {
      if (date < today && !event?.completed) tier = TIER.OVERDUE;
      else if (date === today) tier = TIER.TODAY;
    }

    items.push({
      key: `${eventId}:${change.id}`,
      eventId,
      event: event ?? null,
      change,
      state,
      tier,
      detail: firstChangedField(change),
      date,
    });
  }

  items.sort((a, b) => (
    a.tier - b.tier
    || String(a.date ?? '9999').localeCompare(String(b.date ?? '9999'))
    || (TYPE_RANK[a.event?.event_type] ?? 9) - (TYPE_RANK[b.event?.event_type] ?? 9)
    || (PRIORITY_RANK[a.event?.priority] ?? 9) - (PRIORITY_RANK[b.event?.priority] ?? 9)
    || (b.change.id ?? 0) - (a.change.id ?? 0)
  ));

  return { items: items.slice(0, cap), more: Math.max(0, items.length - cap) };
}
