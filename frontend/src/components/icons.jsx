// 7 · Iconography.
//
// A hand-authored set shipped as inline SVG. No icon library: eighteen glyphs
// is not worth a dependency, and a bundled set would bring hundreds of shapes
// nobody draws.
//
// Style: outline, 1.5px stroke, currentColor, 24x24 box, square-ish geometry
// to match the open apertures of a UI sans. Every glyph inherits colour and sizing
// from its context, so a chip's icon is the chip's colour by construction.
//
// Icons are load-bearing in exactly two places: the mobile tab bar, where
// there is no room for labels alone, and inline state markers. Everywhere else
// the product uses words. Icons are decorative by default (aria-hidden) and
// every tab icon still carries its own text label.

function Svg({ size = 20, title, children }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
         stroke="currentColor" strokeWidth="1.5"
         strokeLinecap="round" strokeLinejoin="round"
         aria-hidden={title ? undefined : 'true'}
         role={title ? 'img' : undefined}
         focusable="false">
      {title && <title>{title}</title>}
      {children}
    </svg>
  );
}

/* ── Navigation ─────────────────────────────────────────────────────────── */

// Dashboard: the departure board itself — a ruled list, not a grid of tiles.
export const IconDashboard = (p) => (
  <Svg {...p}><rect x="3" y="4" width="18" height="16" rx="2" />
    <path d="M3 9h18M8 13h9M8 16.5h6" /></Svg>
);

export const IconCalendar = (p) => (
  <Svg {...p}><rect x="3" y="5" width="18" height="16" rx="2" />
    <path d="M3 10h18M8 3v4M16 3v4" /></Svg>
);

// Community: people, drawn as a group rather than a single figure.
export const IconCommunity = (p) => (
  <Svg {...p}><circle cx="9" cy="8" r="3" />
    <path d="M3.5 19a5.5 5.5 0 0 1 11 0" />
    <path d="M16 6.2a3 3 0 0 1 0 5.6M17.5 19a5.6 5.6 0 0 0-2.2-4.4" /></Svg>
);

export const IconChat = (p) => (
  <Svg {...p}><path d="M20 15a2 2 0 0 1-2 2H8l-4 3.5V6a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2z" />
    <path d="M8.5 9.5h7M8.5 12.5h4" /></Svg>
);

/* ── Actions ────────────────────────────────────────────────────────────── */

export const IconAdd = (p) => <Svg {...p}><path d="M12 5v14M5 12h14" /></Svg>;
export const IconSearch = (p) => (
  <Svg {...p}><circle cx="11" cy="11" r="6" /><path d="M20 20l-4.4-4.4" /></Svg>
);
export const IconFilter = (p) => (
  <Svg {...p}><path d="M4 6h16M7 12h10M10 18h4" /></Svg>
);
export const IconEdit = (p) => (
  <Svg {...p}><path d="M4 20h4L19 9a2.1 2.1 0 0 0-3-3L5 17z" /><path d="M14.5 7.5l2 2" /></Svg>
);
export const IconTrash = (p) => (
  <Svg {...p}><path d="M4 7h16M10 4h4M6 7l1 13h10l1-13" /><path d="M10 11v6M14 11v6" /></Svg>
);
export const IconClose = (p) => <Svg {...p}><path d="M6 6l12 12M18 6L6 18" /></Svg>;
export const IconBack = (p) => <Svg {...p}><path d="M14 6l-6 6 6 6" /></Svg>;
export const IconChevronRight = (p) => <Svg {...p}><path d="M9 5l7 7-7 7" /></Svg>;
export const IconChevronDown = (p) => <Svg {...p}><path d="M5 9l7 7 7-7" /></Svg>;

/* ── Inline state markers ───────────────────────────────────────────────── */

export const IconCheck = (p) => <Svg {...p}><path d="M4.5 12.5l5 5 10-11" /></Svg>;
export const IconAlert = (p) => (
  <Svg {...p}><path d="M12 4.5L2.8 20h18.4z" /><path d="M12 10v4.2M12 17.2v.1" /></Svg>
);
export const IconInfo = (p) => (
  <Svg {...p}><circle cx="12" cy="12" r="8.5" /><path d="M12 11v5.5M12 7.9v.1" /></Svg>
);
export const IconClock = (p) => (
  <Svg {...p}><circle cx="12" cy="12" r="8.5" /><path d="M12 7v5.3l3.4 2" /></Svg>
);
// Venue. A map pin, because a venue is a place, not a building.
export const IconPin = (p) => (
  <Svg {...p}><path d="M12 21s6.5-5.7 6.5-10.3a6.5 6.5 0 1 0-13 0C5.5 15.3 12 21 12 21z" />
    <circle cx="12" cy="10.5" r="2.4" /></Svg>
);
// Supporting material. A paperclip, because the file is attached TO the
// record rather than being the record.
export const IconPaperclip = (p) => (
  <Svg {...p}><path d="M17.5 9.5 10 17a3.5 3.5 0 0 1-5-5l7.8-7.8a2.4 2.4 0 0 1 3.4 3.4
    l-7.7 7.7a1.2 1.2 0 0 1-1.7-1.7l7-7" /></Svg>
);
export const IconUser = (p) => (
  <Svg {...p}><circle cx="12" cy="8" r="3.3" /><path d="M5.5 19.5a6.5 6.5 0 0 1 13 0" /></Svg>
);

