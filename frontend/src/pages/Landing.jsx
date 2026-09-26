// The public home page — the unauthenticated entry point to AcademicAI.
//
// One page, anchored sections, because the public story is a narrative and
// reads better in order: what it is, the problem, how it works, what is in
// it, who it is for, how official information is authorised, and only then
// how to get in.
//
// COPY RULES THIS PAGE IS WRITTEN UNDER
// -------------------------------------
// Every claim here has to be true of the MVP as built. Specifically it does
// NOT say, or imply, that AcademicAI:
//   * verifies identity, student ID cards or university records
//   * guarantees any date, deadline or venue is correct
//   * publishes official information itself
//   * contacts lecturers, or represents any university
//   * notifies by anything other than email
//
// And it states the trust model plainly, because that model IS the product:
// AI proposes, a human course rep reviews, the backend authorises, the
// database is the record.

import { Link } from 'react-router-dom';
import PublicNav from '../components/PublicNav.jsx';
import PublicFooter from '../components/PublicFooter.jsx';
import ProductPreview from '../components/ProductPreview.jsx';
import { useAuth } from '../auth/AuthContext.jsx';
import {
  IconBell, IconBook, IconCalendar, IconChat, IconCheck, IconDashboard,
  IconInbox, IconMegaphone, IconShield, IconSpark, IconUser,
} from '../components/icons.jsx';

const PROBLEMS = [
  {
    Icon: IconInbox,
    title: 'Buried in the group chat',
    body: 'An assignment date is announced at 11pm between two hundred other '
        + 'messages, and by morning it is forty messages further up.',
  },
  {
    Icon: IconCalendar,
    title: 'Changed, and you missed it',
    body: 'A venue moves or a quiz shifts by a week. The correction travels '
        + 'less far than the original did.',
  },
  {
    Icon: IconBook,
    title: 'Impossible to find later',
    body: 'You know someone mentioned the presentation order. You do not know '
        + 'who, when, or in which conversation.',
  },
];

const FEATURES = [
  { Icon: IconDashboard, title: 'Dashboard',
    body: 'What needs attention first — overdue items, today, and anything that '
        + 'was cancelled or rescheduled — then what is coming up.' },
  { Icon: IconCalendar, title: 'Calendar',
    body: 'Your academic dates by week on a laptop and as an agenda on a phone, '
        + 'with the course, time and venue attached.' },
  { Icon: IconBell, title: 'Reminders',
    body: 'Set a personal reminder on any event. It is yours alone — nobody '
        + 'else in your community can see it.' },
  { Icon: IconMegaphone, title: 'Official updates',
    body: 'Announcements, timetable changes and academic events published by a '
        + 'verified course representative for your exact community.' },
  { Icon: IconChat, title: 'AI Chat',
    body: 'Ask what is due this week. Answers come from your community’s '
        + 'own records, and it says so plainly when it has nothing.' },
  { Icon: IconSpark, title: 'Add a message',
    body: 'Paste a messy announcement. AcademicAI reads it and proposes a '
        + 'structured record for a course rep to review.' },
];

const CHAIN = [
  { title: 'AI proposes', body: 'It reads a pasted message and extracts a draft record. It decides nothing.' },
  { title: 'A rep reviews', body: 'A verified course representative checks every field and confirms or discards it.' },
  { title: 'The backend authorises', body: 'Permission is re-checked on the server at the moment of publishing.' },
  { title: 'The database is the record', body: 'What is stored is what the community sees. Nothing else counts.', truth: true },
];

