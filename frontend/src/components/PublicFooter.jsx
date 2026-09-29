// The public footer.
//
// Deliberately short. It links only to things that exist: the in-page sections
// and the two real auth routes. There is no Privacy or Terms link because
// there are no Privacy or Terms pages — linking to a 404, or inventing legal
// text, would both be worse than omitting them.
//
// No social accounts either. The contact address lives in the page's last
// section (#contact), which the Feedback link below leads to. The one legal
// page that exists - the Terms - sits in the same column, not a strip of its
// own under the footer.

import { Link, useLocation } from 'react-router-dom';
import Brand from './Brand.jsx';

export default function PublicFooter() {
  // Section anchors live on the landing page; from the Terms they lead back.
  const { pathname } = useLocation();
  const at = (hash) => (pathname === '/' ? hash : `/${hash}`);
  return (
    <footer className="pubfooter">
      <div className="wrap">
        <div className="pubfooter__grid">
          <div>
            <Brand />
            <p className="t-meta" style={{ marginTop: 'var(--s3)', maxWidth: '34ch' }}>
              Academic information for university students, organised into events,
              reminders and updates you can actually find again.
            </p>
          </div>

          <div>
            <h4>Product</h4>
            <ul>
              <li><a href={at('#how')}>How it works</a></li>
              <li><a href={at('#features')}>Features</a></li>
              <li><a href={at('#roles')}>For students &amp; reps</a></li>
              <li><a href={at('#trust')}>How official updates work</a></li>
            </ul>
          </div>

          <div>
            <h4>Get started</h4>
            <ul>
              <li><Link to="/sign-up">Create an account</Link></li>
              <li><Link to="/login">Log in</Link></li>
              <li><a href={at('#contact')}>Feedback</a></li>
              <li><Link to="/terms">Terms &amp; Conditions</Link></li>
            </ul>
          </div>
        </div>
      </div>
    </footer>
  );
}
