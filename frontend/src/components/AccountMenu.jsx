// The account menu: who you are, where your things are, and the way out.
//
// ONE COMPONENT, TWO FORMS. On a laptop or tablet it is a popover under the
// avatar. On a phone it is a bottom sheet over a dimmed page - a 300px
// dropdown pinned under a 40px avatar is a desktop control squeezed onto a
// phone, and the sheet puts every row where a thumb already is. The switch
// is CSS (styles.css section 46); the markup and behaviour are the same.
//
// IDENTITY ON NIGHT. The header is the one night surface in the menu, like
// the rail it opens beside: your initials, your name, what you are in your
// community and your address. Everything under it is plain rows.
//
// KEYBOARD. It is a real menu: opening moves focus to the first item, arrow
// keys (and Home/End) move between items, Escape closes and puts focus back
// on the avatar. Clicking outside closes it, as does any navigation.
//
// ON A PHONE IT IS MODAL. The sheet is a dialog (aria-modal) holding the menu,
// and while it is open nothing behind it can be reached: the page is locked
// where it was (lib/scrollLock.js - wheel, trackpad, touch and keyboard, and
// put back exactly on close), the rest of the app is inert, and Tab cycles
// within the sheet instead of leaving it. Tapping the backdrop closes it and
// returns focus to the avatar. On a laptop it stays a popover: tabbing out
// of it closes it, and the page scrolls as normal.

import { useCallback, useEffect, useRef, useState } from 'react';
import { useScrollLock } from '../lib/scrollLock.js';
import { NavLink, useLocation } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext.jsx';
import ThemeToggle from './ThemeToggle.jsx';
import { usePresence } from './motion.js';
import { initials } from './ui.jsx';
import {
  IconBell, IconChevronRight, IconCommunity, IconLogout, IconSliders, IconUser,
} from './icons.jsx';

// A NavLink, so the page you are on is marked as current in the menu too.
// The sheet form (styles.css section 46) applies below 640px.
const SHEET_QUERY = '(max-width: 639px)';
// What sits behind the sheet in the app shell (Layout.jsx) and must not be
// reachable while it is open. The top bar is left alone: the menu lives in it,
// and the backdrop covers the rest of it.
const BACKGROUND = '#content, .sidebar, .tabbar, .fab, .skip';

function useSheet() {
  const supported = typeof window !== 'undefined' && typeof window.matchMedia === 'function';
  const [sheet, setSheet] = useState(() => supported && window.matchMedia(SHEET_QUERY).matches);
  useEffect(() => {
    if (!supported) return undefined;
    const query = window.matchMedia(SHEET_QUERY);
    const onChange = () => setSheet(query.matches);
    query.addEventListener?.('change', onChange);
    return () => query.removeEventListener?.('change', onChange);
  }, [supported]);
  return sheet;
}

const FOCUSABLE = 'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])';

function Item({ to, icon: Icon, children }) {
  return (
    <NavLink role="menuitem" to={to}
             className={({ isActive }) => `menu__item acct__item${isActive ? ' acct__item--here' : ''}`}>
      <Icon size={18} />
      <span className="acct__label">{children}</span>
      <IconChevronRight size={15} />
    </NavLink>
  );
}

