// The AcademicAI lockup: a mark plus the wordmark.
//
// The mark is the favicon's figure at a larger size — three ruled lines of
// decreasing length on the accent ground, i.e. a departure board reduced to
// its smallest legible form. Keeping the two identical means the browser tab
// and the page agree about what this product is.
//
// It is not a fabricated university crest. AcademicAI is not a university and
// must never dress like one.

import { Link } from 'react-router-dom';

export function BrandMark({ size = 30, radius = 7 }) {
  return (
    <span className="brand__mark" style={{ width: size, height: size, borderRadius: radius }}>
      <svg width={Math.round(size * 0.62)} height={Math.round(size * 0.62)}
           viewBox="0 0 24 24" fill="none" stroke="currentColor"
           strokeWidth="2.4" strokeLinecap="round" aria-hidden="true" focusable="false">
        <path d="M4 7h16M4 12h11M4 17h7" />
      </svg>
    </span>
  );
}

// `to` defaults to the public home page. Inside the authenticated shell the
// caller passes /dashboard, so the wordmark always goes somewhere useful
// rather than bouncing a signed-in user out to marketing.
export default function Brand({ to = '/', size = 30, label = 'AcademicAI' }) {
  return (
    <Link className="brand" to={to} aria-label={`${label} home`}>
      <BrandMark size={size} />
      <span className="brand__word">{label}</span>
    </Link>
  );
}
