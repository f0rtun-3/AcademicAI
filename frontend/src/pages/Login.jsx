// Log in.
//
// The authentication behaviour is unchanged: the same login() from
// AuthContext, the same ErrorBanner rendering the same backend message, the
// same redirect to /dashboard. Only the composition around it is new.
//
// The h1 stays "Sign in". It is the plainest accurate label for the screen,
// and it is what the onboarding routing test asserts an anonymous visitor is
// sent to — "Welcome back" is the supporting line instead, where it belongs.

import { useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext.jsx';
import AuthLayout from '../components/AuthLayout.jsx';
import { ErrorBanner } from '../components/States.jsx';
import { Field, PasswordInput } from '../components/ui.jsx';

export default function Login() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [form, setForm] = useState({ email: '', password: '' });
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  // Where the gate bounced them from, so a deep link survives signing in.
  const from = location.state?.from;

  async function submit(event) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await login(form.email, form.password);
      // The backend decides the landing step; /dashboard is re-gated on
      // arrival, so an onboarding-incomplete account is still routed correctly.
      navigate(from && from !== '/login' ? from : '/dashboard');
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthLayout
      title="Sign in"
      subtitle="Welcome back. Sign in to see what your community has published."
      footer={<>New to AcademicAI? <Link to="/sign-up">Create an account</Link></>}
    >
      <ErrorBanner message={error} onDismiss={() => setError(null)} />

      <form onSubmit={submit} className="stack">
        <Field id="email" label="Student email" type="email" required
               autoComplete="username" value={form.email}
               onChange={(e) => setForm({ ...form, email: e.target.value })} />

        <div className="stack stack--tight">
          <PasswordInput id="password" label="Password" required
                         autoComplete="current-password" value={form.password}
                         onChange={(e) => setForm({ ...form, password: e.target.value })} />
          <p className="t-meta authform__aside">
            <span />
            <Link to="/forgot-password">Forgot your password?</Link>
          </p>
        </div>

        <button type="submit" className="btn btn--primary btn--block" disabled={busy}
                aria-busy={busy || undefined}
                style={{ marginTop: 'var(--s2)' }}>
          {busy ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
    </AuthLayout>
  );
}
