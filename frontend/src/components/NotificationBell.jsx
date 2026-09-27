// The notification bell.
//
// WHAT IT IS ALLOWED TO DECIDE: nothing.
//
// A reminder has fired when the worker says so. This component reads
// `/api/notifications` and renders what is there. It never compares a
// reminder's time to the clock and concludes anything — if the worker is
// stopped, the bell stays empty, which is the truth.
//
// POLLING, NOT SOCKETS
// --------------------
// One GET on an interval, plus a refresh when the tab regains focus, which is
// when a person is actually looking. Polling stops entirely while the tab is
// hidden: a background tab asking every minute forever is the reason this kind
// of thing gets blamed for battery life.

import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api/client.js';
import { IconBell, IconCheck } from './icons.jsx';
import { whenParts } from './ui.jsx';
import NotificationToasts from './NotificationToasts.jsx';
import { notificationKindLabel, notificationViewLabel } from '../lib/vocabulary.js';

// Slow enough to be invisible in aggregate, fast enough that a reminder
// arriving while you are reading the page shows up on its own.
const POLL_MS = 45000;

// A stack, not a wall. Anything beyond this waits in the bell.
const MAX_TOASTS = 3;

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
  const { top, bottom } = whenParts(value);
  return `${top} ${bottom}`;
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

  // Every notification id this session has already seen. `null` means the
  // first load has not happened yet.
  //
  // This is the whole "do not replay old notifications" rule. The FIRST
  // response only records what already exists — a page you open with nine
  // unread reminders must not fire nine popups. Every load after that toasts
  // only ids that were not in the set, so a focus refresh or a poll that
  // returns the same rows produces nothing.
  const seen = useRef(null);

  const load = useCallback(async () => {
    try {
      const data = await api.get('/notifications');
      const list = data.notifications ?? [];
      setItems(list);
      setUnread(data.unread ?? 0);

      if (seen.current === null) {
        // First sight. Record, announce nothing.
        seen.current = new Set(list.map((n) => n.id));
        return;
      }
      const fresh = list.filter((n) => !n.read_at && !seen.current.has(n.id));
      list.forEach((n) => seen.current.add(n.id));
      if (fresh.length > 0) {
        setToasts((prev) => {
          const known = new Set(prev.map((t) => t.id));
          const added = fresh
            .filter((n) => !known.has(n.id))
            .map((n) => ({
              id: n.id,
              subject: n.subject,
              body: n.body,
              link: n.link,
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
    return () => {
      clearInterval(tick);
      document.removeEventListener('visibilitychange', onFocus);
      window.removeEventListener('focus', onFocus);
    };
  }, [load]);

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
      <button type="button" className="bell__btn" ref={buttonRef}
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

      {open && (
        <div className="bell__panel" role="dialog" aria-label="Notifications">
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
        {kind && <span className="bellrow__kind">{kind}</span>}
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
