// The public navigation bar.
//
// Section links are in-page anchors, not routes: the public story reads better
// as one continuous page than as five thin ones, and a single page keeps the
// narrative order (problem -> how -> features -> trust) intact no matter where
// someone enters it.
//
// The right-hand actions change with session state. An already signed-in
// visitor who lands on the marketing page is offered the application rather
// than being told to log in again — and is never redirected away, because a
// redirect would make the public page unreachable to the people most likely
// to link it to someone else.

import { useEffect, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext.jsx';
import Brand from './Brand.jsx';
import ThemeToggle from './ThemeToggle.jsx';
import { IconClose, IconMenu } from './icons.jsx';

const SECTIONS = [
  { href: '#problem', label: 'Why' },
  { href: '#how', label: 'How it works' },
  { href: '#features', label: 'Features' },
  { href: '#roles', label: 'For students & reps' },
  { href: '#contact', label: 'Contact' },
];

export default function PublicNav() {
  const { status } = useAuth();
  const { pathname, hash } = useLocation();
  const [open, setOpen] = useState(false);

  // Any navigation closes the sheet, including an in-page jump.
  useEffect(() => { setOpen(false); }, [pathname, hash]);

  useEffect(() => {
    if (!open) return undefined;
    const onKey = (event) => { if (event.key === 'Escape') setOpen(false); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open]);

  const signedIn = status === 'ready';

  return (
    <header className="pubnav">
      <div className="wrap pubnav__in">
        <Brand />

        <nav className="pubnav__links" aria-label="Sections of this page">
          {SECTIONS.map((item) => (
            <a key={item.href} href={item.href}>{item.label}</a>
          ))}
        </nav>

        <div className="pubnav__actions">
          <ThemeToggle />
          {signedIn ? (
            <Link className="btn btn--primary" to="/dashboard">Open AcademicAI</Link>
          ) : (
            <>
              <Link className="btn btn--secondary" to="/login">Log in</Link>
              <Link className="btn btn--primary" to="/sign-up">Get started</Link>
            </>
          )}
          <button type="button" className="btn btn--secondary btn--icon pubnav__burger"
                  aria-expanded={open} aria-controls="public-menu"
                  aria-label={open ? 'Close menu' : 'Open menu'}
                  onClick={() => setOpen((value) => !value)}>
            {open ? <IconClose size={20} /> : <IconMenu size={20} />}
          </button>
        </div>
      </div>

      {open && (
        <div className="pubsheet" id="public-menu">
          {SECTIONS.map((item) => (
            <a key={item.href} href={item.href} onClick={() => setOpen(false)}>{item.label}</a>
          ))}
          <div className="pubsheet__actions">
            {signedIn ? (
              <Link className="btn btn--primary" to="/dashboard">Open AcademicAI</Link>
            ) : (
              <>
                <Link className="btn btn--secondary" to="/login">Log in</Link>
                <Link className="btn btn--primary" to="/sign-up">Get started</Link>
              </>
            )}
          </div>
        </div>
      )}
    </header>
  );
}
