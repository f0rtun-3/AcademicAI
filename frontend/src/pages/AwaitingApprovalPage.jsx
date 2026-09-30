// Awaiting approval. A rep in the destination has to act; there is
// nothing the student can do but wait or leave, so the screen offers exactly
// those two and no busywork in between.

import { useAuth } from '../auth/AuthContext.jsx';
import { AwaitingApproval } from '../components/States.jsx';

export default function AwaitingApprovalPage() {
  const { refresh, logout, user } = useAuth();
  return (
    <div className="gate">
      <div className="gate__card stack">
        <p className="t-label">Step 3 of 3</p>
        <AwaitingApproval community={{
          department: user?.department, level: user?.level,
          academic_session: user?.academic_session,
        }} />
        <div className="row-x stackable">
          <button type="button" className="btn btn--secondary" onClick={refresh}>
            Check again
          </button>
          <button type="button" className="btn btn--quiet" onClick={logout}>Log out</button>
        </div>
      </div>
    </div>
  );
}
