// 13 · Navigation. Four destinations at every size; the shell never changes
// with role.
//
// Three layouts, one structure:
//   >=1024px  a left rail holds the destinations, the top bar holds context
//             (page title, Add message, theme, account)
//   640-1023  the original top-tabs bar
//   <640px    title bar + fixed bottom tab bar + one floating action
//
// The rail is new; the other two are unchanged. Adding it at desktop widths
// frees the top bar for context and stops the four tabs being marooned in the
// middle of a very wide header.
//
// Manage is NOT a fifth destination. It appears as a sub-tab inside Community
// for a verified rep and is absent otherwise — a role changes what is inside
// the shell, never the shell itself.

import { useEffect, useRef, useState } from 'react';
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext.jsx';
import { initials } from './ui.jsx';
import Brand from './Brand.jsx';
import ThemeToggle from './ThemeToggle.jsx';
import NotificationBell from './NotificationBell.jsx';
import { usePresence } from './motion.js';
import {
  IconAdd, IconBell, IconCalendar, IconChat, IconCommunity, IconDashboard, IconUser,
} from './icons.jsx';

const TABS = [
  { to: '/dashboard', label: 'Dashboard', short: 'Dashboard', Icon: IconDashboard },
  { to: '/calendar', label: 'Calendar', short: 'Calendar', Icon: IconCalendar },
  { to: '/community', label: 'Community', short: 'Community', Icon: IconCommunity },
  { to: '/chat', label: 'Chat', short: 'Chat', Icon: IconChat },
];

// Secondary destinations. They are reachable from the rail but are not
// primary: Reminders has its own route and is also surfaced on the dashboard.
const SECONDARY = [
  { to: '/reminders', label: 'Reminders', Icon: IconBell },
  { to: '/profile', label: 'Profile', Icon: IconUser },
];

function titleFor(pathname) {
  // Manage is a Community sub-route; the bar names the tool, while the rail
  // keeps Community highlighted as the place.
  if (pathname.startsWith('/community/manage')) return 'Manage';
  const tab = TABS.find((t) => pathname.startsWith(t.to));
  if (tab) return tab.label;
  if (pathname.startsWith('/events')) return 'Event';
  if (pathname.startsWith('/add-message')) return 'Add message';
  if (pathname.startsWith('/rep')) return 'Manage';
  if (pathname.startsWith('/reminders')) return 'Your reminders';
  if (pathname.startsWith('/profile')) return 'Profile';
  if (pathname.startsWith('/settings')) return 'Settings';
  return 'AcademicAI';
}

