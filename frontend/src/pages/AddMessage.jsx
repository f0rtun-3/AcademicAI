// S13 · Add message → proposal review (spec 14, 28).
//
// THE PRODUCT'S CENTRAL PRINCIPLE, MADE VISIBLE:
//
//   AI proposes → a human rep reviews → the backend authorizes → the database
//   becomes truth.
//
// Publish is always a human action with a human name on it, and the
// confirmation says so. No screen, label or animation may suggest that
// AcademicAI published anything.
//
// CLARIFICATION and DUPLICATE have NO publish control - absent, not disabled.
// A disabled control invites guessing at how to enable it. A student's path
// has no publish control at all, for the same reason.

import { useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api/client.js';
import { useAuth } from '../auth/AuthContext.jsx';
import { useResource } from '../components/useResource.js';
import { ErrorBanner, Loading, SuccessBanner, errorText } from '../components/States.jsx';
import { Field, Notice, PageHeader, Panel, StateChip, longDate } from '../components/ui.jsx';
import {
  EVENT_TYPES as TYPES, confidenceWords, dayLong, describeFieldChanges, eventTypeLabel,
} from '../lib/vocabulary.js';

function Proposal({ proposal, isRep, onPublish, onDiscard, publishing, publishError,
                    staged, onStage }) {
  const [edited, setEdited] = useState(proposal);
  const [editing, setEditing] = useState(false);

  // Absent, not disabled.
  const canPublish = isRep && proposal.publishable;

  return (
    <Panel className="stack">
      {/* What kind of proposal this is, and how sure the reading is - in
          words. The percentage stays in the data; a student reads what it
          means for them. */}
      <div className="panel__head">
        <StateChip value={proposal.action} context="proposal" />
        {confidenceWords(proposal.confidence) && (
          <span className="t-meta">{confidenceWords(proposal.confidence)}</span>
        )}
      </div>

      <p className="t-body">{proposal.explanation}</p>

      {proposal.needs_clarification && proposal.clarification_question && (
        <Notice tone="warn" label="Needs clarification" role="status">
          {proposal.clarification_question}
        </Notice>
      )}

      {proposal.discrepancies?.length > 0 && (
        <Notice tone="warn" label="Check these details" role="alert">
          <ul>{proposal.discrepancies.map((d) => <li key={d}>{d}</li>)}</ul>
        </Notice>
      )}

      <dl className="kv" style={{ marginTop: 'var(--s4)' }}>
        <dt>Course</dt><dd className="mono">{proposal.course_code ?? 'Not specified'}</dd>
        <dt>Type</dt>
        <dd>{proposal.event_type ? eventTypeLabel(proposal.event_type) : 'Not specified'}</dd>
        <dt>Title</dt><dd>{edited.title ?? 'Not specified'}</dd>
        {edited.description && (
          <><dt>Instructions</dt><dd className="evdesc-inline">{edited.description}</dd></>
        )}
        <dt>Date</dt><dd>{edited.event_date ? longDate(edited.event_date) : 'Not specified'}</dd>
        <dt>Time</dt><dd>{edited.event_time ?? 'Not specified'}</dd>
        <dt>Venue</dt><dd>{edited.venue ?? 'Not specified'}</dd>
        {proposal.day_of_week && (<><dt>Day</dt><dd>{dayLong(proposal.day_of_week)}</dd></>)}
      </dl>

      {proposal.matched_record && (
        <div style={{ marginTop: 'var(--s4)' }}>
          <span className="t-label">Matches an existing record</span>
          {/* The record's name - never its version number, which is how the
              backend guards against overwriting a newer change, not something
              a person needs to read. */}
          <p className="t-meta">
            {proposal.matched_record.title
              ?? (proposal.matched_record.day_of_week
                ? `The ${dayLong(proposal.matched_record.day_of_week)} class` : 'An existing record')}
          </p>
          {proposal.old_value && proposal.new_value && (
            <ul className="chdetails t-meta">
              {describeFieldChanges(proposal.old_value, proposal.new_value, proposal.event_type)
                .map((line) => <li key={line}>{line}</li>)}
            </ul>
          )}
        </div>
      )}

      {!isRep && (
        <Notice tone="info" label="Personal interpretation" style={{ marginTop: 'var(--s4)' }}>
          {proposal.note ?? 'Only a verified course rep can publish official information.'}
        </Notice>
      )}

      {isRep && (
        <>
          <ErrorBanner message={publishError} />
          {editing && (
            <div className="form-grid form-grid--2" style={{ marginTop: 'var(--s4)' }}>
              <Field id="p-title" label="Title" value={edited.title ?? ''}
                     onChange={(e) => setEdited({ ...edited, title: e.target.value })} />
              {/* Typed instructions, added at review time rather than in a
                  separate form: the message a rep pasted is rarely the whole
                  brief. Optional - leaving it empty publishes exactly as
                  before. */}
              <Field id="p-description" label="Instructions (optional)"
                     hint="What the work is. Students see this on the record.">
                {(props) => (
                  <textarea {...props} rows={4} value={edited.description ?? ''}
                            onChange={(e) => setEdited(
                              { ...edited, description: e.target.value || null })} />
                )}
              </Field>
              <Field id="p-date" label="Date" placeholder="YYYY-MM-DD"
                     value={edited.event_date ?? ''}
                     onChange={(e) => setEdited({ ...edited, event_date: e.target.value || null })} />
              <Field id="p-venue" label="Venue" value={edited.venue ?? ''}
                     onChange={(e) => setEdited({ ...edited, venue: e.target.value || null })} />
            </div>
          )}
          {/* ── Supporting material (optional) ───────────────────────────
              The original brief, when the lecturer handed one out as a photo
              or a document. It sits here, beside Confirm & Publish, because
              this is where the record being created is shown.

              It is STAGED, not uploaded: an attachment needs an event to
              belong to, and the event does not exist until the rep publishes.
              So the file is held, the record is published first, and the file
              follows. If the upload then fails the record is still published -
              publishing is never blocked by, or rolled back for, an optional
              file. */}
          {canPublish && (
            <div className="matadd" style={{ marginTop: 'var(--s4)' }}>
              <Field id="p-material" label="Supporting material (optional)"
                     hint={`Attach an image, PDF, or document if the original was
                            given in that format. You can publish without one.`}>
                {(props) => (
                  <input {...props} type="file" disabled={publishing}
                         onChange={(e) => onStage(e.target.files?.[0] ?? null)} />
                )}
              </Field>
              {staged && (
                <p className="prose">
                  <strong>{staged.name}</strong> will be attached once this is
                  published.{' '}
                  <button type="button" className="linkish"
                          onClick={() => onStage(null)}>Remove it</button>
                </p>
              )}
            </div>
          )}

          <div className="row-x stackable" style={{ marginTop: 'var(--s4)' }}>
            {canPublish && (
              <button type="button" className="btn btn--primary" disabled={publishing}
                      onClick={() => onPublish(edited)}>
                {publishing ? 'Publishing…' : 'Confirm & Publish'}
              </button>
            )}
            {/* C·11 — Edit is a real path a rep takes often, not a quiet
                afterthought, so it keeps secondary weight. */}
            <button type="button" className="btn btn--secondary"
                    onClick={() => setEditing((v) => !v)}>
              {editing ? 'Done editing' : 'Edit'}
            </button>
            <button type="button" className="btn btn--quiet" onClick={onDiscard}>Discard</button>
          </div>
          {!canPublish && (
            <Notice tone="warn" label="Not publishable" style={{ marginTop: 'var(--s3)' }}>
              {proposal.action === 'DUPLICATE'
                ? 'An existing record already says this, so there is nothing to publish.'
                : 'This proposal cannot be published as it stands. Answer the clarification '
                  + 'above and analyse the message again.'}
            </Notice>
          )}
        </>
      )}
    </Panel>
  );
}

// Shown in the review column while there is nothing to review.
//
// Not decoration: it sets the expectation BEFORE the AI returns anything, so a
// rep reading a proposal for the first time already knows the AI has not done
// anything yet, and a student already knows why they will see no publish
// control. The wording matches the landing page's trust chain deliberately.
function ProposalExplainer({ isRep }) {
  return (
    <Panel title="What happens next" className="stack">
      <ol className="flowlist">
        <li>
          <span className="flowlist__n">1</span>
          <div>
            <strong>AcademicAI reads it</strong>
            <p className="t-meta">
              It extracts a date, time, venue and course where it can, and marks
              anything it could not find as not specified.
            </p>
          </div>
        </li>
        <li>
          <span className="flowlist__n">2</span>
          <div>
            <strong>It proposes, it does not publish</strong>
            <p className="t-meta">
              You get a draft record to check. Nothing has been saved and nobody
              has been notified at this point.
            </p>
          </div>
        </li>
        <li>
          <span className="flowlist__n">3</span>
          <div>
            <strong>{isRep ? 'You confirm it' : 'A course rep confirms it'}</strong>
            <p className="t-meta">
              {isRep
                ? 'Publishing is your action, and the record says it was published '
                  + 'by you. AcademicAI checks that you are still a verified rep at '
                  + 'that moment.'
                : 'Only a verified course representative can publish official '
                  + 'information, so you will get a personal reading instead.'}
            </p>
          </div>
        </li>
      </ol>
      <Notice tone="info" label="Why it works this way">
        An assistant that could publish on its own would make every official
        record only as reliable as its worst reading.
      </Notice>
    </Panel>
  );
}

// The backend's course_service._clean_code, mirrored so the client can tell
// whether what was typed names a course the community already has:
//
//     code.strip().upper().replace(" ", "")
//
// This is NOT a second matching rule. The client uses it only to decide what
// to SHOW and which field to send; the backend re-resolves the code inside the
// writing transaction and its refusal is what the rep reads (C·3, C·9).
function normaliseCode(value) {
  return String(value || '').trim().toUpperCase().replace(/ /g, '');
}

export default function AddMessage() {
  const { isRep, user } = useAuth();
  const courses = useResource(() => api.get('/community/courses'));
  const [form, setForm] = useState({
    message: '', information_type: '', course: '', context: '',
    event_date: '', event_time: '', venue: '',
    no_date: false, no_time: false, no_venue: false,
  });
  const [proposal, setProposal] = useState(null);
  const [error, setError] = useState(null);
  const [publishError, setPublishError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [busy, setBusy] = useState(false);
  const [publishing, setPublishing] = useState(false);
  // The file a rep chose before publishing. It cannot be uploaded yet: an
  // attachment belongs to an event, and the event does not exist until the
  // proposal is published.
  const [staged, setStaged] = useState(null);
  // Reported at PAGE level, not inside the proposal panel: that panel is
  // unmounted the moment the record is published, which is exactly when this
  // message has something to say.
  const [attachWarning, setAttachWarning] = useState(null);

  function update(field, value) {
    setForm((prev) => ({ ...prev, [field]: value }));
  }

  // The community's published course list, and what the typed code resolves
  // to within it. An unmatched code is not an error here — the field is free
  // text on purpose — but for a rep it will be refused at publish, so it is
  // worth saying so before they get there.
  const known = courses.status === 'ready' ? (courses.data.courses ?? []) : [];
  const typedCode = normaliseCode(form.course);
  const matched = typedCode
    ? known.find((c) => normaliseCode(c.code) === typedCode) ?? null
    : null;
  const unknownCourse = Boolean(typedCode && !matched);

  async function analyse(event) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setProposal(null);
    setNotice(null);
    setAttachWarning(null);
    try {
      const payload = {
        message: form.message,
        context: form.context || undefined,
        information_type: form.information_type || undefined,
        // /ai/analyze-message takes an id, not a code: the selected course only
        // biases which of the community's existing events the AI is shown, so
        // an unmatched code has nothing to bias and is left out.
        course_id: matched ? matched.id : undefined,
        event_date: form.no_date ? undefined : form.event_date || undefined,
        event_time: form.no_time ? undefined : form.event_time || undefined,
        venue: form.no_venue ? undefined : form.venue || undefined,
        no_date: form.no_date, no_time: form.no_time, no_venue: form.no_venue,
      };
      const response = await api.post('/ai/analyze-message', payload);
      setProposal(response.proposal);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  async function publish(edited) {
    setPublishing(true);
    setPublishError(null);
    try {
      const result = await api.post('/ai/publish', {
        action: proposal.action,
        scope: proposal.scope,
        target_id: proposal.possible_match_id,
        expected_version: proposal.expected_version,
        // What the rep typed beats what the AI read out of the message: they
        // have just stated the course explicitly. The backend still has to
        // resolve it against the community's list and refuses if it cannot.
        course_code: typedCode || proposal.course_code,
        event_type: proposal.event_type,
        day_of_week: proposal.day_of_week,
        original_message: proposal.original_message,
        title: edited.title,
        description: edited.description ?? null,
        event_date: edited.event_date,
        event_time: edited.event_time,
        venue: edited.venue,
      });
      // The record is official from this moment. The optional file follows
      // it, and a failure there is reported WITHOUT implying the publish
      // failed - because it did not.
      let published = 'Published by you'
        + (user?.full_name ? ` (${user.full_name})` : '')
        + '. Enrolled students have been notified.';
      const eventId = result?.published?.event?.id;
      if (staged && eventId) {
        try {
          const upload = new FormData();
          upload.append('file', staged);
          await api.postForm(`/events/${eventId}/attachments`, upload);
          published += ` ${staged.name} is attached.`;
        } catch (uploadError) {
          setAttachWarning(
            `The record was published, but ${staged.name} could not be attached: `
            + `${errorText(uploadError)} Open the event to try again.`);
        }
      } else if (staged && !eventId) {
        // An UPDATE or CANCEL has no new record to hold a file.
        setAttachWarning(
          `The change was published. ${staged.name} was not attached, because `
          + 'material is attached to a record rather than to a change. Open the '
          + 'event to add it.');
      }
      setNotice(published);
      setProposal(null);
      setStaged(null);
      setForm((prev) => ({ ...prev, message: '' }));
    } catch (err) {
      setPublishError(
        err.code === 'stale_proposal'
          // Never a force-overwrite option: re-analysis is the only way on.
          ? 'This record changed while you were reviewing. Analyse the message again.'
          : err,
      );
    } finally {
      setPublishing(false);
    }
  }

  return (
    <div className="stack stack--loose">
      {/* The eyebrow states whose screen this is, because the page does two
        * different jobs: a rep publishes from it, a student only gets a
        * personal reading. That difference is the first thing to establish. */}
      <PageHeader
        eyebrow={isRep ? 'Publishing' : 'Personal interpretation'}
        title="Add message"
        lede={isRep
          ? 'Paste the message exactly as you received it. AcademicAI proposes an '
            + 'action; nothing is published until you confirm.'
          : 'Paste a message to have it interpreted for you. This creates personal '
            + 'notes only.'} />

      <SuccessBanner message={notice} onDismiss={() => setNotice(null)} />
      <ErrorBanner message={error} onDismiss={() => setError(null)} />
      {/* The publish succeeded; only the optional file did not. A warning, not
          an error, because calling it an error invites the rep to publish the
          same record a second time. */}
      {attachWarning && (
        <Notice tone="warn" label="Published, but not attached" role="status">
          {attachWarning}
        </Notice>
      )}

      <div className="split">
        {/* Desktop keeps the message visible while the proposal is reviewed. */}
        <Panel title="Paste what you were told">
          <form className="stack" onSubmit={analyse}>
            <Field id="message" label="Original message" required
                   className="field--composer">
              {(props) => (
                <textarea {...props} required rows={6} value={form.message}
                          onChange={(e) => update('message', e.target.value)} />
              )}
            </Field>

            <Field id="information_type" label="Information type">
              {(props) => (
                <select {...props} value={form.information_type}
                        onChange={(e) => update('information_type', e.target.value)}>
                  <option value="">Let AcademicAI decide</option>
                  {TYPES.map((type) => (
                    <option key={type} value={type}>{eventTypeLabel(type)}</option>
                  ))}
                </select>
              )}
            </Field>

            {/* TYPE the course code; the published list is offered as
                suggestions rather than as the only choice.

                It was a <select> whose only option, in a community whose rep
                has not published a course list, was "No specific course" — a
                control with nothing in it and no explanation of why. A code is
                something the person pasting the message already knows, so the
                field now accepts it directly and the list assists instead of
                gating. `list=` keeps it a native combobox: the suggestions
                open with the keyboard and the input is still just an input. */}
            <Field id="course" label="Course"
                   hint={courses.status !== 'ready' ? undefined
                     : known.length
                       ? 'Type a code such as COS202, or pick one from your community’s list.'
                       : 'Your community has no published course list yet. You can still type '
                         + 'a code.'}>
              {(props) => (
                <>
                  <input {...props} type="text" autoComplete="off"
                         list="course-codes" placeholder="e.g. COS202"
                         value={form.course}
                         onChange={(e) => update('course', e.target.value)} />
                  <datalist id="course-codes">
                    {known.map((course) => (
                      <option key={course.id} value={course.code}>{course.title ?? ''}</option>
                    ))}
                  </datalist>
                </>
              )}
            </Field>

            {/* A rep's publish will be refused by the backend if the code is
                not in the community's list, because a course is a rep-curated
                record and an event may only point at one that exists. Said
                here rather than discovered after writing the whole thing.
                It WARNS and does not block: the client is not the authority on
                what the registry contains (C·3). */}
            {isRep && unknownCourse && (
              <Notice tone="warn" label="Not in your course list" role="status">
                {typedCode} is not a course in this community yet. Add it under{' '}
                <Link className="linkish" to="/community/manage">Manage → Courses</Link> first,
                or clear this field to publish without a course.
              </Notice>
            )}

            {/* "Not specified" is an explicit control, never an empty field the
                user must infer: the backend treats an explicit null as a real
                answer, so the form offers it as one (spec 14). */}
            <Field id="event_date" label="Date" placeholder="YYYY-MM-DD"
                   disabled={form.no_date} value={form.event_date}
                   onChange={(e) => update('event_date', e.target.value)} />
            <label className="check">
              <input type="checkbox" checked={form.no_date}
                     onChange={(e) => update('no_date', e.target.checked)} />
              No specified date
            </label>

            <Field id="event_time" label="Time" placeholder="HH:MM"
                   disabled={form.no_time} value={form.event_time}
                   onChange={(e) => update('event_time', e.target.value)} />
            <label className="check">
              <input type="checkbox" checked={form.no_time}
                     onChange={(e) => update('no_time', e.target.checked)} />
              No specified time
            </label>

            <Field id="venue" label="Venue" disabled={form.no_venue} value={form.venue}
                   onChange={(e) => update('venue', e.target.value)} />
            <label className="check">
              <input type="checkbox" checked={form.no_venue}
                     onChange={(e) => update('no_venue', e.target.checked)} />
              No specified venue
            </label>

            <Field id="context" label="Extra context (optional)" value={form.context}
                   onChange={(e) => update('context', e.target.value)} />

            <button type="submit" className="btn btn--primary" disabled={busy}>
              {busy ? 'Analysing…' : 'Analyse message'}
            </button>
          </form>
        </Panel>

        <div className="stack">
          {busy && <Loading label="AcademicAI is reading the message…" rows={2} />}
          {proposal && (
            <Proposal proposal={proposal} isRep={isRep} publishing={publishing}
                      publishError={publishError}
                      staged={staged} onStage={setStaged}
                      onPublish={publish} onDiscard={() => setProposal(null)} />
          )}
          {/* Before anything has been analysed this column would be empty, so
              it carries the one thing worth reading first: who actually decides.
              It is the product's central claim and this is the screen it
              applies to, so it is stated here rather than only on marketing. */}
          {!busy && !proposal && <ProposalExplainer isRep={isRep} />}
        </div>
      </div>
    </div>
  );
}
