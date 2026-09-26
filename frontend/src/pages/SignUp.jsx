// S1 · Sign up.
//
// Every field, hint, label, validation rule and request is unchanged. What is
// new is the composition: the nine fields are grouped into three labelled
// fieldsets (account, community, profile) so the form reads as three short
// tasks instead of one long one, and the two shortest fields share a row.
//
// Field LABELS are load-bearing and must not be reworded casually: the
// institutional-domain tests address every input by its label text.
//
// Two rules this screen keeps:
//   * The client never becomes the authority on approved email domains. A
//     mismatch WARNS and still submits; the backend refuses it.
//   * The Matric Number is profile data. Its hint says plainly that nothing
//     verifies it, because nothing does.

import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { api } from '../api/client.js';
import { useAuth } from '../auth/AuthContext.jsx';
import AuthLayout from '../components/AuthLayout.jsx';
import { ErrorBanner, SuccessBanner } from '../components/States.jsx';
import { Field, Notice, PasswordInput } from '../components/ui.jsx';

const EMPTY = {
  full_name: '', email: '', password: '', confirm_password: '',
  university: '', department: '', level: '', academic_session: '',
  // Wire field name, unchanged. The user-facing word is Matric Number (C·12).
  student_id_number: '',
};

export default function SignUp() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [form, setForm] = useState(EMPTY);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [busy, setBusy] = useState(false);
  // The supported universities and their approved domains come from the
  // backend, which is the source of truth. This list is for guidance only:
  // the backend re-checks the domain regardless of what is submitted.
  const [universities, setUniversities] = useState([]);
  // A refusal that names its field (the backend's `details.field`, or the one
  // check made here) is shown BESIDE that field, bound to it with
  // aria-describedby, and focus moves to it - on a nine-field form a message
  // at the top is off-screen by the time the button is pressed.
  const [fieldErrors, setFieldErrors] = useState({});
  const summaryRef = useRef(null);

  useEffect(() => {
    let cancelled = false;
    api.get('/universities')
      .then((data) => { if (!cancelled) setUniversities(data.universities ?? []); })
      .catch(() => { /* guidance only; registration still validates server-side */ });
    return () => { cancelled = true; };
  }, []);

  const selected = universities.find((u) => u.name === form.university);
  const expectedDomains = selected ? selected.domains.map((d) => d.domain) : [];
  const emailDomain = form.email.includes('@')
    ? form.email.trim().toLowerCase().split('@').pop()
    : '';
  const domainMismatch = Boolean(
    emailDomain && expectedDomains.length && !expectedDomains.includes(emailDomain),
  );
  // The one place in the product with a genuine success signal to show: the
  // typed domain is on the approved list for the selected university. It is
  // still only a reading — the backend re-checks it, and a green border here
  // promises nothing about whether registration will be accepted.
  const domainMatches = Boolean(
    emailDomain && expectedDomains.length && expectedDomains.includes(emailDomain),
  );

  function update(field) {
    return (event) => {
      setForm((prev) => ({ ...prev, [field]: event.target.value }));
      // Editing a field answers its error; leave the others where they are.
      setFieldErrors((prev) => {
        if (!prev[field]) return prev;
        const next = { ...prev };
        delete next[field];
        return next;
      });
    };
  }

  function focusField(field) {
    // After React has rendered the error, so the field is announced with it.
    requestAnimationFrame(() => document.getElementById(field)?.focus());
  }

  async function submit(event) {
    event.preventDefault();
    setError(null);
    // The one check made before sending: two password boxes that disagree
    // cannot be what the student meant, and saying so here saves a round trip.
    // The backend still checks it, and every other rule, itself.
    if (form.password && form.confirm_password && form.password !== form.confirm_password) {
      setFieldErrors({ confirm_password: 'Passwords do not match.' });
      focusField('confirm_password');
      return;
    }
    setFieldErrors({});
    setBusy(true);
    try {
      const created = await api.post('/auth/register', form);
      // Say what actually happened, in all three cases. "Check your email"
      // sends someone hunting for a message that was never sent, and this
      // deployment may not verify email at all.
      setNotice(
        created?.email_verification_required === false
          ? 'Account created. You can start using AcademicAI right away.'
          : created?.email_delivered === false
            ? 'Account created. A verification code was generated.'
            : 'Account created. Check your email for a verification code.');
      await login(form.email, form.password);
      // Where to go is the BACKEND's answer, not an assumption made here.
      // With verification off there is no verification step, and routing to
      // one would show a screen that immediately bounces.
      navigate(created?.next_step === 'verify_email' ? '/verify-email' : '/');
    } catch (err) {
      const field = err?.details?.field;
      if (field && field in EMPTY) {
        setFieldErrors({ [field]: err.message });
        focusField(field);
      } else {
        // Not about one field: the summary above the form says it, and takes
        // focus so it is read out rather than appearing silently.
        setError(err);
        requestAnimationFrame(() => summaryRef.current?.focus());
      }
    } finally {
      setBusy(false);
    }
  }

  const placement = [form.university, form.department, form.level, form.academic_session]
    .filter(Boolean).join(' · ');

  return (
    <AuthLayout
      wide
      title="Create your account"
      subtitle="Use your university email. It takes about a minute."
      pitch="Start with your university email."
      blurb="Join the community for your department, level and session, and see what
             your course representatives publish."
      footer={<>Already registered? <Link to="/login">Sign in</Link></>}
    >
      <SuccessBanner message={notice} />
      <div ref={summaryRef} tabIndex={-1} style={{ outline: 'none' }}>
        <ErrorBanner message={error} onDismiss={() => setError(null)} />
      </div>

      <form onSubmit={submit}>
        <fieldset className="fset">
          <legend>Your account</legend>

          <Field id="full_name" label="Full name" required value={form.full_name}
                 error={fieldErrors.full_name}
                 autoComplete="name" onChange={update('full_name')} />

          <Field id="email" label="Student email" type="email" required value={form.email}
                 error={fieldErrors.email}
                 className={domainMatches ? 'field--ok' : undefined}
                 autoComplete="username" onChange={update('email')}
                 hint={expectedDomains.length > 0
                   ? `${form.university} addresses end in `
                     + `${expectedDomains.map((d) => `@${d}`).join(' or ')}.`
                   : 'Use your official student or institutional email address. '
                     + 'Its domain must match the university you select.'} />

          {/* Says exactly what this establishes and no more. It shows control
              of an email account on an approved institution domain - it is not
              evidence of current enrolment, and must never be written as if it
              were. */}
          <p className="t-meta">
            Your institutional email helps us verify that you control an email account
            associated with your university.
          </p>

          {domainMismatch && (
            // Warns, but still submits: the client is not the authority on
            // which domains are approved, and blocking here would make the UI
            // the gate.
            <Notice tone="warn" label="Not an approved domain" role="status">
              That email domain is not approved for {form.university}. Registration will
              be refused unless the address ends in{' '}
              {expectedDomains.map((d) => `@${d}`).join(' or ')}.
            </Notice>
          )}

          <div className="pair">
            <PasswordInput id="password" label="Password" required
                           autoComplete="new-password" value={form.password}
                           error={fieldErrors.password}
                           onChange={update('password')} />
            <PasswordInput id="confirm_password" label="Confirm password" required
                           autoComplete="new-password" value={form.confirm_password}
                           error={fieldErrors.confirm_password}
                           onChange={update('confirm_password')} />
          </div>
        </fieldset>

        <fieldset className="fset">
          <legend>Your academic community</legend>

          {/* University is a closed set held by the backend registry, so it is
              a select. Department, level and session have NO registry (C·4) —
              they stay text inputs, with a preview of what will be stored. The
              client normalises nothing. */}
          <Field id="university" label="University" required error={fieldErrors.university}>
            {(props) => (
              universities.length > 0 ? (
                <select {...props} required value={form.university}
                        onChange={update('university')}>
                  <option value="">Select your university</option>
                  {universities.map((u) => (
                    <option key={u.name} value={u.name}>{u.name}</option>
                  ))}
                </select>
              ) : (
                <input {...props} required value={form.university}
                       onChange={update('university')} />
              )
            )}
          </Field>

          <Field id="department" label="Department" required value={form.department}
                 error={fieldErrors.department}
                 onChange={update('department')}
                 hint="Type it exactly as your classmates do — this is how you are put in the same community." />

          <div className="pair">
            <Field id="level" label="Level" required value={form.level}
                   error={fieldErrors.level}
                   onChange={update('level')} hint="Digits only, e.g. 200" />
            {/* The example is in the hint, not a placeholder: at full contrast
                a placeholder "2026/2027" read as a value already entered. */}
            <Field id="academic_session" label="Academic session" required
                   value={form.academic_session} error={fieldErrors.academic_session}
                   onChange={update('academic_session')} hint="For example 2026/2027" />
          </div>

          {/* Recessed, the same as the transfer form's matching preview: both
              are the community key the form derives, not another input. */}
          <div className="derived stack stack--tight">
            <span className="t-label">You will be placed in</span>
            <span className="t-meta">{placement || '—'}</span>
          </div>
        </fieldset>

        <fieldset className="fset">
          <legend>Your profile</legend>

          {/* Profile information, not evidence. Nothing verifies it: there is
              no ID-card check in this MVP and no university-records lookup, so
              the hint says so plainly rather than letting the student assume
              otherwise. The placeholder is a made-up example on purpose. */}
          <Field id="student_id_number" label="Matric Number" required
                 placeholder="21/1234" value={form.student_id_number}
                 error={fieldErrors.student_id_number}
                 onChange={update('student_id_number')}
                 hint="Your university matric number. AcademicAI does not currently verify this information." />
        </fieldset>

        <button type="submit" className="btn btn--primary btn--block" disabled={busy}
                style={{ marginTop: 'var(--s5)' }}>
          {busy ? 'Creating account…' : 'Create account'}
        </button>
      </form>
    </AuthLayout>
  );
}
