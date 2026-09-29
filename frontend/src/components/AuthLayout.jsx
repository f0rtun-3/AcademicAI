// The shell every unauthenticated auth screen sits in.
//
// Three compositions, one per kind of screen:
//
//   laptop   two columns. The brand column's content is a panel exactly one
//            viewport tall and sticky, so it is composed against the SCREEN,
//            not against the form beside it: brand, copy, then the phone
//            rising from the panel's foot. (It used to stretch to the form's
//            height - 1,371px on sign-up - and split the difference into two
//            voids, with the phone below the fold.)
//   tablet   one column: a landscape card - the copy beside the phone - and
//            the form straight after it, at the same width.
//   phone    the form first. Sign-in keeps a compact band with the top of the
//            phone; sign-up, nine fields long, goes without.
//
// On a short screen (below 720px tall, under laptop width) the card and the
// band give their height to the form. All of this is CSS (styles.css section
// 42); the markup below is the same at every size.
//
// Existing gate screens (verify email, community setup, awaiting approval)
// keep the narrower `.gate` composition on purpose: they are steps INSIDE
// onboarding, where a two-column marketing split would be noise. This layout
// is for the three screens a stranger can reach.

import { Link } from 'react-router-dom';
import Brand from './Brand.jsx';
import ThemeToggle from './ThemeToggle.jsx';
import AcademicPhone from './PhoneMockup.jsx';
import { IconBack } from './icons.jsx';

export default function AuthLayout({
  title, subtitle, children, footer, wide = false,
  pitch = 'Your academic life, in one place you can trust.',
  blurb = 'Assignments, quizzes, venue changes and announcements — organised by '
        + 'your department, level and academic session.',
  preview = true,
}) {
  return (
    <div className="authpage">
      <aside className="authbrand">
        <div className={`authbrand__panel${preview ? '' : ' authbrand__panel--plain'}`}>
          <Brand />
          <div className="authbrand__body">
            {/* A <p>, not an <h2>. As a heading it preceded the form's <h1> in
                DOM order, so the page's first heading was not its title. This is
                marketing copy; the screen's heading is "Sign in". */}
            <p className="authbrand__pitch">{pitch}</p>
            <p className="authbrand__blurb">{blurb}</p>
            <p className="authbrand__foot t-meta">
              {/* Said on the way in, not buried in a settings page. */}
              AcademicAI does not verify identity or university records.
            </p>
          </div>
          {/* The product, straight after the copy it illustrates: a phone with
              AcademicAI on it, cropped by the panel's foot so it reads as an
              object in the composition rather than a picture placed in it. */}
          {preview && (
            <div className="authbrand__phone">
              <div className="phone-float"><AcademicPhone className="phone--auth" /></div>
            </div>
          )}
        </div>
      </aside>

      <main className="authform">
        <div className={`authform__in${wide ? ' authform__in--wide' : ''}`}>
          <div className="authform__brand row-x" style={{ justifyContent: 'space-between' }}>
            <Brand />
            <ThemeToggle />
          </div>

          {/* Below laptop width the brand column is gone, and this takes its
              place: the tablet card (copy beside phone), or on a phone the
              sign-in band (the phone alone). Only one of the column and this
              is ever displayed, so the copy is never read twice. */}
          {preview && (
            <div className={`authcard${wide ? ' authcard--wide' : ''}`}>
              <div className="authcard__copy">
                <p className="authcard__pitch">{pitch}</p>
                <p className="authcard__blurb">{blurb}</p>
              </div>
              <div className="authcard__phone"><AcademicPhone className="phone--card" /></div>
            </div>
          )}

          <h1>{title}</h1>
          {subtitle && <p className="authform__sub">{subtitle}</p>}

          {children}

          {footer && <div className="authform__foot">{footer}</div>}

          <p style={{ marginTop: 'var(--s5)' }}>
            <Link className="backlink" to="/">
              <IconBack size={15} />
              <span>Back to home</span>
            </Link>
          </p>
        </div>
      </main>
    </div>
  );
}
