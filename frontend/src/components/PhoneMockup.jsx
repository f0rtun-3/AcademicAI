// A current iPhone, with AcademicAI running on it.
//
// It replaces the old browser-window preview: AcademicAI is used on phones,
// so the product is shown as the object students actually hold. Two parts:
//
//   Phone          the device - titanium band, black bezel, Dynamic Island,
//                  side buttons, a clipped screen. Purely presentational.
//   AcademicPhone  the device showing AcademicAI: a reminder arriving, the
//                  week's record, then the full record behind one item.
//
// THE SCREEN IS THE REAL UI. The content is built from the application's own
// components and classes (Board, Row, StateChip, the date tile, the facts
// grid) and laid out at a true phone width (390px), then scaled to fit the
// device's screen - so it shows exactly what the app looks like, in the
// current theme, and restyling a row restyles the phone with it. The data is
// illustrative sample content, like the preview it replaces.
//
// It is INERT and DECORATIVE: nothing inside is focusable (no Row has an
// onClick) and the whole device is aria-hidden; the surrounding copy says
// what it shows.

import { Board, Row, StateChip } from './ui.jsx';
import { BrandMark } from './Brand.jsx';
import {
  IconBell, IconCalendar, IconChat, IconCommunity, IconDashboard,
} from './icons.jsx';

// The phone's own status bar: the time, then cellular, Wi-Fi and battery.
function StatusBar() {
  return (
    <div className="phone__status">
      <span className="phone__time">9:41</span>
      <span className="phone__glyphs">
        <svg width="18" height="12" viewBox="0 0 18 12" aria-hidden="true">
          <rect x="0" y="8" width="3" height="4" rx="1" />
          <rect x="5" y="5.5" width="3" height="6.5" rx="1" />
          <rect x="10" y="3" width="3" height="9" rx="1" />
          <rect x="15" y="0" width="3" height="12" rx="1" />
        </svg>
        <svg width="16" height="12" viewBox="0 0 16 12" aria-hidden="true">
          <path d="M8 11.5 5.6 9a3.4 3.4 0 0 1 4.8 0L8 11.5Z" />
          <path d="M3.4 6.8a6.5 6.5 0 0 1 9.2 0l-1.3 1.3a4.7 4.7 0 0 0-6.6 0L3.4 6.8Z" />
          <path d="M1.1 4.5a9.8 9.8 0 0 1 13.8 0l-1.3 1.3a8 8 0 0 0-11.2 0L1.1 4.5Z" />
        </svg>
        <span className="phone__battery"><i /></span>
      </span>
    </div>
  );
}

// The app's own tab dock, as it sits at the foot of a phone.
function TabDock() {
  return (
    <div className="ptabs">
      <span className="is-on"><IconDashboard size={22} />Dashboard</span>
      <span><IconCalendar size={22} />Calendar</span>
      <span><IconCommunity size={22} />Community</span>
      <span><IconChat size={22} />Chat</span>
    </div>
  );
}

// The device. `className` carries the size variant (phone--hero, --auth,
// --peek); everything else is the same object at every size.
export function Phone({ children, className = '' }) {
  return (
    <div className={`phone ${className}`.trim()} aria-hidden="true">
      <span className="phone__btn phone__btn--action" />
      <span className="phone__btn phone__btn--volup" />
      <span className="phone__btn phone__btn--voldown" />
      <span className="phone__btn phone__btn--power" />
      <div className="phone__bezel">
        <div className="phone__screen">
          <span className="phone__island"><i /></span>
          <div className="phone__viewport">
            <StatusBar />
            {children}
            <span className="phone__homebar" />
          </div>
        </div>
      </div>
    </div>
  );
}

// AcademicAI on the phone: a reminder notification drops in, over the week's
// record; then the screen turns to the full record behind that item, and
// back. The cycle is CSS (styles.css section 42), and reduced motion holds it
// on the first screen with the notification shown.
export default function AcademicPhone({ className = '' }) {
  return (
    <Phone className={className}>
      {/* The notification - the moment a reminder fires. */}
      <div className="pnotif">
        <span className="pnotif__icon"><BrandMark size={30} radius={8} /></span>
        <div className="pnotif__body">
          <p className="pnotif__top"><span>AcademicAI</span><span>now</span></p>
          <p className="pnotif__title">COS202 Assignment</p>
          <p className="pnotif__text">Due tomorrow at 23:59. This is your reminder.</p>
        </div>
      </div>

      <div className="papp">
        <header className="papp__bar">
          <span className="papp__brand"><BrandMark size={26} radius={7} />AcademicAI</span>
          <span className="papp__avatar">AO</span>
        </header>

        <div className="papp__scenes">
          {/* Scene one: what is next, and the week around it. */}
          <section className="papp__scene papp__scene--next">
            <p className="eyebrow-label">Your next reminder</p>
            <div className="pnext">
              <span className="pnext__icon"><IconBell size={20} /></span>
              <div className="pnext__body">
                <p className="pnext__when">Today at 18:00</p>
                <p className="pnext__title">COS202 Assignment</p>
                <p className="pnext__meta">Data Structures · due Monday 23:59</p>
              </div>
            </div>
            {/* It is Sunday: everything here is still ahead, so every node
                on the spine is hollow. */}
            <Board title="This week" icon={IconCalendar} className="board--timeline">
              <Row when={{ top: 'Mon', bottom: '28 Sep' }}
                   title="COS202 Assignment" meta="Assignment · due 23:59" />
              <Row when={{ top: 'Wed', bottom: '30 Sep' }}
                   title="MTH202 Test" meta="Test · 14:00 · B107" />
              <Row when={{ top: 'Thu', bottom: '1 Oct' }}
                   title="PHY204 Lab" meta="Practical · 10:00 · Lab 3" />
              <Row when={{ top: 'Fri', bottom: '2 Oct' }}
                   title="COS210 Proposal" meta="Project · online" />
            </Board>
          </section>

          {/* Scene two: the record behind that item - dated, placed, and
              showing what changed. */}
          <section className="papp__scene papp__scene--record">
            <p className="eyebrow-label">The record</p>
            <div className="precord__head">
              <span className="datetile">
                <span className="datetile__dow">Mon</span>
                <span className="datetile__num">28</span>
                <span className="datetile__mon">Sep</span>
              </span>
              <div>
                <p className="precord__title">COS202 Assignment</p>
                <p className="evmeta">
                  <span className="evmeta__course">COS202</span>
                  <StateChip value="DEADLINE_MOVED" />
                </p>
              </div>
            </div>
            <dl className="kv kv--facts">
              <div className="kv__item"><dt>Due</dt><dd>Monday 28 September</dd></div>
              <div className="kv__item"><dt>Time</dt><dd>23:59</dd></div>
              <div className="kv__item"><dt>Venue</dt><dd>Online portal</dd></div>
              <div className="kv__item"><dt>Status</dt><dd>Scheduled</dd></div>
            </dl>
            <p className="precord__change">
              The deadline moved from Friday 25 September to Monday 28 September.
              <span>By your course rep</span>
            </p>
            <p className="precord__remind">
              <IconBell size={18} />
              <span><b>Your reminder</b>Today at 18:00, and again at 21:00</span>
            </p>
          </section>
        </div>
      </div>

      <TabDock />
    </Phone>
  );
}
