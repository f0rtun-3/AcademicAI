// S15 · Personal reminders (spec 20, 28).
//
// Separate from official academic records: these belong to one student, are
// never published, and the backend scopes every read and write to the owner.
// The privacy statement leads, because "is this visible to my rep?" is the
// first question.
//
// Per the approved decision there is NO COMPLETED state. The action is
// labelled "Cancel reminder" — honest about what it does. Finishing the
// academic work is a separate thing, and lives on the event.

import { useCallback, useEffect, useState } from 'react';
import { api } from '../api/client.js';
import { EmptyState, ErrorBanner } from './States.jsx';
import {
  Board, Field, Panel, Row, StatusBadge, localTime, whenParts,
} from './ui.jsx';
import { reminderLocal } from '../lib/academicTime.js';

const PRIVACY = 'These are personal. They are not official academic records and '
              + 'nobody else sees them.';

// `caption` DEFAULTS to the privacy statement. It must appear wherever
// reminders are shown, so a caller has to opt OUT deliberately (RemindersPage
// does, because it prints the same sentence in a Notice directly above).
// Defaulting to null once already dropped it silently from the dashboard.
export default function PersonalReminders({ caption = PRIVACY }) {
  const [reminders, setReminders] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState(null);
  const [draft, setDraft] = useState({ title: '', remind_at: '' });
  const [creating, setCreating] = useState({ title: '', remind_at: '' });

  const load = useCallback(async () => {
    try {
      const data = await api.get('/reminders');
      setReminders(data.reminders ?? []);
    } catch (err) {
      setError(err);
      setReminders([]);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  async function act(fn) {
    setBusy(true);
    setError(null);
    try {
      await fn();
      await load();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  function startEdit(reminder) {
    setEditing(reminder.id);
    setDraft({
      title: reminder.title,
      // datetime-local wants YYYY-MM-DDTHH:MM: the reminder's time on the
      // university's clock, exactly as the API reports it.
      remind_at: reminderLocal(reminder),
    });
  }

  async function saveEdit(event) {
    event.preventDefault();
    const id = editing;
    await act(() => api.put(`/reminders/${id}`, {
      title: draft.title,
      // Sent as picked; the backend reads it on the university's clock.
      remind_at_local: draft.remind_at,
    }));
    setEditing(null);
  }

  async function create(event) {
    event.preventDefault();
    await act(() => api.post('/reminders', {
      title: creating.title,
      remind_at_local: creating.remind_at,
    }));
    setCreating({ title: '', remind_at: '' });
  }

  if (reminders === null) return <p className="t-meta">Loading reminders…</p>;

  const pending = reminders.filter((r) => r.status === 'PENDING');
  const rest = reminders.filter((r) => r.status !== 'PENDING');
  const ordered = [...pending, ...rest];

  return (
    <div className="stack stack--loose" data-testid="personal-reminders">
      <ErrorBanner message={error} onDismiss={() => setError(null)} />

      {/* The board carries no privacy caption: RemindersPage already states it
          in a Notice directly above, and printing the same sentence twice on
          one screen made the page look padded rather than careful. On the
          dashboard, where there is no Notice, the caption is still supplied by
          the caller. */}
      <Board title="Your reminders"
             action={caption ? <span className="t-meta">{caption}</span> : null}>
        {ordered.length === 0 ? (
          <EmptyState title="You have no personal reminders."
                      message="Add one below, or accept a reminder AcademicAI offers you in chat." />
        ) : ordered.map((reminder) => (
          editing === reminder.id ? (
            <div className="brow brow--flat" key={reminder.id}>
              <form onSubmit={saveEdit} className="stack" style={{ width: '100%' }}>
                <Field id={`r-title-${reminder.id}`} label="Reminder title" required
                       value={draft.title} disabled={busy}
                       onChange={(e) => setDraft({ ...draft, title: e.target.value })} />
                <Field id={`r-when-${reminder.id}`} label="Remind me at" type="datetime-local"
                       required value={draft.remind_at} disabled={busy}
                       onChange={(e) => setDraft({ ...draft, remind_at: e.target.value })} />
                <div className="row-x stackable">
                  <button type="submit" className="btn btn--primary" disabled={busy}>Save</button>
                  <button type="button" className="btn btn--secondary" disabled={busy}
                          onClick={() => setEditing(null)}>Cancel editing</button>
                </div>
              </form>
            </div>
          ) : (
            <Row key={reminder.id}
                 /* Same column as the calendar and the dashboard: the day
                    named, not an ISO date. The clock time moves to the meta
                    line, where a reminder's own detail belongs. */
                 when={whenParts(reminderLocal(reminder))}
                 title={reminder.title}
                 meta={[localTime(reminderLocal(reminder)),
                        reminder.event_id ? 'linked to an academic event' : null]
                   .filter(Boolean).join(' · ') || null}
                 side={<>
                   <StatusBadge value={reminder.status} context="reminder" />
                   {reminder.status === 'PENDING' && (
                     <>
                       <button type="button" className="btn btn--secondary" disabled={busy}
                               data-testid={`edit-${reminder.id}`}
                               onClick={() => startEdit(reminder)}>Edit</button>
                       <button type="button" className="btn btn--danger" disabled={busy}
                               data-testid={`cancel-${reminder.id}`}
                               onClick={() => act(() => api.del(`/reminders/${reminder.id}`))}>
                         Cancel reminder
                       </button>
                     </>
                   )}
                 </>} />
          )
        ))}
      </Board>

      <Panel title="Add a reminder">
        <form onSubmit={create} className="form-grid form-grid--2">
          <Field id="new-reminder-title" label="Reminder title" required
                 value={creating.title} disabled={busy}
                 onChange={(e) => setCreating({ ...creating, title: e.target.value })} />
          <Field id="new-reminder-when" label="Remind me at" type="datetime-local" required
                 value={creating.remind_at} disabled={busy}
                 onChange={(e) => setCreating({ ...creating, remind_at: e.target.value })} />
          <div style={{ gridColumn: '1 / -1' }}>
            <button type="submit" className="btn btn--primary" disabled={busy}>
              {busy ? 'Saving…' : 'Add reminder'}
            </button>
          </div>
        </form>
      </Panel>
    </div>
  );
}
