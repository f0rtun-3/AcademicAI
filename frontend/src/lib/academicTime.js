// The academic clock, in the browser.
//
// Every AcademicAI date and time is read on the UNIVERSITY'S clock - the IANA
// zone the session carries (/auth/me -> timezone, e.g. "Africa/Lagos") - not
// on whatever the device happens to be set to. A Babcock student whose laptop
// says London still sees Babcock's "08:00" and Babcock's "today".
//
// Two kinds of value reach the interface, and this module keeps them apart:
//
//   * an INSTANT - "2026-09-26T23:30:00+00:00", with its offset. Read here on
//     the academic clock; its first ten characters are the UTC date, which is
//     a different day for part of every night, so they are never used as-is.
//   * an ACADEMIC WALL-CLOCK value - "2026-09-27" or "2026-09-27T00:30" - is
//     already on the university's clock and is used exactly as written.
//
// The browser never turns a wall-clock value into an instant: reminders are
// sent as remind_at_local and the backend attaches the university's zone. So
// nothing here does DST arithmetic; Intl reads instants with the zone's rules.
//
// Before a session names a zone (sign-in pages), the device's own zone is used:
// that is generic browser behaviour, not an AcademicAI time.

let zone = null;
const formatters = new Map();

function isValidZone(name) {
  if (typeof name !== 'string' || !name) return false;
  try {
    new Intl.DateTimeFormat('en-GB', { timeZone: name });
    return true;
  } catch {
    return false;
  }
}

// Called by the auth context whenever the session changes.
export function setAcademicTimeZone(name) {
  zone = isValidZone(name) ? name : null;
}

export function academicTimeZone() {
  return zone;
}

function formatter() {
  // Keyed by the zone NAME (the device's resolved zone when no session has
  // named one), so a cached formatter can never answer for a different zone.
  const key = zone ?? new Intl.DateTimeFormat().resolvedOptions().timeZone;
  if (!formatters.has(key)) {
    formatters.set(key, new Intl.DateTimeFormat('en-GB', {
      timeZone: key,
      year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
    }));
  }
  return formatters.get(key);
}

function partsOf(date) {
  const out = {};
  for (const part of formatter().formatToParts(date)) out[part.type] = part.value;
  return out;
}

const INSTANT = /T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})$/;

// True for a string that names an absolute moment (it carries Z or an offset).
export function isInstant(value) {
  return typeof value === 'string' && INSTANT.test(value);
}

// "2026-09-26T23:30:00+00:00" -> "2026-09-27T00:30" on a Lagos clock.
export function instantToLocal(value) {
  if (!isInstant(value)) return '';
  const at = new Date(value);
  if (Number.isNaN(at.getTime())) return '';
  const p = partsOf(at);
  return `${p.year}-${p.month}-${p.day}T${p.hour}:${p.minute}`;
}

// The academic calendar date of any value: an instant is read on the academic
// clock, a date or wall-clock value is already there.
export function academicDateOf(value) {
  if (!value) return '';
  if (isInstant(value)) return instantToLocal(value).slice(0, 10);
  return String(value).slice(0, 10);
}

// "HH:MM" on the academic clock.
export function academicClockTime(value) {
  if (!value) return null;
  const local = isInstant(value) ? instantToLocal(value) : String(value);
  const time = local.slice(11, 16);
  return /^\d{2}:\d{2}$/.test(time) ? time : null;
}

// Today's date on the academic clock.
export function academicToday(now = new Date()) {
  const p = partsOf(now);
  return `${p.year}-${p.month}-${p.day}`;
}

// A reminder's time on the academic clock, as the API reports it
// (remind_at_local), or read from its instant when an older payload has none.
export function reminderLocal(reminder) {
  return reminder?.remind_at_local || instantToLocal(reminder?.remind_at);
}
