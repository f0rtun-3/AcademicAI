// The public home page — the unauthenticated entry point to AcademicAI.
//
// One page, anchored sections, because the public story is a narrative and
// reads better in order: what it is, the problem, how it works, what is in
// it, who it is for, how official information is authorised, and only then
// how to get in - and last, how to reach the people building it.
//
// COPY RULES THIS PAGE IS WRITTEN UNDER
// -------------------------------------
// Every claim here has to be true of the MVP as built. Specifically it does
// NOT say, or imply, that AcademicAI:
//   * verifies identity, student ID cards or university records
//   * guarantees any date, deadline or venue is correct
//   * publishes official information itself
//   * contacts lecturers, or represents any university
//   * notifies by anything other than in-app notifications and email
//
// And it states the trust model plainly, because that model IS the product:
// AI proposes, a human course rep reviews, the backend authorises, the
// database is the record.

import { useEffect } from 'react';
import { Link } from 'react-router-dom';
import PublicNav from '../components/PublicNav.jsx';
import PublicFooter from '../components/PublicFooter.jsx';
import AcademicPhone from '../components/PhoneMockup.jsx';
import { useAuth } from '../auth/AuthContext.jsx';
import {
  IconArrowRight, IconBell, IconBook, IconCalendar, IconChat, IconCheck, IconDashboard,
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

// The six features, split the way the product itself is split: four are the
// RECORD (what your reps publish, organised by time), two are the SIGNAL (the
// assistant that reads it). The section shows that split rather than six
// identical cards.
// Where feedback goes: a real inbox, reached by the visitor's own email app.
// Each reason fills in only the SUBJECT, so the message itself is theirs.
const CONTACT_EMAIL = 'helloacademicai@gmail.com';
const mailto = (subject) => `mailto:${CONTACT_EMAIL}?subject=${encodeURIComponent(subject)}`;
const CONTACT_REASONS = [
  { title: 'Report a bug', body: 'Something isn’t working as expected.',
    subject: 'AcademicAI — Bug Report' },
  { title: 'Share feedback', body: 'Tell us what would make AcademicAI better.',
    subject: 'AcademicAI — Feedback' },
  { title: 'Ask a question', body: 'Questions about AcademicAI or how it works.',
    subject: 'AcademicAI — Question' },
];

const RECORD_FEATURES = FEATURES.filter((f) => !['AI Chat', 'Add a message'].includes(f.title));
const SIGNAL_FEATURES = FEATURES.filter((f) => ['AI Chat', 'Add a message'].includes(f.title));

// A section's place in the page's narrative. The page IS read in order (see
// the note at the top), so the numbering encodes a real sequence.
function SectionMark({ n, label }) {
  return (
    <p className="smark">
      <span className="smark__n">{n}</span>
      <span className="smark__label">{label}</span>
    </p>
  );
}

// Adds `is-revealed` to each [data-reveal] block as it scrolls into view, so
// sections settle in once rather than all being present at load. Without
// IntersectionObserver, or under reduced motion, everything is simply shown:
// the hidden starting state only applies once this has run (html.reveal-on).
function useReveal() {
  useEffect(() => {
    const root = document.documentElement;
    const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
    if (reduced || typeof IntersectionObserver === 'undefined') return undefined;
    root.classList.add('reveal-on');
    const seen = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add('is-revealed');
          seen.unobserve(entry.target);
        }
      });
    }, { rootMargin: '0px 0px -8% 0px', threshold: 0.08 });
    document.querySelectorAll('[data-reveal]').forEach((el) => seen.observe(el));
    return () => { seen.disconnect(); root.classList.remove('reveal-on'); };
  }, []);
}

// Arriving at "/#contact" from another page (the Terms' nav or footer): the
// browser looked for #contact before React rendered it, so look again once
// the page exists - and land there at once. The page's smooth scrolling is
// for moving within it; arriving is not a journey down five screens.
function useArrivalHash() {
  useEffect(() => {
    const id = window.location.hash.slice(1);
    if (id) document.getElementById(id)?.scrollIntoView({ behavior: 'instant', block: 'start' });
  }, []);
}

