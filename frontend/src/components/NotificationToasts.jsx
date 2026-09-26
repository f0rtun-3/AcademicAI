// The toast stack.
//
// Presentational only. It owns no polling, no timers that fetch anything, and
// no knowledge of what a reminder is — NotificationBell decides what is new
// and hands it here. There is exactly one poll in this app and it is the
// bell's.
//
// AUTO-DISMISS AND KEYBOARD ACCESS
// -------------------------------
// A toast that disappears on a fixed timer while someone is tabbing towards
// its buttons is unusable by keyboard. The timer therefore pauses while the
// stack has focus or the pointer is over it, and resumes when it leaves.
//
// The region is `aria-live="polite"`: a reminder arriving is worth announcing,
// but not worth interrupting whatever is being read. It is ALWAYS mounted,
// even with nothing in it. A live region inserted together with its first
// message is often not announced at all, because assistive technology only
// watches regions that already existed.

import { useCallback, useEffect, useRef, useState } from 'react';
import { IconBell, IconClose } from './icons.jsx';

// Long enough to read a title and reach a button, short enough not to linger.
const DISMISS_MS = 7000;

function Toast({ toast, onView, onDismiss, paused }) {
  const timer = useRef(null);

  useEffect(() => {
    if (paused) return undefined;
    timer.current = setTimeout(() => onDismiss(toast.id), DISMISS_MS);
    return () => clearTimeout(timer.current);
    // `paused` flipping restarts the countdown, which is the intent: leaving
    // the stack gives you the full time again rather than a remnant.
  }, [paused, toast.id, onDismiss]);

  return (
    <div className="toast">
      <span className="toast__icon" aria-hidden="true"><IconBell size={16} /></span>
      <div className="toast__body">
        {toast.kindLabel && <p className="toast__kind">{toast.kindLabel}</p>}
        <p className="toast__subject">{toast.subject}</p>
        {toast.body && <p className="toast__text">{toast.body}</p>}
        {/* Only offered when there is somewhere to go. A button that leads
            nowhere is worse than no button. */}
        {toast.link && (
          <button type="button" className="btn btn--secondary btn--sm toast__view"
                  onClick={() => onView(toast)}>
            {toast.viewLabel}
          </button>
        )}
      </div>
      {/* Dismiss ONLY. It closes the toast and deliberately leaves the
          notification unread — you have glanced at it, not dealt with it, and
          the bell must still be holding it. */}
      <button type="button" className="toast__close"
              aria-label={`Dismiss ${toast.subject}`}
              onClick={() => onDismiss(toast.id)}>
        <IconClose size={15} />
      </button>
    </div>
  );
}

// `returnFocusTo` is a ref to the control focus should go back to when the
// last toast holding focus is dismissed - the bell, which still holds the
// notification.
export default function NotificationToasts({ toasts, onView, onDismiss, returnFocusTo }) {
  const [paused, setPaused] = useState(false);
  const stackRef = useRef(null);
  const restoreFocus = useRef(false);

  // An emptied stack can never receive the mouseleave or blur that would
  // unpause it, so the pause is released here. Without this, dismissing the
  // last toast with the pointer over it left every later toast on screen for
  // good.
  useEffect(() => {
    if (toasts.length === 0) setPaused(false);
  }, [toasts.length]);

  // A dismissed toast takes its focused button with it, which would drop
  // keyboard focus to the top of the page. Focus moves to the next toast, or
  // back to the bell when none is left.
  useEffect(() => {
    if (!restoreFocus.current) return;
    restoreFocus.current = false;
    const next = stackRef.current?.querySelector('.toast button');
    if (next) next.focus();
    else returnFocusTo?.current?.focus();
  }, [toasts, returnFocusTo]);

  // Stable, so a re-render does not restart every toast's countdown.
  const dismiss = useCallback((id) => {
    if (stackRef.current?.contains(document.activeElement)) restoreFocus.current = true;
    onDismiss(id);
  }, [onDismiss]);

  return (
    <div className="toasts" ref={stackRef} role="region" aria-label="New notifications"
         aria-live="polite"
         onMouseEnter={() => setPaused(true)}
         onMouseLeave={() => setPaused(false)}
         onFocus={() => setPaused(true)}
         onBlur={(event) => {
           // Only unpause when focus leaves the stack entirely, not when it
           // moves between the buttons inside it.
           if (!event.currentTarget.contains(event.relatedTarget)) setPaused(false);
         }}>
      {toasts.map((toast) => (
        <Toast key={toast.id} toast={toast} onView={onView}
               onDismiss={dismiss} paused={paused} />
      ))}
    </div>
  );
}
