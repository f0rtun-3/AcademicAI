// Calendar derivations. Pure functions, no React, no fetching.
//
// Everything here is computed from what /api/calendar already returns. It adds
// no data and invents no fields: where the backend has nothing (an event with
// no date, no time, no venue, no course) these functions say so rather than
// filling a gap.
//
// DATES ARE LOCAL, NEVER UTC. `new Date("2026-09-21")` parses as midnight UTC,
// which in Lagos (UTC+1) is still the 21st but in any negative offset is the
// 20th - so every date here is built from explicit local components, the same
// rule todayISO() already follows in ui.jsx.

export const DAY_ORDER = ['MONDAY', 'TUESDAY', 'WEDNESDAY', 'THURSDAY',
                         'FRIDAY', 'SATURDAY', 'SUNDAY'];

const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July',
                'August', 'September', 'October', 'November', 'December'];

/* ── Local-safe date helpers ─────────────────────────────────────────────── */

export function parseISO(value) {
  if (!value) return null;
  const [y, m, d] = String(value).slice(0, 10).split('-').map(Number);
  if (!y || !m || !d) return null;
  const date = new Date(y, m - 1, d);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function toISO(date) {
  const m = String(date.getMonth() + 1).padStart(2, '0');
  const d = String(date.getDate()).padStart(2, '0');
  return `${date.getFullYear()}-${m}-${d}`;
}

export function startOfToday() {
  const now = new Date();
  return new Date(now.getFullYear(), now.getMonth(), now.getDate());
}

export function addMonths(date, n) {
  // Day 1 first, so stepping from the 31st never skips a short month.
  return new Date(date.getFullYear(), date.getMonth() + n, 1);
}

export function addDays(date, n) {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate() + n);
}

// Monday-first, matching DAY_ORDER and the timetable's own week.
export function startOfWeek(date) {
  const day = date.getDay();               // 0 = Sunday
  return addDays(date, day === 0 ? -6 : 1 - day);
}

export function monthLabel(date) {
  return `${MONTHS[date.getMonth()]} ${date.getFullYear()}`;
}

export function sameMonth(a, b) {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth();
}

/* ── Event shaping ───────────────────────────────────────────────────────── */

// Assessment types, used only to answer "is this a deadline?" for the summary.
// Derived from the event_type values the backend already stores; nothing is
// added to the model.
// Work with a deadline, where "Due in 3 days" is the point. A project
// belongs here for the same reason an assignment does.
const ASSESSMENT = new Set(['ASSIGNMENT', 'PROJECT', 'QUIZ', 'TEST', 'EXAM']);

export function isAssessment(event) {
  return ASSESSMENT.has(event.event_type);
}

export function applyFilter(events, type) {
  return type === 'ALL' ? events : events.filter((e) => e.event_type === type);
}

// Events whose date falls inside `anchor`'s month, plus (always) undated ones,
// which would otherwise be invisible in every month. Sorted by date then time,
// with undated last - they have no position on a timeline.
export function eventsInMonth(events, anchor) {
  const dated = [];
  const undated = [];
  for (const event of events) {
    const date = parseISO(event.event_date);
    if (!date) { undated.push(event); continue; }
    if (sameMonth(date, anchor)) dated.push(event);
  }
  dated.sort((a, b) => (
    String(a.event_date).localeCompare(String(b.event_date))
    || String(a.event_time ?? '99:99').localeCompare(String(b.event_time ?? '99:99'))
  ));
  return [...dated, ...undated];
}

// Group into day buckets, in order, undated collected at the end under a null
// key so the view can label it honestly rather than inventing a date.
export function groupByDay(events) {
  const days = new Map();
  const undated = [];
  for (const event of events) {
    if (!event.event_date) { undated.push(event); continue; }
    if (!days.has(event.event_date)) days.set(event.event_date, []);
    days.get(event.event_date).push(event);
  }
  const groups = [...days.entries()].map(([date, items]) => ({ date, items }));
  if (undated.length) groups.push({ date: null, items: undated });
  return groups;
}

/* ── Summary ─────────────────────────────────────────────────────────────── */

// Three counts, each straight from the data. A zero is reported as a zero.
//
// `windowDays` mirrors the dashboard's 7-day horizon so the two screens do not
// disagree about what "this week" means.
export function summarise(events, today = startOfToday(), windowDays = 7) {
  const todayKey = toISO(today);
  const horizon = toISO(addDays(today, windowDays));

  let upcoming = 0;
  let thisWeek = 0;
  let deadlines = 0;
  let cancelled = 0;

  for (const event of events) {
    if (event.status === 'CANCELLED') {
      // A cancellation is still worth counting, but it is not "upcoming".
      if (event.event_date && event.event_date >= todayKey) cancelled += 1;
      continue;
    }
    if (!event.event_date) continue;
    if (event.event_date < todayKey) continue;
    upcoming += 1;
    if (event.event_date <= horizon) {
      thisWeek += 1;
      if (isAssessment(event)) deadlines += 1;
    }
  }
  return { upcoming, thisWeek, deadlines, cancelled, windowDays };
}

/* ── Week grid ───────────────────────────────────────────────────────────── */

function minutes(time) {
  if (!time) return null;
  const [h, m] = String(time).split(':').map(Number);
  return Number.isFinite(h) ? h * 60 + (m || 0) : null;
}

export function timeToMinutes(time) { return minutes(time); }

// The hour range the grid needs to show: wide enough for every entry, never
// wider. Falls back to a plausible teaching day when there is nothing at all,
// so an empty grid still reads as a timetable rather than a void.
export function hourRange(entries, events) {
  const stamps = [];
  for (const e of entries) {
    const s = minutes(e.start_time); if (s !== null) stamps.push(s);
    const t = minutes(e.end_time); if (t !== null) stamps.push(t);
  }
  for (const e of events) {
    const s = minutes(e.event_time); if (s !== null) stamps.push(s);
  }
  if (!stamps.length) return { from: 8, to: 18 };
  const from = Math.max(0, Math.floor(Math.min(...stamps) / 60) - 1);
  const to = Math.min(24, Math.ceil(Math.max(...stamps) / 60) + 1);
  return { from, to: Math.max(to, from + 4) };
}

// Which weekday columns to draw. Mon-Fri always; a weekend column appears only
// if something is actually scheduled in it, so the grid does not carry two
// permanently empty columns.
export function weekColumns(entries, events, weekStart) {
  const used = new Set(entries.map((e) => e.day_of_week));
  for (const event of events) {
    const date = parseISO(event.event_date);
    if (!date) continue;
    const index = (date.getDay() + 6) % 7;             // Monday = 0
    used.add(DAY_ORDER[index]);
  }
  const days = DAY_ORDER.slice(0, 5);
  for (const weekend of ['SATURDAY', 'SUNDAY']) {
    if (used.has(weekend)) days.push(weekend);
  }
  return days.map((day, i) => ({
    day,
    date: weekStart ? addDays(weekStart, DAY_ORDER.indexOf(day)) : null,
    index: i,
  }));
}

// Dated events that fall inside the anchored week, keyed by weekday. The
// recurring timetable has no dates at all, so only these carry one.
export function eventsForWeek(events, weekStart) {
  const from = toISO(weekStart);
  const to = toISO(addDays(weekStart, 6));
  const byDay = new Map();
  for (const event of events) {
    if (!event.event_date) continue;
    if (event.event_date < from || event.event_date > to) continue;
    const date = parseISO(event.event_date);
    const day = DAY_ORDER[(date.getDay() + 6) % 7];
    if (!byDay.has(day)) byDay.set(day, []);
    byDay.get(day).push(event);
  }
  return byDay;
}