export default function Landing() {
  const { status } = useAuth();
  const signedIn = status === 'ready';

  return (
    <div className="public">
      <PublicNav />

      <main className="public__main" id="main">
        {/* ── Hero ───────────────────────────────────────────────────────── */}
        <section className="hero">
          <div className="wrap hero__grid">
            <div>
              <span className="eyebrow">For university students</span>
              <h1>Your academic life, in one place you can trust.</h1>
              <p className="hero__lede">
                Assignments, quizzes, venue changes and announcements arrive scattered
                across group chats. AcademicAI turns them into dated records, reminders
                and answers — organised by your department, level and session.
              </p>
              <div className="hero__cta">
                {signedIn ? (
                  <Link className="btn btn--primary btn--block" to="/dashboard"
                        style={{ maxWidth: 260 }}>Open AcademicAI</Link>
                ) : (
                  <>
                    <Link className="btn btn--primary" to="/sign-up">Create your account</Link>
                    <Link className="btn btn--secondary" to="/login">Log in</Link>
                  </>
                )}
              </div>
              <p className="hero__note">
                Free to use with your university email. No card, no app to install.
              </p>
            </div>
            <ProductPreview />
          </div>
        </section>

        {/* ── The problem ────────────────────────────────────────────────── */}
        <section className="section" id="problem">
          <div className="wrap">
            <div className="section__head">
              <h2>Nothing is missing. It is just somewhere in the chat.</h2>
              <p>
                Most academic information does get shared. The difficulty is that it
                is shared as conversation — so it is not dated, not structured, and
                not there when you go looking for it.
              </p>
            </div>
            <div className="grid3">
              {PROBLEMS.map(({ Icon, title, body }) => (
                <article className="card" key={title}>
                  <span className="card__icon"><Icon size={20} /></span>
                  <h3>{title}</h3>
                  <p>{body}</p>
                </article>
              ))}
            </div>
          </div>
        </section>

        {/* ── How it works ───────────────────────────────────────────────── */}
        <section className="section section--tint" id="how">
          <div className="wrap">
            <div className="section__head">
              <h2>How it works</h2>
              <p>Three steps, and a human decides the one that matters.</p>
            </div>
            <div className="steps">
              <div className="step">
                <span className="step__n">Step 01</span>
                <h3>Academic information arrives</h3>
                <p>
                  A course rep publishes an event, or anyone pastes an announcement
                  they were sent for AcademicAI to interpret.
                </p>
              </div>
              <div className="step">
                <span className="step__n">Step 02</span>
                <h3>AcademicAI organises it</h3>
                <p>
                  Dates, times, venues and courses are pulled into structured records
                  scoped to your exact community — and a rep confirms anything official.
                </p>
              </div>
              <div className="step">
                <span className="step__n">Step 03</span>
                <h3>You know what matters, and when</h3>
                <p>
                  It shows up on your dashboard and calendar, and you can set a
                  private reminder or just ask what is due.
                </p>
              </div>
            </div>
          </div>
        </section>

        {/* ── Features ───────────────────────────────────────────────────── */}
        <section className="section" id="features">
          <div className="wrap">
            <div className="section__head">
              <h2>What is in it</h2>
              <p>
                Built around one community at a time: your university, department,
                level and academic session.
              </p>
            </div>
            <div className="grid3">
              {FEATURES.map(({ Icon, title, body }) => (
                <article className="card card--hover" key={title}>
                  <span className="card__icon"><Icon size={20} /></span>
                  <h3>{title}</h3>
                  <p>{body}</p>
                </article>
              ))}
            </div>
          </div>
        </section>

        {/* ── Students and reps ──────────────────────────────────────────── */}
        <section className="section section--tint" id="roles">
          <div className="wrap grid2">
            <article className="card">
              <span className="card__icon"><IconUser size={20} /></span>
              <h3>If you are a student</h3>
              <p style={{ marginBottom: 'var(--s4)' }}>
                Join the community for your department, level and session, and get
                everything published to it.
              </p>
              <ul className="ticks">
                <li><IconCheck size={16} /><span>See what is due, what changed and what was cancelled</span></li>
                <li><IconCheck size={16} /><span>Set private reminders only you can see</span></li>
                <li><IconCheck size={16} /><span>Ask the assistant about your own community&apos;s records</span></li>
                <li><IconCheck size={16} /><span>Stand for election as a course representative</span></li>
              </ul>
            </article>

            <article className="card">
              <span className="card__icon"><IconMegaphone size={20} /></span>
              <h3>If you are a course representative</h3>
              <p style={{ marginBottom: 'var(--s4)' }}>
                Elected by your own community, and the only person who can publish
                official information to it.
              </p>
              <ul className="ticks">
                <li><IconCheck size={16} /><span>Publish events, timetable entries and announcements</span></li>
                <li><IconCheck size={16} /><span>Review what the AI proposes before anything goes out</span></li>
                <li><IconCheck size={16} /><span>Manage courses and approve who joins</span></li>
                <li><IconCheck size={16} /><span>Hold authority only in your own community</span></li>
              </ul>
            </article>
          </div>
        </section>

        {/* ── Trust model ────────────────────────────────────────────────── */}
        <section className="section" id="trust">
          <div className="wrap">
            <div className="section__head">
              <h2>The AI never publishes anything</h2>
              <p>
                It reads and it proposes. A person decides. That order is the whole
                point, and it does not bend.
              </p>
            </div>
            <div className="chain">
              {CHAIN.map(({ title, body, truth }) => (
                <div className={`chain__link${truth ? ' chain__link--truth' : ''}`} key={title}>
                  <h4>{title}</h4>
                  <p>{body}</p>
                </div>
              ))}
            </div>

            <div className="band" style={{ marginTop: 'var(--s7)' }}>
              <div>
                <h3 className="t-section" style={{ marginBottom: 'var(--s3)' }}>
                  What AcademicAI does not do
                </h3>
                <p className="t-body" style={{ color: 'var(--slate)' }}>
                  Being clear about the limits is part of being useful. AcademicAI
                  organises what your community shares with it — it is not a source
                  of authority about your university.
                </p>
              </div>
              <ul className="ticks">
                <li><IconShield size={16} /><span>
                  It does <strong>not</strong> verify your identity. Signing up
                  confirms you control a university email address, nothing more.
                </span></li>
                <li><IconShield size={16} /><span>
                  It does <strong>not</strong> check university records, and it is
                  not connected to any university system.
                </span></li>
                <li><IconShield size={16} /><span>
                  It cannot <strong>guarantee</strong> a date is correct. Records are
                  as accurate as what your course rep published.
                </span></li>
                <li><IconShield size={16} /><span>
                  It reaches you by <strong>email</strong> only. No SMS, no WhatsApp.
                </span></li>
              </ul>
            </div>
          </div>
        </section>

        {/* ── Contact / feedback ─────────────────────────────────────────── */}
        <section className="section section--tint" id="contact">
          <div className="wrap band">
            <div className="section__head" style={{ marginBottom: 0 }}>
              <h2>Feedback</h2>
              <p>
                AcademicAI is an early-stage student project and is actively being
                built. What breaks, what is missing and what is confusing are all
                worth hearing about.
              </p>
            </div>
            <div className="card">
              {/* No contact backend exists, so this does NOT pretend to send a
                  message and there is no fabricated email address or form. It
                  says where feedback actually goes today: to the person you got
                  the link from. */}
              <h3>How to get in touch</h3>
              <p style={{ marginBottom: 'var(--s4)' }}>
                There is no contact form yet — building one that silently discarded
                your message would be worse than not having it.
              </p>
              <p>
                If someone shared AcademicAI with you, send your feedback to them
                directly. If you are already signed in, the fastest route is your
                own course representative, who can raise it with the community.
              </p>
            </div>
          </div>
        </section>

        {/* ── Closing CTA ────────────────────────────────────────────────── */}
        <section className="section">
          <div className="wrap">
            <div className="cta">
              <h2>Start with your university email</h2>
              <p>
                Create an account, join the community for your department and level,
                and see what is actually due this week.
              </p>
              <div className="cta__row">
                {signedIn ? (
                  <Link className="btn btn--onaccent" to="/dashboard">Open AcademicAI</Link>
                ) : (
                  <>
                    <Link className="btn btn--onaccent" to="/sign-up">Create your account</Link>
                    <Link className="btn btn--ghostaccent" to="/login">I already have one</Link>
                  </>
                )}
              </div>
            </div>
          </div>
        </section>
      </main>

      <PublicFooter />
    </div>
  );
}
