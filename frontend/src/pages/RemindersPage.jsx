// S15 · Your reminders, as its own route.
//
// Reachable from the Dashboard and from chat, not from primary navigation:
// four tabs at every size, and reminders are not one of them.

import { Link } from 'react-router-dom';
import PersonalReminders from '../components/PersonalReminders.jsx';
import { Notice, PageHeader } from '../components/ui.jsx';

export default function RemindersPage() {
  return (
    <div className="stack stack--loose">
      <PageHeader
        title="Your reminders"
        lede="Private notes AcademicAI emails back to you at a time you choose.
              They are yours alone and never become part of the community's record." />

      <Notice tone="info" label="Private to you">
        These are personal. They are not official academic records and nobody else
        sees them — not your course rep, not your classmates.
      </Notice>

      {/* caption={null}: the Notice directly above already says this, and
          printing it twice on one screen read as padding. */}
      <PersonalReminders caption={null} />

      <p className="prose">
        <Link className="linkish" to="/dashboard">Back to dashboard</Link>
      </p>
    </div>
  );
}
