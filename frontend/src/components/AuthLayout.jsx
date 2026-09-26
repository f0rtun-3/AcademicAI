// The shell every unauthenticated auth screen sits in.
//
// Two columns on a laptop: the product on the left, the form on the right.
// Below 960px the brand column is removed entirely rather than stacked above
// the form — someone who came here to sign in wants the form, not a second
// helping of marketing, and stacking would push the first input below the
// fold on a phone.
//
// Existing gate screens (verify email, community setup, awaiting approval)
// keep the narrower `.gate` composition on purpose: they are steps INSIDE
// onboarding, where a two-column marketing split would be noise. This layout
// is for the three screens a stranger can reach.

import { Link } from 'react-router-dom';
import Brand from './Brand.jsx';
import ThemeToggle from './ThemeToggle.jsx';
import ProductPreview from './ProductPreview.jsx';
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
        <Brand />
        <div className="authbrand__body">
          {/* A <p>, not an <h2>. As a heading it preceded the form's <h1> in
              DOM order, so the page's first heading was not its title. This is
              marketing copy; the screen's heading is "Sign in". */}
          <p className="authbrand__pitch">{pitch}</p>
          <p>{blurb}</p>
        </div>
        {preview && <ProductPreview />}
        <p className="authbrand__foot t-meta">
          {/* Said on the way in, not buried in a settings page. */}
          AcademicAI does not verify identity or university records.
        </p>
      </aside>

      <main className="authform">
        <div className={`authform__in${wide ? ' authform__in--wide' : ''}`}>
          <div className="authform__brand row-x" style={{ justifyContent: 'space-between' }}>
            <Brand />
            <ThemeToggle />
          </div>

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
