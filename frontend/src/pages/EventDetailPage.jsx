// S7 · Event detail.
//
// A ROUTE, not a modal and not a side panel: it must be linkable and survive a
// refresh, because reps share these. /events/:id is the canonical address of
// one official record.
//
// Current facts first — what a student came for. Then the change history,
// which explains the chip. Then the original message, because provenance
// matters but is rarely the reason for the visit.

import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { api } from '../api/client.js';
import { useAuth } from '../auth/AuthContext.jsx';
import { useResource } from '../components/useResource.js';
import {
  EmptyState, ErrorBanner, ErrorState, Loading, SuccessBanner,
} from '../components/States.jsx';
import {
  Board, Completion, Field, Modal, Notice, Panel, Row, StatusBadge,
  localInputToUtc, longDate, todayISO, whenParts,
} from '../components/ui.jsx';
import {
  PRIORITIES, dateLabel, describeChange, eventTypeNoun, priorityLabel, statusLabel,
} from '../lib/vocabulary.js';
import { IconBack, IconPaperclip } from '../components/icons.jsx';
import { EventType } from '../components/calendar/AgendaView.jsx';
import AttachmentViewer, { canPreview } from '../components/AttachmentViewer.jsx';

// One row of this event's history, in words. The change is described from the
// event's own point of view ("The deadline was updated.") because the event's
// name is already the page heading; the details say from what to what. No raw
// field name, id, version or state transition reaches the page - the
// vocabulary layer drops what a student has no use for.
function HistoryRow({ change, eventType }) {
  // The event's own type decides the words: an assignment has a deadline and
  // was "added" as an assignment; a quiz has a date.
  const { sentence, details } = describeChange(change, {
    perspective: 'event', subject: { event_type: eventType },
  });
  return (
    <Row when={whenParts(change.created_at)}
         title={sentence}
         meta={(details.length > 0 || change.actor_name) ? (
           <>
             {details.length > 0 && (
               <ul className="chdetails">
                 {details.map((line) => <li key={line}>{line}</li>)}
               </ul>
             )}
             {/* Every change a person made is attributed to them. */}
             {change.actor_name && <span className="chlist__by">By {change.actor_name}</span>}
           </>
         ) : null} />
  );
}