/* ── Added for the public site, theme control and password fields ────────────
 * Same construction as above: outline, 1.5px, currentColor, 24x24. The set is
 * still small enough that a dependency would be the wrong trade. */

export const IconMenu = (p) => <Svg {...p}><path d="M4 7h16M4 12h16M4 17h16" /></Svg>;

// Reminders: a bell, the only notification channel the MVP actually has.
export const IconBell = (p) => (
  <Svg {...p}><path d="M18 16V11a6 6 0 1 0-12 0v5l-1.5 2.5h15L18 16Z" />
    <path d="M10 21h4" /></Svg>
);

// Trust: a shield with a rule through it — checked, not decorated.
export const IconShield = (p) => (
  <Svg {...p}><path d="M12 3l7 3v6c0 4.2-2.9 7.6-7 9-4.1-1.4-7-4.8-7-9V6l7-3Z" />
    <path d="M9 12l2.2 2.2L15.5 10" /></Svg>
);

// The AI assist mark. A four-point star, NOT a brain or a robot: the product
// claim is that it reads and proposes, not that it thinks.
// Sending a question. An arrow, not a paper plane: the plane is a messaging
// metaphor and this is a query.
export const IconSend = (p) => (
  <Svg {...p}><path d="M12 19V5M5.5 11.5 12 5l6.5 6.5" /></Svg>
);
export const IconSpark = (p) => (
  <Svg {...p}><path d="M12 3.5l1.7 4.6 4.6 1.7-4.6 1.7L12 16.1l-1.7-4.6L5.7 9.8l4.6-1.7L12 3.5Z" />
    <path d="M18.5 15.5l.8 2 2 .8-2 .8-.8 2-.8-2-2-.8 2-.8.8-2Z" /></Svg>
);

// Official publication: a stamped document.
export const IconMegaphone = (p) => (
  <Svg {...p}><path d="M4 10v4a1 1 0 0 0 1 1h2l6 4V5L7 9H5a1 1 0 0 0-1 1Z" />
    <path d="M17 9.5a3.5 3.5 0 0 1 0 5" /></Svg>
);

export const IconBook = (p) => (
  <Svg {...p}><path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v15H6.5A2.5 2.5 0 0 0 4 20.5V5.5Z" />
    <path d="M8 7.5h8M8 11h5" /></Svg>
);

export const IconInbox = (p) => (
  <Svg {...p}><path d="M3 13l2.6-7A2 2 0 0 1 7.5 4.7h9a2 2 0 0 1 1.9 1.3L21 13v5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-5Z" />
    <path d="M3 13h5l1 2.5h6l1-2.5h5" /></Svg>
);

/* ── Theme control ──────────────────────────────────────────────────────── */

export const IconSun = (p) => (
  <Svg {...p}><circle cx="12" cy="12" r="4" />
    <path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6l1.4 1.4M17 17l1.4 1.4M18.4 5.6L17 7M7 17l-1.4 1.4" /></Svg>
);
export const IconMoon = (p) => (
  <Svg {...p}><path d="M20 14.5A8.2 8.2 0 0 1 9.5 4 8.5 8.5 0 1 0 20 14.5Z" /></Svg>
);
// "System": a display, i.e. whatever the device decides.
export const IconMonitor = (p) => (
  <Svg {...p}><rect x="3" y="4" width="18" height="12" rx="2" />
    <path d="M9 20h6M12 16v4" /></Svg>
);

/* ── Password visibility ────────────────────────────────────────────────── */

export const IconEye = (p) => (
  <Svg {...p}><path d="M2.5 12S6 6 12 6s9.5 6 9.5 6-3.5 6-9.5 6-9.5-6-9.5-6Z" />
    <circle cx="12" cy="12" r="2.6" /></Svg>
);
export const IconEyeOff = (p) => (
  <Svg {...p}><path d="M4 4l16 16" />
    <path d="M9.9 5.2A9.7 9.7 0 0 1 12 5c6 0 9.5 7 9.5 7a17 17 0 0 1-2.3 3.2" />
    <path d="M6.5 7.3A17 17 0 0 0 2.5 12S6 19 12 19a9.6 9.6 0 0 0 3.3-.6" />
    <path d="M9.6 9.8a2.6 2.6 0 0 0 3.5 3.6" /></Svg>
);
