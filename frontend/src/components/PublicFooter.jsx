// The public footer.
//
// Deliberately short. It links only to things that exist: the in-page sections
// and the two real auth routes. There is no Privacy or Terms link because
// there are no Privacy or Terms pages — linking to a 404, or inventing legal
// text, would both be worse than omitting them.
//
// No invented email address or social accounts either. The one factual line it
// does carry is the product's own limitation, which belongs in the footer of
// every page rather than buried in an About section.

import { Link } from 'react-router-dom';
import Brand from './Brand.jsx';

export default function PublicFooter() {
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
              <li><a href="#how">How it works</a></li>
              <li><a href="#features">Features</a></li>
              <li><a href="#roles">For students &amp; reps</a></li>
              <li><a href="#trust">How official updates work</a></li>
            </ul>
          </div>

          <div>
            <h4>Get started</h4>
            <ul>
              <li><Link to="/sign-up">Create an account</Link></li>
              <li><Link to="/login">Log in</Link></li>
              <li><a href="#contact">Feedback</a></li>
            </ul>
          </div>
        </div>

        <div className="pubfooter__base">
          <span>AcademicAI — a student project, not a university system.</span>
          <span>Built for Nigerian universities</span>
        </div>
      </div>
    </footer>
  );
}
