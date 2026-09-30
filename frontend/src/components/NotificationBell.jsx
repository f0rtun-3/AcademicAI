// The notification bell.
//
// It decides nothing: a reminder has fired when the worker says so, and the
// bell renders what `/api/notifications` returns. If the worker is stopped, the
// bell stays empty.
//
// Polling, not sockets: one GET on an interval, plus a refresh when the tab
// regains focus. Polling stops entirely while the tab is hidden.
//
// On time, not eventually: each response says when this person's next
// reminder is due (`next_reminder_at`), and the bell asks again just after
// that. The worker checks for due reminders every two seconds, so the toast
// appears within seconds of the reminder's time. If the worker is late the bell
// asks again shortly; if it is not running, the regular poll carries on. The
// hint only says WHEN to ask - what the bell shows is only what the server
// returned.
//
// A reminder created, edited or cancelled anywhere (liveEvents.js) makes the
// bell re-read at once.

import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api/client.js';
import { IconBell, IconCheck } from './icons.jsx';
import { whenParts } from './ui.jsx';
import NotificationToasts from './NotificationToasts.jsx';
import { usePresence } from './motion.js';
import { notificationKindLabel, notificationViewLabel } from '../lib/vocabulary.js';
import { announce, listen, NOTIFICATIONS_ARRIVED, REMINDERS_CHANGED } from '../lib/liveEvents.js';

// For everything that is not a reminder (a rep's announcement, a changed
// deadline): slow enough to be invisible in aggregate, quick enough that it
// shows up on its own while you are reading. Reminders do not wait for it.
const POLL_MS = 30000;

// Just after a reminder's time: the worker checks every 2s, so by now it has
// had its chance to fire it.
const DUE_GRACE_MS = 2500;
// Due but not in yet - the worker is mid-cycle or behind. Ask again soon...
const RECHECK_MS = 3000;
// ...for this long. Past that the worker is not running, and polling hard
// would change nothing; the regular poll carries on.
const LATE_WINDOW_MS = 2 * 60 * 1000;

// A stack, not a wall. Anything beyond this waits in the bell.
const MAX_TOASTS = 3;

// How long the bell carries its swing class: the swing itself is twice
// --dur-slow (640ms), and the class must outlast it to be removed cleanly.
const NUDGE_MS = 700;

// What sort of thing happened comes from the vocabulary layer
// (notificationKindLabel). A kind it does not know shows no label rather than
// printing its own token.