// The reminder defaults to the morning before, but nothing is created until
// the student submits: an offer, never a silent write.
function defaultRemindAt(event) {
  if (!event.event_date) return '';
  const date = new Date(`${event.event_date}T08:00:00`);
  date.setDate(date.getDate() - 1);
  const pad = (n) => String(n).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T08:00`;
}

// Sizes are for a person deciding whether to open something on mobile data,
// so they are rounded rather than exact.
function fileSize(bytes) {
  if (!Number.isFinite(bytes)) return '';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function EventDetailPage() {
  const { eventId } = useParams();
  const { isRep } = useAuth();
  const navigate = useNavigate();
  const { status, data, error, reload } = useResource(
    () => api.get(`/events/${eventId}`), [eventId],
  );
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [confirmCancel, setConfirmCancel] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(null);
  const [reminder, setReminder] = useState(null);
  const [file, setFile] = useState(null);
  const [viewing, setViewing] = useState(null);

  if (status === 'loading') return <Loading label="Loading this record…" />;
  if (status === 'error') {
    // 404 must not confirm existence outside the student's own community.
    return <ErrorState title="That record isn’t in your community"
                       message={error} onRetry={reload} />;
  }

  const { event, history = [] } = data;
  const archived = event.status === 'ARCHIVED';
  const cancelled = event.status === 'CANCELLED';
  const noun = eventTypeNoun(event.event_type);
  const past = Boolean(event.event_date) && event.event_date < todayISO();
  // What the event still asks of the student. A cancelled event asks nothing,
  // so it offers no reminder and no completion; a reminder also makes no
  // sense for work already marked done or a date already gone. Official state
  // and personal completion stay separate: this reads both, changes neither.
  const canRemind = !cancelled && !archived && !past && !event.completed;
  const canComplete = !cancelled;
  // Never assume the key is present: a cached page or an older response shape
  // would otherwise take the whole route down over an optional field.
  const materials = event.attachments ?? [];

  function startEdit() {
    setDraft({
      title: event.title ?? '',
      description: event.description ?? '',
      event_date: event.event_date ?? '',
      event_time: event.event_time ?? '',
      venue: event.venue ?? '',
      priority: event.priority ?? 'NORMAL',
    });
    setEditing(true);
  }

  async function run(fn, message) {
    setBusy(true);
    setActionError(null);
    setNotice(null);
    try {
      await fn();
      if (message) setNotice(message);
      await reload();
      return true;
    } catch (err) {
      setActionError(
        err.code === 'stale_proposal' || err.status === 409
          // Never a force-overwrite: re-reading is the only way on.
          ? err
          : err,
      );
      return false;
    } finally {
      setBusy(false);
    }
  }

  // Uploading is an ordinary, skippable action on an existing record. It is
  // deliberately NOT part of publishing: an event is created and published
  // without this form ever being touched.
  async function attachFile(submitEvent) {
    submitEvent.preventDefault();
    if (!file) return;
    const form = new FormData();
    form.append('file', file);
    const ok = await run(
      () => api.postForm(`/events/${event.id}/attachments`, form),
      'Supporting material added.');
    if (ok) setFile(null);
  }

  async function saveEdit(submitEvent) {
    submitEvent.preventDefault();
    // The version travels with the edit, so a stale form loses to a concurrent
    // change instead of overwriting it. The backend decides.
    const ok = await run(() => api.put(`/events/${event.id}`, {
      title: draft.title,
      // An emptied box means "no instructions were given", which is a real
      // answer and a legitimate edit - so it is sent as null, not omitted.
      description: draft.description || null,
      event_date: draft.event_date || null,
      event_time: draft.event_time || null,
      venue: draft.venue || null,
      priority: draft.priority,
      expected_version: event.version,
    }), 'Updated by you. Enrolled students have been notified.');
    if (ok) setEditing(false);
  }

  async function createReminder(submitEvent) {
    submitEvent.preventDefault();
    const ok = await run(() => api.post('/reminders', {
      title: reminder.title,
      // The picked wall-clock time, as the instant it means in THIS browser's
      // zone (DST included). It used to be the same digits relabelled as UTC,
      // so a Lagos reminder set for 08:00 fired at 09:00.
      remind_at: localInputToUtc(reminder.remind_at),
      event_id: event.id,
    }), 'Personal reminder created. Only you can see it.');
    if (ok) setReminder(null);
  }

  return (
    <div className="stack stack--loose">
      <p className="t-meta">
        <Link className="linkish" to="/calendar"
              style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
          <IconBack size={14} />
          Calendar
        </Link>
      </p>

      <header className="page__head">
        <div className="row-x" style={{ justifyContent: 'space-between' }}>
          <h1 className="t-display">{event.title}</h1>
          {/* Only a state worth noticing earns the badge; "Scheduled" is
              stated in the details below instead. */}
          <StatusBadge value={event.status} />
        </div>
        <p className="evmeta">
          <EventType type={event.event_type} />
          {event.course_code && <span className="evmeta__course mono">{event.course_code}</span>}
          {event.priority === 'HIGH' && <span className="evmeta__pri">High priority</span>}
        </p>
      </header>

      <SuccessBanner message={notice} onDismiss={() => setNotice(null)} />
      <ErrorBanner message={actionError} onDismiss={() => setActionError(null)} />

      {archived && (
        <Notice tone="none" label="Archived">
          This academic session has been archived and no longer accepts changes.
        </Notice>
      )}

      <div className="split">
        <div className="stack">
          <Panel title="Details">
            {editing ? (
              <form onSubmit={saveEdit} className="stack">
                <Field id="e-title" label="Title" required value={draft.title}
                       disabled={busy}
                       onChange={(e) => setDraft({ ...draft, title: e.target.value })} />
                <Field id="e-description" label="Instructions"
                       hint="What the work is. Leave blank if the message did not say.">
                  {(props) => (
                    <textarea {...props} rows={5} value={draft.description}
                              disabled={busy}
                              onChange={(e) => setDraft(
                                { ...draft, description: e.target.value })} />
                  )}
                </Field>
                <Field id="e-date" label="Date" type="date" value={draft.event_date}
                       disabled={busy} hint="Leave blank if the message does not say."
                       onChange={(e) => setDraft({ ...draft, event_date: e.target.value })} />
                <Field id="e-time" label="Time" placeholder="HH:MM" value={draft.event_time}
                       disabled={busy} hint="Leave blank if the message does not say."
                       onChange={(e) => setDraft({ ...draft, event_time: e.target.value })} />
                <Field id="e-venue" label="Venue" value={draft.venue} disabled={busy}
                       hint="Leave blank if the message does not say."
                       onChange={(e) => setDraft({ ...draft, venue: e.target.value })} />
                <Field id="e-priority" label="Priority">
                  {(props) => (
                    <select {...props} value={draft.priority} disabled={busy}
                            onChange={(e) => setDraft({ ...draft, priority: e.target.value })}>
                      {PRIORITIES.map((value) => (
                        <option key={value} value={value}>{priorityLabel(value)}</option>
                      ))}
                    </select>
                  )}
                </Field>
                <Notice tone="warn" label="Publishing a change">
                  Saving notifies every student enrolled on this course, and records
                  what changed against your name.
                </Notice>
                <div className="row-x stackable">
                  <button type="submit" className="btn btn--primary" disabled={busy}>
                    {busy ? 'Saving…' : 'Save and notify students'}
                  </button>
                  <button type="button" className="btn btn--secondary" disabled={busy}
                          onClick={() => setEditing(false)}>Cancel editing</button>
                </div>
              </form>
            ) : (
              <>
                {/* The instructions, when a rep typed any. They come first
                    because they are what the work actually is; the dates and
                    the venue qualify them. Absent is normal and prints
                    nothing rather than an empty heading. */}
                {event.description && (
                  <div className="prose evdesc">{event.description}</div>
                )}

                <dl className="kv">
                  <dt>{dateLabel(event.event_type)}</dt><dd>{longDate(event.event_date)}</dd>
                  <dt>Time</dt><dd>{event.event_time ?? 'Not specified'}</dd>
                  <dt>Venue</dt><dd>{event.venue ?? 'Not specified'}</dd>
                  <dt>Status</dt><dd>{statusLabel(event.status)}</dd>
                </dl>

                {cancelled && (
                  <Notice tone="crit" label={`This ${noun} was cancelled`}
                          style={{ marginTop: 'var(--s5)' }}>
                    There is nothing to prepare for or hand in. The record is kept so
                    you can see what was planned.
                  </Notice>
                )}

                <div className="row-x stackable" style={{ marginTop: 'var(--s5)' }}>
                  {/* Student primary. A rep gets Edit as the primary instead. */}
                  {isRep && !archived && (
                    <button type="button" className="btn btn--primary" disabled={busy}
                            onClick={startEdit}>Edit</button>
                  )}
                  {canRemind && !reminder && (
                    <button type="button"
                            className={isRep ? 'btn btn--secondary' : 'btn btn--primary'}
                            disabled={busy}
                            onClick={() => setReminder({
                              title: `Prepare for ${event.title}`,
                              remind_at: defaultRemindAt(event),
                            })}>
                      Add a reminder
                    </button>
                  )}
                  {/* Cancel is ABSENT for a student, not disabled. */}
                  {isRep && !archived && event.status !== 'CANCELLED' && (
                    <button type="button" className="btn btn--danger" disabled={busy}
                            onClick={() => setConfirmCancel(true)}>Cancel event</button>
                  )}
                </div>

                {reminder && (
                  <form onSubmit={createReminder} className="stack"
                        style={{ marginTop: 'var(--s4)' }}>
                    <Field id="r-title" label="Reminder title" required
                           value={reminder.title} disabled={busy}
                           onChange={(e) => setReminder({ ...reminder, title: e.target.value })} />
                    <Field id="r-when" label="Remind me at" type="datetime-local" required
                           value={reminder.remind_at} disabled={busy}
                           onChange={(e) => setReminder({ ...reminder, remind_at: e.target.value })} />
                    <div className="row-x stackable">
                      <button type="submit" className="btn btn--primary" disabled={busy}>
                        Create reminder
                      </button>
                      <button type="button" className="btn btn--quiet" disabled={busy}
                              onClick={() => setReminder(null)}>No thanks</button>
                    </div>
                  </form>
                )}

                {/* C·2 — personal completion, in its own labelled row, separated
                    from the official fields. Never the header chip. A completion
                    recorded before a cancellation is still shown - it is still
                    true - but a cancelled event offers no way to complete it. */}
                {(canComplete || event.completed) && (
                  <div style={{
                    marginTop: 'var(--s5)', paddingTop: 'var(--s3)',
                    borderTop: '1px solid var(--line)',
                  }}>
                    <span className="t-label">Your progress</span>
                    <p className="t-meta" style={{ marginTop: 2 }}>
                      {event.completed ? <Completion done /> : 'Not marked complete.'}
                    </p>
                    {canComplete && (
                      <>
                        <div className="row-x" style={{ marginTop: 'var(--s3)' }}>
                          <button type="button" className="btn btn--secondary" disabled={busy}
                                  onClick={() => run(
                                    () => api.post(`/events/${event.id}/complete`,
                                                   { complete: !event.completed }),
                                    event.completed
                                      ? 'No longer marked complete.'
                                      : 'Marked complete. Only you can see this.')}>
                            {event.completed ? 'Mark not complete' : 'Mark complete'}
                          </button>
                        </div>
                        <p className="t-meta" style={{ marginTop: 'var(--s2)' }}>
                          This does not change the official record and nobody else can see it.
                        </p>
                      </>
                    )}
                  </div>
                )}
              </>
            )}
          </Panel>

          {/* ── Supporting material (optional) ─────────────────────────
              The original brief, when the lecturer gave one as a file. It
              sits BESIDE the record above, never in place of it: the record
              is what is dated, searchable and remindable; this is what stops
              a student hunting through WhatsApp in week nine.

              For a student with nothing attached this whole panel is absent -
              an empty "no attachments" box would imply something is missing
              from a record that is complete. A rep always sees it, because a
              rep is the person who can add one. */}
          {(materials.length > 0 || (isRep && !archived)) && (
            <Panel title="Supporting material">
              {materials.length === 0 ? (
                <p className="prose">
                  Nothing attached, and nothing needs to be. Add the original
                  paper only if the lecturer gave this out as a file.
                </p>
              ) : (
                <ul className="matlist">
                  {materials.map((file) => (
                    <li key={file.id} className="matrow">
                      <span className="matrow__icon" aria-hidden="true">
                        <IconPaperclip size={16} />
                      </span>
                      <span className="matrow__body">
                        <span className="matrow__name">{file.filename}</span>
                        <span className="matrow__meta mono">{fileSize(file.byte_size)}</span>
                      </span>
                      <span className="matrow__side">
                        {/* Two separate acts. Viewing is the common one - a
                            student checking what question 3 says - and it now
                            happens here rather than in the downloads folder.
                            Saving is still one click away, and is the only
                            option for a format no browser can render. */}
                        {canPreview(file.content_type) && (
                          <button type="button" className="btn btn--secondary btn--sm"
                                  onClick={() => setViewing(file)}>
                            View
                          </button>
                        )}
                        <button type="button" className="btn btn--secondary btn--sm"
                                disabled={busy}
                                onClick={() => run(
                                  () => api.download(
                                    `/events/${event.id}/attachments/${file.id}`,
                                    file.filename), null)}>
                          Download
                        </button>
                        {isRep && !archived && (
                          <button type="button" className="btn btn--danger btn--sm"
                                  disabled={busy}
                                  onClick={() => run(
                                    () => api.del(
                                      `/events/${event.id}/attachments/${file.id}`),
                                    'Supporting material removed.')}>
                            Remove
                          </button>
                        )}
                      </span>
                    </li>
                  ))}
                </ul>
              )}

              {isRep && !archived && (
                <form className="matadd" onSubmit={attachFile}>
                  <Field id="material" label="Add supporting material (optional)"
                         hint="An image, PDF, or document, if the original was given in
                               that format. You can publish without one.">
                    {(props) => (
                      <input {...props} type="file" disabled={busy}
                             onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
                    )}
                  </Field>
                  <button type="submit" className="btn btn--secondary"
                          disabled={busy || !file}>
                    {busy ? 'Uploading…' : 'Add attachment'}
                  </button>
                </form>
              )}
            </Panel>
          )}
        </div>

        <div className="stack">
          <Board title="What changed">
            {history.length === 0 ? (
              <EmptyState title="No changes yet"
                          message="Nothing has changed since this was published." />
            ) : [...history].reverse().map((change) => (
              <HistoryRow key={change.id} change={change} eventType={event.event_type} />
            ))}
          </Board>

          {event.original_message && (
            <Panel title="Original message">
              <details>
                <summary className="t-label" style={{ cursor: 'pointer' }}>
                  Show original message
                </summary>
                <blockquote className="quote" style={{ marginTop: 'var(--s2)' }}>
                  {event.original_message}
                </blockquote>
              </details>
            </Panel>
          )}
        </div>
      </div>

      {viewing && (
        <AttachmentViewer file={viewing} onClose={() => setViewing(null)}
                          path={`/events/${event.id}/attachments/${viewing.id}`} />
      )}

      {confirmCancel && (
        <Modal title={`Cancel ${event.title}?`}
               onClose={() => setConfirmCancel(false)}
               actions={<>
                 <button type="button" className="btn btn--secondary"
                         onClick={() => setConfirmCancel(false)}>Keep it</button>
                 <button type="button" className="btn btn--danger" disabled={busy}
                         onClick={async () => {
                           const ok = await run(
                             () => api.post(`/events/${event.id}/cancel`,
                                            { expected_version: event.version }),
                             'Cancelled by you. Enrolled students have been notified.');
                           setConfirmCancel(false);
                           if (ok) navigate(`/events/${event.id}`, { replace: true });
                         }}>
                   Yes, cancel it
                 </button>
               </>}>
          <Notice tone="crit" label="Students will be notified">
            <ul>
              <li>Every student enrolled on this course is notified.</li>
              <li>The record is kept and marked cancelled — history is never deleted.</li>
              <li>Reminders linked to it are cancelled.</li>
            </ul>
          </Notice>
        </Modal>
      )}
    </div>
  );
}