export default function Landing() {
  const { status } = useAuth();
  const signedIn = status === 'ready';
  useReveal();
  useArrivalHash();

  return (
    <div className="public">
      <PublicNav />

      <main className="public__main" id="main">
        {/* ── Hero: night, the product set on it ─────────────────────────── */}
        <section className="hero">
          <div className="wrap hero__grid">
            <div className="hero__copy">
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
            {/* The story in one picture: a message as it arrives in a group
                chat - lower-case, buried, easy to miss - and the same thing on
                AcademicAI, a dated record with a reminder that fires. The phone
                is the real application at phone size. Illustrative and inert. */}
            <div className="hero__visual" aria-hidden="true">
              <p className="hero__raw">
                <span className="hero__raw-who">Class group · 11:02 pm</span>
                pls note cos202 assignment is due monday by 11:59pm, submit on the portal
              </p>
              <div className="phone-stage">
                <div className="phone-float">
                  <AcademicPhone className="phone--hero" />
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* ── 01 · The problem ───────────────────────────────────────────── */}
        <section className="section section--problem" id="problem">
          <div className="wrap split-ed" data-reveal>
            <div className="split-ed__head">
              <SectionMark n="01" label="The problem" />
              <h2 className="ed-h2">Nothing is missing. It is just somewhere in the chat.</h2>
              <p className="ed-lede">
                Most academic information does get shared. The difficulty is that it
                is shared as conversation — so it is not dated, not structured, and
                not there when you go looking for it.
              </p>
            </div>
            <ul className="edlist">
              {PROBLEMS.map(({ Icon, title, body }) => (
                <li className="edlist__item" key={title}>
                  <span className="edlist__icon" aria-hidden="true"><Icon size={18} /></span>
                  <div>
                    <h3 className="edlist__title">{title}</h3>
                    <p className="edlist__body">{body}</p>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        </section>

        {/* ── 02 · How it works: three steps on the time spine ───────────── */}
        <section className="section section--white" id="how">
          <div className="wrap" data-reveal>
            <div className="ed-head">
              <SectionMark n="02" label="The process" />
              <h2 className="ed-h2">How it works</h2>
              <p className="ed-lede">Three steps, and a human decides the one that matters.</p>
            </div>
            <ol className="spine3">
              <li className="spine3__step">
                <span className="spine3__node" aria-hidden="true" />
                <span className="spine3__n" aria-hidden="true">01</span>
                <h3>Academic information arrives</h3>
                <p>
                  A course rep publishes an event, or anyone pastes an announcement
                  they were sent for AcademicAI to interpret.
                </p>
              </li>
              <li className="spine3__step spine3__step--signal">
                <span className="spine3__node" aria-hidden="true" />
                <span className="spine3__n" aria-hidden="true">02</span>
                <h3>AcademicAI organises it</h3>
                <p>
                  Dates, times, venues and courses are pulled into structured records
                  scoped to your exact community — and a rep confirms anything official.
                </p>
              </li>
              <li className="spine3__step spine3__step--record">
                <span className="spine3__node" aria-hidden="true" />
                <span className="spine3__n" aria-hidden="true">03</span>
                <h3>You know what matters, and when</h3>
                <p>
                  It shows up on your dashboard and calendar, and you can set a
                  private reminder or just ask what is due.
                </p>
              </li>
            </ol>
          </div>
        </section>

        {/* ── 03 · What is in it: the record, and the signal ─────────────── */}
        <section className="section" id="features">
          <div className="wrap">
            <div className="ed-head" data-reveal>
              <SectionMark n="03" label="Features" />
              <h2 className="ed-h2">What is in it</h2>
              <p className="ed-lede">
                Built around one community at a time: your university, department,
                level and academic session.
              </p>
            </div>
            <div className="duo">
              <article className="duo__panel duo__panel--record" data-reveal>
                <p className="duo__kicker">The record</p>
                <p className="duo__line">What your course reps publish, organised by time.</p>
                <ul className="duo__list">
                  {RECORD_FEATURES.map(({ Icon, title, body }) => (
                    <li key={title}>
                      <span className="duo__icon" aria-hidden="true"><Icon size={17} /></span>
                      <div>
                        <h3>{title}</h3>
                        <p>{body}</p>
                      </div>
                    </li>
                  ))}
                </ul>
              </article>
              <article className="duo__panel duo__panel--signal" data-reveal>
                <p className="duo__kicker">The signal</p>
                <p className="duo__line">The assistant that reads the record — and never writes it.</p>
                {/* A glimpse of the assistant, illustrative and inert. */}
                <div className="duo__chat" aria-hidden="true">
                  <p className="duo__q">What is due this week?</p>
                  <p className="duo__a">
                    Two things: the COS202 assignment today at 23:59, and the SEN212
                    quiz on Friday.
                  </p>
                </div>
                <ul className="duo__list">
                  {SIGNAL_FEATURES.map(({ Icon, title, body }) => (
                    <li key={title}>
                      <span className="duo__icon" aria-hidden="true"><Icon size={17} /></span>
                      <div>
                        <h3>{title}</h3>
                        <p>{body}</p>
                      </div>
                    </li>
                  ))}
                </ul>
              </article>
            </div>
          </div>
        </section>

        {/* ── 04 · Who it is for: two columns, not two cards ─────────────── */}
        <section className="section section--white" id="roles">
          <div className="wrap">
            <div className="ed-head" data-reveal>
              <SectionMark n="04" label="Who it is for" />
              {/* The two columns carry their own headings; this keeps the
                  page's outline whole for a screen reader. */}
              <h2 className="sr-only">Who it is for</h2>
            </div>
            <div className="roles" data-reveal>
              <article className="roles__col">
                <span className="roles__icon" aria-hidden="true"><IconUser size={20} /></span>
                <h3 className="ed-h3">If you are a student</h3>
                <p className="roles__lede">
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

              <article className="roles__col">
                <span className="roles__icon" aria-hidden="true"><IconMegaphone size={20} /></span>
                <h3 className="ed-h3">If you are a course representative</h3>
                <p className="roles__lede">
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
          </div>
        </section>

        {/* ── 05 · Trust: the chain, on the spine, on night ──────────────── */}
        <section className="section section--night" id="trust">
          <div className="wrap">
            <div className="ed-head" data-reveal>
              <SectionMark n="05" label="Trust" />
              <h2 className="ed-h2">The AI never publishes anything</h2>
              <p className="ed-lede">
                It reads and it proposes. A person decides. That order is the whole
                point, and it does not bend.
              </p>
            </div>
            {/* The trust model as a sequence along one line: it starts in the
                signal (the AI's proposal) and ends in the record. */}
            <ol className="chain" data-reveal>
              {CHAIN.map(({ title, body, truth }, i) => (
                <li className={`chain__link${truth ? ' chain__link--truth' : ''}`
                               + `${i === 0 ? ' chain__link--signal' : ''}`} key={title}>
                  <span className="chain__node" aria-hidden="true" />
                  <h4>{title}</h4>
                  <p>{body}</p>
                </li>
              ))}
            </ol>

            <div className="limits" data-reveal>
              <div>
                <h3 className="ed-h3">What AcademicAI does not do</h3>
                <p className="limits__lede">
                  Being clear about the limits is part of being useful. AcademicAI
                  organises what your community shares with it — it is not a source
                  of authority about your university.
                </p>
              </div>
              <ul className="ticks ticks--night">
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
                  It reaches you <strong>only</strong> in the app and by email. No SMS, no WhatsApp.
                </span></li>
              </ul>
            </div>
          </div>
        </section>

        {/* ── How to get in: one night surface ──────────────────────────
            Straight after the trust model, as the page's opening note says:
            how official information is authorised, and only then how to
            get in. Contact follows it as the page's last word. */}
        <section className="section section--cta">
          <div className="wrap">
            <div className="cta" data-reveal>
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
        {/* ── 06 · Contact: the last word ────────────────────────────────
            The page opens on night with a statement and closes on night with
            one, set the same way. One action - an email to a real inbox - and
            three reasons that open the same email with its subject filled
            in. No form: there is no backend for one, and a form that went
            nowhere would be worse than an address. */}
        <section className="section section--night shape" id="contact"
                 aria-labelledby="shape-title">
          <div className="wrap">
            <div className="shape__head" data-reveal>
              <SectionMark n="06" label="Contact" />
              <h2 className="shape__title" id="shape-title">Help shape AcademicAI.</h2>
              <div className="shape__body">
                <p className="shape__lede">
                  AcademicAI is built around how students actually manage school. If
                  something feels confusing, missing, or unnecessarily difficult, tell us.
                </p>
                <div className="shape__act">
                  <a className="btn shape__cta" href={mailto('AcademicAI — Feedback')}>
                    Send us a message
                    <IconArrowRight size={18} />
                    <span className="sr-only"> (opens your email app)</span>
                  </a>
                </div>
              </div>
            </div>

            <ul className="shape__reasons" data-reveal aria-label="Or start with what it is about">
              {CONTACT_REASONS.map(({ title, body, subject }) => (
                <li key={title}>
                  <a className="shape__reason" href={mailto(subject)}>
                    <span className="shape__reason-title">
                      {title}
                      <IconArrowRight size={16} />
                    </span>
                    <span className="shape__reason-body">{body}</span>
                  </a>
                </li>
              ))}
            </ul>
          </div>
        </section>
      </main>

      <PublicFooter />
    </div>
  );
}