export default function AccountMenu() {
  const { user, membership, isRep, logout } = useAuth();
  const { pathname } = useLocation();
  const [open, setOpen] = useState(false);
  // Kept mounted for its closing animation (usePresence), then removed.
  const [shown, leaving] = usePresence(open);
  const wrapRef = useRef(null);
  const buttonRef = useRef(null);
  const menuRef = useRef(null);
  const sheet = useSheet();
  const modal = open && sheet;

  // The page stays exactly where it was while the sheet is up; the sheet
  // itself may scroll if it is taller than the screen.
  useScrollLock(modal, menuRef);
  // ...and nothing behind it takes focus, clicks or a screen reader's cursor.
  useEffect(() => {
    if (!modal) return undefined;
    const behind = [...document.querySelectorAll(BACKGROUND)];
    behind.forEach((el) => el.setAttribute('inert', ''));
    return () => behind.forEach((el) => el.removeAttribute('inert'));
  }, [modal]);

  // preventScroll on every focus move: handing focus back must not move the
  // page (on a phone the top bar scrolls away, and focusing an avatar that is
  // off-screen would drag the page to it - undoing the lock's exact restore).
  const close = useCallback((returnFocus = false) => {
    setOpen(false);
    if (returnFocus) buttonRef.current?.focus({ preventScroll: true });
  }, []);

  useEffect(() => { setOpen(false); }, [pathname]);

  useEffect(() => {
    if (!open) return undefined;
    // Focus lands on the first item, so the keyboard starts inside the menu.
    menuRef.current?.querySelector('[role="menuitem"]')?.focus({ preventScroll: true });
    const onKey = (event) => { if (event.key === 'Escape') close(true); };
    const onDown = (event) => {
      if (wrapRef.current && !wrapRef.current.contains(event.target)) close();
    };
    document.addEventListener('keydown', onKey);
    document.addEventListener('mousedown', onDown);
    return () => {
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('mousedown', onDown);
    };
  }, [open, close]);

  // Arrow keys move between items and wrap; Home and End jump to the ends.
  // As a phone's sheet, Tab also wraps within it rather than leaving it.
  function onMenuKey(event) {
    if (event.key === 'Tab' && modal) {
      const focusable = [...menuRef.current.querySelectorAll(FOCUSABLE)];
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
      return;
    }
    const items = [...menuRef.current.querySelectorAll('[role="menuitem"]')];
    const at = items.indexOf(document.activeElement);
    const go = (i) => { event.preventDefault(); items[(i + items.length) % items.length]?.focus(); };
    if (event.key === 'ArrowDown') go(at + 1);
    else if (event.key === 'ArrowUp') go(at < 0 ? items.length - 1 : at - 1);
    else if (event.key === 'Home') go(0);
    else if (event.key === 'End') go(items.length - 1);
  }

  // Tabbing out of the popover closes it; tabbing within it does not. (The
  // phone's sheet never loses focus this way: Tab wraps inside it.)
  function onBlur(event) {
    if (open && !modal && wrapRef.current && !wrapRef.current.contains(event.relatedTarget)) {
      // A click outside is handled by mousedown; this is the keyboard's exit.
      if (event.relatedTarget) close();
    }
  }

  const name = user?.full_name ?? 'You';
  // What you are here, in words: the role first, then the community you
  // registered for. Without a membership, it says so rather than inventing one.
  const role = !membership ? 'Not in a community yet' : isRep ? 'Course rep' : 'Student';
  const where = [user?.department, user?.level ? `Level ${user.level}` : null]
    .filter(Boolean).join(' · ');
  const state = leaving ? 'closed' : 'open';

  return (
    <div className="acct" ref={wrapRef} onBlur={onBlur}>
      <button type="button" className="avatar" ref={buttonRef}
              aria-haspopup="menu" aria-expanded={open}
              aria-label={`Account: ${name}`}
              onClick={() => setOpen((value) => !value)}>
        {initials(user?.full_name)}
      </button>

      {shown && (
        <>
          {/* The phone's backdrop. On wider screens it is not displayed. */}
          {/* preventDefault: a mousedown's own default would move focus to
              the page body straight after close() hands it to the avatar. */}
          <div className="acct__scrim" data-state={state} aria-hidden="true"
               onMouseDown={(event) => { event.preventDefault(); close(true); }} />
          {/* A menu on a laptop; on a phone a modal dialog that holds the
              menu (the items' wrapper below takes the menu role there). */}
          <div className="menu acct__menu" role={sheet ? 'dialog' : 'menu'}
               aria-modal={sheet || undefined} aria-label="Account"
               data-state={state} ref={menuRef} onKeyDown={onMenuKey}>
            <span className="acct__handle" aria-hidden="true" />

            <div className="acct__who">
              <span className="acct__avatar" aria-hidden="true">
                {initials(user?.full_name)}
              </span>
              <div className="acct__id">
                <p className="acct__name">{name}</p>
                <p className="acct__role">{role}</p>
                {membership && where && <p className="acct__where">{where}</p>}
                {user?.email && <p className="acct__mail">{user.email}</p>}
              </div>
            </div>

            <div className="acct__items" role={sheet ? 'menu' : 'none'}
                 aria-label={sheet ? 'Account' : undefined}>
            <div className="acct__group" role="none">
              <Item to="/profile" icon={IconUser}>Your profile</Item>
              <Item to="/reminders" icon={IconBell}>Your reminders</Item>
              {membership && <Item to="/community/members" icon={IconCommunity}>Community members</Item>}
              <Item to="/settings" icon={IconSliders}>Settings</Item>
            </div>

            {/* The rail carries the theme control on a laptop (styles.css hides
                this row there); below that, this is where it lives. */}
            <div className="acct__theme" role="none">
              <span>Appearance</span>
              <ThemeToggle />
            </div>

            <div className="acct__group acct__group--end" role="none">
              <button type="button" className="menu__item acct__item acct__item--out"
                      role="menuitem" onClick={logout}>
                <IconLogout size={18} />
                <span className="acct__label">Log out</span>
              </button>
            </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
