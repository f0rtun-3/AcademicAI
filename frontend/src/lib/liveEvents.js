// Two in-page signals, so the parts of the app that show reminders move
// together without a second poll or a socket.
//
//   REMINDERS_CHANGED       a reminder was created, edited or cancelled. Sent
//                           by the API client after any successful write to
//                           /reminders; the bell re-reads, because when the
//                           next reminder is due may have changed.
//   NOTIFICATIONS_ARRIVED   the bell's poll found something new. Sent by the
//                           bell with the kinds that arrived; the reminders
//                           list and the dashboard re-read, so a reminder
//                           reads "Sent" the moment its toast appears.
//
// Window events rather than a store: three listeners, no shared state, and
// nothing to wire through the component tree.

export const REMINDERS_CHANGED = 'academicai:reminders-changed';
export const NOTIFICATIONS_ARRIVED = 'academicai:notifications-arrived';

export function announce(name, detail) {
  if (typeof window === 'undefined') return;
  window.dispatchEvent(new CustomEvent(name, { detail }));
}

// Returns the unsubscribe function, so an effect can return it directly.
export function listen(name, fn) {
  if (typeof window === 'undefined') return () => {};
  window.addEventListener(name, fn);
  return () => window.removeEventListener(name, fn);
}
