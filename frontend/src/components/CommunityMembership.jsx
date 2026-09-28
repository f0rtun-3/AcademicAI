// S11 · Community → Membership (spec 10).
//
// Transfer sits above Leave: it is the commoner and less destructive action.
// Each is PRECEDED by what it does, never followed by it.
//
// Per J·6, level changes happen only here — never in Profile.

import { useState } from 'react';
import { api } from '../api/client.js';
import { useAuth } from '../auth/AuthContext.jsx';
import { ErrorBanner, SuccessBanner } from './States.jsx';
import { Field, Notice, Panel } from './ui.jsx';

export default function CommunityMembership({ community, membership }) {
  const { refresh, logout } = useAuth();
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [busy, setBusy] = useState(false);
  const [confirmLeave, setConfirmLeave] = useState(false);
  const [transfer, setTransfer] = useState({
    university: community?.university ?? '',
    department: community?.department ?? '',
    level: '',
    academic_session: community?.academic_session ?? '',
  });

  function update(field) {
    return (event) => setTransfer((prev) => ({ ...prev, [field]: event.target.value }));
  }

  async function leave() {
    setBusy(true);
    setError(null);
    try {
      await api.post('/community/leave');
      // Leaving as a rep revokes every session, so the token may already be
      // dead. Either way the session view must be re-read, never predicted.
      await refresh();
    } catch (err) {
      if (err.status === 401) {
        logout();
        return;
      }
      setError(err);
    } finally {
      setBusy(false);
      setConfirmLeave(false);
    }
  }

  async function requestTransfer(event) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const response = await api.post('/community/transfer', transfer);
      setNotice(response.awaiting_approval
        ? 'Transfer requested. You stay in your current community until a rep '
          + 'in the destination approves it.'
        : 'Transfer complete. You are now a member of the destination community.');
      await refresh();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  const isRep = membership?.role === 'VERIFIED_REP';

  return (
    <div className="stack stack--loose" data-testid="community-membership">
      <ErrorBanner message={error} onDismiss={() => setError(null)} />
      <SuccessBanner message={notice} onDismiss={() => setNotice(null)} />

      <Panel title="Transfer to another community">
        <p className="t-body">
          Your current membership stays active until a rep in the destination approves
          the request. Your institutional email must match the destination university.
        </p>

        {/* C·4 — department, level and session have no backend registry, and
            the community is matched on these four values exactly. The preview
            shows what will be stored so a stray space or capital is visible
            while it can still be fixed. The client normalises NOTHING: a
            client that silently rewrote input would become a second,
            undocumented matching rule. */}
        <form onSubmit={requestTransfer} className="form-grid form-grid--2"
              style={{ marginTop: 'var(--s4)' }}>
          <Field id="t-university" label="University" required value={transfer.university}
                 onChange={update('university')} disabled={busy} />
          <Field id="t-department" label="Department" required value={transfer.department}
                 onChange={update('department')} disabled={busy}
                 hint="Type it exactly as your classmates do." />
          <Field id="t-level" label="Level" required value={transfer.level}
                 onChange={update('level')} disabled={busy}
                 hint="Digits only, e.g. 300" />
          <Field id="t-session" label="Academic session" required
                 value={transfer.academic_session} onChange={update('academic_session')}
                 disabled={busy} hint="YYYY/YYYY, e.g. 2026/2027" />
          <div style={{ gridColumn: '1 / -1' }} className="stack">
            {/* Recessed, so the matching key reads as something the form
                derived rather than as a fifth thing to fill in. */}
            <div className="derived stack stack--tight">
              <span className="t-label">You will be matched to</span>
              <span className="t-meta">
                {[transfer.university, transfer.department, transfer.level,
                  transfer.academic_session].filter(Boolean).join(' · ') || '—'}
              </span>
            </div>
            {/* `.stack` is a flex column, so `justify-self` did nothing and the
                button stretched the full width of the panel — the only
                full-bleed button in the product. */}
            <button type="submit" className="btn btn--primary" disabled={busy}
                    aria-busy={busy || undefined}
                    style={{ alignSelf: 'flex-start' }}>
              {busy ? 'Requesting…' : 'Request transfer'}
            </button>
          </div>
        </form>
      </Panel>

      <Panel title="Leave this community">
        {!confirmLeave ? (
          <>
            <Notice tone="crit" label="What leaving does">
              Leaving removes your access to this community&apos;s official information,
              drops your course enrolments and stops its notifications.
              {isRep && ' As a verified rep you also lose that authority and will be signed out.'}
            </Notice>
            <button type="button" className="btn btn--danger" disabled={busy}
                    style={{ marginTop: 'var(--s4)' }}
                    onClick={() => setConfirmLeave(true)}>
              Leave community
            </button>
          </>
        ) : (
          <div className="stack" data-testid="leave-confirm">
            <p className="t-body">
              Leave {community?.department} Level {community?.level}? This cannot be undone
              without a new membership request.
            </p>
            <div className="row-x stackable">
              <button type="button" className="btn btn--danger" disabled={busy}
                      aria-busy={busy || undefined} onClick={leave}>
                {busy ? 'Leaving…' : 'Yes, leave'}
              </button>
              <button type="button" className="btn btn--secondary" disabled={busy}
                      onClick={() => setConfirmLeave(false)}>
                Cancel
              </button>
            </div>
          </div>
        )}
      </Panel>
    </div>
  );
}