// Relative inside a day, then the same short day the rest of the product uses
// ("Fri 25 Sep") - not a full date with the year, which read as a different
// kind of value from the "2m ago" beside it.
function when(value) {
  if (!value) return '';
  const at = new Date(value);
  if (Number.isNaN(at.getTime())) return '';
  const minutes = Math.round((Date.now() - at.getTime()) / 60000);
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes}m ago`;
  if (minutes < 60 * 24) return `${Math.round(minutes / 60)}h ago`;
  // The whole instant, not its first ten characters: those are the UTC date,
  // and whenParts reads the day on the university's clock.
  const { top, bottom, year } = whenParts(value);
  return year ? `${top} ${bottom} ${year}` : `${top} ${bottom}`;
}

export default function NotificationBell() {
  const navigate = useNavigate();
  const [items, setItems] = useState([]);
  const [unread, setUnread] = useState(0);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const panelRef = useRef(null);
  const buttonRef = useRef(null);
  const [toasts, setToasts] = useState([]);
  // The panel stays mounted for its closing animation, then goes.
  const [panelShown, panelLeaving] = usePresence(open);
  // A counter, bumped only when something genuinely new and unread arrives;
  // each bump swings the bell once (styles.css §31), and nothing else does.
  const [arrivals, setArrivals] = useState(0);
  const [nudging, setNudging] = useState(false);

  // Every notification id this session has already seen. `null` means the
  // first load has not happened yet.
  //
  // This is the whole "do not replay old notifications" rule. The FIRST
  // response only records what already exists — a page you open with nine
  // unread reminders must not fire nine popups. Every load after that toasts
  // only ids that were not in the set, so a focus refresh or a poll that
  // returns the same rows produces nothing.
  const seen = useRef(null);
  // The one pending "ask again at the reminder's time" timer.
  const dueTimer = useRef(null);

  const load = useCallback(async () => {
    // Replaces any earlier timer: every response carries the current hint.
    function scheduleDueCheck(nextAt) {
      clearTimeout(dueTimer.current);
      dueTimer.current = null;
      const due = nextAt ? Date.parse(nextAt) : NaN;
      if (Number.isNaN(due)) return;
      const now = Date.now();
      let wait;
      if (due > now) wait = due - now + DUE_GRACE_MS;
      else if (now - due < LATE_WINDOW_MS) wait = RECHECK_MS;
      else return;
      // Further off than two polls: a later response will schedule it (and a
      // timer that long is past what setTimeout holds reliably).
      if (wait > 2 * POLL_MS) return;
      dueTimer.current = setTimeout(() => {
        dueTimer.current = null;
        // Hidden: skip. Coming back to the tab reloads, which finds it.
        if (document.visibilityState === 'visible') load();
      }, wait);
    }

    try {
      const data = await api.get('/notifications');
      const list = data.notifications ?? [];
      setItems(list);
      setUnread(data.unread ?? 0);
      scheduleDueCheck(data.next_reminder_at);

      if (seen.current === null) {
        // First sight. Record, announce nothing.
        seen.current = new Set(list.map((n) => n.id));
        return;
      }
      const fresh = list.filter((n) => !n.read_at && !seen.current.has(n.id));
      list.forEach((n) => seen.current.add(n.id));
      if (fresh.length > 0) {
        setArrivals((n) => n + 1);
        // The reminders list and the dashboard re-read, so a reminder reads
        // "Sent" the moment its toast appears rather than after a reload.
        announce(NOTIFICATIONS_ARRIVED, { kinds: fresh.map((n) => n.kind) });
        setToasts((prev) => {
          const known = new Set(prev.map((t) => t.id));
          const added = fresh
            .filter((n) => !known.has(n.id))
            .map((n) => ({
              id: n.id,
              subject: n.subject,
              body: n.body,
              link: n.link,
              kind: n.kind,
              kindLabel: notificationKindLabel(n.kind) ?? 'Notification',
              viewLabel: notificationViewLabel(n.kind),
            }));
          // Newest first, and capped: ten reminders coming due together must
          // not cover the screen. The rest are still in the bell, which is
          // where a backlog belongs.
          return [...added.reverse(), ...prev].slice(0, MAX_TOASTS);
        });
      }
    } catch {
      // A failed poll is not worth a banner. The bell simply shows what it
      // last knew; the next tick tries again.
    }

  }, []);

  useEffect(() => {
    load();
    const tick = setInterval(() => {
      if (document.visibilityState === 'visible') load();
    }, POLL_MS);
    // Coming back to the tab is the moment the count is most likely stale.
    const onFocus = () => { if (document.visibilityState === 'visible') load(); };
    document.addEventListener('visibilitychange', onFocus);
    window.addEventListener('focus', onFocus);
    // A reminder was just set or changed: when the next one is due may be
    // different now.
    const unlisten = listen(REMINDERS_CHANGED, onFocus);
    return () => {
      clearInterval(tick);
      clearTimeout(dueTimer.current);
      document.removeEventListener('visibilitychange', onFocus);
      window.removeEventListener('focus', onFocus);
      unlisten();
    };
  }, [load]);

  // One swing per arrival, then the bell is still again.
  useEffect(() => {
    if (arrivals === 0) return undefined;
    setNudging(true);
    const stop = setTimeout(() => setNudging(false), NUDGE_MS);
    return () => clearTimeout(stop);
  }, [arrivals]);

  // Close on Escape or an outside click, and return focus to the bell — the
  // same contract the account menu in this shell already keeps.
  useEffect(() => {
    if (!open) return undefined;
    const onKey = (event) => {
      if (event.key === 'Escape') { setOpen(false); buttonRef.current?.focus(); }
    };
    const onClick = (event) => {
      if (panelRef.current && !panelRef.current.contains(event.target)
          && !buttonRef.current?.contains(event.target)) setOpen(false);
    };
    document.addEventListener('keydown', onKey);
    document.addEventListener('mousedown', onClick);
    return () => {
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('mousedown', onClick);
    };
  }, [open]);

  async function markRead(id) {
    // Optimistic: the row greys immediately and the badge drops. The server is
    // still the authority — the next load overwrites this either way.
    setItems((prev) => prev.map((n) => (
      n.id === id && !n.read_at ? { ...n, read_at: 'pending' } : n)));
    setUnread((n) => Math.max(0, n - 1));
    try {
      const result = await api.post(`/notifications/${id}/read`);
      if (typeof result?.unread === 'number') setUnread(result.unread);
    } catch {
      load();
    }
  }

  async function markAll() {
    setBusy(true);
    try {
      await api.post('/notifications/read-all');
      await load();
    } finally {
      setBusy(false);
    }
  }

  function openItem(item) {
    if (!item.read_at) markRead(item.id);
    if (item.link) {
      setOpen(false);
      navigate(item.link);
    }
  }

  // Closes the popup and NOTHING else. The notification stays unread, so the
  // bell is still holding it — glancing at a toast is not reading it. Stable,
  // so a bell re-render does not restart the toasts' countdowns.
  const dismissToast = useCallback((id) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  function viewToast(toast) {
    markRead(toast.id);
    dismissToast(toast.id);
    if (toast.link) navigate(toast.link);
  }

  const label = unread > 0
    ? `Notifications, ${unread} unread`
    : 'Notifications';

  return (
    <>
      <NotificationToasts toasts={toasts} onView={viewToast} onDismiss={dismissToast}
                          returnFocusTo={buttonRef} />
      <div className="bell" ref={panelRef}>
      <button type="button" className={`bell__btn${nudging ? ' bell__btn--nudge' : ''}`}
              ref={buttonRef}
              aria-haspopup="dialog" aria-expanded={open} aria-label={label}
              onClick={() => setOpen((v) => !v)}>
        <IconBell size={19} />
        {unread > 0 && (
          // aria-hidden: the count is already in the button's label, and a
          // screen reader should not hear the number twice.
          <span className="bell__badge mono" aria-hidden="true">
            {unread > 9 ? '9+' : unread}
          </span>
        )}
      </button>

      {panelShown && (
        <div className="bell__panel" role="dialog" aria-label="Notifications"
             data-state={panelLeaving ? 'closed' : 'open'}>
          <div className="bell__head">
            <h2 className="t-label">Notifications</h2>
            {unread > 0 && (
              <button type="button" className="linkish" disabled={busy}
                      onClick={markAll}>
                Mark all as read
              </button>
            )}
          </div>

          {items.length === 0 ? (
            <p className="bell__empty prose">
              Nothing yet. Updates from your course reps, and reminders you set,
              appear here when they arrive.
            </p>
          ) : (
            <ul className="bell__list">
              {items.map((item) => {
                const kind = notificationKindLabel(item.kind);
                const isLink = Boolean(item.link);
                return (
                  <li key={item.id}
                      className={`bellrow${item.read_at ? ' bellrow--read' : ''}`}>
                    {/* A row with somewhere to go is a button; one without is
                        text with its own read control, rather than a control
                        that pretends to lead somewhere. */}
                    {isLink ? (
                      <button type="button" className="bellrow__main"
                              onClick={() => openItem(item)}>
                        <BellBody item={item} kind={kind} />
                      </button>
                    ) : (
                      <div className="bellrow__main bellrow__main--flat">
                        <BellBody item={item} kind={kind} />
                      </div>
                    )}
                    {/* The column is always present, even when there is
                        nothing in it: rendering it only for unread rows made
                        the panel's right edge step in and out and pushed each
                        row's text to a different width. */}
                    <span className="bellrow__side">
                      {!item.read_at && (
                        <button type="button" className="bellrow__read"
                                aria-label={`Mark "${item.subject}" as read`}
                                onClick={() => markRead(item.id)}>
                          <IconCheck size={15} />
                        </button>
                      )}
                    </span>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      )}
      </div>
    </>
  );
}

function BellBody({ item, kind }) {
  const unread = !item.read_at;
  return (
    <>
      <span className="bellrow__top">
        {/* Said once, in words, for a screen reader; the dot below is the
            same fact for the eye. */}
        {unread && <span className="sr-only">Unread.</span>}
        {/* The kind drives the label's tone (a cancellation is crit, a
            change is info) - the word is always there, so tone is an echo. */}
        {kind && <span className="bellrow__kind" data-kind={item.kind}>{kind}</span>}
        <span className="bellrow__when">{when(item.created_at)}</span>
      </span>
      <span className="bellrow__subject">
        <span className="bellrow__dot" aria-hidden="true" />
        {item.subject}
      </span>
      {item.body && <span className="bellrow__body">{item.body}</span>}
    </>
  );
}