export default function Layout() {
  const { user, logout } = useAuth();
  const { pathname } = useLocation();
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef(null);
  // Kept mounted for its closing animation (usePresence), then removed.
  const [menuShown, menuLeaving] = usePresence(menuOpen);
  const onChat = pathname.startsWith('/chat');

  useEffect(() => { setMenuOpen(false); }, [pathname]);
  useEffect(() => {
    if (!menuOpen) return undefined;
    const onKey = (event) => { if (event.key === 'Escape') setMenuOpen(false); };
    const onClick = (event) => {
      if (menuRef.current && !menuRef.current.contains(event.target)) setMenuOpen(false);
    };
    document.addEventListener('keydown', onKey);
    document.addEventListener('mousedown', onClick);
    return () => {
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('mousedown', onClick);
    };
  }, [menuOpen]);

  return (
    <div className="shell shell--rail">
      {/* Skip link: the rail puts eight links before the content, which is a
          long way to tab past on every page. */}
      <a className="skip" href="#content">Skip to content</a>

      {/* ── Desktop rail (hidden below 1024px by the stylesheet) ────────── */}
      <aside className="sidebar">
        <div className="sidebar__brand"><Brand to="/dashboard" size={28} /></div>

        <nav className="sidenav" aria-label="Main">
          {TABS.map((tab) => (
            <NavLink key={tab.to} to={tab.to}
                     className={({ isActive }) => (isActive ? 'active' : undefined)}>
              <tab.Icon size={18} />
              {tab.label}
            </NavLink>
          ))}
        </nav>

        <div>
          <p className="sidebar__heading">Yours</p>
          <nav className="sidenav" aria-label="Your items">
            {SECONDARY.map((item) => (
              <NavLink key={item.to} to={item.to}
                       className={({ isActive }) => (isActive ? 'active' : undefined)}>
                <item.Icon size={18} />
                {item.label}
              </NavLink>
            ))}
          </nav>
        </div>

        <div className="sidebar__group">
          <Link className="btn btn--primary" to="/add-message"
                style={{ justifyContent: 'center' }}>
            <IconAdd size={18} />
            Add message
          </Link>
          <div className="row-x" style={{ justifyContent: 'space-between', marginTop: 'var(--s3)' }}>
            <Link className="sidebar__quiet" to="/settings">Settings</Link>
            <ThemeToggle />
          </div>
        </div>
      </aside>

      <header className="topbar">
        {/* The wordmark stays in the bar below 1024px, where there is no rail
            to carry it. The rail's own brand is hidden at those widths. */}
        <span className="topbar__brand"><Brand to="/dashboard" size={28} /></span>

        <nav className="tabs" aria-label="Main">
          {TABS.map((tab) => (
            <NavLink key={tab.to} to={tab.to}
                     className={({ isActive }) => (isActive ? 'active' : undefined)}>
              {tab.label}
            </NavLink>
          ))}
        </nav>

        {/* At rail widths the bar states where you are instead of repeating
            the navigation. Deliberately NOT an <h1>: every page renders its own
            heading, so marking this one too gave the document two h1s and made
            the real page heading ambiguous. It is contextual chrome, so it is
            a span, and it is hidden from the accessibility tree because the
            page heading already says the same thing. */}
        <span className="topbar__title" aria-hidden="true">{titleFor(pathname)}</span>

        {/* The words go at tablet widths, where the bar would otherwise
            overflow; the aria-label keeps the link's name either way. */}
        <Link className="btn btn--primary topbar__add" to="/add-message" aria-label="Add message">
          <IconAdd size={18} />
          <span className="topbar__addword">Add message</span>
        </Link>

        {/* Phones, Chat only. The floating Add message is withheld there
            because it would sit on the composer's send button, so the bar
            carries the same action as a labelled icon button instead. */}
        {onChat && (
          <Link className="btn btn--primary btn--icon topbar__chatadd" to="/add-message"
                aria-label="Add message" title="Add message">
            <IconAdd size={20} />
          </Link>
        )}

        {/* Beside the account control at every width, because a notification
            is about you in the same way your account is. */}
        <NotificationBell />

        <div ref={menuRef} style={{ position: 'relative' }}>
          <button type="button" className="avatar" aria-haspopup="menu"
                  aria-expanded={menuOpen}
                  aria-label={`Account: ${user?.full_name ?? 'you'}`}
                  onClick={() => setMenuOpen((open) => !open)}>
            {initials(user?.full_name)}
          </button>
          {menuShown && (
            <div className="menu" role="menu" data-state={menuLeaving ? 'closed' : 'open'}>
              <div className="menu__who">
                <strong>{user?.full_name ?? 'You'}</strong>
                <span className="mono">{user?.email}</span>
              </div>
              <Link className="menu__item" role="menuitem" to="/profile">Profile</Link>
              <Link className="menu__item" role="menuitem" to="/reminders">Your reminders</Link>
              <Link className="menu__item" role="menuitem" to="/settings">Settings</Link>
              <div className="menu__theme">
                <span className="t-label">Theme</span>
                <ThemeToggle />
              </div>
              <button type="button" className="menu__item" role="menuitem"
                      onClick={logout}>Log out</button>
            </div>
          )}
        </div>
      </header>

      <main className="main" id="content">
        <Outlet />
      </main>

      {/* One floating action on phones; the header/rail button covers the rest.
          Not on Chat: that page's own composer is fixed to the bottom of the
          screen, and a floating button lands squarely on its send control.
          There the top bar's icon button carries the action instead. */}
      {!onChat && (
        <Link className="btn btn--primary fab" to="/add-message">
          <IconAdd size={20} />
          Add message
        </Link>
      )}

      <nav className="tabbar" aria-label="Sections">
        {TABS.map((tab) => (
          <NavLink key={tab.to} to={tab.to}
                   className={({ isActive }) => (isActive ? 'active' : undefined)}>
            <tab.Icon size={22} />
            {/* Every tab icon carries its label — never an icon alone. */}
            <span>{tab.short}</span>
          </NavLink>
        ))}
      </nav>
    </div>
  );
}
