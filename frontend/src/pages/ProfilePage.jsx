// S16 · Profile.
//
// What AcademicAI believes about you, and how sure it is. Verification sits
// beside the claims it qualifies, so the page can never read as though the
// email check were a university records check.
//
// Per J·6 the academic block is READ-ONLY: changing level means transferring,
// because level is part of the community's identity and changing it moves you
// to a different community.
//
// VISUAL NOTE. The name and email used to sit as bare text on the page
// background — the clearest case of "text placed on a page" rather than an
// application surface. They now occupy an identity card, which carries only
// what the panels below do not: the role and membership state.
//
// The university NAME is deliberately absent: /api/auth/me returns
// `university_id` and no name, and inventing one or adding a request to fetch
// it would be fabrication and an API change respectively. The facts that ARE
// available are shown; the one that is not, is not.

import { Link } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext.jsx';
import { Loading } from '../components/States.jsx';
import { Notice, PageHeader, Panel, StateChip, initials } from '../components/ui.jsx';

export default function ProfilePage() {
  const { user, membership, isRep } = useAuth();
  if (!user) return <Loading label="Loading your profile…" />;

  return (
    <div className="stack stack--loose">
      <PageHeader
        title="Profile"
        lede="What AcademicAI holds about you. Your academic details are read-only —
              changing your level or session means transferring communities." />

      <section className="identity">
        <span className="identity__avatar" aria-hidden="true">{initials(user.full_name)}</span>
        <div className="identity__body">
          <p className="identity__name">{user.full_name}</p>
          <p className="identity__mail">{user.email}</p>
          {/* No facts row. Every value on this page belongs to exactly one
              panel below — academic detail, verification, community — and a
              summary strip repeating them was padding, not hierarchy. The card
              exists to give the name and address a surface, which is the
              defect it was added to fix. */}
        </div>
      </section>

      <Panel title="Academic">
        <dl className="kv">
          <dt>Department</dt><dd>{user.department ?? 'Not set'}</dd>
          <dt>Level</dt><dd className="mono">{user.level ?? 'Not set'}</dd>
          <dt>Session</dt><dd className="mono">{user.academic_session ?? 'Not set'}</dd>
          {/* C·12 — Matric Number in the UI; the column keeps its own name. */}
          <dt>Matric No.</dt><dd className="mono">{user.student_id_number ?? 'Not set'}</dd>
        </dl>
        <p className="prose" style={{ marginTop: 'var(--s3)' }}>
          These are read-only. To change your level or session,{' '}
          <Link className="linkish" to="/community/membership">request a transfer</Link>.
        </p>
      </Panel>

      <Panel title="Verification">
        <dl className="kv">
          <dt>Email</dt>
          <dd><StateChip value={user.email_verified ? 'VERIFIED' : 'UNVERIFIED'} /></dd>
        </dl>
        {/* Says exactly what was established and nothing more. AcademicAI does
            not verify who you are — there is no ID-card check in this MVP — so
            this must never read as "identity verified". */}
        <Notice tone="info" label="What this means" style={{ marginTop: 'var(--s3)' }}>
          Your email address has been verified, and it is on an approved domain for
          your university. AcademicAI has not otherwise confirmed your identity or
          checked your university&apos;s student records.
        </Notice>
      </Panel>

      <Panel title="Community">
        {membership ? (
          <>
            <dl className="kv">
              <dt>Role</dt>
              <dd><StateChip value={isRep ? 'VERIFIED_REP' : 'STUDENT'} /></dd>
              <dt>Status</dt><dd><StateChip value={membership.status} context="membership" /></dd>
            </dl>
            <p className="prose" style={{ marginTop: 'var(--s3)' }}>
              <Link className="linkish" to="/community">Open Community</Link>
            </p>
          </>
        ) : (
          <p className="prose">
            You are not a member of a community yet.{' '}
            <Link className="linkish" to="/community">Find yours</Link>.
          </p>
        )}
      </Panel>
    </div>
  );
}
